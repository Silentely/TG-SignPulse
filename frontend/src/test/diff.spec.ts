import { describe, expect, it } from 'vitest'
import { computeLineDiff } from '../lib/diff'

describe('computeLineDiff', () => {
  it('当两段文本相同时全部为 same', () => {
    const text = 'line 1\nline 2'
    const diff = computeLineDiff(text, text)
    expect(diff).toHaveLength(2)
    expect(diff.every((d) => d.type === 'same')).toBe(true)
    expect(diff[0].oldLine).toBe(1)
    expect(diff[0].newLine).toBe(1)
  })

  it('能正确识别新增行与删除行', () => {
    const oldCode = 'def foo():\n    return 1'
    const newCode = 'def foo():\n    return 2\n    # end'
    const diff = computeLineDiff(oldCode, newCode)

    expect(diff[0]).toEqual({ type: 'same', text: 'def foo():', oldLine: 1, newLine: 1 })
    expect(diff[1]).toEqual({ type: 'del', text: '    return 1', oldLine: 2 })
    expect(diff[2]).toEqual({ type: 'add', text: '    return 2', newLine: 2 })
    expect(diff[3]).toEqual({ type: 'add', text: '    # end', newLine: 3 })
  })

  it('面对极端空文本能安全处理', () => {
    const diff = computeLineDiff('', 'new line')
    expect(diff.length).toBeGreaterThan(0)
  })
})
