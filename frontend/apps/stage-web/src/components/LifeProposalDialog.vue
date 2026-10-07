<script setup lang="ts">
import type { LifeProposalPayload } from '@proj-airi/stage-ui/services/betteragent-ws'

import { betterAgentWSBridge } from '@proj-airi/stage-ui/services/betteragent-ws'
import { useBetterAgentGatewayStore } from '@proj-airi/stage-ui/stores/modules/betteragent-gateway'
import { useSpeechOutputControlStore } from '@proj-airi/stage-ui/stores/speech-output-control'
import { computed, reactive, ref, watch } from 'vue'

/**
 * 「需要确认」全局弹窗：数字人准备修改向着星数据时弹出。
 *
 * 数据来源：agent.life_proposal WS 帧（后端提议生成时发 pending，执行/取消后发
 * 终态）。用户点确认/取消后，通过 WS 哨兵文本回传（不经过模型决策）；点击前
 * 后端不会写入任何数据。可以展开「查看详情」并手动修改白名单字段（服务端仍会
 * 做完整校验）。终态展示一会儿后自动收起。
 */

interface FieldSpec {
  key: string
  label: string
  type: 'text' | 'textarea' | 'select' | 'checkbox' | 'date' | 'number'
  options?: { label: string, value: string }[]
  hint?: string
}

const KIND_LABELS: Record<string, string> = {
  'commission.create': '新增每日委托',
  'commission.complete': '更新委托完成状态',
  'commission.update': '修改每日委托',
  'schedule.add': '新增日程计划',
  'audit.undo': '撤销上一步操作',
  'focus.start': '开始专注（番茄钟）',
}

const FOCUS_MINUTE_PRESETS = [15, 25, 30, 45, 60, 90]

const DIFFICULTY_OPTIONS = ['A', 'B', 'C', 'D'].map(value => ({ label: `难度 ${value}`, value }))

const gatewayStore = useBetterAgentGatewayStore()
const speechOutputControl = useSpeechOutputControlStore()
const proposal = computed(() => gatewayStore.lifeProposal)
const queueRemaining = computed(() => gatewayStore.lifeProposalQueue.length)

const showDetails = ref(false)
const sending = ref(false)
const fields = reactive<Record<string, any>>({})
const result = ref<{ phase: string, message: string } | null>(null)
let resultTimer: ReturnType<typeof setTimeout> | null = null

const kindLabel = computed(() => KIND_LABELS[proposal.value?.kind || ''] || proposal.value?.kind || '数据修改')
const visible = computed(() => !!proposal.value && !result.value)
const executing = computed(() => sending.value || proposal.value?.phase === 'executing')
const confirmLabel = computed(() => {
  if (executing.value)
    return '正在执行…'
  return proposal.value?.kind === 'focus.start' ? '确认开始' : '确认执行'
})

function editableSpecs(kind: string): FieldSpec[] {
  switch (kind) {
    case 'commission.create':
      return [
        { key: 'title', label: '标题', type: 'text' },
        { key: 'description', label: '说明', type: 'textarea' },
        { key: 'difficulty', label: '难度', type: 'select', options: DIFFICULTY_OPTIONS },
        { key: 'category', label: '分类', type: 'text' },
        { key: 'assigned_date', label: '日期', type: 'date', hint: '留空 = 今天（以凌晨 4 点为界）' },
        { key: 'is_required', label: '必要委托', type: 'checkbox' },
        { key: 'is_recurring', label: '日常重复', type: 'checkbox' },
      ]
    case 'commission.complete':
      return [
        { key: 'completed', label: '标记为已完成（取消勾选 = 恢复未完成）', type: 'checkbox' },
      ]
    case 'commission.update':
      return [
        { key: 'title', label: '标题', type: 'text' },
        { key: 'description', label: '说明', type: 'textarea' },
        { key: 'difficulty', label: '难度', type: 'select', options: DIFFICULTY_OPTIONS },
        { key: 'category', label: '分类', type: 'text' },
        { key: 'is_required', label: '必要委托', type: 'checkbox' },
        { key: 'is_recurring', label: '日常重复', type: 'checkbox' },
      ]
    case 'schedule.add':
      return [
        { key: 'title', label: '标题', type: 'text' },
        { key: 'start', label: '开始时间', type: 'text', hint: 'HH:MM，如 20:00' },
        { key: 'end', label: '结束时间', type: 'text', hint: 'HH:MM，如 21:00' },
        { key: 'plan_date', label: '日期', type: 'date', hint: '留空 = 今天' },
        { key: 'content', label: '备注', type: 'textarea' },
      ]
    case 'focus.start':
      return [
        { key: 'minutes', label: '专注时长（分钟，5~240）', type: 'number', hint: '默认 60' },
      ]
    default:
      return []
  }
}

