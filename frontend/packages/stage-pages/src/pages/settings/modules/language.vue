<script setup lang="ts">
import type { MMDLipSyncMode } from '@proj-airi/stage-ui/stores/modules/language'

import { useLanguageModuleStore } from '@proj-airi/stage-ui/stores/modules/language'
import { storeToRefs } from 'pinia'

const languageModuleStore = useLanguageModuleStore()
const { mmdLipSyncMode } = storeToRefs(languageModuleStore)

const modes: { id: MMDLipSyncMode, title: string, description: string, icon: string }[] = [
  {
    id: 'viseme',
    title: '逐字口型（推荐）',
    description: '服务端按整句真实时长生成口型时间轴，逐音节切换元音口型，接近原神剧情演绎的观感。',
    icon: 'i-solar:user-speak-rounded-bold-duotone',
  },
  {
    id: 'audio',
    title: '音频驱动',
    description: '实时分析播放音频的共振峰连续驱动口型，过渡更平滑，但逐字口型感较弱。',
    icon: 'i-solar:waveform-bold-duotone',
  },
]
</script>

<template>
  <div flex="~ col gap-4">
    <div
      v-for="mode in modes"
      :key="mode.id"
      flex="~ items-center gap-4"
      cursor-pointer rounded-xl border p-4 transition-colors
      :class="mmdLipSyncMode === mode.id
        ? 'border-primary-500/60 bg-primary-500/10'
        : 'border-neutral-200/60 bg-neutral-50/60 dark:border-neutral-700/60 dark:bg-neutral-900/40'"
      @click="mmdLipSyncMode = mode.id"
    >
      <div :class="mode.icon" text-3xl text-primary-500 />
      <div flex="~ col gap-1">
        <div font-medium>
          {{ mode.title }}
          <span v-if="mmdLipSyncMode === mode.id" text-primary-500 text-sm>（当前）</span>
        </div>
        <div text-neutral-500 text-sm>
          {{ mode.description }}
        </div>
      </div>
    </div>

    <div text-neutral-500 text-xs>
      仅影响 MMD 模型的嘴型驱动方式；Live2D / VRM 使用各自既有管线。切换后立即生效，无需重启。
    </div>
  </div>
</template>

<route lang="yaml">
meta:
  layout: settings
  title: 语言模块
  subtitleKey: settings.title
  stageTransition:
    name: slide
</route>
