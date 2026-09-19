import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mockI18nPassthrough } from './composable-test-utils'
import TaskFormTargetSection from '../components/tasks/TaskFormTargetSection.vue'
import * as api from '../lib/api'

vi.mock('../composables/useI18n', () => ({
  useI18n: () => mockI18nPassthrough(),
}))

vi.mock('../lib/api', async () => {
  const actual = await vi.importActual<typeof import('../lib/api')>('../lib/api')
  return {
    ...actual,
    listAccountFolders: vi.fn(),
    listForumTopics: vi.fn(),
  }
})

vi.mock('../lib/api/core', () => ({
  getAuthToken: () => 'mock-token',
}))

describe('TaskFormTargetSection - Folders and Topics', () => {
  const sampleChats = [
    { id: 1001, title: 'Chat 1001', type: 'group' },
    { id: 1002, title: 'Chat 1002', type: 'supergroup' },
    { id: 1003, title: 'Chat 1003', type: 'channel' },
  ]

  const sampleFolders = [
    { id: 'all', title: '全部', pinned_peers: [], include_peers: [] },
    { id: 1, title: '工作群', pinned_peers: [], include_peers: [1001, 1002] },
    { id: 2, title: '频道', pinned_peers: [], include_peers: [1003] },
  ]

  const sampleTopics = [
    { id: 10, title: '日常打卡', closed: false },
    { id: 20, title: '公告区', closed: true },
  ]

  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(api.listAccountFolders).mockResolvedValue(sampleFolders)
    vi.mocked(api.listForumTopics).mockResolvedValue([])
  })

  const mountSection = (props = {}) =>
    mount(TaskFormTargetSection, {
      props: {
        isEditing: false,
        createMode: 'shared',
        targetChats: [],
        activeChatIndex: 0,
        selectedAccount: 'acc1',
        selectedAccounts: ['acc1'],
        selectedChatId: 0,
        messageThreadId: '',
        senderFilter: '',
        showAdvanced: false,
        availableChats: sampleChats as any,
        chatSearch: '',
        chatSearchResults: [],
        chatSearchLoading: false,
        chatListRefreshing: false,
        chatListError: '',
        bulkSelectedChatIds: [],
        ...props,
      },
      global: {
        stubs: {
          CustomSelect: {
            props: ['options', 'modelValue'],
            emits: ['update:modelValue'],
            template: `
              <div class="custom-select-stub">
                <button
                  v-for="opt in options"
                  :key="opt.value"
                  :data-value="opt.value"
                  @click="$emit('update:modelValue', opt.value)"
                >
                  {{ opt.label }}
                </button>
              </div>
            `,
          },
        },
      },
    })

  it('fetches and renders chat folders', async () => {
    const wrapper = mountSection()
    await flushPromises()

    expect(api.listAccountFolders).toHaveBeenCalledWith('mock-token', 'acc1')
    const buttons = wrapper.findAll('button')
    const folderButtons = buttons.filter((b) =>
      ['全部', '工作群', '频道'].some((name) => b.text().includes(name)),
    )
    expect(folderButtons.length).toBe(3)
  })

  it('filters available chats when a folder is clicked', async () => {
    const wrapper = mountSection()
    await flushPromises()

    // Click on '工作群' folder (which includes 1001 and 1002)
    const workFolderBtn = wrapper
      .findAll('button')
      .find((b) => b.text().includes('工作群'))
    expect(workFolderBtn).toBeDefined()
    await workFolderBtn!.trigger('click')
    await flushPromises()

    // Inspect the chat list labels inside the bulk picker
    const chatLabels = wrapper.findAll('.ui-checkbox')
    expect(chatLabels.length).toBe(2)
  })

  it('fetches forum topics when a chat is selected and shows topic selector', async () => {
    vi.mocked(api.listForumTopics).mockResolvedValue(sampleTopics)

    const wrapper = mountSection({ selectedChatId: 1002 })
    await flushPromises()

    expect(api.listForumTopics).toHaveBeenCalledWith('mock-token', 'acc1', 1002)
    expect(wrapper.text()).toContain('taskForm.forumTopic')

    // Find topic option button for '日常打卡' (value: '10')
    const topicBtn = wrapper.find('[data-value="10"]')
    expect(topicBtn.exists()).toBe(true)

    await topicBtn.trigger('click')
    expect(wrapper.emitted('update:messageThreadId')).toBeTruthy()
    expect(wrapper.emitted('update:messageThreadId')![0]).toEqual(['10'])
  })

  it('handles main timeline (value 0) topic selection', async () => {
    vi.mocked(api.listForumTopics).mockResolvedValue(sampleTopics)

    const wrapper = mountSection({ selectedChatId: 1002, messageThreadId: '10' })
    await flushPromises()

    // Query CustomSelect inside the forum topic section
    const topicSection = wrapper.find('.bg-sky-50\\/50')
    expect(topicSection.exists()).toBe(true)
    const mainTimelineBtn = topicSection.find('[data-value="0"]')
    expect(mainTimelineBtn.exists()).toBe(true)

    await mainTimelineBtn.trigger('click')
    expect(wrapper.emitted('update:messageThreadId')).toBeTruthy()
    expect(wrapper.emitted('update:messageThreadId')![0]).toEqual([''])
  })
})
