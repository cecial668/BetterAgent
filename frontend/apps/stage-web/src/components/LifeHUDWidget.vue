<script setup lang="ts">
import type { LifeLegend, LifeSnapshot } from '@proj-airi/stage-ui/services/betteragent-admin-api'

import { getLifeSnapshot } from '@proj-airi/stage-ui/services/betteragent-admin-api'
import { betterAgentWSBridge } from '@proj-airi/stage-ui/services/betteragent-ws'
import { computed, onMounted, onUnmounted, ref } from 'vue'

/**
 * 舞台「生活概览 HUD」：把向着星的一天摘要摆在数字人旁边。
 *
 * - 数据经 Admin 代理读向着星（避免跨域），字段按权限配置裁剪；
 * - 这是用户自己看自己的数据，所以不受"数字人能看多少"的限制 —— 权限约束的
 *   是数字人（认知服务侧的工具门控与提示词注入），两者职责不重叠。
 * - 「让她讲讲今天」把一句上下文提示发给她（走已连接的 WebGateway），
 *   她不凭空知道你在看什么，得你开口。
 */

const TOTHESTARS_WEB_URL = (typeof import.meta !== 'undefined' && import.meta.env?.VITE_TOTHESTARS_URL)
  ? import.meta.env.VITE_TOTHESTARS_URL
  : 'http://127.0.0.1:8765'

const snapshot = ref<LifeSnapshot | null>(null)
const loading = ref(false)
const failed = ref(false)
const asked = ref(false)

const emit = defineEmits<{ close: [] }>()

const commissions = computed(() => snapshot.value?.commissions ?? [])
const doneCount = computed(() => commissions.value.filter(q => q.is_completed).length)
const pendingRequired = computed(() => commissions.value.filter(q => q.is_required && !q.is_completed))
const pendingOptional = computed(() => commissions.value.filter(q => !q.is_required && !q.is_completed))
const plans = computed(() => snapshot.value?.schedule?.plans ?? [])
const nextPlan = computed(() => plans.value.find(p => !p.completed) ?? null)
const legends = computed(() => (snapshot.value?.legends ?? []).slice(0, 2))
const isVacation = computed(() => snapshot.value?.is_vacation === true)

function percent(done: number, total: number) {
  if (!total)
    return 0
  return Math.max(0, Math.min(100, Math.round((done / total) * 100)))
}

function remainingLabel(legend: LifeLegend) {
  if (legend.remaining_days == null)
    return ''
  if (legend.remaining_days < 0)
    return `已过期 ${Math.abs(legend.remaining_days)} 天`
  if (legend.remaining_days === 0)
    return '今天截止'
  return `剩 ${legend.remaining_days} 天`
}

async function refresh() {
  loading.value = true
  try {
    snapshot.value = await getLifeSnapshot()
    failed.value = !snapshot.value
  }
  finally {
    loading.value = false
  }
}

function askCompanion() {
  if (!betterAgentWSBridge.isConnected()) {
    failed.value = true
    return
  }
  betterAgentWSBridge.sendUserText('帮我看看今天的委托和日程，有什么需要提醒我的吗？')
  asked.value = true
}

let timer: ReturnType<typeof setInterval> | undefined

onMounted(() => {
  refresh()
  timer = setInterval(refresh, 60000)
})

onUnmounted(() => {
  if (timer)
    clearInterval(timer)
})
</script>

