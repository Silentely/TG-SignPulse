/**
 * AvatarUrlCache：ObjectURL 复用与回收行为。
 */
import { describe, expect, it, vi, afterEach } from 'vitest'
import { AvatarUrlCache } from '../lib/avatar-cache'

describe('AvatarUrlCache', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('复用已缓存 URL，替换时回收旧引用', () => {
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const cache = new AvatarUrlCache()

    expect(cache.get('acc-1')).toBeUndefined()
    cache.set('acc-1', 'blob:a')
    expect(cache.get('acc-1')).toBe('blob:a')

    // 同账号新 URL：旧 blob 被回收
    cache.set('acc-1', 'blob:b')
    expect(revoke).toHaveBeenCalledWith('blob:a')
    expect(cache.get('acc-1')).toBe('blob:b')

    // 相同 URL 重复登记不重复回收
    cache.set('acc-1', 'blob:b')
    expect(revoke).toHaveBeenCalledTimes(1)
  })

  it('release 回收全部 URL 并清空缓存', () => {
    const revoke = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const cache = new AvatarUrlCache()
    cache.set('acc-1', 'blob:a')
    cache.set('acc-2', 'blob:b')

    cache.release()
    expect(revoke).toHaveBeenCalledWith('blob:a')
    expect(revoke).toHaveBeenCalledWith('blob:b')
    expect(cache.get('acc-1')).toBeUndefined()
    expect(cache.get('acc-2')).toBeUndefined()
  })

  it('release 后再次使用可重新登记', () => {
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    const cache = new AvatarUrlCache()
    cache.set('acc-1', 'blob:a')
    cache.release()
    cache.set('acc-1', 'blob:c')
    expect(cache.get('acc-1')).toBe('blob:c')
  })
})
