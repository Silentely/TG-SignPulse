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

  // 超过百万复杂度时快速 fallback，保证 UI 不卡顿；
  // 先裁剪公共前后缀，仅将真正变化的区间整体标记为删+增，显著减少噪声行
  if (m * n > 500_000) {
    let prefix = 0
    while (prefix < m && prefix < n && oldLines[prefix] === newLines[prefix]) prefix++
    let suffix = 0
    while (
      suffix < m - prefix &&
      suffix < n - prefix &&
      oldLines[m - 1 - suffix] === newLines[n - 1 - suffix]
    ) suffix++

    const head: DiffLine[] = oldLines.slice(0, prefix).map((l, idx) => ({
      type: 'same' as const,
      text: l,
      oldLine: idx + 1,
      newLine: idx + 1,
    }))
    const tail: DiffLine[] = oldLines.slice(m - suffix).map((l, idx) => ({
      type: 'same' as const,
      text: l,
      oldLine: m - suffix + idx + 1,
      newLine: n - suffix + idx + 1,
    }))
    const dels: DiffLine[] = oldLines.slice(prefix, m - suffix).map((l, idx) => ({
      type: 'del' as const,
      text: l,
      oldLine: prefix + idx + 1,
    }))
    const adds: DiffLine[] = newLines.slice(prefix, n - suffix).map((l, idx) => ({
      type: 'add' as const,
      text: l,
      newLine: prefix + idx + 1,
    }))
    return [...head, ...dels, ...adds, ...tail]
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

  // 先 push 收集再一次性 reverse，避免循环内 unshift 的二次方开销
  const diff: DiffLine[] = []
  let i = m
  let j = n
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && oldLines[i - 1] === newLines[j - 1]) {
      diff.push({ type: 'same', text: oldLines[i - 1], oldLine: i, newLine: j })
      i--
      j--
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      diff.push({ type: 'add', text: newLines[j - 1], newLine: j })
      j--
    } else if (i > 0 && (j === 0 || dp[i][j - 1] < dp[i - 1][j])) {
      diff.push({ type: 'del', text: oldLines[i - 1], oldLine: i })
      i--
    }
  }
  diff.reverse()

  return diff
}
