/**
 * 账号列表：批量/单账号状态检测 Job、轮询与重检。
 */
import { ref, computed, onUnmounted, type Ref, type ComputedRef } from 'vue'
import {
  checkAccountsStatus,
  startAccountStatusCheckJob,
  getAccountStatusCheckJob,
  listAccountStatusCheckJobs,
  cancelAccountStatusCheckJob,
} from '../lib/api'
import { withToken, getAuthToken } from '../lib/api/core'
import type { AccountStatusJob, AccountStatusItem } from '../lib/api'
import type { AccountUiItem } from '../lib/types'
import { notifyApiError } from '../lib/notify'
import { useI18n } from './useI18n'
import { useToast } from './useToast'
import { startChainPoll, type ChainPollHandle } from '../lib/chain-poll'

export function useAccountBatchCheck(options: {
  accounts: Ref<AccountUiItem[]>
  filteredAccounts: ComputedRef<AccountUiItem[]>
  searchQuery: Ref<string>
  loadAccounts: () => Promise<void>
}) {
  const { t } = useI18n()
  const toast = useToast()

  const checkingAccount = ref('')
  const batchChecking = ref(false)
  const batchJob = ref<AccountStatusJob | null>(null)
  const batchResultMap = ref<Record<string, AccountStatusItem>>({})
  const lastBatchFailedNames = ref<string[]>([])
  let batchPollHandle: ChainPollHandle | null = null
  let lastLiveRefreshDone = 0

  const batchProgressPct = computed(() => {
    const total = Number(batchJob.value?.progress?.total || 0)
    const done = Number(batchJob.value?.progress?.done || 0)
    if (total <= 0) return 0
    return Math.min(100, Math.round((done / total) * 100))
  })

  const lastFailedAccountNames = computed(() => lastBatchFailedNames.value)

  const clearBatchPoll = () => {
    batchPollHandle?.stop()
    batchPollHandle = null
  }

  onUnmounted(() => {
    clearBatchPoll()
  })

  const applyLiveResults = (results: AccountStatusItem[] | undefined) => {
    if (!results?.length) return
    const map = { ...batchResultMap.value }
    for (const item of results) {
      if (!item?.account_name) continue
      map[item.account_name] = item
    }
    batchResultMap.value = map

    for (const acc of options.accounts.value) {
      const r = map[acc.name]
      if (!r) continue
      if (r.ok) {
        acc.status = 'active'
        acc.message = ''
        if (acc.raw) {
          acc.raw.status = 'connected'
          acc.raw.needs_relogin = false
          acc.raw.status_message = r.message || ''
        }
      } else if (r.needs_relogin || r.status === 'invalid') {
        acc.status = 'error'
        acc.message = t('accounts.loginExpired')
        if (acc.raw) {
          acc.raw.status = 'invalid'
          acc.raw.needs_relogin = true
          acc.raw.status_message = r.message || ''
        }
      } else {
        acc.status = 'error'
        acc.message = r.message || t('accounts.statusUnknown')
        if (acc.raw) {
          acc.raw.status = r.status || 'error'
          acc.raw.status_message = r.message || ''
        }
      }
    }
  }

  const applyBatchJobResult = async (job: AccountStatusJob) => {
    applyLiveResults(job.results)
    lastBatchFailedNames.value = (job.results || [])
      .filter((item) => item && !item.ok && item.account_name)
      .map((item) => item.account_name)
    await options.loadAccounts()
    const summary = job.summary || {}
    const ok = Number(summary.ok ?? job.progress?.ok ?? 0)
    const failed = Number(summary.fail ?? job.progress?.fail ?? 0)
    if (job.status === 'canceled') {
      toast.error(t('accounts.batchCheckCanceled'), {
        description: `${t('accounts.checkOkCount')}: ${ok} · ${t('accounts.checkFailedCount')}: ${failed}`,
      })
      return
    }
    if (job.status === 'failed') {
      toast.error(t('accounts.checkFailed'), {
        description: job.error || t('accounts.batchCheckFailed'),
      })
      return
    }
    if (failed === 0) {
      toast.success(t('accounts.batchCheckDone'), {
        description: `${t('accounts.checkOkCount')}: ${ok}`,
      })
    } else {
      const failedPreview = (job.results || [])
        .filter((item) => !item.ok)
        .slice(0, 5)
        .map((item) => `${item.account_name}: ${item.message || item.code || t('accounts.loginExpired')}`)
        .join('\n')
      toast.error(t('accounts.batchCheckDone'), {
        description: `${t('accounts.checkOkCount')}: ${ok} · ${t('accounts.checkFailedCount')}: ${failed}\n${failedPreview}`,
        duration: 8000,
      })
    }
  }

  const pollBatchJob = async (jobId: string) => {
    return withToken(async (token) => {
      try {
        const job = await getAccountStatusCheckJob(token, jobId)
        batchJob.value = job
        if (job.status === 'running' || job.status === 'canceling') {
          const done = Number(job.progress?.done || 0)
          if (done > lastLiveRefreshDone) {
            lastLiveRefreshDone = done
            applyLiveResults(job.results)
          }
          return
        }
        clearBatchPoll()
        batchChecking.value = false
        await applyBatchJobResult(job)
        batchJob.value = null
        batchResultMap.value = {}
        lastLiveRefreshDone = 0
      } catch (e: unknown) {
        clearBatchPoll()
        batchChecking.value = false
        batchJob.value = null
        batchResultMap.value = {}
        lastLiveRefreshDone = 0
        notifyApiError(e, 'accounts.checkFailed')
      }
    })
  }

  const startPollingJob = (jobId: string) => {
    clearBatchPoll()
    batchPollHandle = startChainPoll(
      () => pollBatchJob(jobId),
      { intervalMs: 1200 },
    )
  }

  const resumeActiveBatchJob = async () => {
    if (batchChecking.value) return
    return withToken(async (token) => {
      try {
        const res = await listAccountStatusCheckJobs(token, 5)
        const active = (res.jobs || []).find(
          (j) => j.status === 'running' || j.status === 'canceling',
        )
        if (!active?.job_id) return
        batchChecking.value = true
        batchJob.value = active
        lastLiveRefreshDone = Number(active.progress?.done || 0)
        applyLiveResults(active.results)
        startPollingJob(active.job_id)
        await pollBatchJob(active.job_id)
      } catch {
        // 恢复失败不打扰用户
      }
    })
  }

  const handleCheck = async (name: string) => {
    const token = getAuthToken()
    checkingAccount.value = name
    try {
      const res = await checkAccountsStatus(token, { account_names: [name] })
      await options.loadAccounts()
      const result = res.results?.[0]
      if (result) {
        if (result.ok) {
          toast.success(`${name}: ${t('accounts.checkOk')}`)
        } else {
          toast.error(`${name}: ${result.message || t('accounts.loginExpired')}`)
        }
      }
    } catch (e: unknown) {
      notifyApiError(e, 'accounts.checkFailed')
    } finally {
      checkingAccount.value = ''
    }
  }

  /**
   * 批量状态检测统一实现：2+ 账号走异步 Job 轮询，单个账号走同步接口。
   * 批量检测与失败重检共用，仅提示文案与展示粒度不同。
   */
  const runStatusCheck = async (
    names: string[],
    opts: {
      /** 空目标/未登录时的提示 key */
      emptyTargetKey: string
      /** 任务启动成功提示 key（含插值） */
      startedKey: string
      /** 是否带 scoped 提示（批量检测带，失败重检不带） */
      scopedHint?: string
      /** 同步结果失败 toast 是否带失败账号预览 */
      withFailedPreview?: boolean
    },
  ) => {
    const token = getAuthToken()
    if (!token || names.length === 0) {
      toast.error(t(opts.emptyTargetKey))
      return
    }
    if (batchChecking.value) return

    batchChecking.value = true
    batchJob.value = null
    batchResultMap.value = {}
    lastLiveRefreshDone = 0
    clearBatchPoll()
    try {
      if (names.length >= 2) {
        const job = await startAccountStatusCheckJob(token, {
          account_names: names,
          timeout_seconds: 8,
        })
        batchJob.value = job
        const progressDesc = t('accounts.batchCheckProgress', {
          done: job.progress?.done ?? 0,
          total: job.progress?.total ?? names.length,
        })
        toast.success(t(opts.startedKey), {
          description: [opts.scopedHint, progressDesc].filter(Boolean).join('\n'),
        })
        startPollingJob(job.job_id)
        await pollBatchJob(job.job_id)
        return
      }

      const res = await checkAccountsStatus(token, { account_names: names, timeout_seconds: 8 })
      lastBatchFailedNames.value = res.results
        .filter((item) => !item.ok && item.account_name)
        .map((item) => item.account_name)
      await options.loadAccounts()
      const ok = res.results.filter((item) => item.ok).length
      const failed = res.results.length - ok
      if (failed === 0) {
        toast.success(t('accounts.batchCheckDone'), {
          description: [opts.scopedHint, `${t('accounts.checkOkCount')}: ${ok}`]
            .filter(Boolean)
            .join('\n'),
        })
      } else {
        const failedPreview = opts.withFailedPreview
          ? res.results
              .filter((item) => !item.ok)
              .slice(0, 5)
              .map((item) => `${item.account_name}: ${item.message || item.code || t('accounts.loginExpired')}`)
              .join('\n')
          : undefined
        toast.error(t('accounts.batchCheckDone'), {
          description: [
            opts.scopedHint,
            `${t('accounts.checkOkCount')}: ${ok} · ${t('accounts.checkFailedCount')}: ${failed}`,
            failedPreview,
          ]
            .filter(Boolean)
            .join('\n'),
          duration: 8000,
        })
      }
    } catch (e: unknown) {
      notifyApiError(e, 'accounts.checkFailed')
    } finally {
      if (!batchPollHandle?.active) {
        batchChecking.value = false
      }
    }
  }

  const handleBatchCheck = async () => {
    const source = options.searchQuery.value.trim()
      ? options.filteredAccounts.value
      : options.accounts.value
    const names = source.map((acc) => acc.name).filter(Boolean)
    const scopedHint =
      options.searchQuery.value.trim() && names.length < options.accounts.value.length
        ? t('accounts.batchCheckScoped', {
            n: names.length,
            total: options.accounts.value.length,
          })
        : undefined
    await runStatusCheck(names, {
      emptyTargetKey: 'accounts.batchCheckNoTarget',
      startedKey: 'accounts.batchCheckStarted',
      scopedHint,
      withFailedPreview: true,
    })
  }

  const handleCancelBatchCheck = async () => {
    const jobId = batchJob.value?.job_id
    if (!jobId) return
    return withToken(async (token) => {
      try {
        await cancelAccountStatusCheckJob(token, jobId)
        toast.success(t('accounts.batchCheckCancelRequested'))
        await pollBatchJob(jobId)
      } catch (e: unknown) {
        notifyApiError(e, 'accounts.checkFailed')
      }
    })
  }

  const handleRecheckFailed = async () => {
    const names = [...lastBatchFailedNames.value]
    await runStatusCheck(names, {
      emptyTargetKey: 'accounts.batchCheckNoFailed',
      startedKey: 'accounts.batchRecheckStarted',
    })
  }

  return {
    checkingAccount,
    batchChecking,
    batchJob,
    batchProgressPct,
    lastFailedAccountNames,
    handleCheck,
    handleBatchCheck,
    handleCancelBatchCheck,
    handleRecheckFailed,
    resumeActiveBatchJob,
  }
}
