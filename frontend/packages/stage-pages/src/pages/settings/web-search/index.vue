<script setup lang="ts">
import type { WebSearchConfig } from '@proj-airi/stage-ui/services/betteragent-admin-api'

import { Button, FieldCheckbox, FieldInput } from '@proj-airi/ui'
import {
  getWebSearchConfig,
  updateWebSearchConfig,
} from '@proj-airi/stage-ui/services/betteragent-admin-api'
import { computed, onMounted, ref } from 'vue'

const config = ref<WebSearchConfig | null>(null)
const loading = ref(false)
const saving = ref(false)
const apiKeyInput = ref('')
const message = ref('')
const messageKind = ref<'info' | 'success' | 'error'>('info')

// 开关状态由服务端返回的配置驱动；本地不保留"以为改了"的状态，
// 保存失败时直接重新拉一次服务端状态即可自然回滚。
const enabled = computed({
  get: () => config.value?.enabled ?? false,
  set: (value: boolean) => {
    void toggleEnabled(value)
  },
})

// 开关打开但没配 Key 时，cognitive 服务会按"不可用"处理，界面必须说清楚，
// 否则会让人以为联网已经生效了。
const keyMissing = computed(() => !!config.value?.enabled && !config.value.key_set)

const keyDescription = computed(() => {
  if (config.value?.key_set)
    return `已配置：${config.value.key_masked}。留空并保存可清空。`
  return '尚未配置。填入搜索服务的 API Key 后保存。'
})

function setMessage(text: string, kind: 'info' | 'success' | 'error' = 'info') {
  message.value = text
  messageKind.value = kind
}

async function refresh() {
  loading.value = true
  try {
    const next = await getWebSearchConfig()
    config.value = next
    if (!next)
      setMessage('读取不到配置：请确认后台服务（:8094）已启动。', 'error')
  }
  finally {
    loading.value = false
  }
}

async function toggleEnabled(value: boolean) {
  if (saving.value || !config.value)
    return
  saving.value = true
  setMessage('')
  try {
    const next = await updateWebSearchConfig({ enabled: value })
    if (!next) {
      setMessage('保存失败，开关已还原。', 'error')
      await refresh()
      return
    }
    config.value = next
    setMessage(
      next.enabled
        ? (next.key_set ? '联网搜索已开启。' : '联网搜索已开启，但还没填 API Key，暂时不可用。')
        : '联网搜索已关闭，数字人不会联网。',
      next.enabled && !next.key_set ? 'info' : 'success',
    )
  }
  finally {
    saving.value = false
  }
}

async function saveApiKey() {
  if (saving.value || !config.value)
    return
  saving.value = true
  setMessage('')
  try {
    const next = await updateWebSearchConfig({ api_key: apiKeyInput.value.trim() })
    if (!next) {
      setMessage('保存 API Key 失败。', 'error')
      return
    }
    config.value = next
    apiKeyInput.value = ''
    setMessage(next.key_set ? 'API Key 已保存。' : 'API Key 已清空。', 'success')
  }
  finally {
    saving.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div class="flex flex-col gap-4 pb-4">
    <div
      v-if="message"
      class="rounded-lg px-3 py-2 text-sm"
      :class="messageKind === 'success'
        ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400'
        : messageKind === 'error'
          ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
          : 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300'"
    >
      {{ message }}
    </div>

    <div class="rounded-xl border border-neutral-200/60 bg-white/70 p-4 shadow-sm dark:border-neutral-800/60 dark:bg-neutral-900/60">
      <div class="text-lg font-medium">
        总开关
      </div>
      <div class="mt-3">
        <FieldCheckbox
          v-model="enabled"
          :disabled="loading || saving || !config"
          label="启用联网搜索"
          description="关闭时数字人完全看不到联网工具，等于本项目没有接入联网功能；出问题时把它关掉即可完整回退。"
        />
      </div>
      <div v-if="keyMissing" class="mt-3 rounded-lg bg-amber-100 px-3 py-2 text-xs text-amber-800 dark:bg-amber-900/30 dark:text-amber-300">
        开关已打开，但还没有配置 API Key，当前按「不可用」处理。
      </div>
    </div>

    <div class="rounded-xl border border-neutral-200/60 bg-white/70 p-4 shadow-sm dark:border-neutral-800/60 dark:bg-neutral-900/60">
      <div class="text-lg font-medium">
        搜索服务凭据
      </div>
      <div class="mt-1 text-xs text-neutral-500 dark:text-neutral-400">
        当前服务商：{{ config?.provider ?? '—' }}，写入位置：{{ config?.api_key_env ?? '—' }}（根目录 .env）
      </div>
      <div class="mt-3 flex flex-col gap-3">
        <FieldInput
          v-model="apiKeyInput"
          type="password"
          label="API Key"
          :description="keyDescription"
          placeholder="填写后点右侧保存"
        />
        <div class="flex justify-end">
          <Button :disabled="saving || !config" @click="saveApiKey">
            保存 API Key
          </Button>
        </div>
      </div>
    </div>

    <div class="rounded-xl border border-neutral-200/60 bg-white/70 p-4 shadow-sm dark:border-neutral-800/60 dark:bg-neutral-900/60">
      <div class="text-lg font-medium">
        当前生效参数
      </div>
      <dl class="mt-3 grid grid-cols-2 gap-y-2 text-sm">
        <dt class="text-neutral-500 dark:text-neutral-400">
          单轮最多搜索次数
        </dt>
        <dd>{{ config?.max_calls_per_turn ?? '—' }}</dd>
        <dt class="text-neutral-500 dark:text-neutral-400">
          每次返回条数
        </dt>
        <dd>{{ config?.top_k ?? '—' }}</dd>
        <dt class="text-neutral-500 dark:text-neutral-400">
          超时（秒）
        </dt>
        <dd>{{ config?.timeout_seconds ?? '—' }}</dd>
      </dl>
      <div class="mt-2 text-xs text-neutral-500 dark:text-neutral-400">
        这些值写在 config/config.yaml 的 tools.web_search 下，改完需要重启相关服务。
      </div>
    </div>
  </div>
</template>

<route lang="yaml">
meta:
  layout: settings
  title: 联网搜索
  subtitle: 设置
  description: 控制数字人是否可以联网查询实时信息
  icon: i-solar:global-bold-duotone
  settingsEntry: true
  order: 7
  stageTransition:
    name: slide
</route>
