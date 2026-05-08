import { TopBar } from '@/components/TopBar'
import { GanttChart } from '@/components/GanttChart'
import { StatusBanner } from '@/components/StatusBanner'
import { useIntervals } from '@/hooks/useIntervals'
import { useApp } from '@/hooks/useApp'

export function GanttPage() {
  const { tz, scrollAnchor } = useApp()
  const {
    groups, loading, error, load,
    filterMG, setFilterMG,
    filterIv, setFilterIv,
    showIgnored, setShowIgnored,
  } = useIntervals()

  return (
    <>
      <StatusBanner onRefreshComplete={load} />
      <TopBar
        filterMG={filterMG}       setFilterMG={setFilterMG}
        filterIv={filterIv}       setFilterIv={setFilterIv}
        showIgnored={showIgnored} setShowIgnored={setShowIgnored}
      />
      <div className="main-area">
        {error
          ? <div className="state-msg" style={{ color: 'var(--conflict-hi)' }}>
              Error: {error}
            </div>
          : <GanttChart
              groups={groups}
              tz={tz}
              loading={loading}
              scrollAnchor={scrollAnchor}
            />
        }
      </div>
    </>
  )
}
