import { describe, it, expect } from 'vitest'
import { canKeepExistingHash, validateAccountApiCredentials } from '../lib/api-credentials'

describe('validateAccountApiCredentials', () => {
  it('accepts both fields blank (inherit global config)', () => {
    expect(validateAccountApiCredentials('', '')).toEqual({
      valid: true,
      missing: null,
      error: null,
    })
    expect(validateAccountApiCredentials('  ', '  ').valid).toBe(true)
    expect(validateAccountApiCredentials(null, null).valid).toBe(true)
  })

  it('accepts a complete pair and trims whitespace', () => {
    expect(
      validateAccountApiCredentials(' 123456 ', ' abcdef0123456789 '),
    ).toEqual({ valid: true, missing: null, error: null })
  })

  it('rejects a lone api_id and points at the hash field', () => {
    expect(validateAccountApiCredentials('123456', '')).toEqual({
      valid: false,
      missing: 'api_hash',
      error: 'pair',
    })
  })

  it('rejects a lone api_hash and points at the id field', () => {
    expect(validateAccountApiCredentials('', 'abcdef')).toEqual({
      valid: false,
      missing: 'api_id',
      error: 'pair',
    })
  })

  it('allows an existing hash to be kept when the account already has one', () => {
    expect(
      validateAccountApiCredentials('123456', '', {
        canKeepExistingHash: true,
      }),
    ).toEqual({ valid: true, missing: null, error: null })
  })

  it('rejects malformed api_id values', () => {
    for (const bad of ['0', '-1', 'abc', '1.5', '1e3']) {
      expect(validateAccountApiCredentials(bad, 'hash')).toEqual({
        valid: false,
        missing: 'api_id',
        error: 'id',
      })
    }
  })

  it('validates the api_id format before allowing a saved hash to be kept', () => {
    expect(
      validateAccountApiCredentials('abc', '', { canKeepExistingHash: true }),
    ).toEqual({ valid: false, missing: 'api_id', error: 'id' })
  })
})

describe('canKeepExistingHash', () => {
  const base = {
    isExistingAccount: true,
    hasExistingHash: true,
    apiId: '111',
    savedApiId: '111',
  }

  it('allows reuse only when the api id is unchanged', () => {
    expect(canKeepExistingHash(base)).toBe(true)
    expect(canKeepExistingHash({ ...base, apiId: ' 111 ' })).toBe(true)
  })

  it('blocks reuse when the api id changed', () => {
    expect(canKeepExistingHash({ ...base, apiId: '222' })).toBe(false)
  })

  it('blocks reuse for a hash-only saved record without an api id', () => {
    expect(canKeepExistingHash({ ...base, savedApiId: '' })).toBe(false)
    expect(canKeepExistingHash({ ...base, savedApiId: undefined })).toBe(false)
  })

  it('blocks reuse when not an existing account or no saved hash', () => {
    expect(canKeepExistingHash({ ...base, isExistingAccount: false })).toBe(false)
    expect(canKeepExistingHash({ ...base, hasExistingHash: false })).toBe(false)
  })
})
