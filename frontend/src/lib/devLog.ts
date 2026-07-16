/**
 * 开发期诊断日志：生产构建默认静默，避免控制台噪声。
 * 可通过 localStorage.tg_dev_log=1 强制开启。
 */

function isDevLogEnabled(): boolean {
  try {
    if (typeof localStorage !== 'undefined' && localStorage.getItem('tg_dev_log') === '1') {
      return true
    }
  } catch {
    // ignore
  }
  return Boolean(import.meta.env.DEV)
}

export const devLog = {
  error(message: string, ...args: unknown[]) {
    if (!isDevLogEnabled()) return
    // eslint-disable-next-line no-console
    console.error(message, ...args)
  },
  warn(message: string, ...args: unknown[]) {
    if (!isDevLogEnabled()) return
    // eslint-disable-next-line no-console
    console.warn(message, ...args)
  },
  info(message: string, ...args: unknown[]) {
    if (!isDevLogEnabled()) return
    // eslint-disable-next-line no-console
    console.info(message, ...args)
  },
}
