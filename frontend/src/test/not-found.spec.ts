import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import NotFound from '../views/NotFound.vue'
import { useAuthStore } from '../stores/auth'
import { mockI18nPassthrough } from './composable-test-utils'

const pushMock = vi.fn()
const backMock = vi.fn()
vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: pushMock,
    back: backMock,
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
    backMock.mockClear()
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

  it('组件挂载时同步更新网页标题 document.title', () => {
    mount(NotFound)
    expect(document.title).toBe('404 notFound.title - TG-SignPulse')
  })

  it('当存在浏览历史时支持点击返回上一页', async () => {
    Object.defineProperty(window.history, 'length', {
      value: 3,
      configurable: true,
    })
    const wrapper = mount(NotFound)
    const backBtn = wrapper.find('button.ui-btn-secondary')
    expect(backBtn.exists()).toBe(true)
    expect(backBtn.text()).toContain('notFound.goBack')

    await backBtn.trigger('click')
    expect(backMock).toHaveBeenCalled()
  })
})
