<script setup lang="ts">
import { Greeting } from '@proj-airi/stage-ui/components'
</script>

<template>
  <Greeting />
</template>

<route lang="yaml">
meta:
  layout: settings
  title: 打招呼
  subtitleKey: settings.title
  stageTransition:
    name: slide
    pageSpecificAvailable: true
</route>
