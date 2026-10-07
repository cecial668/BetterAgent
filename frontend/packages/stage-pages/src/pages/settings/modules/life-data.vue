<script setup lang="ts">
import { LifeData } from '@proj-airi/stage-ui/components'
</script>

<template>
  <LifeData />
</template>

<route lang="yaml">
meta:
  layout: settings
  title: 生活数据（向着星）
  subtitleKey: settings.title
  stageTransition:
    name: slide
    pageSpecificAvailable: true
</route>
