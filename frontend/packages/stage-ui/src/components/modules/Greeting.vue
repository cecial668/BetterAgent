<script setup lang="ts">
import { FieldCheckbox } from '@proj-airi/ui'

import { useGreetingStore } from '../../stores/modules/greeting'

/**
 * 打招呼：打开前端网页时让她主动说一句问候。
 *
 * 触发发生在前端（页面加载 → WS user.greeting），后端只负责生成与播放，
 * 所以开关存浏览器本地（localStorage），无需 admin 后台参与。
 */
const greetingStore = useGreetingStore()
</script>

<template>
  <div flex="~ col gap-6">
    <FieldCheckbox
      v-model="greetingStore.enabled"
      label="打开前端页面时主动打招呼"
      description="每次打开舞台页面（刷新也算）她都会主动说一句问候：可能是寒暄、简单提下今天的安排、有趣的见闻，或提到你多久没来。内容由模型现场生成，每次都不一样。"
    />

    <div class="flex flex-col gap-2 rounded-lg border border-neutral-200 p-4 text-xs text-neutral-500 dark:border-neutral-800 dark:text-neutral-400">
      <div>· 只在打开/刷新前端网页时触发；从设置页返回舞台、网络重连、切浏览器标签都不会重复打招呼。</div>
      <div>· 连续刷新有 10 秒冷却；她正在说话或思考时不会被打断（这次直接跳过）。</div>
      <div>· 第一次访问没有「离开时长」可参考，会按普通寒暄处理。</div>
      <div>· 浏览器可能会拦截页面刚打开时的自动播放：点一下页面即可听到声音，之后同一站点不再拦截。</div>
    </div>
  </div>
</template>
