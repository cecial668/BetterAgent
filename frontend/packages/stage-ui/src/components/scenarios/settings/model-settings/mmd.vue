<script setup lang="ts">
import type { MMDGazeMode, MorphSlot } from '@proj-airi/stage-ui-mmd'

import type { ModelSettingsRuntimeSnapshot } from './runtime'

import { controlConfig, Emotion, useMMD } from '@proj-airi/stage-ui-mmd'
import { Button, FieldCheckbox, FieldCombobox, FieldRange, GhostButton } from '@proj-airi/ui'
import { useFileDialog } from '@vueuse/core'
import { storeToRefs } from 'pinia'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

import { Container, PropertyColor, PropertyNumber } from '../../../data-pane'
import { Section } from '../../../layouts'
import { ColorPalette } from '../../../widgets'
import MotionGroupEditor from './motion-group-editor.vue'

const props = withDefaults(defineProps<{
  palette: string[]
  allowExtractColors?: boolean
  runtimeSnapshot: ModelSettingsRuntimeSnapshot
}>(), {
  allowExtractColors: true,
})

defineEmits<{
  (e: 'extractColorsFromModel'): void
}>()

const { t } = useI18n()

const mmdStore = useMMD()
const {
  scale,
  position,
  rotationY,
  physicsEnabled,
  ikEnabled,
  grantEnabled,
  physicsGravity,
  gazeMode,
  idleMotionName,
  availableMotions,
  normalizeRootMotion,
  emotionActionGroups,
  fallbackActionGroup,
  idleRandomEnabled,
  idleActionGroup,
  idleRandomMinSeconds,
  idleRandomMaxSeconds,
  speakingGesturesEnabled,
  availableMorphs,
  availableMaterials,
  materialOpacity,
  morphOverrides,
  cameraFov,
  ambientColor,
  ambientIntensity,
  directionalColor,
  directionalIntensity,
  directionalPosition,
  albedoGlow,
  renderScale,
} = storeToRefs(mmdStore)

const {
  addEmotionAction,
  removeEmotionAction,
  addFallbackAction,
  removeFallbackAction,
  addIdleAction,
  removeIdleAction,
} = mmdStore

const canExtractColors = computed(() => props.runtimeSnapshot.canCapturePreview)

// VRM-style eye-tracking buttons placed in the scene grid (cols 3–5).
const trackingOptions = computed<{ value: MMDGazeMode, label: string, class: string }[]>(() => [
  { value: 'camera', label: t('settings.mmd.gaze.options.camera'), class: 'col-start-3' },
  { value: 'mouse', label: t('settings.mmd.gaze.options.cursor'), class: 'col-start-4' },
  { value: 'none', label: t('settings.mmd.gaze.options.none'), class: 'col-start-5' },
])

const motionOptions = computed(() => availableMotions.value.map(motion => ({
  label: motion.name,
  value: motion.name,
  description: '',
})))

// '(auto)' lets the renderer pick the morph by its standard-name candidates.
const morphOptions = computed(() => [
  { label: t('settings.mmd.morphs.auto'), value: '', description: '' },
  ...availableMorphs.value.map(name => ({ label: name, value: name, description: '' })),
])

/** Logical morph slots exposed for manual remapping, grouped by purpose. */
const MORPH_SLOTS: { slot: MorphSlot, label: string }[] = [
  { slot: 'vowelA', label: 'Mouth あ (A)' },
  { slot: 'vowelI', label: 'Mouth い (I)' },
  { slot: 'vowelU', label: 'Mouth う (U)' },
  { slot: 'vowelE', label: 'Mouth え (E)' },
  { slot: 'vowelO', label: 'Mouth お (O)' },
  { slot: 'blink', label: 'Blink' },
  { slot: 'blinkLeft', label: 'Wink (L)' },
  { slot: 'blinkRight', label: 'Wink (R)' },
  { slot: 'smile', label: 'Smile' },
  { slot: 'anger', label: 'Anger' },
  { slot: 'sad', label: 'Sad' },
  { slot: 'surprise', label: 'Surprise' },
  { slot: 'troubled', label: 'Troubled' },
  { slot: 'serious', label: 'Serious' },
]

