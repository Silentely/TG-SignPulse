<script setup lang="ts">
import { ref, watch } from 'vue'
import Modal from '../Modal.vue'
import AccountImpactModal from './AccountImpactModal.vue'
import { previewAccountChange, applyAccountChange, type AccountChangePlan } from '../../lib/api/accounts'
import { updateAccount } from '../../lib/api'
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
  proxy: ''
})
const loading = ref(false)
const error = ref('')

const handleClosed = () => emit('closed')

watch(() => props.isOpen, (val) => {
  if (val && props.account) {
    form.value = {
      new_account_name: props.account.name || '',
      remark: props.account.remark || '',
      proxy: props.account.raw.proxy || ''
    }
    error.value = ''
  }
})

const renamePlan = ref<AccountChangePlan | null>(null)
const handleSave = async (confirmed = false) => {
  const token = getAuthToken()
  if (!token || !props.account) return

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
      proxy: form.value.proxy || null
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
