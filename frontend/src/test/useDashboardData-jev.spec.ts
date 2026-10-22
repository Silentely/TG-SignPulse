import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import { setActivePinia, createPinia } from 'pinia'
import * as semanticApi from '../lib/api/semantic'
import * as api from '../lib/api'
import * as coreApi from '../lib/api/core'
import { useDashboardData } from '../composables/useDashboardData'

vi.mock('../lib/api/core', () => ({
  getAuthToken: vi.fn(() => 'mock-jwt-token'),
  request: vi.fn(),
}))

vi.mock('../lib/api', () => ({
  listSignTasks: vi.fn().mockResolvedValue([]),
  getRecentAccountLogs: vi.fn().mockResolvedValue([]),
  listScheduledJobs: vi.fn().mockResolvedValue([]),
  listKeywordHits: vi.fn().mockResolvedValue([]),
  listAccountStatusCheckJobs: vi.fn().mockResolvedValue([]),
  issueStreamTicket: vi.fn().mockResolvedValue({ ticket: 'test-ticket' }),
  STREAM_TICKET_PURPOSE: { signHistorySse: 'sign_history_sse' },
}))

vi.mock('../lib/chain-poll', () => ({
  startChainPoll: vi.fn(() => ({ stop: vi.fn() })),
}))

vi.mock('../lib/devLog', () => ({
  devLog: { error: vi.fn(), info: vi.fn() },
}))

describe('useDashboardData JEV status', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('exposes jevStatus with circuit breaker and call metrics', async () => {
    vi.spyOn(semanticApi, 'getSemanticConfig').mockResolvedValue({
      enabled: true,
      drift_enabled: false,
      mode: 'official',
      base_url: 'https://api.typesafe.ai/v1',
      model: 'jev-1.13.0',
      has_api_key: true,
      api_key_masked: 'sk-***',
      timeout_seconds: 8.0,
      max_concurrency: 2,
      max_calls_per_run: 6,
      max_calls_per_minute: 60,
      retain_evidence: false,
      generation: 1,
      monitor_keys_usage: { count: 0, capacity: 10000, is_full: false },
      stats: {
        total_calls: 42,
        success_calls: 38,
        failed_calls: 4,
        escalate_calls: 0,
        cache_hits: 15,
        cache_misses: 27,
        cache_hit_rate: 0.357,
        breaker: {
          state: 'open',
          consecutive_failures: 5,
        },
      },
    })

    const { jevStatus, reload } = useDashboardData()

    // initial default
    expect(jevStatus.value).toBeDefined()

    // trigger load
    await reload()

    expect(jevStatus.value.enabled).toBe(true)
    expect(jevStatus.value.breakerState).toBe('open')
    expect(jevStatus.value.consecutiveFailures).toBe(5)
    expect(jevStatus.value.totalCalls).toBe(42)
    expect(jevStatus.value.cacheHitRate).toBe(0.357)
  })
})
