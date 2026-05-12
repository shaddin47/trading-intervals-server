import {
  createContext, useCallback, useContext, useEffect, useRef, useState,
} from 'react'
import type { ReactNode } from 'react'
import type {
  ConflictFilter, Env, MarketGroup, ScrollAnchor,
  StatusInfo, Theme, TzMode,
} from '@/types'
import type { SortKey, SortDir } from '@/utils/sort'
import { fetchStatus, fetchIntervals } from '@/utils/api'
import { loadPrefs, savePrefs } from '@/utils/prefs'
import type { Prefs } from '@/utils/prefs'

interface AppCtx {
  env:               Env
  setEnv:            (e: Env) => void
  tz:                TzMode
  setTz:             (t: TzMode) => void
  theme:             Theme
  setTheme:          (t: Theme) => void
  scrollAnchor:      ScrollAnchor
  setScrollAnchor:   (a: ScrollAnchor) => void
  conflictFilter:    ConflictFilter
  setConflictFilter: (f: ConflictFilter) => void
  sortKey:           SortKey
  setSortKey:        (k: SortKey) => void
  sortDir:           SortDir
  setSortDir:        (d: SortDir) => void
  status:            StatusInfo[]
  refreshStatus:     () => void
  // Intervals data — lifted here so it persists across page navigation
  // and so ConfigPage can patch comments without a full reload.
  raw:               MarketGroup[]
  intervalsLoading:  boolean
  loadIntervals:     () => void
  patchGroupComment: (routeGroupId: number, name: string, comment: string | null) => void
  patchGroupIgnored:  (routeGroupId: number, name: string, ignored: boolean) => void
  patchGroupName:     (routeGroupId: number, oldName: string, newName: string) => void
}

const Ctx = createContext<AppCtx | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const initial = loadPrefs()

  const [env,            setEnvState]            = useState<Env>(initial.env)
  const [tz,             setTzState]             = useState<TzMode>(initial.tz)
  const [theme,          setThemeState]          = useState<Theme>(initial.theme)
  const [scrollAnchor,   setScrollAnchorState]   = useState<ScrollAnchor>(initial.scrollAnchor)
  const [conflictFilter, setConflictFilterState] = useState<ConflictFilter>(initial.conflictFilter)
  const [sortKey,        setSortKeyState]        = useState<SortKey>(initial.sortKey)
  const [sortDir,        setSortDirState]        = useState<SortDir>(initial.sortDir)
  const [status,         setStatus]              = useState<StatusInfo[]>([])
  const [raw,            setRaw]                 = useState<MarketGroup[]>([])
  const [intervalsLoading, setIntervalsLoading]  = useState(false)

  // Keep a ref to env so loadIntervals always uses the current value
  // without being recreated on every env change (which would re-trigger effects).
  const envRef = useRef(env)
  envRef.current = env

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  useEffect(() => {
    const prefs: Prefs = {
      env, tz, theme, scrollAnchor, conflictFilter, sortKey, sortDir,
    }
    savePrefs(prefs)
  }, [env, tz, theme, scrollAnchor, conflictFilter, sortKey, sortDir])

  const setEnv            = useCallback((v: Env)            => setEnvState(v),            [])
  const setTz             = useCallback((v: TzMode)         => setTzState(v),             [])
  const setTheme          = useCallback((v: Theme)          => setThemeState(v),          [])
  const setScrollAnchor   = useCallback((v: ScrollAnchor)   => setScrollAnchorState(v),   [])
  const setConflictFilter = useCallback((v: ConflictFilter) => setConflictFilterState(v), [])
  const setSortKey        = useCallback((v: SortKey)        => setSortKeyState(v),        [])
  const setSortDir        = useCallback((v: SortDir)        => setSortDirState(v),        [])

  const refreshStatus = useCallback(() => {
    fetchStatus().then(setStatus).catch(console.error)
  }, [])

  useEffect(() => {
    refreshStatus()
    const id = setInterval(refreshStatus, 60_000)
    return () => clearInterval(id)
  }, [refreshStatus])

  const loadIntervals = useCallback(() => {
    setIntervalsLoading(true)
    fetchIntervals(envRef.current, true)
      .then(setRaw)
      .catch(console.error)
      .finally(() => setIntervalsLoading(false))
  }, [])

  // Reload when env changes
  useEffect(() => { loadIntervals() }, [env, loadIntervals])

  const patchGroupComment = useCallback((
    routeGroupId: number,
    _name: string,
    comment: string | null,
  ) => {
    setRaw(prev => prev.map(g =>
      g.route_group_id === routeGroupId ? { ...g, comment } : g
    ))
  }, [])

  const patchGroupIgnored = useCallback((
    routeGroupId: number,
    _name: string,
    ignored: boolean,
  ) => {
    setRaw(prev => prev.map(g =>
      g.route_group_id === routeGroupId ? { ...g, ignored } : g
    ))
  }, [])

  const patchGroupName = useCallback((
    routeGroupId: number,
    _oldName: string,
    newName: string,
  ) => {
    setRaw(prev => prev.map(g =>
      g.route_group_id === routeGroupId
        ? { ...g, market_group: newName }
        : g
    ))
  }, [])

  return (
    <Ctx.Provider value={{
      env, setEnv,
      tz, setTz,
      theme, setTheme,
      scrollAnchor, setScrollAnchor,
      conflictFilter, setConflictFilter,
      sortKey, setSortKey,
      sortDir, setSortDir,
      status, refreshStatus,
      raw, intervalsLoading, loadIntervals, patchGroupComment, patchGroupIgnored, patchGroupName,
    }}>
      {children}
    </Ctx.Provider>
  )
}

export function useApp() {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}
