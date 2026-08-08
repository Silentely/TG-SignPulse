/**
 * 跨页面共享的签到 active runs 状态。
 * Dashboard 与 Tasks 共用同一轮询结果，避免重复打 listActiveSignTaskRuns。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { listActiveSignTaskRuns, type ActiveRunSummary } from '../lib/api'
import { getAuthToken } from '../lib/api/core'
import { groupActiveRunsByTask, isRunInProgress } from '../lib/run-status'
import { startChainPoll, type ChainPollHandle } from '../lib/chain-poll'
import { devLog } from '../lib/devLog'

const POLL_MS = 4000

export const useActiveRunsStore = defineStore('activeRuns', () => {
  const runs = ref<ActiveRunSummary[]>([])
  const byTask = ref<Record<string, ActiveRunSummary[]>>({})
  const fetchedAt = ref(0)
  const loading = ref(false)
  let pollHandle: ChainPollHandle | null = null
  let consumers = 0

  const hasAnyActive = computed(() =>
    runs.value.some((r) => isRunInProgress(r)),
  )

  const applyRuns = (list: ActiveRunSummary[]) => {
    runs.value = list
    byTask.value = groupActiveRunsByTask(list)
    fetchedAt.value = Date.now()
  }

  const refresh = async (): Promise<boolean> => {
    const token = getAuthToken()
    if (!token) return false
    loading.value = true
    try {
      const res = await listActiveSignTaskRuns(token)
      applyRuns(res.runs || [])
      return true
    } catch (e) {
      devLog.error('Failed to refresh active runs', e)
      // 保留上一轮结果，同时让上层知道本次刷新没有成功。
      return false
    } finally {
      loading.value = false
    }
  }

  const ensurePolling = () => {
    if (hasAnyActive.value) {
      if (!pollHandle?.active) {
        // 轮询只关心刷新完成，不向轮询器暴露 Dashboard 使用的成功标记。
        pollHandle = startChainPoll(async () => {
          await refresh()
        }, {
          intervalMs: POLL_MS,
          runImmediately: false,
        })
      }
    } else {
      pollHandle?.stop()
      pollHandle = null
    }
  }

  /** 从任务列表 raw.active_run 种子化（避免首屏空窗） */
  const seedFromTaskActiveRuns = (flat: ActiveRunSummary[]) => {
    const inProgress = flat.filter((r) => isRunInProgress(r))
    if (inProgress.length) {
      applyRuns(inProgress)
      ensurePolling()
    }
  }

  const acquire = () => {
    consumers += 1
    if (consumers === 1) {
      void refresh().then(() => ensurePolling())
    } else {
      ensurePolling()
    }
  }

  const release = () => {
    consumers = Math.max(0, consumers - 1)
    if (consumers === 0) {
      pollHandle?.stop()
      pollHandle = null
    }
  }

  return {
    runs,
    byTask,
    fetchedAt,
    loading,
    hasAnyActive,
    refresh,
    seedFromTaskActiveRuns,
    applyRuns,
    acquire,
    release,
    ensurePolling,
  }
})
