import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import DeviceManagerModal from '../components/accounts/DeviceManagerModal.vue'
import * as api from '../lib/api'
import * as coreApi from '../lib/api/core'

const mockConfirm = vi.fn()

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({
    t: (k: string) => k,
  }),
}))

vi.mock('../composables/useConfirm', () => ({
  useConfirm: () => ({
    confirm: mockConfirm,
  }),
}))

describe('DeviceManagerModal', () => {
  beforeEach(() => {
    document.body.innerHTML = ''
    vi.clearAllMocks()
    vi.spyOn(coreApi, 'getAuthToken').mockReturnValue('mock-token')
    vi.spyOn(api, 'listAccountDevices').mockResolvedValue({
      devices: [
        {
          hash: '111',
          current: true,
          official_app: true,
          password_pending: false,
          device_model: 'MacBook Pro',
          platform: 'macOS',
          system_version: '14.0',
          app_name: 'Telegram macOS',
          app_version: '10.5',
          ip: '1.1.1.1',
          country: 'US',
          region: 'CA',
        },
        {
          hash: '222',
          current: false,
          official_app: false,
          password_pending: false,
          device_model: 'Pixel 8',
          platform: 'Android',
          system_version: '14',
          app_name: 'TG-SignPulse',
          app_version: '1.0',
          ip: '2.2.2.2',
          country: 'SG',
          region: 'SG',
        },
      ],
      total: 2,
    })
    vi.spyOn(api, 'listAccountOfficialMessages').mockResolvedValue({
      messages: [
        {
          id: 100,
          date: '2026-09-19T00:00:00Z',
          text: 'We detected a login to your account from a new device',
          outgoing: false,
        },
      ],
      total: 1,
    })
    vi.spyOn(api, 'resetOtherDevices').mockResolvedValue({
      success: true,
      message: '已成功清退其他设备',
    })
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('loads devices and official messages when opened', async () => {
    const wrapper = mount(DeviceManagerModal, {
      props: {
        isOpen: true,
        accountName: 'test-account',
      },
      attachTo: document.body,
    })

    await flushPromises()

    expect(api.listAccountDevices).toHaveBeenCalledWith('mock-token', 'test-account')
    expect(api.listAccountOfficialMessages).toHaveBeenCalledWith('mock-token', 'test-account', 10)
    expect(document.body.textContent).toContain('MacBook Pro')
    expect(document.body.textContent).toContain('Pixel 8')
    expect(document.body.textContent).toContain('We detected a login')

    wrapper.unmount()
  })

  it('handles reset other sessions when confirmed', async () => {
    mockConfirm.mockResolvedValue(true)

    const wrapper = mount(DeviceManagerModal, {
      props: {
        isOpen: true,
        accountName: 'test-account',
      },
      attachTo: document.body,
    })

    await flushPromises()

    const buttons = Array.from(document.body.querySelectorAll('button'))
    const resetBtn = buttons.find((b) => (b.textContent || '').includes('accounts.resetOtherDevices'))
    expect(resetBtn).toBeDefined()

    resetBtn!.click()

    expect(mockConfirm).toHaveBeenCalledWith(
      expect.objectContaining({
        title: 'accounts.resetOtherDevicesConfirmTitle',
        message: 'accounts.resetOtherDevicesConfirm',
        confirmText: 'accounts.resetOtherDevices',
        danger: true,
      })
    )

    await flushPromises()

    expect(api.resetOtherDevices).toHaveBeenCalledWith('mock-token', 'test-account')
    // Should re-fetch both devices and official messages
    expect(api.listAccountDevices).toHaveBeenCalledTimes(2)
    expect(api.listAccountOfficialMessages).toHaveBeenCalledTimes(2)
    expect(wrapper.emitted('reset-others')).toBeTruthy()
    expect(document.body.textContent).toContain('已成功清退其他设备')

    wrapper.unmount()
  })

  it('does not reset other sessions when cancel clicked in dialog', async () => {
    mockConfirm.mockResolvedValue(false)

    const wrapper = mount(DeviceManagerModal, {
      props: {
        isOpen: true,
        accountName: 'test-account',
      },
      attachTo: document.body,
    })

    await flushPromises()

    const buttons = Array.from(document.body.querySelectorAll('button'))
    const resetBtn = buttons.find((b) => (b.textContent || '').includes('accounts.resetOtherDevices'))
    resetBtn!.click()

    await flushPromises()

    expect(api.resetOtherDevices).not.toHaveBeenCalled()
    expect(wrapper.emitted('reset-others')).toBeFalsy()

    wrapper.unmount()
  })
})
