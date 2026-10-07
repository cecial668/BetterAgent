/**
 * 动作组随机器：从一个"动作组"（同一情绪/情景下可互相替换的多个 VMD）里
 * 随机挑一个，并尽量避免与上次重复。触发点的语义是"情绪/情景"，具体动作
 * 由玩家在设置里编排。
 */

/**
 * @param group     玩家配置的动作组（动作名列表）
 * @param available 当前模型已注册的动作名（组里可能有已删除/未导入的名字）
 * @param lastPlayed 上一次播放的动作名（>1 个候选时避免连续重复）
 * @returns 随机选中的动作名；组为空或全部不可用时返回 undefined
 */
export function pickMotionFromGroup(
  group: readonly string[] | undefined,
  available: readonly string[],
  lastPlayed?: string,
): string | undefined {
  const availableSet = new Set(available)
  const candidates = (group ?? []).filter(name => availableSet.has(name))
  if (!candidates.length)
    return undefined

  const pool = candidates.length > 1 && lastPlayed
    ? candidates.filter(name => name !== lastPlayed)
    : candidates
  const list = pool.length ? pool : candidates
  return list[Math.floor(Math.random() * list.length)]
}

export interface IdleDelayOptions {
  /** 两次动作之间的最短间隔（秒）。 */
  minSeconds: number
  /** 两次动作之间的最长间隔（秒）。 */
  maxSeconds: number
  /** 上一个动作的实际时长；下一次触发从它播完后起算。 */
  actionDurationMs?: number
  /** 注入随机源，便于测试。 @default Math.random */
  random?: () => number
}

/**
 * 下一次待机动作距"现在"的毫秒数 = 当前动作剩余时长 + 动作间停顿。
 * 说话期间由调度器暂停倒计时，这里只负责时间计算。
 */
export function nextIdleDelayMs(options: IdleDelayOptions): number {
  const { minSeconds, maxSeconds, actionDurationMs = 0 } = options
  const random = options.random ?? Math.random
  const low = Math.max(1, minSeconds)
  const high = Math.max(low, maxSeconds)
  return Math.max(0, actionDurationMs) + (low + random() * (high - low)) * 1000
}
