/**
 * safe-storage 容错：存储不可用（SecurityError）时读回退 null、写静默跳过。
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  storageGet,
  storageSet,
  storageRemove,
  storageGetJSON,
  storageSetJSON,
  sessionGet,
  sessionSet,
  sessionRemove,
} from '../lib/safe-storage'

describe('safe-storage', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('正常环境读写删透传', () => {
    storageSet('k1', 'v1')
    expect(storageGet('k1')).toBe('v1')
    storageRemove('k1')
    expect(storageGet('k1')).toBeNull()
  })

  it('localStorage 抛错时读回退 null、写删不抛出', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })

    expect(storageGet('k1')).toBeNull()
    expect(() => storageSet('k1', 'v')).not.toThrow()
    expect(() => storageRemove('k1')).not.toThrow()
  })

  it('JSON 读写与回退', () => {
    storageSetJSON('json_key', { count: 42, text: 'hello' })
    expect(storageGetJSON('json_key')).toEqual({ count: 42, text: 'hello' })
    expect(storageGetJSON('missing_key', { fallback: true })).toEqual({ fallback: true })

    // Corrupted JSON
    storageSet('bad_json', '{not-json')
    expect(storageGetJSON('bad_json', null)).toBeNull()
  })

  it('sessionStorage 读写删容错', () => {
    sessionSet('s1', 'v1')
    expect(sessionGet('s1')).toBe('v1')
    sessionRemove('s1')
    expect(sessionGet('s1')).toBeNull()
  })
})
