import type { Ref } from 'vue'
import type { Profile } from 'wlipsync'

import type { VowelSlot } from '../../constants/morphs'
import type { MorphController } from './morph'

import { useAsyncState } from '@vueuse/core'
import { onUnmounted, watch } from 'vue'
import { createWLipSyncNode } from 'wlipsync'

import profile from '../../assets/lip-sync-profile.json' with { type: 'json' }

// NOTICE:
// Cross-package source import (no package.json dependency) to reach the shared
// AudioContext. Root cause: the audio context is owned by `@proj-airi/stage-ui`,
// which in turn depends on this package, so adding it as a dependency would
// create a cycle. The VRM renderer reaches the same store the same way.
// Source: packages/stage-ui-three/src/composables/vrm/lip-sync.ts.
// Removal condition: the AudioContext provider moves to a dependency-free
// shared package both renderers can import.
import { useAudioContext } from '../../../../stage-ui/src/stores/audio'

/** wLipSync emits 6 visemes; we fold the sibilant `S` into `I`. */
const RAW_KEYS = ['A', 'E', 'I', 'O', 'U', 'S'] as const
type LipKey = 'A' | 'E' | 'I' | 'O' | 'U'
const LIP_KEYS: LipKey[] = ['A', 'E', 'I', 'O', 'U']

/** Maps wLipSync visemes onto the MMD vowel morph slots (あいうえお). */
const LIP_TO_SLOT: Record<LipKey, VowelSlot> = {
  A: 'vowelA',
  E: 'vowelE',
  I: 'vowelI',
  O: 'vowelO',
  U: 'vowelU',
}
const RAW_TO_LIP: Record<typeof RAW_KEYS[number], LipKey> = {
  A: 'A',
  E: 'E',
  I: 'I',
  O: 'O',
  U: 'U',
  S: 'I',
}

const ATTACK = 50 // approach speed toward the next mouth shape
const RELEASE = 30 // decay speed when a shape ends
const CAP = 0.7 // max morph weight, mirrors the VRM tuning
const SILENCE_VOL = 0.04
const SILENCE_GAIN = 0.05

/**
 * One server-side viseme event from the BetterAgent TTS pipeline, timed on the
 * shared AudioContext clock. `shape` is one of aa/ee/ih/oh/ou.
 */
export interface VisemeEvent {
  /** AudioContext-clock time, kept for the Live2D path. */
  absTime: number
  /** Same event on the wall clock (performance.now()/1000); used here so the
   *  timeline stays comparable even if this package ends up with its own
   *  AudioContext instance. */
  wallTime: number
  shape: string
}

/**
 * One ~50ms RMS frame of an audio buffer the stage has scheduled, on the wall
 * clock. Computed by Stage.vue from the decoded AudioBuffers themselves, so it
 * always matches what actually plays -- unlike Web Audio analyser graphs,
 * which read pure silence in this environment (dead-end branches skipped /
 * cross-context connects).
 */
export interface EnvelopeEvent {
  wallTime: number
  rms: number
}

/** BetterAgent viseme shape -> MMD vowel key. */
const VISEME_SHAPE_TO_LIP: Record<string, LipKey> = {
  aa: 'A',
  ee: 'E',
  ih: 'I',
  oh: 'O',
  ou: 'U',
}

/**
 * Cutscene-style target weights per vowel shape: `aa` opens wide, `ih`/`ee`
 * barely move the lips, rounded vowels sit in between. Kept below 1.0 because
 * the MMD vowel morphs are already full-shape and full weight gapes.
 */
const VISEME_SHAPE_TARGET: Record<string, number> = {
  aa: 0.9,
  ee: 0.55,
  ih: 0.45,
  oh: 0.8,
  ou: 0.65,
}

// Discrete per-syllable switching (cutscene-like), but not twitchy: shapes
// resolve quickly (ATTACK) and relax a bit slower (RELEASE) so consonants
// between vowels do not slam the mouth shut.
const VISEME_ATTACK = 65
const VISEME_RELEASE = 32
// Start each shape this many seconds before its exact audio time -- a small
// lead reads as natural anticipation instead of lag, like hand-animated
// cutscene mouths.
const VISEME_LEAD = 0.04
// Never re-shape faster than this; rapid syllable turns otherwise produce a
// jittery, mechanical flap instead of readable mouth movement.
const VISEME_MIN_HOLD = 0.09

