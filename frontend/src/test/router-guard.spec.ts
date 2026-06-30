import { describe, expect, it, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../stores/auth'

// 模拟路由对象
const createMockRoute = (name: string | null) => ({ name, path: `/${name || ''}` })

describe('路由守卫逻辑', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  // 提取路由守卫核心逻辑为可测试函数
  const guardLogic = (to: { name: string | null }, authStore: ReturnType<typeof useAuthStore>) => {
    if (to.name !== 'login' && !authStore.token) {
      return { name: 'login' }
    } else if (to.name === 'login' && authStore.token) {
      if (authStore.isTokenExpired()) {
        authStore.clearToken()
        return { name: 'login' }
      }
      return { name: 'dashboard' }
    }
    return undefined
  }

  it('无 token 访问受保护页面 → 跳转 login', () => {
    const store = useAuthStore()
    const result = guardLogic(createMockRoute('dashboard'), store)
    expect(result).toEqual({ name: 'login' })
  })

  it('无 token 访问 login → 不拦截', () => {
    const store = useAuthStore()
    const result = guardLogic(createMockRoute('login'), store)
    expect(result).toBeUndefined()
  })

  it('有有效 token 访问 login → 跳转 dashboard', () => {
    const store = useAuthStore()
    // exp = 2126-06-30
    const payload = btoa(JSON.stringify({ exp: 4956508800 }))
    store.setToken(`header.${payload}.signature`)
    const result = guardLogic(createMockRoute('login'), store)
    expect(result).toEqual({ name: 'dashboard' })
  })

  it('有过期 token 访问 login → 清除 token 并留在 login', () => {
    const store = useAuthStore()
    // exp = 2020-01-01
    const payload = btoa(JSON.stringify({ exp: 1577836800 }))
    store.setToken(`header.${payload}.signature`)
    const result = guardLogic(createMockRoute('login'), store)
    expect(result).toEqual({ name: 'login' })
    expect(store.token).toBeNull()
  })

  it('有有效 token 访问受保护页面 → 不拦截', () => {
    const store = useAuthStore()
    const payload = btoa(JSON.stringify({ exp: 4956508800 }))
    store.setToken(`header.${payload}.signature`)
    const result = guardLogic(createMockRoute('settings'), store)
    expect(result).toBeUndefined()
  })

  it('无 token 访问根路径 → 跳转 login', () => {
    const store = useAuthStore()
    const result = guardLogic(createMockRoute(null), store)
    expect(result).toEqual({ name: 'login' })
  })
})
