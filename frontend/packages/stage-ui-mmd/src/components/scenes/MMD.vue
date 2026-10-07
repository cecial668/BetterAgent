<script setup lang="ts">
/*
  * Root MMD scene component.
  *
  * Unlike the VRM renderer (which is declarative via TresJS), MMD is driven
  * imperatively: the MMD runtime coordinates mixer, IK, grant, and physics in
  * a hand-managed render loop. This component owns the WebGLRenderer, camera,
  * lights, OrbitControls, and the per-frame pipeline, and exposes the same
  * contract Stage.vue expects from every renderer.
*/

import type { SkinnedMesh } from 'three'

import type { EnvelopeEvent, GazeOffset, MMDAnimationManager, MorphController, VisemeEvent } from '../../composables/mmd'
import type { ResolvedMMDModel } from '../../utils/mmd-loader'

import { errorMessageFrom } from '@moeru/std'
import { Screen } from '@proj-airi/ui'
import { storeToRefs } from 'pinia'
import {
  AmbientLight,
  Box3,
  Clock,
  Color,
  DirectionalLight,
  Group,
  NoToneMapping,
  PerspectiveCamera,
  Quaternion,
  Scene,
  SRGBColorSpace,
  Vector3,
  WebGLRenderer,
} from 'three'
import { OrbitControls } from 'three-stdlib'
import { onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'

import {
  createGazeController,
  createMMDAnimationManager,
  createMorphController,
  EYE_PITCH_LIMIT,
  EYE_YAW_LIMIT,
  loadMMDAnimationClip,
  useMMDBlink,
  useMMDEmote,
  useMMDLipSync,
} from '../../composables/mmd'
import { Emotion, EMOTION_VALUES } from '../../constants/emotions'
import { useMMD } from '../../stores/mmd'
import { loadMMDModelFromSource } from '../../utils/mmd-loader'
import { pickMotionFromGroup, nextIdleDelayMs } from '../../utils/motion-group'
import {
  applyMMDMaterialOpacity,
  collectMMDMaterials,
  disposeMMDObject,
  setMMDMaterialGlow,
} from '../../utils/mmd-materials'

const props = withDefaults(defineProps<{
  modelSrc?: string
  modelId?: string
  paused?: boolean
  cursorPosition?: { x: number, y: number }
  currentAudioSource?: AudioBufferSourceNode
  /**
   * Server viseme timeline (AudioContext-clock absolute times) pushed by the
   * BetterAgent TTS pipeline; when present, drives discrete vowel mouth shapes
   * in preference to the audio-formant analyser.
   */
  visemeSchedule?: VisemeEvent[]
  /**
   * ~50ms RMS frames of every scheduled audio buffer (wall-clock times),
   * computed by Stage.vue from the decoded buffers. Primary driver for audio
   * lip-sync mode -- unlike Web Audio analyser graphs, this can never read
   * silence while audio is actually playing.
   */
  audioEnvelope?: EnvelopeEvent[]
  /**
   * Which driver moves the mouth (语言模块 setting):
   * - 'viseme' (default): discrete, cutscene-like shapes from the server timeline.
   * - 'audio': continuous formant analysis of the audio being played.
   * The formant analyser is also the automatic fallback whenever no viseme
   * timeline exists (frontend TTS, or utterances without visemes).
   */
  lipSyncMode?: 'viseme' | 'audio'
  /**
   * The AudioContext the stage plays through. Lip-sync analysis MUST run on
   * this exact instance; using this package's own store copy of it can end up
   * on a second AudioContext where connect() silently fails and the analyser
   * hears nothing.
   */
  audioContext?: AudioContext
  enableOrbitControls?: boolean
  /**
   * 她是否正在说话。待机随机动作会在说话期间暂停——演绎动作与待机小动作
   * 同时触发会互相打断，观感很乱。
   */
  speaking?: boolean
}>(), {
  paused: false,
  lipSyncMode: 'viseme',
  enableOrbitControls: false,
  speaking: false,
})

const emit = defineEmits<{
  (e: 'error', err: unknown): void
}>()

const componentState = defineModel<'pending' | 'loading' | 'mounted'>('state', { default: 'pending' })

const mmdStore = useMMD()
const {
  physicsEnabled,
  ikEnabled,
  grantEnabled,
  physicsGravity,
  gazeMode,
  position,
  scale,
  rotationY,
  morphOverrides,
  emotionActionGroups,
  fallbackActionGroup,
  idleRandomEnabled,
  idleActionGroup,
  idleRandomMinSeconds,
  idleRandomMaxSeconds,
  speakingGesturesEnabled,
  materialOpacity,
  idleMotionName,
  availableMotions,
  normalizeRootMotion,
  oneShotAction,
  cameraFov,
  ambientColor,
  ambientIntensity,
  directionalColor,
  directionalIntensity,
  directionalPosition,
  albedoGlow,
  renderScale,
} = storeToRefs(mmdStore)

const canvasRef = ref<HTMLCanvasElement>()

// Imperative three.js objects (no reactivity — mutated in the render loop).
let renderer: WebGLRenderer | undefined
let scene: Scene | undefined
let camera: PerspectiveCamera | undefined
let controls: OrbitControls | undefined
let ambientLight: AmbientLight | undefined
let directionalLight: DirectionalLight | undefined
let modelGroup: Group | undefined
let resolved: ResolvedMMDModel | undefined
let mesh: SkinnedMesh | undefined
let morphs: MorphController | undefined
let animation: MMDAnimationManager | undefined
let emote: ReturnType<typeof useMMDEmote> | undefined
// Motion names already bound to the current model runtime.
const registeredMotions = new Set<string>()
const clock = new Clock()
let rafHandle = 0

// Lip-sync owns Vue lifecycle hooks, so it must be created during setup. It
// is fed the live audio source and applied to whichever morphs are mounted.
const audioRef = shallowRef<AudioBufferSourceNode | undefined>(props.currentAudioSource)
watch(() => props.currentAudioSource, v => audioRef.value = v)
const lipSync = useMMDLipSync(audioRef, props.audioContext)
const blink = useMMDBlink()
let gaze: ReturnType<typeof createGazeController> | undefined

/**
 * Stage.vue hands every BetterAgent audio chunk it schedules here, so the
 * audio-driven lip-sync mode has real signal to analyse while the chunks play
 * back-to-back (the single currentAudioSource prop only ever holds the last
 * scheduled chunk).
 */
function attachAudioSource(node: AudioBufferSourceNode) {
  lipSync.attachAudioNode(node)
}

function canvasElement() {
  return canvasRef.value
}

function captureFrame(): Promise<Blob | null> | undefined {
  if (!renderer || !scene || !camera)
    return undefined
  // preserveDrawingBuffer keeps the last frame readable for the snapshot.
  renderer.render(scene, camera)
  return new Promise(resolve => canvasRef.value?.toBlob(resolve, 'image/png'))
}

/**
 * Resolves the gaze target for the current tracking mode.
 *
 * - `none`   → `undefined`, so the gaze controller idle-saccades.
 * - `camera` → centered offset, so the model looks forward toward the camera.
 * - `mouse`  → cursor position normalized to the canvas, or `undefined`
 *   (idle saccades) when there is no cursor.
 */
function resolveGazeOffset(): GazeOffset | undefined {
  if (gazeMode.value === 'none')
    return undefined

  if (gazeMode.value === 'camera') {
    // Aim the eyes at the camera: take the camera direction relative to the
    // look-at center, bring it into the model's local frame (so the user's
    // rotation is accounted for), and convert to yaw/pitch fractions of the
    // eye swing limits. Clamped, so an off-axis camera reads as a hard look.
    if (!camera || !controls || !modelGroup)
      return { x: 0, y: 0 }
    const dir = camera.position.clone().sub(controls.target).normalize()
    dir.applyQuaternion(new Quaternion().copy(modelGroup.quaternion).invert())
    const yaw = Math.atan2(dir.x, dir.z)
    const pitch = Math.asin(Math.max(-1, Math.min(1, dir.y)))
    return {
      x: Math.max(-1, Math.min(1, yaw / EYE_YAW_LIMIT)),
      y: Math.max(-1, Math.min(1, -pitch / EYE_PITCH_LIMIT)),
    }
  }

  // mouse
  if (!props.cursorPosition || !canvasRef.value)
    return undefined
  const rect = canvasRef.value.getBoundingClientRect()
  if (rect.width === 0 || rect.height === 0)
    return undefined
  const nx = ((props.cursorPosition.x - rect.left) / rect.width) * 2 - 1
  const ny = ((props.cursorPosition.y - rect.top) / rect.height) * 2 - 1
  return { x: Math.max(-1, Math.min(1, nx)), y: Math.max(-1, Math.min(1, ny)) }
}

function applyTransform() {
  if (!modelGroup)
    return
  modelGroup.scale.setScalar(scale.value)
  modelGroup.rotation.y = rotationY.value
  modelGroup.position.set(position.value.x, position.value.y, 0)
}

/**
 * three.Color rejects 8-digit `#RRGGBBAA` hex, which the color picker emits.
 * Strip the alpha channel so light colors actually apply.
 */
function normalizeHex(hex: string): string {
  return /^#[0-9a-f]{8}$/i.test(hex) ? hex.slice(0, 7) : hex
}

function setupScene() {
  const canvas = canvasRef.value!
  renderer = new WebGLRenderer({ canvas, alpha: true, antialias: true, preserveDrawingBuffer: true })
  renderer.outputColorSpace = SRGBColorSpace
  // MMD toon materials are not PBR/HDR; filmic tone mapping desaturates and
  // washes them out, so render their colors directly.
  renderer.toneMapping = NoToneMapping
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2) * renderScale.value)

  scene = new Scene()
  camera = new PerspectiveCamera(cameraFov.value, 1, 0.1, 1000)
  camera.position.set(0, 1, 3)

  // Toon shading with an albedo self-glow (applied at load): keep direct lights
  // moderate so the lit side doesn't blow out, while the glow + ambient keep the
  // shadow side bright. All values are user-adjustable via the settings store.
  ambientLight = new AmbientLight(new Color(normalizeHex(ambientColor.value)), ambientIntensity.value)
  scene.add(ambientLight)
  directionalLight = new DirectionalLight(new Color(normalizeHex(directionalColor.value)), directionalIntensity.value)
  directionalLight.position.set(directionalPosition.value.x, directionalPosition.value.y, directionalPosition.value.z)
  scene.add(directionalLight)

  controls = new OrbitControls(camera, canvas)
  controls.enableDamping = true
  controls.enabled = props.enableOrbitControls
}

