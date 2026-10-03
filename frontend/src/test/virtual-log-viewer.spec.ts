import { mount } from '@vue/test-utils'
import { describe, it, expect } from 'vitest'
import VirtualLogViewer from '../components/common/VirtualLogViewer.vue'

describe('VirtualLogViewer', () => {
  it('renders only visible slice of lines plus buffer', () => {
    const lines = Array.from({ length: 5000 }, (_, i) => `log line ${i}`)
    const wrapper = mount(VirtualLogViewer, {
      props: { lines, itemHeight: 24, containerHeight: 240 },
    })
    expect(wrapper.findAll('.log-line').length).toBeLessThan(35)
  })

  it('calculates top and bottom spacers correctly for initial viewport', () => {
    const lines = Array.from({ length: 1000 }, (_, i) => `line ${i}`)
    const wrapper = mount(VirtualLogViewer, {
      props: { lines, itemHeight: 20, containerHeight: 200, buffer: 2 },
    })

    // At scrollTop = 0: startIndex = 0 (topSpacer = 0)
    // visibleCount = 200/20 = 10, endIndex = 0 + 10 + 2 = 12
    // bottomSpacer = (1000 - 12) * 20 = 988 * 20 = 19760px
    const bottomSpacer = wrapper.find('.virtual-spacer-bottom')
    expect(bottomSpacer.exists()).toBe(true)
    expect(bottomSpacer.attributes('style')).toContain('19760px')

    const linesRendered = wrapper.findAll('.log-line')
    expect(linesRendered.length).toBe(12)
    expect(linesRendered[0].text()).toBe('line 0')
    expect(linesRendered[11].text()).toBe('line 11')
  })

  it('updates rendered slice and spacers when scrolling', async () => {
    const lines = Array.from({ length: 500 }, (_, i) => `line ${i}`)
    const wrapper = mount(VirtualLogViewer, {
      props: { lines, itemHeight: 20, containerHeight: 200, buffer: 2 },
    })

    const container = wrapper.find('.virtual-log-viewer')
    // Simulate scroll to scrollTop = 1000 (which corresponds to item index 50)
    Object.defineProperty(container.element, 'scrollTop', {
      value: 1000,
      writable: true,
    })
    await container.trigger('scroll')

    // startIndex = 50 - 2 = 48 -> topSpacer = 48 * 20 = 960px
    // visibleCount = 10 -> raw endIndex = 50 + 10 + 2 = 62
    // bottomSpacer = (500 - 62) * 20 = 438 * 20 = 8760px
    const topSpacer = wrapper.find('.virtual-spacer-top')
    expect(topSpacer.exists()).toBe(true)
    expect(topSpacer.attributes('style')).toContain('960px')

    const bottomSpacer = wrapper.find('.virtual-spacer-bottom')
    expect(bottomSpacer.exists()).toBe(true)
    expect(bottomSpacer.attributes('style')).toContain('8760px')

    const linesRendered = wrapper.findAll('.log-line')
    expect(linesRendered.length).toBe(14)
    expect(linesRendered[0].text()).toBe('line 48')
    expect(linesRendered[linesRendered.length - 1].text()).toBe('line 61')
  })

  it('applies custom lineTone or default tones', () => {
    const lines = [
      'Task failed with error',
      'Task completed successfully',
      'Warning: slow response',
      'Normal log message',
    ]
    const wrapper = mount(VirtualLogViewer, {
      props: { lines },
    })

    const rendered = wrapper.findAll('.log-line')
    expect(rendered[0].classes()).toContain('text-rose-400')
    expect(rendered[1].classes()).toContain('text-emerald-400')
    expect(rendered[2].classes()).toContain('text-amber-400')
    expect(rendered[3].classes()).toContain('text-green-400')
  })

  it('supports custom lineTone callback', () => {
    const lines = ['custom line']
    const wrapper = mount(VirtualLogViewer, {
      props: {
        lines,
        lineTone: () => 'custom-class',
      },
    })
    expect(wrapper.find('.log-line').classes()).toContain('custom-class')
  })

  it('displays emptyText when lines is empty', () => {
    const wrapper = mount(VirtualLogViewer, {
      props: { lines: [], emptyText: 'No logs available' },
    })
    expect(wrapper.findAll('.log-line').length).toBe(0)
    expect(wrapper.text()).toContain('No logs available')
  })

  it('exposes containerRef and scrollToBottom', () => {
    const wrapper = mount(VirtualLogViewer, {
      props: { lines: ['line 1', 'line 2'] },
    })
    expect(wrapper.vm.containerRef).toBeDefined()
    expect(typeof wrapper.vm.scrollToBottom).toBe('function')
  })
})
