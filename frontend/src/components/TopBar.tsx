import type { Env, TzMode, ConflictFilter, Theme } from '@/types'
import { SORT_OPTIONS } from '@/utils/sort'
import type { ScrollAnchor } from '@/types'
import { useApp } from '@/hooks/useApp'

interface Props {
  filterMG:       string
  setFilterMG:    (v: string) => void
  filterIv:       string
  setFilterIv:    (v: string) => void
  showIgnored:    boolean
  setShowIgnored: (v: boolean) => void
}

const CONFLICT_OPTIONS: { value: ConflictFilter; label: string }[] = [
  { value: 'all',          label: 'All' },
  { value: 'conflicts',    label: 'Conflicts' },
  { value: 'no-conflicts', label: 'OK only' },
]

const THEME_OPTIONS: { value: Theme; label: string }[] = [
  { value: 'dark',     label: '🌑 Dark' },
  { value: 'midnight', label: '🌌 Midnight' },
  { value: 'light',    label: '☀ Light' },
  { value: 'warm',     label: '🌅 Warm' },
]

// Group sort options by their group label for <optgroup>
const SORT_GROUPS = Array.from(
  SORT_OPTIONS.reduce((acc, o) => {
    if (!acc.has(o.group)) acc.set(o.group, [])
    acc.get(o.group)!.push(o)
    return acc
  }, new Map<string, typeof SORT_OPTIONS>())
)

export function TopBar({ filterMG, setFilterMG, filterIv, setFilterIv, showIgnored, setShowIgnored }: Props) {
  const {
    env, setEnv, tz, setTz, theme, setTheme,
    scrollAnchor, setScrollAnchor,
    conflictFilter, setConflictFilter,
    sortKey, setSortKey, sortDir, setSortDir,
  } = useApp()

  function handleSortKeyChange(key: string) {
    setSortKey(key as any)
  }

  return (
    <div className="topbar">
      <span className="logo">TI_MONITOR</span>
      <div className="divider" />

      {/* Environment */}
      <div className="ctrl-group">
        <span className="ctrl-label">Env</span>
        <div className="seg">
          {(['prod', 'stage'] as Env[]).map(e => (
            <button key={e} className={env === e ? 'active' : ''} onClick={() => setEnv(e)}>{e}</button>
          ))}
        </div>
      </div>
      <div className="divider" />

      {/* Timezone */}
      <div className="ctrl-group">
        <span className="ctrl-label">TZ</span>
        <div className="seg">
          {(['UTC', 'Chicago', 'Local'] as TzMode[]).map(t => (
            <button key={t} className={tz === t ? 'active' : ''} onClick={() => setTz(t)}>{t}</button>
          ))}
        </div>
      </div>
      <div className="divider" />

      {/* Scroll anchor */}
      <div className="ctrl-group">
        <span className="ctrl-label">View</span>
        <div className="seg">
          {([['sunday', '◀ Sun'], ['now', '▶ Now']] as [ScrollAnchor, string][]).map(([a, label]) => (
            <button key={a} className={scrollAnchor === a ? 'active' : ''} onClick={() => setScrollAnchor(a)}>
              {label}
            </button>
          ))}
        </div>
      </div>
      <div className="divider" />

      {/* Conflict filter */}
      <div className="ctrl-group">
        <span className="ctrl-label">Show</span>
        <div className="seg">
          {CONFLICT_OPTIONS.map(o => (
            <button key={o.value} className={conflictFilter === o.value ? 'active' : ''} onClick={() => setConflictFilter(o.value)}>
              {o.label}
            </button>
          ))}
        </div>
      </div>
      <div className="divider" />

      {/* Filters */}
      <div className="ctrl-group">
        <span className="ctrl-label">Filter</span>
        <input className="filter-input" placeholder="Market group…" value={filterMG} onChange={e => setFilterMG(e.target.value)} />
        <input className="filter-input" style={{ width: 120 }} placeholder="Task / box…" value={filterIv} onChange={e => setFilterIv(e.target.value)} />
      </div>
      <div className="divider" />

      {/* Sort — grouped optgroup select */}
      <div className="ctrl-group">
        <span className="ctrl-label">Sort</span>
        <div className="sort-pill">
          <select value={sortKey} onChange={e => handleSortKeyChange(e.target.value)}>
            {SORT_GROUPS.map(([group, opts]) => (
              <optgroup key={group} label={group}>
                {opts.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </optgroup>
            ))}
          </select>
          <button className="sort-dir-btn" onClick={() => setSortDir(sortDir === 'asc' ? 'desc' : 'asc')}>
            {sortDir === 'asc' ? '↑' : '↓'}
          </button>
        </div>
      </div>
      <div className="divider" />

      {/* Show ignored */}
      <div className="ctrl-group">
        <label className="toggle" title="Show ignored groups">
          <input type="checkbox" checked={showIgnored} onChange={e => setShowIgnored(e.target.checked)} />
          <span className="toggle-slider" />
        </label>
        <span className="ctrl-label">Ignored</span>
      </div>
      <div className="divider" />

      {/* Theme — dropdown */}
      <div className="ctrl-group">
        <span className="ctrl-label">Theme</span>
        <div className="sort-pill">
          <select
            value={theme}
            onChange={e => setTheme(e.target.value as Theme)}
          >
            {THEME_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
      </div>
    </div>
  )
}