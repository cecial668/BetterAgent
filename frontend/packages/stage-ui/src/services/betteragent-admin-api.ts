export interface ScheduleRecord {
  schedule_id: string
  title: string
  remind_at: string
  note: string
  status: string
}

export interface ScheduleCreatePayload {
  chat_id: number
  user_id: number
  title: string
  remind_at: string
  note?: string
}

export interface SessionSummary {
  chat_id: number
  message_count: number
  last_timestamp: number | null
  preview: string
}

export interface SessionMessage {
  message_id: string | number
  role: string
  content: string
  timestamp: number
}

export interface LongTermMemory {
  id: string
  text: string
  timestamp?: number
  metadata?: Record<string, unknown>
}

export interface MemoryProfile {
  user_id: number
  display_name: string
  known_facts: string[]
  dislikes: string[]
  last_seen?: string | null
}

export interface MemoryProfilePatch {
  display_name?: string
  known_facts?: string[]
  dislikes?: string[]
}

/**
 * 联网搜索（tools.web_search）在 Admin 配置接口里的形态。
 *
 * `enabled` 是 config.yaml 里的总开关；`key_set` 表示搜索服务的 API Key 是否
 * 已经配置。两者要分开看：开关打开但没填 Key 时，cognitive 服务会按"不可用"
 * 处理，所以界面必须如实提示，不能只显示开关状态。
 */
export interface WebSearchConfig {
  enabled: boolean
  provider: string
  api_key_env: string
  top_k: number
  timeout_seconds: number
  max_calls_per_turn: number
  key_masked: string | null
  key_set: boolean
}

/** 只传需要改的字段；api_key 会写进根目录 .env，其余写进 config.yaml。 */
export interface WebSearchConfigPatch {
  enabled?: boolean
  provider?: string
  api_key?: string
  top_k?: number
  timeout_seconds?: number
  max_calls_per_turn?: number
}

const ADMIN_API_BASE = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_ADMIN_API_BASE)
  ? import.meta.env.VITE_ADMIN_API_BASE
  : 'http://localhost:8094'

export function resolveBetterAgentWebId(chatId?: number | null): number {
  const envUserId = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_BETTERAGENT_USER_ID)
    ? import.meta.env.VITE_BETTERAGENT_USER_ID
    : undefined
  if (envUserId && !Number.isNaN(Number(envUserId)))
    return Number(envUserId)
  return chatId ?? 0
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T | null> {
  try {
    const headers = new Headers(init?.headers)
    headers.set('Accept', 'application/json')
    const adminToken = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_ADMIN_API_TOKEN)
      ? import.meta.env.VITE_ADMIN_API_TOKEN
      : undefined
    if (adminToken)
      headers.set('Authorization', `Bearer ${adminToken}`)
    if (init?.body)
      headers.set('Content-Type', 'application/json')
    const res = await fetch(`${ADMIN_API_BASE}${path}`, { ...init, headers })
    if (!res.ok)
      return null
    return (await res.json()) as T
  }
  catch {
    return null
  }
}

export async function listSchedules(chatId: number): Promise<ScheduleRecord[]> {
  const payload = await requestJson<{ schedules: ScheduleRecord[] }>(
    `/api/admin/schedules?chat_id=${encodeURIComponent(chatId)}`,
  )
  return payload?.schedules ?? []
}

export async function createSchedule(input: ScheduleCreatePayload): Promise<boolean> {
  const res = await requestJson<{ schedule_id: string }>('/api/admin/schedules', {
    method: 'POST',
    body: JSON.stringify(input),
  })
  return !!res?.schedule_id
}

export async function deleteSchedule(scheduleId: string): Promise<boolean> {
  const res = await requestJson<{ status: string }>(
    `/api/admin/schedules/${encodeURIComponent(scheduleId)}`,
    { method: 'DELETE' },
  )
  return res?.status === 'deleted'
}

