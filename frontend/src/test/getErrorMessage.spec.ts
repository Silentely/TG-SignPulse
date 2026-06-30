import { describe, expect, it } from 'vitest'
import { getErrorMessage } from '../lib/types'

describe('getErrorMessage', () => {
  it('返回 Error 对象的 message', () => {
    expect(getErrorMessage(new Error('network failed'))).toBe('network failed')
  })

  it('直接返回 string', () => {
    expect(getErrorMessage('plain string error')).toBe('plain string error')
  })

  it('序列化 object 为 JSON', () => {
    expect(getErrorMessage({ code: 42, detail: 'bad input' })).toBe('{"code":42,"detail":"bad input"}')
  })

  it('空 object 返回序列化结果', () => {
    expect(getErrorMessage({})).toBe('{}')
  })

  it('null 返回 Unknown error', () => {
    expect(getErrorMessage(null)).toBe('Unknown error')
  })

  it('undefined 返回 Unknown error', () => {
    expect(getErrorMessage(undefined)).toBe('Unknown error')
  })

  it('number 返回 Unknown error', () => {
    expect(getErrorMessage(42)).toBe('Unknown error')
  })

  it('Error 子类（TypeError）正确提取 message', () => {
    expect(getErrorMessage(new TypeError('invalid type'))).toBe('invalid type')
  })

  it('空字符串返回空字符串', () => {
    expect(getErrorMessage('')).toBe('')
  })
})
