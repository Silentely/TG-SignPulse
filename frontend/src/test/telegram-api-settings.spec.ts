import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import TelegramApiSettings from '../components/settings/TelegramApiSettings.vue'

vi.mock('../composables/useI18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

describe('TelegramApiSettings', () => {
  it('API ID 明文展示且没有显隐按钮，只有 Hash 保留显隐按钮', () => {
    const wrapper = mount(TelegramApiSettings, {
      props: {
        modelValue: { api_id: '18114140', api_hash: '' } as never,
        reveal: { tgApiHash: false },
      },
    })

    const idInput = wrapper.find('#settings-api-id')
    expect(idInput.attributes('type')).toBe('text')
    expect((idInput.element as HTMLInputElement).value).toBe('18114140')

    expect(wrapper.text()).toContain('settings.apiId')
    expect(wrapper.text()).toContain('settings.apiHash')
    expect(wrapper.findAll('button[aria-label="settings.showSecret"]')).toHaveLength(1)
  })
})
