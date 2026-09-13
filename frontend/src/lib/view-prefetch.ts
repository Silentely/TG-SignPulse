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
      options.warn?.(name, error)
    })
  }

  return { prefetch }
}
