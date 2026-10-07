import { defineStore } from 'pinia'
import { ref } from 'vue'
import { betterAgentWSBridge, resolveStableChatId, toSubChatId } from '../../services/betteragent-ws'
import { useChatStreamStore } from '../chat/stream-store'
import { useChatSessionStore } from '../chat/session-store'
import { useSpeechOutputControlStore } from '../speech-output-control'
import { useSTS2GameStateStore } from './sts2-game-state'

import type { Citation, EmotionalStatePayload, LifeProposalPayload } from '../../services/betteragent-ws'

export const useBetterAgentGatewayStore = defineStore('betteragent-gateway', () => {
  const currentChatId = ref<number | null>(null)
  const csmState = ref<'idle' | 'talking' | 'thinking' | 'listening' | 'executing_action' | string>('idle')
  const isSpeaking = ref(false)
  const isStreaming = ref(false)
  const isGracePeriodActive = ref(false)
  const lastEmotion = ref('')
  const lastAction = ref('')
  const emotionalState = ref<EmotionalStatePayload | null>(null)
  // Live mid-utterance STT preview (unpunctuated, still being refined) --
  // cleared once the matching final transcript lands. No UI consumes this
  // yet; exposed for a future "recognizing..." indicator to bind to.
  const partialTranscript = ref('')
  const scheduleDialogOpen = ref(false)
  const emotionDialogOpen = ref(false)
  // Typewriter-style live caption text, revealed incrementally by
  // Stage.vue as each audio chunk's own text_segment actually starts
  // playing (see appendRevealedCaption). Reset at the start of each new
  // turn (resetRevealedCaption), accumulates across all sentences within
  // one turn.
  const revealedCaption = ref('')
  // Campus KB citations for the current turn's final reply, if any --
  // replaced (not accumulated) each time a text_delta carries some, reset
  // to empty at the start of each new turn alongside revealedCaption.
  const citations = ref<Citation[]>([])
  // 工具执行进度（Layer 4）。目前只有联网搜索会发 start/done，用于在搜索那
  // 3~8 秒里显示"正在查阅资料…"的呼吸光提示。label 是后端按角色卡渲染好的
  // 人设化文案（例如「正在翻手机查资料…」），前端原样显示，不自己拼词。
  const toolActivity = ref<{ tool: string, label: string } | null>(null)
  // 向着星写入确认框：lifeProposal 是当前弹窗展示的那条；lifeProposalQueue 是
  // 排队等待确认的其余提议（同一轮可能生成多条，用户逐条确认）。pending 入队，
  // 终态由弹窗展示结果后从队列里推出下一条。
  const lifeProposal = ref<LifeProposalPayload | null>(null)
  const lifeProposalQueue = ref<LifeProposalPayload[]>([])

  function promoteNextLifeProposal() {
    const [next, ...rest] = lifeProposalQueue.value
    lifeProposalQueue.value = rest
    lifeProposal.value = next ?? null
  }

  const streamStore = useChatStreamStore()
  const chatSession = useChatSessionStore()
  const sts2GameState = useSTS2GameStateStore()
  const speechOutputControl = useSpeechOutputControlStore()

  let streamingWatchdog: ReturnType<typeof setTimeout> | null = null
  let graceTimer: ReturnType<typeof setTimeout> | null = null

  function appendRevealedCaption(segment: string) {
    if (segment)
      revealedCaption.value += segment
  }

  function resetRevealedCaption() {
    revealedCaption.value = ''
  }

  function resetStreamingWatchdog() {
    if (streamingWatchdog) {
      clearTimeout(streamingWatchdog)
      streamingWatchdog = null
    }
  }

  function touchStreamingWatchdog() {
    resetStreamingWatchdog()
    streamingWatchdog = setTimeout(() => {
      if (isStreaming.value) {
        console.warn('[BetterAgentGateway] Stream watchdog timeout reached, resetting isStreaming state')
        isStreaming.value = false
        isGracePeriodActive.value = false
        streamStore.finalizeStream()
      }
    }, 45000)
  }

  function triggerGracePeriod() {
    isGracePeriodActive.value = true
    if (graceTimer)
      clearTimeout(graceTimer)
    // 1200ms grace period bridges the gap between LLM isFinal=true and first TTS audio chunk arrival
    graceTimer = setTimeout(() => {
      isGracePeriodActive.value = false
      graceTimer = null
    }, 1200)
  }

  function getResolvedChatId(): number | null {
    if (currentChatId.value)
      return currentChatId.value

    const bridgeChatId = betterAgentWSBridge.getChatId()
    if (bridgeChatId) {
      currentChatId.value = bridgeChatId
      return bridgeChatId
    }

    const stableChatId = resolveStableChatId()
    if (stableChatId) {
      currentChatId.value = stableChatId
      return currentChatId.value
    }

    return null
  }

  function isChatMatch(msgChatId?: number | null): boolean {
    // !msgChatId would also match a real (but falsy) chat_id of 0.
    if (msgChatId == null)
      return true
    const active = getResolvedChatId()
    if (!active)
      return true
    // active and msgChatId aren't guaranteed to be the same type (one may
    // come off a URL query param as a string) -- compare as numbers so a
    // type mismatch alone never causes a live chat_id to be filtered out.
    const activeNum = Number(active)
    const msgNum = Number(msgChatId)
    if (!Number.isFinite(activeNum) || !Number.isFinite(msgNum))
      return true
    // 关键：本地拿到的是**子 id**（URL / localStorage），而 Go 回传的每一帧
    // payload.chat_id 是**折叠过**的 id（子 id + WebNamespaceOffset）。直接比会
    // 永远不相等，于是 agent.tool_activity（联网搜索提示）、agent.state_change
    // 这类「带 chat_id 的帧」会被这里全部丢掉——用户看到的就是"卡住、没有搜索
    // 过程"。两边统一折回子 id 再比。
    return toSubChatId(activeNum) === toSubChatId(msgNum)
  }

  let unsubs: Array<() => void> = []

  let initialized = false
  function initialize(pinnedChatId?: number) {
    if (pinnedChatId) {
      currentChatId.value = pinnedChatId
    }

    if (initialized)
      return
    initialized = true

    // Warm the cache early so the first isChatMatch() call (which can
    // arrive before anything else has triggered a resolution) doesn't race
    // against it -- resolution failing on that first call means every
    // check falls through to the "no active chat yet, allow" branch.
    getResolvedChatId()

    // Clean up previous listeners if re-initializing
    unsubs.forEach(unsub => unsub())
    unsubs = []

    betterAgentWSBridge.connect()

    // 1. Text Delta & Stream Life Cycle
    unsubs.push(betterAgentWSBridge.onTextDelta((text: string, isFinal?: boolean, chatId?: number, msgCitations?: Citation[]) => {
      if (!isChatMatch(chatId))
        return

      // 只带 citations、不带文字的收尾帧：仅更新"她的消息来源"，绝不当作一句话。
      // 它比最后几句的 TTS 回灌还早到（句子要等音频分块才 flush），若让它走进
      // 下面那段"开流/收尾"的逻辑，就会凭空开一个空字幕、或提前 finalize 把尾句
      // 甩到流外面。"回合结束"由 CSM 的 state_change 负责，不靠这条帧。
      if (!text) {
        if (msgCitations?.length)
          citations.value = msgCitations
        return
      }

      touchStreamingWatchdog()
      if (!isStreaming.value) {
        isStreaming.value = true
        streamStore.beginStream()
        resetRevealedCaption()
        citations.value = []
      }
      streamStore.appendStreamLiteral(text)

      if (msgCitations?.length)
        citations.value = msgCitations

      if (isFinal) {
        resetStreamingWatchdog()
        isStreaming.value = false
        triggerGracePeriod()
        streamStore.finalizeStream()
        // 兜底：搜完立刻撤掉提示，不等 done 事件（两者通常同时到）。
        toolActivity.value = null
      }
    }))

    // 2. CSM State Transitions
    unsubs.push(betterAgentWSBridge.onStateChange((state: string, chatId?: number, reason?: string) => {
      if (!isChatMatch(chatId))
        return

      const normalized = state.toLowerCase()
      csmState.value = normalized
      if (normalized === 'talking') {
        isSpeaking.value = true
      }
      else if (normalized === 'idle') {
        isSpeaking.value = false
        isStreaming.value = false
        isGracePeriodActive.value = false
        if (graceTimer) {
          clearTimeout(graceTimer)
          graceTimer = null
        }
        resetStreamingWatchdog()
        // 兜底：搜索中途被打断（barge-in / 取消）时 done 事件不会来，
        // 否则提示会一直转下去。
        toolActivity.value = null
        // The CSM reaches idle both on a normal turn end (reason
        // "tts_stream_end"/"text_fallback_idle", sent as soon as the server
        // is done producing/sending, not once the client has finished
        // *playing* the already-queued/in-flight audio) and on a barge-in
        // cancel (reason "stream_cancelled"). Only the latter should cut
        // audio short -- stopping unconditionally here would clip the tail
        // of every normal response.
        if (reason === 'stream_cancelled')
          speechOutputControl.requestStopSpeaking('server-state-idle')
      }
    }))

    // 3. Audio Chunks
    unsubs.push(betterAgentWSBridge.onAudioChunk((_audioBase64: string, _sampleRate: number, chatId?: number) => {
      if (!isChatMatch(chatId))
        return
      isSpeaking.value = true
    }))

    // 4. Emotion & Action Tokens
    unsubs.push(betterAgentWSBridge.onEmotion((emotion: string, action?: string) => {
      lastEmotion.value = emotion
      if (action)
        lastAction.value = action
    }))

    unsubs.push(betterAgentWSBridge.onEmotionState((state) => {
      emotionalState.value = state
    }))

    // 5. Tool activity (Layer 4) -- persona-flavoured "looking it up" indicator
    //    shown while a web search is in flight.
    unsubs.push(betterAgentWSBridge.onToolActivity((activity) => {
      if (!isChatMatch(activity.chat_id))
        return
      if (activity.phase === 'start')
        toolActivity.value = { tool: activity.tool, label: activity.label || '' }
      else
        toolActivity.value = null
    }))

    // 5. Game State
    unsubs.push(betterAgentWSBridge.onGameState((state) => {
      sts2GameState.updateState(state)
    }))

    // 5.5 向着星写入确认框：同一轮的多条提议进入队列，弹窗按顺序逐条确认
    unsubs.push(betterAgentWSBridge.onLifeProposal((proposal) => {
      if (!isChatMatch(proposal.chat_id))
        return
      const phase = proposal.phase

      // 当前弹窗正在展示的那条：任何相位都就地更新（终态由弹窗展示结果）
      if (lifeProposal.value?.proposal_id === proposal.proposal_id) {
        lifeProposal.value = proposal
        return
      }

      const index = lifeProposalQueue.value.findIndex(item => item.proposal_id === proposal.proposal_id)
      if (index >= 0) {
        const next = [...lifeProposalQueue.value]
        if (phase === 'executing')
          next[index] = proposal
        else
          next.splice(index, 1) // 还没轮到展示就收到终态（超时等）：直接出队
        lifeProposalQueue.value = next
        return
      }

      // 新提议：没在展示就排队（pending 才会到这一步）
      if (!lifeProposal.value) {
        lifeProposal.value = proposal
        return
      }
      lifeProposalQueue.value = [...lifeProposalQueue.value, proposal]
    }))

    // 6. STT transcripts -- show the user's recognized voice input as a
    // normal user message so a spoken turn reads like a typed one. Partial
    // (mid-utterance) results only update the live preview, never the chat.
    unsubs.push(betterAgentWSBridge.onSTTTranscript((text, isFinal, chatId) => {
      if (!isChatMatch(chatId))
        return

      if (!isFinal) {
        partialTranscript.value = text
        return
      }

      partialTranscript.value = ''

      if (!text.trim())
        return

      const sessionId = chatSession.activeSessionId
      if (!sessionId)
        return

      chatSession.appendSessionMessage(sessionId, {
        role: 'user',
        content: text.trim(),
      })
    }))
  }

  return {
    currentChatId,
    csmState,
    isSpeaking,
    isStreaming,
    isGracePeriodActive,
    lastEmotion,
    lastAction,
    emotionalState,
    partialTranscript,
    revealedCaption,
    citations,
    toolActivity,
    lifeProposal,
    lifeProposalQueue,
    promoteNextLifeProposal,
    scheduleDialogOpen,
    emotionDialogOpen,
    initialize,
    getResolvedChatId,
    appendRevealedCaption,
    resetRevealedCaption,
  }
})
