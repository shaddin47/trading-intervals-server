import React from 'react'
import type { TradingInterval, UptimeInterval, MarketGroup } from '@/types'
import { parseUtc, msToPixel, getTotalPx } from '@/utils/time'
import type { useTooltip } from './useTooltip'

type TipController = ReturnType<typeof useTooltip>

function barStyle(fromMs: number, toMs: number): React.CSSProperties | null {
  const totalPx = getTotalPx()
  const left  = Math.max(0, msToPixel(fromMs))
  const right = Math.min(totalPx, msToPixel(toMs))
  const width = right - left
  if (width <= 0) return null
  return { left, width: Math.max(width, 2) }
}

interface IntervalBarProps {
  iv:  TradingInterval
  mg:  MarketGroup
  tip: TipController
}

export function IntervalBar({ iv, mg, tip }: IntervalBarProps) {
  const style = barStyle(parseUtc(iv.from_utc), parseUtc(iv.to_utc))
  if (!style) return null

  return (
    <div
      className={`gantt-bar status-${iv.status}`}
      style={style}
      onMouseEnter={e => tip.show({
        type: 'interval',
        marketGroup: mg.market_group,
        comment: mg.comment,
        interval: iv,
      }, e)}
      onMouseMove={tip.move}
      onMouseLeave={tip.hide}
    />
  )
}

interface UptimeBarProps {
  u:            UptimeInterval
  computerName: string
  mg:           MarketGroup
  tip:          TipController
  source?:      string
}

export function UptimeBar({ u, computerName, mg, tip, source }: UptimeBarProps) {
  const style = barStyle(parseUtc(u.from_utc), parseUtc(u.to_utc))
  if (!style) return null

  return (
    <div
      className="gantt-bar type-uptime"
      style={style}
      onMouseEnter={e => tip.show({
        type: 'uptime',
        marketGroup: mg.market_group,
        comment: mg.comment,
        uptime: u,
        computerName,
        source,
      }, e)}
      onMouseMove={tip.move}
      onMouseLeave={tip.hide}
    />
  )
}
