/**
 * 签到列表：批量操作、克隆、启停、删除、触发运行。
 */
import { ref, type Ref, type ComputedRef } from 'vue'
import {
  deleteSignTask,
  startSignTaskRun,
  toggleSignTaskEnabled,
  batchSignTasks,
  cloneSignTask,
} from '../lib/api'
import { getAuthToken } from '../lib/api/core'
import type { SignTask } from '../lib/api'
import type { TaskUiItem } from '../lib/types'
import { getLocalizedErrorMessage } from '../lib/types'
import { notifyApiError } from '../lib/notify'
import {
  resolveTaskAccountName,
  resolveTaskRealAccounts,
} from '../lib/task-list-map'
import { useI18n } from './useI18n'
import { useToast } from './useToast'
import { useConfirm } from './useConfirm'

export function useTaskListActions(options: {
  tasks: Ref<TaskUiItem[]>
  selectedTaskIds: Ref<Set<string>>
  allAccounts: Ref<string[]>
  selectedCount: ComputedRef<number>
  loadTasks: () => Promise<void>
  openLogsAfterRun: (task: TaskUiItem, accountName: string) => void
}) {
  const { t } = useI18n()
  const toast = useToast()
  const { confirm } = useConfirm()

  const batchBusy = ref(false)
  const cloneBusy = ref(false)
  /** 单任务操作 busy 键：启停请求在途时防连点竞态（无确认弹窗的轻操作） */
  const toggleBusyKey = ref('')
  /** 触发运行 busy 键：启动请求在途时防连点重复触发 */
  const runBusyKey = ref('')
  /** 单任务删除 busy 键：确认后的删除请求在途时禁用删除按钮 */
  const deleteBusyKey = ref('')
  const showCloneModal = ref(false)
  const cloneSource = ref<TaskUiItem | null>(null)
  const runMenuTask = ref<TaskUiItem | null>(null)
  const runMenuAccounts = ref<string[]>([])

  const clearSelection = () => {
    options.selectedTaskIds.value = new Set()
  }

  // 与 Tasks 视图 / 弹窗共享同一账号名解析：直接值优先、跳过通配符、回落 account_names
  const getTaskAccountName = (task: SignTask | TaskUiItem): string => resolveTaskAccountName(task)

  const getTaskRealAccounts = (task: TaskUiItem | SignTask): string[] =>
    resolveTaskRealAccounts(task, options.allAccounts.value)

  const runBatch = async (action: 'enable' | 'disable' | 'delete' | 'run') => {
    if (!options.selectedCount.value || batchBusy.value) return
    if (action === 'delete') {
      const ok = await confirm({
        title: t('common.dangerConfirm'),
        message: `${t('tasks.batchDeleteConfirm')} (${options.selectedCount.value})`,
        confirmText: t('common.delete'),
        danger: true,
      })
      if (!ok) return
    }
    const token = getAuthToken()
    const items = options.tasks.value
      .filter((task) => options.selectedTaskIds.value.has(task.id))
      .map((task) => ({
        name: task.name,
        account_name: getTaskAccountName(task.raw) || undefined,
      }))
    batchBusy.value = true
    try {
      const res = await batchSignTasks(token, items, action)
      if (res.fail_count === 0) {
        toast.success(t('tasks.batchSuccessDetail', { ok: res.success_count }))
      } else {
        const failedNames = (res.results || [])
          .filter((r) => !r.success)
          .map((r) => r.name)
          .filter(Boolean)
          .slice(0, 3)
        const detail = failedNames.length
          ? ` · ${failedNames.join(', ')}${(res.fail_count || 0) > failedNames.length ? '…' : ''}`
          : ''
        toast.warning(
          `${t('tasks.batchPartialDetail', { ok: res.success_count, fail: res.fail_count })}${detail}`,
        )
      }
      clearSelection()
      await options.loadTasks()
    } catch (e: unknown) {
      notifyApiError(e, 'tasks.batchFailed')
    } finally {
      batchBusy.value = false
    }
  }

  const openCloneModal = (task: TaskUiItem) => {
    cloneSource.value = task
    showCloneModal.value = true
  }

  const closeCloneModal = () => {
    showCloneModal.value = false
    cloneSource.value = null
  }

  const submitClone = async (rawName: string) => {
    if (cloneBusy.value || !cloneSource.value) return
    const newName = rawName.trim()
    if (!newName) {
      toast.error(t('tasks.cloneNameRequired'))
      return
    }
    if (/[/\\]/.test(newName)) {
      toast.error(t('tasks.cloneNameInvalid'))
      return
    }
    const token = getAuthToken()
    cloneBusy.value = true
    try {
      await cloneSignTask(
        token,
        cloneSource.value.name,
        newName,
        getTaskAccountName(cloneSource.value) || undefined,
      )
      toast.success(t('tasks.cloneSuccess'))
      closeCloneModal()
      await options.loadTasks()
    } catch (e: unknown) {
      notifyApiError(e, 'tasks.cloneFailed')
    } finally {
      cloneBusy.value = false
    }
  }

  const handleDelete = async (task: TaskUiItem) => {
    const ok = await confirm({
      title: t('common.dangerConfirm'),
      message: `${t('tasks.deleteConfirm')} ${task.name} ?`,
      confirmText: t('common.delete'),
      danger: true,
    })
    if (!ok) return
    if (deleteBusyKey.value) return
    deleteBusyKey.value = task.name
    const token = getAuthToken()
    try {
      const accountName = getTaskAccountName(task.raw) || undefined
      await deleteSignTask(token, task.name, accountName)
      toast.success(t('tasks.deleteSuccess'))
      await options.loadTasks()
    } catch (e: unknown) {
      toast.error(
        `${t('tasks.deleteFailed')}: ${getLocalizedErrorMessage(e, t, t('tasks.unknownError'))}`,
      )
    } finally {
      deleteBusyKey.value = ''
    }
  }

  const handleToggleEnabled = async (task: TaskUiItem) => {
    if (toggleBusyKey.value) return
    toggleBusyKey.value = task.name
    const token = getAuthToken()
    try {
      const accountName = getTaskAccountName(task.raw) || undefined
      await toggleSignTaskEnabled(token, task.name, accountName)
      toast.success(task.enabled ? t('tasks.pauseSuccess') : t('tasks.resumeSuccess'))
      await options.loadTasks()
    } catch (e: unknown) {
      toast.error(
        `${t('tasks.toggleFailed')}: ${getLocalizedErrorMessage(e, t, t('tasks.unknownError'))}`,
      )
    } finally {
      toggleBusyKey.value = ''
    }
  }

  const doRun = async (task: TaskUiItem, accountName: string) => {
    if (runBusyKey.value) return
    runBusyKey.value = `${task.name}:${accountName}`
    runMenuTask.value = null
    const token = getAuthToken()
    try {
      await startSignTaskRun(token, task.name, accountName)
      options.openLogsAfterRun(task, accountName)
    } catch (e: unknown) {
      toast.error(
        `${t('tasks.triggerFailed')}: ${getLocalizedErrorMessage(e, t, t('tasks.unknownError'))}`,
      )
    } finally {
      runBusyKey.value = ''
    }
  }

  const handleRun = (task: TaskUiItem) => {
    const accounts = getTaskRealAccounts(task)
    if (accounts.length <= 1) {
      void doRun(task, accounts[0] || getTaskAccountName(task.raw))
    } else {
      runMenuTask.value = task
      runMenuAccounts.value = accounts
    }
  }

  const closeRunMenu = () => {
    runMenuTask.value = null
  }

  return {
    batchBusy,
    cloneBusy,
    toggleBusyKey,
    runBusyKey,
    deleteBusyKey,
    showCloneModal,
    cloneSource,
    runMenuTask,
    runMenuAccounts,
    clearSelection,
    getTaskAccountName,
    getTaskRealAccounts,
    runBatch,
    openCloneModal,
    closeCloneModal,
    submitClone,
    handleDelete,
    handleToggleEnabled,
    handleRun,
    doRun,
    closeRunMenu,
  }
}
