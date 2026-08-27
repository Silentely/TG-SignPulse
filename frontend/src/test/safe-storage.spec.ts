/**
 * safe-storage 容错：存储不可用（SecurityError）时读回退 null、写静默跳过。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { storageGet, storageSet, storageRemove } from '../lib/safe-storage'

describe('safe-storage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('正常环境读写删透传', () => {
    storageSet('k1', 'v1')
    expect(storageGet('k1')).toBe('v1')
    storageRemove('k1')
    expect(storageGet('k1')).toBeNull()
  })

  it('localStorage 抛错时读回退 null、写删不抛出', () => {
    const broken = {
      getItem: () => { throw new DOMException('denied', 'SecurityError') },
      setItem: () => { throw new DOMException('denied', 'SecurityError') },
      removeItem: () => { throw new DOMException('denied', 'SecurityError') },
    }
    vi.stubGlobal('localStorage', broken)
    expect(storageGet('k1')).toBeNull()
    expect(() => storageSet('k1', 'v')).not.toThrow()
    expect(() => storageRemove('k1')).not.toThrow()
  })
})
