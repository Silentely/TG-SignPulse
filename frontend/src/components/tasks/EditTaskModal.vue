<script setup lang="ts">
import { ref, watch } from 'vue'
import Modal from '../Modal.vue'
import TaskForm from './TaskForm.vue'
import { updateSignTask } from '../../lib/api'
import { useI18n } from '../../composables/useI18n'

const { t } = useI18n()

const props = defineProps<{ isOpen: boolean, task: any }>()
const emit = defineEmits<{ (e: 'close'): void, (e: 'success'): void }>()

const payload = ref<any>({})
const notifyOnFailure = ref(true)

const loading = ref(false)
const error = ref('')

watch(() => props.isOpen, (val) => {
  if (val && props.task) {
    error.value = ''
    payload.value = {}
    notifyOnFailure.value = props.task.notify_on_failure ?? true
  }
})

const handleSave = async () => {
  const token = localStorage.getItem('tg-signer-token')
  if (!token || !props.task) return

  loading.value = true
  error.value = ''
  try {
    await updateSignTask(token, props.task.name, { ...payload.value, notify_on_failure: notifyOnFailure.value }, props.task.account_name)
    emit('success')
    emit('close')
  } catch (e: any) {
    error.value = e.message || t('taskModal.saveFailed')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <Modal :isOpen="isOpen" @close="$emit('close')" :title="t('taskModal.editTitle')" maxWidthClass="max-w-3xl">
    <template #header-extra>
      <label class="flex items-center gap-1.5 ml-4 cursor-pointer">
        <input type="checkbox" v-model="notifyOnFailure" class="rounded border-gray-300 text-gray-900 dark:border-gray-600 dark:text-gray-100 focus:ring-0 w-3.5 h-3.5">
        <span class="text-xs font-medium text-gray-500 dark:text-gray-400">{{ t('taskForm.notifyOnFailure') }}</span>
      </label>
    </template>

    <div class="space-y-4 px-1">
      <div v-if="error" class="text-xs text-rose-600 dark:text-rose-500 bg-rose-50 dark:bg-rose-500/10 p-2 border border-rose-200 dark:border-transparent rounded-md">
        {{ error }}
      </div>
      
      <TaskForm v-if="isOpen && task" :initialTask="task" @update:payload="payload = $event" />
    </div>

    <template #footer>
      <button @click="$emit('close')" class="px-4 py-2 text-sm text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 transition-colors">{{ t('common.cancel') }}</button>
      <button @click="handleSave" :disabled="loading" class="px-4 py-2 text-sm bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-950 hover:bg-gray-800 dark:hover:bg-white transition-colors disabled:opacity-50">
        {{ loading ? t('taskModal.saving') : t('taskModal.saveChanges') }}
      </button>
    </template>
  </Modal>
</template>
