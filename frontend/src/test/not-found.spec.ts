import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import NotFound from '../views/NotFound.vue'
import { useAuthStore } from '../stores/auth'
import { mockI18nPassthrough } from './composable-test-utils'

const pushMock = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: pushMock,
  }),
}))

vi.mock('../composables/useI18n', () => ({
  useI18n: () => mockI18nPassthrough(),
}))

describe('NotFound.vue 404 页面', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    pushMock.mockClear()
  })

  it('未登录状态下展示前往登录文案并导航至 /login', async () => {
    const wrapper = mount(NotFound)
    expect(wrapper.text()).toContain('404')
    expect(wrapper.text()).toContain('notFound.title')
    expect(wrapper.text()).toContain('notFound.goToLogin')

    const actionBtn = wrapper.find('button.ui-btn-primary')
    expect(actionBtn.exists()).toBe(true)
    await actionBtn.trigger('click')

    expect(pushMock).toHaveBeenCalledWith('/login')
  })

  it('有效登录状态下展示返回控制台文案并导航至 /dashboard', async () => {
    const authStore = useAuthStore()
    const payload = btoa(JSON.stringify({ exp: 4956508800 }))
    authStore.setToken(`header.${payload}.signature`)

    const wrapper = mount(NotFound)
    expect(wrapper.text()).toContain('404')
    expect(wrapper.text()).toContain('notFound.backHome')

    const actionBtn = wrapper.find('button.ui-btn-primary')
    await actionBtn.trigger('click')

    expect(pushMock).toHaveBeenCalledWith('/dashboard')
  })

  it('点击 GitHub 按钮打开项目主页', async () => {
    const openSpy = vi.spyOn(window, 'open').mockImplementation(() => null)
    const wrapper = mount(NotFound)

    const githubBtn = wrapper.find('button[title="common.github"]')
    expect(githubBtn.exists()).toBe(true)
    await githubBtn.trigger('click')

    expect(openSpy).toHaveBeenCalledWith('https://github.com/Silentely/TG-SignPulse', '_blank')
    openSpy.mockRestore()
  })
})
