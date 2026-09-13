import { describe, expect, it, vi } from 'vitest'
import { resolveAuthRedirect } from '../lib/auth-guard'
import type { AuthLike } from '../lib/auth-guard'

function makeAuth(overrides: Partial<AuthLike> = {}): AuthLike {
  return {
    token: null,
    isTokenExpired: () => false,
    clearToken: vi.fn(),
    ...overrides,
  }
}

describe('resolveAuthRedirect 纯函数', () => {
  it('无 token 访问 dashboard → login', () => {
    expect(resolveAuthRedirect('dashboard', makeAuth())).toEqual({ name: 'login' })
  })

  it('过期 token 会调用 clearToken', () => {
    const clearToken = vi.fn()
    const auth = makeAuth({
      token: 'x.y.z',
      isTokenExpired: () => true,
      clearToken,
    })
    expect(resolveAuthRedirect('tasks', auth)).toEqual({ name: 'login' })
    expect(clearToken).toHaveBeenCalled()
  })

  it('有效 token 访问 login → dashboard', () => {
    const auth = makeAuth({
      token: 'valid',
      isTokenExpired: () => false,
    })
    expect(resolveAuthRedirect('login', auth)).toEqual({ name: 'dashboard' })
  })

  it('访问 not-found 放行（不论是否已登录）', () => {
    expect(resolveAuthRedirect('not-found', makeAuth())).toBeUndefined()

    const clearToken = vi.fn()
    const expiredAuth = makeAuth({
      token: 'expired.jwt',
      isTokenExpired: () => true,
      clearToken,
    })
    expect(resolveAuthRedirect('not-found', expiredAuth)).toBeUndefined()
    expect(clearToken).toHaveBeenCalled()
  })
})
