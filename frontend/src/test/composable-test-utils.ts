/**
 * composable 单测共用：i18n / toast / confirm mock 工厂。
 */
import { vi } from 'vitest'
import { ref } from 'vue'
import type { TaskUiItem } from '../lib/types'
import type { SignTask } from '../lib/api'

export function mockI18nPassthrough() {
  return {
    t: (key: string, named?: Record<string, unknown>) =>
      named ? `${key}|${JSON.stringify(named)}` : key,
    locale: ref('zh'),
    toggleLanguage: vi.fn(),
  }
}

export function createToastSpy() {
  return {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    show: vi.fn(),
    dismiss: vi.fn(),
    clear: vi.fn(),
    toasts: ref([]),
  }
}

export function createConfirmMock(defaultResult = true) {
  const confirm = vi.fn(async () => defaultResult)
  return { confirm, accept: vi.fn(), cancel: vi.fn(), state: ref({ open: false }) }
}

export function makeTaskUi(over: Partial<TaskUiItem> & { raw?: Partial<SignTask> } = {}): TaskUiItem {
  const name = over.name || 'task-1'
  const raw: SignTask = {
    name,
    account_name: 'acc1',
    account_names: ['acc1'],
    sign_at: '08:00',
    execution_mode: 'fixed',
    chats: [],
    enabled: true,
    ...(over.raw || {}),
  } as SignTask
  return {
    id: name,
    name,
    scheduleMode: '08:00',
    targetStr: 'chat',
    targetCount: 1,
    lastRunStr: '-',
    lastRunSuccess: null,
    modeIcon: {} as TaskUiItem['modeIcon'],
    isListenMode: false,
    enabled: true,
    chatAvatarUrl: '',
    chatName: '',
    raw,
    ...over,
    raw: { ...raw, ...(over.raw || {}) } as SignTask,
  }
}
