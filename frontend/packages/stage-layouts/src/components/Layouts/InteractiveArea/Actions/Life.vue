<script setup lang="ts">
import { onClickOutside, onKeyStroke } from '@vueuse/core'
import { ref } from 'vue'

import LifeHUDWidget from '../../../../../../../apps/stage-web/src/components/LifeHUDWidget.vue'

const show = ref(false)
const wrap = ref<HTMLElement | null>(null)

onClickOutside(wrap, () => { show.value = false })
onKeyStroke('Escape', () => { show.value = false })
</script>

<template>
  <div ref="wrap" class="relative w-fit">
    <button
      title="生活概览（向着星）"
      :class="[
        'w-fit p-2',
        'flex justify-center md:items-center self-end',
        'border-2 border-solid border-neutral-100/60 dark:border-neutral-800/30',
        'bg-neutral-50/70 dark:bg-neutral-800/70',
        'backdrop-blur-md',
        'rounded-xl transition-transform active:scale-95',
      ]"
      @click="show = !show"
    >
      <div class="i-solar:notebook-bold-duotone size-5 text-amber-500 dark:text-amber-400" />
    </button>
    <LifeHUDWidget v-if="show" @close="show = false" />
  </div>
</template>
