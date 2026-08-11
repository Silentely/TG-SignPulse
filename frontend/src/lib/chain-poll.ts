/**
 * 链式轮询：上一轮异步结束后再等待 interval，避免 setInterval + async 叠请求。
 */

export type ChainPollOptions = {
  /** 两轮之间的间隔（毫秒），默认 1500 */
  intervalMs?: number
  /** true 时立即执行第一轮；false 则先等 interval（默认 true） */
  runImmediately?: boolean
}

export type ChainPollHandle = {
  /** 是否仍在调度中（含 in-flight） */
  readonly active: boolean
  /** 停止后续调度；当前 in-flight 仍会跑完但不再续约 */
  stop: () => void
}

/**
 * 启动链式轮询。tick 抛错不会中断后续调度（由 tick 内部自行处理错误更佳）。
 */
export function startChainPoll(
  tick: () => void | Promise<void>,
  options: ChainPollOptions = {},
): ChainPollHandle {
  const intervalMs = Math.max(0, options.intervalMs ?? 1500)
  const runImmediately = options.runImmediately !== false
  let stopped = false
  let timer: ReturnType<typeof setTimeout> | null = null
  let inFlight = false

  const clearTimer = () => {
    if (timer !== null) {
      clearTimeout(timer)
      timer = null
    }
  }

  const schedule = (delay: number) => {
    if (stopped) return
    clearTimer()
    timer = setTimeout(() => {
      timer = null
      void run()
    }, delay)
  }

  const run = async () => {
    if (stopped || inFlight) return
    inFlight = true
    try {
      await tick()
    } catch {
      // tick 异常不终止链；调用方应在 tick 内处理可感知错误
    } finally {
      inFlight = false
    }
    if (!stopped) schedule(intervalMs)
  }

  if (runImmediately) {
    void run()
  } else {
    schedule(intervalMs)
  }

  return {
    get active() {
      return !stopped
    },
    stop() {
      stopped = true
      clearTimer()
    },
  }
}
