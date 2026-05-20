/**
 * prefs.ts — Persist user preferences in a cookie.
 * Single JSON cookie named "ti_prefs", 1-year expiry.
 */

import type { TzMode, ConflictFilter, ScrollAnchor, Theme } from '@/types'
import type { SortKey, SortDir } from './sort'

export interface Prefs {
  tz:             TzMode
  theme:          Theme
  scrollAnchor:   ScrollAnchor
  conflictFilter: ConflictFilter
  sortKey:        SortKey
  sortDir:        SortDir
  env:            'prod' | 'stage'
  configUnlocked: boolean
}

const DEFAULTS: Prefs = {
  tz:             'UTC',
  theme:          'dark',
  scrollAnchor:   'now',
  conflictFilter: 'all',
  sortKey:        'name',
  sortDir:        'asc',
  env:            'prod',
  configUnlocked: false,
}

const COOKIE_NAME = 'ti_prefs'
const COOKIE_DAYS = 365

function setCookie(value: string) {
  const expires = new Date()
  expires.setDate(expires.getDate() + COOKIE_DAYS)
  document.cookie = `${COOKIE_NAME}=${encodeURIComponent(value)}; expires=${expires.toUTCString()}; path=/; SameSite=Lax`
}

function getCookie(): string | null {
  const match = document.cookie.split(';').find(c => c.trim().startsWith(`${COOKIE_NAME}=`))
  return match ? decodeURIComponent(match.trim().slice(COOKIE_NAME.length + 1)) : null
}

export function loadPrefs(): Prefs {
  try {
    const raw = getCookie()
    return raw ? { ...DEFAULTS, ...JSON.parse(raw) } : { ...DEFAULTS }
  } catch {
    return { ...DEFAULTS }
  }
}

/** Save the full prefs object — caller owns the current state, no read needed. */
export function savePrefs(prefs: Prefs): void {
  try { setCookie(JSON.stringify(prefs)) } catch { /* non-fatal */ }
}
