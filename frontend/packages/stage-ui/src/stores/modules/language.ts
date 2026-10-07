import { useLocalStorageManualReset } from '@proj-airi/stage-shared/composables'
import { defineStore } from 'pinia'
import { computed } from 'vue'

/**
 * How MMD lip-sync is driven:
 * - 'viseme' (default): the server-side viseme timeline -- one mouth shape per
 *   syllable, laid out over the utterance's true duration -- drives discrete
 *   cutscene-like mouth shapes.
 * - 'audio': continuous wLipSync formant analysis of the audio being played;
 *   smoother transitions, but loses the per-syllable articulation.
 */
export type MMDLipSyncMode = 'viseme' | 'audio'

export const useLanguageModuleStore = defineStore('language-module', () => {
  const mmdLipSyncMode = useLocalStorageManualReset<MMDLipSyncMode>(
    'settings/language/mmd-lip-sync-mode',
    'viseme',
  )

  // Local-only settings with sane defaults -- this module is always usable.
  const configured = computed(() => true)

  return {
    configured,
    mmdLipSyncMode,
  }
})
