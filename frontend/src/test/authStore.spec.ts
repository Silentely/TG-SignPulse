import { beforeEach, describe, expect, it } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useAuthStore } from '../stores/auth'

describe('authStore', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
  })

  it('初始 token 从 localStorage 读取', () => {
    localStorage.setItem('tg-signer-token', 'stored-token')
    const store = useAuthStore()
    expect(store.token).toBe('stored-token')
  })

  it('初始无 token 时为 null', () => {
    const store = useAuthStore()
    expect(store.token).toBeNull()
  })

  it('setToken 同步更新 Store 和 localStorage', () => {
    const store = useAuthStore()
    store.setToken('new-token')
    expect(store.token).toBe('new-token')
    expect(localStorage.getItem('tg-signer-token')).toBe('new-token')
  })

  it('clearToken 同步清除 Store 和 localStorage', () => {
    const store = useAuthStore()
    store.setToken('to-clear')
    store.clearToken()
    expect(store.token).toBeNull()
    expect(localStorage.getItem('tg-signer-token')).toBeNull()
  })

  it('isAuthenticated 跟随 token 变化', () => {
    const store = useAuthStore()
    expect(store.isAuthenticated).toBe(false)
    store.setToken('valid')
    expect(store.isAuthenticated).toBe(true)
    store.clearToken()
    expect(store.isAuthenticated).toBe(false)
  })

  describe('isTokenExpired', () => {
    it('无 token 返回 true', () => {
      const store = useAuthStore()
      expect(store.isTokenExpired()).toBe(true)
    })

    it('有效 token 返回 false', () => {
      const store = useAuthStore()
      // exp = 2126-06-30 (未来时间)
      const payload = btoa(JSON.stringify({ exp: 4956508800 }))
      store.setToken(`header.${payload}.signature`)
      expect(store.isTokenExpired()).toBe(false)
    })

    it('过期 token 返回 true', () => {
      const store = useAuthStore()
      // exp = 2020-01-01
      const payload = btoa(JSON.stringify({ exp: 1577836800 }))
      store.setToken(`header.${payload}.signature`)
      expect(store.isTokenExpired()).toBe(true)
    })

    it('格式错误的 token 返回 false（让服务端拒绝）', () => {
      const store = useAuthStore()
      store.setToken('malformed-token')
      expect(store.isTokenExpired()).toBe(false)
    })

    it('无 exp 字段的 token 返回 falsy（让服务端决定）', () => {
      const store = useAuthStore()
      const payload = btoa(JSON.stringify({ sub: 'user1' }))
      store.setToken(`header.${payload}.signature`)
      expect(store.isTokenExpired()).toBeFalsy()
    })
  })
})
