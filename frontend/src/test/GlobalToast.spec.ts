import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

const toastState = vi.hoisted(() => ({
  toasts: [{ id: 1, message: '消息内容', type: 'info' }],
  dismiss: vi.fn(),
  pause: vi.fn(),
  resume: vi.fn(),
}))

vi.mock('../composables/useToast', () => ({
  useToast: () => toastState,
}))
vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

import GlobalToast from '../components/GlobalToast.vue'

describe('GlobalToast', () => {
  it('keeps toast announcements atomic and resumes after a cancelled touch', async () => {
    const wrapper = mount(GlobalToast, {
      global: {
        stubs: { Teleport: true },
      },
    })
    const toast = wrapper.find('[role="status"]')

    expect(toast.attributes('aria-live')).toBe('polite')
    expect(toast.attributes('aria-atomic')).toBe('true')

    await toast.trigger('touchstart')
    await toast.trigger('touchcancel')

    expect(toastState.pause).toHaveBeenCalledWith(1)
    expect(toastState.resume).toHaveBeenCalledWith(1)

    const closeButton = toast.find('button')
    expect(closeButton.classes()).toContain('focus-visible:opacity-100')
    expect(closeButton.classes()).toContain('focus-visible:ring-2')

    wrapper.unmount()
  })
})
