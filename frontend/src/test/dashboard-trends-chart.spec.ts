import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import DashboardTrendsChart from '../components/dashboard/DashboardTrendsChart.vue'
import * as api from '../lib/api'

vi.mock('../lib/api', () => ({
  getHistoryTrends: vi.fn(),
}))

vi.mock('../lib/api/core', () => ({
  withToken: vi.fn((cb) => cb('mock-token')),
}))

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}))

const mockTrendsPayload = {
  days: 7,
  total_runs: 10,
  total_success: 9,
  total_failed: 1,
  overall_success_rate: 0.9,
  trends: [
    { date: '2026-09-05', total: 1, success: 1, failed: 0, success_rate: 1.0 },
    { date: '2026-09-06', total: 2, success: 2, failed: 0, success_rate: 1.0 },
    { date: '2026-09-07', total: 1, success: 0, failed: 1, success_rate: 0.0 },
    { date: '2026-09-08', total: 2, success: 2, failed: 0, success_rate: 1.0 },
    { date: '2026-09-09', total: 1, success: 1, failed: 0, success_rate: 1.0 },
    { date: '2026-09-10', total: 2, success: 2, failed: 0, success_rate: 1.0 },
    { date: '2026-09-11', total: 1, success: 1, failed: 0, success_rate: 1.0 },
  ],
  categories: { timeout: 1 },
}

describe('DashboardTrendsChart', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders trends summary and svg correctly', async () => {
    vi.mocked(api.getHistoryTrends).mockResolvedValueOnce(mockTrendsPayload as any)
    const wrapper = mount(DashboardTrendsChart)
    await flushPromises()

    expect(wrapper.text()).toContain('dashboard.trendsTitle')
    expect(wrapper.text()).toContain('10') // total_runs
    expect(wrapper.text()).toContain('90%') // overall_success_rate
    expect(wrapper.find('svg').exists()).toBe(true)
    expect(wrapper.text()).toContain('timeout: 1')
  })

  it('shows error state and retries on button click', async () => {
    vi.mocked(api.getHistoryTrends)
      .mockRejectedValueOnce(new Error('network error'))
      .mockResolvedValueOnce(mockTrendsPayload as any)

    const wrapper = mount(DashboardTrendsChart)
    await flushPromises()

    expect(wrapper.text()).toContain('dashboard.trendsLoadFailed')
    const retryBtn = wrapper.find('[data-testid="trends-retry-btn"]')
    expect(retryBtn.exists()).toBe(true)

    await retryBtn.trigger('click')
    await flushPromises()

    expect(wrapper.find('svg').exists()).toBe(true)
    expect(wrapper.text()).toContain('90%')
  })
})
