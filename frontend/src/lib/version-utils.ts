/** 前端版本比较、GitHub 回退检查与本地缓存。 */
import { devLog } from './devLog'
import { storageGet, storageSet, storageRemove } from './safe-storage'

export const DEFAULT_GITHUB_RELEASES_URL =
  'https://api.github.com/repos/Silentely/TG-SignPulse/releases/latest'

/** 不计入 api.github.com 配额：跟随 HTML 站 latest 重定向解析 tag */
export const DEFAULT_GITHUB_HTML_LATEST_URL =
  'https://github.com/Silentely/TG-SignPulse/releases/latest'

const CACHE_KEY = 'tg_signpulse_update_check_v1'
const CACHE_TTL_MS = 24 * 60 * 60 * 1000

export type ClientUpdateCheckPayload = {
  latest_version: string | null
  latest_url: string | null
  update_available: boolean
  checked_at: string
  error: string | null
}

export function normalizeVersion(raw: string): string {
  let s = (raw || '').trim()
  if (s.length >= 2 && (s[0] === 'v' || s[0] === 'V') && /\d/.test(s[1])) {
    s = s.slice(1)
  }
  return s
}

function parseSemver(raw: string): [number, number, number] {
  let s = normalizeVersion(raw)
  if (!s) return [0, 0, 0]
  s = s.split('+')[0].split('-')[0]
  const parts: number[] = []
  for (const piece of s.split('.')) {
    const m = piece.match(/^\d+/)
    parts.push(m ? Math.min(parseInt(m[0], 10), 999999) : 0)
    if (parts.length >= 3) break
  }
  while (parts.length < 3) parts.push(0)
  return [parts[0], parts[1], parts[2]]
}

export function isUpdateAvailable(current: string, latest: string): boolean {
  const cur = normalizeVersion(current)
  const lat = normalizeVersion(latest)
  if (!cur || !lat) return false
  const a = parseSemver(cur)
  const b = parseSemver(lat)
  for (let i = 0; i < 3; i++) {
    if (b[i] > a[i]) return true
    if (b[i] < a[i]) return false
  }
  return false
}

export function clearCachedUpdateCheck(): void {
  storageRemove(CACHE_KEY)
}

export function saveCachedUpdateCheck(payload: ClientUpdateCheckPayload): void {
  storageSet(
    CACHE_KEY,
    JSON.stringify({ saved_at: Date.now(), payload }),
  )
}