<template>
  <section
    class="absolute right-0 top-full z-[9999] mt-2 w-[min(21rem,calc(100vw-1.5rem))] rounded-2xl border border-neutral-200/70 bg-white/95 p-4 text-neutral-800 shadow-2xl backdrop-blur-xl dark:border-neutral-700/70 dark:bg-neutral-950/95 dark:text-neutral-100"
  >
    <!-- Header -->
    <div class="flex items-center justify-between">
      <div class="flex items-center gap-2 text-sm font-semibold">
        <div class="i-solar:notebook-bold-duotone text-amber-500 dark:text-amber-400" />
        <span>生活概览</span>
        <span v-if="snapshot?.date" class="text-[11px] font-normal text-neutral-400">{{ snapshot.date }}</span>
        <span v-if="isVacation" class="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] text-emerald-600 dark:text-emerald-400">假期日</span>
      </div>
      <div class="flex items-center gap-1">
        <button
          class="p-1 text-neutral-400 transition-colors hover:text-amber-500"
          title="刷新"
          @click="refresh"
        >
          <div class="i-solar:restart-bold text-sm" :class="{ 'animate-spin': loading }" />
        </button>
        <button
          class="p-1 text-neutral-400 transition-colors hover:text-rose-400"
          title="关闭"
          @click="emit('close')"
        >
          <div class="i-solar:close-circle-bold text-base" />
        </button>
      </div>
    </div>

    <!-- Offline -->
    <div v-if="failed" class="mt-3 flex flex-col gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-300">
      <span>读不到生活数据。请确认向着星 (8765) 与 Admin (8094) 都在运行，并且已在设置里开启联动。</span>
      <button class="self-start rounded-lg bg-amber-500/20 px-2 py-1 font-medium" @click="refresh">
        重试
      </button>
    </div>

    <template v-else-if="snapshot">
      <!-- Commissions -->
      <div v-if="snapshot.commissions" class="mt-3">
        <div class="flex items-center justify-between text-xs">
          <span class="font-medium text-neutral-600 dark:text-neutral-300">今日委托</span>
          <span class="font-mono text-neutral-400">{{ doneCount }}/{{ commissions.length }}</span>
        </div>
        <div class="mt-1.5 h-1.5 overflow-hidden rounded-full bg-neutral-200/70 dark:bg-neutral-800">
          <div
            class="h-full rounded-full bg-gradient-to-r from-amber-400 to-orange-400 transition-all"
            :style="{ width: `${percent(doneCount, commissions.length)}%` }"
          />
        </div>
        <div v-if="pendingRequired.length" class="mt-2 flex flex-col gap-1 text-xs">
          <div v-for="q in pendingRequired.slice(0, 3)" :key="q.id" class="flex items-center gap-1.5 text-neutral-700 dark:text-neutral-200">
            <span class="text-rose-400">✦</span>
            <span class="truncate">{{ q.title }}</span>
            <span class="ml-auto shrink-0 text-[10px] text-neutral-400">必要</span>
          </div>
          <div v-if="pendingOptional.length" class="text-[11px] text-neutral-400">
            另有 {{ pendingOptional.length }} 条支线未完成
          </div>
        </div>
        <div v-else-if="commissions.length" class="mt-2 text-xs text-emerald-600 dark:text-emerald-400">
          必要委托已完成 🎉
        </div>
        <div v-else class="mt-2 text-xs text-neutral-400">
          今天还没有委托。
        </div>
      </div>

      <!-- Schedule -->
      <div v-if="snapshot.schedule" class="mt-3 border-t border-neutral-200/60 pt-3 dark:border-neutral-800">
        <div class="text-xs font-medium text-neutral-600 dark:text-neutral-300">
          今日日程
        </div>
        <div v-if="nextPlan" class="mt-1.5 flex items-center gap-2 text-xs">
          <span class="rounded-md bg-sky-500/15 px-1.5 py-0.5 font-mono text-[10px] text-sky-600 dark:text-sky-400">
            {{ nextPlan.start }}-{{ nextPlan.end }}
          </span>
          <span class="truncate text-neutral-700 dark:text-neutral-200">{{ nextPlan.title }}</span>
        </div>
        <div v-else class="mt-1.5 text-xs text-neutral-400">
          今天没有待办的安排。
        </div>
        <div v-if="plans.length > 1" class="mt-1 text-[11px] text-neutral-400">
          今天共 {{ plans.length }} 项安排，已完成 {{ plans.filter(p => p.completed).length }} 项
        </div>
      </div>

      <!-- Legends -->
      <div v-if="snapshot.legends && legends.length" class="mt-3 border-t border-neutral-200/60 pt-3 dark:border-neutral-800">
        <div class="text-xs font-medium text-neutral-600 dark:text-neutral-300">
          传说任务
        </div>
        <div v-for="legend in legends" :key="legend.id" class="mt-1.5 flex flex-col gap-1">
          <div class="flex items-center justify-between text-xs">
            <span class="truncate text-neutral-700 dark:text-neutral-200">{{ legend.title }}</span>
            <span class="ml-2 shrink-0 font-mono text-[10px] text-neutral-400">
              {{ legend.progress?.done ?? 0 }}/{{ legend.progress?.total ?? 0 }}
              <template v-if="remainingLabel(legend)"> · {{ remainingLabel(legend) }}</template>
            </span>
          </div>
          <div class="h-1 overflow-hidden rounded-full bg-neutral-200/70 dark:bg-neutral-800">
            <div
              class="h-full rounded-full bg-gradient-to-r from-violet-400 to-sky-400"
              :style="{ width: `${percent(legend.progress?.done ?? 0, legend.progress?.total ?? 0)}%` }"
            />
          </div>
        </div>
      </div>

      <!-- Actions -->
      <div class="mt-3 flex items-center justify-between gap-2 border-t border-neutral-200/60 pt-3 dark:border-neutral-800">
        <button
          class="flex items-center gap-1.5 rounded-lg bg-amber-500/15 px-3 py-1.5 text-xs font-medium text-amber-600 transition-colors hover:bg-amber-500/25 disabled:opacity-50 dark:text-amber-400"
          :disabled="loading"
          @click="askCompanion"
        >
          <div class="i-solar:chat-round-dots-bold text-sm" />
          {{ asked ? '已请她开口' : '让她讲讲今天' }}
        </button>
        <a
          :href="TOTHESTARS_WEB_URL"
          target="_blank"
          rel="noopener"
          class="flex items-center gap-1 text-xs text-neutral-400 transition-colors hover:text-sky-500"
        >
          打开向着星
          <div class="i-solar:arrow-right-up-bold text-xs" />
        </a>
      </div>
    </template>

    <div v-else class="mt-3 text-xs text-neutral-400">
      正在读取…
    </div>
  </section>
</template>
