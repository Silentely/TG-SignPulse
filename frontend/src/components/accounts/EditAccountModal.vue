<script setup lang="ts">
import { ref, watch } from 'vue'
import Modal from '../Modal.vue'
import { updateAccount } from '../../lib/api'
import { useI18n } from '../../composables/useI18n'

const { t } = useI18n()

const props = defineProps<{ 
  isOpen: boolean
  account: any
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
      proxy: props.account.proxy || ''
    }
    error.value = ''
  }
})

const handleSave = async () => {
  const token = localStorage.getItem('tg-signer-token')
  if (!token || !props.account) return

  loading.value = true
  error.value = ''
  try {
    await updateAccount(token, props.account.name, {
      new_account_name: form.value.new_account_name || null,
      remark: form.value.remark || null,
      proxy: form.value.proxy || null
    })
    emit('success')
    emit('close')
  } catch (e: any) {
    error.value = e.message || t('editAccount.saveFailed')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <Modal :isOpen="isOpen" @close="$emit('close')" :title="t('editAccount.title')">
    <div class="space-y-4">
      <div v-if="error" class="text-xs text-rose-600 dark:text-rose-500 bg-rose-50 dark:bg-rose-500/10 p-2 border border-rose-200 dark:border-transparent">
        {{ error }}
      </div>

      <div class="space-y-1.5">
        <label class="text-xs text-gray-500 block">{{ t('editAccount.nameLabel') }}</label>
        <input 
          v-model="form.new_account_name"
          type="text" 
          :placeholder="t('editAccount.namePlaceholder')"
          class="w-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:bg-gray-50 dark:focus:bg-gray-800"
        >
      </div>

      <div class="space-y-1.5">
        <label class="text-xs text-gray-500 block">{{ t('editAccount.remarkLabel') }}</label>
        <input 
          v-model="form.remark"
          type="text" 
          :placeholder="t('editAccount.remarkPlaceholder')"
          class="w-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:bg-gray-50 dark:focus:bg-gray-800"
        >
      </div>

      <div class="space-y-1.5">
        <label class="text-xs text-gray-500 block">{{ t('editAccount.proxyLabel') }}</label>
        <input 
          v-model="form.proxy"
          type="text" 
          placeholder="socks5://..."
          class="w-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:bg-gray-50 dark:focus:bg-gray-800"
        >
      </div>
    </div>

    <template #footer>
      <div class="flex-1">
        <button 
          @click="$emit('relogin', account?.name)"
          class="px-4 py-2 text-sm text-rose-600 hover:bg-rose-50 dark:text-rose-500 dark:hover:bg-rose-500/10 transition-colors border border-rose-200 dark:border-rose-500/30"
        >
          {{ t('editAccount.relogin') }}
        </button>
      </div>
      <button 
        @click="$emit('close')"
        class="px-4 py-2 text-sm text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 transition-colors"
      >
        {{ t('editAccount.cancel') }}
      </button>
      <button 
        @click="handleSave"
        :disabled="loading"
        class="px-4 py-2 text-sm bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-950 hover:bg-gray-800 dark:hover:bg-white transition-colors disabled:opacity-50"
      >
        {{ loading ? t('editAccount.saving') : t('editAccount.saveChanges') }}
      </button>
    </template>
  </Modal>
</template>