export async function getSessionOverview(): Promise<SessionSummary[]> {
  const payload = await requestJson<{ sessions: SessionSummary[] }>('/api/admin/sessions/overview')
  return payload?.sessions ?? []
}

export async function getSessionMessages(chatId: number): Promise<SessionMessage[]> {
  const payload = await requestJson<{ sessions: SessionMessage[] }>(
    `/api/admin/sessions?chat_id=${encodeURIComponent(chatId)}`,
  )
  return payload?.sessions ?? []
}

export async function getShortTermMemory(userId: number): Promise<SessionMessage[]> {
  const payload = await requestJson<{ messages: SessionMessage[] }>(
    `/api/admin/memory/short-term?user_id=${encodeURIComponent(userId)}`,
  )
  return payload?.messages ?? []
}

export async function clearShortTermMemory(userId: number): Promise<boolean> {
  const res = await requestJson<{ status: string }>(
    `/api/admin/memory/short-term?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  )
  return res?.status === 'cleared'
}

export async function getLongTermMemory(userId: number, query?: string): Promise<LongTermMemory[]> {
  const params = new URLSearchParams({ user_id: String(userId) })
  if (query?.trim())
    params.set('query', query.trim())
  const payload = await requestJson<{ memories: LongTermMemory[] }>(
    `/api/admin/memory/long-term?${params.toString()}`,
  )
  return payload?.memories ?? []
}

export async function deleteLongTermMemory(pointId: string): Promise<boolean> {
  const res = await requestJson<{ status: string }>(
    `/api/admin/memory/long-term/${encodeURIComponent(pointId)}`,
    { method: 'DELETE' },
  )
  return res?.status === 'deleted'
}

export async function getMemoryProfile(userId: number): Promise<MemoryProfile | null> {
  return requestJson<MemoryProfile>(`/api/admin/memory/profile?user_id=${encodeURIComponent(userId)}`)
}

export async function updateMemoryProfile(userId: number, patch: MemoryProfilePatch): Promise<MemoryProfile | null> {
  return requestJson<MemoryProfile>(
    `/api/admin/memory/profile/${encodeURIComponent(userId)}`,
    { method: 'PUT', body: JSON.stringify(patch) },
  )
}

/**
 * 读取联网搜索配置。返回 null 表示后台配置服务不可达或返回了非 2xx。
 */
export async function getWebSearchConfig(): Promise<WebSearchConfig | null> {
  const payload = await requestJson<{ web_search?: WebSearchConfig }>('/api/admin/config')
  return payload?.web_search ?? null
}

/**
 * 修改联网搜索配置，并返回服务端重新读回的最新状态。
 *
 * PATCH 接口只回 {status, reloaded}，所以这里写完必须再 GET 一次：一是让调用方
 * 拿到权威状态（用于在保存失败时回滚界面），二是能确认改动真的落盘了。
 */
export async function updateWebSearchConfig(
  patch: WebSearchConfigPatch,
): Promise<WebSearchConfig | null> {
  const res = await requestJson<{ status: string }>('/api/admin/config', {
    method: 'PATCH',
    body: JSON.stringify({ web_search: patch }),
  })
  if (res?.status !== 'ok')
    return null
  return getWebSearchConfig()
}

// ---------------------------------------------------------------------------
// 向着星联动（integration.tothestars）：生活数据权限矩阵 + 主动策略
// ---------------------------------------------------------------------------

/**
 * 四档权限，含义与 shared/life_data_permissions.py 完全一致：
 * - read_write_proactive: 可读、可写、可主动提及（工具进模型可见表 + 可写）
 * - read_only:            可读、不可写、可主动提及
 * - on_request:           只有用户明确问起才可读，不主动提
 * - hidden:               完全不可见（工具不进模型可见表，提示词也不注入）
 */
export type LifeDataTier
  = | 'read_write_proactive'
    | 'read_only'
    | 'on_request'
    | 'hidden'

export type LifeDataCategory
  = | 'commissions'
    | 'schedule'
    | 'legends'
    | 'wallet'
    | 'journal'
    | 'journal_text'
    | 'focus'

export interface TothestarsPermissions {
  commissions: LifeDataTier
  schedule: LifeDataTier
  legends: LifeDataTier
  wallet: LifeDataTier
  journal: LifeDataTier
  journal_text: LifeDataTier
  focus: LifeDataTier
}

/** 主动提及策略（触发链路在下一阶段接入，这里先负责配置的读写与落盘）。 */
export interface TothestarsProactiveConfig {
  enabled: boolean
  /** 两段 HH:MM：静默开始时、静默结束时（可跨零点，如 23:00 → 07:00）。 */
  quiet_hours: string[]
  max_per_hour: number
  max_per_day: number
}

/** 写入通道：local=进程内直连向着星数据库（同机推荐）；remote=HTTP + 失败暂存重试。 */
export type TothestarsWriteMode = 'local' | 'remote'

export interface TothestarsConfig {
  enabled: boolean
  endpoint: string
  timeout_seconds: number
  permissions: TothestarsPermissions
  proactive: TothestarsProactiveConfig
  write_mode: TothestarsWriteMode
  /** 本地直连时的向着星项目根目录（数据库为 <root>/data/growth_system.db）。 */
  local_project_root: string
}

/** 只传需要改的字段；permissions / proactive 都按子键合并，不整段覆盖。 */
export interface TothestarsConfigPatch {
  enabled?: boolean
  endpoint?: string
  timeout_seconds?: number
  permissions?: Partial<TothestarsPermissions>
  proactive?: Partial<TothestarsProactiveConfig>
  write_mode?: TothestarsWriteMode
  local_project_root?: string
}

export async function getTothestarsConfig(): Promise<TothestarsConfig | null> {
  const payload = await requestJson<{ tothestars?: TothestarsConfig }>('/api/admin/config')
  return payload?.tothestars ?? null
}

/**
 * 保存权限矩阵 / 主动策略，并返回服务端读回的最新状态（写入失败返回 null，
 * 调用方据此提示"未落盘"并保留界面状态，见 WebSearch.vue 的同一约定）。
 */
export async function updateTothestarsConfig(
  patch: TothestarsConfigPatch,
): Promise<TothestarsConfig | null> {
  const res = await requestJson<{ status: string }>('/api/admin/config', {
    method: 'PATCH',
    body: JSON.stringify({ tothestars: patch }),
  })
  if (res?.status !== 'ok')
    return null
  return getTothestarsConfig()
}

// ---------------------------------------------------------------------------
// 生活概览 HUD：经 Admin 代理读向着星今日快照（避免跨域）
// ---------------------------------------------------------------------------

export interface LifeCommission {
  id: number
  title: string
  difficulty?: string
  category?: string
  is_required: boolean
  is_completed: boolean
  points?: number
}

export interface LifeSchedulePlan {
  id: number
  title: string
  start: string
  end: string
  kind: string
  completed: boolean
  quest_id?: number | null
}

export interface LifeLegend {
  id: number
  title: string
  deadline?: string | null
  progress?: { done: number, total: number }
  remaining_days?: number | null
}

export interface LifeSnapshot {
  date: string
  is_vacation?: boolean
  condition?: {
    total_points: number
    required_all_done: boolean
    can_bank: boolean
    explain: string
  }
  commissions?: LifeCommission[]
  schedule?: { date: string, plans: LifeSchedulePlan[] }
  legends?: LifeLegend[]
  wallet?: { practice_points: number, growth_points: number }
}

/**
 * 读取向着星今日生活快照。返回 null 表示 Admin 或向着星服务不可达。
 * 数据字段按权限配置裁剪：她看不到的类目，这里也不会出现。
 */
export async function getLifeSnapshot(): Promise<LifeSnapshot | null> {
  return requestJson<LifeSnapshot>('/api/admin/tothestars/snapshot')
}
