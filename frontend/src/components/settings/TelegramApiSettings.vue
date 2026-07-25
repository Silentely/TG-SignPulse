<script setup lang="ts">
/**
 * Telegram API 配置区块：自定义 api_id / api_hash，包含显示密码切换与重置默认按钮。
 * 父组件 Settings.vue 持有 tgConfig 状态与 revealSecrets 状态，通过 v-model 同步。
 */
import { KeyRound, Eye, EyeOff } from 'lucide-vue-next'
import { useI18n } from '../../composables/useI18n'
import type { TgFormState } from '../../lib/settings-form'

interface RevealSecrets {
  tgApiId: boolean
  tgApiHash: boolean
  aiKey: boolean
  botToken: boolean
}

const props = defineProps<{
  /** TG API 配置（v-model） */
  modelValue: TgFormState
  /** 密钥显隐状态（与父组件其他区块共用同一对象） */
  reveal: Pick<RevealSecrets, 'tgApiId' | 'tgApiHash'>
  /** 保存中 */
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: TgFormState): void
  (e: 'save'): void
  (e: 'reset'): void
  (e: 'toggle-reveal', key: 'tgApiId' | 'tgApiHash'): void
}>()

const { t } = useI18n()

const update = <K extends keyof TgFormState>(key: K, value: TgFormState[K]) => {
  emit('update:modelValue', { ...props.modelValue, [key]: value })
}

const onInput = (key: keyof TgFormState, e: Event) => {
  update(key, (e.target as HTMLInputElement).value as never)
}
</script>

<template>
  <section class="ui-card p-6">
    <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-center justify-between gap-3">
      <div class="flex items-start gap-3 min-w-0">
        <span class="ui-section-icon" aria-hidden="true"><KeyRound class="w-3.5 h-3.5" /></span>
        <div class="min-w-0">
          <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.tgApi') }}</h2>
          <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.tgApiDesc') }}</p>
        </div>
      </div>
      <button type="button" class="ui-btn-secondary !px-3 !py-1 !text-xs shrink-0" :disabled="loading" @click="emit('reset')">{{ t('settings.resetDefault') }}</button>
    </div>
    <div class="space-y-5">
      <div class="space-y-1.5">
        <label class="ui-label">API ID</label>
        <div class="relative">
          <input :value="modelValue.api_id" @input="onInput('api_id', $event)" :type="reveal.tgApiId ? 'text' : 'password'" class="ui-input pr-10" autocomplete="off">
          <button type="button" class="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200" :aria-label="reveal.tgApiId ? t('settings.hideSecret') : t('settings.showSecret')" @click="emit('toggle-reveal', 'tgApiId')">
            <EyeOff v-if="reveal.tgApiId" class="w-4 h-4" /><Eye v-else class="w-4 h-4" />
          </button>
        </div>
      </div>
      <div class="space-y-1.5">
        <label class="ui-label">API Hash</label>
        <div class="relative">
          <input :value="modelValue.api_hash" @input="onInput('api_hash', $event)" :type="reveal.tgApiHash ? 'text' : 'password'" class="ui-input pr-10">
          <button type="button" class="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200" :aria-label="reveal.tgApiHash ? t('settings.hideSecret') : t('settings.showSecret')" @click="emit('toggle-reveal', 'tgApiHash')">
            <EyeOff v-if="reveal.tgApiHash" class="w-4 h-4" /><Eye v-else class="w-4 h-4" />
          </button>
        </div>
      </div>
      <div class="p-3 bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-800/50 text-xs text-amber-700 dark:text-amber-400 leading-relaxed">
        <p>
          {{ t('settings.apiWarning') }}
          <a href="https://my.telegram.org/auth" target="_blank" rel="noopener noreferrer" class="underline hover:text-amber-900 dark:hover:text-amber-300 font-medium">my.telegram.org</a>
        </p>
      </div>
      <div class="pt-2">
        <button type="button" class="ui-btn-primary w-full py-2.5" :disabled="loading || !modelValue.api_id || !modelValue.api_hash" @click="emit('save')">{{ loading ? t('settings.saving') : t('settings.saveTgConfig') }}</button>
      </div>
    </div>
  </section>
</template>
