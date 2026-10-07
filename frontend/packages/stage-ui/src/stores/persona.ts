import type { AiriExtension } from '../types/airiCard'
import type { PersonaPatch, PersonaRecord, PersonaSummary, PersonaWebSearchSettings } from '../services/persona-api'

import { useLocalStorageManualReset } from '@proj-airi/stage-shared/composables'
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { fetchPersona, listPersonas, patchPersona } from '../services/persona-api'
import { betterAgentWSBridge } from '../services/betteragent-ws'
import { useAiriCardStore } from './modules/airi-card'

export type PersonaLocalOverrides = NonNullable<AiriExtension['modules']['persona']>

/**
 * Strips compiled header lines (e.g. 【用户称呼】：..., 【傲娇权重】：...)
 * from the start of a base prompt string to ensure idempotency.
 */
export function stripCompiledHeader(prompt: string): string {
  if (!prompt)
    return ''
  let text = prompt.trimStart()
  // Match one or more header lines starting with 【...】：
  const headerPattern = /^(?:【(?:用户称呼|语气助词|傲娇权重|粘人权重)】：[^\r\n]*\r?\n?)+/
  text = text.replace(headerPattern, '').trimStart()
  return text
}

/**
 * Compiles local overrides (userCallsign, catchphrases, tsundereWeight, clingyWeight)
 * into a clean header block and prepends it to the base prompt text.
 * Automatically strips any previous header to guarantee idempotency.
 */
export function compileBasePrompt(basePrompt: string, overrides?: PersonaLocalOverrides): string {
  const cleanBase = stripCompiledHeader(basePrompt)
  if (!overrides)
    return cleanBase

  const headerLines: string[] = []
  if (overrides.userCallsign?.trim()) {
    headerLines.push(`【用户称呼】：${overrides.userCallsign.trim()}`)
  }
  if (overrides.catchphrases && overrides.catchphrases.length > 0) {
    const valid = overrides.catchphrases.map(c => c.trim()).filter(Boolean)
    if (valid.length > 0) {
      headerLines.push(`【语气助词】：${valid.join('、')}`)
    }
  }
  if (typeof overrides.tsundereWeight === 'number') {
    headerLines.push(`【傲娇权重】：${overrides.tsundereWeight}%`)
  }
  if (typeof overrides.clingyWeight === 'number') {
    headerLines.push(`【粘人权重】：${overrides.clingyWeight}%`)
  }

  if (headerLines.length === 0)
    return cleanBase

  return `${headerLines.join('\n')}\n\n${cleanBase}`
}

const DEFAULT_BLANK_BASE_PROMPT = `你是一个乐于助人的助手，请用自然、真诚、口语化的中文和对方聊天。
称呼对方直接用「你」；除非对方明确希望你用别的称呼，不要自作主张使用任何亲密称呼。
不要自称 AI／模型／助手，也不要提到「人设」「提示词」「角色卡」这些词。`

