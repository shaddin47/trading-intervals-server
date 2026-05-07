import React from 'react'
import type { TzMode } from '@/types'
import { formatTime, parseUtc } from '@/utils/time'
import type { TooltipState } from './useTooltip'

interface Props {
  tip: TooltipState
  tz: TzMode
}

export function Tooltip({ tip, tz }: Props) {
  const { data, x, y } = tip
  const pad = 14
  const W = window.innerWidth
  const H = window.innerHeight
  const style: React.CSSProperties = {
    left: x + pad + 320 > W ? x - 320 - pad : x + pad,
    top:  y + pad + 260 > H ? y - 260       : y + pad,
  }

  const fmt = (iso: string) => formatTime(parseUtc(iso), tz, true)

  return (
    <div className="tooltip" style={style}>
      <div className="tooltip-title">{data.marketGroup}</div>

      {data.type === 'interval' && data.interval && (() => {
        const iv = data.interval
        return (
          <>
            <div className="tooltip-row">
              <span className="k">Start</span>
              <span className="v">{fmt(iv.from_utc)}</span>
            </div>
            <div className="tooltip-row">
              <span className="k">Stop</span>
              <span className="v">{fmt(iv.to_utc)}</span>
            </div>
            <div className="tooltip-row">
              <span className="k">Status</span>
              <span className={`v ${iv.status.toLowerCase()}`}>{iv.status}</span>
            </div>
            {iv.start_xbit && (
              <div className="tooltip-row">
                <span className="k">Start xb</span>
                <span className="v">{iv.start_xbit}</span>
              </div>
            )}
            {iv.stop_xbit && (
              <div className="tooltip-row">
                <span className="k">Stop xb</span>
                <span className="v">{iv.stop_xbit}</span>
              </div>
            )}
          </>
        )
      })()}

      {data.type === 'uptime' && data.uptime && (() => {
        const u = data.uptime
        return (
          <>
            <div className="tooltip-row">
              <span className="k">Up from</span>
              <span className="v">{fmt(u.from_utc)}</span>
            </div>
            <div className="tooltip-row">
              <span className="k">Up to</span>
              <span className="v">{fmt(u.to_utc)}</span>
            </div>
            <hr className="tooltip-sep" />
            <div className="tooltip-row">
              <span className="k">Start</span>
              <span className="v">{u.start_task}</span>
            </div>
            <div className="tooltip-row">
              <span className="k">Stop</span>
              <span className="v">{u.stop_task}</span>
            </div>
            {data.computerName && (
              <div className="tooltip-row">
                <span className="k">Box</span>
                <span className="v">{data.computerName}</span>
              </div>
            )}
            {data.source && (
              <div className="tooltip-row">
                <span className="k">Source</span>
                <span className="v">{data.source}</span>
              </div>
            )}
          </>
        )
      })()}

      {data.comment && (
        <div className="tooltip-comment">💬 {data.comment}</div>
      )}
    </div>
  )
}
