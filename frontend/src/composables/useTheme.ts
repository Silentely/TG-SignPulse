import { ref } from 'vue'
import { storageGet, storageSet } from '../lib/safe-storage'

// 主题色常量与 index.html / PWA manifest 保持一致
const LIGHT_THEME_COLOR = '#ffffff'
const DARK_THEME_COLOR = '#0f172a'

/** 同步浏览器标签栏/地址栏主题色（含 PWA 安装后运行时），跟随实际主题而非系统偏好 */
const applyThemeColor = (dark: boolean) => {
  const meta = document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')
  if (meta) meta.content = dark ? DARK_THEME_COLOR : LIGHT_THEME_COLOR
}

// 存储不可用时按「未设置」处理，回退系统偏好
const savedTheme = storageGet('theme')
const initDark = savedTheme === 'dark' || (savedTheme === null && window.matchMedia('(prefers-color-scheme: dark)').matches)
const isDark = ref(initDark)

if (initDark) {
  document.documentElement.classList.add('dark')
} else {
  document.documentElement.classList.remove('dark')
}
applyThemeColor(initDark)

export const useTheme = () => {
  const toggleTheme = (event?: MouseEvent) => {
    const isAppearanceTransition = typeof document.startViewTransition === 'function' && !window.matchMedia('(prefers-reduced-motion: reduce)').matches

    if (!isAppearanceTransition || !event) {
      isDark.value = !isDark.value
      updateDOM()
      return
    }

    const x = event.clientX
    const y = event.clientY
    const endRadius = Math.hypot(
      Math.max(x, innerWidth - x),
      Math.max(y, innerHeight - y)
    )

    const transition = document.startViewTransition(() => {
      isDark.value = !isDark.value
      updateDOM()
    })

    transition.ready.then(() => {
      const clipPath = [
        `circle(0px at ${x}px ${y}px)`,
        `circle(${endRadius}px at ${x}px ${y}px)`
      ]
      
      document.documentElement.animate(
        {
          clipPath: clipPath
        },
        {
          duration: 500,
          easing: 'ease-in-out',
          pseudoElement: '::view-transition-new(root)'
        }
      )
    }).catch(() => {
      // View Transition 被跳过（如页面不可见）时 ready 会 reject，此处静默降级
    })
  }

  const updateDOM = () => {
    if (isDark.value) {
      document.documentElement.classList.add('dark')
      storageSet('theme', 'dark')
    } else {
      document.documentElement.classList.remove('dark')
      storageSet('theme', 'light')
    }
    applyThemeColor(isDark.value)
  }

  return { isDark, toggleTheme }
}
