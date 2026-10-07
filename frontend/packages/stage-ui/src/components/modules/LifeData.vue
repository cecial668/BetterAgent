<script setup lang="ts">
import type { LifeDataCategory, TothestarsConfig, TothestarsConfigPatch, TothestarsWriteMode, LifeDataTier } from '../../services/betteragent-admin-api'

import { Button, FieldCheckbox, FieldInput } from '@proj-airi/ui'
import { computed, onMounted, ref } from 'vue'

import { useLifeDataStore } from '../../stores/modules/life-data'

/**
 * 生活数据（向着星）：她能看到什么、能动什么、什么时候可以主动开口。
 *
 * 这一页直接读写 BetterAgent 后台（admin/backend，:8094）→ `config/config.yaml`
 * 的 `integration.tothestars`，由后台发 `agent.config.reloaded` 热刷新：
 * 认知服务的工具门控（模型可见工具表）与提示词注入每轮实时读取，保存后立即生效。
 *
 * 设计口径（作品集核心机制「AI 应该知道多少」）：
 * - 权限四档按类目独立配置，默认最小权限（日记正文默认完全不可见）；
 * - 「hidden」不是口头劝阻，而是工具根本不进模型可见表 —— 她连"想看"的念头都没有；
 * - 写入永远需要用户逐次确认（提议 → 复述 → 确认 → 执行 → 可撤销），
 *   所以「可写」不等于"她可以背着你改数据"。
 */

const lifeDataStore = useLifeDataStore()

const unreachable = computed(() => lifeDataStore.unreachable)
const loading = computed(() => lifeDataStore.loading)
const saving = computed(() => lifeDataStore.saving)
const notice = ref<{ type: 'success' | 'warn', msg: string } | null>(null)

const enabled = ref(true)
const endpoint = ref('http://127.0.0.1:8765')
const timeoutSeconds = ref(2)
const permissions = ref<Record<LifeDataCategory, LifeDataTier>>({
  commissions: 'read_write_proactive',
  schedule: 'read_write_proactive',
  legends: 'read_only',
  wallet: 'read_only',
  journal: 'on_request',
  journal_text: 'hidden',
  focus: 'read_write_proactive',
})
const writeMode = ref<TothestarsWriteMode>('local')
const localProjectRoot = ref('')
const proactiveEnabled = ref(false)
const quietStart = ref('23:00')
const quietEnd = ref('07:00')
const maxPerHour = ref(2)
const maxPerDay = ref(6)

const CATEGORY_META: { id: LifeDataCategory, name: string, description: string, icon: string }[] = [
  { id: 'commissions', name: '每日委托', description: '今天的待办、难度、完成状态；可提议新增/完成/修改', icon: 'i-solar:checklist-minimalistic-bold-duotone' },
  { id: 'schedule', name: '日程安排', description: '时间轴里的计划片段；可提议新增计划', icon: 'i-solar:calendar-bold-duotone' },
  { id: 'legends', name: '传说任务', description: '长期目标的指标与进度', icon: 'i-solar:star-fall-bold-duotone' },
  { id: 'wallet', name: '点数钱包', description: '实践点 / 成长点余额', icon: 'i-solar:wallet-money-bold-duotone' },
  { id: 'journal', name: '日记摘要', description: '心情评分、能量与情绪标签（不含正文）', icon: 'i-solar:notebook-bold-duotone' },
  { id: 'journal_text', name: '日记正文与照片', description: '日记全文与插图，最私密的一类', icon: 'i-solar:lock-password-bold-duotone' },
  { id: 'focus', name: '专注 / 番茄钟', description: '专注记录与今日累计；可提议开始番茄钟', icon: 'i-solar:alarm-bold-duotone' },
]

const TIER_META: { id: LifeDataTier, label: string, short: string, description: string }[] = [
  { id: 'read_write_proactive', label: '可读可写可主动', short: '可读写', description: '可以读、可以提议修改（仍需你逐次确认），也可以在合适时机主动提起' },
  { id: 'read_only', label: '只读可主动', short: '只读', description: '可以读、可以主动提起，但没有任何修改入口（提议工具也不可见）' },
  { id: 'on_request', label: '问起才读', short: '问起才读', description: '只有你明确问起时才能读取，绝不主动提及、不进入日常简报' },
  { id: 'hidden', label: '完全不可见', short: '不可见', description: '工具不进模型可见表，提示词也不注入 —— 她会如实说"这部分我看不到"' },
]

