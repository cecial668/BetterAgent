<script setup lang="ts">
import type { WebSearchConfig, WebSearchConfigPatch } from '../../services/betteragent-admin-api'

import { Button, FieldCheckbox, FieldInput } from '@proj-airi/ui'
import { computed, onMounted, ref } from 'vue'

import { getWebSearchConfig, updateWebSearchConfig } from '../../services/betteragent-admin-api'

/**
 * 联网搜索：全局总开关（L0）+ 搜索服务 Key。
 *
 * 这一页直接读写 BetterAgent 后台（admin/backend，:8094），**不再**走 AIRI 上游
 * 那套只存 localStorage 的 module store —— 那个 Key 只有浏览器自己看得见，Python
 * 认知服务永远读不到，所以在这个项目里填了等于没填（这正是它以前"开了也没用"的原因）。
 *
 * 落盘位置：
 *   · Key      -> 根目录 .env 的 TAVILY_API_KEY
 *   · 开关/数值 -> config/config.yaml 的 tools.web_search
 * 两者都由后台发 agent.config.reloaded 热刷新，**不需要重启 runner.py**。
 *
 * 「用什么说法把查资料说出口」不在这里，那是角色卡的 web_search.* —— 见
 * 设置 → 角色人设与交互边界 → 联网能力。
 */

const loading = ref(true)
const saving = ref(false)
/** 后台不可达时为 true：此时界面只读，并给出直接改文件的手动说明。 */
const unreachable = ref(false)
const config = ref<WebSearchConfig | null>(null)
const notice = ref<{ type: 'success' | 'warn', msg: string } | null>(null)

const enabled = ref(false)
const apiKey = ref('')
const topK = ref(5)
const timeoutSeconds = ref(15)
const maxCallsPerTurn = ref(1)

const keySet = computed(() => !!config.value?.key_set)
/** 开关开着但没 Key —— cognitive 服务会按"不可用"处理，模型连工具都看不到。 */
const enabledWithoutKey = computed(() => enabled.value && !keySet.value)

function applyConfig(cfg: WebSearchConfig) {
  config.value = cfg
  enabled.value = cfg.enabled
  topK.value = cfg.top_k
  timeoutSeconds.value = cfg.timeout_seconds
  maxCallsPerTurn.value = cfg.max_calls_per_turn
}

async function load() {
  loading.value = true
  notice.value = null
  const cfg = await getWebSearchConfig()
  if (cfg) {
    unreachable.value = false
    applyConfig(cfg)
  }
  else {
    unreachable.value = true
    config.value = null
  }
  loading.value = false
}

