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

/**
 * 冷却倒计时：根据 wait_seconds + 轮询时间估算剩余秒。
 * remainingAtFetch 为拉取时服务端 wait_seconds；fetchedAtMs 为本地 Date.now()。
 */
export function remainingWaitSeconds(
  remainingAtFetch: number | null | undefined,
  fetchedAtMs: number,
  nowMs: number = Date.now(),
): number | null {
  if (remainingAtFetch == null || !Number.isFinite(remainingAtFetch)) return null
  if (remainingAtFetch <= 0) return 0
  const elapsed = Math.max(0, (nowMs - fetchedAtMs) / 1000)
  return Math.max(0, Math.ceil(remainingAtFetch - elapsed))
}

/** 展示用 phase 文案：有倒计时则拼到 phase 标签后，优先 i18n phase */
export function formatActiveRunLabel(
  status: SignTaskRunStatusLike | null | undefined,
  t: Translate,
  opts?: { remainingSec?: number | null },
): string {
  if (!status || !isRunInProgress(status)) return ''
  const phase = phaseLabel(status.phase, t) || t('runStatus.inProgress')
  const rem = opts?.remainingSec
  if (rem != null && rem > 0 && String(status.phase || '') === 'cooldown') {
    return `${phase} ${rem}s`
  }
  // 细节含账号名时作副信息，主标签仍用 phase
  return phase
}

/** 按 task_name 分组活跃 run，同任务多账号保留全部 */
export function groupActiveRunsByTask(
  runs: ActiveRunSummary[],
): Record<string, ActiveRunSummary[]> {
  const map: Record<string, ActiveRunSummary[]> = {}
  for (const run of runs) {
    const name = String(run.task_name || '')
    if (!name || !isRunInProgress(run)) continue
    if (!map[name]) map[name] = []
    map[name].push(run)
  }
  for (const key of Object.keys(map)) {
    map[key].sort((a, b) => String(b.started_at || '').localeCompare(String(a.started_at || '')))
  }
  return map
}

export function pickPrimaryActiveRun(
  runs: ActiveRunSummary[] | undefined | null,
): ActiveRunSummary | null {
  if (!runs || !runs.length) return null
  return runs[0] || null
}
