import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import EditAccountModal from '../components/accounts/EditAccountModal.vue'

const apiMocks = vi.hoisted(() => ({
  updateAccount: vi.fn().mockResolvedValue({ success: true }),
  previewAccountChange: vi.fn(),
  applyAccountChange: vi.fn(),
}))

vi.mock('../lib/api', () => ({ updateAccount: apiMocks.updateAccount }))
vi.mock('../lib/api/core', () => ({ getAuthToken: () => 'tok' }))
vi.mock('../lib/api/accounts', () => ({
  previewAccountChange: apiMocks.previewAccountChange,
  applyAccountChange: apiMocks.applyAccountChange,
}))
vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))
vi.mock('../composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}))

// 面板与页脚都要真实渲染，否则拿不到 API ID 输入框与保存按钮
const ModalStub = defineComponent({
  name: 'Modal',
  emits: ['close', 'closed'],
  template: '<div><slot /><slot name="footer" /></div>',
})

const account = {
  id: 'acc-a',
  name: 'acc-a',
  remark: '',
  message: '',
  avatarUrl: '',
  status: 'active',
  raw: {
    name: 'acc-a',
    proxy: '',
    api_id: 111,
    has_api_hash: true,
    api_hash_masked: 'd524****ac9c',
    use_custom_api: true,
    needs_relogin: false,
  },
} as never

const mountModal = () =>
  mount(EditAccountModal, {
    props: { isOpen: true, account },
    global: { stubs: { Modal: ModalStub, AccountImpactModal: true } },
  })

const saveButton = (wrapper: ReturnType<typeof mountModal>) => {
  const btn = wrapper.findAll('button').find((b) => b.text() === 'editAccount.saveChanges')
  if (!btn) throw new Error('save button not found')
  return btn
}

const expandCredentials = async (wrapper: ReturnType<typeof mountModal>) => {
  await wrapper.find('button[aria-controls]').trigger('click')
  return wrapper.find('input[id^="account-api-id-"]')
}

describe('EditAccountModal 账号级凭据门禁', () => {
  beforeEach(() => {
    apiMocks.updateAccount.mockClear()
    apiMocks.previewAccountChange.mockClear()
    apiMocks.applyAccountChange.mockClear()
  })

  it('改动 API ID 却留空 Hash 时拦截保存，请求不会发出', async () => {
    const wrapper = mountModal()
    const idInput = await expandCredentials(wrapper)
    await idInput.setValue('222')

    await saveButton(wrapper).trigger('click')

    expect(apiMocks.updateAccount).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('accountApi.pairRequired')
  })

  it('API ID 未改动时允许沿用已保存 Hash', async () => {
    const wrapper = mountModal()
    await expandCredentials(wrapper)

    await saveButton(wrapper).trigger('click')

    expect(apiMocks.updateAccount).toHaveBeenCalledTimes(1)
    const payload = apiMocks.updateAccount.mock.calls[0]?.[2] as Record<string, unknown>
    // 未改动凭据：不下发 api_id / api_hash
    expect(payload).not.toHaveProperty('api_id')
    expect(payload).not.toHaveProperty('api_hash')
  })

  it('改动 API ID 并重新填写 Hash 时正常保存成对凭据', async () => {
    const wrapper = mountModal()
    const idInput = await expandCredentials(wrapper)
    await idInput.setValue('222')
    await wrapper.find('input[id^="account-api-hash-"]').setValue('new-hash')

    await saveButton(wrapper).trigger('click')

    expect(apiMocks.updateAccount).toHaveBeenCalledTimes(1)
    const payload = apiMocks.updateAccount.mock.calls[0]?.[2] as Record<string, unknown>
    expect(payload.api_id).toBe('222')
    expect(payload.api_hash).toBe('new-hash')
  })
})
