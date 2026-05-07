import { useState, useEffect, useCallback } from 'react'
import type { MarketGroup, ConflictFilter } from '@/types'
import type { SortKey, SortDir } from '@/utils/sort'
import { fetchIntervals } from '@/utils/api'
import { sortMarketGroups } from '@/utils/sort'
import { useApp } from './useApp'

export function useIntervals() {
  const { env, conflictFilter, sortKey, sortDir } = useApp()
  const [raw, setRaw]         = useState<MarketGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)
  const [filterMG, setFilterMG] = useState('')
  const [filterIv, setFilterIv] = useState('')
  const [showIgnored, setShowIgnored] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    fetchIntervals(env, true)
      .then(setRaw)
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false))
  }, [env])

  useEffect(() => { load() }, [load])

  const groups = (() => {
    let list = raw
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
    groups, loading, error, load,
    filterMG, setFilterMG,
    filterIv, setFilterIv,
    showIgnored, setShowIgnored,
  }
}
