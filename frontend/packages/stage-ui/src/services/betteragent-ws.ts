/**
 * BetterAgent WebSocket Client Bridge
 * Connects Airi frontend directly to BetterAgent Go WebGateway (ws://localhost:8080/ws)
 */

export interface Viseme {
  time_offset: number
  viseme_id: number
  shape: string
}

// Mirrors campus_kb_tool.py's fact shape / Go's webgateway.Citation. Only
// ever present on the agent.text_delta message carrying is_final=true.
export interface Citation {
  content: string
  source: string
  relevance_score?: number
}

export interface WSMessage<T = any> {
  type: string
  payload?: T
}

export type TextDeltaCallback = (text: string, isFinal: boolean, chatId?: number, citations?: Citation[]) => void
export type EmotionCallback = (emotion: string, action?: string) => void
export type AudioChunkCallback = (audioBase64: string, sampleRate: number, chatId?: number, visemes?: Viseme[], textSegment?: string) => void
export type StateChangeCallback = (state: string, chatId?: number, reason?: string) => void

/**
 * 工具执行进度（Layer 4）。目前只有联网搜索会发：phase="start" 表示搜索已发起
 * （前端该显示"正在查阅资料…"），phase="done" 表示搜索结束（该撤掉提示）。
 * label 是角色卡渲染好的人设化文案，前端原样显示，不要自己拼"正在搜索"。
 */
export interface ToolActivityPayload {
  chat_id?: number
  tool: string
  phase: 'start' | 'done' | string
  label?: string
}
export type ToolActivityCallback = (activity: ToolActivityPayload) => void

/**
 * 向着星写入提议（确认框）帧。phase 生命周期：
 * pending → executing → executed | failed，或 pending → cancelled | expired。
 * 用户在框里点确认/取消后，前端通过 sendLifeDecision 把哨兵文本走普通
 * user.text 发回；在用户确认之前后端不会写入任何数据。
 */
export interface LifeProposalPayload {
  chat_id?: number
  proposal_id: string
  phase: 'pending' | 'executing' | 'executed' | 'failed' | 'cancelled' | 'expired' | string
  kind?: string
  params?: Record<string, any>
  summary?: string
  message?: string
}
export type LifeProposalCallback = (proposal: LifeProposalPayload) => void

/** 确认框决策的哨兵前缀；后端 cognitive_engine.parse_life_decision 依赖它。 */
export const LIFE_DECISION_PREFIX = '【确认框】'

/**
 * 专注模式（番茄钟）状态帧。Go 的 FocusManager 是计时唯一真源：剩余时间以
 * 广播为准，前端只用 deadline_unix 本地平滑倒数、每次广播再校正。
 * phase=completed 表示自然结束，等待用户在总结弹窗里提交内容。
 */
export interface FocusStatePayload {
  chat_id?: number
  phase: 'idle' | 'running' | 'paused' | 'completed' | string
  planned_minutes: number
  remaining_seconds: number
  started_at_unix?: number
  deadline_unix?: number
  elapsed_seconds?: number
}
export type FocusStateCallback = (state: FocusStatePayload) => void

/** 专注挂件控制哨兵；后端 cognitive_engine.parse_focus_control 依赖它。 */
export const FOCUS_CONTROL_PREFIX = '【专注】'

/**
 * 轻量 UI 通知（不经过 LLM、不播报）：目前用于「远程连接」模式下暂存的
 * 向着星写入补交成功/放弃。前端只弹一条低优先级 toast。
 */
export interface NoticePayload {
  level?: 'info' | 'warn' | string
  title?: string
  message: string
}
export type NoticeCallback = (notice: NoticePayload) => void
export type STTTranscriptCallback = (text: string, isFinal: boolean, chatId?: number) => void
export interface GameStatePayload {
  floor: number
  hp: number
  max_hp: number
  gold: number
  act: number
}
export type GameStateCallback = (state: GameStatePayload) => void

export interface EmotionalStatePayload {
  mood: 'HAPPY' | 'NEUTRAL' | 'MOODY' | 'SLEEPY' | 'JEALOUS' | string
  valence: number
  arousal: number
  energy: number
  satiety: number
  social_battery: number
  affection: number
  is_jealous: boolean
  description: string
}
export type EmotionStateCallback = (state: EmotionalStatePayload, action?: string) => void

const STORAGE_CHAT_ID_KEY = 'betteragent:web:chat_id'