function applyConfig(cfg: TothestarsConfig) {
  enabled.value = cfg.enabled
  endpoint.value = cfg.endpoint
  timeoutSeconds.value = cfg.timeout_seconds
  permissions.value = { ...permissions.value, ...cfg.permissions }
  writeMode.value = cfg.write_mode === 'remote' ? 'remote' : 'local'
  localProjectRoot.value = cfg.local_project_root ?? ''
  proactiveEnabled.value = cfg.proactive.enabled
  quietStart.value = cfg.proactive.quiet_hours?.[0] ?? '23:00'
  quietEnd.value = cfg.proactive.quiet_hours?.[1] ?? '07:00'
  maxPerHour.value = cfg.proactive.max_per_hour
  maxPerDay.value = cfg.proactive.max_per_day
}

async function load() {
  notice.value = null
  const cfg = await lifeDataStore.load(true)
  if (cfg)
    applyConfig(cfg)
}

async function save() {
  notice.value = null
  const patch: TothestarsConfigPatch = {
    enabled: enabled.value,
    endpoint: endpoint.value.trim(),
    timeout_seconds: Number(timeoutSeconds.value),
    permissions: { ...permissions.value },
    write_mode: writeMode.value,
    local_project_root: localProjectRoot.value.trim(),
    proactive: {
      enabled: proactiveEnabled.value,
      quiet_hours: [quietStart.value, quietEnd.value],
      max_per_hour: Number(maxPerHour.value),
      max_per_day: Number(maxPerDay.value),
    },
  }
  const next = await lifeDataStore.save(patch)
  if (next) {
    applyConfig(next)
    notice.value = { type: 'success', msg: '已保存到 config.yaml 并热刷新 —— 她能看到和说到的内容已经改变（无需重启）' }
  }
  else {
    notice.value = { type: 'warn', msg: '保存失败：后台没有返回成功。改动未落盘，请检查 Admin 服务 (:8094) 是否在运行。' }
  }
}

/** 本地直连模式下推导出的数据库文件位置，给用户一个可核对的即时反馈。 */
const localDbHint = computed(() => {
  const root = localProjectRoot.value.trim().replace(/[\\/]+$/, '')
  return root ? `${root}\\data\\growth_system.db` : '(先填写项目路径)'
})

/** 一句话预览"她现在的可见范围"，给设置页一个即时反馈。 */
const effectSummary = computed(() => {
  if (!enabled.value)
    return '她完全看不到你的生活数据（工具与提示词都未接入）'
  const visible = CATEGORY_META
    .filter(category => permissions.value[category.id] !== 'hidden')
    .map(category => `${category.name}·${TIER_META.find(tier => tier.id === permissions.value[category.id])?.short ?? ''}`)
  return visible.length > 0 ? `她现在能看到：${visible.join('，')}` : '她看不到任何生活数据'
})

function tierButtonClass(category: LifeDataCategory, tier: LifeDataTier) {
  if (permissions.value[category] === tier) {
    return tier === 'hidden'
      ? 'border-neutral-400 bg-neutral-200 text-neutral-700 dark:border-neutral-500 dark:bg-neutral-700 dark:text-neutral-100'
      : 'border-primary-500/60 bg-primary-500/15 text-primary-600 dark:text-primary-300'
  }
  return 'border-neutral-200 bg-white/40 text-neutral-500 hover:border-neutral-300 dark:border-neutral-700 dark:bg-neutral-900/40 dark:text-neutral-400'
}

onMounted(load)
</script>

