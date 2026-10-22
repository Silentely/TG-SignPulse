import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import i18n from '../i18n'
import Logs from '../views/Logs.vue'
import * as semanticApi from '../lib/api/semantic'

const selectedLog = ref<any>(null)
const logDetail = ref<any>(null)

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
  }),
  useRoute: () => ({
    query: {},
  }),
}))

vi.mock('../composables/useLogsPage', () => ({
  useLogsPage: () => ({
    activeTab: ref('tasks'),
    filterTask: ref(''),
    filterAccount: ref(''),
    filterDate: ref(''),
    filterStatus: ref(''),
    filterCategory: ref(''),
    pageLoading: ref(false),
    loadFailed: ref(false),
    clearing: ref(false),
    selectedLog,
    logDetail,
    detailLoading: ref(false),
    loginLogs: ref([]),
    logs: ref([]),
    accountOptions: ref([]),
    statusOptions: ref([]),
    categoryOptions: ref([]),
    failureCategoryLabel: (cat: string) => cat,
    hasActiveFilters: ref(false),
    loadLogs: vi.fn(),
    openLogDetail: vi.fn(),
    handleClear: vi.fn(),
    exportingAccountLogs: ref(false),
    handleExportAccountLogs: vi.fn(),
    clearCategoryFilter: vi.fn(),
    clearFilters: vi.fn(),
  }),
}))

describe('Logs.vue - Jev Rule Suggestions Integration', () => {
  beforeEach(() => {
    selectedLog.value = null
    logDetail.value = null
    vi.clearAllMocks()
  })

  const mountLogs = () =>
    mount(Logs, {
      global: {
        plugins: [i18n],
        stubs: {
          Modal: {
            props: ['isOpen'],
            template: `
              <div v-if="isOpen" class="modal-stub">
                <slot name="header-extra" />
                <slot />
              </div>
            `,
          },
        },
      },
    })

  it('does not display suggestions panel when no log is selected', () => {
    const wrapper = mountLogs()
    expect(wrapper.findComponent({ name: 'TaskRuleSuggestionsPanel' }).exists()).toBe(false)
  })

  it('mounts TaskRuleSuggestionsPanel with hideWhenEmpty and showNavigateToTasks when a log is selected', async () => {
    vi.spyOn(semanticApi, 'listRuleSuggestions').mockResolvedValue([])

    const wrapper = mountLogs()

    selectedLog.value = {
      id: 'log-1',
      account: 'acc1',
      task: 'checkin',
      time: '2026-10-22 10:00:00',
      status: 'error',
      text: 'Button not found',
    }
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 20))

    const panel = wrapper.findComponent({ name: 'TaskRuleSuggestionsPanel' })
    expect(panel.exists()).toBe(true)
    expect(panel.props('accountName')).toBe('acc1')
    expect(panel.props('taskName')).toBe('checkin')
    expect(panel.props('hideWhenEmpty')).toBe(true)
    expect(panel.props('showNavigateToTasks')).toBe(true)
    // Because hideWhenEmpty is true and suggestions are empty, inner ui-card is hidden
    expect(panel.find('.ui-card').exists()).toBe(false)
  })

  it('renders suggestion card when pending suggestions exist for the selected log', async () => {
    const mockSuggestions: semanticApi.RuleSuggestion[] = [
      {
        id: 'sug-btn',
        scope: 'acc1:checkin',
        account_name: 'acc1',
        task_name: 'checkin',
        kind: 'button_label',
        status: 'pending',
        created_at: 1000,
        confidence: 0.95,
        patch: {
          op: 'replace',
          path: '/chats/0/actions/0/text',
          old: '每日签到',
          value: '点击签到',
        },
      },
    ]
    vi.spyOn(semanticApi, 'listRuleSuggestions').mockResolvedValue(mockSuggestions)

    const wrapper = mountLogs()

    selectedLog.value = {
      id: 'log-1',
      account: 'acc1',
      task: 'checkin',
      time: '2026-10-22 10:00:00',
      status: 'error',
      text: 'Button not found',
    }
    await wrapper.vm.$nextTick()
    await new Promise((r) => setTimeout(r, 30))

    const panel = wrapper.findComponent({ name: 'TaskRuleSuggestionsPanel' })
    expect(panel.exists()).toBe(true)
    expect(panel.find('.ui-card').exists()).toBe(true)
    expect(panel.text()).toContain('button_label')
    expect(panel.text()).toContain('95%')
    expect(panel.text()).toContain('每日签到')
    expect(panel.text()).toContain('点击签到')
    expect(panel.text()).toContain('前往任务编排')
  })
})
