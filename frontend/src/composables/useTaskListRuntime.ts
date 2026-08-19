/**
 * 签到列表运行时：活跃 run 轮询、命中角标、头像、账号状态与取消。
 */
import { ref, watch, onUnmounted, type Ref, type ComputedRef } from 'vue'
import { storeToRefs } from 'pinia'
import {
  cancelSignTaskRun,
  listKeywordHitGroups,
  fetchChatAvatar,
  listAccounts,
} from '../lib/api'
import { withToken, getAuthToken } from '../lib/api/core'
import type { ActiveRunSummary } from '../lib/api'
import type { TaskUiItem } from '../lib/types'
import { notifyApiError } from '../lib/notify'
import { useI18n } from './useI18n'
import { useToast } from './useToast'
import { useActiveRunsStore } from '../stores/activeRuns'
import { devLog } from '../lib/devLog'
import { resolveTaskAccountNames } from '../lib/task-list-map'
import { AVATAR_FETCH_CONCURRENCY, mapPool } from '../lib/async-pool'
import { startChainPoll, type ChainPollHandle } from '../lib/chain-poll'
import {
  formatActiveRunLabel,
  formatPhaseDetail,
  isRunInProgress,
  phaseLabel,
  pickPrimaryActiveRun,
  remainingWaitSeconds,
} from '../lib/run-status'

// 头像本地缓存有效期（毫秒）：聊天头像变更不频繁，7 天内复用 dataURL
const AVATAR_CACHE_TTL_MS = 7 * 24 * 3600 * 1000

/** 构造头像缓存值：{v: dataURL, ts: 写入时间戳}；压缩体积不放多余字段 */
export function buildAvatarCache(dataUrl: string): string {
  return JSON.stringify({ v: dataUrl, ts: Date.now() })
}

/**
 * 解析头像缓存值。返回可用的 dataURL；过期或损坏返回 null。
 * 兼容旧版纯 dataURL 字符串（无 ts 字段，视为有效，下次刷新自然更新）。
 */
export function parseAvatarCache(raw: string | null): string | null {
  if (!raw || raw === '__no_avatar__') return null
  if (raw.startsWith('data:')) return raw
  try {
    const parsed = JSON.parse(raw) as { v?: unknown; ts?: unknown }
    if (typeof parsed.v !== 'string' || !parsed.v.startsWith('data:')) return null
    if (typeof parsed.ts === 'number' && Date.now() - parsed.ts > AVATAR_CACHE_TTL_MS) {
      return null
    }
    return parsed.v
  } catch {
    return null
  }
}

