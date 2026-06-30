import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useAuthStore } from '../stores/auth'

// mock fetch
const mockFetch = vi.fn()
vi.stubGlobal('fetch', mockFetch)

async function importApi() {
  return import('../lib/api')
}

describe('api.request - 401 处理', () => {
  beforeEach(() => {
    localStorage.clear()
    setActivePinia(createPinia())
    mockFetch.mockReset()
  })

  it('401 响应时清除 token 并跳转', async () => {
    const store = useAuthStore()
    store.setToken('expired-token')

    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ detail: 'Unauthorized' }),
    })

    const api = await importApi()
    await expect(api.listAccounts('expired-token')).rejects.toThrow('Unauthorized')

    expect(store.token).toBeNull()
    expect(window.location.href).toContain('/')
  })

  it('401 不匹配当前 token 时不清除', async () => {
    const store = useAuthStore()
    store.setToken('current-token')

    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 401,
      json: async () => ({ detail: 'Unauthorized' }),
    })

    const api = await importApi()
    await expect(api.listAccounts('old-token')).rejects.toThrow('Unauthorized')

    // token 未被清除（请求中的 token 与 store 不一致）
    expect(store.token).toBe('current-token')
  })

  it('非 401 错误不触发清除', async () => {
    const store = useAuthStore()
    store.setToken('valid-token')

    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 500,
      json: async () => ({ detail: 'Server Error' }),
    })

    const api = await importApi()
    await expect(api.listAccounts('valid-token')).rejects.toThrow('Server Error')

    expect(store.token).toBe('valid-token')
  })

  it('FastAPI 校验错误格式正确提取 msg', async () => {
    const store = useAuthStore()
    store.setToken('valid-token')

    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 422,
      json: async () => ({
        detail: [
          { loc: ['body', 'name'], msg: 'field required', type: 'value_error.missing' },
        ],
      }),
    })

    const api = await importApi()
    await expect(api.createSignTask('valid-token', {} as never)).rejects.toThrow('field required')
  })

  it('非 JSON 错误响应使用文本', async () => {
    const store = useAuthStore()
    store.setToken('valid-token')

    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 503,
      json: async () => { throw new Error('not json') },
      text: async () => 'Service Unavailable',
    })

    const api = await importApi()
    await expect(api.listAccounts('valid-token')).rejects.toThrow('Service Unavailable')
  })

  it('错误响应携带 status 和 code', async () => {
    const store = useAuthStore()
    store.setToken('valid-token')

    mockFetch.mockResolvedValueOnce({
      ok: false,
      status: 403,
      json: async () => ({ detail: 'Forbidden', code: 'INSUFFICIENT_PERMISSIONS' }),
    })

    const api = await importApi()
    try {
      await api.listAccounts('valid-token')
    } catch (e: unknown) {
      const err = e as { status?: number; code?: string }
      expect(err.status).toBe(403)
      expect(err.code).toBe('INSUFFICIENT_PERMISSIONS')
    }
  })
})
