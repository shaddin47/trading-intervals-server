import { useState } from 'react'
import { useApp } from '@/hooks/useApp'
import { triggerRefreshAndWait } from '@/utils/api'

interface Props {
  onRefreshComplete?: () => void  // called when refresh finishes so Gantt reloads
}

export function StatusBanner({ onRefreshComplete }: Props) {
  const { env, status, refreshStatus } = useApp()
  const [refreshState, setRefreshState] = useState<'idle' | 'running' | 'error'>('idle')
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  const info = status.find(s => s.env === env)

  async function handleRefresh() {
    setRefreshState('running')
    setErrorMsg(null)

    try {
      await triggerRefreshAndWait(
        env,
        () => {
          // still running — keep spinner going
        },
        (error) => {
          if (error) {
            setRefreshState('error')
            setErrorMsg(error)
          } else {
            setRefreshState('idle')
            // Update status banner timestamp
            refreshStatus()
            // Tell the Gantt page to re-fetch intervals
            onRefreshComplete?.()
          }
        },
      )
    } catch (e) {
      setRefreshState('error')
      setErrorMsg(String(e))
    }
  }

  const dotClass = !info ? 'missing'
    : info.is_stale ? 'stale'
    : ''

  const isRunning = refreshState === 'running'

  return (
    <div className="status-banner">
      <div className={`dot ${dotClass}`} />

      {isRunning ? (
        <span style={{ color: 'var(--accent)' }}>↻ Refreshing…</span>
      ) : (
        <span>
          {info
            ? `Updated ${info.last_updated_utc ?? 'never'}`
            : 'No cache data'}
        </span>
      )}

      {info && !isRunning && (
        <>
          <span className="sep">·</span>
          <span>{info.market_group_count} groups</span>
          <span className="sep">·</span>
          <span>{info.windows_task_count}W / {info.linux_task_count}L tasks</span>
        </>
      )}

      {info?.is_stale && !isRunning && (
        <>
          <span className="sep">·</span>
          <span style={{ color: 'var(--partial-hi)' }}>⚠ stale</span>
        </>
      )}

      {refreshState === 'error' && errorMsg && (
        <>
          <span className="sep">·</span>
          <span style={{ color: 'var(--conflict-hi)' }} title={errorMsg}>
            ✗ Refresh failed
          </span>
        </>
      )}

      <span style={{ flex: 1 }} />

      <button
        className="icon-btn"
        title={isRunning ? 'Refresh in progress…' : 'Force refresh'}
        onClick={handleRefresh}
        disabled={isRunning}
        style={{
          width: 'auto',
          padding: '0 10px',
          fontFamily: 'var(--mono)',
          fontSize: 10,
          opacity: isRunning ? 0.5 : 1,
        }}
      >
        {isRunning ? '↻ …' : '↻ refresh'}
      </button>
    </div>
  )
}
