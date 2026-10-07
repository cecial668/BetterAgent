<script setup lang="ts">
import type { FocusStatePayload } from '@proj-airi/stage-ui/services/betteragent-ws'

import { betterAgentWSBridge } from '@proj-airi/stage-ui/services/betteragent-ws'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

/**
 * 专注模式（番茄钟）挂件。
 *
 * 计时真源在 Go 的 FocusManager（刷新/关页面都不丢）：本组件只负责画倒计时、
 * 发控制哨兵（暂停/继续/放弃/提交总结），每次 agent.focus_state 广播都会校正
 * 本地倒数。自然结束后弹出「专注总结」表单，提交后由认知引擎写入向着星，
 * 芙宁娜会围绕填写的内容说鼓励的话。
 */

const state = ref<FocusStatePayload | null>(null)
const now = ref(Date.now())
const submitted = ref(false)
const confirmingAbandon = ref(false)
const category = ref('学习')
const description = ref('')

const CATEGORIES = ['学习', '工作', '编程', '阅读', '写作', '复盘', '其他']

let ticker: ReturnType<typeof setInterval> | undefined
let unsubscribe: (() => void) | undefined

const active = computed(() => !!state.value && state.value.phase !== 'idle')
const running = computed(() => state.value?.phase === 'running')
const paused = computed(() => state.value?.phase === 'paused')
const completed = computed(() => state.value?.phase === 'completed')
const showSummary = computed(() => completed.value && !submitted.value)

/** 剩余秒数：运行中用 deadline 本地平滑倒数，暂停/回帧时用服务端给的剩余值。 */
const remainingSeconds = computed(() => {
  const s = state.value
  if (!s)
    return 0
  if (s.phase === 'running' && s.deadline_unix) {
    return Math.max(0, Math.round(s.deadline_unix - now.value / 1000))
  }
  return Math.max(0, s.remaining_seconds || 0)
})

const totalSeconds = computed(() => Math.max(0, (state.value?.planned_minutes || 0) * 60))
/** 1 = 剩余满，0 = 结束。 */
const remainingRatio = computed(() => {
  if (totalSeconds.value <= 0)
    return 0
  return Math.min(1, Math.max(0, remainingSeconds.value / totalSeconds.value))
})

const mmss = computed(() => {
  const total = remainingSeconds.value
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
})

const RING_RADIUS = 52
const ringDash = 2 * Math.PI * RING_RADIUS
const ringOffset = computed(() => ringDash * remainingRatio.value)

const phaseLabel = computed(() => {
  if (running.value)
    return '专注中'
  if (paused.value)
    return '已暂停'
  if (completed.value)
    return '已完成'
  return ''
})

watch(state, (s) => {
  if (!s)
    return
  if (s.phase !== 'completed')
    confirmingAbandon.value = false
  if (s.phase === 'idle') {
    submitted.value = false
    description.value = ''
  }
})

function pause() {
  confirmingAbandon.value = false
  betterAgentWSBridge.sendFocusControl('pause')
}

function resume() {
  betterAgentWSBridge.sendFocusControl('resume')
}

function abandon() {
  betterAgentWSBridge.sendFocusControl('abandon')
  confirmingAbandon.value = false
}

function submitSummary() {
  if (submitted.value)
    return
  submitted.value = true
  betterAgentWSBridge.sendFocusControl('finish', {
    category: category.value,
    description: description.value.trim(),
    planned_minutes: state.value?.planned_minutes,
  })
}

onMounted(() => {
  unsubscribe = betterAgentWSBridge.onFocusState((payload) => {
    state.value = payload
  })
  // 页面加载/刷新后拉取当前状态：正在专注的番茄钟要能续上倒计时。
  betterAgentWSBridge.sendFocusStatus()
  ticker = setInterval(() => {
    now.value = Date.now()
  }, 250)
})

onUnmounted(() => {
  unsubscribe?.()
  if (ticker)
    clearInterval(ticker)
})
</script>

