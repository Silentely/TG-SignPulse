/** 前端版本比较、GitHub 回退检查与本地缓存。 */

export const DEFAULT_GITHUB_RELEASES_URL =
  'https://api.github.com/repos/Silentely/TG-SignPulse/releases/latest'

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
    parts.push(m ? parseInt(m[0], 10) : 0)
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
  try {
    localStorage.removeItem(CACHE_KEY)
  } catch {
    /* ignore */
  }
}

export function saveCachedUpdateCheck(payload: ClientUpdateCheckPayload): void {
  try {
    localStorage.setItem(
      CACHE_KEY,
      JSON.stringify({ saved_at: Date.now(), payload }),
    )
  } catch {
    /* ignore quota */
  }
}

export function loadCachedUpdateCheck(): ClientUpdateCheckPayload | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as {
      saved_at?: number
      payload?: ClientUpdateCheckPayload
    }
    if (!parsed?.saved_at || !parsed.payload) return null
    if (Date.now() - parsed.saved_at > CACHE_TTL_MS) return null
    return parsed.payload
  } catch {
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

export async function fetchGithubLatestRelease(
  url: string = DEFAULT_GITHUB_RELEASES_URL,
): Promise<{ version: string; url: string | null }> {
  const res = await fetch(url, {
    headers: {
      Accept: 'application/vnd.github+json',
    },
    cache: 'no-store',
  })
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
