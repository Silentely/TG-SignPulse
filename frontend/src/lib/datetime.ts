/**
 * 时间展示格式化：面板内统一 24 小时制与无效输入兜底。
 * 空值返回 fallback，解析失败返回原始字符串。
 *
 * 展示时区：默认 Asia/Hong_Kong（与后端 TZ 默认一致）；
 * Settings 页保存时区后通过 setPanelTimezone 生效，全面板展示跟随。
 */

/** 面板统一展示时区（模块级可变，Settings 保存后写入） */
let panelTimezone = 'Asia/Hong_Kong'

export function isValidTimezone(tz: string): boolean {
  try {
    Intl.DateTimeFormat(undefined, { timeZone: tz })
    return true
  } catch {
    return false
  }
}

export function setPanelTimezone(tz: string | undefined | null): void {
  if (tz && typeof tz === 'string' && tz.trim()) {
    const trimmed = tz.trim()
    if (isValidTimezone(trimmed)) {
      panelTimezone = trimmed
    }
  }
}

export function getPanelTimezone(): string {
  return panelTimezone
}

/** 仅时间（HH:MM:SS，24 小时制） */
export function formatTimeOnly(value?: string | null, fallback = ''): string {
  if (!value) return fallback
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleTimeString('en-US', { hour12: false, timeZone: panelTimezone })
}

/**
 * 日志行时间：当天仅显示时刻，跨天补「MM/DD」日期前缀。
 * 面板日志常驻滚动，近午夜前后仅看时刻容易产生歧义（昨天 23:59 vs 今天 00:01）。
 * 「今天」按面板统一展示时区判定，避免本机时区差异导致误判。
 */
export function formatLogTime(value?: string | null, fallback = ''): string {
  if (!value) return fallback
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value

  const hkDateKey = (date: Date) =>
    new Intl.DateTimeFormat('en-US', {
      timeZone: panelTimezone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    })
      .format(date)
      .replace(/\//g, '-')

  const time = formatTimeOnly(value, fallback)
  if (hkDateKey(d) === hkDateKey(new Date())) return time

  const monthDay = new Intl.DateTimeFormat('en-US', {
    timeZone: panelTimezone,
    month: '2-digit',
    day: '2-digit',
  }).format(d)
  return `${monthDay} ${time}`
}

/**
 * 完整日期时间（24 小时制，可按语言区域展示）。
 * locale 缺省时固定用 zh-CN：避免隐式依赖浏览器区域，导致同一面板
 * 在不同机器上出现 2026/8/8 与 08/08/2026 等格式混排。
 */
export function formatDateTime(
  value?: string | null,
  locale: string = 'zh-CN',
  fallback = '-',
): string {
  if (!value) return fallback
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString(locale, { hour12: false, timeZone: panelTimezone })
}

/** 短日期时间（MM/DD HH:MM[:SS]），手工拼接避免语言区域导致的顺序/分隔符差异 */
export function formatShortDateTime(
  value?: string | null,
  withSeconds = false,
  fallback = '-',
): string {
  if (!value) return fallback
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  // 与其他格式化函数保持一致：统一按面板展示时区输出，
  // 避免同一事件在不同面板出现两套时刻
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: panelTimezone,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: withSeconds ? '2-digit' : undefined,
    hour12: false,
  }).formatToParts(d)
  const part = (type: string) => parts.find((p) => p.type === type)?.value ?? '00'
  // 部分引擎 hour12:false 对午夜输出 24，规整回 00 保持 24 小时制语义
  let hour = Number(part('hour'))
  if (Number.isNaN(hour) || hour === 24) hour = 0
  const pad = (n: number) => String(n).padStart(2, '0')
  const base = `${part('month')}/${part('day')} ${pad(hour)}:${part('minute')}`
  return withSeconds ? `${base}:${part('second')}` : base
}
