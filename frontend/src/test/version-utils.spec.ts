import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearCachedUpdateCheck,
  fetchGithubLatestRelease,
  isUpdateAvailable,
  loadCachedUpdateCheck,
  normalizeVersion,
  safeHttpUrl,
  saveCachedUpdateCheck,
} from '../lib/version-utils'

describe('version-utils', () => {
  beforeEach(() => {
    clearCachedUpdateCheck()
  })

  it('normalizeVersion strips v prefix', () => {
    expect(normalizeVersion('v2.1.0')).toBe('2.1.0')
    expect(normalizeVersion('  V1.0.0 ')).toBe('1.0.0')
  })

  it('isUpdateAvailable compares semver', () => {
    expect(isUpdateAvailable('2.0.0', '2.1.0')).toBe(true)
    expect(isUpdateAvailable('2.1.0', '2.1.0')).toBe(false)
    expect(isUpdateAvailable('2.2.0', '2.1.0')).toBe(false)
    expect(isUpdateAvailable('v2.0.0', 'v2.0.1')).toBe(true)
  })

  it('localStorage cache roundtrip', () => {
    saveCachedUpdateCheck({
      latest_version: '2.1.0',
      latest_url: 'https://example.com',
      update_available: true,
      checked_at: new Date().toISOString(),
      error: null,
    })
    const loaded = loadCachedUpdateCheck()
    expect(loaded?.latest_version).toBe('2.1.0')
    expect(loaded?.update_available).toBe(true)
  })

  it('expired cache returns null', () => {
    const old = Date.now() - 25 * 60 * 60 * 1000
    localStorage.setItem(
      'tg_signpulse_update_check_v1',
      JSON.stringify({
        saved_at: old,
        payload: {
          latest_version: '9.0.0',
          latest_url: null,
          update_available: true,
          checked_at: new Date(old).toISOString(),
          error: null,
        },
      }),
    )
    expect(loadCachedUpdateCheck()).toBeNull()
  })

  it('fetchGithubLatestRelease parses tag', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        tag_name: 'v3.0.0',
        html_url: 'https://github.com/Silentely/TG-SignPulse/releases/tag/v3.0.0',
      }),
    })
    vi.stubGlobal('fetch', mockFetch)
    const result = await fetchGithubLatestRelease()
    expect(result.version).toBe('3.0.0')
    expect(result.url).toContain('releases')
  })

  it('fetchGithubLatestRelease throws on non-ok', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 403, json: async () => ({}) }),
    )
    await expect(fetchGithubLatestRelease()).rejects.toThrow()
  })

  it('safeHttpUrl allows only http(s)', () => {
    expect(safeHttpUrl('https://example.com/a')).toBe('https://example.com/a')
    expect(safeHttpUrl('http://example.com/a')).toBe('http://example.com/a')
    expect(safeHttpUrl('javascript:alert(1)')).toBeNull()
    expect(safeHttpUrl('data:text/html,hi')).toBeNull()
    expect(safeHttpUrl(null)).toBeNull()
  })

  it('fetchGithubLatestRelease drops unsafe html_url', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({
          tag_name: 'v1.0.0',
          html_url: 'javascript:alert(1)',
        }),
      }),
    )
    const result = await fetchGithubLatestRelease()
    expect(result.version).toBe('1.0.0')
    expect(result.url).toBeNull()
  })
})
