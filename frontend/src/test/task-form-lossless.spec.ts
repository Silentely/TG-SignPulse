import { describe, expect, it, vi } from 'vitest'
import { defineComponent } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { buildTaskMetadataPatch, buildTargetFlowPatch } from '../lib/task-form-payload'
import type { SignTask } from '../lib/api'
import TaskForm from '../components/tasks/TaskForm.vue'
import EditTaskModal from '../components/tasks/EditTaskModal.vue'

const api = vi.hoisted(() => ({
  listAccounts: vi.fn(async () => ({ accounts: [{ name: 'a' }] })),
  getAccountChats: vi.fn(async () => []),
  searchAccountChats: vi.fn(async () => []),
  updateSignTask: vi.fn(async (..._args: unknown[]) => ({})),
}))
vi.mock('../lib/api', () => api)
vi.mock('../lib/api/core', () => ({ getAuthToken: () => 'token' }))
vi.mock('../composables/useI18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('../composables/useToast', () => ({ useToast: () => ({ error: vi.fn(), show: vi.fn() }) }))

const original = {
  name: 'daily', account_name: 'a', account_names: ['a'], revision: 'rev1',
  sign_at: '09:00', random_seconds: 12, sign_interval: 5, enabled: true, tags: ['old'],
  chats: [
    { chat_id: 1, name: 'one', action_interval: 7, actions: [{ action: 1, text: 'one', extension: 1 }], custom: { keep: true } },
    { chat_id: 2, name: 'two', action_interval: 19, steps: [{ id: 'entry', type: 'send_message' }], initial_step_id: 'entry', flow_graph: { version: 1, nodes: [] }, extra: 'keep' },
  ],
} as unknown as SignTask

describe('lossless task updates', () => {
  it('only masks metadata that changed, preserving raw per-target configurations', () => {
    const before = structuredClone(original)
    const patch = buildTaskMetadataPatch(original, { tags: ['new'], chats: [], random_seconds: 0 })
    expect(patch).toEqual({ revision: 'rev1', field_mask: ['tags'], tags: ['new'] })
    expect(original).toEqual(before)
  })

  it('emits explicit nulls when clearing a task chain field', () => {
    const chained = { ...original, next_task_on_success: 'later', next_task_delay_seconds: 10 } as SignTask
    const patch = buildTaskMetadataPatch(
      chained,
      { next_task_on_success: null, next_task_delay_seconds: null },
      { next_task_on_success: 'later', next_task_delay_seconds: 10 },
    )
    expect(patch).toEqual({
      revision: 'rev1',
      field_mask: ['next_task_on_success', 'next_task_delay_seconds'],
      next_task_on_success: null,
      next_task_delay_seconds: null,
    })
  })

  it('updates only the explicitly edited target and retains its unknown fields and interval', () => {
    const patch = buildTargetFlowPatch(original, '1:', { actions: [{ action: 1, text: 'changed' }] })!
    expect(patch.field_mask).toEqual(['chats'])
    expect(patch.chats![1]).toEqual(original.chats[1])
    expect(patch.chats![0]).toEqual({ ...original.chats[0], actions: [{ action: 1, text: 'changed' }] })
    expect(buildTargetFlowPatch(original, 'missing:', { actions: [] })).toBeNull()
  })

  it('initializes the form without leaking normalized defaults or replacing advanced targets', async () => {
    const wrapper = mount(TaskForm, {
      props: { initialTask: original, lockTaskName: true },
      global: { stubs: { CustomSelect: true, MultiSelect: true, TaskFormTargetSection: true, TaskFormListenSection: true, TaskFormActionsSection: true } },
    })
    await flushPromises()
    expect(wrapper.vm.buildMetadataPatch()).toEqual({ revision: 'rev1', field_mask: [] })
    expect(wrapper.vm.buildUpdatePatch()).toEqual({ revision: 'rev1', field_mask: [] })
    wrapper.unmount()
  })

  it('validates the edit form before attempting a save', async () => {
    api.updateSignTask.mockClear()
    const validate = vi.fn(() => false)
    const form = defineComponent({
      setup(_, { expose }) { expose({ validateForSubmit: validate, buildUpdatePatch: () => ({}) }); return {} },
      template: '<div />',
    })
    const modal = defineComponent({ template: '<div><slot /><slot name="footer" /></div>' })
    const wrapper = mount(EditTaskModal, {
      props: { isOpen: true, task: original },
      global: { stubs: { TaskForm: form, Modal: modal } },
    })
    await wrapper.get('button.ui-btn-primary').trigger('click')
    expect(validate).toHaveBeenCalledOnce()
    expect(api.updateSignTask).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('edits one target only after explicit opt-in and keeps the advanced target intact', async () => {
    const wrapper = mount(TaskForm, {
      props: { initialTask: original, lockTaskName: true },
      global: { stubs: { CustomSelect: true, MultiSelect: true, TaskFormTargetSection: true, TaskFormListenSection: true, TaskFormActionsSection: true } },
    })
    await flushPromises()
    expect(wrapper.findComponent({ name: 'TaskFormActionsSection' }).exists()).toBe(true)
    const section = wrapper.findComponent({ name: 'TaskFormActionsSection' })
    const actions = section.props('actions') as { value: string }[]
    actions[0]!.value = 'edited'
    await flushPromises()
    const patch = wrapper.vm.buildUpdatePatch()
    expect(patch.field_mask).toEqual(['chats'])
    expect(patch.chats![0]!.actions![0]!.text).toBe('edited')
    expect(patch.chats![0]!.action_interval).toBe(7)
    expect(patch.chats![1]).toEqual(original.chats[1])
    expect(wrapper.vm.buildFlowPatch('2:')).toBeNull()
    wrapper.unmount()
  })

  it('shows action editor for reply-confirmation steps that can be reconstructed', async () => {
    const replyTask = {
      ...original,
      chats: [{
        chat_id: 3,
        name: 'reply-bot',
        action_interval: 1,
        steps: [
          { step_id: 'step_0', node_type: 'action', action_type: 'SEND_TEXT', params: { text: '/checkin' }, next_step_id: 'step_0_wait' },
          { step_id: 'step_0_wait', node_type: 'wait_event', success_patterns: ['签到成功'], retry_keywords: ['稍后'], timeout_seconds: 90 },
        ],
      }],
    } as unknown as SignTask
    const wrapper = mount(TaskForm, {
      props: { initialTask: replyTask, lockTaskName: true },
      global: { stubs: { CustomSelect: true, MultiSelect: true, TaskFormTargetSection: true, TaskFormListenSection: true, TaskFormActionsSection: true } },
    })
    await flushPromises()
    expect(wrapper.findComponent({ name: 'TaskFormActionsSection' }).exists()).toBe(true)
    expect(wrapper.find('[data-testid="preserved-flow-summary"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('sends a notification-only mask from the edit modal without including flows', async () => {
    api.updateSignTask.mockClear()
    const form = defineComponent({
      setup(_, { expose }) {
        expose({ validateForSubmit: () => true, buildUpdatePatch: () => ({ revision: 'rev1', field_mask: [] }) })
        return {}
      },
      template: '<div />',
    })
    const modal = defineComponent({ template: '<div><slot name="header-extra" /><slot /><slot name="footer" /></div>' })
    const wrapper = mount(EditTaskModal, {
      props: { isOpen: true, task: original },
      global: { stubs: { TaskForm: form, Modal: modal } },
    })
    await wrapper.findAll('input[type="checkbox"]')[1]!.setValue(false)
    await wrapper.get('button.ui-btn-primary').trigger('click')
    expect(api.updateSignTask.mock.calls[0]?.[2]).toEqual({
      revision: 'rev1', field_mask: ['notify_on_success'], notify_on_success: false,
    })
    wrapper.unmount()
  })
})
