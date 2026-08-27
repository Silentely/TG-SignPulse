import { createI18n } from 'vue-i18n'
import { watch } from 'vue'
import zhCN from '../locales/zh-CN.json'
import enUS from '../locales/en-US.json'
import { storageGet } from '../lib/safe-storage'

// 从 localStorage 读取用户语言偏好，默认中文（存储不可用环境回退默认）
const savedLocale = storageGet('tg-signer-locale') || 'zh'

const i18n = createI18n({
  legacy: false, // 使用 Composition API 模式
  locale: savedLocale === 'en' ? 'en-US' : 'zh-CN',
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': zhCN,
    'en-US': enUS,
  },
})

// 语言切换时同步 <html lang>：仅首帧初始化不够，运行时切换语言后
// 屏读器发音与页面语言声明需与界面保持一致（含返回 zh 的默认分支）
watch(
  i18n.global.locale,
  (val) => {
    document.documentElement.lang = String(val) === 'en-US' ? 'en-US' : 'zh-CN'
  },
  { immediate: true },
)

export default i18n
