import type { BeatSyncDetectorState } from '@proj-airi/stage-shared/beat-sync'

import { getBeatSyncState, isBeatSyncSupported, listenBeatSyncStateChange } from '@proj-airi/stage-shared/beat-sync'
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

import factorioIcon from '../assets/factorio-simple.png'

import { getWebSearchConfig } from '../services/betteragent-admin-api'

import { useArtistryStore } from '../stores/modules/artistry'
import { useConsciousnessStore } from '../stores/modules/consciousness'
import { useDiscordStore } from '../stores/modules/discord'
import { useFactorioStore } from '../stores/modules/gaming-factorio'
import { useMinecraftStore } from '../stores/modules/gaming-minecraft'
import { useGreetingStore } from '../stores/modules/greeting'
import { useHearingStore } from '../stores/modules/hearing'
import { useLanguageModuleStore } from '../stores/modules/language'
import { useLifeDataStore } from '../stores/modules/life-data'
import { useSpeechStore } from '../stores/modules/speech'
import { useTwitterStore } from '../stores/modules/twitter'
import { useVisionStore } from '../stores/modules/vision'
import { useWebSearchStore } from '../stores/modules/web-search'

export interface Module {
  id: string
  name: string
  description: string
  icon?: string
  iconColor?: string
  iconImage?: string
  to: string
  configured: boolean
  category: string
}

