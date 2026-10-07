<script setup lang="ts">
import type { PersonaWebSearchSettings } from '@proj-airi/stage-ui/services/persona-api'

import { Button, FieldInput, FieldSelect, FieldTextArea } from '@proj-airi/ui'
import { computed, ref, watch } from 'vue'

import { usePersonaStore } from '@proj-airi/stage-ui/stores/persona'

type WebSearchStyle = NonNullable<PersonaWebSearchSettings['style']>

const personaStore = usePersonaStore()

// 预设清单必须与 shared/web_search_persona.py 的 STYLE_PRESETS 保持一致。
// 前端这份只负责"显示中文名 + 该预设的默认说法"，真正的提示词渲染在 Python 侧。
const STYLE_OPTIONS: { label: string, value: WebSearchStyle, description: string }[] = [
  { label: '中性（不角色化）', value: 'neutral', description: '默认。不带任何表演色彩的说明，跟任何世界观都不冲突' },
  { label: '随手掏手机', value: 'phone', description: '现代日常：「我刚翻了下手机——」' },
  { label: '掐指一算', value: 'divination', description: '仙侠 / 神明：「让我卜一卦……」' },
  { label: '翻查典籍', value: 'library', description: '学者 / 古典：「让我查查典籍……」' },
  { label: '托人打听', value: 'informant', description: '侦探 / 江湖：「我让人去打听了一下……」' },
  { label: '感知世界', value: 'oracle', description: '超能力 / 灵媒：「让我听听风里的声音……」' },
  { label: '完全自定义', value: 'custom', description: '自己写下面的「自定义说法」，会覆盖预设' },
]

const enabled = ref(true)
const style = ref<WebSearchStyle>('neutral')
const alias = ref('')
const missed = ref('')
const searching = ref('')
const framing = ref('')
const isSaving = ref(false)
const saveNotice = ref<{ type: 'success' | 'warn', msg: string } | null>(null)

watch(
  () => personaStore.mergedPersona,
  (merged) => {
    const ws = merged.web_search ?? {}
    // 缺省语义与 Python 侧完全一致：不填 = 跟随全局开关、中性说法。
    enabled.value = ws.enabled ?? true
    style.value = ws.style ?? 'neutral'
    alias.value = ws.alias ?? ''
    missed.value = ws.missed ?? ''
    searching.value = ws.searching ?? ''
    framing.value = ws.framing ?? ''
  },
  { immediate: true },
)

const currentPreset = computed(() => STYLE_OPTIONS.find(o => o.value === style.value) ?? STYLE_OPTIONS[0])

// 只做提示用，避免用户以为"填了 alias 就等于改了全部说法"。
const usesPresetVerb = computed(() => !framing.value.trim() && style.value !== 'custom')

async function handleSave() {
  isSaving.value = true
  saveNotice.value = null
  try {
    const payload: PersonaWebSearchSettings = {
      enabled: enabled.value,
      style: style.value,
      alias: alias.value.trim(),
      missed: missed.value.trim(),
      searching: searching.value.trim(),
      framing: framing.value.trim(),
    }
    const res = await personaStore.savePersona({ web_search: payload })
    if (res.isRemoteSynced) {
      saveNotice.value = { type: 'success', msg: '联网设置已保存到角色卡（热更新已生效，无需重启）' }
    }
    else {
      saveNotice.value = { type: 'warn', msg: 'Admin 服务 (8094) 未打通，设置暂存在本地，未写入角色卡文件' }
    }
  }
  finally {
    isSaving.value = false
  }
}
</script>

