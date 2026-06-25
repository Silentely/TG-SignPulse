import { createI18n } from 'vue-i18n'
import zhCN from '../locales/zh-CN.json'
import enUS from '../locales/en-US.json'

// 从 localStorage 读取用户语言偏好，默认中文
const savedLocale = localStorage.getItem('tg-signer-locale') || 'zh'

const i18n = createI18n({
  legacy: false, // 使用 Composition API 模式
  locale: savedLocale === 'en' ? 'en-US' : 'zh-CN',
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': zhCN,
    'en-US': enUS,
  },
})

export default i18n
