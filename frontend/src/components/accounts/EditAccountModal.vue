<script setup lang="ts">
import { ref, watch } from 'vue'
import Modal from '../Modal.vue'
import { updateAccount } from '../../lib/api'
import { useI18n } from '../../composables/useI18n'
import { useToast } from '../../composables/useToast'
import { useAuthStore } from '../../stores/auth'
import type { AccountUiItem } from '../../lib/types'
import { getLocalizedErrorMessage } from '../../lib/types'

const { t } = useI18n()
const toast = useToast()
const authStore = useAuthStore()

const props = defineProps<{
  isOpen: boolean
  account: AccountUiItem
}>()

const emit = defineEmits<{ (e: 'close'): void, (e: 'success'): void, (e: 'relogin', name: string): void }>()

const form = ref({
  new_account_name: '',
  remark: '',
  proxy: ''
})
const loading = ref(false)
const error = ref('')

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

const handleSave = async () => {
  const token = authStore.token
  if (!token || !props.account) return

  loading.value = true
  error.value = ''
  try {
    await updateAccount(token, props.account.name, {
      new_account_name: form.value.new_account_name || null,
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
  <Modal :isOpen="isOpen" @close="$emit('close')" :title="t('editAccount.title')">
    <div class="space-y-4">
      <div v-if="error" class="ui-alert-error">
        {{ error }}
      </div>

      <div class="space-y-1.5">
        <label class="ui-label">{{ t('editAccount.nameLabel') }}</label>
        <input 
          v-model="form.new_account_name"
          type="text" 
          :placeholder="t('editAccount.namePlaceholder')"
          class="ui-input"
        >
      </div>

      <div class="space-y-1.5">
        <label class="ui-label">{{ t('editAccount.remarkLabel') }}</label>
        <input 
          v-model="form.remark"
          type="text" 
          :placeholder="t('editAccount.remarkPlaceholder')"
          class="ui-input"
        >
      </div>

      <div class="space-y-1.5">
        <label class="ui-label">{{ t('editAccount.proxyLabel') }}</label>
        <input 
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
        {{ t('editAccount.cancel') }}
      </button>
      <button 
        type="button"
        class="ui-btn-primary !px-4 !py-2"
        :disabled="loading"
        @click="handleSave"
      >
        {{ loading ? t('editAccount.saving') : t('editAccount.saveChanges') }}
      </button>
    </template>
  </Modal>
</template>
