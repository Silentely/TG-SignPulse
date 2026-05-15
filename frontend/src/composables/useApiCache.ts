import { ref } from 'vue'

interface CacheEntry<T> {
  data: T
  timestamp: number
}

const cache = new Map<string, CacheEntry<any>>()

/**
 * Simple API response cache with TTL.
 * Usage: const { data, loading, refresh } = useApiCache('accounts', () => listAccounts(token), 10000)
 */
export function useApiCache<T>(
  key: string,
  fetcher: () => Promise<T>,
  ttlMs: number = 8000
) {
  const data = ref<T | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function load(forceRefresh = false) {
    const now = Date.now()
    const cached = cache.get(key)

    if (!forceRefresh && cached && now - cached.timestamp < ttlMs) {
      data.value = cached.data
      return cached.data
    }

    loading.value = true
    error.value = null
    try {
      const result = await fetcher()
      data.value = result as any
      cache.set(key, { data: result, timestamp: now })
      return result
    } catch (e: any) {
      error.value = e.message || 'Request failed'
      throw e
    } finally {
      loading.value = false
    }
  }

  function invalidate() {
    cache.delete(key)
  }

  function refresh() {
    return load(true)
  }

  return { data, loading, error, load, refresh, invalidate }
}

/** Invalidate all cache entries matching a prefix */
export function invalidateCache(prefix?: string) {
  if (!prefix) {
    cache.clear()
    return
  }
  for (const key of cache.keys()) {
    if (key.startsWith(prefix)) {
      cache.delete(key)
    }
  }
}
