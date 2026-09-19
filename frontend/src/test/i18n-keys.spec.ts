import { describe, expect, it } from 'vitest'
import zhCN from '../locales/zh-CN.json'
import enUS from '../locales/en-US.json'

/**
 * 文案完整性守卫。
 *
 * 组件用 t('section.key') 引用文案，缺失的键会在界面上原样渲染成 key，
 * 而单测里 mock 掉 useI18n 的写法无法发现这类问题。此处静态扫描源码中的
 * 静态文案键，逐一校验中英文两套 locale 是否都已定义。
 *
 * 使用 import.meta.glob 读取源码，避免引入 node 内置模块类型依赖。
 */

// 排除测试自身与 locale 数据文件
const sources = import.meta.glob('../**/*.{vue,ts}', {
  query: '?raw',
  import: 'default',
  eager: true,
}) as Record<string, string>

const scanned = Object.entries(sources).filter(
  ([path]) => !path.includes('/test/') && !path.includes('/locales/'),
)

// 仅匹配静态键：t('a.b') / t("a.b")；含模板字符串或变量的动态键无法静态校验，跳过
const STATIC_KEY_RE = /(?<![\w.])t\(\s*['"]([A-Za-z][A-Za-z0-9_]*)\.([A-Za-z0-9_]+)['"]/g

function hasKey(dict: Record<string, unknown>, section: string, key: string): boolean {
  const bucket = dict[section]
  return !!bucket && typeof bucket === 'object' && key in (bucket as Record<string, unknown>)
}

describe('i18n 文案完整性', () => {
  const used = new Map<string, string>()

  for (const [path, content] of scanned) {
    for (const match of content.matchAll(STATIC_KEY_RE)) {
      const full = `${match[1]}.${match[2]}`
      if (!used.has(full)) used.set(full, path)
    }
  }

  it('扫描到的源码与静态文案键非空（防止扫描逻辑失效）', () => {
    expect(scanned.length).toBeGreaterThan(50)
    expect(used.size).toBeGreaterThan(100)
  })

  it('每个静态文案键在 zh-CN 与 en-US 中均已定义', () => {
    const missing: string[] = []
    for (const [full, path] of used) {
      const [section, key] = full.split('.', 2)
      if (!hasKey(zhCN as Record<string, unknown>, section, key)) {
        missing.push(`${full} [zh-CN] <- ${path}`)
      }
      if (!hasKey(enUS as Record<string, unknown>, section, key)) {
        missing.push(`${full} [en-US] <- ${path}`)
      }
    }
    expect(missing).toEqual([])
  })
})
