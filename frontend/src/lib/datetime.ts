/**
 * 时间展示格式化：面板内统一 24 小时制与无效输入兜底。
 * 空值返回 fallback，解析失败返回原始字符串。
 */

/** 仅时间（HH:MM:SS，24 小时制） */
export function formatTimeOnly(value?: string | null, fallback = ''): string {
  if (!value) return fallback
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleTimeString('en-US', { hour12: false, timeZone: 'Asia/Hong_Kong' })
}

/** 完整日期时间（24 小时制，可按语言区域展示） */
export function formatDateTime(
  value?: string | null,
  locale?: string,
  fallback = '-',
): string {
  if (!value) return fallback
  const d = new Date(value)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleString(locale, { hour12: false, timeZone: 'Asia/Hong_Kong' })
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
  const pad = (n: number) => String(n).padStart(2, '0')
  const base = `${pad(d.getMonth() + 1)}/${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`
  return withSeconds ? `${base}:${pad(d.getSeconds())}` : base
}
