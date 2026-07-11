/**
 * 路由鉴权决策（纯函数，便于单测与 router 共用）。
 */
export type AuthLike = {
  token: string | null
  isTokenExpired: () => boolean
  clearToken: () => void
}

export type GuardResult = { name: 'login' | 'dashboard' } | undefined

/**
 * 根据目标路由与 auth 状态返回重定向目标。
 * - 未登录 / token 过期 → login
 * - 已登录访问 login → dashboard
 * - 其余 → 放行 (undefined)
 */
export function resolveAuthRedirect(
  toName: string | null | undefined,
  auth: AuthLike,
): GuardResult {
  const isLogin = toName === 'login'

  // 受保护路由：无 token 或已过期
  if (!isLogin) {
    if (!auth.token || auth.isTokenExpired()) {
      if (auth.token) auth.clearToken()
      return { name: 'login' }
    }
    return undefined
  }

  // 登录页：有效 token 则进仪表盘；过期则清掉并留在登录页
  if (auth.token) {
    if (auth.isTokenExpired()) {
      auth.clearToken()
      return undefined
    }
    return { name: 'dashboard' }
  }

  return undefined
}
