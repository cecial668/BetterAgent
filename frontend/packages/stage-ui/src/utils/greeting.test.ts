import { describe, expect, it } from 'vitest'

import { computeAwaySeconds } from './greeting'

describe('computeAwaySeconds', () => {
  it('返回两次打开之间的秒数', () => {
    expect(computeAwaySeconds(1_000_000, 1_000_000 + 90_000)).toBe(90)
  })

  it('首次访问没有记录时返回 undefined', () => {
    expect(computeAwaySeconds(undefined, 1_000_000)).toBeUndefined()
    expect(computeAwaySeconds(null, 1_000_000)).toBeUndefined()
    expect(computeAwaySeconds(0, 1_000_000)).toBeUndefined()
  })

  it('时钟回拨或时间相同（结果非正）时返回 undefined', () => {
    expect(computeAwaySeconds(2_000_000, 1_000_000)).toBeUndefined()
    expect(computeAwaySeconds(1_000_000, 1_000_000)).toBeUndefined()
  })

  it('非法时间戳返回 undefined', () => {
    expect(computeAwaySeconds(Number.NaN, 1_000_000)).toBeUndefined()
    expect(computeAwaySeconds(Number.POSITIVE_INFINITY, 1_000_000)).toBeUndefined()
  })
})
