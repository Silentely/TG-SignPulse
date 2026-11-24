<script setup lang="ts">
/**
 * 账号级 Telegram API 凭据（高级设置折叠面板）。
 *
 * 默认收起；成对校验在前端实时拦截单边提交，避免把账号 api_id 与全局
 * api_hash 拼接后触发 Telegram 400 API_ID_INVALID。
 */
import { computed, ref } from 'vue'
import { ChevronDown, Eye, EyeOff } from 'lucide-vue-next'
import { useI18n } from '../../composables/useI18n'
import {
  validateAccountApiCredentials,
} from '../../lib/api-credentials'

const props = withDefaults(
  defineProps<{
    apiId: string
    apiHash: string
    /** 编辑已有账号 */
    editMode?: boolean
    /** 重新登录已有账号：复用已保存凭据，Hash 留空表示保留 */
    reloginMode?: boolean
    /** 账号已保存独立凭据 */
    hasCustomApi?: boolean
    /** 账号已保存独立 Hash（编辑/重登模式下 Hash 留空表示保留） */
    hasApiHash?: boolean
    /** 已保存 Hash 的脱敏展示 */
    apiHashMasked?: string | null
    /** 留空 Hash 对应的已保存 API ID；ID 变化时必须重新填写 Hash */
    keepApiId?: string
    /** 凭据变更后需要重新登录 */
    needsRelogin?: boolean
    disabled?: boolean
  }>(),
  {
    editMode: false,
    reloginMode: false,
    hasCustomApi: false,
    hasApiHash: false,
    apiHashMasked: null,
    keepApiId: '',
    needsRelogin: false,
    disabled: false,
  },
)

const emit = defineEmits<{
  (e: 'update:apiId', value: string): void
  (e: 'update:apiHash', value: string): void
}>()

const { t } = useI18n()

const uid = Math.random().toString(36).slice(2, 8)
const idInputId = `account-api-id-${uid}`
const hashInputId = `account-api-hash-${uid}`
const panelId = `account-api-panel-${uid}`

const expanded = ref(false)
const revealHash = ref(false)

const isExistingAccount = computed(() => props.editMode || props.reloginMode)

const canKeepExistingHash = computed(() => {
  if (!isExistingAccount.value || !props.hasApiHash) return false
  const savedApiId = String(props.keepApiId || '').trim()
  if (!savedApiId) return true
  // 只有沿用已保存的 API ID 时，空 Hash 才代表保留原值；
  // 改了 ID 就必须重新填写 Hash，避免拼出新的混合凭据对。
  return String(props.apiId || '').trim() === savedApiId
})

const validation = computed(() =>
  validateAccountApiCredentials(props.apiId, props.apiHash, {
    canKeepExistingHash: canKeepExistingHash.value,
  }),
)

const pairError = computed(() => {
  if (validation.value.valid) return ''
  return validation.value.error === 'id'
    ? t('accountApi.idInvalid')
    : t('accountApi.pairRequired')
})

const highlightId = computed(() => validation.value.missing === 'api_id')
const highlightHash = computed(() => validation.value.missing === 'api_hash')

const showReloginHint = computed(
  () =>
    !props.reloginMode &&
    isExistingAccount.value &&
    (props.needsRelogin ||
      props.hasCustomApi ||
      String(props.apiId || '').trim() !== '' ||
      String(props.apiHash || '').trim() !== ''),
)

const description = computed(() =>
  props.reloginMode
    ? t('accountApi.reloginDescription')
    : t('accountApi.description'),
)

const idPlaceholder = computed(() =>
  props.reloginMode && props.hasCustomApi
    ? t('accountApi.keepIdPlaceholder')
    : t('accountApi.apiIdPlaceholder'),
)

const hashPlaceholder = computed(() => {
  if (props.hasApiHash && props.apiHashMasked) {
    return t('accountApi.keepHashPlaceholder', { hash: props.apiHashMasked })
  }
  return t('accountApi.apiHashPlaceholder')
})

const expand = () => {
  expanded.value = true
}

/** 供父组件在提交前调用；无效时不折叠，保持错误可见 */
const validate = () => {
  if (validation.value.valid) return true
  expanded.value = true
  return false
}

const clearCredentials = () => {
  emit('update:apiId', '')
  emit('update:apiHash', '')
  expanded.value = true
}