/**
 * Audio-driven mouth animation for MMD models.
 *
 * Reuses the exact wLipSync profile and winner/runner blending strategy as
 * the VRM renderer (only the two strongest visemes are mixed, so the wide
 * "A" shape does not dominate), but writes the result to MMD vowel morphs
 * through a {@link MorphController} instead of VRM expressions.
 *
 * Returns an `update(delta)` to call once per frame, after the animation
 * helper has run, so lip-sync wins over any VMD mouth keyframes.
 */
export function useMMDLipSync(audioNode: Ref<AudioBufferSourceNode | undefined>, context?: AudioContext) {
  const { audioContext: storeContext } = useAudioContext()
  // Prefer the caller-supplied AudioContext (the one the stage actually plays
  // through). Falling back to this package's store instance can silently end
  // up on a second AudioContext, where connect() from the playback sources
  // throws and the analyser never sees any signal.
  const ctx = context ?? storeContext
  const { state: lipSyncNode, isReady } = useAsyncState(createWLipSyncNode(ctx, profile as Profile), undefined)
  // Guaranteed-to-work fallback driver: raw RMS envelope. Lazily created on
  // the FIRST audio source's own AudioContext -- creating it on this package's
  // store context could land on a second AudioContext, where connect() from
  // the playback sources throws and the analyser stays silent forever
  // (observed as worklet=true vol=0.000 rms=0.000 while audio is audible).
  let analyser: AnalyserNode | undefined
  let analyserSink: GainNode | undefined
  let timeData: Uint8Array<ArrayBuffer> | undefined

  function ensureAnalyser(context: BaseAudioContext) {
    if (analyser && analyser.context === context)
      return
    analyser = context.createAnalyser()
    analyser.fftSize = 1024
    timeData = new Uint8Array(new ArrayBuffer(analyser.fftSize))
    // NOTICE:
    // A zero-gain sink into the destination is REQUIRED here. An analyser
    // that is only fed by a source and has no path to the destination is a
    // dead-end branch: browsers are then free to skip processing it, and it
    // reads pure silence forever (observed live: attached=28 sources audibly
    // playing while getByteTimeDomainData() returned all 128s). The gain is
    // 0, so this path is inaudible and cannot double the audio.
    // Removal condition: never -- re-verify analyser readings if this is
    // ever deleted.
    analyserSink = context.createGain()
    analyserSink.gain.value = 0
    analyser.connect(analyserSink)
    analyserSink.connect(context.destination)
  }

  // Same dead-end problem for the wLipSync worklet node: give it its own
  // silent path to the destination so browsers keep processing it.
  const workletSink = ctx.createGain()
  workletSink.gain.value = 0
  workletSink.connect(ctx.destination)

  const smoothState: Record<LipKey, number> = { A: 0, E: 0, I: 0, O: 0, U: 0 }
  // Cursor into the server viseme timeline, plus the length seen last frame so
  // a barge-in reset (parent clears the array in place) restarts the cursor.
  let visemeCursor = 0
  let visemeScheduleLength = 0
  // Same bookkeeping for the RMS-envelope timeline (audio mode).
  let envelopeCursor = 0
  let envelopeScheduleLength = 0
  // Currently displayed shape and when it was entered, for the min-hold guard.
  let activeShape = ''
  let lastShapeSwitchAt = 0

  watch([isReady, audioNode], ([ready, newAudioNode], [, oldAudioNode]) => {
    // Disconnect ONLY the edges into the analysers, never the bare
    // disconnect() -- that would also tear down the source's connection to
    // ctx.destination and silence any chunk still queued for playback
    // (BetterAgent audio chunks are scheduled back-to-back and arrive much
    // faster than they play).
    if (oldAudioNode && oldAudioNode !== newAudioNode) {
      for (const dest of [lipSyncNode.value, analyser]) {
        if (!dest)
          continue
        try {
          oldAudioNode.disconnect(dest)
        }
        catch {}
      }
    }
    if (!newAudioNode)
      return
    ensureAnalyser(newAudioNode.context)
    if (ready && lipSyncNode.value) {
      try {
        newAudioNode.connect(lipSyncNode.value)
      }
      catch {}
    }
    if (analyser) {
      try {
        newAudioNode.connect(analyser)
      }
      catch (err) {
        console.warn('[mmd-lipsync] failed to connect source to RMS analyser', err)
      }
    }
  }, { immediate: true })

  watch([isReady, lipSyncNode], ([ready, node]) => {
    if (ready && node) {
      try {
        node.connect(workletSink)
      }
      catch {}
    }
  }, { immediate: true })

  onUnmounted(() => {
    const node = audioNode.value
    if (node) {
      for (const dest of [lipSyncNode.value, analyser]) {
        if (!dest)
          continue
        try {
          node.disconnect(dest)
        }
        catch {}
      }
    }
    attachedNodes.clear()
  })

  // Additional sources connected straight to the analyser. BetterAgent audio
  // arrives as dozens of pre-scheduled chunks; the single-audioNode prop above
  // can only ever hold the last one, so audio-driven mode would otherwise
  // analyse silence until the final chunk starts. Stage.vue attaches every
  // chunk it schedules, and each node drops itself when playback ends.
  const attachedNodes = new Set<AudioBufferSourceNode>()

  function attachAudioNode(node: AudioBufferSourceNode) {
    if (attachedNodes.has(node))
      return
    attachedNodes.add(node)
    // Analyse on the source's own context so the connection can never be a
    // cross-context no-op.
    ensureAnalyser(node.context)
    if (lipSyncNode.value) {
      try {
        node.connect(lipSyncNode.value)
      }
      catch {}
    }
    if (analyser) {
      try {
        node.connect(analyser)
      }
      catch (err) {
        console.warn('[mmd-lipsync] failed to connect chunk to RMS analyser', err)
      }
    }
    node.addEventListener('ended', () => attachedNodes.delete(node), { once: true })
  }

  function update(morphs: MorphController | undefined, delta = 0.016) {
    if (!morphs)
      return

    const target: Record<LipKey, number> = { A: 0, E: 0, I: 0, O: 0, U: 0 }
    let active = false

    // 1) Formant analysis, when the wLipSync worklet is live and has signal.
    const node = lipSyncNode.value
    if (node) {
      const vol = node.volume ?? 0
      const amp = Math.min(vol * 0.9, 1) ** 0.7
      if (amp >= SILENCE_VOL) {
        // Project the 6 raw visemes down to 5 vowels, scaled by amplitude.
        const projected: Record<LipKey, number> = { A: 0, E: 0, I: 0, O: 0, U: 0 }
        for (const raw of RAW_KEYS) {
          const lip = RAW_TO_LIP[raw]
          projected[lip] = Math.max(projected[lip], (node.weights[raw] ?? 0) * amp)
        }

        // Only blend the two strongest vowels. Mixing all five biases toward
        // the wide "A" shape because it has the largest deformation.
        let winner: LipKey = 'I'
        let runner: LipKey = 'E'
        let winnerVal = -Infinity
        let runnerVal = -Infinity
        for (const key of LIP_KEYS) {
          const val = projected[key]
          if (val > winnerVal) {
            runnerVal = winnerVal
            runner = winner
            winnerVal = val
            winner = key
          }
          else if (val > runnerVal) {
            runnerVal = val
            runner = key
          }
        }

        if (winnerVal >= SILENCE_GAIN) {
          target[winner] = Math.min(CAP, winnerVal)
          target[runner] = Math.min(CAP * 0.5, runnerVal * 0.6)
          active = true
        }
      }
    }

    // 2) RMS-envelope fallback: guarantees visible movement on any audible
    // signal even if the formant worklet never produced data (separate
    // AudioContext, worklet unavailable, ...). Openness drives the wide "A"
    // shape; the smoothing below supplies the continuous feel.
    if (!active && analyser && timeData) {
      analyser.getByteTimeDomainData(timeData)
      let sum = 0
      for (let i = 0; i < timeData.length; i++) {
        const v = (timeData[i] - 128) / 128
        sum += v * v
      }
      const rms = Math.sqrt(sum / timeData.length)
      const openness = Math.max(0, Math.min(1, (rms - 0.008) * 5)) * 0.85
      if (openness > 0.02) {
        target.A = openness
        active = true
      }
    }

    // No active signal -> targets stay zero, so the smoothing loop below
    // closes the mouth at the release rate (brief gaps between phrases).
    if (!active) {
      target.A = 0
      target.E = 0
      target.I = 0
      target.O = 0
      target.U = 0
    }

    for (const key of LIP_KEYS) {
      const from = smoothState[key]
      const to = target[key]
      const rate = 1 - Math.exp(-(to > from ? ATTACK : RELEASE) * delta)
      smoothState[key] = from + (to - from) * rate
      const weight = (smoothState[key] <= 0.01 ? 0 : smoothState[key]) * 0.7
      morphs.set(LIP_TO_SLOT[key], weight)
    }
  }

  /**
   * Drives the mouth from the RMS-envelope timeline (see EnvelopeEvent).
   * Audio mode's PRIMARY driver: the data is computed from the very buffers
   * the stage schedules, so it works regardless of how (or whether) Web Audio
   * analyser graphs are processed in the host environment -- which is exactly
   * what kept reading silence before.
   */
  function updateFromEnvelope(morphs: MorphController | undefined, schedule: readonly EnvelopeEvent[] | undefined, delta = 0.016): boolean {
    if (!morphs || !schedule || schedule.length === 0) {
      envelopeCursor = 0
      envelopeScheduleLength = 0
      return false
    }

    if (schedule.length < envelopeScheduleLength)
      envelopeCursor = 0
    envelopeScheduleLength = schedule.length

    const now = performance.now() / 1000
    const first = schedule[0]
    const last = schedule[schedule.length - 1]
    if (now < first.wallTime - 0.05 || now > last.wallTime + 0.3)
      return false

    while (envelopeCursor < schedule.length - 1 && schedule[envelopeCursor + 1].wallTime <= now)
      envelopeCursor++

    const rms = schedule[envelopeCursor].rms
    const openness = Math.max(0, Math.min(1, (rms - 0.008) * 6)) * 0.85

    const target: Record<LipKey, number> = { A: openness, E: 0, I: 0, O: 0, U: 0 }
    for (const key of LIP_KEYS) {
      const from = smoothState[key]
      const to = target[key]
      const rate = 1 - Math.exp(-(to > from ? ATTACK : RELEASE) * delta)
      smoothState[key] = from + (to - from) * rate
      const weight = (smoothState[key] <= 0.01 ? 0 : smoothState[key]) * 0.7
      morphs.set(LIP_TO_SLOT[key], weight)
    }
    return true
  }

  /**
   * Drives the mouth from the server-side viseme timeline (one event per
   * syllable, absolute AudioContext times) with discrete cutscene-style shape
   * switching. Returns `false` when the timeline has nothing for the current
   * moment, so the caller can fall back to the formant analyser (frontend TTS
   * path, or gaps between backend utterances).
   */
  function updateFromVisemes(morphs: MorphController | undefined, schedule: readonly VisemeEvent[] | undefined, delta = 0.016): boolean {
    if (!morphs || !schedule || schedule.length === 0) {
      visemeCursor = 0
      visemeScheduleLength = 0
      activeShape = ''
      lastShapeSwitchAt = 0
      return false
    }

    // The parent clears the array in place on barge-in/stop; a shorter array
    // than last frame means a fresh utterance started.
    if (schedule.length < visemeScheduleLength) {
      visemeCursor = 0
      activeShape = ''
      lastShapeSwitchAt = 0
    }
    visemeScheduleLength = schedule.length

    // Slight lead: shapes land a touch before the sound, which reads as
    // natural anticipation instead of the mouth trailing the audio.
    const now = performance.now() / 1000 - VISEME_LEAD
    const first = schedule[0]
    const last = schedule[schedule.length - 1]
    if (now < first.wallTime - 0.05 || now > last.wallTime + 0.4)
      return false

    while (visemeCursor < schedule.length - 1 && schedule[visemeCursor + 1].wallTime <= now)
      visemeCursor++

    // Min-hold guard: only re-shape once the previous shape has been visible
    // long enough, so closely-spaced syllables do not produce a twitch.
    const desiredShape = schedule[visemeCursor].shape
    if (desiredShape !== activeShape && (activeShape === '' || now - lastShapeSwitchAt >= VISEME_MIN_HOLD)) {
      activeShape = desiredShape
      lastShapeSwitchAt = now
    }

    const lip = VISEME_SHAPE_TO_LIP[activeShape] ?? 'A'
    const target: Record<LipKey, number> = { A: 0, E: 0, I: 0, O: 0, U: 0 }
    target[lip] = VISEME_SHAPE_TARGET[activeShape] ?? 0.6

    for (const key of LIP_KEYS) {
      const from = smoothState[key]
      const to = target[key]
      const rate = 1 - Math.exp(-(to > from ? VISEME_ATTACK : VISEME_RELEASE) * delta)
      smoothState[key] = from + (to - from) * rate
      morphs.set(LIP_TO_SLOT[key], smoothState[key] <= 0.01 ? 0 : smoothState[key])
    }
    return true
  }

  return {
    attachAudioNode,
    update,
    updateFromEnvelope,
    updateFromVisemes,
  }
}
