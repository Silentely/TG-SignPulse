<script setup lang="ts">
import { ref, watch, useTemplateRef } from 'vue'
import Modal from '../Modal.vue'
import TaskForm from './TaskForm.vue'
import { updateSignTask } from '../../lib/api'
import { getAuthToken } from '../../lib/api/core'
import type { SignTask, UpdateSignTaskRequest } from '../../lib/api'
import { useI18n } from '../../composables/useI18n'
import { getLocalizedErrorMessage } from '../../lib/types'
import { resolveTaskAccountName } from '../../lib/task-list-map'

const { t } = useI18n()

const props = defineProps<{ isOpen: boolean, task: SignTask }>()
const emit = defineEmits<{ (e: 'close'): void, (e: 'success'): void }>()

const taskFormRef = useTemplateRef<InstanceType<typeof TaskForm>>('taskForm')
const notifyOnFailure = ref(true)
const notifyOnSuccess = ref(true)

const loading = ref(false)
const error = ref('')

watch(() => props.isOpen, (val) => {
  if (val && props.task) {
    error.value = ''
    notifyOnFailure.value = props.task.notify_on_failure ?? true
    notifyOnSuccess.value = props.task.notify_on_success ?? true
  }
})

const handleSave = async () => {
  const token = getAuthToken()
  if (!token || !props.task) return

  // 命令式取最新 payload（TaskForm 已去除 update:payload 双通道，保存路径直接读取）
  const body = taskFormRef.value?.buildPayload?.() as UpdateSignTaskRequest | undefined

  loading.value = true
  error.value = ''
  try {
    // Resolve account_name: use direct value, skip wildcard, fallback to account_names
    const accountName = resolveTaskAccountName(props.task)
    await updateSignTask(
      token,
      props.task.name,
      {
        ...body,
        notify_on_failure: notifyOnFailure.value,
        notify_on_success: notifyOnSuccess.value,
      },
      accountName || undefined,
    )
    emit('success')
    emit('close')
  } catch (e: unknown) {
    error.value = getLocalizedErrorMessage(e, t, t('taskModal.saveFailed'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <Modal :isOpen="isOpen" @close="$emit('close')" :title="t('taskModal.editTitle')" maxWidthClass="max-w-3xl">
    <template #header-extra>
      <div class="flex flex-wrap items-center gap-x-3 gap-y-1 ml-4">
        <label class="flex items-center gap-1.5 cursor-pointer">
          <input type="checkbox" v-model="notifyOnFailure" class="rounded border-gray-300 accent-sky-500 w-3.5 h-3.5">
          <span class="text-xs font-medium text-gray-500 dark:text-gray-400">{{ t('taskForm.notifyOnFailure') }}</span>
        </label>
        <label class="flex items-center gap-1.5 cursor-pointer">
          <input type="checkbox" v-model="notifyOnSuccess" class="rounded border-gray-300 accent-sky-500 w-3.5 h-3.5">
          <span class="text-xs font-medium text-gray-500 dark:text-gray-400">{{ t('taskForm.notifyOnSuccess') }}</span>
        </label>
      </div>
    </template>

    <div class="space-y-4 px-1">
      <div v-if="error" class="ui-alert-error">
        {{ error }}
      </div>
      
      <TaskForm
        v-if="isOpen && task"
        ref="taskForm"
        :initialTask="task"
        lock-task-name
      />
    </div>

    <template #footer>
      <button @click="$emit('close')" class="ui-btn-secondary !border-transparent !bg-transparent !px-4 !py-2">{{ t('common.cancel') }}</button>
      <button @click="handleSave" :disabled="loading" class="ui-btn-primary !px-4 !py-2">
        {{ loading ? t('taskModal.saving') : t('taskModal.saveChanges') }}
      </button>
    </template>
  </Modal>
</template>