defineExpose({ expand, validate })
</script>

<template>
  <div class="border-t border-[var(--sp-border)] pt-3">
    <button
      type="button"
      class="inline-flex items-center gap-1 text-xs text-[var(--sp-text-secondary)] hover:text-[var(--sp-text)]"
      :aria-expanded="expanded"
      :aria-controls="panelId"
      :disabled="disabled"
      @click="expanded = !expanded"
    >
      <ChevronDown
        class="w-3.5 h-3.5 transition-transform"
        :class="expanded ? 'rotate-180' : ''"
      />
      {{ t('accountApi.advanced') }}
      <span
        v-if="hasCustomApi"
        class="ml-1 rounded-full bg-sky-100 px-1.5 py-0.5 text-[10px] font-medium text-sky-700 dark:bg-sky-500/15 dark:text-sky-300"
      >
        {{ t('accountApi.customBadge') }}
      </span>
    </button>

    <div v-if="expanded" :id="panelId" class="mt-3 space-y-3">
      <p class="text-[11px] leading-relaxed text-[var(--sp-text-muted)]">
        {{ description }}
      </p>

      <div class="space-y-1.5">
        <label class="ui-label" :for="idInputId">{{ t('accountApi.apiId') }}</label>
        <input
          :id="idInputId"
          :value="apiId"
          type="number"
          inputmode="numeric"
          min="1"
          step="1"
          autocomplete="off"
          class="ui-input api-id-input"
          :class="{ '!border-rose-500 !ring-1 !ring-rose-500': highlightId }"
          :placeholder="idPlaceholder"
          :disabled="disabled"
          @input="emit('update:apiId', ($event.target as HTMLInputElement).value)"
        />
      </div>

      <div class="space-y-1.5">
        <label class="ui-label" :for="hashInputId">{{ t('accountApi.apiHash') }}</label>
        <div class="relative">
          <input
            :id="hashInputId"
            :value="apiHash"
            :type="revealHash ? 'text' : 'password'"
            autocomplete="new-password"
            class="ui-input pr-10"
            :class="{ '!border-rose-500 !ring-1 !ring-rose-500': highlightHash }"
            :placeholder="hashPlaceholder"
            :disabled="disabled"
            @input="emit('update:apiHash', ($event.target as HTMLInputElement).value)"
          />
          <button
            type="button"
            class="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-[var(--sp-text-muted)] hover:text-[var(--sp-text-secondary)] dark:hover:text-[var(--sp-text)]"
            :aria-label="revealHash ? t('accountApi.hideSecret') : t('accountApi.showSecret')"
            :disabled="disabled"
            @click="revealHash = !revealHash"
          >
            <EyeOff v-if="revealHash" class="w-4 h-4" />
            <Eye v-else class="w-4 h-4" />
          </button>
        </div>
        <p
          v-if="hasApiHash && apiHashMasked"
          class="text-[10px] leading-relaxed text-[var(--sp-text-muted)]"
        >
          {{ t('accountApi.currentHash', { hash: apiHashMasked }) }}
          {{ t('accountApi.keepHashHint') }}
        </p>
      </div>

      <p v-if="pairError" class="text-[11px] text-rose-600 dark:text-rose-400" role="alert">
        {{ pairError }}
      </p>

      <div v-if="hasCustomApi && !reloginMode" class="flex justify-end">
        <button
          type="button"
          class="text-[11px] text-rose-600 hover:underline disabled:opacity-50 dark:text-rose-400"
          :disabled="disabled"
          @click="clearCredentials"
        >
          {{ t('accountApi.clear') }}
        </button>
      </div>

      <p
        v-if="showReloginHint"
        class="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-700 dark:border-amber-800/50 dark:bg-amber-500/10 dark:text-amber-400"
      >
        {{ t('accountApi.reloginHint') }}
      </p>
    </div>
  </div>
</template>

<style scoped>
/* 隐藏数字输入框的原生上下调节箭头，避免误触加减 API ID */
.api-id-input {
  appearance: textfield;
  -moz-appearance: textfield;
}

.api-id-input::-webkit-outer-spin-button,
.api-id-input::-webkit-inner-spin-button {
  -webkit-appearance: none;
  margin: 0;
}
</style>