/** Frames the camera so the whole model fits the viewport, and centers it. */
function frameCamera() {
  if (!camera || !controls || !modelGroup)
    return
  modelGroup.updateMatrixWorld(true)
  const box = new Box3().setFromObject(modelGroup)
  if (box.isEmpty())
    return
  const size = box.getSize(new Vector3())
  const center = box.getCenter(new Vector3())

  // Fit to BOTH axes using the camera aspect, so the model fills a portrait or
  // landscape viewport without being cropped (mirrors Spine's auto-fit).
  const vFov = (camera.fov * Math.PI) / 180
  const fitHeightDistance = (size.y / 2) / Math.tan(vFov / 2)
  const fitWidthDistance = (size.x / 2) / (Math.tan(vFov / 2) * camera.aspect)
  const distance = 1.2 * Math.max(fitHeightDistance, fitWidthDistance)

  camera.position.set(center.x, center.y, center.z + distance)
  camera.near = Math.max(distance / 100, 0.01)
  camera.far = distance * 100
  camera.updateProjectionMatrix()
  camera.lookAt(center)
  controls.target.copy(center)
  controls.update()
}

function resize() {
  if (!renderer || !camera || !canvasRef.value)
    return
  const w = canvasRef.value.clientWidth
  const h = canvasRef.value.clientHeight
  if (w === 0 || h === 0)
    return
  renderer.setSize(w, h, false)
  camera.aspect = w / h
  camera.updateProjectionMatrix()
}

