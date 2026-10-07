import { useLocalStorageManualReset } from '@proj-airi/stage-shared/composables'
import { defineStore } from 'pinia'
import { ref } from 'vue'

import { computeAwaySeconds } from '../../utils/greeting'

const LAST_VISIT_STORAGE_KEY = 'settings/greeting/last-visit'

/**
 * 打招呼：打开前端网页（页面加载）时，让她主动说一句问候。
 * 开关存在浏览器本地——触发动作发生在前端，后端只是被动响应
 * （见 Go 侧 user.greeting → handleUserGreeting）。
 */
export const useGreetingStore = defineStore('greeting', () => {
  /** 打开前端页面时主动打招呼（设置 → 打招呼）。 */
  const enabled = useLocalStorageManualReset<boolean>('settings/greeting/enabled', true)

  /**
   * 本页面加载是否已经请求过打招呼。存在 store（页面内单例）而不是组件里，
   * 这样从设置页返回舞台、WS 重连都不会重复触发；刷新页面则重置，
   * 正是"每次打开网页都要说一句"的语义。
   */
  const requested = ref(false)

  /**
   * 取出"距离上次打开前端页面"的秒数，同时把本次打开时间写回本地。
   * 首次访问返回 undefined（后端会退化成普通寒暄）。
   */
  function takeAwaySeconds(now = Date.now()): number | undefined {
    let previous: number | undefined
    try {
      const raw = localStorage.getItem(LAST_VISIT_STORAGE_KEY)
      previous = raw ? Number(raw) : undefined
    }
    catch {}
    try {
      localStorage.setItem(LAST_VISIT_STORAGE_KEY, String(now))
    }
    catch {}
    return computeAwaySeconds(previous, now)
  }

  function markRequested() {
    requested.value = true
  }

  function resetState() {
    enabled.reset()
    requested.value = false
  }

  return { enabled, requested, takeAwaySeconds, markRequested, resetState }
})
