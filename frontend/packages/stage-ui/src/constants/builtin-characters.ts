import type { Character } from '../types/character'

import { parse } from 'valibot'

import { CharacterWithRelationsSchema } from '../types/character'

/**
 * 内置角色卡：芙宁娜（BetterAgent 当前默认人设）。
 *
 * 前端「角色卡」页（settings/characters）的数据源是本地 IndexedDB + 远端社区
 * API；本 fork 没有远端 API，列表原本会一直空转。这里内置一张芙宁娜卡片，
 * store 在首次拉取时自动写入本地，用户可以查看/编辑/删除（删除后不再自动
 * 重建，见 stores/characters.ts 的 dismissed 记录）。
 */
export const BUILTIN_FURINA_CHARACTER_ID = 'builtin-furina'

export function buildBuiltinFurinaCharacter(): Character {
  const now = new Date()
  const id = BUILTIN_FURINA_CHARACTER_ID

  return parse(CharacterWithRelationsSchema, {
    id,
    version: '1.0.0',
    coverUrl: '',
    avatarUrl: undefined,
    characterAvatarUrl: undefined,
    coverBackgroundUrl: undefined,
    creatorRole: 'built-in',
    priceCredit: '0',
    likesCount: 0,
    bookmarksCount: 0,
    interactionsCount: 0,
    forksCount: 0,
    creatorId: 'betteragent',
    ownerId: 'betteragent',
    characterId: 'furina',
    createdAt: now,
    updatedAt: now,
    deletedAt: undefined,
    capabilities: [
      {
        id: 'builtin-furina-llm',
        characterId: id,
        type: 'llm',
        config: {
          apiKey: '',
          apiBaseUrl: '',
          llm: { temperature: 0.8, model: 'deepseek-flash' },
        },
      },
      {
        id: 'builtin-furina-tts',
        characterId: id,
        type: 'tts',
        config: {
          apiKey: '',
          apiBaseUrl: '',
          tts: { ssml: '', voiceId: 'furina', speed: 1, pitch: 0 },
        },
      },
    ],
    i18n: [
      {
        id: 'builtin-furina-zh',
        characterId: id,
        language: 'zh-CN',
        name: '芙宁娜',
        tagline: '枫丹的水神，也是会陪你排日程、干正事的数字人',
        description:
          'BetterAgent 当前默认角色卡：芙宁娜。日常口语、简短利落，会陪你专注工作、排日程、记录生活；'
          + '具体人设与说话方式在「设置 → 角色人设与交互边界」里调整（config/persona/furina.yaml）。',
        tags: ['原神', '枫丹', '数字人', '专注'],
        createdAt: now,
        updatedAt: now,
      },
    ],
    prompts: [
      {
        id: 'builtin-furina-system',
        characterId: id,
        language: 'zh-CN',
        type: 'system',
        content: '人设由 BetterAgent 后端的 config/persona/furina.yaml 提供，这里仅作为角色卡展示。',
      },
    ],
    likes: [],
    bookmarks: [],
  })
}
