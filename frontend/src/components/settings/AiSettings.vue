<script setup lang="ts">
/**
 * AI 配置区块：base_url / model / api_key，测试连接按钮。
 * 内嵌「高级执行 / AI 视觉」子区块（execTimeout / accountCooldown / flowRetry /
 * historyMaxAge / aiVisionTimeout / aiVisionRetry）——历史上与 AI 视觉相关，按原 UI 保留。
 */
import { Sparkles, Eye, EyeOff } from 'lucide-vue-next'
import { useI18n } from '../../composables/useI18n'
import SettingsFieldHint from './SettingsFieldHint.vue'
import type { AiFormState, SettingsFormState } from '../../lib/settings-form'

interface RevealSecrets {
  aiKey: boolean
}

const props = defineProps<{
  /** AI 配置（v-model） */
  aiModelValue: AiFormState
  /** 全局表单状态（v-model，用于高级字段双向绑定） */
  settingsModelValue: SettingsFormState
  /** 密钥显隐（仅 aiKey） */
  reveal: Pick<RevealSecrets, 'aiKey'>
  /** AI 保存中 */
  aiLoading?: boolean
  /** 高级保存中 */
  advancedLoading?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:aiModelValue', value: AiFormState): void
  (e: 'update:settingsModelValue', value: SettingsFormState): void
  (e: 'save-ai'): void
  (e: 'save-advanced'): void
  (e: 'test-ai'): void
  (e: 'toggle-reveal', key: 'aiKey'): void
}>()

const { t } = useI18n()

const updateAi = <K extends keyof AiFormState>(key: K, value: AiFormState[K]) => {
  emit('update:aiModelValue', { ...props.aiModelValue, [key]: value })
}

const updateSettings = <K extends keyof SettingsFormState>(key: K, value: SettingsFormState[K]) => {
  emit('update:settingsModelValue', { ...props.settingsModelValue, [key]: value } as SettingsFormState)
}

const onAiInput = (key: keyof AiFormState, e: Event) => {
  updateAi(key, (e.target as HTMLInputElement).value as never)
}

const onSettingsNumberInput = (key: keyof SettingsFormState, e: Event) => {
  const v = (e.target as HTMLInputElement).value
  updateSettings(key, (v === '' ? '' : Number(v)) as never)
}
</script>

<template>
  <section class="ui-card p-6">
    <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-center justify-between gap-3">
      <div class="flex items-start gap-3 min-w-0">
        <span class="ui-section-icon" aria-hidden="true"><Sparkles class="w-3.5 h-3.5" /></span>
        <div class="min-w-0">
          <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.aiConfig') }}</h2>
          <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.aiDesc') }}</p>
        </div>
      </div>
      <button type="button" class="ui-btn-secondary !px-3 !py-1 !text-xs shrink-0" :disabled="aiLoading" @click="emit('test-ai')">{{ t('settings.testConnection') }}</button>
    </div>
    <div class="space-y-5">
      <div class="space-y-1.5">
        <label class="ui-label">{{ t('settings.apiBaseUrl') }}</label>
        <input :value="aiModelValue.base_url" @input="onAiInput('base_url', $event)" type="text" placeholder="https://api.openai.com/v1" class="ui-input">
      </div>
      <div class="space-y-1.5">
        <label class="ui-label">{{ t('settings.model') }}</label>
        <input :value="aiModelValue.model" @input="onAiInput('model', $event)" type="text" placeholder="gpt-5-nano" class="ui-input">
      </div>
      <div class="space-y-1.5">
        <label class="ui-label">{{ t('settings.apiKey') }}</label>
        <div class="relative">
          <input :value="aiModelValue.api_key" @input="onAiInput('api_key', $event)" :type="reveal.aiKey ? 'text' : 'password'" placeholder="sk-..." class="ui-input pr-10">
          <button type="button" class="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200" :aria-label="reveal.aiKey ? t('settings.hideSecret') : t('settings.showSecret')" @click="emit('toggle-reveal', 'aiKey')">
            <EyeOff v-if="reveal.aiKey" class="w-4 h-4" /><Eye v-else class="w-4 h-4" />
          </button>
        </div>
      </div>
      <!-- 高级执行 / AI 视觉（从关于页移入） -->
      <div class="pt-4 border-t border-gray-200 dark:border-gray-800/60 space-y-3">
        <div>
          <h3 class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ t('settings.advanced') }}</h3>
          <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.advancedDesc') }}</p>
          <p class="text-[10px] text-gray-500">{{ t('settings.emptyAdvancedHint') }}</p>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <div class="space-y-1">
            <label class="text-[10px] text-gray-500">{{ t('settings.execTimeout') }}</label>
            <input :value="settingsModelValue.execTimeout" @input="onSettingsNumberInput('execTimeout', $event)" type="number" min="30" max="3600" :placeholder="t('settings.execTimeoutPlaceholder')" class="ui-input" />
            <SettingsFieldHint :text="t('settings.execTimeoutHint')" />
          </div>
          <div class="space-y-1">
            <label class="text-[10px] text-gray-500">{{ t('settings.accountCooldown') }}</label>
            <input :value="settingsModelValue.accountCooldown" @input="onSettingsNumberInput('accountCooldown', $event)" type="number" min="0" max="600" :placeholder="t('settings.accountCooldownPlaceholder')" class="ui-input" />
          </div>
          <div class="space-y-1">
            <label class="text-[10px] text-gray-500">{{ t('settings.flowRetry') }}</label>
            <input :value="settingsModelValue.flowRetry" @input="onSettingsNumberInput('flowRetry', $event)" type="number" min="1" max="10" :placeholder="t('settings.flowRetryPlaceholder')" class="ui-input" />
            <SettingsFieldHint :text="t('settings.flowRetryHint')" />
          </div>
          <div class="space-y-1">
            <label class="text-[10px] text-gray-500">{{ t('settings.historyMaxAge') }}</label>
            <input :value="settingsModelValue.historyMaxAge" @input="onSettingsNumberInput('historyMaxAge', $event)" type="number" min="1" max="90" :placeholder="t('settings.historyMaxAgePlaceholder')" class="ui-input" />
          </div>
          <div class="space-y-1">
            <label class="text-[10px] text-gray-500">{{ t('settings.aiVisionTimeout') }}</label>
            <input :value="settingsModelValue.aiVisionTimeout" @input="onSettingsNumberInput('aiVisionTimeout', $event)" type="number" min="3" max="120" :placeholder="t('settings.aiVisionTimeoutPlaceholder')" class="ui-input" />
          </div>
          <div class="space-y-1">
            <label class="text-[10px] text-gray-500">{{ t('settings.aiVisionRetry') }}</label>
            <input :value="settingsModelValue.aiVisionRetry" @input="onSettingsNumberInput('aiVisionRetry', $event)" type="number" min="1" max="8" :placeholder="t('settings.aiVisionRetryPlaceholder')" class="ui-input" />
          </div>
        </div>
        <button type="button" class="ui-btn-secondary w-full !py-2 !text-xs" :disabled="advancedLoading" @click="emit('save-advanced')">
          {{ advancedLoading ? t('settings.saving') : t('settings.saveAdvanced') }}
        </button>
      </div>
      <div class="pt-2">
        <button type="button" class="ui-btn-primary w-full py-2.5" :disabled="aiLoading" @click="emit('save-ai')">{{ aiLoading ? t('settings.saving') : t('settings.saveAiConfig') }}</button>
      </div>
    </div>
  </section>
</template>
