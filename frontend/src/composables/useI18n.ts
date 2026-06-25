import { computed } from 'vue'
import { useI18n as vueUseI18n } from 'vue-i18n'

/**
 * 项目级 i18n 包装器，保持与 vue-i18n 的桥接兼容。
 * 所有翻译已迁移至 vue-i18n（locales/zh-CN.json、locales/en-US.json），
 * 此 composable 仅提供旧版 API 兼容接口，避免大规模修改已有组件。
 */
export function useI18n() {
  const { locale, t: vueT } = vueUseI18n()

  // 兼容旧版 locale 值：vue-i18n 使用 'zh-CN'/'en-US'，旧代码使用 'zh'/'en'
  const legacyLocale = computed({
    get: () => locale.value === 'zh-CN' ? 'zh' : 'en',
    set: (val: string) => {
      locale.value = val === 'en' ? 'en-US' : 'zh-CN'
      localStorage.setItem('tg-signer-locale', val)
    },
  })

  const toggleLanguage = () => {
    const newLocale = locale.value === 'zh-CN' ? 'en-US' : 'zh-CN'
    locale.value = newLocale
    localStorage.setItem('tg-signer-locale', newLocale === 'zh-CN' ? 'zh' : 'en')
  }

  // 包装 vue-i18n 的 t 函数，处理嵌套 key（如 'logs.detail.LOGIN_SUCCESS'）
  function t(key: string): string {
    return vueT(key)
  }

  return { locale: legacyLocale, toggleLanguage, t }
}
