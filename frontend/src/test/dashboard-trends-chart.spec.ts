import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import DashboardTrendsChart from '../components/dashboard/DashboardTrendsChart.vue'

vi.mock('../lib/api', () => ({
  getHistoryTrends: vi.fn().mockResolvedValue({
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
  }),
}))

vi.mock('../lib/api/core', () => ({
  withToken: vi.fn((cb) => cb('mock-token')),
}))

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}))

describe('DashboardTrendsChart', () => {
  it('renders trends summary and svg correctly', async () => {
    const wrapper = mount(DashboardTrendsChart)
    // 等待 onMounted 中的异步请求
    await new Promise((r) => setTimeout(r, 50))
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain('签到执行与成功率趋势')
    expect(wrapper.text()).toContain('10') // total_runs
    expect(wrapper.text()).toContain('90%') // overall_success_rate
    expect(wrapper.find('svg').exists()).toBe(true)
  })
})
