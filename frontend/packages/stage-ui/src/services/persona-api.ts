/**
 * Persona Admin REST API client with graceful degradation fallback.
 * Interacts with http://localhost:8094/api/admin/personas endpoints.
 */

/**
 * 角色卡里的「联网搜索」段（Layer 2）。字段含义、预设清单与填写注意事项见
 * 设置页右上角的「角色卡字段说明」。
 *
 * 缺省语义：整段不填 = enabled: true（跟随全局开关）、style: neutral。
 * 全部子字段都是可选的，后台按 key 逐个合并，不会整段覆盖。
 */
export interface PersonaWebSearchSettings {
  /** 这个人设会不会上网。false = 模型根本看不到联网工具（不是"看到了但被劝阻"）。 */
  enabled?: boolean
  /** 说法预设。与 shared/web_search_persona.py 的 STYLE_PRESETS 一一对应。 */
  style?: 'neutral' | 'phone' | 'divination' | 'library' | 'informant' | 'oracle' | 'custom'
  /** 这个能力在角色语境里叫什么（为空则用预设默认）。 */
  alias?: string
  /** 查不到时怎么说（强烈建议填：没有出口的角色一定会编造）。 */
  missed?: string
  /** 正在查的时候在界面上显示什么（Layer 4 的呼吸光提示文案，为空则用预设默认）。 */
  searching?: string
  /** 整段自定义「怎么说出口」，覆盖预设说法；但"该查/不该查"的硬规则不可覆盖。 */
  framing?: string
}

export interface PersonaPatch {
  name?: string
  appearance?: string
  base_prompt?: string
  sleepy_prompt?: string
  knowledge_scope?: string
  forbidden_topics?: string
  web_search?: PersonaWebSearchSettings
}

export interface PersonaRecord extends PersonaPatch {
  id: string
  tts_provider?: string
  voice_id?: string
}

/** 角色卡列表摘要（GET /api/admin/personas），用于设置页的人设选择器。 */
export interface PersonaSummary {
  id: string
  name?: string
  tts_provider?: string
  voice_id?: string
  is_active?: boolean
}

export interface PersonaListResult {
  personas: PersonaSummary[]
  active_id: string
}

const ADMIN_API_BASE = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_ADMIN_API_BASE)
  ? import.meta.env.VITE_ADMIN_API_BASE
  : 'http://localhost:8094'

/**
 * List all persona cards known to the Admin backend (id/name/voice/is_active).
 * Returns null if Admin backend is unreachable.
 */
export async function listPersonas(): Promise<PersonaListResult | null> {
  try {
    const res = await fetch(`${ADMIN_API_BASE}/api/admin/personas`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
    })
    if (!res.ok)
      return null
    const data = (await res.json()) as PersonaListResult
    return Array.isArray(data?.personas) ? data : null
  }
  catch {
    return null
  }
}

/**
 * Fetch persona details from Admin API.
 * Returns null if Admin backend is unreachable or returns an error.
 */
export async function fetchPersona(personaId: string): Promise<PersonaRecord | null> {
  try {
    const res = await fetch(`${ADMIN_API_BASE}/api/admin/personas/${encodeURIComponent(personaId)}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
    })
    if (!res.ok)
      return null
    return (await res.json()) as PersonaRecord
  }
  catch {
    return null
  }
}

/**
 * Send whitelist PATCH update to Admin API.
 * Returns true on success, false if Admin backend is unreachable or errors out.
 */
export async function patchPersona(personaId: string, patch: PersonaPatch): Promise<boolean> {
  try {
    const res = await fetch(`${ADMIN_API_BASE}/api/admin/personas/${encodeURIComponent(personaId)}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(patch),
    })
    return res.ok
  }
  catch {
    return false
  }
}
