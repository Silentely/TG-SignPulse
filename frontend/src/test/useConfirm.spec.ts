import { describe, it, expect, beforeEach } from 'vitest'
import { useConfirm } from '../composables/useConfirm'

describe('useConfirm', () => {
  beforeEach(() => {
    const { state, cancel } = useConfirm()
    if (state.value.open) cancel()
  })

  it('opens dialog and resolves true on accept', async () => {
    const { state, confirm, accept } = useConfirm()
    const p = confirm({ title: 'T', message: 'M', danger: true })
    expect(state.value.open).toBe(true)
    expect(state.value.title).toBe('T')
    expect(state.value.danger).toBe(true)
    accept()
    await expect(p).resolves.toBe(true)
    expect(state.value.open).toBe(false)
  })

  it('resolves false on cancel', async () => {
    const { confirm, cancel } = useConfirm()
    const p = confirm({ title: 'T', message: 'M' })
    cancel()
    await expect(p).resolves.toBe(false)
  })

  it('cancels previous pending when a new confirm starts', async () => {
    const { confirm, accept } = useConfirm()
    const first = confirm({ title: 'A', message: '1' })
    const second = confirm({ title: 'B', message: '2' })
    await expect(first).resolves.toBe(false)
    accept()
    await expect(second).resolves.toBe(true)
  })
})
