<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import Modal from '../Modal.vue'
import AccountImpactModal from './AccountImpactModal.vue'
import AccountApiCredentials from './AccountApiCredentials.vue'
import { previewAccountChange, applyAccountChange, type AccountChangePlan } from '../../lib/api/accounts'
import { updateAccount } from '../../lib/api'
import { validateAccountApiCredentials } from '../../lib/api-credentials'
import { getAuthToken } from '../../lib/api/core'
import { useI18n } from '../../composables/useI18n'
import { useToast } from '../../composables/useToast'
import type { AccountUiItem } from '../../lib/types'
import { getLocalizedErrorMessage } from '../../lib/types'

const { t } = useI18n()
const toast = useToast()

const props = defineProps<{
  isOpen: boolean
  account: AccountUiItem
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'success'): void
  (e: 'relogin', name: string): void
  /** 离场动画播完：显式转发，供父组件串行打开下一个弹窗 */
  (e: 'closed'): void
}>()

const form = ref({
  new_account_name: '',
  remark: '',
  proxy: '',
  api_id: '',
  api_hash: '',
})
const loading = ref(false)
const error = ref('')

const apiCredentialsRef = ref<InstanceType<typeof AccountApiCredentials> | null>(null)
/** 打开弹窗时的 API ID 基线：用于判断用户是否真的改动了凭据 */
const initialApiId = ref('')

const hasCustomApi = computed(() => !!props.account?.raw?.use_custom_api)
const hasApiHash = computed(() => !!props.account?.raw?.has_api_hash)

const credentialsChanged = computed(
  () =>
    form.value.api_id.trim() !== initialApiId.value.trim() ||
    form.value.api_hash.trim() !== '',
)

const handleClosed = () => emit('closed')

watch(() => props.isOpen, (val) => {
  if (val && props.account) {
    initialApiId.value = props.account.raw.api_id != null
      ? String(props.account.raw.api_id)
      : ''
    form.value = {
      new_account_name: props.account.name || '',
      remark: props.account.remark || '',
      proxy: props.account.raw.proxy || '',
      api_id: initialApiId.value,
      api_hash: '',
    }
    error.value = ''
  }
}, { immediate: true })

const ensureApiCredentialsValid = (): boolean => {
  // Hash 留空 + 已保存 Hash：保留原值，仍是完整凭据对
  const check = validateAccountApiCredentials(form.value.api_id, form.value.api_hash, {
    canKeepExistingHash: hasApiHash.value,
  })
  if (check.valid) return true
  // 错误文案由面板内联展示：避免用户补齐后顶部仍残留过期提示
  apiCredentialsRef.value?.expand()
  return false
}

const renamePlan = ref<AccountChangePlan | null>(null)
const handleSave = async (confirmed = false) => {
  const token = getAuthToken()
  if (!token || !props.account) return
  if (!ensureApiCredentialsValid()) return

  loading.value = true
  error.value = ''
  try {
    let accountName = props.account.name
    if (form.value.new_account_name && form.value.new_account_name !== accountName) {
      if (!confirmed) {
        renamePlan.value = await previewAccountChange(token, accountName, 'rename', form.value.new_account_name)
        return
      }
      if (!renamePlan.value) return
      accountName = (await applyAccountChange(token, renamePlan.value)).account_name
      renamePlan.value = null
      emit('success')
    }
    await updateAccount(token, accountName, {
      new_account_name: null,
      remark: form.value.remark || null,
      proxy: form.value.proxy || null,
      // 仅在用户实际改动凭据时下发；两项都为空表示清除账号级凭据
      ...(credentialsChanged.value
        ? {
            api_id: form.value.api_id.trim() || null,
            api_hash: form.value.api_hash.trim() || null,
          }
        : {}),
    })
    toast.success(t('editAccount.saveSuccess'))
    emit('success')
    emit('close')
  } catch (e: unknown) {
    error.value = getLocalizedErrorMessage(e, t, t('editAccount.saveFailed'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <AccountImpactModal :isOpen="!!renamePlan" :plan="renamePlan" :loading="loading" :error="error" @close="renamePlan = null" @closed="handleClosed" @apply="handleSave(true)" />
  <Modal :isOpen="isOpen" @close="$emit('close')" @closed="handleClosed" :title="t('editAccount.title')">
    <div class="space-y-4">
      <div v-if="error" class="ui-alert-error" role="alert">
        {{ error }}
      </div>

      <div class="space-y-1.5">
        <label class="ui-label" for="edit-account-name">{{ t('editAccount.nameLabel') }}</label>
        <input 
          id="edit-account-name"
          v-model="form.new_account_name"
          type="text" 
          :placeholder="t('editAccount.namePlaceholder')"
          class="ui-input"
        >
      </div>

      <div class="space-y-1.5">
        <label class="ui-label" for="edit-account-remark">{{ t('editAccount.remarkLabel') }}</label>
        <input 
          id="edit-account-remark"
          v-model="form.remark"
          type="text" 
          :placeholder="t('editAccount.remarkPlaceholder')"
          class="ui-input"
        >
      </div>

      <div class="space-y-1.5">
        <label class="ui-label" for="edit-account-proxy">{{ t('editAccount.proxyLabel') }}</label>
        <input 
          id="edit-account-proxy"
          v-model="form.proxy"
          type="text" 
          placeholder="socks5://..."
          class="ui-input"
        >
      </div>

      <!-- 账号级 API 凭据：默认收起；留空 Hash 表示保留已保存值 -->
      <AccountApiCredentials
        ref="apiCredentialsRef"
        v-model:api-id="form.api_id"
        v-model:api-hash="form.api_hash"
        edit-mode
        :has-custom-api="hasCustomApi"
        :has-api-hash="hasApiHash"
        :api-hash-masked="account?.raw?.api_hash_masked || null"
        :needs-relogin="!!account?.raw?.needs_relogin"
      />
    </div>

    <template #footer>
      <div class="flex-1">
        <button 
          type="button"
          class="ui-btn-danger !px-4 !py-2"
          @click="$emit('relogin', account?.name)"
        >
          {{ t('editAccount.relogin') }}
        </button>
      </div>
      <button 
        type="button"
        class="ui-btn-secondary !border-transparent !bg-transparent !px-4 !py-2"
        @click="$emit('close')"
      >
        {{ t('common.cancel') }}
      </button>
      <button 
        type="button"
        class="ui-btn-primary !px-4 !py-2"
        :disabled="loading"
        @click="handleSave()"
      >
        {{ loading ? t('editAccount.saving') : t('editAccount.saveChanges') }}
      </button>
    </template>
  </Modal>
</template>
