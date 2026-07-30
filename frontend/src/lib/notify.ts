/**
 * API 错误通知单入口：统一的「错误对象 + i18n 兜底 key」解析与 toast 报错。
 * lib 层直接取全局 i18n 实例（vue-i18n 的 useI18n 仅限组件 setup 顶层调用，
 * 异步 catch 回调中会抛 MUST_BE_CALL_SETUP_TOP）；toast 走 useToast 的单例状态，
 * 事件回调与异步 catch 中均可安全调用。
 */
import i18n from '../i18n'
import { useToast } from '../composables/useToast'
import { getLocalizedErrorMessage } from './types'

const globalT = (key: string) => String(i18n.global.t(key))

/** 解析 API 错误为本地化文案，key 为兜底翻译键（如 'settings.saveFailed'） */
export const resolveApiErrorMessage = (e: unknown, key: string): string =>
  getLocalizedErrorMessage(e, globalT, globalT(key))

/** API 失败统一 error toast */
export const notifyApiError = (e: unknown, key: string) => {
  useToast().error(resolveApiErrorMessage(e, key))
}
