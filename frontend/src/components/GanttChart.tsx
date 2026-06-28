import React, { useRef, useEffect, useCallback, useState, useMemo } from 'react'
import type { MarketGroup, TzMode, ScrollAnchor } from '@/types'
import {
  DAY_MS, HOUR_MS, DISPLAY_DAYS,
  msToPixel, formatTime, dayStartMs, dayLabel,
  computeDayPx, computeTotalPx, setRenderDayPx, FALLBACK_DAY_PX,
  tzOffsetMs, localTodayStartMs,
} from '@/utils/time'
import { IntervalBar, UptimeBar } from './GanttBar'
import { Tooltip } from './Tooltip'
import { useTooltip } from './useTooltip'

const HOURS_TO_SHOW = [0, 3, 6, 9, 12, 15, 18, 21]
const LABEL_W  = 240    // px — sticky label column
const ROW_H    = 32     // px
const HEADER_H = 48     // px


interface Props {
  groups:       MarketGroup[]
  tz:           TzMode
  loading:      boolean
  scrollAnchor: ScrollAnchor
}

export function GanttChart({ groups, tz, loading, scrollAnchor }: Props) {
  const wrapperRef   = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [dayPx, setDayPx] = useState(FALLBACK_DAY_PX)
  const tip = useTooltip()

  // ~1 inch gap between the sticky label column and the now-line.
  const NOW_INSET = 96

  // Refs so callbacks always read current values without stale closures.
  const scrollAnchorRef = useRef(scrollAnchor)
  scrollAnchorRef.current = scrollAnchor
  const dayPxRef = useRef(dayPx)
  dayPxRef.current = dayPx

  const doNowScroll = useCallback(() => {
    const el = containerRef.current
    if (!el) return
    // Use the ref so we always have the latest measured dayPx.
    setRenderDayPx(dayPxRef.current)
    const px = msToPixel(Date.now())
    // nowPx is positioned inside a div that includes LABEL_W before the timeline.
    // The sticky label doesn't scroll, so we must subtract it from the target.
    el.scrollLeft = Math.max(0, px - LABEL_W - NOW_INSET)
  }, [])

  const scrollToAnchor = useCallback((anchor: ScrollAnchor) => {
    const el = containerRef.current
    if (!el) return
    if (anchor === 'sunday') {
      el.scrollLeft = 0
    } else {
      doNowScroll()
    }
  }, [doNowScroll])

  // Measure wrapper width. After the final measurement, scroll to anchor
  // so the scroll target uses the real dayPx, not the fallback.
  const measure = useCallback(() => {
    const el = wrapperRef.current
    if (!el) return
    const available = el.getBoundingClientRect().width - LABEL_W
    if (available > 0) {
      const px = computeDayPx(available)
      setDayPx(px)
      setRenderDayPx(px)
      dayPxRef.current = px
    }
  }, [])

  useEffect(() => {
    let rafId = requestAnimationFrame(() => {
      measure()
      rafId = requestAnimationFrame(() => {
        measure()
        scrollToAnchor(scrollAnchorRef.current)
      })
    })
    const ro = new ResizeObserver(measure)
    if (wrapperRef.current) ro.observe(wrapperRef.current)
    window.addEventListener('resize', measure)
    return () => { cancelAnimationFrame(rafId); ro.disconnect(); window.removeEventListener('resize', measure) }
  }, [measure, scrollToAnchor])

  // Re-measure when data arrives — on first load groups is empty so wrapperRef
  // may not be mounted yet; this fires once groups populate.
  useEffect(() => {
    if (groups.length > 0) {
      requestAnimationFrame(() => {
        measure()
        requestAnimationFrame(() => {
          measure()
          scrollToAnchor(scrollAnchorRef.current)
        })
      })
    }
  }, [groups.length, measure, scrollToAnchor])

  // Re-scroll when anchor or data changes (not tz — tz never moves the chart).
  useEffect(() => {
    scrollToAnchor(scrollAnchor)
  }, [scrollAnchor, groups, scrollToAnchor])

  // Changing tz does NOT scroll the chart — the viewport is fixed.
  // Only the overlay elements (day headers, day lines, today band) re-render.

  // Tick every 60 s — advances the now-line and re-pins the viewport
  // to keep the now-line at NOW_INSET px when anchor is 'now'.
  const [_tick, setTick] = useState(0)
  useEffect(() => {
    const id = setInterval(() => {
      setTick(n => n + 1)
      if (scrollAnchorRef.current === 'now') doNowScroll()
    }, 60_000)
    return () => clearInterval(id)
  }, [])

  // Timezone offset in ms — used to shift day/hour grid lines from UTC midnight
  // to the local midnight for the selected timezone.
  const tzOff = useMemo(() => {
    // Sample at the middle of the display window for a representative offset
    const midMs = dayStartMs(Math.floor(DISPLAY_DAYS / 2))
    return tzOffsetMs(midMs, tz)
  }, [tz])

  const gridLines = useMemo(() => Array.from({ length: DISPLAY_DAYS }, (_, d) => [
    { ms: dayStartMs(d) - tzOff, isDay: true },
    ...HOURS_TO_SHOW.slice(1).map(h => ({ ms: dayStartMs(d) - tzOff + h * HOUR_MS, isDay: false })),
  ]).flat(), [tz, tzOff])

  if (loading) {
    return <div className="state-msg"><div className="spinner" />Loading intervals…</div>
  }
  if (groups.length === 0) {
    return <div className="state-msg">No market groups match the current filters.</div>
  }

  // Keep module-level cache fresh — must happen before any msToPixel call below.
  setRenderDayPx(dayPx)
  const totalPx = computeTotalPx(dayPx)

  // Computed after setRenderDayPx so _dayPx is always the current measured value.
  const nowPx        = msToPixel(Date.now())
  const todayStartPx = msToPixel(localTodayStartMs(tz))

  // Weekend bands — tz-aware Sat/Sun columns rendered as shaded overlays.
  // A "day" here is defined by the local midnight in the selected tz.
  // Weekend bands — the display window is always Sunday-anchored UTC, so
  // d % 7 === 6 is always Saturday and d % 7 === 0 (and d > 0) is always Sunday.
  // We shade the pixel span from local Saturday midnight to local Sunday midnight
  // (i.e. the full local Saturday), then from local Sunday midnight to Monday midnight
  // (i.e. the full local Sunday). The tzOff shift moves these in lock-step with the
  // day headers so they always cover exactly Sat 00:00 → Mon 00:00 local time.
  const weekendBands: { leftPx: number; widthPx: number }[] = []
  for (let d = 0; d < DISPLAY_DAYS; d++) {
    const utcDow = d % 7   // 0=Sun,1=Mon,...,6=Sat (window starts on UTC Sunday)
    if (utcDow !== 6 && utcDow !== 0) continue  // only Sat and Sun
    if (utcDow === 0 && d === 0) continue        // skip the very first Sunday (before visible Sat)
    const columnMs = dayStartMs(d) - tzOff       // local midnight of this day
    const leftPx   = msToPixel(columnMs)
    weekendBands.push({ leftPx, widthPx: dayPx })
  }

  // Flatten rows
  type Row =
    | { kind: 'intervals'; mg: MarketGroup }
    | { kind: 'uptime';    mg: MarketGroup; mc_idx: number; computer_name: string }

  const rows: Row[] = []
  for (const mg of groups) {
    rows.push({ kind: 'intervals', mg })
    if (!mg.ignored) {
      mg.messenger_coverages.forEach((mc, mc_idx) =>
        rows.push({ kind: 'uptime', mg, mc_idx, computer_name: mc.computer_name })
      )
    }
  }

  return (
    <div className="gantt-wrapper" ref={wrapperRef}>
      {/* Single scroll container — both label and timeline scroll together */}
      <div
        ref={containerRef}
        style={{ flex: 1, overflow: 'auto', position: 'relative' }}
      >
        <div style={{ width: LABEL_W + totalPx, position: 'relative' }}>

          {/* ── Sticky header ── */}
          <div style={{
            display: 'flex',
            position: 'sticky',
            top: 0,
            zIndex: 10,
            height: HEADER_H,
          }}>
            {/* Corner cell — sticky on both axes */}
            <div style={{
              width: LABEL_W,
              flexShrink: 0,
              position: 'sticky',
              left: 0,
              zIndex: 12,
              background: 'var(--bg-2)',
              borderRight: '1px solid var(--border)',
              borderBottom: '1px solid var(--border)',
              display: 'flex',
              alignItems: 'flex-end',
              padding: '0 12px 8px',
            }}>
              <span style={{
                fontFamily: 'var(--mono)', fontSize: 10,
                color: 'var(--text-xdim)', textTransform: 'uppercase', letterSpacing: '0.08em',
              }}>Market Group</span>
            </div>

            {/* Day headers */}
            <div style={{
              width: totalPx,
              position: 'relative',
              background: 'var(--bg-2)',
              borderBottom: '1px solid var(--border)',
              flexShrink: 0,
            }}>
              {Array.from({ length: DISPLAY_DAYS }, (_, d) => {
                // Position each header column at its local-midnight pixel offset,
                // matching the day-line separator in the data rows.
                const columnMs  = dayStartMs(d) - tzOff
                const leftPx    = msToPixel(columnMs)
                const rightPx   = msToPixel(columnMs + DAY_MS)
                const widthPx   = rightPx - leftPx
                return (
                  <div key={d} className="day-header" style={{ left: leftPx, width: widthPx }}>
                    <span className="day-name" style={{ fontSize: 10, whiteSpace: 'nowrap', overflow: 'hidden' }}>
                      {dayLabel(d, tz, columnMs)}
                    </span>
                    <div className="hour-ticks">
                      {HOURS_TO_SHOW.map(h => (
                        <span key={h} className="hour-tick" style={{ left: `${(h / 24) * 100}%` }}>
                          {h === 0 ? '' : formatTime(columnMs + h * HOUR_MS, tz)}
                        </span>
                      ))}
                    </div>
                  </div>
                )
              })}
              {/* Now line in header */}
              {nowPx >= 0 && nowPx <= totalPx && (
                <div style={{
                  position: 'absolute', top: 0, bottom: 0, left: nowPx,
                  width: 1, background: 'var(--accent)', opacity: 0.8, pointerEvents: 'none',
                }} />
              )}
            </div>
          </div>

          {/* ── Data rows ── */}
          {rows.map((row, i) => {
            const isIgnored    = row.kind === 'intervals' && row.mg.ignored
            // Count which group index this row belongs to for alternating shade
            const groupIdx     = groups.indexOf(row.mg)
            const isEvenGroup  = groupIdx % 2 === 0
            return (
              <div key={i} style={{ display: 'flex', height: ROW_H }}>

                {/* Label — sticky left */}
                <div
                  className={`gantt-group-label-cell ${isIgnored ? 'is-ignored' : ''}`}
                  style={{
                    width: LABEL_W, flexShrink: 0,
                    position: 'sticky', left: 0, zIndex: 30,
                    height: ROW_H, borderBottom: 'none',
                    borderRight: '1px solid var(--border)',
                    background: isIgnored ? 'var(--ignored)' : isEvenGroup ? 'var(--bg-2)' : 'var(--bg-label-alt)',
                  }}
                >
                  {row.kind === 'intervals' ? (
                    <>
                      <span className="mg-name" title={row.mg.market_group}>{row.mg.market_group}</span>
                      <span className="row-type-badge">intervals</span>
                    </>
                  ) : (
                    <>
                      <span className="mg-name" style={{ color: 'var(--text-dim)', fontSize: 11 }}>
                        {row.computer_name}
                      </span>
                      <span className="row-type-badge">uptime</span>
                    </>
                  )}
                </div>

                {/* Timeline cell — day banding via CSS custom properties + gradient */}
                <div
                  className={`gantt-timeline-cell ${isIgnored ? 'is-ignored' : ''} ${isEvenGroup ? 'group-even' : 'group-odd'}`}
                  style={{
                    width: totalPx, flexShrink: 0,
                    position: 'relative', height: ROW_H,
                    borderBottom: 'none', overflow: 'visible',
                    '--today-offset': `${todayStartPx}px`,
                    '--day-px': `${dayPx}px`,
                  } as React.CSSProperties}
                >
                  {/* Weekend shading — tz-aware Sat/Sun columns */}
                  {weekendBands.map(({ leftPx, widthPx }, wi) => (
                    <div key={wi} style={{
                      position: 'absolute', top: 0, bottom: 0,
                      left: leftPx, width: widthPx,
                      background: 'var(--weekend-band)', pointerEvents: 'none',
                    }} />
                  ))}
                  {gridLines.map(({ ms, isDay }) => (
                    <div key={ms} className={isDay ? 'day-line' : 'hour-line'} style={{ left: msToPixel(ms) }} />
                  ))}
                  {nowPx >= 0 && nowPx <= totalPx && (
                    <div className="now-line" style={{ left: nowPx }} />
                  )}
                  {row.kind === 'intervals' && !isIgnored &&
                    row.mg.trading_intervals.map((iv, j) => (
                      <IntervalBar key={j} iv={iv} mg={row.mg} tip={tip} />
                    ))
                  }
                  {row.kind === 'uptime' && (() => {
                    const mc = row.mg.messenger_coverages[row.mc_idx]
                    const source = row.mg.trading_intervals
                      .find(iv => iv.computer_name === row.computer_name)?.source ?? undefined
                    return mc?.uptime_intervals.map((u, j) => (
                      <UptimeBar key={j} u={u} computerName={row.computer_name} mg={row.mg} tip={tip} source={source} />
                    ))
                  })()}
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Legend */}
      <div className="legend">
        {[
          { cls: 'status-OK',       label: 'OK' },
          { cls: 'status-PARTIAL',  label: 'Partial coverage' },
          { cls: 'status-CONFLICT', label: 'Conflict' },
          { cls: 'type-uptime',     label: 'Messenger uptime' },
        ].map(({ cls, label }) => (
          <div key={cls} className="legend-item">
            <div className={`legend-swatch gantt-bar ${cls}`} style={{ position: 'static', height: 8, top: 'auto' }} />
            <span>{label}</span>
          </div>
        ))}
      </div>

      {tip.tip && <Tooltip tip={tip.tip} tz={tz} />}
    </div>
  )
}
