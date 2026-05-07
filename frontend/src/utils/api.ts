import type {
  Env, MarketGroup, MarketGroupConfig, StatusInfo
} from '@/types'

// In production, Apache proxies /time-tracker-server/ → uvicorn @ :3000.
// In dev, Vite proxies /api/ → uvicorn @ :8000 (see vite.config.ts).
const BASE = import.meta.env.PROD
  ? '/trading-intervals-server/api'
  : '/api'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path)
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`)
  return res.json()
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: body ? { 'Content-Type': 'application/json' } : {},
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`POST ${path} → ${res.status}`)
  return res.json()
}

async function put<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`PUT ${path} → ${res.status}`)
  return res.json()
}

async function del(path: string): Promise<void> {
  const res = await fetch(BASE + path, { method: 'DELETE' })
  if (!res.ok) throw new Error(`DELETE ${path} → ${res.status}`)
}

// ── Intervals ────────────────────────────────────────────────────────────────

export function fetchIntervals(
  env: Env,
  includeIgnored = false,
): Promise<MarketGroup[]> {
  return get(`/intervals?env=${env}&include_ignored=${includeIgnored}`)
}

// ── Config ───────────────────────────────────────────────────────────────────

export function fetchConfigs(env: Env): Promise<MarketGroupConfig[]> {
  return get(`/config/market-groups?env=${env}`)
}

export function upsertConfig(cfg: MarketGroupConfig): Promise<MarketGroupConfig> {
  return post('/config/market-groups', cfg)
}

export function patchConfig(
  env: Env,
  route_group_id: number,
  name: string,
  patch: Partial<MarketGroupConfig>,
): Promise<MarketGroupConfig> {
  const q = new URLSearchParams({ env, name }).toString()
  return put(`/config/market-groups/${route_group_id}?${q}`, patch)
}

export function deleteConfig(
  env: Env,
  route_group_id: number,
  name: string,
): Promise<void> {
  return del(`/config/market-groups/${route_group_id}/${encodeURIComponent(name)}?env=${env}`)
}

// ── Status / admin ───────────────────────────────────────────────────────────

export function fetchStatus(): Promise<StatusInfo[]> {
  return get('/status')
}

export interface RefreshStatus {
  env: Env
  running: boolean
  error: string | null
  last_updated_utc: string | null
}

export function triggerRefresh(env: Env): Promise<{ started: boolean; message: string }> {
  return post(`/admin/refresh?env=${env}`)
}

export function fetchRefreshStatus(env: Env): Promise<RefreshStatus> {
  return get(`/admin/refresh-status?env=${env}`)
}

/**
 * Trigger a refresh and poll until it completes.
 * onProgress: called on each poll while running=true
 * onDone:     called once with error string (or null on success)
 */
export async function triggerRefreshAndWait(
  env: Env,
  onProgress: () => void,
  onDone: (error: string | null) => void,
  pollIntervalMs = 3000,
): Promise<void> {
  const response = await triggerRefresh(env)

  if (!response.started) {
    const status = await fetchRefreshStatus(env)
    if (!status.running) {
      onDone(status.error)
      return
    }
  }

  const poll = async () => {
    try {
      const status = await fetchRefreshStatus(env)
      if (status.running) {
        onProgress()
        setTimeout(poll, pollIntervalMs)
      } else {
        onDone(status.error)
      }
    } catch {
      onProgress()
      setTimeout(poll, pollIntervalMs)
    }
  }

  setTimeout(poll, 100)
}
