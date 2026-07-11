import { describe, expect, it, beforeEach } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../stores/auth'
import { resolveAuthRedirect } from '../lib/auth-guard'

describe('路由守卫逻辑 (resolveAuthRedirect)', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('无 token 访问受保护页面 → 跳转 login', () => {
    const store = useAuthStore()
    expect(resolveAuthRedirect('dashboard', store)).toEqual({ name: 'login' })
  })

  it('无 token 访问 login → 不拦截', () => {
    const store = useAuthStore()
    expect(resolveAuthRedirect('login', store)).toBeUndefined()
  })

  it('有有效 token 访问 login → 跳转 dashboard', () => {
    const store = useAuthStore()
    const payload = btoa(JSON.stringify({ exp: 4956508800 }))
    store.setToken(`header.${payload}.signature`)
    expect(resolveAuthRedirect('login', store)).toEqual({ name: 'dashboard' })
  })

  it('有过期 token 访问 login → 清除 token 并留在 login', () => {
    const store = useAuthStore()
    const payload = btoa(JSON.stringify({ exp: 1577836800 }))
    store.setToken(`header.${payload}.signature`)
    expect(resolveAuthRedirect('login', store)).toBeUndefined()
    expect(store.token).toBeNull()
  })

  it('有有效 token 访问受保护页面 → 不拦截', () => {
    const store = useAuthStore()
    const payload = btoa(JSON.stringify({ exp: 4956508800 }))
    store.setToken(`header.${payload}.signature`)
    expect(resolveAuthRedirect('settings', store)).toBeUndefined()
  })

  it('有过期 token 访问受保护页面 → 清除并跳转 login', () => {
    const store = useAuthStore()
    const payload = btoa(JSON.stringify({ exp: 1577836800 }))
    store.setToken(`header.${payload}.signature`)
    expect(resolveAuthRedirect('dashboard', store)).toEqual({ name: 'login' })
    expect(store.token).toBeNull()
  })

  it('无 token 访问根路径 (name null) → 跳转 login', () => {
    const store = useAuthStore()
    expect(resolveAuthRedirect(null, store)).toEqual({ name: 'login' })
  })
})
