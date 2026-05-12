import { useState } from 'react'
import type { MarketGroup } from '@/types'
import { sortMarketGroups } from '@/utils/sort'
import { useApp } from './useApp'

export function useIntervals() {
  const { env, raw, intervalsLoading: loading, loadIntervals: load, conflictFilter, sortKey, sortDir } = useApp()
  const [filterMG, setFilterMG] = useState('')
  const [filterIv, setFilterIv] = useState('')
  const [showIgnored, setShowIgnored] = useState(false)

  const groups = (() => {
    let list: MarketGroup[] = raw
    if (!showIgnored) list = list.filter(g => !g.ignored)

    if (filterMG.trim()) {
      const q = filterMG.toLowerCase()
      list = list.filter(g => g.market_group.toLowerCase().includes(q))
    }
    if (filterIv.trim()) {
      const q = filterIv.toLowerCase()
      list = list.filter(g =>
        g.trading_intervals.some(iv =>
          (iv.start_task ?? '').toLowerCase().includes(q) ||
          (iv.stop_task  ?? '').toLowerCase().includes(q) ||
          (iv.computer_name ?? '').toLowerCase().includes(q)
        ) ||
        g.messenger_coverages.some(mc => mc.computer_name.toLowerCase().includes(q))
      )
    }
    if (conflictFilter === 'conflicts') {
      list = list.filter(g =>
        g.trading_intervals.some(iv => iv.status === 'CONFLICT' || iv.status === 'PARTIAL')
      )
    } else if (conflictFilter === 'no-conflicts') {
      list = list.filter(g =>
        g.trading_intervals.length === 0 ||
        g.trading_intervals.every(iv => iv.status === 'OK')
      )
    }

    return sortMarketGroups(list, sortKey, sortDir)
  })()

  return {
    groups, loading, load,
    filterMG, setFilterMG,
    filterIv, setFilterIv,
    showIgnored, setShowIgnored,
    env,
  }
}