/** Emotion -> one-shot gesture motion rows, in the renderer's own vocabulary order. */
const EMOTION_MAP_ROWS: { emotion: Emotion, labelKey: string }[] = [
  { emotion: Emotion.Happy, labelKey: 'settings.mmd.emotions.happy' },
  { emotion: Emotion.Sad, labelKey: 'settings.mmd.emotions.sad' },
  { emotion: Emotion.Angry, labelKey: 'settings.mmd.emotions.angry' },
  { emotion: Emotion.Think, labelKey: 'settings.mmd.emotions.think' },
  { emotion: Emotion.Surprise, labelKey: 'settings.mmd.emotions.surprised' },
  { emotion: Emotion.Awkward, labelKey: 'settings.mmd.emotions.awkward' },
  { emotion: Emotion.Question, labelKey: 'settings.mmd.emotions.question' },
  { emotion: Emotion.Curious, labelKey: 'settings.mmd.emotions.curious' },
  { emotion: Emotion.Neutral, labelKey: 'settings.mmd.emotions.neutral' },
]

function handleIdleMotionSelect(name: string | number | undefined) {
  if (typeof name !== 'string')
    return
  idleMotionName.value = name
}

function setMorphOverride(slot: MorphSlot, value: string | number | undefined) {
  if (typeof value !== 'string')
    return
  morphOverrides.value = { ...morphOverrides.value, [slot]: value }
}

function setMaterialOpacity(name: string, value: number) {
  materialOpacity.value = { ...materialOpacity.value, [name]: value }
}

const vmdDialog = useFileDialog({ accept: '.vmd', multiple: true, reset: true })
vmdDialog.onChange(async (files) => {
  if (!files)
    return
  for (const file of Array.from(files)) {
    const descriptor = await mmdStore.addMotion(file)
    // Make the first imported motion the idle if none is chosen yet, so the
    // character immediately animates instead of standing in rest pose.
    if (!idleMotionName.value)
      idleMotionName.value = descriptor.name
  }
})

function playMotionOnce(name: string) {
  mmdStore.playOneShotAction(name, false)
}

function removeMotion(id: string) {
  void mmdStore.removeMotion(id)
}
</script>

