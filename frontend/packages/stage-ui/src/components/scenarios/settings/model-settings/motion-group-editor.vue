<script setup lang="ts">
/**
 * 动作组编辑器：一组可互相替换的 VMD 动作（触发时随机播放一个）。
 * 用于 9 种情绪、通用备选与待机随机动作。选项来自已导入的动作列表。
 */
const props = defineProps<{
  /** 当前组内的动作名列表。 */
  group: string[]
  /** 已导入的动作（stage-ui-mmd 的 availableMotions）。 */
  motions: { id: string, name: string }[]
}>()

const emit = defineEmits<{
  (e: 'add' | 'remove', name: string): void
}>()

function handleAdd(event: Event) {
  const select = event.target as HTMLSelectElement
  const name = select.value
  if (name)
    emit('add', name)
  select.value = ''
}
</script>

<template>
  <div class="flex flex-wrap items-center gap-1.5">
    <span
      v-for="name in props.group"
      :key="name"
      class="inline-flex items-center gap-1 rounded-full bg-primary-100/70 px-2 py-0.5 text-xs text-primary-700 dark:bg-primary-900/40 dark:text-primary-200"
    >
      {{ name }}
      <button class="opacity-60 transition-opacity hover:opacity-100" title="移除" @click="emit('remove', name)">
        ×
      </button>
    </span>
    <select
      class="rounded-md border border-neutral-200 bg-white px-1.5 py-0.5 text-xs text-neutral-600 outline-none dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300"
      value=""
      @change="handleAdd"
    >
      <option value="" disabled>
        + 添加动作
      </option>
      <option v-for="motion in props.motions" :key="motion.id" :value="motion.name">
        {{ motion.name }}
      </option>
    </select>
  </div>
</template>
