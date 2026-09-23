/**
 * ToneBadge：运行状态徽章的 tone 推导、附加 class 合并与脉冲圆点。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ToneBadge from '../components/ToneBadge.vue'
import type { SignTaskRunStatusLike } from '../lib/run-status'

/** 构造最小运行态：SignTaskRunStatusLike 在 ActiveRunSummary 上补了 success / error 等字段 */
const run = (over: Partial<SignTaskRunStatusLike>): SignTaskRunStatusLike => ({
  run_id: 'r1',
  state: 'running',
  account_name: 'alice',
  task_name: 'daily',
  ...over,
})

describe('ToneBadge', () => {
  it('status 为 null 时回落到中性色板', () => {
    const wrapper = mount(ToneBadge, { props: { status: null }, slots: { default: '无运行' } })
    expect(wrapper.classes()).toContain('ui-badge-neutral')
    expect(wrapper.text()).toBe('无运行')
  })

  it('运行中按 phase 区分 sky / amber', () => {
    const sky = mount(ToneBadge, { props: { status: run({ phase: 'executing' }) } })
    expect(sky.classes()).toContain('bg-sky-50')
    expect(sky.classes()).not.toContain('ui-badge-neutral')

    const amber = mount(ToneBadge, { props: { status: run({ phase: 'cooldown' }) } })
    expect(amber.classes()).toContain('bg-amber-50')
  })

  it('finished 按 success 区分 emerald / rose', () => {
    const ok = mount(ToneBadge, { props: { status: run({ state: 'finished', success: true }) } })
    expect(ok.classes()).toContain('bg-emerald-50')

    const fail = mount(ToneBadge, { props: { status: run({ state: 'finished', success: false }) } })
    expect(fail.classes()).toContain('bg-rose-50')

    const timeout = mount(ToneBadge, { props: { status: run({ state: 'timeout' }) } })
    expect(timeout.classes()).toContain('bg-rose-50')
  })

  it('extraClass 与色板 class 同时保留', () => {
    const wrapper = mount(ToneBadge, {
      props: { status: run({}), extraClass: '!text-[11px] max-w-[16rem] truncate' },
      slots: { default: '运行中' },
    })
    expect(wrapper.classes()).toContain('!text-[11px]')
    expect(wrapper.classes()).toContain('truncate')
    expect(wrapper.classes()).toContain('bg-sky-50')
  })

  it('pulse 控制脉冲圆点，title 透传到根节点', () => {
    const pulsed = mount(ToneBadge, { props: { status: run({}), pulse: true, title: '提示' } })
    expect(pulsed.find('.ui-pulse-dot').exists()).toBe(true)
    expect(pulsed.attributes('title')).toBe('提示')

    const plain = mount(ToneBadge, { props: { status: run({}) } })
    expect(plain.find('.ui-pulse-dot').exists()).toBe(false)
  })
})