function renderLoop() {
  rafHandle = requestAnimationFrame(renderLoop)
  const delta = clock.getDelta()

  if (props.paused || !renderer || !scene || !camera)
    return

  if (animation) {
    // three-mmd preserves the required mixer → IK → grant → physics order.
    animation.update(delta)
    // Apply AIRI-owned morphs after the runtime so lip-sync/expression win
    // over any VMD mouth/expression keyframes.
    emote?.update(delta)
    blink.update(morphs, delta)
    // Driver selection (语言模块 settings). Audio mode prefers the RMS
    // envelope timeline (computed from the scheduled buffers, so it always
    // has data); the analyser path stays as a secondary fallback. Viseme mode
    // uses the server timeline with the analyser as fallback for utterances
    // without visemes (frontend TTS, ...).
    if (props.lipSyncMode === 'audio') {
      if (!lipSync.updateFromEnvelope(morphs, props.audioEnvelope, delta))
        lipSync.update(morphs, delta)
    }
    else if (!lipSync.updateFromVisemes(morphs, props.visemeSchedule, delta)) {
      lipSync.update(morphs, delta)
    }
    // Gaze rotates eye/head bones, also after the helper.
    gaze?.update(resolveGazeOffset(), delta)
  }

  controls?.update()
  renderer.render(scene, camera)
}

