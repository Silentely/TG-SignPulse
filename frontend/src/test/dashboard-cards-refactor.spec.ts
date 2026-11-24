import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'
import Dashboard from '../views/Dashboard.vue'
import { useAccountsStore } from '../stores/accounts'

const mockPush = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockPush }),
}))

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: Record<string, any>) => {
      if (params?.count !== undefined) return `${key}:${params.count}`
      if (params?.rate !== undefined) return `${key}:${params.rate}%`
      return key
    },
  }),
}))

const mockLogs = ref<any[]>([])
const mockActiveRuns = ref<any[]>([])
const mockFailureBreakdown = ref<any[]>([])
const mockUpcomingJobs = ref<any[]>([])

vi.mock('../composables/useDashboardData', () => ({
  useDashboardData: () => ({
    pageLoading: ref(false),
    partialLoad: ref(false),
    refreshing: ref(false),
    liveConnected: ref(true),
    stats: ref([]),
    logs: mockLogs,
    upcomingJobs: mockUpcomingJobs,
    activeRuns: mockActiveRuns,
    failureBreakdown: mockFailureBreakdown,
    recentHits: ref([]),
    statusJobs: ref([]),
    jevStatus: ref({
      enabled: false,
      hasApiKey: false,
      runtimeAvailable: false,
      stale: false,
      breakerState: 'unknown',
      consecutiveFailures: 0,
      totalCalls: 0,
      cacheHitRate: 0,
    }),
    formatTime: (time: string) => time || '',
    reload: vi.fn(),
  }),
}))

vi.mock('../components/dashboard/DashboardTrendsChart.vue', () => ({
  default: { template: '<div data-testid=\"trends-chart\" />' },
}))

describe('Dashboard Refactored Core Cards', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    mockLogs.value = []
    mockActiveRuns.value = []
    mockFailureBreakdown.value = []
    mockUpcomingJobs.value = []
  })

  it('Card 1: displays recent completed runs when active runs is empty', () => {
    mockLogs.value = [
      {
        account: 'user1',
        task: 'Channel Sign',
        status: 'success',
        text: 'signed ok',
        time: '12:00:00',
        created_at: '2026-11-24T12:00:00Z',
      },
      {
        account: 'user2',
        task: 'Bot Checkin',
        status: 'error',
        text: 'timeout',
        time: '12:05:00',
        created_at: '2026-11-24T12:05:00Z',
      },
    ]

    const wrapper = mount(Dashboard)
    expect(wrapper.text()).toContain('dashboard.runStatusAndRecent')
    expect(wrapper.text()).toContain('dashboard.noActiveRuns')
    expect(wrapper.text()).toContain('dashboard.recentFinished')
    expect(wrapper.text()).toContain('Channel Sign')
    expect(wrapper.text()).toContain('Bot Checkin')
  })

  it('Card 2: displays failure breakdown tags and navigates on click', async () => {
    mockFailureBreakdown.value = [
      { category: 'reply_timeout', count: 4 },
      { category: 'session_invalid', count: 1 },
    ]

    const wrapper = mount(Dashboard)
    expect(wrapper.text()).toContain('dashboard.failureBreakdown')
    const failureBadges = wrapper.findAll('.ui-badge-error')
    expect(failureBadges.length).toBeGreaterThanOrEqual(2)

    // Click session_invalid button
    const sessionInvalidBtn = failureBadges.find((b) => b.text().includes('session_invalid') || b.text().includes('会话失效'))
    if (sessionInvalidBtn) {
      await sessionInvalidBtn.trigger('click')
      expect(mockPush).toHaveBeenCalledWith({ name: 'accounts' })
    }
  })

  it('Card 3: displays upcoming sign jobs', () => {
    mockUpcomingJobs.value = [
      {
        id: 'task_morning',
        kind: 'sign',
        next_run_time: '2026-11-24T15:00:00Z',
        execution_mode: 'fixed',
      },
    ]

    const wrapper = mount(Dashboard)
    expect(wrapper.text()).toContain('dashboard.upcomingRuns')
    expect(wrapper.text()).toContain('task_morning')
  })

  it('Card 4: displays healthy shield when all accounts are connected', () => {
    const accountsStore = useAccountsStore()
    accountsStore.accounts = [
      { name: 'acc1', status: 'connected', exists: true, session_file: 'acc1.session', size: 100 },
      { name: 'acc2', status: 'connected', exists: true, session_file: 'acc2.session', size: 100 },
    ]

    const wrapper = mount(Dashboard)
    expect(wrapper.text()).toContain('dashboard.accountHealth')
    expect(wrapper.text()).toContain('dashboard.allAccountsHealthy')
    expect(wrapper.text()).toContain('dashboard.healthyCount:2')
  })

  it('Card 4: displays warning alert when accounts need re-login', async () => {
    const accountsStore = useAccountsStore()
    accountsStore.accounts = [
      { name: 'acc_ok', status: 'connected', exists: true, session_file: 'acc_ok.session', size: 100 },
      { name: 'acc_expired', status: 'invalid', needs_relogin: true, exists: true, session_file: 'acc_expired.session', size: 100 },
    ]

    const wrapper = mount(Dashboard)
    expect(wrapper.text()).toContain('dashboard.accountHealth')
    expect(wrapper.text()).toContain('dashboard.accountsNeedingRelogin')
    expect(wrapper.text()).toContain('acc_expired')
    expect(wrapper.text()).toContain('dashboard.invalidCount:1')

    // Click relogin button navigates to accounts
    const reloginBtn = wrapper.find('button.text-rose-600, button.text-rose-400')
    if (reloginBtn.exists()) {
      await reloginBtn.trigger('click')
      expect(mockPush).toHaveBeenCalledWith({ name: 'accounts' })
    }
  })
})
