<script setup lang="ts">
import { Button } from '@proj-airi/ui'
import { onMounted, ref } from 'vue'

import { usePersonaStore } from '@proj-airi/stage-ui/stores/persona'

import BasicProfileTab from './components/BasicProfileTab.vue'
import BoundaryTab from './components/BoundaryTab.vue'
import EmotionWeightTab from './components/EmotionWeightTab.vue'
import PersonaFieldGuide from './components/PersonaFieldGuide.vue'
import PromptEditorTab from './components/PromptEditorTab.vue'
import WebSearchTab from './components/WebSearchTab.vue'

const personaStore = usePersonaStore()
type PersonaTab = 'basic' | 'prompt' | 'boundary' | 'emotion' | 'websearch'
const activeTab = ref<PersonaTab>('prompt')

// 字段说明面板：点 ⓘ 打开，并自动跳到当前 tab 对应的章节。
const guideOpen = ref(false)

// tab -> 说明面板章节。加新 tab 时记得在这里补一条映射。
const TAB_TO_GUIDE_SECTION: Record<PersonaTab, string> = {
  prompt: 'prompt',
  basic: 'basic',
  emotion: 'emotion',
  boundary: 'boundary',
  websearch: 'websearch',
}

onMounted(() => {
  personaStore.fetchRemote().catch(console.error)
})
</script>

<template>
  <div class="h-full flex flex-col gap-6 p-4 md:p-6 max-w-5xl mx-auto">
    <!-- Header Section -->
    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
      <div>
        <div class="flex items-center gap-3">
          <h1 class="text-2xl text-neutral-900 font-bold dark:text-neutral-100 flex items-center gap-2">
            <div class="i-solar:user-speak-rounded-bold-duotone text-primary-500" />
            角色人设与交互边界
          </h1>
          <span
            class="rounded-full px-2.5 py-0.5 text-xs font-medium border"
            :class="personaStore.isSynced
              ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/30'
              : 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/30'"
          >
            {{ personaStore.isSynced ? 'Admin API 8094 已同步' : '纯本地/降级模式' }}
          </span>
        </div>
        <p class="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
          实时调节角色人设、对话风格、称呼词、提示词与知识边界（免重启 runner.py）。
        </p>
      </div>

      <div class="flex items-center gap-2">
        <div class="flex items-center gap-2">
          <div class="i-solar:card-2-bold-duotone text-lg text-primary-500" />
          <select
            class="min-w-[10rem] rounded-lg border border-neutral-200 bg-white px-2.5 py-2 text-sm text-neutral-700 outline-none transition-colors focus:border-primary-500 dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-200"
            :value="personaStore.personaId"
            :disabled="personaStore.personaList.length === 0"
            title="切换要查看/编辑的角色卡；带 ★ 的是系统当前激活的人设"
            @change="personaStore.selectPersona(($event.target as HTMLSelectElement).value)"
          >
            <option v-if="personaStore.personaList.length === 0" :value="personaStore.personaId">
              {{ personaStore.personaId }}
            </option>
            <option v-for="item in personaStore.personaList" :key="item.id" :value="item.id">
              {{ item.id === personaStore.activePersonaId ? '★ ' : '' }}{{ item.name || item.id }}
            </option>
          </select>
        </div>
        <button
          class="flex items-center gap-1.5 rounded-lg border border-neutral-200 px-3 py-2 text-sm text-neutral-600 transition-colors hover:border-primary-500 hover:text-primary-600 dark:border-neutral-800 dark:text-neutral-300 dark:hover:text-primary-400"
          title="查看角色卡每个字段的含义、示例与注意事项"
          @click="guideOpen = true"
        >
          <div class="i-solar:info-circle-bold text-base" />
          角色卡字段说明
        </button>
        <Button
          :disabled="personaStore.isFetching"
          class="!py-2"
          @click="personaStore.fetchRemote()"
        >
          <div v-if="personaStore.isFetching" class="i-svg-spinners:90-ring-with-bg mr-2 text-sm" />
          <div v-else class="i-solar:restart-bold mr-2 text-sm" />
          从 Admin 拉取
        </Button>
      </div>
    </div>

    <!-- Navigation Tabs Bar -->
    <div class="flex border-b border-neutral-200 dark:border-neutral-800 gap-2">
      <button
        class="flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors"
        :class="activeTab === 'prompt'
          ? 'border-primary-500 text-primary-600 dark:text-primary-400 font-semibold'
          : 'border-transparent text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-200'"
        @click="activeTab = 'prompt'"
      >
        <div class="i-solar:document-text-bold text-base" />
        提示词编辑 (Base Prompt)
      </button>

      <button
        class="flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors"
        :class="activeTab === 'basic'
          ? 'border-primary-500 text-primary-600 dark:text-primary-400 font-semibold'
          : 'border-transparent text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-200'"
        @click="activeTab = 'basic'"
      >
        <div class="i-solar:user-heart-bold text-base" />
        基础设定 (名称与称呼)
      </button>

      <button
        class="flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors"
        :class="activeTab === 'emotion'
          ? 'border-primary-500 text-primary-600 dark:text-primary-400 font-semibold'
          : 'border-transparent text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-200'"
        @click="activeTab = 'emotion'"
      >
        <div class="i-solar:slider-vertical-bold text-base" />
        性格权重 (傲娇/粘人)
      </button>

      <button
        class="flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors"
        :class="activeTab === 'boundary'
          ? 'border-primary-500 text-primary-600 dark:text-primary-400 font-semibold'
          : 'border-transparent text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-200'"
        @click="activeTab = 'boundary'"
      >
        <div class="i-solar:shield-warning-bold text-base" />
        交互边界与知识库
      </button>

      <button
        class="flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition-colors"
        :class="activeTab === 'websearch'
          ? 'border-primary-500 text-primary-600 dark:text-primary-400 font-semibold'
          : 'border-transparent text-neutral-500 hover:text-neutral-700 dark:text-neutral-400 dark:hover:text-neutral-200'"
        @click="activeTab = 'websearch'"
      >
        <div class="i-solar:global-bold text-base" />
        联网能力
      </button>
    </div>

    <!-- Active Tab Panel Content -->
    <div class="pb-16">
      <PromptEditorTab v-if="activeTab === 'prompt'" />
      <BasicProfileTab v-else-if="activeTab === 'basic'" />
      <EmotionWeightTab v-else-if="activeTab === 'emotion'" />
      <BoundaryTab v-else-if="activeTab === 'boundary'" />
      <WebSearchTab v-else-if="activeTab === 'websearch'" />
    </div>

    <!-- 角色卡字段说明（ⓘ） -->
    <PersonaFieldGuide
      v-model:open="guideOpen"
      :section="TAB_TO_GUIDE_SECTION[activeTab]"
    />
  </div>
</template>

<route lang="yaml">
meta:
  layout: settings
  title: 角色人设与交互边界
</route>