function disposeModel() {
  const runtimeDisposedByManager = animation !== undefined
  if (animation) {
    animation.dispose()
    animation = undefined
  }
  if (!runtimeDisposedByManager)
    resolved?.mmd.dispose()

  if (modelGroup && scene) {
    scene.remove(modelGroup)
    disposeMMDObject(modelGroup)
  }
  resolved?.dispose()
  registeredMotions.clear()
  modelGroup = undefined
  mesh = undefined
  morphs = undefined
  emote = undefined
  gaze = undefined
  resolved = undefined
  mmdStore.isModelLoaded = false
}

// ---------- 待机随机动作 ----------

let idleMotionTimer: ReturnType<typeof setTimeout> | undefined
let lastIdleMotion: string | undefined
let idleRemainingMs = 0
let idleDeadline = 0

function clearIdleMotionTimer() {
  if (idleMotionTimer) {
    clearTimeout(idleMotionTimer)
    idleMotionTimer = undefined
  }
}

function hasIdleCandidates() {
  return idleRandomEnabled.value && idleActionGroup.value.length > 0 && registeredMotions.size > 0
}

/**
 * 排下一次待机动作。计时只在"没在说话"时走：
 * 说话时暂停（记住剩余时间），说完继续，而不是从头重新倒计时——
 * 否则聊天越频繁动作越不触发。
 * 下一次触发从上一个动作播完后起算（动作时长 + 随机停顿）。
 */
function scheduleIdleMotion(delayMs?: number) {
  clearIdleMotionTimer()
  if (!hasIdleCandidates())
    return

  const delay = delayMs ?? nextIdleDelayMs({
    minSeconds: idleRandomMinSeconds.value,
    maxSeconds: idleRandomMaxSeconds.value,
  })
  idleRemainingMs = Math.max(0, delay)

  if (props.speaking)
    return

  idleDeadline = Date.now() + idleRemainingMs
  idleMotionTimer = setTimeout(fireIdleMotion, idleRemainingMs)
}

/** 暂停倒计时（说话开始），保留剩余时间。 */
function pauseIdleMotion() {
  if (!idleMotionTimer)
    return
  idleRemainingMs = Math.max(0, idleDeadline - Date.now())
  clearIdleMotionTimer()
}

/** 继续倒计时（说话结束）。 */
function resumeIdleMotion() {
  if (idleMotionTimer || !hasIdleCandidates())
    return
  scheduleIdleMotion(idleRemainingMs)
}

function fireIdleMotion() {
  idleMotionTimer = undefined
  idleDeadline = 0
  if (props.speaking || !hasIdleCandidates())
    return

  const name = pickMotionFromGroup(idleActionGroup.value, Array.from(registeredMotions), lastIdleMotion)
  let actionDurationMs = 0
  if (name) {
    lastIdleMotion = name
    actionDurationMs = (animation?.getClipDuration(name) ?? 0) * 1000
    animation?.playAction(name, { loop: false })
  }

  scheduleIdleMotion(nextIdleDelayMs({
    minSeconds: idleRandomMinSeconds.value,
    maxSeconds: idleRandomMaxSeconds.value,
    actionDurationMs,
  }))
}

