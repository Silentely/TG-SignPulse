<script setup lang="ts">
/**
 * 通用设置区块：日志保留、数据目录、代理、并发、签到间隔、设备保活、时区。
 * 父组件 Settings.vue 持有表单状态，本组件通过 v-model 双向同步并触发保存/立即保活事件。
 */
import { Settings2 } from 'lucide-vue-next'
import CustomSelect from '../CustomSelect.vue'
import { useI18n } from '../../composables/useI18n'
import { parseNumberInputValue, type SettingsFormState } from '../../lib/settings-form'

interface TimezoneOption {
  label: string
  value: string
}

const props = defineProps<{
  /** 表单状态（v-model） */
  modelValue: SettingsFormState
  /** 时区选项列表 */
  timezoneOptions: TimezoneOption[]
  /** 主保存中 */
  loading?: boolean
  /** 设备保活「立即执行」中 */
  keepaliveLoading?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: SettingsFormState): void
  (e: 'save'): void
  (e: 'run-keepalive'): void
}>()

const { t } = useI18n()

type NumberInputKey = 'logDays' | 'concurrency' | 'deviceKeepaliveIntervalDays'

/** 字段级更新：浅拷贝并覆盖单个字段，保证父组件 ref 收到新对象引用 */
const update = <K extends keyof SettingsFormState>(key: K, value: SettingsFormState[K]) => {
  emit('update:modelValue', { ...props.modelValue, [key]: value } as SettingsFormState)
}

const onNumberInput = (key: NumberInputKey, e: Event) => {
  const value = (e.target as HTMLInputElement).value
  update(key, parseNumberInputValue(value))
}

const onStringInput = (key: keyof SettingsFormState, e: Event) => {
  update(key, (e.target as HTMLInputElement).value as never)
}
</script>

<template>
  <section class="ui-card p-6">
    <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-center justify-between gap-3">
      <div class="flex items-start gap-3 min-w-0">
        <span class="ui-section-icon" aria-hidden="true"><Settings2 class="w-3.5 h-3.5" /></span>
        <div class="min-w-0">
          <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.general') }}</h2>
          <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.generalDesc') }}</p>
        </div>
      </div>
      <span v-if="loading" class="text-xs text-gray-500 shrink-0">{{ t('settings.saving') }}</span>
    </div>
    <div class="space-y-5">
      <div class="space-y-1.5">
        <label class="ui-label">{{ t('settings.logRetention') }}</label>
        <input :value="modelValue.logDays" @input="onNumberInput('logDays', $event)" type="number" class="ui-input">
      </div>
      <div class="space-y-1.5">
        <label class="ui-label">{{ t('settings.dataDir') }}</label>
        <input :value="modelValue.dataDir" @input="onStringInput('dataDir', $event)" type="text" placeholder="/data" class="ui-input">
      </div>
      <div class="space-y-1.5">
        <label class="ui-label">{{ t('settings.proxy') }}</label>
        <input :value="modelValue.proxy" @input="onStringInput('proxy', $event)" type="text" placeholder="socks5://127.0.0.1:1080" class="ui-input">
      </div>
      <div class="space-y-1.5">
        <label class="ui-label">{{ t('settings.concurrency') }}</label>
        <input :value="modelValue.concurrency" @input="onNumberInput('concurrency', $event)" type="number" min="1" max="10" :placeholder="t('settings.concurrencyPlaceholder')" class="ui-input">
      </div>
      <div class="space-y-1.5">
        <label class="ui-label">{{ t('settings.signInterval') }}</label>
        <input :value="modelValue.checkInterval" @input="onStringInput('checkInterval', $event)" type="number" min="0" max="3600" :placeholder="t('settings.signIntervalPlaceholder')" class="ui-input">
        <p class="text-[10px] text-gray-500">{{ t('settings.signIntervalHint') }}</p>
      </div>
      <div class="p-3 bg-gray-50 dark:bg-white/[0.02] border border-gray-200 dark:border-gray-800/60 space-y-3">
        <div class="flex items-center justify-between gap-3">
          <div>
            <label class="text-xs text-gray-600 dark:text-gray-300 block">{{ t('settings.deviceKeepalive') }}</label>
            <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.deviceKeepaliveDesc') }}</p>
          </div>
          <button
            type="button"
            class="ui-switch"
            role="switch"
            :aria-checked="modelValue.deviceKeepaliveEnabled"
            :class="modelValue.deviceKeepaliveEnabled ? 'ui-switch-on' : ''"
            @click="update('deviceKeepaliveEnabled', !modelValue.deviceKeepaliveEnabled)"
          >
            <span class="ui-switch-knob" />
          </button>
        </div>
        <div class="grid grid-cols-1 sm:grid-cols-[1fr_auto] gap-2">
          <input :value="modelValue.deviceKeepaliveIntervalDays" @input="onNumberInput('deviceKeepaliveIntervalDays', $event)" type="number" min="1" max="170" :disabled="!modelValue.deviceKeepaliveEnabled" class="ui-input disabled:opacity-50">
          <button type="button" class="ui-btn-secondary !px-3 !py-2 !text-xs" :disabled="keepaliveLoading" @click="emit('run-keepalive')">
            {{ keepaliveLoading ? t('settings.saving') : t('settings.keepaliveNow') }}
          </button>
        </div>
        <p class="text-[10px] text-gray-500">{{ t('settings.deviceKeepaliveIntervalHint') }}</p>
      </div>
      <div class="space-y-1.5">
        <label class="ui-label">{{ t('settings.timezone') }}</label>
        <CustomSelect
          :modelValue="modelValue.timezone"
          @update:modelValue="update('timezone', String($event ?? ''))"
          :options="timezoneOptions"
          className="w-full"
        />
      </div>
      <div class="pt-2">
        <button type="button" class="ui-btn-primary w-full py-2.5" :disabled="loading" @click="emit('save')">{{ loading ? t('settings.saving') : t('settings.saveGeneral') }}</button>
      </div>
    </div>
  </section>
</template>
