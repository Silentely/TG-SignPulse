/**
 * Lightweight, safe Markdown renderer for TG-SignPulse UI.
 * Zero external dependencies, built-in XSS sanitization.
 */

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function sanitizeUrl(rawUrl: string): string | null {
  const trimmed = rawUrl.trim()
  if (trimmed.startsWith('#')) {
    const cleanAnchor = trimmed.replace(/[^a-zA-Z0-9_\-#]/g, '')
    return cleanAnchor || null
  }
  // Disallow javascript:, data:, vbscript:
  const lower = trimmed.toLowerCase()
  if (lower.startsWith('javascript:') || lower.startsWith('data:') || lower.startsWith('vbscript:')) {
    return null
  }
  try {
    const parsed = new URL(trimmed)
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
      return trimmed
    }
  } catch {
    // Relative or invalid
  }
  return null
}

function renderInline(rawText: string): string {
  // 1. Preserve explicit anchor spans: <span id="..."></span>
  const spanPlaceholders: string[] = []
  let text = rawText.replace(/<span\s+id=["']([a-zA-Z0-9_-]+)["']\s*><\/span>/gi, (_, id) => {
    const idx = spanPlaceholders.length
    spanPlaceholders.push(`<span id="${escapeHtml(id)}"></span>`)
    return `\x00SPAN${idx}\x00`
  })

  // 2. Escape HTML characters in remaining text
  text = escapeHtml(text)

  // 3. Inline code: `code` (use alphanumeric placeholder without underscore to avoid italic conflict)
  const codePlaceholders: string[] = []
  text = text.replace(/`([^`]+)`/g, (_, code) => {
    const idx = codePlaceholders.length
    codePlaceholders.push(
      `<code class="px-1.5 py-0.5 bg-[var(--sp-canvas)] dark:bg-slate-800 border border-[var(--sp-border)] rounded font-mono text-[11px] text-indigo-600 dark:text-indigo-400">${code}</code>`
    )
    return `\x00INLINECODE${idx}\x00`
  })

  // 4. Links: [text](url) - match matching outer parens
  text = text.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+|#[^\s)]+|[^\s)]+)\)/g, (_, linkText, url) => {
    const safe = sanitizeUrl(url)
    if (!safe) {
      return linkText
    }
    const isAnchor = safe.startsWith('#')
    const targetAttrs = isAnchor ? '' : ' target="_blank" rel="noopener noreferrer"'
    return `<a href="${safe}"${targetAttrs} class="text-indigo-600 dark:text-indigo-400 hover:underline font-medium">${linkText}</a>`
  })
  // Catch any remaining malicious [text](javascript:...) with parens
  text = text.replace(/\[([^\]]+)\]\(javascript:[^)]*\)/gi, '$1')

  // 5. Bold & Italic (using ** and * or __ and _)
  text = text.replace(/\*\*\*([^*]+)\*\*\*/g, '<strong class="font-semibold text-[var(--sp-text-primary)]"><em class="italic">$1</em></strong>')
  text = text.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold text-[var(--sp-text-primary)]">$1</strong>')
  text = text.replace(/__([^_]+)__/g, '<strong class="font-semibold text-[var(--sp-text-primary)]">$1</strong>')
  text = text.replace(/(?<!\w)\*([^*]+)\*(?!\w)/g, '<em class="italic">$1</em>')
  text = text.replace(/(?<!\w)_([^_]+)_(?!\w)/g, '<em class="italic">$1</em>')

  // 6. Strikethrough: ~~text~~
  text = text.replace(/~~([^~]+)~~/g, '<del class="line-through opacity-70">$1</del>')

  // 7. Restore placeholders
  text = text.replace(/\x00INLINECODE(\d+)\x00/g, (_, idx) => codePlaceholders[Number(idx)] || '')
  text = text.replace(/\x00SPAN(\d+)\x00/g, (_, idx) => spanPlaceholders[Number(idx)] || '')

  return text
}

function parseTable(lines: string[]): string {
  if (lines.length < 2) return ''
  const headerCells = lines[0]
    .split('|')
    .slice(1, -1)
    .map((c) => c.trim())
  const alignCells = lines[1]
    .split('|')
    .slice(1, -1)
    .map((c) => {
      const trimmed = c.trim()
      const left = trimmed.startsWith(':')
      const right = trimmed.endsWith(':')
      if (left && right) return 'center'
      if (right) return 'right'
      return 'left'
    })

  const rowLines = lines.slice(2)

  let html = '<div class="my-3 overflow-x-auto rounded border border-[var(--sp-border)]">'
  html += '<table class="w-full text-left text-xs border-collapse">'
  html += '<thead class="bg-[var(--sp-canvas)] dark:bg-slate-800 text-[var(--sp-text-secondary)] font-medium">'
  html += '<tr>'
  headerCells.forEach((c, i) => {
    const align = alignCells[i] || 'left'
    const alignClass = align === 'center' ? 'text-center' : align === 'right' ? 'text-right' : 'text-left'
    html += `<th class="p-2 border-b border-[var(--sp-border)] ${alignClass}">${renderInline(c)}</th>`
  })
  html += '</tr></thead>'
  html += '<tbody class="divide-y divide-[var(--sp-border)] bg-[var(--sp-surface)] dark:bg-slate-900/30">'
  rowLines.forEach((row) => {
    const cells = row
      .split('|')
      .slice(1, -1)
      .map((c) => c.trim())
    html += '<tr class="hover:bg-[var(--sp-surface-muted)]/50 transition-colors">'
    cells.forEach((cell, i) => {
      const align = alignCells[i] || 'left'
      const alignClass = align === 'center' ? 'text-center' : align === 'right' ? 'text-right' : 'text-left'
      html += `<td class="p-2 ${alignClass}">${renderInline(cell)}</td>`
    })
    html += '</tr>'
  })
  html += '</tbody></table></div>'
  return html
}

export function renderMarkdown(markdown: string): string {
  if (!markdown || !markdown.trim()) {
    return ''
  }

  // Normalize line endings
  let text = markdown.replace(/\r\n/g, '\n').replace(/\r/g, '\n')

  // 1. Extract fenced code blocks
  const codeBlocks: string[] = []
  text = text.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (_, lang, content) => {
    const idx = codeBlocks.length
    const escaped = escapeHtml(content.trimEnd())
    const langAttr = lang ? ` data-language="${escapeHtml(lang)}"` : ''
    codeBlocks.push(
      `<pre class="my-2.5 p-3 bg-[var(--sp-canvas)] dark:bg-slate-900 border border-[var(--sp-border)] rounded-[var(--sp-radius-md,6px)] font-mono text-[11px] overflow-x-auto text-[var(--sp-text-primary)] select-text"${langAttr}><code>${escaped}</code></pre>`
    )
    return `\n\x00CODEBLOCK${idx}\x00\n`
  })

  const lines = text.split('\n')
  const out: string[] = []

  let inList: 'ul' | 'ol' | null = null
  let listItems: string[] = []

  const flushList = () => {
    if (!inList) return
    const tag = inList
    const listClass = tag === 'ul' ? 'list-disc list-inside space-y-1 my-2 text-xs' : 'list-decimal list-inside space-y-1 my-2 text-xs'
    out.push(`<${tag} class="${listClass}">`)
    listItems.forEach((item) => {
      out.push(`  <li class="leading-relaxed text-[var(--sp-text-secondary)]">${renderInline(item)}</li>`)
    })
    out.push(`</${tag}>`)
    inList = null
    listItems = []
  }

  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    // Empty line
    if (!trimmed) {
      flushList()
      i++
      continue
    }

    // Code block placeholder
    if (trimmed.startsWith('\x00CODEBLOCK') && trimmed.endsWith('\x00')) {
      flushList()
      const match = trimmed.match(/\x00CODEBLOCK(\d+)\x00/)
      if (match) {
        out.push(codeBlocks[Number(match[1])] || '')
      }
      i++
      continue
    }

    // Horizontal rule
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(trimmed)) {
      flushList()
      out.push('<hr class="my-4 border-[var(--sp-border)]" />')
      i++
      continue
    }

    // Headers (# to ####)
    const headerMatch = line.match(/^(#{1,6})\s+(.*)$/)
    if (headerMatch) {
      flushList()
      const level = headerMatch[1].length
      const title = headerMatch[2]
      if (level === 1) {
        out.push(
          `<h1 class="text-base font-bold text-[var(--sp-text-primary)] mt-4 mb-2 pb-1 border-b border-[var(--sp-border)]">${renderInline(
            title
          )}</h1>`
        )
      } else if (level === 2) {
        out.push(
          `<h2 class="text-sm font-semibold text-[var(--sp-text-primary)] mt-3 mb-1.5 pb-0.5 border-b border-[var(--sp-border)]/60">${renderInline(
            title
          )}</h2>`
        )
      } else if (level === 3) {
        out.push(`<h3 class="text-xs font-semibold text-[var(--sp-text-primary)] mt-2.5 mb-1">${renderInline(title)}</h3>`)
      } else {
        out.push(`<h4 class="text-xs font-medium text-[var(--sp-text-secondary)] mt-2 mb-1">${renderInline(title)}</h4>`)
      }
      i++
      continue
    }

    // Blockquote
    if (trimmed.startsWith('>')) {
      flushList()
      const quoteLines: string[] = []
      while (i < lines.length && lines[i].trim().startsWith('>')) {
        quoteLines.push(lines[i].trim().replace(/^>\s?/, ''))
        i++
      }
      out.push(
        `<blockquote class="border-l-4 border-indigo-500/70 pl-3 py-1.5 my-2 text-[var(--sp-text-secondary)] bg-[var(--sp-canvas)]/50 rounded-r text-xs italic">${renderInline(
          quoteLines.join(' ')
        )}</blockquote>`
      )
      continue
    }

    // Table detection: starts with | and next line has |---
    if (trimmed.startsWith('|') && trimmed.endsWith('|') && i + 1 < lines.length && lines[i + 1].trim().startsWith('|') && lines[i + 1].includes('-')) {
      flushList()
      const tableLines: string[] = []
      while (i < lines.length && lines[i].trim().startsWith('|') && lines[i].trim().endsWith('|')) {
        tableLines.push(lines[i].trim())
        i++
      }
      out.push(parseTable(tableLines))
      continue
    }

    // Unordered list
    const ulMatch = line.match(/^(\s*)[-*+]\s+(.*)$/)
    if (ulMatch) {
      if (inList !== 'ul') {
        flushList()
        inList = 'ul'
      }
      listItems.push(ulMatch[2])
      i++
      continue
    }

    // Ordered list
    const olMatch = line.match(/^(\s*)\d+\.\s+(.*)$/)
    if (olMatch) {
      if (inList !== 'ol') {
        flushList()
        inList = 'ol'
      }
      listItems.push(olMatch[2])
      i++
      continue
    }

    // Regular paragraph
    flushList()
    out.push(`<p class="my-1.5 leading-relaxed text-[var(--sp-text-primary)]">${renderInline(trimmed)}</p>`)
    i++
  }

  flushList()
  return out.join('\n')
}
