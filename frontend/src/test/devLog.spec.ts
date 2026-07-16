import { describe, expect, it, vi } from 'vitest'
import { devLog } from '../lib/devLog'

describe('devLog', () => {
  it('error/warn/info 可调用且不抛异常', () => {
    const err = vi.spyOn(console, 'error').mockImplementation(() => {})
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    const info = vi.spyOn(console, 'info').mockImplementation(() => {})
    expect(() => devLog.error('e', { a: 1 })).not.toThrow()
    expect(() => devLog.warn('w')).not.toThrow()
    expect(() => devLog.info('i')).not.toThrow()
    // vitest 默认 DEV=true，应会输出
    expect(err).toHaveBeenCalled()
    err.mockRestore()
    warn.mockRestore()
    info.mockRestore()
  })
})
