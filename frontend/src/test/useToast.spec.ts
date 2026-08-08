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

  it('success 添加一条 toast', () => {
    const { toasts, success } = useToast()
    success('操作成功')
    expect(toasts.value).toHaveLength(1)
    expect(toasts.value[0].message).toBe('操作成功')
    expect(toasts.value[0].type).toBe('success')
  })

  it('info 添加 info 类型 toast', () => {
    const { toasts, info } = useToast()
    info('提示信息')
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

  it('warning 快捷方法设置 type=warning', () => {
    const { toasts, warning } = useToast()
    warning('部分失败')
    expect(toasts.value[0].type).toBe('warning')
  })

  it('warning 类型 4500ms 后自动移除', () => {
    const { toasts, warning } = useToast()
    warning('警告消息')
    expect(toasts.value).toHaveLength(1)
    vi.advanceTimersByTime(4500)
    expect(toasts.value).toHaveLength(0)
  })

  it('默认 4000ms 后自动移除', () => {
    const { toasts, info } = useToast()
    info('临时消息')
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
    const { toasts, info } = useToast()
    info('消息1')
    vi.advanceTimersByTime(2000)
    info('消息2')
    expect(toasts.value).toHaveLength(2)
    vi.advanceTimersByTime(2000)
    // 消息1 已到 4000ms，应被移除；消息2 仅 2000ms，仍在
    expect(toasts.value).toHaveLength(1)
    expect(toasts.value[0].message).toBe('消息2')
  })

  it('每条 toast 有唯一 id', () => {
    const { toasts, info } = useToast()
    info('a')
    info('b')
    info('c')
    const ids = toasts.value.map(t => t.id)
    expect(new Set(ids).size).toBe(3)
  })

  it('dismiss 可手动关闭指定 toast', () => {
    const { toasts, info, dismiss } = useToast()
    info('可关闭')
    const id = toasts.value[0].id
    dismiss(id)
    expect(toasts.value).toHaveLength(0)
  })

  it('clear 清空全部 toast', () => {
    const { toasts, info, clear } = useToast()
    info('a')
    info('b')
    clear()
    expect(toasts.value).toHaveLength(0)
  })

  it('空消息不会入栈', () => {
    const { toasts, info } = useToast()
    info('   ')
    info('')
    expect(toasts.value).toHaveLength(0)
  })

  it('超出上限时淘汰最早条目', () => {
    const { toasts, info } = useToast()
    for (let i = 0; i < 6; i++) {
      info(`msg-${i}`)
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

  it('pause 暂停自动关闭倒计时', () => {
    const { toasts, info, pause } = useToast()
    info('长消息')
    const id = toasts.value[0].id
    pause(id)
    // 超过默认 4000ms 仍保留（已暂停）
    vi.advanceTimersByTime(10000)
    expect(toasts.value).toHaveLength(1)
  })

  it('resume 从剩余时长继续倒计时', () => {
    const { toasts, info, pause, resume } = useToast()
    info('长消息')
    const id = toasts.value[0].id
    vi.advanceTimersByTime(3000)
    pause(id)
    // 暂停期间不消失
    vi.advanceTimersByTime(5000)
    expect(toasts.value).toHaveLength(1)
    // 恢复后仅剩 1000ms，到达后消失
    resume(id)
    vi.advanceTimersByTime(999)
    expect(toasts.value).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(toasts.value).toHaveLength(0)
  })

  it('重复 pause 幂等，不叠加剩余时间', () => {
    const { toasts, info, pause, resume } = useToast()
    info('消息')
    const id = toasts.value[0].id
    vi.advanceTimersByTime(2000)
    pause(id)
    pause(id)
    // 暂停两次后恢复，剩余应为 2000ms 而非 4000ms
    resume(id)
    vi.advanceTimersByTime(2000)
    expect(toasts.value).toHaveLength(0)
  })

  it('dismiss 暂停中的 toast 后恢复不复活', () => {
    const { toasts, info, pause, dismiss, resume } = useToast()
    info('消息')
    const id = toasts.value[0].id
    pause(id)
    dismiss(id)
    expect(toasts.value).toHaveLength(0)
    resume(id) // 不应复活
    expect(toasts.value).toHaveLength(0)
  })

  it('clear 清理后暂停/恢复无副作用', () => {
    const { toasts, info, pause, clear, resume } = useToast()
    info('a')
    const id = toasts.value[0].id
    pause(id)
    clear()
    expect(toasts.value).toHaveLength(0)
    resume(id)
    expect(toasts.value).toHaveLength(0)
  })

  it('相同文案合并计数并重置计时', () => {
    const { toasts, error } = useToast()
    error('删除失败')
    vi.advanceTimersByTime(4000)
    // 距过期 1000ms 时再次触发：应合并而非新增
    error('删除失败')
    expect(toasts.value).toHaveLength(1)
    expect(toasts.value[0].count).toBe(2)
    // 合并后计时已重置，再过 4000ms 才消失
    vi.advanceTimersByTime(4000)
    expect(toasts.value).toHaveLength(1)
    vi.advanceTimersByTime(1000)
    expect(toasts.value).toHaveLength(0)
  })

  it('不同文案不合并，各自独立', () => {
    const { toasts, error } = useToast()
    error('删除失败')
    error('保存失败')
    expect(toasts.value).toHaveLength(2)
    expect(toasts.value.map((t) => t.count)).toEqual([1, 1])
  })

  it('合并后 dismiss 正常移除整条', () => {
    const { toasts, info, dismiss } = useToast()
    info('消息')
    info('消息')
    expect(toasts.value).toHaveLength(1)
    expect(toasts.value[0].count).toBe(2)
    dismiss(toasts.value[0].id)
    expect(toasts.value).toHaveLength(0)
  })
})

