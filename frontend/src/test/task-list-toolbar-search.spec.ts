import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import TaskListToolbar from '../components/tasks/TaskListToolbar.vue'

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

const baseProps = {
  searchQuery: '',
  modeFilter: 'all' as const,
  allSelected: false,
  selectedCount: 0,
  batchBusy: false,
  listenTaskCount: 0,
  hasListFilters: false,
  accountFilter: '',
  showTemplateMenu: false,
}

describe('TaskListToolbar 搜索状态', () => {
  it('输入搜索会立即同步父级，清除后不会恢复旧查询', async () => {
    const wrapper = mount(TaskListToolbar, {
      props: { ...baseProps, searchQuery: 'old', hasListFilters: true },
    })
    const input = wrapper.find('input[type="search"]')

    await input.setValue('new')
    await wrapper.find('button[title="common.clearFilters"]').trigger('click')

    expect(wrapper.emitted('update:searchQuery')).toEqual([['new'], ['']])
    wrapper.unmount()
  })

  it('父级外部清空搜索时会同步输入框且不会产生额外回写', async () => {
    const wrapper = mount(TaskListToolbar, {
      props: { ...baseProps, searchQuery: 'old', hasListFilters: true },
    })
    const input = wrapper.find('input[type="search"]')

    await input.setValue('new')
    await wrapper.setProps({ searchQuery: '' })
    await wrapper.vm.$nextTick()

    expect(wrapper.emitted('update:searchQuery')).toEqual([['new']])
    expect((input.element as HTMLInputElement).value).toBe('')
    wrapper.unmount()
  })
})