<template>
  <Container
    :title="t('settings.pages.models.sections.section.scene')"
    icon="i-solar:people-nearby-bold-duotone"
    :class="['rounded-xl', 'bg-white/80 dark:bg-black/75', 'backdrop-blur-lg']"
  >
    <template v-if="allowExtractColors">
      <ColorPalette class="mb-4 mt-2" :colors="palette.map(hex => ({ hex, name: hex }))" mx-auto />
      <Button :disabled="!canExtractColors" @click="$emit('extractColorsFromModel')">
        {{ t('settings.mmd.theme-color-from-model.button-extract.title') }}
      </Button>
    </template>

    <div grid="~ cols-5 gap-1" p-2>
      <PropertyNumber
        v-model="scale"
        :config="{ min: controlConfig.scale.min, max: controlConfig.scale.max, step: controlConfig.scale.step, label: 'Scale', formatValue: val => val?.toFixed(2) }"
        :label="t('settings.mmd.scale-and-position.scale')"
      />
      <PropertyNumber
        v-model="position.x"
        :config="{ min: controlConfig.x.min, max: controlConfig.x.max, step: controlConfig.x.step, label: 'X', formatValue: val => val?.toFixed(2) }"
        :label="t('settings.mmd.scale-and-position.x')"
      />
      <PropertyNumber
        v-model="position.y"
        :config="{ min: controlConfig.y.min, max: controlConfig.y.max, step: controlConfig.y.step, label: 'Y', formatValue: val => val?.toFixed(2) }"
        :label="t('settings.mmd.scale-and-position.y')"
      />
      <PropertyNumber
        v-model="cameraFov"
        :config="{ min: 10, max: 120, step: 1, label: 'FOV' }"
        label="Camera FOV"
      />
      <PropertyNumber
        v-model="rotationY"
        :config="{ min: controlConfig.rotationY.min, max: controlConfig.rotationY.max, step: controlConfig.rotationY.step, label: 'Rotation', formatValue: val => val?.toFixed(2) }"
        :label="t('settings.mmd.scale-and-position.rotation')"
      />

      <!-- Eye tracking mode -->
      <div class="text-xs">
        {{ t('settings.mmd.gaze.tracking') }}:
      </div>
      <div />
      <template v-for="option in trackingOptions" :key="option.value">
        <GhostButton
          :class="[option.class, 'w-auto']"
          size="sm"
          :active="gazeMode === option.value"
          :label="option.label"
          @click="gazeMode = option.value"
        />
      </template>

      <PropertyNumber
        v-model="directionalPosition.x"
        :config="{ min: -10, max: 10, step: 0.1, label: 'X' }"
        label="Directional Light - X"
      />
      <PropertyNumber
        v-model="directionalPosition.y"
        :config="{ min: -10, max: 10, step: 0.1, label: 'Y' }"
        label="Directional Light - Y"
      />
      <PropertyNumber
        v-model="directionalPosition.z"
        :config="{ min: -10, max: 10, step: 0.1, label: 'Z' }"
        label="Directional Light - Z"
      />
      <PropertyColor
        v-model="directionalColor"
        label="Directional Light Color"
      />
      <PropertyNumber
        v-model="directionalIntensity"
        :config="{ min: 0, max: 3, step: 0.01, label: 'Intensity' }"
        label="Directional Light Intensity"
      />

      <PropertyNumber
        v-model="ambientIntensity"
        :config="{ min: 0, max: 3, step: 0.01, label: 'Intensity' }"
        label="Ambient Light Intensity"
      />
      <PropertyColor
        v-model="ambientColor"
        label="Ambient Light Color"
      />

      <PropertyNumber
        v-model="albedoGlow"
        :config="{ min: 0, max: 1, step: 0.01, label: 'Glow', formatValue: val => val?.toFixed(2) }"
        label="Albedo Glow"
      />
      <PropertyNumber
        v-model="renderScale"
        :config="{ min: 0.5, max: 2, step: 0.1, label: 'Scale' }"
        label="Render Scale"
      />
    </div>
  </Container>

  <Section
    :title="t('settings.mmd.physics.title')"
    icon="i-solar:atom-bold-duotone"
    :class="['rounded-xl', 'bg-white/80 dark:bg-black/75', 'backdrop-blur-lg']"
    size="sm"
    :expand="false"
  >
    <FieldCheckbox v-model="physicsEnabled" :label="t('settings.mmd.physics.enabled')" />
    <FieldCheckbox v-model="ikEnabled" :label="t('settings.mmd.physics.ik')" />
    <FieldCheckbox v-model="grantEnabled" :label="t('settings.mmd.physics.grant')" />
    <FieldRange
      v-model="physicsGravity"
      as="div"
      :min="0"
      :max="200"
      :step="1"
      :default-value="98"
      :label="t('settings.mmd.physics.gravity')"
    />
  </Section>

  <Section
    :title="t('settings.mmd.animation.title')"
    icon="i-solar:play-bold-duotone"
    inner-class="text-sm"
    :class="['rounded-xl', 'bg-white/80 dark:bg-black/75', 'backdrop-blur-lg']"
    size="sm"
    :expand="false"
  >
    <p :class="['mb-2', 'text-xs', 'text-neutral-500', 'dark:text-neutral-400']">
      {{ t('settings.mmd.animation.description') }}
    </p>
    <Button :class="['mb-2']" @click="vmdDialog.open()">
      {{ t('settings.mmd.animation.import-motion') }}
    </Button>
    <FieldCombobox
      v-if="motionOptions.length > 0"
      :model-value="idleMotionName"
      :options="motionOptions"
      :label="t('settings.mmd.animation.idle-motion')"
      @update:model-value="handleIdleMotionSelect"
    />
    <FieldCheckbox
      v-if="availableMotions.length > 0"
      v-model="normalizeRootMotion"
      :class="['mt-2']"
      label="对话动作锁定站位与朝向"
      description="有些动作（尤其「背景角色用」对谈动作）把站位和转身写在根骨骼上，开启后会归一化到默认位置并面朝前方；需要保留走位的舞蹈类动作可关闭。切换后会重新加载全部动作。"
    />
    <div
      v-if="availableMotions.length > 0"
      :class="['mt-3', 'flex', 'flex-col', 'gap-2', 'rounded-lg', 'border', 'border-neutral-200/70', 'p-3', 'dark:border-neutral-700/70']"
    >
      <FieldCheckbox
        v-model="idleRandomEnabled"
        label="待机随机动作"
        description="空闲时从下面的「待机动作组」里随机播放动作，播完自动回待机；说话期间倒计时暂停、说完继续（不会从头重排，聊天多也能触发）。"
      />
      <FieldRange
        v-if="idleRandomEnabled"
        v-model="idleRandomMinSeconds"
        as="div"
        :min="1"
        :max="120"
        :step="1"
        :default-value="6"
        label="两次动作最短间隔（秒）"
      />
      <FieldRange
        v-if="idleRandomEnabled"
        v-model="idleRandomMaxSeconds"
        as="div"
        :min="2"
        :max="300"
        :step="1"
        :default-value="15"
        label="两次动作最长间隔（秒）"
      />
      <div v-if="idleRandomEnabled" :class="['text-xs', 'text-neutral-500', 'dark:text-neutral-400']">
        动作之间的基础站姿由上方「待机动作」决定；若显得僵，可换一个有呼吸/摆动、可循环的动作。
      </div>
      <div :class="['text-xs', 'text-neutral-500', 'dark:text-neutral-400']">
        待机动作组（触发时随机播放一个）
      </div>
      <MotionGroupEditor
        :group="idleActionGroup"
        :motions="availableMotions"
        @add="addIdleAction"
        @remove="removeIdleAction"
      />
    </div>
    <div v-if="availableMotions.length > 0" :class="['mt-2', 'flex', 'flex-col', 'gap-1']">
      <div
        v-for="motion in availableMotions"
        :key="motion.name"
        :class="['flex', 'items-center', 'justify-between', 'gap-2']"
      >
        <div :class="['truncate', 'text-sm']">
          {{ motion.name }}
        </div>
        <div :class="['flex', 'shrink-0', 'items-center', 'gap-1']">
          <Button @click="playMotionOnce(motion.name)">
            {{ t('settings.mmd.animation.play-once') }}
          </Button>
          <Button

            :aria-label="t('settings.mmd.animation.remove')"
            @click="removeMotion(motion.id)"
          >
            <div i-solar:trash-bin-minimalistic-bold-duotone />
          </Button>
        </div>
      </div>
    </div>
  </Section>

  <Section
    :title="t('settings.mmd.emotions.title')"
    icon="i-solar:heart-pulse-bold-duotone"
    inner-class="text-sm"
    :class="['rounded-xl', 'bg-white/80 dark:bg-black/75', 'backdrop-blur-lg']"
    size="sm"
    :expand="false"
  >
    <p :class="['mb-2', 'text-xs', 'text-neutral-500', 'dark:text-neutral-400']">
      {{ t('settings.mmd.emotions.description') }}
    </p>
    <FieldCheckbox
      v-if="availableMotions.length > 0"
      v-model="speakingGesturesEnabled"
      :class="['mb-3']"
      label="说话时持续动作"
      description="说话期间从当前情绪的动作组里一个接一个随机播（动作之间停 0.4~1.2 秒），整段台词都在演；关闭则只在情绪触发时播一个动作。与待机随机动作无关。"
    />
    <div :class="['flex', 'flex-col', 'gap-3']">
      <div
        v-for="row in EMOTION_MAP_ROWS"
        :key="row.emotion"
        :class="['flex', 'flex-col', 'gap-1']"
      >
        <div :class="['text-xs', 'text-neutral-500', 'dark:text-neutral-400']">
          {{ t(row.labelKey) }}
        </div>
        <MotionGroupEditor
          :group="emotionActionGroups[row.emotion] ?? []"
          :motions="availableMotions"
          @add="name => addEmotionAction(row.emotion, name)"
          @remove="name => removeEmotionAction(row.emotion, name)"
        />
      </div>
      <div :class="['flex', 'flex-col', 'gap-1', 'border-t', 'border-neutral-200/70', 'pt-2', 'dark:border-neutral-700/70']">
        <div :class="['text-xs', 'text-neutral-500', 'dark:text-neutral-400']">
          通用备选（某情绪组为空时随机播放；全部为空则只做表情）
        </div>
        <MotionGroupEditor
          :group="fallbackActionGroup"
          :motions="availableMotions"
          @add="addFallbackAction"
          @remove="removeFallbackAction"
        />
      </div>
    </div>
  </Section>

  <Section
    :title="t('settings.mmd.morphs.title')"
    icon="i-solar:emoji-funny-square-bold-duotone"
    inner-class="text-sm"
    :class="['rounded-xl', 'bg-white/80 dark:bg-black/75', 'backdrop-blur-lg']"
    size="sm"
    :expand="false"
  >
    <p :class="['mb-2', 'text-xs', 'text-neutral-500', 'dark:text-neutral-400']">
      {{ t('settings.mmd.morphs.description') }}
    </p>
    <template v-if="availableMorphs.length > 0">
      <FieldCombobox
        v-for="entry in MORPH_SLOTS"
        :key="entry.slot"
        :model-value="morphOverrides[entry.slot] ?? ''"
        :options="morphOptions"
        :label="entry.label"
        @update:model-value="value => setMorphOverride(entry.slot, value)"
      >
        <template #label>
          <span>{{ entry.label }}</span>
          <button
            v-if="morphOverrides[entry.slot]"
            type="button"
            :title="t('settings.mmd.morphs.revert')"
            :aria-label="t('settings.mmd.morphs.revert')"
            :class="['ml-1', 'inline-flex', 'items-center']"
            @click.stop.prevent="setMorphOverride(entry.slot, '')"
          >
            <div :class="['i-solar:forward-linear', 'transform-scale-x--100', 'text-neutral-500', 'dark:text-neutral-400']" />
          </button>
        </template>
      </FieldCombobox>
    </template>
    <p v-else :class="['text-xs', 'text-amber-600', 'dark:text-amber-400']">
      {{ t('settings.mmd.morphs.no-morphs') }}
    </p>
  </Section>

  <Section
    :title="t('settings.mmd.materials.title')"
    icon="i-solar:layers-bold-duotone"
    inner-class="text-sm"
    :class="['rounded-xl', 'bg-white/80 dark:bg-black/75', 'backdrop-blur-lg']"
    size="sm"
    :expand="false"
  >
    <p :class="['mb-2', 'text-xs', 'text-neutral-500', 'dark:text-neutral-400']">
      {{ t('settings.mmd.materials.description') }}
    </p>
    <template v-if="availableMaterials.length > 0">
      <FieldRange
        v-for="material in availableMaterials"
        :key="material.index"
        as="div"
        :min="0"
        :max="1"
        :step="0.01"
        :default-value="1"
        :model-value="materialOpacity[material.name] ?? 1"
        :label="material.label"
        @update:model-value="value => setMaterialOpacity(material.name, value)"
      />
    </template>
    <p v-else :class="['text-xs', 'text-amber-600', 'dark:text-amber-400']">
      {{ t('settings.mmd.materials.no-materials') }}
    </p>
  </Section>
</template>
