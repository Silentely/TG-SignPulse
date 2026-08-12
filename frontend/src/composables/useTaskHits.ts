/**
 * 签到日志弹窗：关键词命中列表/分组、导出与清空。
 */
import { ref, computed, type Ref, type ComputedRef } from 'vue'
import {
  listKeywordHits,
  listKeywordHitGroups,
  exportKeywordHitsBlob,
  clearKeywordHits,
} from '../lib/api'
import { getAuthToken } from '../lib/api/core'
import { downloadBlob } from '../lib/download'
import { useLatestResponseGuard } from '../lib/latest-response'
import type { KeywordHitRecord, KeywordHitGroup } from '../lib/api'
import { notifyApiError } from '../lib/notify'
import { useI18n } from './useI18n'
import { useToast } from './useToast'
import { useConfirm } from './useConfirm'
import { startChainPoll, type ChainPollHandle } from '../lib/chain-poll'
import { devLog } from '../lib/devLog'

const HITS_PAGE_SIZE = 50

export function useTaskHits(options: {
  taskName: ComputedRef<string>
  accountName: ComputedRef<string | undefined>
  isListenTask: ComputedRef<boolean>
  isOpen: ComputedRef<boolean>
  panelTab: Ref<'history' | 'hits'>
}) {
  const { t } = useI18n()
  const toast = useToast()
  const { confirm } = useConfirm()

  const hitsLoading = ref(false)
  const hitsLoadingMore = ref(false)
  /** 命中导出请求在途（禁用导出按钮防重复触发） */
  const hitsExporting = ref(false)
  /** 命中清空请求在途（禁用清空按钮防连点） */
  const hitsClearing = ref(false)
  const hitRecords = ref<KeywordHitRecord[]>([])
  const hitTotal = ref(0)
  const hitGroups = ref<KeywordHitGroup[]>([])
  const hitGroupBy = ref<'task' | 'account' | 'chat'>('chat')
  const hitsView = ref<'list' | 'groups'>('list')
  let hitsPollHandle: ChainPollHandle | null = null
  // 请求序号守卫：弹窗切换任务/关闭时丢弃过期响应，避免慢请求覆盖新数据
  const hitSeqGuard = useLatestResponseGuard()

  const canLoadMoreHits = computed(
    () => hitsView.value === 'list' && hitRecords.value.length < hitTotal.value,
  )

  const clearHitsAutoRefresh = () => {
    hitsPollHandle?.stop()
    hitsPollHandle = null
  }

  const loadHits = async (opts?: { silent?: boolean; append?: boolean }) => {
    if (!options.taskName.value) return
    const silent = !!opts?.silent
    const append = !!opts?.append && hitsView.value === 'list'
    if (append) {
      if (hitsLoadingMore.value || !canLoadMoreHits.value) return
      hitsLoadingMore.value = true
    } else if (!silent) {
      hitsLoading.value = true
    }
    const token = getAuthToken()
    const accountName = options.accountName.value
    const seq = hitSeqGuard.next()
    try {
      if (hitsView.value === 'groups') {
        const res = await listKeywordHitGroups(token, {
          account_name: accountName,
          task_name: options.taskName.value,
          group_by: hitGroupBy.value,
          limit_per_group: 30,
        })
        if (!hitSeqGuard.isCurrent(seq)) return // 过期响应：已切换任务/关闭，丢弃
        hitGroups.value = res.groups || []
        hitTotal.value = hitGroups.value.reduce((sum, g) => sum + (g.count || 0), 0)
        hitRecords.value = []
      } else {
        const offset = append ? hitRecords.value.length : 0
        const res = await listKeywordHits(token, {
          account_name: accountName,
          task_name: options.taskName.value,
          limit: HITS_PAGE_SIZE,
          offset,
        })
        const items = res.items || []
        if (!hitSeqGuard.isCurrent(seq)) return // 过期响应：已切换任务/关闭，丢弃
        if (append) {
          const seen = new Set(hitRecords.value.map((h) => h.id))
          hitRecords.value = [
            ...hitRecords.value,
            ...items.filter((h) => h.id && !seen.has(h.id)),
          ]
        } else if (silent && hitRecords.value.length > 0) {
          const existingIds = new Set(hitRecords.value.map((h) => h.id))
          const fresh = items.filter((h) => h.id && !existingIds.has(h.id))
          if (fresh.length) {
            hitRecords.value = [...fresh, ...hitRecords.value]
          } else {
            const byId = new Map(items.map((h) => [h.id, h]))
            hitRecords.value = hitRecords.value.map((h) => byId.get(h.id) || h)
          }
        } else {
          hitRecords.value = items
        }
        hitTotal.value = res.total || 0
        hitGroups.value = []
      }
    } catch (e: unknown) {
      if (!hitSeqGuard.isCurrent(seq)) return
      devLog.error('Failed to fetch keyword hits', e)
      if (!silent) {
        notifyApiError(e, 'taskLogs.hitsLoadFailed')
        if (!append) {
          hitRecords.value = []
          hitGroups.value = []
          hitTotal.value = 0
        }
      }
    } finally {
      if (hitSeqGuard.isCurrent(seq)) {
        hitsLoading.value = false
        hitsLoadingMore.value = false
      }
    }
  }

  const ensureHitsAutoRefresh = () => {
    clearHitsAutoRefresh()
    if (!options.isOpen.value || !options.isListenTask.value || options.panelTab.value !== 'hits') {
      return
    }
    hitsPollHandle = startChainPoll(
      () => loadHits({ silent: true }),
      { intervalMs: 8000, runImmediately: false },
    )
  }

  const loadMoreHits = () => loadHits({ append: true })

  const exportHits = async () => {
    if (!options.taskName.value || hitsExporting.value) return
    hitsExporting.value = true
    const token = getAuthToken()
    try {
      const blob = await exportKeywordHitsBlob(token, {
        account_name: options.accountName.value,
        task_name: options.taskName.value,
        limit: 2000,
      })
      downloadBlob(blob, `keyword_hits_${options.taskName.value}.csv`)
      toast.success(t('taskLogs.hitsExportDone'))
    } catch (e: unknown) {
      notifyApiError(e, 'taskLogs.hitsExportFailed')
    } finally {
      hitsExporting.value = false
    }
  }

  const clearHits = async () => {
    if (!options.taskName.value) return
    const ok = await confirm({
      title: t('taskLogs.hitsClearTitle'),
      message: t('taskLogs.hitsClearConfirm'),
      confirmText: t('common.delete'),
      danger: true,
    })
    if (!ok) return
    if (hitsClearing.value) return
    hitsClearing.value = true
    const token = getAuthToken()
    try {
      const res = await clearKeywordHits(token, {
        account_name: options.accountName.value,
        task_name: options.taskName.value,
      })
      toast.success(t('taskLogs.hitsCleared', { n: res.deleted ?? 0 }))
      await loadHits()
    } catch (e: unknown) {
      notifyApiError(e, 'taskLogs.hitsClearFailed')
    } finally {
      hitsClearing.value = false
    }
  }

  const resetHitsState = () => {
    // 使在途响应全部失效，避免关闭后写入已重置状态
    hitSeqGuard.invalidate()
    hitRecords.value = []
    hitGroups.value = []
    hitTotal.value = 0
    hitsView.value = 'list'
    hitGroupBy.value = 'chat'
    clearHitsAutoRefresh()
  }

  return {
    hitsLoading,
    hitsLoadingMore,
    hitsExporting,
    hitsClearing,
    hitRecords,
    hitTotal,
    hitGroups,
    hitGroupBy,
    hitsView,
    canLoadMoreHits,
    loadHits,
    loadMoreHits,
    exportHits,
    clearHits,
    ensureHitsAutoRefresh,
    clearHitsAutoRefresh,
    resetHitsState,
  }
}
