import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import AddAccountModal from '../components/accounts/AddAccountModal.vue'

const api = vi.hoisted(() => ({
  startAccountLogin: vi.fn(),
  verifyAccountLogin: vi.fn(),
  updateAccount: vi.fn(),
  startQrLogin: vi.fn(),
  getQrLoginStatus: vi.fn(),
  submitQrPassword: vi.fn(),
  cancelQrLogin: vi.fn(),
  importAccountSession: vi.fn(),
  importAccountSessionFile: vi.fn(),
}))

vi.mock('../lib/api', () => api)
vi.mock('../lib/api/core', () => ({ getAuthToken: () => 'tok' }))
vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))
vi.mock('../composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn() }),
}))

const ModalStub = defineComponent({
  name: 'Modal',
  emits: ['close', 'closed'],
  template: '<div><slot /><slot name="footer" /></div>',
})

const mountModal = async (props: Record<string, unknown> = {}) => {
  const wrapper = mount(AddAccountModal, {
    props: { isOpen: false, initialMethod: 'code', ...props },
    global: { stubs: { Modal: ModalStub } },
  })
  await wrapper.setProps({ isOpen: true })
  await wrapper.find('#add-account-phone').setValue('+10000000000')
  return wrapper
}

const sendCodeButton = (wrapper: Awaited<ReturnType<typeof mountModal>>) => {
  const btn = wrapper
    .findAll('button')
    .find((b) => b.text().includes('addAccount.getCode'))
  if (!btn) throw new Error('send code button not found')
  return btn
}

describe('AddAccountModal 重新登录凭据下发', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.startAccountLogin.mockResolvedValue({ phone_code_hash: 'pch' })
  })

  it('保留已保存凭据时不下发 api_id/api_hash', async () => {
    const wrapper = await mountModal({
      reloginMode: true,
      initialAccountName: 'acc',
      initialApiId: '111',
      savedApiId: '111',
      initialHasApiHash: true,
      initialHasCustomApi: true,
    })

    await sendCodeButton(wrapper).trigger('click')

    expect(api.startAccountLogin).toHaveBeenCalledTimes(1)
    const payload = api.startAccountLogin.mock.calls[0]?.[1] as Record<string, unknown>
    expect(payload.account_name).toBe('acc')
    expect(payload).not.toHaveProperty('api_id')
    expect(payload).not.toHaveProperty('api_hash')
  })

  it('未保存过 API ID 时，编辑草稿不能当作可沿用的 baseline', async () => {
    const wrapper = await mountModal({
      reloginMode: true,
      initialAccountName: 'acc',
      initialApiId: '222',
      savedApiId: '',
      initialHasApiHash: true,
      initialHasCustomApi: true,
    })

    await sendCodeButton(wrapper).trigger('click')

    expect(api.startAccountLogin).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('accountApi.reloginPairRequired')
  })

  it('改动 API ID 并补齐 Hash 时成对下发', async () => {
    const wrapper = await mountModal({
      reloginMode: true,
      initialAccountName: 'acc',
      initialApiId: '111',
      savedApiId: '111',
      initialHasApiHash: true,
      initialHasCustomApi: true,
    })
    await wrapper.find('button[aria-controls]').trigger('click')
    await wrapper.find('input[id^="account-api-id-"]').setValue('333')
    await wrapper.find('input[id^="account-api-hash-"]').setValue('new-hash')

    await sendCodeButton(wrapper).trigger('click')

    expect(api.startAccountLogin).toHaveBeenCalledTimes(1)
    const payload = api.startAccountLogin.mock.calls[0]?.[1] as Record<string, unknown>
    expect(payload.api_id).toBe('333')
    expect(payload.api_hash).toBe('new-hash')
  })
})
