import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import i18n from '../i18n'
import DataDictSettings from '../components/settings/DataDictSettings.vue'
import { useAuthStore } from '../stores/auth'
import * as dataDictApi from '../lib/api/data-dict'

vi.mock('../lib/api/data-dict', () => ({
  listDataDicts: vi.fn(),
  listBuiltinDataDicts: vi.fn(),
  getDataDict: vi.fn(),
  saveDataDict: vi.fn(),
  deleteDataDict: vi.fn(),
  sampleDataDictEntry: vi.fn(),
  createDataDictFromBuiltin: vi.fn(),
}))

const dicts = (count: number) =>
  Array.from({ length: count }, (_, index) => ({
    name: `dict_${index + 1}`,
    count: 3,
    remark: index % 2 === 0 ? '问候语' : '签到',
    updated_at: '2026-11-13T10:00:00',
  }))

const mountSettings = () => mount(DataDictSettings, { global: { plugins: [i18n] } })

describe('DataDictSettings 我的字典列表', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    useAuthStore().setToken('tok')
    vi.mocked(dataDictApi.listBuiltinDataDicts).mockResolvedValue([])
  })

  it('字典较少时不显示搜索框', async () => {
    vi.mocked(dataDictApi.listDataDicts).mockResolvedValue(dicts(3))
    const wrapper = mountSettings()
    await flushPromises()

    expect(wrapper.find('input[placeholder="搜索字典"]').exists()).toBe(false)
    expect(wrapper.findAll('span.font-mono.font-semibold').length).toBe(3)
  })

  it('字典较多时显示搜索框，并可按名称或备注过滤', async () => {
    vi.mocked(dataDictApi.listDataDicts).mockResolvedValue(dicts(8))
    const wrapper = mountSettings()
    await flushPromises()

    const search = wrapper.get('input[placeholder="搜索字典"]')
    await search.setValue('dict_2')
    expect(wrapper.findAll('span.font-mono.font-semibold').length).toBe(1)
    expect(wrapper.text()).toContain('dict_2')

    await search.setValue('问候语')
    expect(wrapper.findAll('span.font-mono.font-semibold').length).toBe(4)

    await search.setValue('不存在')
    expect(wrapper.text()).toContain('没有匹配的字典')
  })

  it('列表使用限高滚动容器，避免字典增多时卡片无限变高', async () => {
    vi.mocked(dataDictApi.listDataDicts).mockResolvedValue(dicts(20))
    const wrapper = mountSettings()
    await flushPromises()

    const list = wrapper.get('div.max-h-\\[min\\(60vh\\,420px\\)\\]')
    expect(list.classes()).toContain('overflow-y-auto')
    expect(list.findAll('span.font-mono.font-semibold').length).toBe(20)
  })
})
