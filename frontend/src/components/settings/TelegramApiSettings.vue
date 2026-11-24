<script setup lang="ts">
/**
 * Telegram API 配置区块：自定义 api_id / api_hash，包含显示密码切换与重置默认按钮。
 * 父组件 Settings.vue 持有 tgConfig 状态与 revealSecrets 状态，通过 v-model 同步。
 */
import { KeyRound, Eye, EyeOff } from 'lucide-vue-next'
import { useI18n } from '../../composables/useI18n'
import type { TgFormState } from '../../lib/settings-form'

interface RevealSecrets {
  tgApiHash: boolean
  aiKey: boolean
  botToken: boolean
}

const props = defineProps<{
  /** TG API 配置（v-model） */
  modelValue: TgFormState
  /** 密钥显隐状态（与父组件其他区块共用同一对象） */
  reveal: Pick<RevealSecrets, 'tgApiHash'>
  /** 服务端是否已保存 Hash（GET 只返回脱敏值） */
  hasApiHash?: boolean
  /** 已保存 Hash 的脱敏展示 */
  apiHashMasked?: string
  /** 保存中 */
  loading?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:modelValue', value: TgFormState): void
  (e: 'save'): void
  (e: 'reset'): void
  (e: 'toggle-reveal', key: 'tgApiHash'): void
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
    <div class="mb-6 border-b border-[var(--sp-border)] pb-3 flex items-center justify-between gap-3">
      <div class="flex items-start gap-3 min-w-0">
        <span class="ui-section-icon" aria-hidden="true"><KeyRound class="w-3.5 h-3.5" /></span>
        <div class="min-w-0">
          <h2 class="text-base font-medium text-[var(--sp-text)] font-semibold">{{ t('settings.tgApi') }}</h2>
          <p class="text-[10px] text-[var(--sp-text-muted)] mt-1">{{ t('settings.tgApiDesc') }}</p>
        </div>
      </div>
      <button type="button" class="ui-btn-secondary !px-3 !py-1 !text-xs shrink-0" :disabled="loading" @click="emit('reset')">{{ t('settings.resetDefault') }}</button>
    </div>
    <div class="space-y-5">
      <div class="space-y-1.5">
        <label class="ui-label" for="settings-api-id">{{ t('settings.apiId') }}</label>
        <!-- API ID 不是密钥，直接明文展示，无显隐按钮 -->
        <input id="settings-api-id" :value="modelValue.api_id" @input="onInput('api_id', $event)" type="text" inputmode="numeric" :placeholder="t('settings.apiIdPlaceholder')" class="ui-input" autocomplete="off">
      </div>
      <div class="space-y-1.5">
        <label class="ui-label" for="settings-api-hash">{{ t('settings.apiHash') }}</label>
        <div class="relative">
          <input id="settings-api-hash" :value="modelValue.api_hash" @input="onInput('api_hash', $event)" :type="reveal.tgApiHash ? 'text' : 'password'" :placeholder="hasApiHash ? t('accountApi.keepHashPlaceholder', { hash: apiHashMasked || '****' }) : t('settings.apiHashPlaceholder')" class="ui-input pr-10">
          <button type="button" class="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-[var(--sp-text-muted)] hover:text-[var(--sp-text-secondary)] dark:hover:text-[var(--sp-text)]" :aria-label="reveal.tgApiHash ? t('settings.hideSecret') : t('settings.showSecret')" @click="emit('toggle-reveal', 'tgApiHash')">
            <EyeOff v-if="reveal.tgApiHash" class="w-4 h-4" /><Eye v-else class="w-4 h-4" />
          </button>
        </div>
        <p v-if="hasApiHash && !modelValue.api_hash" class="text-[10px] text-[var(--sp-text-muted)] leading-relaxed">
          {{ t('settings.apiHashStoredHint') }}
        </p>
      </div>
      <div class="p-3 bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-800/50 text-xs text-amber-700 dark:text-amber-400 leading-relaxed">
        <p>
          {{ t('settings.apiWarning') }}
          <a href="https://my.telegram.org/auth" target="_blank" rel="noopener noreferrer" class="underline hover:text-amber-900 dark:hover:text-amber-300 font-medium">my.telegram.org</a>
        </p>
      </div>
      <div class="pt-2">
        <button type="button" class="ui-btn-primary w-full py-2.5" :disabled="loading || !modelValue.api_id || (!modelValue.api_hash && !hasApiHash)" @click="emit('save')">{{ loading ? t('common.saving') : t('settings.saveTgConfig') }}</button>
      </div>
    </div>
  </section>
</template>
