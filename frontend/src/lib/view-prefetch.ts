type ViewLoader = () => Promise<unknown>

export function createViewPrefetcher(
  loaders: Record<string, ViewLoader>,
  options: { warn?: (name: string, error: unknown) => void } = {},
) {
  const requested = new Set<string>()

  const prefetch = (name: string) => {
    const loader = loaders[name]
    if (!loader || requested.has(name)) return
    requested.add(name)
    void loader().catch((error: unknown) => {
      // 预加载失败（网络抖动/chunk 404）时移除标记，允许后续悬停或预热重试
      requested.delete(name)
      options.warn?.(name, error)
    })
  }

  // 预热全部视图 chunk：触屏与键盘用户没有 hover 预载时机，空闲期兜底加载
  const warmup = () => {
    Object.keys(loaders).forEach(prefetch)
  }

  return { prefetch, warmup }
}