const specs = computed(() => editableSpecs(proposal.value?.kind || ''))
const readOnlyParams = computed(() => {
  const params = { ...proposal.value?.params }
  if (proposal.value?.kind === 'commission.update' && params.body)
    delete (params as any).body
  if (proposal.value?.kind === 'audit.undo')
    delete (params as any).category
  return params
})

function seedFields(p: LifeProposalPayload) {
  for (const key of Object.keys(fields)) delete fields[key]
  if (!p.params) return
  const source = p.kind === 'commission.update' ? ((p.params as any).body || {}) : p.params
  for (const spec of editableSpecs(p.kind || '')) {
    const value = (source as any)[spec.key]
    fields[spec.key] = spec.type === 'checkbox' ? !!value : (value ?? '')
  }
}

function collectEdits(): Record<string, any> {
  const edits: Record<string, any> = {}
  for (const spec of specs.value)
    edits[spec.key] = fields[spec.key]
  return edits
}

function closeResult() {
  if (resultTimer) {
    clearTimeout(resultTimer)
    resultTimer = null
  }
  result.value = null
  // 队列里还有提议（同一轮生成的多条）时，立刻展示下一条等待确认。
  gatewayStore.promoteNextLifeProposal()
}

watch(proposal, (p) => {
  if (resultTimer) {
    clearTimeout(resultTimer)
    resultTimer = null
  }
  if (!p) return

  if (p.phase === 'pending') {
    sending.value = false
    // 专注提议的核心就是调时长，直接把详情展开，少一步点击。
    showDetails.value = p.kind === 'focus.start'
    result.value = null
    seedFields(p)
    return
  }

  if (p.phase === 'executing') {
    sending.value = true
    return
  }

  // 终态：关闭确认框，短暂展示结果（队列里还有下一条时缩短停留，尽快轮到下一条）
  sending.value = false
  result.value = { phase: p.phase, message: p.message || '' }
  const stayMs = queueRemaining.value > 0 ? 1400 : (p.phase === 'failed' ? 6000 : 3200)
  resultTimer = setTimeout(closeResult, stayMs)
}, { immediate: true })

function confirm() {
  const p = proposal.value
  if (!p)
    return
  // 点确认也是一次"打断"：先停掉她还在念的提议，避免和确认后的回复叠在一起。
  speechOutputControl.requestStopSpeaking('manual-chat')
  sending.value = true
  betterAgentWSBridge.sendLifeDecision(p.proposal_id, 'confirm', collectEdits())
}

function cancel() {
  const p = proposal.value
  if (!p)
    return
  speechOutputControl.requestStopSpeaking('manual-chat')
  sending.value = true
  betterAgentWSBridge.sendLifeDecision(p.proposal_id, 'cancel')
}
</script>

