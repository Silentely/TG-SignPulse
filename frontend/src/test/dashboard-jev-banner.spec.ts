import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { ref } from 'vue'
import Dashboard from '../views/Dashboard.vue'

const mockPush = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockPush }),
}))

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: Record<string, any>) => {
      if (params?.count) return `${key}:${params.count}`
      if (params?.rate !== undefined) return `${key}:${params.rate}%`
      return key
    },
  }),
}))

const mockJevStatus = ref({
  enabled: true,
  hasApiKey: true,
  breakerState: 'closed' as 'closed' | 'open' | 'half_open',
  consecutiveFailures: 0,
  totalCalls: 10,
  cacheHitRate: 0.5,
})

vi.mock('../composables/useDashboardData', () => ({
  useDashboardData: () => ({
    pageLoading: ref(false),
    partialLoad: ref(false),
    refreshing: ref(false),
    liveConnected: ref(true),
    stats: ref([]),
    logs: ref([]),
    upcomingJobs: ref([]),
    activeRuns: ref([]),
    failureBreakdown: ref([]),
    recentHits: ref([]),
    statusJobs: ref([]),
    jevStatus: mockJevStatus,
    formatTime: vi.fn(),
    reload: vi.fn(),
  }),
}))

vi.mock('../components/dashboard/DashboardTrendsChart.vue', () => ({
  default: { template: '<div data-testid="trends-chart" />' },
}))

describe('Dashboard JEV Status and Circuit Breaker Alert', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockJevStatus.value = {
      enabled: true,
      hasApiKey: true,
      breakerState: 'closed',
      consecutiveFailures: 0,
      totalCalls: 10,
      cacheHitRate: 0.5,
    }
  })

  it('does not display warning banner when breaker is closed', () => {
    const wrapper = mount(Dashboard)
    expect(wrapper.find('[data-testid="jev-breaker-alert"]').exists()).toBe(false)
    const badge = wrapper.find('[data-testid="jev-status-badge"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toContain('dashboard.jevStatusHealthy:50%')
  })

  it('displays warning banner when breaker is open', async () => {
    mockJevStatus.value = {
      enabled: true,
      hasApiKey: true,
      breakerState: 'open',
      consecutiveFailures: 5,
      totalCalls: 15,
      cacheHitRate: 0.2,
    }
    const wrapper = mount(Dashboard)
    const alert = wrapper.find('[data-testid="jev-breaker-alert"]')
    expect(alert.exists()).toBe(true)
    expect(alert.text()).toContain('dashboard.jevBreakerTitle')
    expect(alert.text()).toContain('dashboard.jevBreakerDesc:5')

    // clicking settings button pushes to settings
    const btn = alert.find('button')
    await btn.trigger('click')
    expect(mockPush).toHaveBeenCalledWith({ name: 'settings' })
  })

  it('displays disabled status when jev is not enabled', () => {
    mockJevStatus.value = {
      enabled: false,
      hasApiKey: false,
      breakerState: 'closed',
      consecutiveFailures: 0,
      totalCalls: 0,
      cacheHitRate: 0,
    }
    const wrapper = mount(Dashboard)
    expect(wrapper.find('[data-testid="jev-breaker-alert"]').exists()).toBe(false)
    const badge = wrapper.find('[data-testid="jev-status-badge"]')
    expect(badge.exists()).toBe(true)
    expect(badge.text()).toContain('dashboard.jevStatusDisabled')
  })
})
