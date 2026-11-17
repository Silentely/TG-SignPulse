import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import Login from '../views/Login.vue'
import { mockI18nPassthrough } from './composable-test-utils'

const mocks = vi.hoisted(() => ({
  login: vi.fn(), setToken: vi.fn(), replace: vi.fn().mockResolvedValue(undefined),
}))
vi.mock('../lib/api', () => ({ login: mocks.login }))
vi.mock('vue-router', () => ({ useRouter: () => ({ replace: mocks.replace }) }))
vi.mock('../stores/auth', () => ({ useAuthStore: () => ({
  isAuthenticated: false, isTokenExpired: () => true, setToken: mocks.setToken,
}) }))
vi.mock('../composables/useI18n', () => ({ useI18n: () => mockI18nPassthrough() }))
vi.mock('../composables/useTheme', () => ({ useTheme: () => ({ isDark: ref(false), toggleTheme: vi.fn() }) }))

const mounted: ReturnType<typeof mount>[] = []
function render() {
  const wrapper = mount(Login, { attachTo: document.body })
  mounted.push(wrapper)
  return wrapper
}
async function submitPassword(wrapper: ReturnType<typeof render>) {
  await wrapper.get('#login-username').setValue('admin')
  await wrapper.get('#login-password').setValue('password')
  await wrapper.get('form').trigger('submit')
  await flushPromises()
}
async function challenge() {
  mocks.login.mockResolvedValueOnce({ requires_totp: true })
  const wrapper = render()
  await submitPassword(wrapper)
  return wrapper
}
beforeEach(() => { mocks.login.mockReset() })
afterEach(() => { mounted.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('login TOTP steps', () => {
  it('enters a normal challenge without storing a token or navigating', async () => {
    const wrapper = await challenge()
    expect(wrapper.find('#login-totp').exists()).toBe(true)
    expect(document.activeElement).toBe(wrapper.get('#login-totp').element)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('[role="status"]').text()).toContain('login.totpRequired')
    expect(wrapper.get('button[type="submit"]').text()).toContain('login.verifyAndSignIn')
    expect(mocks.setToken).not.toHaveBeenCalled()
    expect(mocks.replace).not.toHaveBeenCalled()
  })

  it.each(['', '12345', 'abcdef', '１２３４５６'])('blocks incomplete or nonnumeric code %s', async code => {
    const wrapper = await challenge()
    await wrapper.get('#login-totp').setValue(code)
    expect((wrapper.get('button[type="submit"]').element as HTMLButtonElement).disabled).toBe(true)
    await wrapper.get('form').trigger('submit')
    expect(mocks.login).toHaveBeenCalledTimes(1)
  })

  it('submits a complete code then stores the token and navigates', async () => {
    const wrapper = await challenge()
    mocks.login.mockResolvedValueOnce({ access_token: 'verified-token', token_type: 'bearer' })
    await wrapper.get('#login-totp').setValue('123456')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(mocks.login).toHaveBeenLastCalledWith({ username: 'admin', password: 'password', totp_code: '123456' })
    expect(mocks.setToken).toHaveBeenCalledWith('verified-token')
    expect(mocks.replace).toHaveBeenCalledWith('/dashboard')
  })

  it('shows an invalid-code error and allows retry', async () => {
    const wrapper = await challenge()
    mocks.login.mockRejectedValueOnce(Object.assign(new Error('TOTP_INVALID'), { code: 'TOTP_INVALID' }))
    await wrapper.get('#login-totp').setValue('123456')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('login.totpInvalid')
    expect((wrapper.get('#login-totp').element as HTMLInputElement).selectionEnd).toBe(6)
    expect(mocks.setToken).not.toHaveBeenCalled()
  })

  it('returns to credentials and clears the previous code and error', async () => {
    const wrapper = await challenge()
    await wrapper.get('#login-totp').setValue('123456')
    mocks.login.mockRejectedValueOnce(new Error('TOTP_INVALID'))
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    await wrapper.get('[data-testid="login-back"]').trigger('click')
    expect(wrapper.find('#login-totp').exists()).toBe(false)
    expect(wrapper.get('button[type="submit"]').text()).toContain('login.nextStep')
    mocks.login.mockResolvedValueOnce({ requires_totp: true })
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect((wrapper.get('#login-totp').element as HTMLInputElement).value).toBe('')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(mocks.login).toHaveBeenLastCalledWith({ username: 'admin', password: 'password' })
  })

  it('still logs in without TOTP when a token is returned immediately', async () => {
    mocks.login.mockResolvedValueOnce({ access_token: 'password-token', token_type: 'bearer' })
    await submitPassword(render())
    expect(mocks.setToken).toHaveBeenCalledWith('password-token')
    expect(mocks.replace).toHaveBeenCalledWith('/dashboard')
  })

  it('supports the legacy backend challenge and invalid-code response', async () => {
    mocks.login.mockRejectedValueOnce(new Error('TOTP_REQUIRED_OR_INVALID'))
    const wrapper = render()
    await submitPassword(wrapper)
    expect(document.activeElement).toBe(wrapper.get('#login-totp').element)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(mocks.setToken).not.toHaveBeenCalled()

    mocks.login.mockRejectedValueOnce(new Error('TOTP_REQUIRED_OR_INVALID'))
    await wrapper.get('#login-totp').setValue('123456')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('login.totpInvalid')
    expect(mocks.replace).not.toHaveBeenCalled()
  })

  it('prevents duplicate submissions and going back while verification is pending', async () => {
    const wrapper = await challenge()
    let finish!: (response: { access_token: string; token_type: string }) => void
    mocks.login.mockReturnValueOnce(new Promise(resolve => { finish = resolve }))
    await wrapper.get('#login-totp').setValue('123456')
    await wrapper.get('form').trigger('submit')
    expect((wrapper.get('#login-totp').element as HTMLInputElement).disabled).toBe(true)
    expect((wrapper.get('[data-testid="login-back"]').element as HTMLButtonElement).disabled).toBe(true)
    await wrapper.get('form').trigger('submit')
    await wrapper.get('[data-testid="login-back"]').trigger('click')
    expect(mocks.login).toHaveBeenCalledTimes(2)
    expect(wrapper.find('#login-totp').exists()).toBe(true)
    finish({ access_token: 'verified-token', token_type: 'bearer' })
    await flushPromises()
    expect(mocks.setToken).toHaveBeenCalledOnce()
  })

  it('allows retry after a network failure and returning to change credentials', async () => {
    const wrapper = await challenge()
    mocks.login.mockRejectedValueOnce(new Error('NETWORK_ERROR'))
    await wrapper.get('#login-totp').setValue('123456')
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)
    expect((wrapper.get('button[type="submit"]').element as HTMLButtonElement).disabled).toBe(false)
    await wrapper.get('[data-testid="login-back"]').trigger('click')
    expect(document.activeElement).toBe(wrapper.get('#login-username').element)
    await wrapper.get('#login-username').setValue('another-admin')
    await wrapper.get('#login-password').setValue('another-password')
    mocks.login.mockResolvedValueOnce({ access_token: 'another-token', token_type: 'bearer' })
    await wrapper.get('form').trigger('submit')
    await flushPromises()
    expect(mocks.login).toHaveBeenLastCalledWith({ username: 'another-admin', password: 'another-password' })
    expect(mocks.setToken).toHaveBeenCalledWith('another-token')
  })
})