/**
 * WebGateway 会话命名空间偏移（镜像 Go core/internal/idspace/idspace.go 的
 * WebNamespaceOffset）。
 *
 * 前端在 URL / localStorage 里持有的是**子 id**（见下面的 resolveStableChatId），
 * 而 Go 回传的每一帧 payload.chat_id 都是**折叠后**的 id（子 id + 该偏移）。
 * 两边必须先折到同一侧再比较，否则 isChatMatch 会把所有带 chat_id 的帧全部丢掉
 * ——联网搜索提示（agent.tool_activity）和 agent.state_change 都因此消失过。
 * 反过来要调 Companion/HTTP 接口时，用「子 id + 该偏移」还原真实 chat_id。
 */
export const WEB_NAMESPACE_OFFSET = 9_000_000_000_000_000

/** 把服务端折叠过的 chat_id 折回前端持有的子 id（本来就未折叠的原样返回）。 */
export function toSubChatId(chatId: number): number {
  return chatId >= WEB_NAMESPACE_OFFSET ? chatId - WEB_NAMESPACE_OFFSET : chatId
}

export function resolveStableChatId(): number {
  if (typeof import.meta !== 'undefined' && import.meta.env?.VITE_BETTERAGENT_USER_ID) {
    const envId = Number(import.meta.env.VITE_BETTERAGENT_USER_ID)
    if (!Number.isNaN(envId) && envId > 0)
      return envId
  }

  if (typeof window !== 'undefined') {
    const urlParams = new URLSearchParams(window.location.search)
    const queryChatId = urlParams.get('chat_id')
    if (queryChatId) {
      const parsed = Number(queryChatId)
      if (!Number.isNaN(parsed) && parsed > 0) {
        localStorage.setItem(STORAGE_CHAT_ID_KEY, String(parsed))
        return parsed
      }
    }
  }

  if (typeof window !== 'undefined') {
    const stored = localStorage.getItem(STORAGE_CHAT_ID_KEY)
    if (stored) {
      const parsed = Number(stored)
      if (!Number.isNaN(parsed) && parsed > 0)
        return parsed
    }
  }

  const generated = Math.floor(1000000 + Math.random() * 9000000)
  if (typeof window !== 'undefined')
    localStorage.setItem(STORAGE_CHAT_ID_KEY, String(generated))
  return generated
}

// Binary Audio Frame Protocol
function encodeBinaryAudioFrame(pcm: Int16Array): ArrayBuffer {
  const buf = new ArrayBuffer(20 + pcm.byteLength)
  const view = new DataView(buf)
  view.setUint8(0, 0x41) // 'A'
  view.setUint8(1, 0x55) // 'U'
  view.setUint8(2, 0x44) // 'D'
  view.setUint8(3, 0x49) // 'I'
  view.setBigInt64(4, 0n, false)
  view.setBigUint64(12, 0n, false)
  new Uint8Array(buf, 20).set(new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength))
  return buf
}

function uint8ArrayToBase64(bytes: Uint8Array): string {
  let binary = ''
  const len = bytes.byteLength
  const chunkSize = 0x8000 // 32KB chunking
  for (let i = 0; i < len; i += chunkSize) {
    const chunk = bytes.subarray(i, Math.min(i + chunkSize, len))
    binary += String.fromCharCode.apply(null, chunk as unknown as number[])
  }
  return btoa(binary)
}

export class BetterAgentWSBridge {
  private ws: WebSocket | null = null
  private url: string
  private chatId: number | null = null
  private reconnectAttempts = 0
  private maxReconnectInterval = 5000
  private isIntentionalClose = false

  private textDeltaListeners: Set<TextDeltaCallback> = new Set()
  private emotionListeners: Set<EmotionCallback> = new Set()
  private emotionStateListeners: Set<EmotionStateCallback> = new Set()
  private audioChunkListeners: Set<AudioChunkCallback> = new Set()
  // Highest binary-frame generation seen per chat, so a reordered/obsoleted
  // frame from a barge-in'd generation can't play after the WebGateway has
  // already moved on (see protocol.go's AUDI header: bytes 12-20).
  private latestGenerationByChat: Map<number, bigint> = new Map()
  // The JSON agent.audio_chunk message (carrying visemes and this chunk's
  // own text_segment) is always sent immediately before the binary AUDI
  // frame for the same chunk, over the same ordered WS connection -- stash
  // them here and pair them with the next binary frame that actually plays.
  private pendingVisemes: Viseme[] | undefined
  private pendingTextSegment: string | undefined
  private sttTranscriptListeners: Set<STTTranscriptCallback> = new Set()
  private stateChangeListeners: Set<StateChangeCallback> = new Set()
  private toolActivityListeners: Set<ToolActivityCallback> = new Set()
  private lifeProposalListeners: Set<LifeProposalCallback> = new Set()
  private focusStateListeners: Set<FocusStateCallback> = new Set()
  private noticeListeners: Set<NoticeCallback> = new Set()
  private gameStateListeners: Set<GameStateCallback> = new Set()
  private openListeners: Set<() => void> = new Set()

