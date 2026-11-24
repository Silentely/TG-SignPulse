import { describe, it, expect } from 'vitest'
import { validateAccountApiCredentials } from '../lib/api-credentials'

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
})
