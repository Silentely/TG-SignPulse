import { mount } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import i18n from '../i18n'
import PluginsSettings from '../components/settings/PluginsSettings.vue'
import * as pluginsApi from '../lib/api/plugins'
import { useConfirm } from '../composables/useConfirm'

vi.mock('../lib/api/core', () => ({
  withToken: vi.fn((cb) => cb('mock-token')),
  getAuthToken: vi.fn(() => 'mock-token'),
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({
    query: {},
  }),
  useRouter: () => ({
    replace: vi.fn(),
    push: vi.fn(),
  }),
}))

describe('PluginsSettings.vue 插件市场功能', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(pluginsApi, 'getPlugins').mockResolvedValue([])
    vi.spyOn(pluginsApi, 'getPluginDiagnostics').mockResolvedValue({
      total_loaded: 0,
      total_errors: 0,
      load_errors: [],
    })
  })

  it('切换到插件市场标签页并加载展示社区插件列表', async () => {
    const mockPlugins: pluginsApi.MarketPluginItem[] = [
      {
        id: 'bing_daily_quote',
        name: '必应每日一图',
        version: '1.0.0',
        mode: 'active',
        category: 'notification',
        description: '每日定时向指定群组推送必应高清美图',
        author: 'TG-SignPulse Team',
        download_url: 'https://raw.githubusercontent.com/.../bing_daily_quote.zip',
        tags: ['bing', 'daily'],
        installed: false,
        installed_is_builtin: false,
        status: 'not_installed',
      },
      {
        id: 'crypto_price_tracker',
        name: '加密货币行情',
        version: '1.1.0',
        mode: 'reactive',
        category: 'message',
        description: '自动解析并查询币种行情',
        author: 'TG-SignPulse Team',
        download_url: 'https://raw.githubusercontent.com/.../crypto.zip',
        tags: ['crypto', 'price'],
        installed: true,
        installed_version: '1.0.0',
        installed_is_builtin: false,
        status: 'upgradable',
      },
    ]

    const getCatalogSpy = vi.spyOn(pluginsApi, 'getMarketCatalog').mockResolvedValueOnce({
      total: 2,
      source_type: 'github',
      source_url: 'https://raw.githubusercontent.com/...',
      plugins: mockPlugins,
      cached: false,
    })

    const getSourceSpy = vi.spyOn(pluginsApi, 'getMarketSource').mockResolvedValueOnce({
      source_type: 'github',
      custom_url: '',
      active_url: 'https://raw.githubusercontent.com/...',
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    // 找到市场 Tab 按钮并点击
    const tabButtons = wrapper.findAll('button')
    const marketTab = tabButtons.find((btn) => btn.text().includes('插件市场'))
    expect(marketTab).toBeDefined()
    await marketTab!.trigger('click')

    expect(getCatalogSpy).toHaveBeenCalled()
    expect(getSourceSpy).toHaveBeenCalled()

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('必应每日一图')
      expect(wrapper.text()).toContain('加密货币行情')
      expect(wrapper.text()).toContain('可更新')
      expect(wrapper.text()).toContain('未安装')
    })
  })

  it('支持一键安装插件并在安装后刷新列表', async () => {
    const mockPlugins: pluginsApi.MarketPluginItem[] = [
      {
        id: 'bing_daily_quote',
        name: '必应每日一图',
        version: '1.0.0',
        mode: 'active',
        category: 'notification',
        description: '每日定时向指定群组推送必应高清美图',
        author: 'TG-SignPulse Team',
        download_url: 'https://...',
        installed: false,
        installed_is_builtin: false,
        status: 'not_installed',
      },
    ]

    vi.spyOn(pluginsApi, 'getMarketCatalog').mockResolvedValue({
      total: 1,
      source_type: 'github',
      source_url: 'https://...',
      plugins: mockPlugins,
      cached: false,
    })
    vi.spyOn(pluginsApi, 'getMarketSource').mockResolvedValue({
      source_type: 'github',
      custom_url: '',
      active_url: 'https://...',
    })

    const installSpy = vi.spyOn(pluginsApi, 'installMarketPlugin').mockResolvedValueOnce({
      name: 'bing_daily_quote',
      mode: 'active',
      description: '必应每日一图',
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    const marketTab = wrapper.findAll('button').find((btn) => btn.text().includes('插件市场'))
    await marketTab!.trigger('click')

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('必应每日一图')
    })

    // 点击安装按钮
    const installBtn = wrapper.findAll('button').find((btn) => btn.text().trim() === '安装')
    expect(installBtn).toBeDefined()
    await installBtn!.trigger('click')

    expect(installSpy).toHaveBeenCalledWith('bing_daily_quote', 'mock-token')
  })

  it('支持切换镜像源并触发重新加载', async () => {
    vi.spyOn(pluginsApi, 'getMarketCatalog').mockResolvedValue({
      total: 0,
      source_type: 'jsdelivr',
      source_url: 'https://cdn.jsdelivr.net/...',
      plugins: [],
      cached: false,
    })
    vi.spyOn(pluginsApi, 'getMarketSource').mockResolvedValue({
      source_type: 'github',
      custom_url: '',
      active_url: 'https://...',
    })

    const updateSourceSpy = vi.spyOn(pluginsApi, 'updateMarketSource').mockResolvedValueOnce({
      source_type: 'jsdelivr',
      custom_url: '',
      active_url: 'https://cdn.jsdelivr.net/...',
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    const marketTab = wrapper.findAll('button').find((btn) => btn.text().includes('插件市场'))
    await marketTab!.trigger('click')

    await vi.waitFor(() => {
      const select = wrapper.find('select')
      expect(select.exists()).toBe(true)
    })

    const select = wrapper.find('select')
    await select.setValue('jsdelivr')
    await select.trigger('change')

    expect(updateSourceSpy).toHaveBeenCalledWith('jsdelivr', undefined, 'mock-token')
  })

  it('支持一键更新可更新插件', async () => {
    const mockPlugins: pluginsApi.MarketPluginItem[] = [
      {
        id: 'crypto_price_tracker',
        name: '加密货币行情',
        version: '1.1.0',
        mode: 'reactive',
        category: 'message',
        description: '自动解析并查询币种行情',
        author: 'TG-SignPulse Team',
        download_url: 'https://...',
        installed: true,
        installed_version: '1.0.0',
        installed_is_builtin: false,
        status: 'upgradable',
      },
    ]

    vi.spyOn(pluginsApi, 'getMarketCatalog').mockResolvedValue({
      total: 1,
      source_type: 'github',
      source_url: 'https://...',
      plugins: mockPlugins,
      cached: false,
    })
    vi.spyOn(pluginsApi, 'getMarketSource').mockResolvedValue({
      source_type: 'github',
      custom_url: '',
      active_url: 'https://...',
    })

    const updateSpy = vi.spyOn(pluginsApi, 'updateMarketPlugin').mockResolvedValueOnce({
      name: 'crypto_price_tracker',
      mode: 'reactive',
      description: '加密货币行情',
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    const marketTab = wrapper.findAll('button').find((btn) => btn.text().includes('插件市场'))
    await marketTab!.trigger('click')

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('加密货币行情')
    })

    const updateBtn = wrapper.findAll('button').find((btn) => btn.text().includes('更新 v1.1.0'))
    expect(updateBtn).toBeDefined()
    await updateBtn!.trigger('click')

    expect(updateSpy).toHaveBeenCalledWith('crypto_price_tracker', 'mock-token')
  })

  it('支持点击查看文档打开 README 弹窗', async () => {
    const mockPlugins: pluginsApi.MarketPluginItem[] = [
      {
        id: 'dice_roller',
        name: '掷骰子与抽签',
        version: '1.0.0',
        mode: 'reactive',
        category: 'entertainment',
        description: '掷骰子插件',
        author: 'TG-SignPulse Team',
        download_url: 'https://...',
        readme: '# 掷骰子说明文档\n\n使用方法：发送 /roll 即可掷骰子。',
        installed: false,
        installed_is_builtin: false,
        status: 'not_installed',
      },
    ]

    vi.spyOn(pluginsApi, 'getMarketCatalog').mockResolvedValue({
      total: 1,
      source_type: 'github',
      source_url: 'https://...',
      plugins: mockPlugins,
      cached: false,
    })
    vi.spyOn(pluginsApi, 'getMarketSource').mockResolvedValue({
      source_type: 'github',
      custom_url: '',
      active_url: 'https://...',
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    const marketTab = wrapper.findAll('button').find((btn) => btn.text().includes('插件市场'))
    await marketTab!.trigger('click')

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('掷骰子与抽签')
    })

    const docBtn = wrapper.findAll('button').find((btn) => btn.text().includes('文档说明'))
    expect(docBtn).toBeDefined()
    await docBtn!.trigger('click')

    await vi.waitFor(() => {
      expect(document.body.textContent).toContain('使用方法：发送 /roll 即可掷骰子。')
    })
  })
  it('支持展示升级版本对比与一键全部更新可升级插件', async () => {
    const { accept } = useConfirm()
    const mockPlugins: pluginsApi.MarketPluginItem[] = [
      {
        id: 'crypto_price_tracker',
        name: '加密货币行情',
        version: '1.2.0',
        mode: 'reactive',
        category: 'message',
        description: '行情插件',
        author: 'TG-SignPulse Team',
        download_url: 'https://...',
        installed: true,
        installed_version: '1.0.0',
        installed_is_builtin: false,
        status: 'upgradable',
      },
    ]

    vi.spyOn(pluginsApi, 'getMarketCatalog').mockResolvedValue({
      total: 1,
      source_type: 'github',
      source_url: 'https://...',
      plugins: mockPlugins,
      cached: false,
    })
    vi.spyOn(pluginsApi, 'getMarketSource').mockResolvedValue({
      source_type: 'github',
      custom_url: '',
      active_url: 'https://...',
    })
    const updateSpy = vi.spyOn(pluginsApi, 'updateMarketPlugin').mockResolvedValue({
      name: 'crypto_price_tracker',
      mode: 'reactive',
      description: '行情插件',
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    const marketTab = wrapper.findAll('button').find((btn) => btn.text().includes('插件市场'))
    await marketTab!.trigger('click')

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('v1.0.0 → v1.2.0')
    })

    const updateAllBtn = wrapper.findAll('button').find((btn) => btn.text().includes('一键更新全部'))
    expect(updateAllBtn).toBeDefined()
    await updateAllBtn!.trigger('click')
    accept()

    await vi.waitFor(() => {
      expect(updateSpy).toHaveBeenCalledWith('crypto_price_tracker', 'mock-token')
    })
  })

  it('市场加载失败时展示网络异常提示并支持快速切换镜像源', async () => {
    vi.spyOn(pluginsApi, 'getMarketCatalog').mockRejectedValueOnce(new Error('Network connection timeout'))
    vi.spyOn(pluginsApi, 'getMarketSource').mockResolvedValue({
      source_type: 'github',
      custom_url: '',
      active_url: 'https://raw.githubusercontent.com/...',
    })
    const updateSourceSpy = vi.spyOn(pluginsApi, 'updateMarketSource').mockResolvedValue({
      source_type: 'jsdelivr',
      custom_url: null,
      active_url: 'https://cdn.jsdelivr.net/...',
    })

    const wrapper = mount(PluginsSettings, {
      global: { plugins: [i18n] },
    })

    const marketTab = wrapper.findAll('button').find((btn) => btn.text().includes('插件市场'))
    await marketTab!.trigger('click')

    await vi.waitFor(() => {
      expect(wrapper.text()).toContain('插件市场清单加载失败')
      expect(wrapper.text()).toContain('Network connection timeout')
    })

    const switchBtn = wrapper.findAll('button').find((btn) => btn.text().includes('切换至 jsDelivr CDN 镜像'))
    expect(switchBtn).toBeDefined()
    await switchBtn!.trigger('click')

    expect(updateSourceSpy).toHaveBeenCalledWith('jsdelivr', undefined, 'mock-token')
  })
})
