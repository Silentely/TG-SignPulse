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
  getDataDictStats: vi.fn(),
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
    vi.mocked(dataDictApi.getDataDictStats).mockResolvedValue({
      dicts: {},
      total: 0,
      dict_count: 0,
    })
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

  it('渲染使用概览 KPI 与每个字典的使用次数角标', async () => {
    vi.mocked(dataDictApi.listDataDicts).mockResolvedValue(dicts(3))
    vi.mocked(dataDictApi.getDataDictStats).mockResolvedValue({
      dicts: {
        dict_1: { count: 12, last_used: '2026-11-13T10:00:00' },
        dict_2: { count: 3, last_used: '2026-11-13T09:00:00' },
      },
      total: 15,
      dict_count: 2,
    })
    const wrapper = mountSettings()
    await flushPromises()

    // 三个 KPI：字典组数 3、词条总数 9、累计抽取 15
    expect(wrapper.text()).toContain('字典组数')
    expect(wrapper.text()).toContain('词条总数')
    expect(wrapper.text()).toContain('累计抽取')
    expect(wrapper.text()).toContain('15')

    // 已使用字典显示「已用 N 次」，未使用字典显示「未使用」
    expect(wrapper.text()).toContain('已用 12 次')
    expect(wrapper.text()).toContain('已用 3 次')
    expect(wrapper.text()).toContain('未使用')
  })

  it('统计接口失败时降级显示，不影响字典列表', async () => {
    vi.mocked(dataDictApi.listDataDicts).mockResolvedValue(dicts(3))
    vi.mocked(dataDictApi.getDataDictStats).mockRejectedValue(new Error('boom'))
    const wrapper = mountSettings()
    await flushPromises()

    // 累计抽取降级为「—」，列表仍完整渲染
    expect(wrapper.text()).toContain('—')
    expect(wrapper.findAll('span.font-mono.font-semibold').length).toBe(3)
    // 无统计数据时不显示「未使用」角标
    expect(wrapper.text()).not.toContain('未使用')
  })

  it('宽屏使用双栏布局容器', async () => {
    vi.mocked(dataDictApi.listDataDicts).mockResolvedValue(dicts(3))
    const wrapper = mountSettings()
    await flushPromises()

    const grid = wrapper.find('.grid.lg\\:grid-cols-\\[minmax\\(0\\,2fr\\)_minmax\\(0\\,3fr\\)\\]')
    expect(grid.exists()).toBe(true)
  })
})