<template>
  <div class="flex flex-col gap-6">
    <!-- Save Status Banner -->
    <div
      v-if="saveNotice"
      class="rounded-lg p-3 text-sm flex items-center justify-between"
      :class="saveNotice.type === 'success'
        ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20'
        : 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20'"
    >
      <div class="flex items-center gap-2">
        <div :class="saveNotice.type === 'success' ? 'i-solar:check-circle-bold' : 'i-solar:danger-triangle-bold'" class="text-base" />
        <span>{{ saveNotice.msg }}</span>
      </div>
      <button class="opacity-60 hover:opacity-100" @click="saveNotice = null">
        <div class="i-solar:close-circle-bold text-base" />
      </button>
    </div>

    <!-- Persona-level switch -->
    <div class="flex items-center justify-between rounded-xl border border-neutral-200 bg-neutral-50/50 p-4 dark:border-neutral-800 dark:bg-neutral-900/40">
      <div>
        <div class="font-medium text-sm text-neutral-800 dark:text-neutral-200 flex items-center gap-2">
          <div class="i-solar:global-bold text-primary-500" />
          让这个角色可以联网 (web_search.enabled)
        </div>
        <div class="text-xs text-neutral-400 mt-0.5">
          关掉后模型<b>根本看不到</b>联网工具，连"想查"的念头都不会有 —— 这是彻底回退，不是口头劝阻。
          古代剑客、清朝格格这类人设应该关掉它。
        </div>
      </div>
      <label class="relative inline-flex cursor-pointer items-center">
        <input v-model="enabled" type="checkbox" class="peer sr-only">
        <div class="h-6 w-11 rounded-full bg-neutral-300 transition-colors peer-checked:bg-primary-500 dark:bg-neutral-700 peer-focus:outline-none after:absolute after:left-0.5 after:top-0.5 after:h-5 after:w-5 after:rounded-full after:bg-white after:transition-all after:content-[''] peer-checked:after:translate-x-5" />
      </label>
    </div>

    <!-- Style preset -->
    <div class="rounded-xl border border-neutral-200 bg-neutral-50/50 p-4 flex flex-col gap-4 dark:border-neutral-800 dark:bg-neutral-900/40">
      <div class="font-medium text-sm text-neutral-800 dark:text-neutral-200 flex items-center gap-2">
        <div class="i-solar:chat-round-line-bold text-primary-500" />
        说法预设 (web_search.style)
      </div>
      <FieldSelect
        v-model="style"
        label="这个角色怎么把「查东西」说出口"
        :description="currentPreset.description"
        :options="STYLE_OPTIONS"
      />
      <p class="text-xs text-neutral-400">
        预设决定{{ usesPresetVerb ? '「怎么说出口」的默认写法' : '默认的说辞（当前已被下方的自定义说法覆盖）' }}；
        「什么时候该查、什么时候绝不能查」是硬规则，任何预设都改不了。
      </p>
    </div>

    <!-- Alias + missed -->
    <div class="rounded-xl border border-neutral-200 bg-neutral-50/50 p-4 flex flex-col gap-4 dark:border-neutral-800 dark:bg-neutral-900/40">
      <div class="font-medium text-sm text-neutral-800 dark:text-neutral-200 flex items-center gap-2">
        <div class="i-solar:magic-stick-3-bold text-primary-500" />
        称呼 / 查不到的说法 / 界面提示
      </div>
      <div class="flex flex-col gap-2">
        <label class="text-sm font-medium text-neutral-800 dark:text-neutral-200">
          这个能力在角色语境里叫什么 (web_search.alias)
        </label>
        <FieldInput v-model="alias" :placeholder="currentPreset.value === 'phone' ? '如: 翻手机查一下' : '留空则用预设默认'" class="w-full" />
      </div>
      <div class="flex flex-col gap-2">
        <label class="text-sm font-medium text-neutral-800 dark:text-neutral-200">
          查不到时怎么说 (web_search.missed)
        </label>
        <FieldInput v-model="missed" placeholder="如: 我翻了半天也没找着……这个我真不知道。" class="w-full" />
        <p class="text-xs text-amber-600 dark:text-amber-400">
          强烈建议填。没有这个出口的角色，会为了维持"无所不知"而开始编造。
        </p>
      </div>
      <div class="flex flex-col gap-2">
        <label class="text-sm font-medium text-neutral-800 dark:text-neutral-200">
          正在查的时候界面显示什么 (web_search.searching)
        </label>
        <FieldInput v-model="searching" placeholder="留空则用预设默认，如: 正在翻手机查资料…" class="w-full" />
        <p class="text-xs text-neutral-400">
          搜索要花好几秒，这几秒里数字人那边会显示一行带呼吸光的提示。这句话是<b>唯一会直接露给用户看的联网文案</b>，所以值得写成角色的口吻。
        </p>
      </div>
    </div>

    <!-- Custom framing -->
    <div class="rounded-xl border border-neutral-200 bg-neutral-50/50 p-4 dark:border-neutral-800 dark:bg-neutral-900/40">
      <FieldTextArea
        v-model="framing"
        :required="false"
        :rows="5"
        label="自定义说法 (web_search.framing)"
        description="留空即用预设。填了会整段覆盖预设的「怎么说出口」，但「该查 / 不该查」的硬规则仍然生效。"
        placeholder="例: 说成你顺手划了两下手机：「等我翻一下手机——」。把结论用你自己的话讲出来，别念网址。"
      />
    </div>

    <!-- Hard rules (read-only explanation) -->
    <div class="rounded-xl border border-primary-500/20 bg-primary-500/5 p-4">
      <div class="font-medium text-sm text-neutral-800 dark:text-neutral-200 flex items-center gap-2">
        <div class="i-solar:shield-check-bold text-primary-500" />
        无论怎么填都会生效的硬规则
      </div>
      <ul class="mt-2 flex flex-col gap-1 text-xs text-neutral-600 dark:text-neutral-300 list-disc pl-5">
        <li>对方明确让你查、或答案依赖现实世界中会变的信息（天气、价格、新闻、赛况）时 → 必须查，而且先说一句再查。</li>
        <li><b>关于角色自己的世界、经历、记忆和感受的一切 → 一律不查</b>（那些是亲历的记忆，查了反而会让人设崩掉）。</li>
        <li>谈感情、求安慰、撒娇、闲聊、起名、写东西的时候 → 不查。</li>
        <li>自己已经知道、且答案不会变 → 不查，凭记忆直接回答。</li>
      </ul>
      <p class="mt-2 text-xs text-neutral-400">
        这些规则的实现位置：<code>shared/web_search_persona.py</code>。它们与全局开关、以及本页的角色开关三层一起决定模型的可见工具表。
      </p>
    </div>

    <!-- Submit Action -->
    <div class="flex justify-end pt-2">
      <Button :disabled="isSaving" class="px-6" @click="handleSave">
        <div v-if="isSaving" class="i-svg-spinners:90-ring-with-bg mr-2 text-base" />
        <div v-else class="i-solar:diskette-bold mr-2 text-base" />
        保存联网设置
      </Button>
    </div>
  </div>
</template>
