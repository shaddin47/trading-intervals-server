import React, {
  createContext, useContext, useState, useEffect, useCallback,
  type ReactNode,
} from 'react'
import type { Env, TzMode, Theme, ConflictFilter, ScrollAnchor } from '@/types'
import type { SortKey, SortDir } from '@/utils/sort'
import type { StatusInfo } from '@/types'
import { fetchStatus } from '@/utils/api'
import { loadPrefs, savePrefs, type Prefs } from '@/utils/prefs'

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
}

const Ctx = createContext<AppCtx | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  // Load once from cookie — not reactive, intentional
  const initial = loadPrefs()

  const [env,            setEnvState]            = useState<Env>(initial.env)
  const [tz,             setTzState]             = useState<TzMode>(initial.tz)
  const [theme,          setThemeState]          = useState<Theme>(initial.theme)
  const [scrollAnchor,   setScrollAnchorState]   = useState<ScrollAnchor>(initial.scrollAnchor)
  const [conflictFilter, setConflictFilterState] = useState<ConflictFilter>(initial.conflictFilter)
  const [sortKey,        setSortKeyState]        = useState<SortKey>(initial.sortKey)
  const [sortDir,        setSortDirState]        = useState<SortDir>(initial.sortDir)
  const [status,         setStatus]              = useState<StatusInfo[]>([])

  // Apply theme to <html> element
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  // Save the full prefs object whenever any preference changes.
  // Using a single useEffect avoids the N separate cookie writes that N
  // individual setters would cause, and removes the need for patchPrefs.
  useEffect(() => {
    const prefs: Prefs = {
      env, tz, theme, scrollAnchor, conflictFilter, sortKey, sortDir,
    }
    savePrefs(prefs)
  }, [env, tz, theme, scrollAnchor, conflictFilter, sortKey, sortDir])

  // Wrap setters in useCallback so consumers don't re-render needlessly
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