export function useTaskListRuntime(options: {
  tasks: Ref<TaskUiItem[]>
  listenTaskCount: ComputedRef<number>
  accountFilter: ComputedRef<string>
  getTaskAccountName: (task: TaskUiItem | { account_name?: string; account_names?: string[] }) => string
}) {
  const { t } = useI18n()
  const toast = useToast()
  const activeRunsStore = useActiveRunsStore()
  const { byTask: activeRunsByTask, fetchedAt: activeRunsFetchedAt, hasAnyActive: hasAnyActiveRun } =
    storeToRefs(activeRunsStore)

  const nowTick = ref(Date.now())
  let countdownTimer: ReturnType<typeof setInterval> | null = null
  let hitCountHandle: ChainPollHandle | null = null
  const cancelBusyKey = ref('')
  const accountStatusMap = ref<Record<string, string>>({})
  const accountNeedsRelogin = ref<Record<string, boolean>>({})
  // 会话级 blob URL 注册表：列表替换/组件卸载时统一 revoke，防止累积泄漏
  const blobUrls = new Set<string>()

  const trackBlobUrl = (url: string) => {
    if (url.startsWith('blob:')) blobUrls.add(url)
  }

  const releaseBlobUrl = (url: string) => {
    if (!url.startsWith('blob:')) return
    blobUrls.delete(url)
    try {
      URL.revokeObjectURL(url)
    } catch { /* ignore */ }
  }

  // 列表替换（筛选/刷新）后，回收已不在列表中的 blob URL
  watch(options.tasks, (items) => {
    if (!blobUrls.size) return
    const live = new Set<string>()
    for (const t of items) {
      const u = t.chatAvatarUrl
      if (u && u.startsWith('blob:')) live.add(u)
    }
    for (const url of blobUrls) {
      if (!live.has(url)) releaseBlobUrl(url)
    }
  })

  const syncActiveRunsFromTasks = (items: TaskUiItem[]) => {
    const flat: ActiveRunSummary[] = []
    for (const task of items) {
      const ar = task.raw.active_run
      if (ar && isRunInProgress(ar)) {
        flat.push({ ...ar, task_name: ar.task_name || task.name })
      }
    }
    activeRunsStore.seedFromTaskActiveRuns(flat)
  }

  const refreshActiveRuns = async () => {
    await activeRunsStore.refresh()
    activeRunsStore.ensurePolling()
  }

  const ensureActivePolling = () => {
    activeRunsStore.ensurePolling()
    if (hasAnyActiveRun.value) {
      if (!countdownTimer) {
        countdownTimer = setInterval(() => {
          nowTick.value = Date.now()
        }, 1000)
      }
    } else if (countdownTimer) {
      clearInterval(countdownTimer)
      countdownTimer = null
    }
  }

  watch(() => hasAnyActiveRun.value, () => ensureActivePolling())
  activeRunsStore.acquire()

  const loadListenHitCounts = async () => {
    return withToken(async (token) => {
      const listenTasks = options.tasks.value.filter((t) => t.isListenMode)
      if (!listenTasks.length) return
      try {
        const res = await listKeywordHitGroups(token, {
          account_name: options.accountFilter.value || undefined,
          group_by: 'task',
          limit_per_group: 1,
        })
        const countByTask = new Map<string, number>()
        for (const g of res.groups || []) {
          countByTask.set(String(g.key), Number(g.count || 0))
        }
        for (const task of options.tasks.value) {
          if (!task.isListenMode) continue
          task.hitCount = countByTask.get(task.name) || 0
        }
      } catch (e: unknown) {
        devLog.error('Failed to load hit counts', e)
      }
    })
  }

  const ensureHitCountPolling = () => {
    if (hitCountHandle?.active) return
    hitCountHandle = startChainPoll(
      async () => {
        // 后台标签页不请求命中角标；回到前台由 visibilitychange 恢复轮询
        if (typeof document !== 'undefined' && document.hidden) return
        if (options.listenTaskCount.value > 0) await loadListenHitCounts()
      },
      { intervalMs: 15000, runImmediately: false },
    )
  }

  const clearHitCountPolling = () => {
    hitCountHandle?.stop()
    hitCountHandle = null
  }

  // 与 Dashboard 策略一致：页面隐藏时暂停命中角标轮询，回到前台立即刷新并恢复
  const handleVisibilityChange = () => {
    if (typeof document === 'undefined') return
    if (document.hidden) {
      clearHitCountPolling()
    } else if (options.listenTaskCount.value > 0) {
      void loadListenHitCounts().finally(() => ensureHitCountPolling())
    }
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', handleVisibilityChange)
  }

  const taskActiveRuns = (task: TaskUiItem): ActiveRunSummary[] => {
    return activeRunsByTask.value[task.name] || (task.raw.active_run && isRunInProgress(task.raw.active_run)
      ? [task.raw.active_run]
      : [])
  }

  const taskActiveRun = (task: TaskUiItem): ActiveRunSummary | null => {
    return pickPrimaryActiveRun(taskActiveRuns(task))
  }

  const activeRunBadgeText = (task: TaskUiItem): string => {
    const ar = taskActiveRun(task)
    if (!ar || !isRunInProgress(ar)) return ''
    void nowTick.value
    const rem = remainingWaitSeconds(ar.wait_seconds, activeRunsFetchedAt.value, nowTick.value)
    return formatActiveRunLabel(ar, t, { remainingSec: rem })
  }

  const activeRunTooltip = (task: TaskUiItem): string => {
    const runs = taskActiveRuns(task)
    if (!runs.length) return ''
    return runs
      .map((r) => {
        const acc = r.account_name || '-'
        const ph = phaseLabel(r.phase, t) || formatPhaseDetail(r, t)
        return `${acc}: ${ph}`
      })
      .join('\n')
  }

  const isAccountInvalid = (accountName: string) => {
    if (accountNeedsRelogin.value[accountName]) return true
    const st = accountStatusMap.value[accountName] || ''
    return st === 'invalid' || st === 'error' || /expired|offline|disconnected/i.test(st)
  }

  const taskHasInvalidAccount = (task: TaskUiItem): boolean => {
    // 具体账号名收敛：去重、跳过通配符，与列表账号名解析共享同一实现
    return resolveTaskAccountNames(task).some((n) => isAccountInvalid(n))
  }

  const handleCancelRun = async (task: TaskUiItem) => {
    const ar = taskActiveRun(task)
    if (!ar?.account_name) {
      toast.error(t('tasks.cancelNeedAccount'))
      return
    }
    const key = `${task.name}:${ar.account_name}`
    if (cancelBusyKey.value === key) return
    cancelBusyKey.value = key
    const token = getAuthToken()
    try {
      const res = await cancelSignTaskRun(token, task.name, ar.account_name, ar.run_id)
      if (res.ok && res.cancelled) {
        toast.success(t('tasks.cancelSuccess'))
        await refreshActiveRuns()
      } else {
        toast.error(res.error || t('tasks.cancelFailed'))
      }
    } catch (e: unknown) {
      notifyApiError(e, 'tasks.cancelFailed')
    } finally {
      cancelBusyKey.value = ''
    }
  }

  const loadChatAvatar = async (task: TaskUiItem, accountName: string, chatId: number) => {
    const token = getAuthToken()
    const cacheKey = `chat_avatar_${chatId}`
    const noAvatarKey = `chat_avatar_${chatId}_404`

    // 头像缓存 TTL：头像变更不频繁，7 天内复用本地 dataURL 减少重复请求；
    // 值格式为 {v, ts}，兼容旧版纯 dataURL（无 ts 视为有效，下次刷新自然更新）
    const cached = localStorage.getItem(cacheKey)
    const cachedValue = cached ? parseAvatarCache(cached) : null
    if (cachedValue) {
      task.chatAvatarUrl = cachedValue
      return
    }

    const noAvatarTime = localStorage.getItem(noAvatarKey)
    if (noAvatarTime) {
      const age = Date.now() - parseInt(noAvatarTime, 10)
      if (age < 3600000) return
    }

    try {
      const blob = await fetchChatAvatar(token, accountName, chatId)
      const url = URL.createObjectURL(blob)
      const prev = task.chatAvatarUrl
      task.chatAvatarUrl = url
      trackBlobUrl(url)
      if (prev && prev.startsWith('blob:')) releaseBlobUrl(prev)
      localStorage.removeItem(noAvatarKey)
      try {
        const reader = new FileReader()
        reader.onload = () => {
          if (reader.result) {
            try {
              localStorage.setItem(cacheKey, buildAvatarCache(String(reader.result)))
            } catch {
              try { sessionStorage.setItem(cacheKey, buildAvatarCache(String(reader.result))) } catch { /* ignore */ }
            }
          }
        }
        reader.readAsDataURL(blob)
      } catch { /* ignore */ }
    } catch (e: unknown) {
      if (e && typeof e === 'object' && 'status' in e && (e as { status: number }).status === 404) {
        try { localStorage.setItem(noAvatarKey, String(Date.now())) } catch { /* ignore */ }
      }
    }
  }

  /** 列表加载后：同步 run、轮询、命中、头像 */
  const afterTasksLoaded = async () => {
    syncActiveRunsFromTasks(options.tasks.value)
    ensureActivePolling()
    void loadListenHitCounts()
    if (options.listenTaskCount.value > 0) ensureHitCountPolling()
    else clearHitCountPolling()

    const avatarJobs = options.tasks.value.flatMap((task) => {
      const firstChat = task.raw.chats?.[0]
      if (!firstChat) return []
      const avatarAccount = firstChat.source_account || options.getTaskAccountName(task.raw)
      if (!avatarAccount) return []
      return [{ task, avatarAccount, chatId: firstChat.chat_id as number }]
    })
    void mapPool(avatarJobs, AVATAR_FETCH_CONCURRENCY, async (job) => {
      await loadChatAvatar(job.task, job.avatarAccount, job.chatId)
    })
  }

  const loadAccountStatusMap = async () => {
    return withToken(async (token) => {
      try {
        const res = await listAccounts(token)
        const map: Record<string, string> = {}
        const relogin: Record<string, boolean> = {}
        for (const a of res.accounts || []) {
          map[a.name] = String(a.status || '')
          relogin[a.name] = !!a.needs_relogin
        }
        accountStatusMap.value = map
        accountNeedsRelogin.value = relogin
      } catch (e: unknown) {
        devLog.error('Failed to load account status map', e)
      }
    })
  }

  const stopAll = () => {
    if (typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', handleVisibilityChange)
    }
    if (countdownTimer) {
      clearInterval(countdownTimer)
      countdownTimer = null
    }
    clearHitCountPolling()
    activeRunsStore.release()
    // 卸载时回收全部 blob URL，避免页面切换后累积
    for (const url of blobUrls) releaseBlobUrl(url)
    blobUrls.clear()
  }

  onUnmounted(() => {
    stopAll()
  })

  return {
    cancelBusyKey,
    loadListenHitCounts,
    taskActiveRuns,
    taskActiveRun,
    activeRunBadgeText,
    activeRunTooltip,
    taskHasInvalidAccount,
    handleCancelRun,
    afterTasksLoaded,
    loadAccountStatusMap,
  }
}
