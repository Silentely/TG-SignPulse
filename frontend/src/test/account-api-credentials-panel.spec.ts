import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import AccountApiCredentials from '../components/accounts/AccountApiCredentials.vue'

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: Record<string, string>) =>
      params?.hash ? `${key}:${params.hash}` : key,
  }),
}))

const mountPanel = (props: Record<string, unknown>) =>
  mount(AccountApiCredentials, {
    props: {
      apiId: '123456',
      apiHash: '',
      reloginMode: true,
      hasCustomApi: true,
      hasApiHash: true,
      apiHashMasked: 'd524****ac9c',
      keepApiId: '123456',
      ...props,
    },
  })

const expandPanel = async (wrapper: ReturnType<typeof mountPanel>) => {
  await wrapper.find('button[aria-controls]').trigger('click')
}

describe('AccountApiCredentials 重新登录回显', () => {
  it('回显已保存的 API ID，并把脱敏 Hash 作为保留提示', async () => {
    const wrapper = mountPanel({})
    await expandPanel(wrapper)

    const idInput = wrapper.find('input[id^="account-api-id-"]')
    const hashInput = wrapper.find('input[id^="account-api-hash-"]')
    expect((idInput.element as HTMLInputElement).value).toBe('123456')
    expect((hashInput.element as HTMLInputElement).value).toBe('')
    expect((hashInput.element as HTMLInputElement).placeholder).toBe(
      'accountApi.keepHashPlaceholder:d524****ac9c',
    )
    expect(wrapper.text()).toContain('accountApi.currentHash:d524****ac9c')
    expect(wrapper.text()).toContain('accountApi.reloginDescription')
    // 重登场景不提供「清除」入口，避免误解为会删除已保存凭据
    expect(wrapper.text()).not.toContain('accountApi.clear')
  })

  it('API ID 未改动时允许 Hash 留空，改动 ID 后要求补齐 Hash', async () => {
    const wrapper = mountPanel({})
    await expandPanel(wrapper)

    expect(wrapper.text()).not.toContain('accountApi.pairRequired')

    await wrapper.setProps({ apiId: '999999' })
    expect(wrapper.text()).toContain('accountApi.pairRequired')

    await wrapper.setProps({ apiId: '123456' })
    expect(wrapper.text()).not.toContain('accountApi.pairRequired')
  })

  it('账号未配置专属凭据时保留默认提示', async () => {
    const wrapper = mountPanel({
      apiId: '',
      reloginMode: true,
      hasCustomApi: false,
      hasApiHash: false,
      apiHashMasked: null,
    })
    await expandPanel(wrapper)

    expect(wrapper.text()).toContain('accountApi.reloginDescription')
    expect(wrapper.text()).not.toContain('accountApi.currentHash')
    expect(wrapper.find('input[id^="account-api-id-"]').attributes('placeholder')).toBe(
      'accountApi.apiIdPlaceholder',
    )
  })
})
