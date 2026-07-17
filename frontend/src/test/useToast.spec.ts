import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'

describe('useToast', () => {
  let useToast: typeof import('../composables/useToast').useToast

  beforeEach(async () => {
    vi.useFakeTimers()
    // 每次测试重新导入模块以重置单例状态
    vi.resetModules()
    useToast = (await import('../composables/useToast')).useToast
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('show 添加一条 toast', () => {
    const { toasts, show } = useToast()
    show('操作成功', 'success')
    expect(toasts.value).toHaveLength(1)
    expect(toasts.value[0].message).toBe('操作成功')
    expect(toasts.value[0].type).toBe('success')
  })

  it('默认类型为 info', () => {
    const { toasts, show } = useToast()
    show('提示信息')
    expect(toasts.value[0].type).toBe('info')
  })

  it('success 快捷方法设置 type=success', () => {
    const { toasts, success } = useToast()
    success('保存成功')
    expect(toasts.value[0].type).toBe('success')
  })

  it('error 快捷方法设置 type=error', () => {
    const { toasts, error } = useToast()
    error('操作失败')
    expect(toasts.value[0].type).toBe('error')
  })

  it('info 快捷方法设置 type=info', () => {
    const { toasts, info } = useToast()
    info('一般提示')
    expect(toasts.value[0].type).toBe('info')
  })

  it('默认 4000ms 后自动移除', () => {
    const { toasts, show } = useToast()
    show('临时消息')
    expect(toasts.value).toHaveLength(1)
    vi.advanceTimersByTime(4000)
    expect(toasts.value).toHaveLength(0)
  })

  it('error 类型 5000ms 后自动移除', () => {
    const { toasts, error } = useToast()
    error('错误消息')
    vi.advanceTimersByTime(4000)
    expect(toasts.value).toHaveLength(1)
    vi.advanceTimersByTime(1000)
    expect(toasts.value).toHaveLength(0)
  })

  it('多条 toast 独立计时', () => {
    const { toasts, show } = useToast()
    show('消息1')
    vi.advanceTimersByTime(2000)
    show('消息2')
    expect(toasts.value).toHaveLength(2)
    vi.advanceTimersByTime(2000)
    // 消息1 已到 4000ms，应被移除；消息2 仅 2000ms，仍在
    expect(toasts.value).toHaveLength(1)
    expect(toasts.value[0].message).toBe('消息2')
  })

  it('每条 toast 有唯一 id', () => {
    const { toasts, show } = useToast()
    show('a')
    show('b')
    show('c')
    const ids = toasts.value.map(t => t.id)
    expect(new Set(ids).size).toBe(3)
  })

  it('dismiss 可手动关闭指定 toast', () => {
    const { toasts, show, dismiss } = useToast()
    show('可关闭')
    const id = toasts.value[0].id
    dismiss(id)
    expect(toasts.value).toHaveLength(0)
  })

  it('clear 清空全部 toast', () => {
    const { toasts, show, clear } = useToast()
    show('a')
    show('b')
    clear()
    expect(toasts.value).toHaveLength(0)
  })

  it('空消息不会入栈', () => {
    const { toasts, show } = useToast()
    show('   ')
    show('')
    expect(toasts.value).toHaveLength(0)
  })

  it('超出上限时淘汰最早条目', () => {
    const { toasts, show } = useToast()
    for (let i = 0; i < 6; i++) {
      show(`msg-${i}`)
    }
    expect(toasts.value).toHaveLength(5)
    expect(toasts.value[0].message).toBe('msg-1')
    expect(toasts.value[4].message).toBe('msg-5')
  })

  it('支持 description 多行详情', () => {
    const { toasts, success } = useToast()
    success('批量完成', { description: 'ok: 3\nfail: 1' })
    expect(toasts.value[0].message).toBe('批量完成')
    expect(toasts.value[0].description).toBe('ok: 3\nfail: 1')
  })
})

