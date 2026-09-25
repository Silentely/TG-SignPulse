/**
 * 将 /ops/memory 返回的 stats 格式化为可读 RSS 文案。
 * 后端 MemoryMonitor.get_stats() 使用 current_rss_mb。
 */
export function formatMemoryRssFromStats(
  stats: Record<string, unknown> | null | undefined,
  unknownLabel: string,
): string {
  const s = stats || {}
  const rawRssMb = s.current_rss_mb ?? s.rss_mb ?? s.rssMb
  if (rawRssMb !== null && rawRssMb !== undefined && rawRssMb !== '') {
    const num = Number(rawRssMb)
    if (!Number.isNaN(num) && Number.isFinite(num)) {
      return `${num.toFixed(1)} MB`
    }
  }
  const rawRssBytes = s.rss_bytes ?? s.rss
  if (rawRssBytes !== null && rawRssBytes !== undefined && rawRssBytes !== '') {
    const num = Number(rawRssBytes)
    if (!Number.isNaN(num) && Number.isFinite(num)) {
      return `${(num / (1024 * 1024)).toFixed(1)} MB`
    }
  }
  return unknownLabel
}