async function save() {
  saving.value = true
  notice.value = null
  try {
    const patch: WebSearchConfigPatch = {
      enabled: enabled.value,
      top_k: topK.value,
      timeout_seconds: timeoutSeconds.value,
      max_calls_per_turn: maxCallsPerTurn.value,
    }
    // 留空 = 不改 Key。这样用户只来改开关时，不会把已配置的 Key 覆盖成空串。
    if (apiKey.value.trim())
      patch.api_key = apiKey.value.trim()

    const next = await updateWebSearchConfig(patch)
    if (next) {
      applyConfig(next)
      apiKey.value = ''
      notice.value = { type: 'success', msg: '已保存到 config.yaml / .env，并已热刷新（无需重启）' }
    }
    else {
      notice.value = { type: 'warn', msg: '保存失败：后台没有返回成功。改动未落盘，请检查 Admin 服务 (:8094) 是否在运行。' }
    }
  }
  finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <div flex="~ col gap-6">
    <!-- 后台不可达：给出手动配置的确切位置，而不是让页面看起来"能用但没反应" -->
    <div v-if="unreachable" class="flex flex-col gap-2 rounded-lg bg-amber-100 p-4 text-sm text-amber-900 dark:bg-amber-500/15 dark:text-amber-200">
      <div class="font-semibold">
        配置后台 (:8094) 连不上，本页暂时无法保存
      </div>
      <div>
        本页需要 BetterAgent 的 Admin 服务在运行。请确认 <code>python runner.py</code> 已启动，然后点下面的「重新读取」。
      </div>
      <details class="text-xs">
        <summary class="cursor-pointer font-medium">
          一定要现在改的话：直接改这两个文件
        </summary>
        <div class="mt-2 flex flex-col gap-1">
          <div><code>config/config.yaml</code> → <code>tools.web_search.enabled: true</code>（缩进 4 个空格）</div>
          <div><code>.env</code> → 末尾加一行 <code>TAVILY_API_KEY=tvly-你的key</code>（等号两侧不要空格、不要引号）</div>
          <div>改完需要重启 <code>python runner.py</code>（手动改文件不会触发热刷新）。</div>
        </div>
      </details>
    </div>

    <div v-else-if="loading" class="text-sm text-neutral-500 dark:text-neutral-400">
      正在读取联网搜索配置…
    </div>

    <template v-else>
      <!-- 保存结果 -->
      <div
        v-if="notice"
        class="flex items-center justify-between rounded-lg p-3 text-sm"
        :class="notice.type === 'success'
          ? 'bg-emerald-500/10 text-emerald-700 border border-emerald-500/20 dark:text-emerald-400'
          : 'bg-amber-500/10 text-amber-700 border border-amber-500/20 dark:text-amber-400'"
      >
        <span>{{ notice.msg }}</span>
        <button class="opacity-60 hover:opacity-100" @click="notice = null">
          ×
        </button>
      </div>

      <!-- 总开关 -->
      <FieldCheckbox
        v-model="enabled"
        label="启用联网搜索（全局）"
        description="关掉后模型根本看不到搜索工具，等价于本项目从未接入过联网 —— 出问题时把它关掉即可完整回退。"
      />

      <div
        v-if="enabledWithoutKey"
        class="rounded-lg bg-red-100 p-3 text-sm text-red-800 dark:bg-red-500/15 dark:text-red-300"
      >
        ⚠ 开关已打开，但还没有填搜索服务的 Key。此时模型仍然看不到搜索工具（不会失败重试，但也查不了）。请在下面填入 Key。
      </div>

      <!-- Key -->
      <div class="flex flex-col gap-2 rounded-lg border border-neutral-200 p-4 dark:border-neutral-800">
        <FieldInput
          v-model="apiKey"
          type="password"
          label="Tavily API Key"
          placeholder="tvly-..."
          autocomplete="off"
          :description="keySet
            ? `已配置：${config?.key_masked ?? '(已设置)'}　留空表示不修改。`
            : '还没有配置。到 app.tavily.com 免费注册即可拿到 Key（每月 1000 次免费，不需要信用卡）。'"
        />
        <div
          class="text-xs"
          :class="keySet ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'"
        >
          {{ keySet ? '✔ Key 已就绪' : '当前状态：未配置 Key —— 联网搜索不可用' }}
        </div>
      </div>

      <!-- 数值项折叠起来：默认值通常够用 -->
      <details class="rounded-lg border border-neutral-200 dark:border-neutral-800">
        <summary class="cursor-pointer p-4 text-sm font-medium">
          高级设置（结果条数 / 超时 / 每轮次数）
        </summary>
        <div class="flex flex-col gap-4 p-4 pt-0">
          <FieldInput
            v-model="topK"
            type="number"
            label="每次返回条数 (top_k)"
            description="1～20。条数越多上下文越占地方，默认 5。"
          />
          <FieldInput
            v-model="timeoutSeconds"
            type="number"
            label="超时秒数 (timeout_seconds)"
            description="1～120。搜索通常 3～8 秒，默认 15。"
          />
          <FieldInput
            v-model="maxCallsPerTurn"
            type="number"
            label="单轮最多搜索次数 (max_calls_per_turn)"
            description="1～5。用于控成本，默认 1（每次搜索消耗 1 个 Tavily credit）。"
          />
        </div>
      </details>

      <!-- 角色卡那侧的分工说明 -->
      <div class="rounded-lg bg-sky-50 p-4 text-xs text-sky-800 dark:bg-sky-500/10 dark:text-sky-300">
        <div class="font-semibold">
          这一页只管"能不能联网"
        </div>
        <div class="mt-1">
          「什么时候该查、什么时候绝不能查、查到了怎么说出口、正在查的时候显示什么字」都由
          <b>角色卡</b>决定 —— 见 设置 → 角色人设与交互边界 → 联网能力。这样换一个角色（古代剑客、
          清朝格格）不用改这里的任何设置。
        </div>
      </div>

      <div class="flex justify-end gap-2">
        <Button :disabled="loading || saving" class="!py-2" @click="load">
          重新读取
        </Button>
        <Button :disabled="saving" class="!py-2" @click="save">
          <div v-if="saving" class="i-svg-spinners:90-ring-with-bg mr-2 text-sm" />
          保存配置
        </Button>
      </div>
    </template>
  </div>
</template>
