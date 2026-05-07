import type { TzMode } from '@/types'

export const DAY_MS  =     24 * 60 * 60 * 1000
export const HOUR_MS =          60 * 60 * 1000
export const WEEK_MS = 7 * DAY_MS

// Display window: this Sunday 00:00 UTC → Monday +2 weeks (15 days)
export const DISPLAY_DAYS = 15

// The viewport shows 7 days. DAY_PX is passed in as a prop/state value
// from GanttChart which measures the container. These helpers accept dayPx
// explicitly rather than reading global mutable state.
export const FALLBACK_DAY_PX = 160

export function computeDayPx(containerWidth: number): number {
  return containerWidth > 0 ? Math.floor(containerWidth / 7) : FALLBACK_DAY_PX
}

export function computeTotalPx(dayPx: number): number {
  return dayPx * DISPLAY_DAYS
}

// Keep these for GanttBar which needs them without prop-drilling.
// They read from a module-level value that GanttChart sets on every render.
let _dayPx = FALLBACK_DAY_PX
let _windowStartMs = 0  // cached per render cycle

export function setRenderDayPx(px: number) {
  _dayPx = px
  // Recompute window start once per render rather than per msToPixel call
  const now = new Date()
  const utcDay = now.getUTCDay()
  const startOfToday = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
  _windowStartMs = startOfToday - utcDay * DAY_MS
}
export function getDayPx(): number { return _dayPx }
export function getTotalPx(): number { return _dayPx * DISPLAY_DAYS }

/**
 * This week's Sunday 00:00:00 UTC — left edge of the display window.
 * Uses UTC day-of-week so the anchor is always Sunday regardless of timezone.
 */
export function getWindowStartMs(): number {
  const now = new Date()
  const utcDay = now.getUTCDay()  // 0=Sun … 6=Sat
  const startOfToday = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
  return startOfToday - utcDay * DAY_MS
}

/** Start of display day d (0=this Sunday … 14=Mon+2wks) in UTC ms. */
export function dayStartMs(d: number): number {
  return getWindowStartMs() + d * DAY_MS
}

/** Parse a UTC ISO string to ms since epoch. */
export function parseUtc(iso: string): number {
  return new Date(iso).getTime()
}

/**
 * Convert a UTC ms timestamp to a pixel offset within the 15-day timeline.
 * Left edge = this Sunday 00:00 UTC.
 */
export function msToPixel(ms: number): number {
  // Use cached values set by setRenderDayPx() — avoids repeated Date() calls per bar
  const winStart = _windowStartMs > 0 ? _windowStartMs : getWindowStartMs()
  const total = _dayPx * DISPLAY_DAYS
  return ((ms - winStart) / (DISPLAY_DAYS * DAY_MS)) * total
}

/** Format a UTC ms timestamp for display in the requested timezone. */
export function formatTime(ms: number, mode: TzMode, includeDay = false): string {
  const date = new Date(ms)
  let displayH: number, displayM: number, displayDay: number

  if (mode === 'UTC') {
    displayH = date.getUTCHours(); displayM = date.getUTCMinutes(); displayDay = date.getUTCDay()
  } else if (mode === 'Chicago') {
    const off = chicagoOffsetHours(date)
    const totalMin = date.getUTCHours() * 60 + date.getUTCMinutes() + off * 60
    const normMin  = ((totalMin % 1440) + 1440) % 1440
    displayH = Math.floor(normMin / 60); displayM = normMin % 60
    displayDay = ((date.getUTCDay() + Math.floor(totalMin / 1440)) % 7 + 7) % 7
  } else {
    displayH = date.getHours(); displayM = date.getMinutes(); displayDay = date.getDay()
  }

  const t = `${String(displayH).padStart(2,'0')}:${String(displayM).padStart(2,'0')}`
  return includeDay ? `${DAY_LABELS[displayDay]} ${t}` : t
}

export function chicagoOffsetHours(date: Date): number {
  try {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'America/Chicago', hour: 'numeric', hour12: false,
    }).formatToParts(date)
    const chiH = parseInt(parts.find(p => p.type === 'hour')?.value ?? '0')
    let diff = chiH - date.getUTCHours()
    if (diff > 12) diff -= 24
    if (diff < -12) diff += 24
    return diff
  } catch { return -6 }
}

/**
 * Header label for display day d (0=this Sunday ... 14).
 * Pass `columnMs` (= dayStartMs(d) - tzOffsetMs) so the label reflects the
 * local date at that pixel position rather than the UTC date.
 */
export function dayLabel(d: number, tz: TzMode, columnMs?: number): string {
  const ms   = columnMs ?? dayStartMs(d)
  const date = new Date(ms)

  // Compare against tz-aware "today" so Today/Tomorrow labels are correct
  const todayStartUtc = localTodayStartMs(tz)
  const isToday    = ms === todayStartUtc
  const isTomorrow = ms === todayStartUtc + DAY_MS

  let dow: number, dom: number, mon: number
  if (tz === 'UTC') {
    dow = date.getUTCDay(); dom = date.getUTCDate(); mon = date.getUTCMonth()
  } else if (tz === 'Chicago') {
    const adj = new Date(ms + chicagoOffsetHours(date) * HOUR_MS)
    dow = adj.getUTCDay(); dom = adj.getUTCDate(); mon = adj.getUTCMonth()
  } else {
    dow = date.getDay(); dom = date.getDate(); mon = date.getMonth()
  }

  const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
  const base = `${DAY_LABELS[dow]} ${dom} ${MONTHS[mon]}`
  if (isToday)    return `Today — ${base}`
  if (isTomorrow) return `Tomorrow — ${base}`
  return base
}

export const DAY_LABELS = ['Sun','Mon','Tue','Wed','Thu','Fri','Sat']

/**
 * Returns the UTC offset in milliseconds for the given TzMode at the given
 * moment. Used to shift day/hour grid lines from UTC midnight to local midnight.
 *
 * e.g. Chicago CDT (UTC-5) → -5 * 3_600_000
 */
export function tzOffsetMs(ms: number, mode: TzMode): number {
  if (mode === 'UTC') return 0
  if (mode === 'Chicago') return chicagoOffsetHours(new Date(ms)) * HOUR_MS
  // Local: derive from the JS Date object
  return -new Date(ms).getTimezoneOffset() * 60_000
}

/**
 * The start of "today" in the given timezone expressed as a UTC ms value,
 * i.e. the UTC instant when local midnight began today.
 *
 * For UTC this is just Date.UTC(y, m, d).
 * For other timezones we find the UTC ms whose local representation is
 * 00:00 on today's local date.
 */
export function localTodayStartMs(mode: TzMode): number {
  const now = new Date()
  if (mode === 'UTC') {
    return Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate())
  }
  if (mode === 'Chicago') {
    // Shift now by Chicago offset to find local "today", then back-convert to UTC midnight
    const off = chicagoOffsetHours(now) * HOUR_MS
    const localNow = new Date(now.getTime() + off)
    const localMidnight = Date.UTC(localNow.getUTCFullYear(), localNow.getUTCMonth(), localNow.getUTCDate())
    return localMidnight - off
  }
  // Local
  return new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
}
