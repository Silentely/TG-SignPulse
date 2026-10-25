/**
 * FlowLogViewer: 测试结构化日志与最后返回内容（lastTargetMessage）的高对比度与响应式渲染。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import FlowLogViewer from '../components/FlowLogViewer.vue'

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({
    t: (k: string) => {
      const map: Record<string, string> = {
        'taskLogs.lastResponse': '最后返回内容：',
        'taskLogs.logDetail': '日志详情：',
        'logs.copy': '复制',
        'logs.copied': '已复制',
        'logs.noDetail': '暂无详情',
      }
      return map[k] || k
    },
  }),
}))

vi.mock('../composables/useToast', () => ({
  useToast: () => ({
    success: vi.fn(),
    error: vi.fn(),
  }),
}))

describe('FlowLogViewer', () => {
  it('渲染最后返回内容时采用浅色高对比度与深色适配样式，避免浅色模式灰蒙看不清', () => {
    const wrapper = mount(FlowLogViewer, {
      props: {
        lastTargetMessage: '签到成功！此次签到获得积分:2',
      },
    })

    expect(wrapper.text()).toContain('最后返回内容：')
    expect(wrapper.text()).toContain('签到成功！此次签到获得积分:2')

    // 找到最后返回内容的容器
    const container = wrapper.find('.bg-emerald-50\\/80')
    expect(container.exists()).toBe(true)

    const classes = container.classes()
    // 浅色模式应具备高对比度深绿文本，深色模式适配浅绿文本
    expect(classes).toContain('text-emerald-900')
    expect(classes).toContain('dark:text-emerald-100')
    expect(classes).toContain('dark:bg-emerald-950/30')
    expect(classes).toContain('border-emerald-200/80')
    expect(classes).toContain('dark:border-emerald-800/50')

    // 严禁浅色下直接使用低对比度或灰暗背景样式
    expect(classes).not.toContain('bg-emerald-950/20')
    expect(classes.some((c) => c === 'text-emerald-100')).toBe(false)
  })

  it('紧凑模式下应用对应字体样式', () => {
    const wrapper = mount(FlowLogViewer, {
      props: {
        lastTargetMessage: '测试返回',
        compact: true,
      },
    })

    const container = wrapper.find('.bg-emerald-50\\/80')
    expect(container.exists()).toBe(true)
    expect(container.classes()).toContain('text-[11px]')
  })
})
