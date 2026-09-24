import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import EditAccountModal from '../components/accounts/EditAccountModal.vue'

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({ t: (k: string) => k }),
}))

vi.mock('../composables/useToast', () => ({
  useToast: () => ({ success: vi.fn(), error: vi.fn() }),
}))

// 只关心 closed 事件的转发链路，Modal 用最小替身
const ModalStub = defineComponent({
  name: 'Modal',
  emits: ['close', 'closed'],
  template: `<div><button class="fire-closed" @click="$emit('closed')">x</button></div>`,
})

const account = {
  name: 'acc-a',
  remark: '',
  raw: { proxy: '' },
} as never

function mountModal() {
  return mount(EditAccountModal, {
    props: { isOpen: true, account },
    global: { stubs: { Modal: ModalStub } },
  })
}

describe('EditAccountModal closed 事件', () => {
  it('在 emits 中显式声明 closed，不依赖 $attrs 透传', () => {
    const emits = (EditAccountModal as { emits?: string[] | Record<string, unknown> }).emits
    const names = Array.isArray(emits) ? emits : Object.keys(emits || {})
    expect(names).toContain('closed')
  })

  it('把 Modal 的 closed 转发给父组件', async () => {
    const wrapper = mountModal()
    await wrapper.find('.fire-closed').trigger('click')
    expect(wrapper.emitted('closed')).toHaveLength(1)
  })
})
