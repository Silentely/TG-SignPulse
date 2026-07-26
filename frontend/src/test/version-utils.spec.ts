import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearCachedUpdateCheck,
  fetchGithubLatestRelease,
  fetchGithubLatestReleaseViaRedirect,
  friendlyGithubError,
  isUpdateAvailable,
  loadCachedUpdateCheck,
  normalizeVersion,
  safeHttpUrl,
  saveCachedUpdateCheck,
  tagFromReleaseUrl,
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

  it('fetchGithubLatestRelease prefers HTML redirect (no API)', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      url: 'https://github.com/Silentely/TG-SignPulse/releases/tag/v3.0.0',
      headers: { get: () => null },
    })
    vi.stubGlobal('fetch', mockFetch)
    const result = await fetchGithubLatestRelease()
    expect(result.version).toBe('3.0.0')
    expect(result.url).toContain('releases')
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(String(mockFetch.mock.calls[0][0])).toContain('github.com')
    expect(String(mockFetch.mock.calls[0][0])).not.toContain('api.github.com')
  })

  it('fetchGithubLatestRelease falls back to API when HTML fails', async () => {
    const mockFetch = vi
      .fn()
      // HTML 无法解析 tag
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        url: 'https://github.com/Silentely/TG-SignPulse/releases/latest',
        headers: { get: () => null },
      })
      // API JSON 成功
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({
          tag_name: 'v3.1.0',
          html_url:
            'https://github.com/Silentely/TG-SignPulse/releases/tag/v3.1.0',
        }),
      })
    vi.stubGlobal('fetch', mockFetch)
    const result = await fetchGithubLatestRelease()
    expect(result.version).toBe('3.1.0')
    expect(mockFetch).toHaveBeenCalledTimes(2)
  })

  it('fetchGithubLatestRelease throws when HTML and API both fail', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn()
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          url: 'https://github.com/Silentely/TG-SignPulse/releases/latest',
          headers: { get: () => null },
        })
        .mockResolvedValueOnce({
          ok: false,
          status: 403,
          json: async () => ({}),
        }),
    )
    await expect(fetchGithubLatestRelease()).rejects.toThrow(/HTTP 403/)
  })

  it('tagFromReleaseUrl extracts tag', () => {
    expect(
      tagFromReleaseUrl(
        'https://github.com/Silentely/TG-SignPulse/releases/tag/v2.5.0',
      ),
    ).toBe('v2.5.0')
    expect(tagFromReleaseUrl('https://example.com/nope')).toBeNull()
  })

  it('friendlyGithubError shortens rate limit text without token hint', () => {
    const msg = friendlyGithubError(
      new Error(
        "Client error '403 rate limit exceeded' for url 'https://api.github.com/...' For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403",
      ),
    )
    expect(msg.toLowerCase()).toMatch(/unavailable|try again/)
    expect(msg).not.toContain('developer.mozilla.org')
    expect(msg).not.toContain('APP_GITHUB_TOKEN')
  })

  it('fetchGithubLatestReleaseViaRedirect parses final url', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        url: 'https://github.com/Silentely/TG-SignPulse/releases/tag/v4.0.0',
        headers: { get: () => null },
      }),
    )
    const result = await fetchGithubLatestReleaseViaRedirect()
    expect(result.version).toBe('4.0.0')
  })

  it('fetchGithubLatestRelease aborts on timeout', async () => {
    vi.useFakeTimers()
    vi.stubGlobal(
      'fetch',
      vi.fn(
        (_url: string, options?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            options?.signal?.addEventListener(
              'abort',
              () => reject(new DOMException('Aborted', 'AbortError')),
              { once: true },
            )
          }),
      ),
    )
    // 直接测 HTML 路径超时（默认主路径）；避免再叠 API 第二轮
    let caught: unknown
    const pending = fetchGithubLatestReleaseViaRedirect(undefined, 1000).then(
      () => {
        throw new Error('expected timeout')
      },
      (e: unknown) => {
        caught = e
      },
    )
    await vi.advanceTimersByTimeAsync(1000)
    await pending
    expect(String((caught as Error)?.message || '')).toMatch(/timed out/i)
    vi.useRealTimers()
  })

  it('safeHttpUrl allows only http(s)', () => {
    expect(safeHttpUrl('https://example.com/a')).toBe('https://example.com/a')
    expect(safeHttpUrl('http://example.com/a')).toBe('http://example.com/a')
    expect(safeHttpUrl('javascript:alert(1)')).toBeNull()
    expect(safeHttpUrl('data:text/html,hi')).toBeNull()
    expect(safeHttpUrl(null)).toBeNull()
  })

  it('fetchGithubLatestRelease drops unsafe html_url', async () => {
    // HTML 失败后走 API；API 返回不安全 html_url 时应被丢掉
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce({
          ok: true,
          status: 200,
          url: 'https://github.com/Silentely/TG-SignPulse/releases/latest',
          headers: { get: () => null },
        })
        .mockResolvedValueOnce({
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