export function loadCachedUpdateCheck(): ClientUpdateCheckPayload | null {
  try {
    const raw = storageGet(CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as {
      saved_at?: number
      payload?: ClientUpdateCheckPayload
    }
    if (!parsed?.saved_at || !parsed.payload) return null
    if (Date.now() - parsed.saved_at > CACHE_TTL_MS) return null
    return parsed.payload
  } catch (e) {
    devLog.warn('Failed to read cached update check', e)
    return null
  }
}

/** 仅允许 http(s) 外链，防止 javascript: 等协议进入 href。 */
export function safeHttpUrl(raw: string | null | undefined): string | null {
  if (!raw) return null
  try {
    const u = new URL(String(raw).trim())
    if (u.protocol !== 'https:' && u.protocol !== 'http:') return null
    return u.toString()
  } catch {
    return null
  }
}

/** GitHub Releases 检查超时（毫秒）；弱网下避免设置页长期挂起。 */
export const GITHUB_RELEASE_TIMEOUT_MS = 12_000

const TAG_PATH_RE = /\/releases\/tag\/([^/?#]+)/i

/** 从 final URL / Location 提取 releases/tag/xxx */
export function tagFromReleaseUrl(raw: string | null | undefined): string | null {
  if (!raw) return null
  try {
    const path = new URL(String(raw).trim()).pathname
    const m = path.match(TAG_PATH_RE)
    return m?.[1] ? decodeURIComponent(m[1]) : null
  } catch {
    const m = String(raw).match(TAG_PATH_RE)
    return m?.[1] ? m[1] : null
  }
}

function isRateLimitMessage(msg: string): boolean {
  const s = msg.toLowerCase()
  return s.includes('rate limit') || s.includes('http 403') || s.includes('http 429')
}

/** 将原始 GitHub 错误压成可展示短文案（不提 Token，自部署零配置）。 */
export function friendlyGithubError(raw: unknown): string {
  const msg = raw instanceof Error ? raw.message : String(raw || '')
  if (isRateLimitMessage(msg)) {
    return 'Update check is temporarily unavailable; please try again later'
  }
  if (msg.length > 160) return `${msg.slice(0, 160).trimEnd()}…`
  return msg || 'GitHub releases network error'
}

async function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController()
  const timer =
    timeoutMs > 0 ? setTimeout(() => controller.abort(), timeoutMs) : null
  try {
    return await fetch(url, { ...init, signal: controller.signal })
  } catch (e: unknown) {
    const isAbort =
      (e instanceof DOMException && e.name === 'AbortError') ||
      (e instanceof Error && e.name === 'AbortError')
    throw new Error(
      isAbort
        ? `GitHub releases timed out after ${timeoutMs}ms`
        : e instanceof Error
          ? e.message
          : 'GitHub releases network error',
    )
  } finally {
    if (timer !== null) clearTimeout(timer)
  }
}

/** 通过 github.com/…/releases/latest 重定向解析最新 tag（绕过 API 限流）。 */
export async function fetchGithubLatestReleaseViaRedirect(
  url: string = DEFAULT_GITHUB_HTML_LATEST_URL,
  timeoutMs: number = GITHUB_RELEASE_TIMEOUT_MS,
): Promise<{ version: string; url: string | null }> {
  // 浏览器 fetch 对跨域 302 通常会自动跟随；最终 URL 常含 /releases/tag/vX
  const res = await fetchWithTimeout(
    url,
    {
      method: 'GET',
      redirect: 'follow',
      cache: 'no-store',
      headers: { Accept: 'text/html' },
    },
    timeoutMs,
  )
  const headerGet =
    res.headers && typeof res.headers.get === 'function'
      ? (k: string) => res.headers.get(k)
      : () => null
  const tag =
    tagFromReleaseUrl(res.url) ||
    tagFromReleaseUrl(headerGet('Location')) ||
    tagFromReleaseUrl(headerGet('location'))
  if (!tag) {
    // 部分环境 CORS 隐藏最终 URL：再由调用方决定是否走 API
    throw new Error(
      `GitHub HTML latest redirect could not resolve tag (HTTP ${res.status})`,
    )
  }
  const pageUrl = safeHttpUrl(res.url) || safeHttpUrl(url)
  return {
    version: normalizeVersion(tag),
    url: pageUrl,
  }
}

/**
 * 浏览器侧检查最新版本。
 * 默认优先 HTML releases/latest 重定向（零配置、不吃 API 配额）；
 * 仅当 HTML 失败时才回退 api.github.com JSON。
 */
export async function fetchGithubLatestRelease(
  url: string = DEFAULT_GITHUB_RELEASES_URL,
  timeoutMs: number = GITHUB_RELEASE_TIMEOUT_MS,
): Promise<{ version: string; url: string | null }> {
  const preferHtml =
    !url ||
    url === DEFAULT_GITHUB_RELEASES_URL ||
    /api\.github\.com\/repos\/[^/]+\/[^/]+\/releases\/latest/i.test(url)

  if (preferHtml) {
    try {
      return await fetchGithubLatestReleaseViaRedirect(
        DEFAULT_GITHUB_HTML_LATEST_URL,
        timeoutMs,
      )
    } catch (htmlErr) {
      // 超时/中止不再拖第二轮 API，避免设置页挂起翻倍
      const msg = htmlErr instanceof Error ? htmlErr.message : String(htmlErr || '')
      const name = htmlErr instanceof Error ? htmlErr.name : ''
      if (
        /timed out/i.test(msg) ||
        /abort/i.test(msg) ||
        name === 'AbortError'
      ) {
        throw htmlErr instanceof Error ? htmlErr : new Error(msg)
      }
      devLog.warn('HTML release check failed, trying API', htmlErr)
    }
  }

  const res = await fetchWithTimeout(
    url || DEFAULT_GITHUB_RELEASES_URL,
    {
      headers: {
        Accept: 'application/vnd.github+json',
      },
      cache: 'no-store',
    },
    timeoutMs,
  )
  if (!res.ok) {
    throw new Error(`GitHub releases HTTP ${res.status}`)
  }
  const data = (await res.json()) as {
    tag_name?: string
    name?: string
    html_url?: string
  }
  const tag = String(data.tag_name || data.name || '').trim()
  if (!tag) throw new Error('release missing tag_name')
  return {
    version: normalizeVersion(tag),
    url: safeHttpUrl(data.html_url ?? null),
  }
}
