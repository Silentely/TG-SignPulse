<script setup lang="ts">
/**
 * 任务执行策略区块：执行超时、账号冷却、流程重试、历史保留、AI 视觉参数。
 * 从 AI 卡中抽出，独立保存（saveAiRuntime 提交 buildAiRuntimePayload）。
 */
import { Settings2 } from 'lucide-vue-next'
import { useI18n } from '../../composables/useI18n'
import SettingsFieldHint from './SettingsFieldHint.vue'
import {
  parseNumberInputValue,
  type SettingsFormState,
} from '../../lib/settings-form'

const props = defineProps<{
  /** 全局表单状态（v-model） */
  modelValue: SettingsFormState
  /** 保存中 */
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: SettingsFormState): void
  (e: 'save'): void
}>()

const { t } = useI18n()

const update = <K extends keyof SettingsFormState>(key: K, value: SettingsFormState[K]) => {
  emit('update:modelValue', { ...props.modelValue, [key]: value } as SettingsFormState)
}

type NumberKey = 'execTimeout' | 'accountCooldown' | 'flowRetry' | 'historyMaxAge' | 'aiVisionTimeout' | 'aiVisionRetry'

const onNumberInput = (key: NumberKey, e: Event) => {
  update(key, parseNumberInputValue((e.target as HTMLInputElement).value) as never)
}

const onReasoningChange = (e: Event) => {
  update('aiVisionReasoningEffort', (e.target as HTMLSelectElement).value)
}
</script>

<template>
  <section class="ui-card p-6">
    <div class="mb-6 border-b border-[var(--sp-border)] pb-3 flex items-center justify-between gap-3">
      <div class="flex items-start gap-3 min-w-0">
        <span class="ui-section-icon" aria-hidden="true"><Settings2 class="w-3.5 h-3.5" /></span>
        <div class="min-w-0">
          <h2 class="text-base font-medium text-[var(--sp-text)] font-semibold">{{ t('settings.taskRuntime') }}</h2>
          <p class="text-[10px] text-[var(--sp-text-muted)] mt-1">{{ t('settings.taskRuntimeDesc') }}</p>
        </div>
      </div>
      <span v-if="loading" class="text-xs text-[var(--sp-text-muted)] shrink-0">{{ t('common.saving') }}</span>
    </div>
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
      <div class="space-y-1">
        <label class="text-[10px] text-[var(--sp-text-muted)]" for="ai-exectimeout">{{ t('settings.execTimeout') }}</label>
        <input id="ai-exectimeout" :value="modelValue.execTimeout" @input="onNumberInput('execTimeout', $event)" type="number" min="30" max="3600" :placeholder="t('settings.execTimeoutPlaceholder')" class="ui-input" />
        <SettingsFieldHint :text="t('settings.execTimeoutHint')" />
      </div>
      <div class="space-y-1">
        <label class="text-[10px] text-[var(--sp-text-muted)]" for="ai-accountcooldown">{{ t('settings.accountCooldown') }}</label>
        <input id="ai-accountcooldown" :value="modelValue.accountCooldown" @input="onNumberInput('accountCooldown', $event)" type="number" min="0" max="600" :placeholder="t('settings.accountCooldownPlaceholder')" class="ui-input" />
        <SettingsFieldHint :text="t('settings.accountCooldownHint')" />
      </div>
      <div class="space-y-1">
        <label class="text-[10px] text-[var(--sp-text-muted)]" for="ai-flowretry">{{ t('settings.flowRetry') }}</label>
        <input id="ai-flowretry" :value="modelValue.flowRetry" @input="onNumberInput('flowRetry', $event)" type="number" min="1" max="10" :placeholder="t('settings.flowRetryPlaceholder')" class="ui-input" />
        <SettingsFieldHint :text="t('settings.flowRetryHint')" />
      </div>
      <div class="space-y-1">
        <label class="text-[10px] text-[var(--sp-text-muted)]" for="ai-historymaxage">{{ t('settings.historyMaxAge') }}</label>
        <input id="ai-historymaxage" :value="modelValue.historyMaxAge" @input="onNumberInput('historyMaxAge', $event)" type="number" min="1" max="90" :placeholder="t('settings.historyMaxAgePlaceholder')" class="ui-input" />
        <SettingsFieldHint :text="t('settings.historyMaxAgeHint')" />
      </div>
      <div class="space-y-1">
        <label class="text-[10px] text-[var(--sp-text-muted)]" for="ai-aivisiontimeout">{{ t('settings.aiVisionTimeout') }}</label>
        <input id="ai-aivisiontimeout" :value="modelValue.aiVisionTimeout" @input="onNumberInput('aiVisionTimeout', $event)" type="number" min="3" max="120" :placeholder="t('settings.aiVisionTimeoutPlaceholder')" class="ui-input" />
        <SettingsFieldHint :text="t('settings.aiVisionTimeoutHint')" />
      </div>
      <div class="space-y-1">
        <label class="text-[10px] text-[var(--sp-text-muted)]" for="ai-aivisionretry">{{ t('settings.aiVisionRetry') }}</label>
        <input id="ai-aivisionretry" :value="modelValue.aiVisionRetry" @input="onNumberInput('aiVisionRetry', $event)" type="number" min="1" max="8" :placeholder="t('settings.aiVisionRetryPlaceholder')" class="ui-input" />
        <SettingsFieldHint :text="t('settings.aiVisionRetryHint')" />
      </div>
      <div class="space-y-1 sm:col-span-2">
        <label class="text-[10px] text-[var(--sp-text-muted)]" for="ai-aivisionreasoning">{{ t('settings.aiVisionReasoningEffort') }}</label>
        <select id="ai-aivisionreasoning" class="ui-input" :value="modelValue.aiVisionReasoningEffort" @change="onReasoningChange" >
          <option value="">{{ t('settings.aiVisionReasoningEffortDefault') }}</option>
          <option value="low">low</option>
          <option value="medium">medium</option>
          <option value="high">high</option>
          <option value="none">{{ t('settings.aiVisionReasoningEffortNone') }}</option>
        </select>
        <SettingsFieldHint :text="t('settings.aiVisionReasoningEffortHint')" />
      </div>
    </div>
    <div class="pt-2">
      <button type="button" class="ui-btn-primary w-full py-2.5" :disabled="loading" @click="emit('save')">{{ loading ? t('common.saving') : t('settings.saveTaskRuntime') }}</button>
    </div>
  </section>
</template>
