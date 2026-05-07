import { useState, useCallback, useRef } from 'react'
import type { TradingInterval, UptimeInterval } from '@/types'

export interface TooltipData {
  type: 'interval' | 'uptime'
  marketGroup: string
  comment: string | null
  interval?: TradingInterval
  uptime?: UptimeInterval
  computerName?: string
  source?: string
}

export interface TooltipState {
  data: TooltipData
  x: number
  y: number
}

export function useTooltip() {
  const [tip, setTip] = useState<TooltipState | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const show = useCallback((data: TooltipData, e: React.MouseEvent) => {
    if (timerRef.current) clearTimeout(timerRef.current)
    setTip({ data, x: e.clientX, y: e.clientY })
  }, [])

  const move = useCallback((e: React.MouseEvent) => {
    setTip(prev => prev ? { ...prev, x: e.clientX, y: e.clientY } : null)
  }, [])

  const hide = useCallback(() => {
    timerRef.current = setTimeout(() => setTip(null), 80)
  }, [])

  return { tip, show, move, hide }
}