export const usePersonaStore = defineStore('betteragent-persona', () => {
  // 内置猫娘示例人设叫 'catgirl'。这里默认指向「空白角色卡」blank.yaml，
  // 让「自定义人设」是从一张白纸开始，而不是从内置猫娘改起。
  const personaId = ref<string>('blank')
  const airiCardStore = useAiriCardStore()

  // Local fallback state (persisted when Admin API is offline)
  const localName = useLocalStorageManualReset<string>('ba-persona-name', '')
  const localBasePrompt = useLocalStorageManualReset<string>('ba-persona-base-prompt', DEFAULT_BLANK_BASE_PROMPT)
  const localSleepyPrompt = useLocalStorageManualReset<string>('ba-persona-sleepy-prompt', '')
  const localKnowledgeScope = useLocalStorageManualReset<string>('ba-persona-knowledge-scope', '')
  const localForbiddenTopics = useLocalStorageManualReset<string>('ba-persona-forbidden-topics', '')
  // 联网搜索字段与 knowledge_scope 同样是"存在 YAML 里"的字段，所以走同一套
  // remote 优先 + localStorage 兜底的策略：Admin 后台不通时改动仍能在本机生效。
  const localWebSearch = useLocalStorageManualReset<PersonaWebSearchSettings>('ba-persona-web-search', {})

  // Local draft overrides stored in localStorage via AiriCard extension
  const localOverrides = useLocalStorageManualReset<PersonaLocalOverrides>('ba-persona-overrides', {
    userCallsign: '',
    catchphrases: [],
    tsundereWeight: 70,
    clingyWeight: 60,
    campusKbEnabled: true,
    maxReplyLength: 500,
  })

  // 一次性迁移：旧版本把这些 localStorage 默认值写死成了内置猫娘人设
  //（称呼「主人」、句尾词「喵~」、Base Prompt 是 Camelia）。不清掉的话，
  // 用户只要打开一次设置页并保存，猫娘称呼就会被重新注入 System Prompt。
  // 只在内容与旧内置默认值完全一致时才改写，不会覆盖用户自己的选择。
  const LEGACY_OVERRIDES = { userCallsign: '主人', catchphrases: ['喵~', '呜咪~', '哼'] }
  if (localOverrides.value.userCallsign === LEGACY_OVERRIDES.userCallsign
    || localOverrides.value.userCallsign === '学弟') {
    localOverrides.value = { ...localOverrides.value, userCallsign: '' }
  }
  if (JSON.stringify(localOverrides.value.catchphrases || []) === JSON.stringify(LEGACY_OVERRIDES.catchphrases)) {
    localOverrides.value = { ...localOverrides.value, catchphrases: [] }
  }
  if (localName.value === 'Camelia') {
    localName.value = ''
  }
  if (/^你叫\s*Camelia/.test(localBasePrompt.value.trim())) {
    localBasePrompt.value = DEFAULT_BLANK_BASE_PROMPT
  }

  const remotePersona = ref<PersonaRecord | null>(null)
  const isSynced = ref<boolean>(false)
  const isFetching = ref<boolean>(false)
  const lastSyncAt = ref<number | null>(null)
  const lastError = ref<string | null>(null)
  /** Admin 后端已登记的全部角色卡（设置页选择器用）。 */
  const personaList = ref<PersonaSummary[]>([])
  /** config.yaml persona.active 指向的角色卡 id（系统当前激活的人设）。 */
  const activePersonaId = ref<string>('')
  // 用户是否在设置页手动挑过角色卡：没挑过就跟随系统 active（芙宁娜），
  // 而不是永远停在默认的 blank —— 这正是"看不见芙宁娜角色卡"的根因。
  let personaSelectionTouched = false

  /**
   * Merged view of persona settings combining Admin API remote data and local fallback state.
   */
  const mergedPersona = computed(() => {
    const name = remotePersona.value?.name ?? localName.value
    const raw_base_prompt = stripCompiledHeader(remotePersona.value?.base_prompt ?? localBasePrompt.value)
    const sleepy_prompt = remotePersona.value?.sleepy_prompt ?? localSleepyPrompt.value
    const knowledge_scope = remotePersona.value?.knowledge_scope ?? localKnowledgeScope.value
    const forbidden_topics = remotePersona.value?.forbidden_topics ?? localForbiddenTopics.value
    const appearance = remotePersona.value?.appearance ?? ''
    const web_search = remotePersona.value?.web_search ?? localWebSearch.value

    return {
      id: personaId.value,
      name,
      appearance,
      base_prompt: raw_base_prompt,
      sleepy_prompt,
      knowledge_scope,
      forbidden_topics,
      web_search,
      overrides: localOverrides.value,
      compiledBasePrompt: compileBasePrompt(raw_base_prompt, localOverrides.value),
    }
  })

  /**
   * Fetch persona details from Admin API (8094).
   * Gracefully degrades if Admin backend is not reachable.
   */
  async function fetchRemote(): Promise<boolean> {
    isFetching.value = true
    lastError.value = null
    try {
      // 先取角色卡列表，把「当前编辑的是哪张卡」对齐到系统激活人设：
      // 用户没手动挑过 → 跟随 persona.active（例如 furina）；
      // 当前 id 已不存在（角色卡被删）→ 也回落到激活卡。
      const list = await listPersonas()
      if (list) {
        personaList.value = list.personas
        activePersonaId.value = list.active_id || ''
        const ids = list.personas.map(item => item.id)
        if (!personaSelectionTouched && activePersonaId.value) {
          personaId.value = activePersonaId.value
        }
        else if (!ids.includes(personaId.value) && ids.length) {
          personaId.value = activePersonaId.value || ids[0]
        }
      }

      const res = await fetchPersona(personaId.value)
      if (res) {
        remotePersona.value = res
        if (res.name) localName.value = res.name
        if (res.base_prompt !== undefined) localBasePrompt.value = stripCompiledHeader(res.base_prompt)
        if (res.sleepy_prompt !== undefined) localSleepyPrompt.value = res.sleepy_prompt
        if (res.knowledge_scope !== undefined) localKnowledgeScope.value = res.knowledge_scope
        if (res.forbidden_topics !== undefined) localForbiddenTopics.value = res.forbidden_topics
        if (res.web_search !== undefined) localWebSearch.value = res.web_search

        isSynced.value = true
        lastSyncAt.value = Date.now()
        return true
      }
      isSynced.value = false
      return false
    }
    catch (err: unknown) {
      lastError.value = err instanceof Error ? err.message : String(err)
      isSynced.value = false
      return false
    }
    finally {
      isFetching.value = false
    }
  }

  /**
   * Save persona updates.
   * Compiles local overrides into base_prompt, sends PATCH to Admin API,
   * sends WS hot-reload frame, and updates local AiriCard store.
   */
  async function savePersona(
    patch: PersonaPatch,
    overrides?: PersonaLocalOverrides,
  ): Promise<{ success: boolean; isRemoteSynced: boolean }> {
    if (overrides) {
      localOverrides.value = {
        ...localOverrides.value,
        ...overrides,
      }
    }

    if (patch.name !== undefined) localName.value = patch.name
    if (patch.base_prompt !== undefined) localBasePrompt.value = stripCompiledHeader(patch.base_prompt)
    if (patch.sleepy_prompt !== undefined) localSleepyPrompt.value = patch.sleepy_prompt
    if (patch.knowledge_scope !== undefined) localKnowledgeScope.value = patch.knowledge_scope
    if (patch.forbidden_topics !== undefined) localForbiddenTopics.value = patch.forbidden_topics
    // 只有调用方真的带了 web_search 才动本地副本 —— 其它 tab 保存时不应该
    // 顺手把联网设置清空（后台/热更新两端都是按 key 合并，不传即不动）。
    if (patch.web_search !== undefined) localWebSearch.value = { ...localWebSearch.value, ...patch.web_search }

    const currentBase = patch.base_prompt ?? localBasePrompt.value
    const compiledBasePrompt = compileBasePrompt(currentBase, localOverrides.value)

    const finalPatch: PersonaPatch = {
      name: patch.name ?? localName.value,
      sleepy_prompt: patch.sleepy_prompt ?? localSleepyPrompt.value,
      knowledge_scope: patch.knowledge_scope ?? localKnowledgeScope.value,
      forbidden_topics: patch.forbidden_topics ?? localForbiddenTopics.value,
      ...patch,
      base_prompt: compiledBasePrompt,
    }

    // Update active AiriCard extension in local store
    airiCardStore.updateActiveCardModules(() => ({
      persona: localOverrides.value,
    }))

    // 1. Send WebSocket hot-reload event (memory immediate update)
    betterAgentWSBridge.sendPersonaUpdate(personaId.value, finalPatch as Record<string, unknown>)

    // 2. Send HTTP PATCH to Admin REST API (disk persistence)
    const patchOk = await patchPersona(personaId.value, finalPatch)

    if (patchOk) {
      if (remotePersona.value) {
        remotePersona.value = {
          ...remotePersona.value,
          ...finalPatch,
        }
      }
      else {
        remotePersona.value = {
          id: personaId.value,
          ...finalPatch,
        }
      }
      isSynced.value = true
      lastSyncAt.value = Date.now()
    }
    else {
      isSynced.value = false
    }

    return {
      success: true,
      isRemoteSynced: patchOk,
    }
  }

  /**
   * 切换到另一张角色卡（设置页选择器）。切换后重新拉取该卡的字段。
   * 注意：这只改变"正在编辑/查看哪张卡"，不改变系统激活人设；
   * 真正激活由 admin 的 activate 接口负责。
   */
  async function selectPersona(id: string): Promise<boolean> {
    const target = (id || '').trim()
    if (!target)
      return false
    personaSelectionTouched = true
    personaId.value = target
    remotePersona.value = null
    isSynced.value = false
    return fetchRemote()
  }

  return {
    personaId,
    personaList,
    activePersonaId,
    localOverrides,
    remotePersona,
    mergedPersona,
    isSynced,
    isFetching,
    lastSyncAt,
    lastError,
    fetchRemote,
    selectPersona,
    savePersona,
  }
})