<template>
  <div>
    <!-- 结果提示（确认框收起后的短暂反馈） -->
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0 translate-y-2"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition duration-200 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0"
    >
      <div
        v-if="result"
        class="fixed left-1/2 top-18 z-[9999] max-w-[min(26rem,calc(100vw-2rem))] -translate-x-1/2 rounded-xl border px-4 py-2.5 text-sm shadow-2xl backdrop-blur-xl"
        :class="result.phase === 'failed'
          ? 'border-rose-500/40 bg-rose-950/85 text-rose-100'
          : 'border-emerald-500/40 bg-emerald-950/85 text-emerald-100'"
      >
        <span class="mr-1">{{ result.phase === 'failed' ? '写入失败：' : result.phase === 'cancelled' ? '已取消：' : '已执行：' }}</span>
        {{ result.message || (result.phase === 'cancelled' ? '没有产生任何修改' : '完成') }}
      </div>
    </Transition>

    <!-- 确认框 -->
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0 scale-95"
      enter-to-class="opacity-100 scale-100"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="opacity-0 scale-95"
    >
      <div v-if="visible" class="fixed inset-0 z-[9998] flex items-start justify-center bg-black/45 p-4 pt-[12vh] backdrop-blur-sm">
        <div class="w-[min(30rem,calc(100vw-2rem))] max-h-[72vh] overflow-y-auto rounded-2xl border border-amber-400/30 bg-neutral-950/95 p-5 text-neutral-100 shadow-2xl">
          <!-- Header -->
          <div class="flex items-center gap-2">
            <div class="i-solar:shield-warning-bold-duotone text-xl text-amber-400" />
            <div class="text-base font-semibold">
              需要确认
            </div>
            <span class="rounded-full bg-amber-400/15 px-2 py-0.5 text-[11px] text-amber-300">{{ kindLabel }}</span>
            <span
              v-if="queueRemaining > 0"
              class="rounded-full bg-cyan-400/15 px-2 py-0.5 text-[11px] text-cyan-300"
            >
              还有 {{ queueRemaining }} 条待确认
            </span>
            <div class="ml-auto font-mono text-[10px] text-neutral-500">#{{ proposal?.proposal_id }}</div>
          </div>

          <p class="mt-2 text-sm leading-relaxed text-neutral-300">
            {{ proposal?.summary }}
          </p>
          <p v-if="proposal?.kind === 'focus.start'" class="mt-1 text-xs text-neutral-500">
            确认后番茄钟立即开始，倒计时会显示在舞台上方；专注期间她不会主动打扰。结束时会再让你确认这次完成的内容并记录到向着星。
          </p>
          <p v-else class="mt-1 text-xs text-neutral-500">
            确认之前不会写入任何数据；确认后仍可在向着星「AI 活动」里撤销。
          </p>

          <!-- Details toggle -->
          <button
            v-if="specs.length > 0"
            class="mt-3 flex items-center gap-1 text-xs text-amber-300/90 transition-colors hover:text-amber-200"
            @click="showDetails = !showDetails"
          >
            <div :class="showDetails ? 'i-solar:alt-arrow-up-bold' : 'i-solar:alt-arrow-down-bold'" class="text-sm" />
            {{ showDetails ? '收起详情' : '查看详情 / 手动修改' }}
          </button>

          <!-- Editable fields -->
          <div v-if="showDetails && specs.length > 0" class="mt-3 flex flex-col gap-3 rounded-xl border border-neutral-800 bg-neutral-900/60 p-3">
            <div v-for="spec in specs" :key="spec.key" class="flex flex-col gap-1">
              <template v-if="spec.type === 'checkbox'">
                <label class="flex cursor-pointer items-center gap-2 text-xs text-neutral-200">
                  <input v-model="fields[spec.key]" type="checkbox" class="accent-amber-400">
                  {{ spec.label }}
                </label>
              </template>
              <template v-else-if="spec.type === 'select'">
                <label class="text-xs text-neutral-400">{{ spec.label }}</label>
                <select v-model="fields[spec.key]" class="rounded-lg border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-100 outline-none focus:border-amber-400/60">
                  <option v-for="option in spec.options" :key="option.value" :value="option.value">{{ option.label }}</option>
                </select>
              </template>
              <template v-else-if="spec.type === 'textarea'">
                <label class="text-xs text-neutral-400">{{ spec.label }}</label>
                <textarea v-model="fields[spec.key]" rows="2" class="resize-none rounded-lg border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-100 outline-none focus:border-amber-400/60" />
              </template>
              <template v-else-if="spec.type === 'number'">
                <label class="text-xs text-neutral-400">{{ spec.label }}<span v-if="spec.hint" class="ml-1 text-neutral-500">（{{ spec.hint }}）</span></label>
                <input v-model.number="fields[spec.key]" type="number" min="5" max="240" class="rounded-lg border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-100 outline-none focus:border-amber-400/60">
                <div v-if="proposal?.kind === 'focus.start'" class="mt-1 flex flex-wrap gap-1.5">
                  <button
                    v-for="preset in FOCUS_MINUTE_PRESETS"
                    :key="preset"
                    class="rounded-full border px-2.5 py-0.5 text-xs transition-colors"
                    :class="fields.minutes === preset
                      ? 'border-amber-400 bg-amber-400 font-semibold text-neutral-900'
                      : 'border-neutral-700 text-neutral-300 hover:border-neutral-500'"
                    @click="fields.minutes = preset"
                  >
                    {{ preset }} 分钟
                  </button>
                </div>
              </template>
              <template v-else>
                <label class="text-xs text-neutral-400">{{ spec.label }}<span v-if="spec.hint" class="ml-1 text-neutral-500">（{{ spec.hint }}）</span></label>
                <input v-model="fields[spec.key]" :type="spec.type === 'date' ? 'date' : 'text'" class="rounded-lg border border-neutral-700 bg-neutral-950 px-2 py-1.5 text-sm text-neutral-100 outline-none focus:border-amber-400/60">
              </template>
            </div>

            <div v-if="Object.keys(readOnlyParams).length" class="border-t border-neutral-800 pt-2 text-[11px] text-neutral-500">
              <span v-for="(value, key) in readOnlyParams" :key="key" class="mr-3">{{ key }}: {{ value }}</span>
            </div>
          </div>

          <!-- Actions -->
          <div class="mt-4 flex justify-end gap-2">
            <button
              class="rounded-lg border border-neutral-700 px-4 py-2 text-sm text-neutral-300 transition-colors hover:border-neutral-500 hover:text-neutral-100 disabled:opacity-40"
              :disabled="executing"
              @click="cancel"
            >
              取消
            </button>
            <button
              class="flex items-center gap-1.5 rounded-lg bg-amber-400 px-4 py-2 text-sm font-semibold text-neutral-900 transition-colors hover:bg-amber-300 disabled:opacity-50"
              :disabled="executing"
              @click="confirm"
            >
              <div v-if="executing" class="i-svg-spinners:90-ring-with-bg text-sm" />
              {{ confirmLabel }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>
