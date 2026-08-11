/**
 * 有限并发执行异步任务池。
 * 用于头像批量拉取等场景，避免 N 路同时打满连接 / 触发 401 风暴。
 */

/**
 * 按 concurrency 上限并行跑 tasks；结果顺序与 tasks 输入顺序一致。
 * 单个任务失败不会中断整池，对应位置为 rejected 的 Promise 结果由调用方处理。
 */
export async function mapPool<T, R>(
  items: readonly T[],
  concurrency: number,
  worker: (item: T, index: number) => Promise<R>,
): Promise<PromiseSettledResult<R>[]> {
  const n = items.length
  if (n === 0) return []
  const limit = Math.max(1, Math.min(concurrency, n))
  const results: PromiseSettledResult<R>[] = new Array(n)
  let nextIndex = 0

  const runOne = async (): Promise<void> => {
    while (true) {
      const i = nextIndex
      nextIndex += 1
      if (i >= n) return
      try {
        const value = await worker(items[i], i)
        results[i] = { status: 'fulfilled', value }
      } catch (reason) {
        results[i] = { status: 'rejected', reason }
      }
    }
  }

  const workers = Array.from({ length: limit }, () => runOne())
  await Promise.all(workers)
  return results
}

/** 头像批量拉取默认并发上限 */
export const AVATAR_FETCH_CONCURRENCY = 4
