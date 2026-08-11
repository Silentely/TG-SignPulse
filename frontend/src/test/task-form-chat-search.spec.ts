/**
 * TaskForm 会话搜索：防抖 + 过期响应丢弃 + 卸载清理定时器。
 */
import { defineComponent } from 'vue'
import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mockI18nPassthrough } from './composable-test-utils'
import { useAuthStore } from '../stores/auth'

const api = vi.hoisted(() => ({
  listAccounts: vi.fn(),
  getAccountChats: vi.fn(),
  searchAccountChats: vi.fn(),
}))

vi.mock('../lib/api', () => api)
vi.mock('../composables/useI18n', () => ({
  useI18n: () => mockI18nPassthrough(),
}))
vi.mock('../composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), show: vi.fn() }),
}))

import TaskForm from '../components/tasks/TaskForm.vue'

const TargetSectionStub = defineComponent({
  name: 'TaskFormTargetSection',
  props: {
    chatSearch: { type: String, default: '' },
    chatSearchResults: { type: Array, default: () => [] },
    chatSearchLoading: { type: Boolean, default: false },
  },
  emits: ['update:chat-search'],
  template: '<div class="target-section-stub" />',
})

const mountForm = () =>
  mount(TaskForm, {
    props: {
      initialTask: undefined,
      preferAccount: null,
      lockTaskName: false,
    },
    global: {
      stubs: {
        CustomSelect: true,
        MultiSelect: true,
        TaskFormTargetSection: TargetSectionStub,
        TaskFormListenSection: true,
        TaskFormActionsSection: true,
      },
    },
  })

const setSearch = (wrapper: ReturnType<typeof mountForm>, value: string) => {
  wrapper.findComponent({ name: 'TaskFormTargetSection' }).vm.$emit('update:chat-search', value)
}

const searchResults = (wrapper: ReturnType<typeof mountForm>) => {
  const props = wrapper.findComponent({ name: 'TaskFormTargetSection' }).props() as {
    chatSearchResults: { id: number }[]
  }
  return props.chatSearchResults
}

describe('TaskForm 会话搜索', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    useAuthStore().setToken('tok')
    api.listAccounts.mockResolvedValue({ accounts: [{ name: 'acc1' }] })
    api.getAccountChats.mockResolvedValue({ items: [] })
    api.searchAccountChats.mockResolvedValue({ items: [] })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('丢弃过期的搜索结果，慢请求不覆盖新输入', async () => {
    let resolveStale!: (v: unknown) => void
    const stalePromise = new Promise((resolve) => {
      resolveStale = resolve
    })
    // 第一次输入 'a' 的请求挂起，第二次输入 'ab' 立即返回
    api.searchAccountChats
      .mockReturnValueOnce(stalePromise)
      .mockResolvedValueOnce({ items: [{ id: 2, title: 'fresh', username: '' }] })

    const wrapper = mountForm()
    await flushPromises() // 完成 loadAccounts / loadChats

    setSearch(wrapper, 'a')
    await vi.advanceTimersByTimeAsync(300) // 第一次请求发出（挂起）
    setSearch(wrapper, 'ab')
    await vi.advanceTimersByTimeAsync(300) // 第二次请求发出并返回
    await flushPromises()

    expect(searchResults(wrapper).map((r) => r.id)).toEqual([2])

    // 迟到的旧响应不得覆盖新结果
    resolveStale({ items: [{ id: 1, title: 'stale', username: '' }] })
    await flushPromises()
    expect(searchResults(wrapper).map((r) => r.id)).toEqual([2])
    wrapper.unmount()
  })

  it('输入变化会取消上一个待执行请求', async () => {
    const wrapper = mountForm()
    await flushPromises()

    setSearch(wrapper, 'a')
    await vi.advanceTimersByTimeAsync(150) // 尚未到 300ms 防抖窗口
    setSearch(wrapper, 'ab') // 取消 'a' 的定时器
    await vi.advanceTimersByTimeAsync(300)
    await flushPromises()

    expect(api.searchAccountChats).toHaveBeenCalledTimes(1)
    expect(api.searchAccountChats).toHaveBeenCalledWith('tok', 'acc1', 'ab')
    wrapper.unmount()
  })

  it('卸载时清理待执行定时器，不再发起请求', async () => {
    const wrapper = mountForm()
    await flushPromises()

    setSearch(wrapper, 'a')
    wrapper.unmount()
    await vi.advanceTimersByTimeAsync(1000)

    expect(api.searchAccountChats).not.toHaveBeenCalled()
  })
})
