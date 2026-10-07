/**
 * 计算"距离上次打开前端页面"的秒数。
 * 首次访问（没有记录）、时钟回拨或非法时间戳时返回 undefined，
 * 由调用方退化为普通寒暄（不要把 0/负数当成"刚走"）。
 */
export function computeAwaySeconds(previousMs: number | null | undefined, nowMs: number): number | undefined {
  if (typeof previousMs !== 'number' || !Number.isFinite(previousMs) || previousMs <= 0)
    return undefined
  const seconds = Math.round((nowMs - previousMs) / 1000)
  return seconds > 0 ? seconds : undefined
}
