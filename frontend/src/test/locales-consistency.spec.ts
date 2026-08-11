import { describe, expect, it } from 'vitest'
import zhCN from '../locales/zh-CN.json'
import enUS from '../locales/en-US.json'

/**
 * 语言文件键结构一致性：中英文必须逐键对齐，
 * 防止新增翻译键时只改一个语言文件导致界面出现裸键。
 */
type JsonNode = string | number | boolean | null | JsonNode[] | { [k: string]: JsonNode }

function collectKeys(node: JsonNode, prefix = '', out: string[] = []): string[] {
  if (node && typeof node === 'object' && !Array.isArray(node)) {
    for (const [k, v] of Object.entries(node)) {
      const path = prefix ? `${prefix}.${k}` : k
      collectKeys(v, path, out)
    }
  } else {
    out.push(prefix)
  }
  return out
}

describe('locales 键一致性', () => {
  it('zh-CN 与 en-US 叶键完全一致', () => {
    const zh = collectKeys(zhCN as JsonNode).sort()
    const en = collectKeys(enUS as JsonNode).sort()
    expect(zh).toEqual(en)
  })

  it('不允许出现 vue-i18n 双花括号占位符（{{ 会编译失败并原样输出）', () => {
    const values = (node: JsonNode, out: string[] = []): string[] => {
      if (node && typeof node === 'object' && !Array.isArray(node)) {
        for (const v of Object.values(node)) values(v as JsonNode, out)
      } else if (typeof node === 'string') {
        out.push(node)
      }
      return out
    }
    const badZh = values(zhCN as JsonNode).filter((s) => s.includes('{{'))
    const badEn = values(enUS as JsonNode).filter((s) => s.includes('{{'))
    expect(badZh, `zh-CN 含双花括号: ${badZh.join(' | ')}`).toEqual([])
    expect(badEn, `en-US 含双花括号: ${badEn.join(' | ')}`).toEqual([])
  })
})
