/**
 * 签到运行状态 / phase 映射（与后端 run status 契约对齐）。
 */

export type RunState =
  | 'idle'
  | 'running'
  | 'finished'
  | 'cancelled'
  | 'stale'
  | 'timeout'
  | string

export type RunPhase =
  | 'starting'
  | 'checking_account'
  | 'waiting_lock'
  | 'cooldown'
  | 'running'
  | 'finalizing'
  | string

export type ActiveRunSummary = {
  run_id?: string
  state?: RunState
  phase?: RunPhase | null
  phase_detail?: string
  account_name?: string
  task_name?: string
  started_at?: string | null
  wait_seconds?: number | null
}

export type SignTaskRunStatusLike = ActiveRunSummary & {
  success?: boolean | null
  error?: string
  output?: string
  finished_at?: string | null
  failure_category?: string | null
  timeout_seconds?: number | null
  retry_count_effective?: number | null
}

export function isRunInProgress(status?: { state?: string | null } | null): boolean {
  return String(status?.state || '') === 'running'
}

/** i18n 翻译函数签名 */
type Translate = (key: string, params?: Record<string, unknown>) => string

export function phaseLabel(phase: string | null | undefined, t: Translate): string {
  if (!phase) return ''
  const key = `runStatus.phase.${phase}`
  const label = t(key)
  return label === key ? phase : label
}

export function stateLabel(state: string | null | undefined, t: Translate): string {
  if (!state) return ''
  const key = `runStatus.state.${state}`
  const label = t(key)
  return label === key ? state : label
}

export function formatPhaseDetail(
  status?: SignTaskRunStatusLike | null,
  t?: Translate,
): string {
  if (!status) return ''
  const detail = String(status.phase_detail || '').trim()
  if (detail) return detail
  if (status.phase && t) return phaseLabel(status.phase, t)
  return String(status.phase || '')
}

export function failureCategoryLabel(
  cat: string | null | undefined,
  t: Translate,
): string {
  if (!cat || cat === 'none') return ''
  const key = `dashboard.failCat.${cat}`
  const label = t(key)
  return label === key ? cat : label
}

export type BadgeTone = 'neutral' | 'amber' | 'sky' | 'emerald' | 'rose'

export function badgeTone(status?: SignTaskRunStatusLike | null): BadgeTone {
  if (!status) return 'neutral'
  const state = String(status.state || '')
  if (state === 'timeout' || (state === 'finished' && status.success === false)) {
    return 'rose'
  }
  if (state === 'finished' && status.success === true) return 'emerald'
  if (state === 'cancelled' || state === 'stale') return 'neutral'
  if (state === 'running') {
    const phase = String(status.phase || '')
    if (phase === 'cooldown' || phase === 'waiting_lock' || phase === 'checking_account') {
      return 'amber'
    }
    if (phase === 'running' || phase === 'finalizing' || phase === 'starting') {
      return 'sky'
    }
    return 'sky'
  }
  return 'neutral'
}

export function badgeToneClass(tone: BadgeTone): string {
  switch (tone) {
    case 'amber':
      return 'border-amber-200 text-amber-800 bg-amber-50 dark:border-amber-800 dark:text-amber-300 dark:bg-amber-950/40'
    case 'sky':
      return 'border-sky-200 text-sky-800 bg-sky-50 dark:border-sky-800 dark:text-sky-300 dark:bg-sky-950/40'
    case 'emerald':
      return 'border-emerald-200 text-emerald-800 bg-emerald-50 dark:border-emerald-800 dark:text-emerald-300 dark:bg-emerald-950/40'
    case 'rose':
      return 'border-rose-200 text-rose-800 bg-rose-50 dark:border-rose-800 dark:text-rose-300 dark:bg-rose-950/40'
    default:
      return 'ui-badge-neutral'
  }
}

/** 按 failure_category 聚合失败日志 */
export function aggregateFailureCategories(
  logs: Array<{ success?: boolean; failure_category?: string | null }>,
): Array<{ category: string; count: number }> {
  const map = new Map<string, number>()
  for (const log of logs) {
    if (log.success) continue
    const cat = String(log.failure_category || 'unknown').trim() || 'unknown'
    if (cat === 'none') continue
    map.set(cat, (map.get(cat) || 0) + 1)
  }
  return Array.from(map.entries())
    .map(([category, count]) => ({ category, count }))
    .sort((a, b) => b.count - a.count)
}
