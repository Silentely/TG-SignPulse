/**
 * composable 单测共用：i18n / toast / confirm / 路由 / mount 工厂。
 */
import { defineComponent, h, ref, type Ref } from 'vue'
import { mount, type VueWrapper } from '@vue/test-utils'
import { vi } from 'vitest'
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

/** 可变路由 query，配合 vi.mock('vue-router') */
export type MockRouteState = {
  query: Record<string, string | undefined>
  name: string
}

export function createRouteMocks(initial?: Partial<MockRouteState>) {
  const state: MockRouteState = {
    query: { ...(initial?.query || {}) },
    name: initial?.name || 'logs',
  }
  const replace = vi.fn(async (loc: { name?: string; query?: Record<string, unknown> }) => {
    if (loc.name) state.name = loc.name
    if (loc.query) {
      state.query = { ...loc.query } as Record<string, string | undefined>
    }
  })
  const push = vi.fn(async (loc: { name?: string; query?: Record<string, unknown> }) => {
    await replace(loc)
  })
  return {
    state,
    route: {
      get name() {
        return state.name
      },
      get query() {
        return state.query
      },
    },
    router: { replace, push },
  }
}

/**
 * 挂载一次性组件以触发 onMounted / onUnmounted。
 * factory 在 setup 内调用目标 composable。
 */
export function mountComposable<T>(factory: () => T): {
  result: T
  wrapper: VueWrapper
  unmount: () => void
} {
  let result!: T
  const Comp = defineComponent({
    name: 'ComposableHarness',
    setup() {
      result = factory()
      return () => h('div', { 'data-testid': 'composable-harness' })
    },
  })
  const wrapper = mount(Comp)
  return {
    result,
    wrapper,
    unmount: () => wrapper.unmount(),
  }
}

/** 排空微任务队列（多段 await 的 composable 需要多轮） */
export async function flushPromises(rounds = 20) {
  for (let i = 0; i < rounds; i++) {
    await Promise.resolve()
  }
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

export function makeAccountUi(
  name: string,
  over: Partial<{ status: string; message: string }> = {},
) {
  return {
    id: name,
    name,
    remark: '',
    status: over.status || 'active',
    message: over.message || '',
    avatarUrl: '',
    avatarLoaded: false,
    raw: {
      name,
      status: over.status === 'error' ? 'invalid' : 'connected',
      needs_relogin: over.status === 'error',
    },
  }
}

/** 简易 EventSource mock（仪表盘 SSE） */
export class MockEventSource {
  static instances: MockEventSource[] = []
  url: string
  onerror: ((ev?: unknown) => void) | null = null
  private listeners = new Map<string, Array<(ev: MessageEvent) => void>>()

  constructor(url: string) {
    this.url = url
    MockEventSource.instances.push(this)
  }

  addEventListener(type: string, fn: (ev: MessageEvent) => void) {
    const list = this.listeners.get(type) || []
    list.push(fn)
    this.listeners.set(type, list)
  }

  close() {
    /* no-op */
  }

  emit(type: string, data: unknown) {
    const payload =
      typeof data === 'string' ? data : JSON.stringify(data ?? {})
    const ev = { data: payload } as MessageEvent
    for (const fn of this.listeners.get(type) || []) fn(ev)
  }

  triggerError() {
    this.onerror?.({})
  }

  static reset() {
    MockEventSource.instances = []
  }
}
