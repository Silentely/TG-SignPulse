<script setup lang="ts">
/**
 * AI 配置区块：base_url / model / api_key，测试连接按钮。
 * 内嵌「高级执行 / AI 视觉」子区块（execTimeout / accountCooldown / flowRetry /
 * historyMaxAge / aiVisionTimeout / aiVisionRetry），与模型配置一并由「保存 AI 配置」提交。
 */
import { Sparkles, Eye, EyeOff } from 'lucide-vue-next'
import { useI18n } from '../../composables/useI18n'
import SettingsFieldHint from './SettingsFieldHint.vue'
import {
  parseNumberInputValue,
  type AiFormState,
  type SettingsFormState,
} from '../../lib/settings-form'

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
  /** AI 保存中（含高级运行时参数） */
  aiLoading?: boolean
  /** 服务端 Key 解密失败（需重填 Key，仍可改 model/base_url） */
  keyDecryptFailed?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:aiModelValue', value: AiFormState): void
  (e: 'update:settingsModelValue', value: SettingsFormState): void
  (e: 'save-ai'): void
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
  updateSettings(key, parseNumberInputValue(v) as never)
}

const onSettingsSelectChange = (key: keyof SettingsFormState, e: Event) => {
  updateSettings(key, (e.target as HTMLSelectElement).value as never)
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
        <label class="ui-label" for="ai-base-url">{{ t('settings.apiBaseUrl') }}</label>
        <input id="ai-base-url" :value="aiModelValue.base_url" @input="onAiInput('base_url', $event)" type="text" placeholder="https://api.openai.com/v1" class="ui-input">
      </div>
      <div class="space-y-1.5">
        <label class="ui-label" for="ai-model">{{ t('settings.model') }}</label>
        <input id="ai-model" :value="aiModelValue.model" @input="onAiInput('model', $event)" type="text" placeholder="gpt-5-nano" class="ui-input">
      </div>
      <div class="space-y-1.5">
        <label class="ui-label" for="ai-api-key">{{ t('settings.apiKey') }}</label>
        <div class="relative">
          <input id="ai-api-key" :value="aiModelValue.api_key" @input="onAiInput('api_key', $event)" :type="reveal.aiKey ? 'text' : 'password'" placeholder="sk-..." class="ui-input pr-10">
          <button type="button" class="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200" :aria-label="reveal.aiKey ? t('settings.hideSecret') : t('settings.showSecret')" @click="emit('toggle-reveal', 'aiKey')">
            <EyeOff v-if="reveal.aiKey" class="w-4 h-4" /><Eye v-else class="w-4 h-4" />
          </button>
        </div>
        <p v-if="keyDecryptFailed" class="text-[11px] text-amber-600 dark:text-amber-400 leading-snug">
          {{ t('settings.aiKeyDecryptFailed') }}
        </p>
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
            <label class="text-[10px] text-gray-500" for="ai-exectimeout">{{ t('settings.execTimeout') }}</label>
            <input id="ai-exectimeout" :value="settingsModelValue.execTimeout" @input="onSettingsNumberInput('execTimeout', $event)" type="number" min="30" max="3600" :placeholder="t('settings.execTimeoutPlaceholder')" class="ui-input" />
            <SettingsFieldHint :text="t('settings.execTimeoutHint')" />
          </div>
          <div class="space-y-1">
            <label class="text-[10px] text-gray-500" for="ai-accountcooldown">{{ t('settings.accountCooldown') }}</label>
            <input id="ai-accountcooldown" :value="settingsModelValue.accountCooldown" @input="onSettingsNumberInput('accountCooldown', $event)" type="number" min="0" max="600" :placeholder="t('settings.accountCooldownPlaceholder')" class="ui-input" />
            <SettingsFieldHint :text="t('settings.accountCooldownHint')" />
          </div>
          <div class="space-y-1">
            <label class="text-[10px] text-gray-500" for="ai-flowretry">{{ t('settings.flowRetry') }}</label>
            <input id="ai-flowretry" :value="settingsModelValue.flowRetry" @input="onSettingsNumberInput('flowRetry', $event)" type="number" min="1" max="10" :placeholder="t('settings.flowRetryPlaceholder')" class="ui-input" />
            <SettingsFieldHint :text="t('settings.flowRetryHint')" />
          </div>
          <div class="space-y-1">
            <label class="text-[10px] text-gray-500" for="ai-historymaxage">{{ t('settings.historyMaxAge') }}</label>
            <input id="ai-historymaxage" :value="settingsModelValue.historyMaxAge" @input="onSettingsNumberInput('historyMaxAge', $event)" type="number" min="1" max="90" :placeholder="t('settings.historyMaxAgePlaceholder')" class="ui-input" />
            <SettingsFieldHint :text="t('settings.historyMaxAgeHint')" />
          </div>
          <div class="space-y-1">
            <label class="text-[10px] text-gray-500" for="ai-aivisiontimeout">{{ t('settings.aiVisionTimeout') }}</label>
            <input id="ai-aivisiontimeout" :value="settingsModelValue.aiVisionTimeout" @input="onSettingsNumberInput('aiVisionTimeout', $event)" type="number" min="3" max="120" :placeholder="t('settings.aiVisionTimeoutPlaceholder')" class="ui-input" />
            <SettingsFieldHint :text="t('settings.aiVisionTimeoutHint')" />
          </div>
          <div class="space-y-1">
            <label class="text-[10px] text-gray-500" for="ai-aivisionretry">{{ t('settings.aiVisionRetry') }}</label>
            <input id="ai-aivisionretry" :value="settingsModelValue.aiVisionRetry" @input="onSettingsNumberInput('aiVisionRetry', $event)" type="number" min="1" max="8" :placeholder="t('settings.aiVisionRetryPlaceholder')" class="ui-input" />
            <SettingsFieldHint :text="t('settings.aiVisionRetryHint')" />
          </div>
          <div class="space-y-1">
            <label class="text-[10px] text-gray-500" for="ai-aivisionreasoning">{{ t('settings.aiVisionReasoningEffort') }}</label>
            <select id="ai-aivisionreasoning" class="ui-input" :value="settingsModelValue.aiVisionReasoningEffort" @change="onSettingsSelectChange('aiVisionReasoningEffort', $event)">
              <option value="">{{ t('settings.aiVisionReasoningEffortDefault') }}</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="none">{{ t('settings.aiVisionReasoningEffortNone') }}</option>
            </select>
            <SettingsFieldHint :text="t('settings.aiVisionReasoningEffortHint')" />
          </div>
        </div>
      </div>
      <div class="pt-2">
        <button type="button" class="ui-btn-primary w-full py-2.5" :disabled="aiLoading" @click="emit('save-ai')">{{ aiLoading ? t('common.saving') : t('settings.saveAiConfig') }}</button>
      </div>
    </div>
  </section>
</template>