export function useModulesList() {
  const { t } = useI18n()

  // Initialize stores
  const consciousnessStore = useConsciousnessStore()
  const speechStore = useSpeechStore()
  const hearingStore = useHearingStore()
  const languageModuleStore = useLanguageModuleStore()
  const lifeDataStore = useLifeDataStore()
  const greetingStore = useGreetingStore()
  const visionStore = useVisionStore()
  const discordStore = useDiscordStore()
  const twitterStore = useTwitterStore()
  const webSearchStore = useWebSearchStore()
  const minecraftStore = useMinecraftStore()
  const factorioStore = useFactorioStore()
  const artistryStore = useArtistryStore()
  const beatSyncState = ref<BeatSyncDetectorState>()
  const beatSyncSupported = isBeatSyncSupported()

  // 联网搜索页现在直连 admin 后端（见 components/modules/WebSearch.vue），而
  // webSearchStore.configured 读的是 AIRI 上游那个只写 localStorage 的 module store
  // —— 那个 Key 只有浏览器自己看得见，对本项目从来没有任何作用。卡片状态若继续只
  // 看它，就会出现"卡片说未配置、点进去说已就绪"的自相矛盾，所以这里以后台为准。
  const webSearchBackendConfigured = ref(false)

  minecraftStore.initialize()

  const modulesList = computed<Module[]>(() => [
    {
      id: 'consciousness',
      name: t('settings.pages.modules.consciousness.title'),
      description: t('settings.pages.modules.consciousness.description'),
      icon: 'i-solar:ghost-bold-duotone',
      to: '/settings/modules/consciousness',
      configured: consciousnessStore.configured,
      category: 'essential',
    },
    {
      id: 'speech',
      name: t('settings.pages.modules.speech.title'),
      description: t('settings.pages.modules.speech.description'),
      icon: 'i-solar:user-speak-rounded-bold-duotone',
      to: '/settings/modules/speech',
      configured: speechStore.configured,
      category: 'essential',
    },
    {
      id: 'hearing',
      name: t('settings.pages.modules.hearing.title'),
      description: t('settings.pages.modules.hearing.description'),
      icon: 'i-solar:microphone-3-bold-duotone',
      to: '/settings/modules/hearing',
      configured: hearingStore.configured,
      category: 'essential',
    },
    {
      // BetterAgent-local module (no upstream AIRI equivalent): lip-sync mode
      // and related speech-appearance settings. Hardcoded Chinese name on
      // purpose -- adding keys to every upstream locale file just for this
      // fork-local module would be churn for no user-visible gain.
      id: 'language',
      name: '语言模块',
      description: '口型同步与说话表现的本地设置',
      icon: 'i-solar:chat-round-dots-bold-duotone',
      to: '/settings/modules/language',
      configured: languageModuleStore.configured,
      category: 'essential',
    },
    {
      id: 'vision',
      name: t('settings.pages.modules.vision.title'),
      description: t('settings.pages.modules.vision.description'),
      icon: 'i-solar:eye-closed-bold-duotone',
      to: '/settings/modules/vision',
      configured: visionStore.configured,
      category: 'essential',
    },
    {
      // BetterAgent-local module（fork 本地页，名称固定中文，理由同语言模块）。
      // 卡片圆点以后台配置为准：联动开关真的打开才算"已配置"。
      id: 'life-data',
      name: '生活数据（向着星）',
      description: '她能看到、能改动哪些生活数据，以及主动提及策略',
      icon: 'i-solar:notebook-bold-duotone',
      to: '/settings/modules/life-data',
      configured: lifeDataStore.configured,
      category: 'essential',
    },
    {
      // BetterAgent-local module（fork 本地页，名称固定中文，理由同语言模块）。
      // 开关存浏览器本地：触发动作发生在前端页面打开时，与后端配置无关。
      id: 'greeting',
      name: '打招呼',
      description: '打开前端页面时让她主动说一句问候（寒暄 / 今日安排 / 久别提醒）',
      icon: 'i-solar:chat-line-bold-duotone',
      to: '/settings/modules/greeting',
      configured: greetingStore.enabled,
      category: 'essential',
    },
    {
      id: 'web-search',
      name: t('settings.pages.modules.web-search.title'),
      description: t('settings.pages.modules.web-search.description'),
      icon: 'i-solar:magnifer-bold-duotone',
      to: '/settings/modules/web-search',
      // 卡片上那个"已配置"圆点：后台真的能联网（开关开 + Key 已填）才算数。
      configured: webSearchStore.configured || webSearchBackendConfigured.value,
      category: 'essential',
    },
    {
      id: 'artistry',
      name: t('settings.pages.modules.artistry.title'),
      description: t('settings.pages.modules.artistry.description'),
      icon: 'i-solar:palette-bold-duotone',
      to: '/settings/modules/artistry',
      configured: artistryStore.configured,
      category: 'essential',
    },
    {
      id: 'memory-short-term',
      name: t('settings.pages.modules.memory-short-term.title'),
      description: t('settings.pages.modules.memory-short-term.description'),
      icon: 'i-solar:bookmark-bold-duotone',
      to: '/settings/modules/memory-short-term',
      configured: false,
      category: 'essential',
    },
    {
      id: 'memory-long-term',
      name: t('settings.pages.modules.memory-long-term.title'),
      description: t('settings.pages.modules.memory-long-term.description'),
      icon: 'i-solar:book-bookmark-bold-duotone',
      to: '/settings/modules/memory-long-term',
      configured: false,
      category: 'essential',
    },
    {
      id: 'messaging-discord',
      name: t('settings.pages.modules.messaging-discord.title'),
      description: t('settings.pages.modules.messaging-discord.description'),
      icon: 'i-simple-icons:discord',
      to: '/settings/modules/messaging-discord',
      configured: discordStore.configured,
      category: 'messaging',
    },
    {
      id: 'x',
      name: t('settings.pages.modules.x.title'),
      description: t('settings.pages.modules.x.description'),
      icon: 'i-simple-icons:x',
      to: '/settings/modules/x',
      configured: twitterStore.configured,
      category: 'messaging',
    },
    {
      id: 'gaming-minecraft',
      name: t('settings.pages.modules.gaming-minecraft.title'),
      description: t('settings.pages.modules.gaming-minecraft.description'),
      iconColor: 'i-vscode-icons:file-type-minecraft',
      to: '/settings/modules/gaming-minecraft',
      configured: minecraftStore.configured,
      category: 'gaming',
    },
    {
      id: 'gaming-factorio',
      name: t('settings.pages.modules.gaming-factorio.title'),
      description: t('settings.pages.modules.gaming-factorio.description'),
      iconImage: factorioIcon,
      to: '/settings/modules/gaming-factorio',
      configured: factorioStore.configured,
      category: 'gaming',
    },
    {
      id: 'mcp-server',
      name: t('settings.pages.modules.mcp-server.title'),
      description: t('settings.pages.modules.mcp-server.description'),
      icon: 'i-solar:server-bold-duotone',
      to: '/settings/modules/mcp',
      configured: false,
      category: 'essential',
    },
    ...(beatSyncSupported
      ? [{
          id: 'beat-sync',
          name: t('settings.pages.modules.beat_sync.title'),
          description: t('settings.pages.modules.beat_sync.description'),
          icon: 'i-solar:music-notes-bold-duotone',
          to: '/settings/modules/beat-sync',
          configured: beatSyncState.value?.isActive ?? false,
          category: 'essential',
        }]
      : []),
  ])

  const categorizedModules = computed(() => {
    return modulesList.value.reduce((categories, module) => {
      const { category } = module
      if (!categories[category]) {
        categories[category] = []
      }
      categories[category].push(module)
      return categories
    }, {} as Record<string, Module[]>)
  })

  // Define category display names
  const categoryNames = computed(() => ({
    essential: t('settings.pages.modules.categories.essential'),
    messaging: t('settings.pages.modules.categories.messaging'),
    gaming: t('settings.pages.modules.categories.gaming'),
  }))

  // TODO(Makito): We can make this a reactive value from a synthetic store.
  onMounted(() => {
    // 后台不可达时保持"未配置"，与联网搜索页里那条"连不上后台"的提示口径一致。
    getWebSearchConfig()
      .then(cfg => webSearchBackendConfigured.value = !!(cfg?.enabled && cfg?.key_set))
      .catch(() => {})

    // 生活数据卡片同理：以后台 integration.tothestars.enabled 为准。
    lifeDataStore.load().catch(() => {})

    if (!beatSyncSupported)
      return

    getBeatSyncState().then(initialState => beatSyncState.value = initialState)
    const removeListener = listenBeatSyncStateChange(newState => beatSyncState.value = { ...newState })
    onUnmounted(() => removeListener())
  })

  return {
    modulesList,
    categorizedModules,
    categoryNames,
  }
}
