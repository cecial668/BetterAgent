import { describe, expect, it } from 'vitest'

import { nextIdleDelayMs, pickMotionFromGroup } from './motion-group'

describe('pickMotionFromGroup', () => {
  it('从组里随机挑一个已注册的动作', () => {
    const picks = new Set<string>()
    for (let i = 0; i < 60; i++) {
      const picked = pickMotionFromGroup(['a', 'b'], ['a', 'b'])
      expect(picked).toBeDefined()
      picks.add(picked!)
    }
    expect(picks).toEqual(new Set(['a', 'b']))
  })

  it('过滤掉未注册/已删除的动作名', () => {
    expect(pickMotionFromGroup(['ghost'], ['a', 'b'])).toBeUndefined()
    expect(['a']).toContain(pickMotionFromGroup(['ghost', 'a'], ['a', 'b']))
  })

  it('组为空或未配置时返回 undefined', () => {
    expect(pickMotionFromGroup([], ['a'])).toBeUndefined()
    expect(pickMotionFromGroup(undefined, ['a'])).toBeUndefined()
  })

  it('多个候选时避免与上次重复', () => {
    for (let i = 0; i < 30; i++)
      expect(pickMotionFromGroup(['a', 'b'], ['a', 'b'], 'a')).toBe('b')
  })

  it('只有一个候选时允许重复（别无选择）', () => {
    expect(pickMotionFromGroup(['a'], ['a'], 'a')).toBe('a')
  })
})

describe('nextIdleDelayMs', () => {
  it('动作时长 + 区间内随机停顿', () => {
    const base = { minSeconds: 6, maxSeconds: 15, actionDurationMs: 3000 }
    expect(nextIdleDelayMs({ ...base, random: () => 0 })).toBe(9000)
    expect(nextIdleDelayMs({ ...base, random: () => 1 })).toBe(18000)
  })

  it('间隔下限钳制为 1 秒，避免配置成 0 时疯狂刷动作', () => {
    expect(nextIdleDelayMs({ minSeconds: -5, maxSeconds: 0, random: () => 0 })).toBe(1000)
  })

  it('动作时长缺失按 0 处理', () => {
    expect(nextIdleDelayMs({ minSeconds: 2, maxSeconds: 2, actionDurationMs: -100, random: () => 0 })).toBe(2000)
  })
})
