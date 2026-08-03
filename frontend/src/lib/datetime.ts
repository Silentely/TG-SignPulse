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
  // 与其他格式化函数保持一致：统一按 Asia/Hong_Kong 展示（后端 TZ 默认值），
  // 避免同一事件在不同面板出现两套时刻
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Hong_Kong',
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
