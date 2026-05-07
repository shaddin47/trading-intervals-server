import type { MarketGroup } from '@/types'
import { parseUtc, WEEK_MS } from './time'

export type SortKey =
  | 'name'
  | 'next_interval_start'
  | 'next_interval_stop'
  | 'next_interval_execution'
  | 'next_uptime_start'
  | 'next_uptime_stop'
  | 'next_uptime_execution'

export type SortDir = 'asc' | 'desc'

export const SORT_OPTIONS: { value: SortKey; label: string; group: string }[] = [
  { value: 'name',                   label: 'Name',             group: 'General' },
  { value: 'next_interval_start',    label: 'Next start',       group: 'Intervals' },
  { value: 'next_interval_stop',     label: 'Next stop',        group: 'Intervals' },
  { value: 'next_interval_execution',label: 'Next start/stop',  group: 'Intervals' },
  { value: 'next_uptime_start',      label: 'Next up',          group: 'Uptime' },
  { value: 'next_uptime_stop',       label: 'Next down',        group: 'Uptime' },
  { value: 'next_uptime_execution',  label: 'Next up/down',     group: 'Uptime' },
]

function nextAfterNow(times: number[]): number | null {
  if (times.length === 0) return null
  const now = Date.now()
  const sorted = [...times].sort((a, b) => a - b)
  return sorted.find(t => t > now) ?? sorted[0] + WEEK_MS
}

const GETTERS: Record<SortKey, (mg: MarketGroup) => string | number> = {
  name: mg => mg.market_group.toLowerCase(),

  // Interval-based sorts
  next_interval_start: mg =>
    nextAfterNow(mg.trading_intervals.map(iv => parseUtc(iv.from_utc))) ?? Infinity,
  next_interval_stop: mg =>
    nextAfterNow(mg.trading_intervals.map(iv => parseUtc(iv.to_utc))) ?? Infinity,
  next_interval_execution: mg =>
    nextAfterNow(mg.trading_intervals.flatMap(iv =>
      [parseUtc(iv.from_utc), parseUtc(iv.to_utc)]
    )) ?? Infinity,

  // Uptime-based sorts (from messenger_coverages)
  next_uptime_start: mg =>
    nextAfterNow(
      mg.messenger_coverages.flatMap(mc =>
        mc.uptime_intervals.map(u => parseUtc(u.from_utc))
      )
    ) ?? Infinity,
  next_uptime_stop: mg =>
    nextAfterNow(
      mg.messenger_coverages.flatMap(mc =>
        mc.uptime_intervals.map(u => parseUtc(u.to_utc))
      )
    ) ?? Infinity,
  next_uptime_execution: mg =>
    nextAfterNow(
      mg.messenger_coverages.flatMap(mc =>
        mc.uptime_intervals.flatMap(u => [parseUtc(u.from_utc), parseUtc(u.to_utc)])
      )
    ) ?? Infinity,
}

export function sortMarketGroups(
  groups: MarketGroup[],
  key: SortKey,
  dir: SortDir,
): MarketGroup[] {
  return [...groups].sort((a, b) => {
    const va = GETTERS[key](a)
    const vb = GETTERS[key](b)
    if (va === vb) return 0
    const cmp = va < vb ? -1 : 1
    return dir === 'asc' ? cmp : -cmp
  })
}