<template>
  <div flex="~ col gap-6">
    <!-- 后台不可达：给出手动配置位置，而不是让页面看起来"能用但没反应" -->
    <div v-if="unreachable" class="flex flex-col gap-2 rounded-lg bg-amber-100 p-4 text-sm text-amber-900 dark:bg-amber-500/15 dark:text-amber-200">
      <div class="font-semibold">
        配置后台 (:8094) 连不上，本页暂时无法保存
      </div>
      <div>
        请确认 <code>python runner.py</code> 已启动，然后点下面的「重新读取」。
      </div>
      <details class="text-xs">
        <summary class="cursor-pointer font-medium">
          一定要现在改的话：直接编辑 config/config.yaml
        </summary>
        <div class="mt-2 flex flex-col gap-1">
          <div><code>integration.tothestars.permissions</code>：每类数据的权限档（默认最小权限）</div>
          <div>四档取值：<code>read_write_proactive</code> / <code>read_only</code> / <code>on_request</code> / <code>hidden</code></div>
          <div>改完需要重启 <code>python runner.py</code>（手动改文件不会触发热刷新）。</div>
        </div>
      </details>
    </div>

    <div v-else-if="loading" class="text-sm text-neutral-500 dark:text-neutral-400">
      正在读取生活数据权限…
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
        label="启用向着星联动（总开关）"
        description="关掉后所有生活数据工具都不进模型可见表，提示词也不注入快照 —— 等价于她从未接入过你的生活数据。"
      />

      <!-- 即时效果预览 -->
      <div class="rounded-xl border border-primary-500/20 bg-primary-500/5 p-4">
        <div class="flex items-center gap-2 text-sm font-medium text-neutral-800 dark:text-neutral-200">
          <div class="i-solar:eye-bold text-primary-500" />
          当前可见范围
        </div>
        <div class="mt-1 text-sm text-neutral-600 dark:text-neutral-300">
          {{ effectSummary }}
        </div>
        <div class="mt-2 text-xs text-neutral-500 dark:text-neutral-400">
          这条设置会立即改变她能看到和说到的东西。修改后点保存即可生效，无需重启。
        </div>
      </div>

      <!-- 写入方式：本地直连 / 远程连接 -->
      <div v-if="enabled" class="flex flex-col gap-3 rounded-xl border border-neutral-200 bg-neutral-50/50 p-4 dark:border-neutral-800 dark:bg-neutral-900/40">
        <div class="text-sm font-medium text-neutral-800 dark:text-neutral-200">
          写入方式（向着星暂时离线时怎么办）
        </div>
        <div class="flex flex-wrap gap-2">
          <button
            type="button"
            class="rounded-lg border px-3 py-1.5 text-xs transition-colors"
            :class="writeMode === 'local'
              ? 'border-primary-500/60 bg-primary-500/15 font-medium text-primary-600 dark:text-primary-300'
              : 'border-neutral-200 bg-white/40 text-neutral-500 hover:border-neutral-300 dark:border-neutral-700 dark:bg-neutral-900/40 dark:text-neutral-400'"
            @click="writeMode = 'local'"
          >
            本地直连（推荐）
          </button>
          <button
            type="button"
            class="rounded-lg border px-3 py-1.5 text-xs transition-colors"
            :class="writeMode === 'remote'
              ? 'border-primary-500/60 bg-primary-500/15 font-medium text-primary-600 dark:text-primary-300'
              : 'border-neutral-200 bg-white/40 text-neutral-500 hover:border-neutral-300 dark:border-neutral-700 dark:bg-neutral-900/40 dark:text-neutral-400'"
            @click="writeMode = 'remote'"
          >
            远程连接（暂存重试）
          </button>
        </div>

        <template v-if="writeMode === 'local'">
          <FieldInput
            v-model="localProjectRoot"
            label="向着星项目路径"
            placeholder="E:\\ToTheStars\\...\\ToTheStarsWeb"
            description="BetterAgent 直接调用向着星自己的服务层读写它的 SQLite（不需要向着星在线），业务规则与审计和网页端完全一致。"
          />
          <div class="text-xs text-neutral-500 dark:text-neutral-400">
            数据库：<code>{{ localDbHint }}</code>
          </div>
        </template>
        <div v-else class="text-xs text-neutral-500 dark:text-neutral-400">
          改动仍先走 HTTP；若向着星没响应，会先把这次修改暂存在 BetterAgent，之后每 15 秒~5 分钟自动重试（不影响她说话）。补交成功只在舞台右下角弹一条轻提示，她不会播报。
        </div>
      </div>

      <!-- 权限矩阵 -->
      <div v-if="enabled" class="flex flex-col gap-3">
        <div class="text-sm font-medium text-neutral-800 dark:text-neutral-200">
          权限矩阵（每类数据独立配置）
        </div>
        <div
          v-for="category in CATEGORY_META"
          :key="category.id"
          class="flex flex-col gap-3 rounded-xl border border-neutral-200 bg-neutral-50/50 p-4 lg:flex-row lg:items-center lg:justify-between dark:border-neutral-800 dark:bg-neutral-900/40"
        >
          <div class="flex items-start gap-3">
            <div :class="category.icon" class="mt-0.5 text-2xl text-primary-500" />
            <div>
              <div class="text-sm font-medium text-neutral-800 dark:text-neutral-200">
                {{ category.name }}
              </div>
              <div class="text-xs text-neutral-500 dark:text-neutral-400">
                {{ category.description }}
              </div>
            </div>
          </div>
          <div class="flex flex-wrap gap-1.5">
            <button
              v-for="tier in TIER_META"
              :key="tier.id"
              type="button"
              class="rounded-lg border px-2.5 py-1.5 text-xs transition-colors"
              :class="tierButtonClass(category.id, tier.id)"
              :title="tier.description"
              :aria-pressed="permissions[category.id] === tier.id"
              @click="permissions[category.id] = tier.id"
            >
              {{ tier.label }}
            </button>
          </div>
        </div>

        <!-- 四档解释（固定展示，不藏进 tooltip） -->
        <div class="grid grid-cols-1 gap-2 rounded-xl border border-neutral-200 p-4 text-xs sm:grid-cols-2 dark:border-neutral-800">
          <div v-for="tier in TIER_META" :key="tier.id" class="flex flex-col gap-0.5">
            <div class="font-medium text-neutral-700 dark:text-neutral-200">
              {{ tier.label }}
            </div>
            <div class="text-neutral-500 dark:text-neutral-400">
              {{ tier.description }}
            </div>
          </div>
        </div>

        <div class="rounded-lg bg-sky-50 p-3 text-xs text-sky-800 dark:bg-sky-500/10 dark:text-sky-300">
          写入不等于放任：即使某类数据是「可读写」，她动数据前也一定会先把提议复述给你、
          等你确认后才会执行，而且每一步都记在向着星的「AI 活动」里，可以随时撤销。
        </div>
      </div>

      <!-- 主动策略 -->
      <div v-if="enabled" class="flex flex-col gap-4 rounded-xl border border-neutral-200 p-4 dark:border-neutral-800">
        <div class="text-sm font-medium text-neutral-800 dark:text-neutral-200">
          主动提及策略
        </div>
        <FieldCheckbox
          v-model="proactiveEnabled"
          label="允许她在合适时机主动提起生活数据"
          description="例如晨间简报、必要委托未完成、传说任务临期。触发链路将在主动层阶段接入；这里先保存策略。"
        />
        <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FieldInput
            v-model="quietStart"
            type="time"
            label="静默开始"
            description="静默时段内她绝不主动开口（可跨零点，如 23:00 → 07:00）。"
          />
          <FieldInput
            v-model="quietEnd"
            type="time"
            label="静默结束"
          />
          <FieldInput
            v-model="maxPerHour"
            type="number"
            label="每小时最多主动次数"
            description="0～24，0 = 不限制。与静默时段、你的心情是「与」关系，任何一个不允许就不开口。"
          />
          <FieldInput
            v-model="maxPerDay"
            type="number"
            label="每天最多主动次数"
            description="0～96，0 = 不限制。主动过少像工具，主动过多像打扰 —— 这里就是那个平衡旋钮。"
          />
        </div>
      </div>

      <!-- 高级：端点与超时 -->
      <details class="rounded-lg border border-neutral-200 dark:border-neutral-800">
        <summary class="cursor-pointer p-4 text-sm font-medium">
          高级设置（向着星地址 / 超时）
        </summary>
        <div class="flex flex-col gap-4 p-4 pt-0">
          <FieldInput
            v-model="endpoint"
            label="向着星地址"
            description="默认 http://127.0.0.1:8765。仅在你自己改了监听端口时需要动。"
          />
          <FieldInput
            v-model="timeoutSeconds"
            type="number"
            label="请求超时（秒）"
            description="0.2～30。本机服务正常 0.1 秒内返回；连不上时她会自然说「暂时读不到」，不影响聊天。"
          />
        </div>
      </details>

      <!-- 手动配置提示 -->
      <details class="rounded-lg border border-neutral-200 dark:border-neutral-800">
        <summary class="cursor-pointer p-4 text-sm font-medium">
          这些设置存在哪里？
        </summary>
        <div class="flex flex-col gap-1 p-4 pt-0 text-xs text-neutral-500 dark:text-neutral-400">
          <div><code>config/config.yaml</code> → <code>integration.tothestars</code>（权限矩阵与主动策略）</div>
          <div>认知服务每轮对话实时读取：保存即生效，无需重启 <code>python runner.py</code>。</div>
          <div>日记类数据默认最严（摘要问起才读、正文完全不可见），任何时刻都可以在这里收紧。</div>
        </div>
      </details>

      <div class="flex justify-end gap-2">
        <Button :disabled="loading || saving" class="!py-2" @click="load">
          重新读取
        </Button>
        <Button :disabled="saving" class="!py-2" @click="save">
          <div v-if="saving" class="i-svg-spinners:90-ring-with-bg mr-2 text-sm" />
          保存设置
        </Button>
      </div>
    </template>
  </div>
</template>
