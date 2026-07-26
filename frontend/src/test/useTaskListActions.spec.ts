import { beforeEach, describe, expect, it, vi } from 'vitest'
import { computed, ref } from 'vue'
import { makeTaskUi, mockI18nPassthrough } from './composable-test-utils'

const { toastSpy, confirmMock } = vi.hoisted(() => {
  // inline minimal spies to avoid hoisting issues with imports
  const toastSpy = {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    show: vi.fn(),
    dismiss: vi.fn(),
    clear: vi.fn(),
  }
  const confirmMock = {
    confirm: vi.fn(async () => true),
    accept: vi.fn(),
    cancel: vi.fn(),
  }
  return { toastSpy, confirmMock }
})

vi.mock('../composables/useI18n', () => ({
  useI18n: () => mockI18nPassthrough(),
}))

vi.mock('../composables/useToast', () => ({
  useToast: () => toastSpy,
}))

vi.mock('../composables/useConfirm', () => ({
  useConfirm: () => confirmMock,
}))

const api = vi.hoisted(() => ({
  batchSignTasks: vi.fn(),
  cloneSignTask: vi.fn(),
  deleteSignTask: vi.fn(),
  toggleSignTaskEnabled: vi.fn(),
  startSignTaskRun: vi.fn(),
}))

vi.mock('../lib/api', () => api)

import { useTaskListActions } from '../composables/useTaskListActions'
import { useAuthStore } from '../stores/auth'