/**
 * Loads and registers any imported VMD motions not yet bound to the current
 * model, then (re)applies the selected idle motion. Safe to call repeatedly;
 * already-registered motions are skipped.
 */
async function syncMotions() {
  if (!animation || !mesh)
    return

  for (const descriptor of availableMotions.value) {
    if (registeredMotions.has(descriptor.name))
      continue
    try {
      // The VMD file lives in IndexedDB (shared across windows); build a
      // window-local object URL to load it, then revoke it once parsed.
      const file = await mmdStore.getMotionFile(descriptor.id)
      if (!file) {
        console.warn(`[mmd] motion file "${descriptor.name}" (${descriptor.id}) not found in storage`)
        continue
      }
      const url = URL.createObjectURL(file)
      try {
        const clip = await loadMMDAnimationClip(url, mesh, undefined, {
          normalizeRootMotion: normalizeRootMotion.value,
        })
        animation.registerClip(descriptor.name, clip)
        registeredMotions.add(descriptor.name)
        if (clip.tracks.length === 0) {
          console.warn(
            `[mmd] motion "${descriptor.name}" loaded but has 0 tracks matching this model. `
            + 'The VMD\'s bone/morph names likely do not match the model (different rig/naming).',
          )
        }
      }
      finally {
        URL.revokeObjectURL(url)
      }
    }
    catch (err) {
      console.error('[mmd] failed to load motion', descriptor.name, errorMessageFrom(err))
      emit('error', err)
    }
  }

  if (idleMotionName.value && registeredMotions.has(idleMotionName.value))
    animation.setIdleMotion(idleMotionName.value)

  scheduleIdleMotion()
}

async function loadModel(src: string) {
  if (!scene)
    return

  componentState.value = 'loading'
  disposeModel()

  try {
    resolved = await loadMMDModelFromSource(src, { cacheKey: props.modelId })
    mesh = resolved.mesh

    modelGroup = new Group()
    modelGroup.add(mesh)
    applyTransform()
    scene.add(modelGroup)

    morphs = createMorphController(mesh, morphOverrides.value)
    mmdStore.availableMorphs = morphs.availableMorphs
    if (!morphs.resolvedSlots.some(slot => slot.startsWith('vowel'))) {
      console.warn(
        '[mmd] no vowel mouth morphs (あ/い/う/え/お) resolved; lip-sync cannot move the mouth. '
        + 'Available morphs:',
        morphs.availableMorphs,
      )
    }

    emote = useMMDEmote(morphs)
    gaze = createGazeController(mesh)

    animation = createMMDAnimationManager(resolved.mmd, { physicsEnabled: physicsEnabled.value })
    // No preset idle VMD ships yet; the runtime still advances solvers and
    // physics without an animation action.
    await animation.init()
    animation.setIKEnabled(ikEnabled.value)
    animation.setGrantEnabled(grantEnabled.value)
    animation.setGravity(physicsGravity.value)

    // Ensure the camera aspect matches the live canvas before fitting.
    resize()
    frameCamera()
    setMMDMaterialGlow(modelGroup, albedoGlow.value)
    mmdStore.availableMaterials = collectMMDMaterials(modelGroup)
    applyMMDMaterialOpacity(modelGroup, materialOpacity.value)

    mmdStore.isModelLoaded = true
    componentState.value = 'mounted'

    // Bind any motions imported before this model mounted.
    await syncMotions()
  }
  catch (err) {
    disposeModel()
    componentState.value = 'pending'
    console.error('[mmd] failed to load model:', errorMessageFrom(err))
    emit('error', err)
  }
}

/** Plays a random gesture from the emotion's motion group (fallback group when empty). */
let lastEmotionMotion: string | undefined
/** 最近一次情绪；说话持续动作会沿用它在整段台词里接着随机播。 */
let activeEmotion: Emotion = Emotion.Neutral

