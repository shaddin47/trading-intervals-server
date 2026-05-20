// Types matching backend Pydantic response schemas exactly

export type Env = 'prod' | 'stage'
export type TzMode = 'UTC' | 'Chicago' | 'Local'
export type ConflictFilter = 'all' | 'conflicts' | 'no-conflicts'
export type ScrollAnchor = 'now' | 'sunday'
export type Theme = 'dark' | 'light' | 'midnight' | 'warm'
export type ConflictStatus = 'OK' | 'PARTIAL' | 'CONFLICT'
export type TaskSource = 'windows' | 'linux'

export interface TradingInterval {
  from_utc: string
  to_utc: string
  status: ConflictStatus
  start_xbit: string | null
  stop_xbit: string | null
  all_xbit: string | null
  start_task: string | null
  stop_task: string | null
  computer_name: string | null
  source: TaskSource | null
}

export interface UptimeInterval {
  from_utc: string
  to_utc: string
  start_task: string
  stop_task: string
}

export interface MessengerCoverage {
  computer_name: string
  uptime_intervals: UptimeInterval[]
}

export interface MarketGroup {
  market_group: string
  route_group_id: number
  ignored: boolean
  comment: string | null
  trading_intervals: TradingInterval[]
  messenger_coverages: MessengerCoverage[]
}

export interface MarketGroupConfig {
  env: Env
  route_group_id: number
  name: string
  task_name: string | null
  exchange_keys_csv: string | null
  exchange_keys_from_viable_routes: boolean
  ignore: boolean
  comment: string | null
}

export interface StatusInfo {
  env: Env
  last_updated_utc: string | null
  is_stale: boolean
  task_archive_path: string
  windows_task_count: number
  linux_task_count: number
  market_group_count: number
}


// Day labels for the Gantt header
export const DAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
