export interface DiffLine {
  type: 'add' | 'del' | 'same'
  text: string
  oldLine?: number
  newLine?: number
}

/**
 * 基于最长公共子序列 (LCS) 计算两个文本的逐行差异。
 */
export function computeLineDiff(oldStr: string, newStr: string): DiffLine[] {
  if (oldStr === newStr) {
    return oldStr.split('\n').map((line, idx) => ({
      type: 'same',
      text: line,
      oldLine: idx + 1,
      newLine: idx + 1,
    }))
  }

  const oldLines = oldStr.split('\n')
  const newLines = newStr.split('\n')
  const m = oldLines.length
  const n = newLines.length

  // 超过百万复杂度时快速 fallback，保证 UI 不卡顿
  if (m * n > 500_000) {
    return [
      ...oldLines.map((l, idx) => ({ type: 'del' as const, text: l, oldLine: idx + 1 })),
      ...newLines.map((l, idx) => ({ type: 'add' as const, text: l, newLine: idx + 1 })),
    ]
  }

  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0))
  for (let i = 0; i < m; i++) {
    for (let j = 0; j < n; j++) {
      if (oldLines[i] === newLines[j]) {
        dp[i + 1][j + 1] = dp[i][j] + 1
      } else {
        dp[i + 1][j + 1] = Math.max(dp[i + 1][j], dp[i][j + 1])
      }
    }
  }

  const diff: DiffLine[] = []
  let i = m
  let j = n
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
      diff.unshift({ type: 'same', text: oldLines[i - 1], oldLine: i, newLine: j })
      i--
      j--
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      diff.unshift({ type: 'add', text: newLines[j - 1], newLine: j })
      j--
    } else if (i > 0 && (j === 0 || dp[i][j - 1] < dp[i - 1][j])) {
      diff.unshift({ type: 'del', text: oldLines[i - 1], oldLine: i })
      i--
    }
  }

  return diff
}
