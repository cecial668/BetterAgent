<script setup lang="ts">
import type { NoticePayload } from '@proj-airi/stage-ui/services/betteragent-ws'

import { betterAgentWSBridge } from '@proj-airi/stage-ui/services/betteragent-ws'
import { onMounted, onUnmounted, ref } from 'vue'

/**
 * 低优先级 UI 通知（TOAST）：目前用于「远程连接」模式下暂存的向着星写入
 * 补交成功/放弃。不经过数字人、不播报，只在右下角静默弹一条，几秒后自动消失。
 */

interface ToastItem extends NoticePayload {
  localId: number
}

const items = ref<ToastItem[]>([])
let nextId = 1
const timers = new Map<number, ReturnType<typeof setTimeout>>()
let unsubscribe: (() => void) | undefined

function dismiss(localId: number) {
  const timer = timers.get(localId)
  if (timer) {
    clearTimeout(timer)
    timers.delete(localId)
  }
  items.value = items.value.filter(item => item.localId !== localId)
}

function push(notice: NoticePayload) {
  const localId = nextId++
  items.value = [...items.value, { ...notice, localId }]
  // warn 多留一会儿（用户可能需要去处理），info 5 秒足够。
  const ttl = notice.level === 'warn' ? 9000 : 5000
  timers.set(localId, setTimeout(() => dismiss(localId), ttl))
}

onMounted(() => {
  unsubscribe = betterAgentWSBridge.onNotice(push)
})

onUnmounted(() => {
  unsubscribe?.()
  for (const timer of timers.values())
    clearTimeout(timer)
  timers.clear()
})
</script>

<template>
  <div class="pointer-events-none fixed bottom-40 right-4 z-[9985] flex w-[min(22rem,calc(100vw-2rem))] flex-col gap-2">
    <TransitionGroup
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="translate-y-2 opacity-0"
      enter-to-class="translate-y-0 opacity-100"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100"
      leave-to-class="translate-y-1 opacity-0"
    >
      <div
        v-for="item in items"
        :key="item.localId"
        class="pointer-events-auto flex items-start gap-2 rounded-xl border px-3.5 py-2.5 text-xs shadow-xl backdrop-blur-xl"
        :class="item.level === 'warn'
          ? 'border-amber-400/30 bg-amber-950/85 text-amber-100'
          : 'border-cyan-400/25 bg-neutral-950/85 text-neutral-100'"
      >
        <div
          class="mt-0.5 text-sm"
          :class="item.level === 'warn' ? 'i-solar:danger-triangle-bold-duotone text-amber-300' : 'i-solar:bell-bing-bold-duotone text-cyan-300'"
        />
        <div class="min-w-0 flex-1">
          <div v-if="item.title" class="font-medium opacity-90">
            {{ item.title }}
          </div>
          <div class="mt-0.5 leading-relaxed opacity-80">
            {{ item.message }}
          </div>
        </div>
        <button class="opacity-50 transition-opacity hover:opacity-100" @click="dismiss(item.localId)">
          ×
        </button>
      </div>
    </TransitionGroup>
  </div>
</template>