// ---------- 说话持续动作（与待机随机动作互相独立） ----------

let speakingGestureTimer: ReturnType<typeof setTimeout> | undefined
let speakingGestureStartedAt = 0
let speakingGestureDurationMs = 0

function clearSpeakingGestureTimer() {
  if (speakingGestureTimer) {
    clearTimeout(speakingGestureTimer)
    speakingGestureTimer = undefined
  }
}

/** 从情绪动作组（空则通用备选组）随机取一个动作；组都没有可用动作时返回 undefined。 */
function pickEmotionMotion(emotion: Emotion): string | undefined {
  const available = Array.from(registeredMotions)
  const name = pickMotionFromGroup(emotionActionGroups.value[emotion], available, lastEmotionMotion)
    ?? pickMotionFromGroup(fallbackActionGroup.value, available)
  if (name)
    lastEmotionMotion = name
  return name
}

/** 播一个情绪手势并记录节拍，返回动作时长（毫秒）。 */
function playEmotionGesture(emotion: Emotion): { played: boolean, durationMs: number } {
  const name = pickEmotionMotion(emotion)
  const durationMs = name ? (animation?.getClipDuration(name) ?? 0) * 1000 : 0
  if (name)
    animation?.playAction(name, { loop: false })
  speakingGestureStartedAt = Date.now()
  speakingGestureDurationMs = durationMs
  return { played: Boolean(name), durationMs }
}

/**
 * 说话持续动作：说话期间从当前情绪的动作组里一个接一个随机播，
 * 动作播完只停 0.4~1.2 秒；台词有多长就演多长。与待机随机动作互相独立
 * （说话时待机调度暂停），开关是「说话时持续动作」。
 */
function scheduleSpeakingGesture() {
  clearSpeakingGestureTimer()
  if (!speakingGesturesEnabled.value || !props.speaking)
    return
  const elapsed = Date.now() - speakingGestureStartedAt
  const remaining = Math.max(0, speakingGestureDurationMs - elapsed) + 400 + Math.random() * 800
  speakingGestureTimer = setTimeout(fireSpeakingGesture, remaining)
}

function fireSpeakingGesture() {
  speakingGestureTimer = undefined
  if (!speakingGesturesEnabled.value || !props.speaking)
    return
  const { played } = playEmotionGesture(activeEmotion)
  if (!played)
    return
  scheduleSpeakingGesture()
}

function setEmotion(emotion: string, intensity = 1) {
  const value = EMOTION_VALUES.includes(emotion as Emotion) ? emotion as Emotion : Emotion.Neutral
  activeEmotion = value
  const { durationMs } = playEmotionGesture(value)

  // Hold the expression for as long as its gesture runs, then blend back to
  // neutral. MMD expressions never decay on their own, so without this a
  // single "happy" would leave the face frozen -- on Genshin-derived models
  // 笑い is an *eye* morph, so the eyes would stay squeezed shut until some
  // later emotion happened to replace it.
  //
  // The 3s fallback covers emotions with no motion mapped (matching the VRM
  // timeout) and single-pose VMDs, whose clips report a 0s duration.
  const holdSeconds = durationMs > 0 ? durationMs / 1000 : 3
  emote?.setEmotionWithResetAfter(value, holdSeconds * 1000, intensity)

  if (props.speaking)
    scheduleSpeakingGesture()
}

let resizeObserver: ResizeObserver | undefined

onMounted(() => {
  setupScene()
  resizeObserver = new ResizeObserver(() => resize())
  if (canvasRef.value)
    resizeObserver.observe(canvasRef.value)
  resize()
  clock.start()
  renderLoop()

  if (props.modelSrc)
    loadModel(props.modelSrc)
})

onUnmounted(() => {
  cancelAnimationFrame(rafHandle)
  clearIdleMotionTimer()
  clearSpeakingGestureTimer()
  resizeObserver?.disconnect()
  disposeModel()
  controls?.dispose()
  if (renderer) {
    renderer.dispose()
    renderer.forceContextLoss()
  }
  scene = undefined
  camera = undefined
  renderer = undefined
  controls = undefined
  ambientLight = undefined
  directionalLight = undefined
})

