import type { TothestarsConfig, TothestarsConfigPatch } from '../../services/betteragent-admin-api'

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { getTothestarsConfig, updateTothestarsConfig } from '../../services/betteragent-admin-api'

/**
 * 「生活数据（向着星）」设置的状态与持久化。
 *
 * 真源在 `config/config.yaml` 的 `integration.tothestars`，由 Admin 后台
 * (:8094) 读写；本 store 只是它在前端的缓存 + 加载/保存动作。认知服务每轮
 * 工具门控与提示词注入都实时读那份配置，所以保存成功 = 立即生效，无需重启。
 *
 * 后台不可达时 config 保持 null（`unreachable`），设置页进入只读提示状态，
 * 而不是假装保存成功。
 */
export const useLifeDataStore = defineStore('life-data', () => {
  const config = ref<TothestarsConfig | null>(null)
  const loading = ref(false)
  const saving = ref(false)
  /** 至少尝试过一次加载；用于区分"还没加载"和"加载了但后台不可达"。 */
  const loaded = ref(false)

  const unreachable = computed(() => loaded.value && config.value === null)
  /** 卡片上的"已配置"圆点：联动开关真的打开才算数。 */
  const configured = computed(() => !!config.value?.enabled)

  async function load(force = false): Promise<TothestarsConfig | null> {
    if (loading.value)
      return config.value
    if (loaded.value && !force)
      return config.value
    loading.value = true
    try {
      config.value = await getTothestarsConfig()
      loaded.value = true
    }
    finally {
      loading.value = false
    }
    return config.value
  }

  async function save(patch: TothestarsConfigPatch): Promise<TothestarsConfig | null> {
    saving.value = true
    try {
      const next = await updateTothestarsConfig(patch)
      if (next)
        config.value = next
      return next
    }
    finally {
      saving.value = false
    }
  }

  return {
    config,
    loading,
    saving,
    loaded,
    unreachable,
    configured,
    load,
    save,
  }
})