describe('useTaskListActions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    confirmMock.confirm.mockResolvedValue(true)
    useAuthStore().setToken('tok')
  })

  function setup(tasks = [makeTaskUi()]) {
    const tasksRef = ref(tasks)
    const selectedTaskIds = ref(new Set(tasks.map((t) => t.id)))
    const allAccounts = ref(['acc1', 'acc2'])
    const loadTasks = vi.fn(async () => {})
    const openLogsAfterRun = vi.fn()
    const actions = useTaskListActions({
      tasks: tasksRef,
      selectedTaskIds,
      allAccounts,
      selectedCount: computed(() => selectedTaskIds.value.size),
      loadTasks,
      openLogsAfterRun,
    })
    return { actions, tasksRef, selectedTaskIds, loadTasks, openLogsAfterRun }
  }

  it('getTaskAccountName skips wildcard', () => {
    const task = makeTaskUi({
      raw: { account_name: '*', account_names: ['*', 'real'] },
    })
    const { actions } = setup([task])
    expect(actions.getTaskAccountName(task)).toBe('real')
    expect(actions.getTaskAccountName(task.raw)).toBe('real')
  })

  it('runBatch no-ops when nothing selected', async () => {
    const { actions, selectedTaskIds, loadTasks } = setup()
    selectedTaskIds.value = new Set()
    await actions.runBatch('enable')
    expect(api.batchSignTasks).not.toHaveBeenCalled()
    expect(loadTasks).not.toHaveBeenCalled()
  })

  it('runBatch enable calls API and reloads', async () => {
    api.batchSignTasks.mockResolvedValue({ success_count: 1, fail_count: 0, results: [] })
    const { actions, loadTasks, selectedTaskIds } = setup()
    await actions.runBatch('enable')
    expect(api.batchSignTasks).toHaveBeenCalledWith(
      'tok',
      [{ name: 'task-1', account_name: 'acc1' }],
      'enable',
    )
    expect(toastSpy.success).toHaveBeenCalled()
    expect(selectedTaskIds.value.size).toBe(0)
    expect(loadTasks).toHaveBeenCalled()
  })

  it('runBatch delete aborts when confirm rejected', async () => {
    confirmMock.confirm.mockResolvedValueOnce(false)
    const { actions } = setup()
    await actions.runBatch('delete')
    expect(api.batchSignTasks).not.toHaveBeenCalled()
  })

  it('runBatch partial failure shows error toast', async () => {
    api.batchSignTasks.mockResolvedValue({
      success_count: 1,
      fail_count: 1,
      results: [
        { name: 'task-1', success: true },
        { name: 'task-2', success: false },
      ],
    })
    const t1 = makeTaskUi({ name: 'task-1', id: 'task-1' })
    const t2 = makeTaskUi({ name: 'task-2', id: 'task-2' })
    const { actions } = setup([t1, t2])
    await actions.runBatch('disable')
    expect(toastSpy.error).toHaveBeenCalled()
  })

  it('submitClone validates empty and illegal names', async () => {
    const task = makeTaskUi()
    const { actions } = setup([task])
    actions.openCloneModal(task)
    await actions.submitClone('  ')
    expect(api.cloneSignTask).not.toHaveBeenCalled()
    expect(toastSpy.error).toHaveBeenCalled()

    await actions.submitClone('bad/name')
    expect(api.cloneSignTask).not.toHaveBeenCalled()
  })

  it('submitClone clones and reloads', async () => {
    api.cloneSignTask.mockResolvedValue({})
    const task = makeTaskUi()
    const { actions, loadTasks } = setup([task])
    actions.openCloneModal(task)
    await actions.submitClone('cloned')
    expect(api.cloneSignTask).toHaveBeenCalledWith('tok', 'task-1', 'cloned', 'acc1')
    expect(actions.showCloneModal.value).toBe(false)
    expect(loadTasks).toHaveBeenCalled()
    expect(toastSpy.success).toHaveBeenCalled()
  })

  it('handleDelete respects confirm cancel', async () => {
    confirmMock.confirm.mockResolvedValueOnce(false)
    const { actions } = setup()
    await actions.handleDelete(makeTaskUi())
    expect(api.deleteSignTask).not.toHaveBeenCalled()
  })

  it('handleDelete deletes and reloads', async () => {
    api.deleteSignTask.mockResolvedValue({})
    const task = makeTaskUi()
    const { actions, loadTasks } = setup([task])
    await actions.handleDelete(task)
    expect(api.deleteSignTask).toHaveBeenCalledWith('tok', 'task-1', 'acc1')
    expect(loadTasks).toHaveBeenCalled()
  })

  it('handleToggleEnabled toggles', async () => {
    api.toggleSignTaskEnabled.mockResolvedValue({})
    const task = makeTaskUi({ enabled: true })
    const { actions, loadTasks } = setup([task])
    await actions.handleToggleEnabled(task)
    expect(api.toggleSignTaskEnabled).toHaveBeenCalledWith('tok', 'task-1', 'acc1')
    expect(loadTasks).toHaveBeenCalled()
  })

  it('handleRun opens menu for multi-account wildcard', () => {
    const task = makeTaskUi({
      raw: { account_name: '*', account_names: ['*'] },
    })
    const { actions } = setup([task])
    actions.handleRun(task)
    expect(actions.runMenuTask.value?.name).toBe('task-1')
    expect(actions.runMenuAccounts.value).toEqual(['acc1', 'acc2'])
  })

  it('doRun starts run and opens logs', async () => {
    api.startSignTaskRun.mockResolvedValue({})
    const task = makeTaskUi()
    const { actions, openLogsAfterRun } = setup([task])
    await actions.doRun(task, 'acc1')
    expect(api.startSignTaskRun).toHaveBeenCalledWith('tok', 'task-1', 'acc1')
    expect(openLogsAfterRun).toHaveBeenCalledWith(task, 'acc1')
  })

  it('doRun surfaces API errors', async () => {
    api.startSignTaskRun.mockRejectedValue(new Error('boom'))
    const task = makeTaskUi()
    const { actions, openLogsAfterRun } = setup([task])
    await actions.doRun(task, 'acc1')
    expect(toastSpy.error).toHaveBeenCalled()
    expect(openLogsAfterRun).not.toHaveBeenCalled()
  })
})