watch(() => props.modelSrc, (src) => {
  if (src)
    loadModel(src)
  else
    disposeModel()
})

watch(() => props.enableOrbitControls, (enabled) => {
  if (controls)
    controls.enabled = enabled
})

// View transform sliders.
watch([scale, rotationY, () => position.value.x, () => position.value.y], () => applyTransform())

// Solver/physics toggles.
watch(physicsEnabled, v => animation?.setPhysicsEnabled(v))
watch(ikEnabled, v => animation?.setIKEnabled(v))
watch(grantEnabled, v => animation?.setGrantEnabled(v))
watch(physicsGravity, v => animation?.setGravity(v))

// Morph-slot overrides: rebind each slot the user remapped (empty = auto).
watch(morphOverrides, (overrides) => {
  if (!morphs)
    return
  for (const [slot, name] of Object.entries(overrides))
    morphs.override(slot as Parameters<MorphController['override']>[0], name ?? '')
}, { deep: true })

// One-shot motion requests from tools/the act bus.
watch(oneShotAction, (request) => {
  if (request)
    animation?.playAction(request.name, { loop: request.loop })
})

// Newly imported VMD motions: load and register them against the live model.
watch(availableMotions, () => {
  void syncMotions()
}, { deep: true })

// 根骨骼归一化开关变化时重新加载全部动作：已注册的旧 clip 需要重建，
// 否则要到下次刷新/重新导入才会生效。
watch(normalizeRootMotion, () => {
  registeredMotions.clear()
  void syncMotions()
})

// Idle-motion selection from the settings panel.
watch(idleMotionName, (name) => {
  if (name && registeredMotions.has(name))
    animation?.setIdleMotion(name)
})

// 待机随机动作：设置变化重排；说话只暂停/续跑，不重置倒计时。
watch(
  [idleRandomEnabled, idleActionGroup, idleRandomMinSeconds, idleRandomMaxSeconds],
  () => scheduleIdleMotion(),
  { deep: true },
)
watch(() => props.speaking, (speaking) => {
  if (speaking) {
    pauseIdleMotion()
    scheduleSpeakingGesture()
  }
  else {
    clearSpeakingGestureTimer()
    resumeIdleMotion()
  }
})
watch(speakingGesturesEnabled, () => {
  if (props.speaking)
    scheduleSpeakingGesture()
  else
    clearSpeakingGestureTimer()
})

// Scene settings — lighting.
watch([ambientColor, ambientIntensity], () => {
  if (!ambientLight)
    return
  ambientLight.color.set(normalizeHex(ambientColor.value))
  ambientLight.intensity = ambientIntensity.value
})
watch([directionalColor, directionalIntensity], () => {
  if (!directionalLight)
    return
  directionalLight.color.set(normalizeHex(directionalColor.value))
  directionalLight.intensity = directionalIntensity.value
})
watch(directionalPosition, () => {
  directionalLight?.position.set(directionalPosition.value.x, directionalPosition.value.y, directionalPosition.value.z)
}, { deep: true })

// Scene settings — camera & rendering.
watch(cameraFov, () => {
  if (!camera)
    return
  camera.fov = cameraFov.value
  camera.updateProjectionMatrix()
})
watch(renderScale, () => {
  renderer?.setPixelRatio(Math.min(window.devicePixelRatio, 2) * renderScale.value)
  resize()
})
watch(albedoGlow, () => {
  if (modelGroup)
    setMMDMaterialGlow(modelGroup, albedoGlow.value)
})
watch(materialOpacity, () => {
  if (modelGroup)
    applyMMDMaterialOpacity(modelGroup, materialOpacity.value)
}, { deep: true })

defineExpose({
  attachAudioSource,
  canvasElement,
  captureFrame,
  setEmotion,
  listMorphs: () => morphs?.availableMorphs ?? [],
  listMotions: () => animation?.availableClips() ?? [],
})
</script>

<template>
  <Screen relative>
    <canvas ref="canvasRef" h-full w-full />
  </Screen>
</template>