  constructor(serverUrl = 'ws://localhost:8080/ws') {
    const existingChatId = (() => {
      try {
        return Number(new URL(serverUrl).searchParams.get('chat_id'))
      }
      catch {
        return Number.NaN
      }
    })()

    if (Number.isNaN(existingChatId) || existingChatId === 0) {
      const stableChatId = resolveStableChatId()
      serverUrl += (serverUrl.includes('?') ? '&' : '?') + `chat_id=${stableChatId}`
    }

    if (!serverUrl.includes('token=')) {
      const token = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_BETTERAGENT_WS_TOKEN)
        ? import.meta.env.VITE_BETTERAGENT_WS_TOKEN
        : undefined
      if (token) {
        serverUrl += (serverUrl.includes('?') ? '&' : '?') + `token=${encodeURIComponent(token)}`
      }
    }

    this.url = serverUrl

    try {
      const parsedUrl = new URL(serverUrl)
      const chatId = Number(parsedUrl.searchParams.get('chat_id'))
      if (!Number.isNaN(chatId))
        this.chatId = chatId
    }
    catch {
      this.chatId = null
    }
  }

  public getChatId(): number | null {
    return this.chatId
  }

  public connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return
    }
    this.isIntentionalClose = false
    try {
      this.ws = new WebSocket(this.url)
      this.ws.binaryType = 'arraybuffer'

      this.ws.onopen = () => {
        console.log('[BetterAgentWSBridge] Connected successfully 🚀')
        this.reconnectAttempts = 0
        // A fresh connection (initial or reconnect) may be talking to a
        // backend process that restarted -- generationID counters reset to
        // 1 there (see core/internal/engine/state_machine.go), so a stale
        // high-water mark from before the disconnect would otherwise cause
        // every future audio frame for that chat to be misjudged as stale
        // and silently dropped forever.
        this.latestGenerationByChat.clear()
        this.openListeners.forEach((cb) => {
          try {
            cb()
          }
          catch (err) {
            console.warn('[BetterAgentWSBridge] onOpen listener threw:', err)
          }
        })
      }

      this.ws.onmessage = (event: MessageEvent) => {
        this.handleMessage(event)
      }

      this.ws.onerror = (err) => {
        console.warn('[BetterAgentWSBridge] WebSocket error:', err)
      }

      this.ws.onclose = () => {
        if (!this.isIntentionalClose) {
          this.scheduleReconnect()
        }
      }
    }
    catch (err) {
      console.error('[BetterAgentWSBridge] Failed to create WebSocket:', err)
      this.scheduleReconnect()
    }
  }

  private scheduleReconnect(): void {
    this.reconnectAttempts++
    const delay = Math.min(1000 * (2 ** this.reconnectAttempts), this.maxReconnectInterval)
    setTimeout(() => this.connect(), delay)
  }

  private handleMessage(event: MessageEvent): void {
    if (event.data instanceof ArrayBuffer) {
      this.handleBinaryFrame(event.data)
      return
    }

    try {
      const msg: WSMessage = JSON.parse(event.data)
      switch (msg.type) {
        case 'agent.text_delta': {
          // text 可以为空：本轮没有剩余句子可播时，后端会单独发一条只带
          // citations 的收尾帧（见 Go 侧 handleActionDecisionMsg），所以判空条件
          // 必须把 citations 也算上，否则"她的消息来源"永远收不到东西。
          const hasCitations = Array.isArray(msg.payload?.citations) && msg.payload.citations.length > 0
          if (msg.payload && (msg.payload.text || hasCitations)) {
            const citations: Citation[] | undefined = hasCitations ? msg.payload.citations : undefined
            this.textDeltaListeners.forEach(cb => cb(msg.payload.text ?? '', !!msg.payload.is_final, msg.payload.chat_id, citations))
          }
          break
        }

        case 'agent.emotion':
          if (msg.payload) {
            const emotionStr = typeof msg.payload === 'string' ? msg.payload : (msg.payload.emotion || msg.payload.mood || '')
            if (emotionStr) {
              this.emotionListeners.forEach(cb => cb(emotionStr, msg.payload.action))
            }
            if (typeof msg.payload === 'object' && ('valence' in msg.payload || 'mood' in msg.payload)) {
              this.emotionStateListeners.forEach(cb => cb(msg.payload as EmotionalStatePayload, msg.payload.action))
            }
          }
          break

        case 'agent.game_state':
          if (msg.payload) {
            this.gameStateListeners.forEach(cb => cb(msg.payload))
          }
          break

        case 'agent.audio_chunk':
          if (Array.isArray(msg.payload?.visemes)) {
            this.pendingVisemes = msg.payload.visemes
          }
          if (typeof msg.payload?.text_segment === 'string' && msg.payload.text_segment) {
            this.pendingTextSegment = msg.payload.text_segment
          }
          break

        case 'agent.stt_transcript':
          if (msg.payload?.text) {
            this.sttTranscriptListeners.forEach(cb => cb(msg.payload.text, !!msg.payload.is_final, msg.payload.chat_id))
          }
          break

        case 'agent.tool_activity':
          if (msg.payload?.tool) {
            this.toolActivityListeners.forEach(cb => cb(msg.payload as ToolActivityPayload))
          }
          break

        case 'agent.life_proposal':
          if (msg.payload?.proposal_id) {
            this.lifeProposalListeners.forEach(cb => cb(msg.payload as LifeProposalPayload))
          }
          break

        case 'agent.focus_state':
          if (msg.payload?.phase) {
            this.focusStateListeners.forEach(cb => cb(msg.payload as FocusStatePayload))
          }
          break

        case 'agent.notice':
          if (msg.payload?.message) {
            this.noticeListeners.forEach(cb => cb(msg.payload as NoticePayload))
          }
          break

        case 'agent.state_change':
          if (msg.payload?.state) {
            this.stateChangeListeners.forEach(cb => cb(msg.payload.state, msg.payload.chat_id, msg.payload.reason))
          }
          break

        default:
          console.debug('[BetterAgentWSBridge] Unknown frame type:', msg.type)
      }
    }
    catch (err) {
      console.warn('[BetterAgentWSBridge] Error parsing JSON message:', err)
    }
  }

  private handleBinaryFrame(buf: ArrayBuffer): void {
    const view = new DataView(buf)
    if (buf.byteLength < 20)
      return

    const magic = String.fromCharCode(view.getUint8(0), view.getUint8(1), view.getUint8(2), view.getUint8(3))
    if (magic !== 'AUDI')
      return

    const chatId = Number(view.getBigInt64(4, false))
    const generationId = view.getBigUint64(12, false)

    const latestGen = this.latestGenerationByChat.get(chatId) ?? 0n
    if (generationId < latestGen) {
      // Stale frame from a generation that's already been superseded
      // (barge-in / new message) -- drop it instead of playing it late.
      // Also discard any visemes/text_segment that arrived paired with this
      // dropped frame, so they don't get attached to the next (unrelated)
      // chunk.
      this.pendingVisemes = undefined
      this.pendingTextSegment = undefined
      return
    }
    if (generationId > latestGen) {
      this.latestGenerationByChat.set(chatId, generationId)
    }

    const rawAudio = buf.slice(20)
    const base64Audio = uint8ArrayToBase64(new Uint8Array(rawAudio))
    const visemes = this.pendingVisemes
    const textSegment = this.pendingTextSegment
    this.pendingVisemes = undefined
    this.pendingTextSegment = undefined
    this.audioChunkListeners.forEach(cb => cb(base64Audio, 32000, chatId, visemes, textSegment))
  }

  public sendUserText(text: string, chatId?: number): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      const msg: WSMessage = {
        type: 'user.text',
        payload: { text, chat_id: chatId },
      }
      this.ws.send(JSON.stringify(msg))
    }
  }

  /**
   * 报告"前端页面刚打开"，由 Go 侧触发一次主动打招呼（见 handleUserGreeting）。
   * awaySeconds 是上一次打开页面距今的秒数，首次访问不传。
   * 服务端有 10 秒冷却与"忙时不打扰"守卫，重复发送是安全的。
   */
  public sendGreeting(awaySeconds?: number): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      const msg: WSMessage = {
        type: 'user.greeting',
        payload: awaySeconds && awaySeconds > 0 ? { away_seconds: Math.round(awaySeconds) } : {},
      }
      this.ws.send(JSON.stringify(msg))
    }
  }

  /**
   * 发送确认框决策。哨兵文本走普通 user.text，因此确认后的执行与语言反馈
   * 复用完整对话管线（记忆/情绪/流式回复），且聊天记录里不会多出一条机器消息
   * （由调用方决定不把它加进 UI）。
   */
  public sendLifeDecision(proposalId: string, action: 'confirm' | 'cancel', edits?: Record<string, unknown>): void {
    const sentinel = `${LIFE_DECISION_PREFIX}${JSON.stringify({ v: 1, id: proposalId, action, edits: edits || {} })}`
    this.sendUserText(sentinel)
  }

  /** 询问当前专注状态；Go 会把 agent.focus_state 只回给发起请求的这个页面。 */
  public sendFocusStatus(): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'user.focus_status' }))
    }
  }

  /**
   * 发送专注挂件控制（暂停/继续/放弃/提交总结），与确认框一样走哨兵文本：
   * 引擎确定性转成 FocusCommandPayload 交给 Go 的 FocusManager，模型只负责说。
   */
  public sendFocusControl(
    action: 'pause' | 'resume' | 'abandon' | 'finish',
    extra: Record<string, unknown> = {},
  ): void {
    const sentinel = `${FOCUS_CONTROL_PREFIX}${JSON.stringify({ v: 1, action, ...extra })}`
    this.sendUserText(sentinel)
  }

  public sendSpeechStart(): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'user.speech_start' }))
    }
  }

  public sendSpeechEnd(): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'user.speech_end' }))
    }
  }

  public sendVisionFrame(imageBase64: string, sourceType: 'screen' | 'camera' = 'screen', format = 'jpeg'): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      const msg: WSMessage = {
        type: 'user.vision_frame',
        payload: {
          image_base64: imageBase64,
          source_type: sourceType,
          format,
        },
      }
      this.ws.send(JSON.stringify(msg))
    }
  }

  public sendAudioChunk(pcm: Int16Array): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(encodeBinaryAudioFrame(pcm))
    }
  }

  public isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN
  }

  public onTextDelta(cb: TextDeltaCallback): () => void {
    this.textDeltaListeners.add(cb)
    return () => this.textDeltaListeners.delete(cb)
  }

  /** 注册 WS 连接成功回调（含重连）；返回取消注册函数。 */
  public onOpen(cb: () => void): () => void {
    this.openListeners.add(cb)
    return () => this.openListeners.delete(cb)
  }

  /** 订阅专注状态广播（含状态查询回帧）；返回取消注册函数。 */
  public onFocusState(cb: FocusStateCallback): () => void {
    this.focusStateListeners.add(cb)
    return () => this.focusStateListeners.delete(cb)
  }

  /** 订阅轻量 UI 通知（补交成功等）；返回取消注册函数。 */
  public onNotice(cb: NoticeCallback): () => void {
    this.noticeListeners.add(cb)
    return () => this.noticeListeners.delete(cb)
  }

  public onEmotion(cb: EmotionCallback): () => void {
    this.emotionListeners.add(cb)
    return () => this.emotionListeners.delete(cb)
  }

  public onAudioChunk(cb: AudioChunkCallback): () => void {
    this.audioChunkListeners.add(cb)
    return () => this.audioChunkListeners.delete(cb)
  }

  public onSTTTranscript(cb: STTTranscriptCallback): () => void {
    this.sttTranscriptListeners.add(cb)
    return () => this.sttTranscriptListeners.delete(cb)
  }

  public onStateChange(cb: StateChangeCallback): () => void {
    this.stateChangeListeners.add(cb)
    return () => this.stateChangeListeners.delete(cb)
  }

  public sendPersonaUpdate(personaId: string, patch: Record<string, unknown>): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      const msg: WSMessage = {
        type: 'admin.persona_update',
        payload: { persona_id: personaId, ...patch },
      }
      this.ws.send(JSON.stringify(msg))
    }
  }

  public onToolActivity(cb: ToolActivityCallback): () => void {
    this.toolActivityListeners.add(cb)
    return () => this.toolActivityListeners.delete(cb)
  }

  public onLifeProposal(cb: LifeProposalCallback): () => void {
    this.lifeProposalListeners.add(cb)
    return () => this.lifeProposalListeners.delete(cb)
  }

  public onEmotionState(cb: EmotionStateCallback): () => void {
    this.emotionStateListeners.add(cb)
    return () => this.emotionStateListeners.delete(cb)
  }

  public onGameState(cb: GameStateCallback): () => void {
    this.gameStateListeners.add(cb)
    return () => this.gameStateListeners.delete(cb)
  }

  public disconnect(): void {
    this.isIntentionalClose = true
    if (this.ws) {
      this.ws.close()
      this.ws = null
    }
  }
}

export const betterAgentWSBridge = new BetterAgentWSBridge()

if (typeof window !== 'undefined') {
  (window as any).betterAgentWSBridge = betterAgentWSBridge
}
