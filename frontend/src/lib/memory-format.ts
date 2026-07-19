/**
 * 将 /ops/memory 返回的 stats 格式化为可读 RSS 文案。
 * 后端 MemoryMonitor.get_stats() 使用 current_rss_mb。
 */
export function formatMemoryRssFromStats(
  stats: Record<string, unknown> | null | undefined,
  unknownLabel: string,
): string {
  const s = stats || {}
  const rssMb = s.current_rss_mb ?? s.rss_mb ?? s.rssMb
  if (typeof rssMb === 'number' && Number.isFinite(rssMb)) {
    return `${rssMb.toFixed(1)} MB`
  }
  const rss = s.rss_bytes ?? s.rss
  if (typeof rss === 'number' && Number.isFinite(rss)) {
    return `${(rss / (1024 * 1024)).toFixed(1)} MB`
  }
  return unknownLabel
}
