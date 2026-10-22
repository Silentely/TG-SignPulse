import { mount, flushPromises } from '@vue/test-utils'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import i18n from '../i18n'
import JevSettings from '../components/settings/JevSettings.vue'
import * as semanticApi from '../lib/api/semantic'
import * as coreApi from '../lib/api/core'

describe('JevSettings 组件测试', () => {
  beforeEach(() => {
    vi.spyOn(coreApi, 'getAuthToken').mockReturnValue('mock-token')
    vi.spyOn(semanticApi, 'getSemanticConfig').mockResolvedValue({
      enabled: true,
      drift_enabled: false,
      mode: 'official',
      base_url: 'https://api.typesafe.ai/v1',
      model: 'jev-1.13.0',
      has_api_key: true,
      api_key_masked: 'ah-1234****5678',
      timeout_seconds: 8.0,
      max_concurrency: 2,
      max_calls_per_run: 6,
      max_calls_per_minute: 60,
      retain_evidence: false,
      generation: 1,
      monitor_keys_usage: { count: 0, capacity: 10000, is_full: false },
    })
  })

  it('默认渲染官方模式，隐藏 Base URL，显示 API Key', async () => {
    const wrapper = mount(JevSettings, {
      global: { plugins: [i18n] },
    })
    await flushPromises()
    // 官方模式下不展示自定义 Base URL 输入框
    expect(wrapper.find('#jev-base-url').exists()).toBe(false)
    expect(wrapper.find('#jev-api-key').exists()).toBe(true)
  })

  it('切换到自定义模式时展示 Base URL 与提示，并可保存', async () => {
    const updateSpy = vi.spyOn(semanticApi, 'updateSemanticConfig').mockResolvedValue({
      enabled: true,
      drift_enabled: false,
      mode: 'custom',
      base_url: 'https://api.example.com/v1',
      model: 'jev',
      has_api_key: true,
      api_key_masked: 'ah-****',
      timeout_seconds: 8.0,
      max_concurrency: 2,
      max_calls_per_run: 6,
      max_calls_per_minute: 60,
      retain_evidence: false,
      generation: 2,
      monitor_keys_usage: { count: 0, capacity: 10000, is_full: false },
    })

    const wrapper = mount(JevSettings, {
      global: { plugins: [i18n] },
    })
    await flushPromises()

    // 选中自定义模式
    const customRadio = wrapper.findAll('input[type="radio"]')[1]
    await customRadio.setValue()
    await wrapper.vm.$nextTick()

    // 出现 Base URL 输入框与 /v1 提示
    const baseUrlInput = wrapper.find('#jev-base-url')
    expect(baseUrlInput.exists()).toBe(true)
    expect(wrapper.text()).toContain('/v1')
    await baseUrlInput.setValue('https://api.example.com/v1')

    // 点击保存
    const saveBtn = wrapper.find('button.ui-btn-primary')
    await saveBtn.trigger('click')
    await flushPromises()

    expect(updateSpy).toHaveBeenCalled()
    const patchArg = updateSpy.mock.calls[0][0]
    expect(patchArg.mode).toBe('custom')
    expect(patchArg.base_url).toContain('/v1')
  })

  it('测试连接成功时正确渲染状态行', async () => {
    vi.spyOn(semanticApi, 'updateSemanticConfig').mockResolvedValue({
      has_api_key: true,
      api_key_masked: 'ah-***',
    } as any)
    vi.spyOn(semanticApi, 'testSemanticConnection').mockResolvedValue({
      success: true,
      status: 'ok',
      http_status: 200,
      selected: 'pong',
      elapsed_ms: 3912,
      reason_code: '',
      error_message: '',
    })

    const wrapper = mount(JevSettings, {
      global: { plugins: [i18n] },
    })
    await flushPromises()

    const testBtn = wrapper.find('button.ui-btn-secondary')
    await testBtn.trigger('click')
    await flushPromises()

    const statusEl = wrapper.find('[role="status"]')
    expect(statusEl.exists()).toBe(true)
    expect(statusEl.text()).toContain('✅')
    expect(statusEl.text()).toContain('3.9s')
  })

  it('测试连接失败时正确渲染状态行与状态码错误摘要', async () => {
    vi.spyOn(semanticApi, 'updateSemanticConfig').mockResolvedValue({
      has_api_key: true,
      api_key_masked: 'ah-***',
    } as any)
    vi.spyOn(semanticApi, 'testSemanticConnection').mockResolvedValue({
      success: false,
      status: 'unavailable',
      http_status: 401,
      selected: 'unknown',
      elapsed_ms: 250,
      reason_code: 'AUTH_FAILED',
      error_message: 'Invalid api key',
    })

    const wrapper = mount(JevSettings, {
      global: { plugins: [i18n] },
    })
    await flushPromises()

    const testBtn = wrapper.find('button.ui-btn-secondary')
    await testBtn.trigger('click')
    await flushPromises()

    const statusEl = wrapper.find('[role="status"]')
    expect(statusEl.exists()).toBe(true)
    expect(statusEl.text()).toContain('❌')
    expect(statusEl.text()).toContain('401')
    expect(statusEl.text()).toContain('Invalid api key')
  })
  it('支持切换启用状态开关并在保存时提交 enabled', async () => {
    const updateSpy = vi.spyOn(semanticApi, 'updateSemanticConfig').mockResolvedValue({
      enabled: false,
      drift_enabled: false,
      mode: 'official',
      base_url: 'https://api.typesafe.ai/v1',
      model: 'jev-1.13.0',
      has_api_key: true,
      api_key_masked: 'ah-****',
      timeout_seconds: 8.0,
      max_concurrency: 2,
      max_calls_per_run: 6,
      max_calls_per_minute: 60,
      retain_evidence: false,
      generation: 2,
      monitor_keys_usage: { count: 0, capacity: 10000, is_full: false },
    })

    const wrapper = mount(JevSettings, {
      global: { plugins: [i18n] },
    })
    await flushPromises()

    const switchBtn = wrapper.find('[data-testid="jev-enable-switch"]')
    expect(switchBtn.exists()).toBe(true)
    expect(switchBtn.classes()).toContain('ui-switch-on')

    // 点击切换为关闭
    await switchBtn.trigger('click')
    expect(switchBtn.classes()).not.toContain('ui-switch-on')

    // 保存
    const saveBtn = wrapper.find('button.ui-btn-primary')
    await saveBtn.trigger('click')
    await flushPromises()

    expect(updateSpy).toHaveBeenCalled()
    const patchArg = updateSpy.mock.calls[0][0]
    expect(patchArg.enabled).toBe(false)
  })
})
