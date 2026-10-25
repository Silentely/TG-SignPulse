import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AccountImpactModal from '../components/accounts/AccountImpactModal.vue'
import { previewAccountChange, applyAccountChange, type AccountChangePlan } from '../lib/api/accounts'
import { request } from '../lib/api/core'

vi.mock('../lib/api/core', () => ({
  request: vi.fn(), requestBlob: vi.fn(), requestFormData: vi.fn(), fetchWithAuth: vi.fn(),
  createRequestAbort: vi.fn(), LONG_TIMEOUT_MS: 1000, MEDIUM_TIMEOUT_MS: 500,
}))

const plan: AccountChangePlan = {
  operation: 'delete', old_name: 'alice', new_name: null,
  affected_tasks: [{ name: 'daily', path: '/signs/alice/daily/config.json', owned: true }],
  affected_jobs: ['sign-alice-daily'], affected_monitors: ['alice/daily'],
  history_policy: 'retain', history_paths: ['alice__daily.json'],
  plugin_namespaces: ['shared (retained)'], reversible_steps: ['stage'],
  warnings: ['Session removal requires login again.'], revision: 'r1',
}

describe('account lifecycle impact', () => {
  it('shows resources, retained history and rollback warning before confirmation', async () => {
    const wrapper = mount(AccountImpactModal, {
      props: { isOpen: true, plan, loading: false },
      global: { stubs: { Modal: { template: '<section><slot /></section>' } } },
    })
    expect(wrapper.text()).toContain('daily')
    expect(wrapper.text()).toContain('sign-alice-daily')
    expect(wrapper.text()).toContain('alice/daily')
    expect(wrapper.text()).toContain('Retain / 保留')
    expect(wrapper.text()).toContain('shared (retained)')
    expect(wrapper.text()).toContain('Session removal requires login again.')
    expect(wrapper.emitted('apply')).toBeUndefined()
    await wrapper.findAll('button')[1]!.trigger('click')
    expect(wrapper.emitted('apply')).toHaveLength(1)
    await wrapper.setProps({ loading: true, error: 'ACCOUNT_PLAN_STALE' })
    expect(wrapper.findAll('button')[1]!.attributes('disabled')).toBeDefined()
    expect(wrapper.get('[role="alert"]').text()).toBe('ACCOUNT_PLAN_STALE')
  })

  it('encodes account names and sends the reviewed plan unchanged for server revalidation', async () => {
    vi.mocked(request).mockResolvedValue(plan)
    await previewAccountChange('token', '测试 account', 'rename', 'bob')
    expect(request).toHaveBeenLastCalledWith('/accounts/%E6%B5%8B%E8%AF%95%20account/lifecycle/preview', {
      method: 'POST', body: JSON.stringify({ operation: 'rename', new_name: 'bob', history_policy: 'retain' }),
    }, 'token')
    await applyAccountChange('token', plan)
    expect(request).toHaveBeenLastCalledWith('/accounts/alice/lifecycle/apply', {
      method: 'POST', body: JSON.stringify({ plan }),
    }, 'token')
  })
})