<template>
  <div>
    <!-- 专注进行中：悬浮大倒计时 -->
    <Transition
      enter-active-class="transition duration-300 ease-out"
      enter-from-class="translate-y-3 opacity-0 scale-95"
      enter-to-class="translate-y-0 opacity-100 scale-100"
      leave-active-class="transition duration-200 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0 scale-95"
    >
      <div
        v-if="active && !showSummary"
        class="fixed left-1/2 top-4 z-[9990] -translate-x-1/2 select-none"
      >
        <div class="relative w-[min(23rem,calc(100vw-2rem))] overflow-hidden rounded-3xl border border-cyan-300/20 bg-neutral-950/85 px-6 py-5 shadow-[0_0_70px_-12px_rgba(56,189,248,0.65)] backdrop-blur-xl">
          <div class="pointer-events-none absolute -top-20 left-1/2 h-44 w-44 -translate-x-1/2 rounded-full bg-cyan-400/20 blur-3xl" />
          <div class="pointer-events-none absolute -right-16 -bottom-24 h-40 w-40 rounded-full bg-violet-500/20 blur-3xl" />

          <div class="relative flex items-center justify-between gap-2">
            <div class="flex items-center gap-2 text-[11px] font-medium tracking-[0.22em] text-cyan-200/90 uppercase">
              <span
                class="inline-block h-2 w-2 rounded-full"
                :class="running
                  ? 'animate-pulse bg-cyan-300 shadow-[0_0_10px_rgba(34,211,238,0.9)]'
                  : 'bg-amber-300 shadow-[0_0_10px_rgba(252,211,77,0.9)]'"
              />
              FOCUS · {{ phaseLabel }}
            </div>
            <div class="text-[11px] text-neutral-400">
              计划 {{ state?.planned_minutes }} 分钟
            </div>
          </div>

          <div class="relative mt-3 flex items-center gap-4">
            <div class="relative h-28 w-28 shrink-0">
              <svg viewBox="0 0 120 120" class="h-28 w-28 -rotate-90">
                <circle cx="60" cy="60" :r="RING_RADIUS" fill="none" stroke="rgba(255,255,255,0.08)" stroke-width="8" />
                <circle
                  cx="60" cy="60" :r="RING_RADIUS" fill="none"
                  stroke="url(#focus-ring-gradient)" stroke-width="8" stroke-linecap="round"
                  :stroke-dasharray="ringDash" :stroke-dashoffset="ringOffset"
                  class="transition-[stroke-dashoffset] duration-300 ease-linear"
                />
                <defs>
                  <linearGradient id="focus-ring-gradient" x1="0" y1="0" x2="1" y2="1">
                    <stop offset="0%" stop-color="#22d3ee" />
                    <stop offset="100%" stop-color="#a78bfa" />
                  </linearGradient>
                </defs>
              </svg>
              <div class="absolute inset-0 flex items-center justify-center">
                <div
                  class="font-mono text-2xl font-bold tabular-nums text-white"
                  style="text-shadow: 0 0 18px rgba(34, 211, 238, 0.55)"
                >
                  {{ Math.round(remainingRatio * 100) }}%
                </div>
              </div>
            </div>

            <div class="min-w-0 flex-1">
              <div
                class="font-mono text-5xl font-bold tracking-tight tabular-nums text-white"
                style="text-shadow: 0 0 28px rgba(34, 211, 238, 0.45)"
              >
                {{ mmss }}
              </div>
              <div class="mt-1 text-xs text-neutral-400">
                {{ paused ? '计时已暂停，继续后接着倒数' : '剩余时间，安心做事就好' }}
              </div>
            </div>
          </div>

          <div class="relative mt-4 h-1.5 overflow-hidden rounded-full bg-white/10">
            <div
              class="h-full rounded-full bg-gradient-to-r from-cyan-400 via-sky-400 to-violet-400 transition-[width] duration-300 ease-linear"
              :style="{ width: `${remainingRatio * 100}%` }"
            />
          </div>

          <div class="relative mt-4 flex items-center justify-end gap-2">
            <button
              v-if="running"
              class="flex items-center gap-1.5 rounded-xl border border-neutral-700 px-3.5 py-1.5 text-sm text-neutral-200 transition-colors hover:border-neutral-500 hover:text-white"
              @click="pause"
            >
              <div class="i-solar:pause-bold-duotone text-base" />
              暂停
            </button>
            <button
              v-else-if="paused"
              class="flex items-center gap-1.5 rounded-xl bg-cyan-400 px-3.5 py-1.5 text-sm font-semibold text-neutral-900 transition-colors hover:bg-cyan-300"
              @click="resume"
            >
              <div class="i-solar:play-bold-duotone text-base" />
              继续
            </button>
            <button
              class="rounded-xl border border-rose-400/30 px-3.5 py-1.5 text-sm text-rose-200/90 transition-colors hover:border-rose-400/60 hover:text-rose-100"
              @click="confirmingAbandon = true"
            >
              结束
            </button>
          </div>

          <div
            v-if="confirmingAbandon"
            class="relative mt-3 rounded-xl border border-rose-400/30 bg-rose-500/10 p-3 text-xs leading-relaxed text-rose-100"
          >
            现在结束算半途而废：这次不会记入向着星，芙宁娜也会对你失望。确定要结束吗？
            <div class="mt-2 flex justify-end gap-2">
              <button
                class="rounded-lg border border-neutral-600 px-3 py-1 text-neutral-300 transition-colors hover:border-neutral-400 hover:text-white"
                @click="confirmingAbandon = false"
              >
                继续专注
              </button>
              <button
                class="rounded-lg bg-rose-400/90 px-3 py-1 font-semibold text-neutral-900 transition-colors hover:bg-rose-300"
                @click="abandon"
              >
                确定结束
              </button>
            </div>
          </div>
        </div>
      </div>
    </Transition>

    <!-- 自然结束：专注总结弹窗 -->
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0 scale-95"
      enter-to-class="opacity-100 scale-100"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to="opacity-0 scale-95"
    >
      <div
        v-if="showSummary"
        class="fixed inset-0 z-[9997] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
      >
        <div class="w-[min(26rem,calc(100vw-2rem))] rounded-2xl border border-cyan-300/25 bg-neutral-950/95 p-5 text-neutral-100 shadow-2xl">
          <div class="flex items-center gap-2">
            <div class="i-solar:cup-star-bold-duotone text-xl text-amber-300" />
            <div class="text-base font-semibold">
              专注完成！
            </div>
            <span class="ml-auto rounded-full bg-cyan-400/15 px-2 py-0.5 text-[11px] text-cyan-200">
              {{ state?.planned_minutes }} 分钟
            </span>
          </div>
          <p class="mt-1 text-xs text-neutral-400">
            记录一下这次专注完成的内容，提交后她会围绕它来给你收尾。
          </p>

          <div class="mt-4 text-xs text-neutral-400">
            分类
          </div>
          <div class="mt-1.5 flex flex-wrap gap-1.5">
            <button
              v-for="item in CATEGORIES"
              :key="item"
              class="rounded-full px-3 py-1 text-xs transition-colors"
              :class="category === item
                ? 'bg-gradient-to-r from-cyan-400 to-violet-400 font-semibold text-neutral-900'
                : 'border border-neutral-700 text-neutral-300 hover:border-neutral-500'"
              @click="category = item"
            >
              {{ item }}
            </button>
          </div>

          <div class="mt-4 text-xs text-neutral-400">
            完成了什么（可留空）
          </div>
          <textarea
            v-model="description"
            rows="3"
            maxlength="200"
            placeholder="例如：写完了报告第三章"
            class="mt-1.5 w-full resize-none rounded-xl border border-neutral-700 bg-neutral-900/70 px-3 py-2 text-sm text-neutral-100 outline-none transition-colors placeholder:text-neutral-600 focus:border-cyan-400/60"
          />

          <div class="mt-4 flex justify-end">
            <button
              class="rounded-xl bg-gradient-to-r from-cyan-400 to-violet-400 px-4 py-2 text-sm font-semibold text-neutral-900 transition-opacity hover:opacity-90"
              @click="submitSummary"
            >
              提交并记录
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>
