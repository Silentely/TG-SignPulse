import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '../lib/markdown'

describe('renderMarkdown', () => {
  it('handles empty and whitespace-only strings gracefully', () => {
    expect(renderMarkdown('')).toBe('')
    expect(renderMarkdown('   \n  \t ')).toBe('')
  })

  it('renders headers correctly', () => {
    const md = '# Header 1\n## Header 2\n### Header 3\n#### Header 4'
    const html = renderMarkdown(md)
    expect(html).toContain('<h1 class="text-base font-bold text-[var(--sp-text-primary)] mt-4 mb-2 pb-1 border-b border-[var(--sp-border)]">Header 1</h1>')
    expect(html).toContain('<h2 class="text-sm font-semibold text-[var(--sp-text-primary)] mt-3 mb-1.5 pb-0.5 border-b border-[var(--sp-border)]/60">Header 2</h2>')
    expect(html).toContain('<h3 class="text-xs font-semibold text-[var(--sp-text-primary)] mt-2.5 mb-1">Header 3</h3>')
    expect(html).toContain('<h4 class="text-xs font-medium text-[var(--sp-text-secondary)] mt-2 mb-1">Header 4</h4>')
  })

  it('renders inline formatting (bold, italic, code, strikethrough)', () => {
    const md = 'This is **bold**, *italic*, ~~deleted~~, and `inline_code()`.'
    const html = renderMarkdown(md)
    expect(html).toContain('<strong class="font-semibold text-[var(--sp-text-primary)]">bold</strong>')
    expect(html).toContain('<em class="italic">italic</em>')
    expect(html).toContain('<del class="line-through opacity-70">deleted</del>')
    expect(html).toContain('>inline_code()</code>')
  })

  it('renders code blocks with syntax escaping', () => {
    const md = '```json\n{\n  "key": "<value>&test"\n}\n```'
    const html = renderMarkdown(md)
    expect(html).toContain('<pre')
    expect(html).toContain('data-language="json"')
    expect(html).toContain('&lt;value&gt;&amp;test')
    expect(html).not.toContain('<value>')
  })

  it('renders safe links and sanitizes malicious ones', () => {
    const md = '[Safe Web](https://example.com) and [Anchor](#english) and [Malicious](javascript:alert(1))'
    const html = renderMarkdown(md)
    expect(html).toContain('href="https://example.com"')
    expect(html).toContain('target="_blank"')
    expect(html).toContain('href="#english"')
    expect(html).not.toContain('javascript:alert(1)')
    expect(html).toContain('Malicious')
  })

  it('preserves anchor spans for multi-language navigation', () => {
    const md = '<span id="english"></span>\n# English Title'
    const html = renderMarkdown(md)
    expect(html).toContain('<span id="english"></span>')
    expect(html).toContain('English Title')
  })

  it('sanitizes dangerous HTML tags', () => {
    const md = '<script>alert("XSS")</script><img src="x" onerror="alert(1)">'
    const html = renderMarkdown(md)
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
    expect(html).not.toContain('<img')
  })

  it('renders lists properly', () => {
    const md = '- Item A\n- Item B\n- Item C\n\n1. First\n2. Second'
    const html = renderMarkdown(md)
    expect(html).toContain('<ul class="list-disc list-inside space-y-1 my-2 text-xs">')
    expect(html).toContain('<li class="leading-relaxed text-[var(--sp-text-secondary)]">Item A</li>')
    expect(html).toContain('<ol class="list-decimal list-inside space-y-1 my-2 text-xs">')
    expect(html).toContain('<li class="leading-relaxed text-[var(--sp-text-secondary)]">First</li>')
  })

  it('renders blockquotes properly', () => {
    const md = '> Note: this is a blockquote\n> spanning multiple lines.'
    const html = renderMarkdown(md)
    expect(html).toContain('<blockquote class="border-l-4 border-indigo-500/70')
    expect(html).toContain('Note: this is a blockquote spanning multiple lines.')
  })

  it('renders markdown tables properly with alignment', () => {
    const md = `
| 参数名 | 类型 | 说明 |
| :--- | :---: | ---: |
| \`delay\` | number | 延迟秒数 |
`
    const html = renderMarkdown(md)
    expect(html).toContain('<table class="w-full text-left text-xs border-collapse">')
    expect(html).toContain('<th class="p-2 border-b border-[var(--sp-border)] text-left">参数名</th>')
    expect(html).toContain('<th class="p-2 border-b border-[var(--sp-border)] text-center">类型</th>')
    expect(html).toContain('<th class="p-2 border-b border-[var(--sp-border)] text-right">说明</th>')
    expect(html).toContain('>delay</code>')
  })
})
