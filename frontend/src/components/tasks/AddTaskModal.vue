<script setup lang="ts">
import { ref, watch, useTemplateRef, computed } from 'vue'
import Modal from '../Modal.vue'
import TaskForm from './TaskForm.vue'
import { createSignTask } from '../../lib/api'
import type { CreateSignTaskRequest, SignTask } from '../../lib/api'
import { useI18n } from '../../composables/useI18n'
import { useAuthStore } from '../../stores/auth'
import { getLocalizedErrorMessage } from '../../lib/types'
import { buildSignTaskFromTemplate, getTemplateById } from '../../lib/task-templates'

const { t } = useI18n()
const authStore = useAuthStore()

const props = defineProps<{
  isOpen: boolean
  /** 从内置模板打开时传入模板 id */
  templateId?: string | null
  /** 预填账号名（通常为当前列表第一个） */
  preferAccount?: string | null
}>()
const emit = defineEmits<{ (e: 'close'): void, (e: 'success'): void }>()

const payload = ref<Partial<CreateSignTaskRequest>>({})
const taskFormRef = useTemplateRef<InstanceType<typeof TaskForm>>('taskForm')
const notifyOnFailure = ref(true)
const notifyOnSuccess = ref(true)
const loading = ref(false)
const error = ref('')
/** 打开弹窗时固定一次，避免 computed 重算改名 */
const templateSeed = ref<SignTask | undefined>(undefined)
const formKey = ref('blank')

const modalTitle = computed(() => {
  if (props.templateId && getTemplateById(props.templateId)) {
    return t('taskModal.addFromTemplate')
  }
  return t('taskModal.addTitle')
})

watch(() => props.isOpen, (val) => {
  if (val) {
    error.value = ''
    payload.value = {}
    notifyOnFailure.value = true
    notifyOnSuccess.value = true
    if (props.templateId && getTemplateById(props.templateId)) {
      try {
        templateSeed.value = buildSignTaskFromTemplate(props.templateId, {
          account_name: props.preferAccount || '',
          task_name: `${props.templateId}_${Date.now().toString(36)}`,
        })
        formKey.value = `${props.templateId}-${templateSeed.value.name}`
      } catch {
        templateSeed.value = undefined
        formKey.value = 'blank'
      }
    } else {
      templateSeed.value = undefined
      formKey.value = 'blank'
    }
  } else {
    templateSeed.value = undefined
  }
})

const handleSave = async () => {
  const token = authStore.token
  if (!token) return

  // 保存前同步刷新 payload，避免防抖延迟导致提交旧值
  taskFormRef.value?.flushPayload?.()

  const chats = payload.value.chats || []
  const hasChat = chats.some((c) => Number(c.chat_id) > 0)
  if (!hasChat) {
    error.value = t('taskModal.needChat')
    return
  }

  loading.value = true
  error.value = ''
  try {
    await createSignTask(token, {
      ...payload.value,
      notify_on_failure: notifyOnFailure.value,
      notify_on_success: notifyOnSuccess.value,
    } as CreateSignTaskRequest)
    emit('success')
    emit('close')
  } catch (e: unknown) {
    error.value = getLocalizedErrorMessage(e, t, t('taskModal.addFailed'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <Modal :isOpen="isOpen" @close="$emit('close')" :title="modalTitle" maxWidthClass="max-w-3xl">
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
      <p v-if="templateId && templateSeed" class="text-xs text-sky-700 dark:text-sky-300 bg-sky-50 dark:bg-sky-500/10 border border-sky-200 dark:border-sky-800/40 px-3 py-2">
        {{ t('taskModal.templatePrefillHint') }}
      </p>

      <!-- key 固定于打开时刻：确保模板预填只应用一次 -->
      <TaskForm
        v-if="isOpen"
        :key="formKey"
        ref="taskForm"
        :initial-task="templateSeed"
        @update:payload="payload = $event"
      />
    </div>

    <template #footer>
      <button @click="$emit('close')" class="ui-btn-secondary !border-transparent !bg-transparent !px-4 !py-2">{{ t('common.cancel') }}</button>
      <button @click="handleSave" :disabled="loading" class="ui-btn-primary !px-4 !py-2">
        {{ loading ? t('taskModal.saving') : t('taskModal.confirmAdd') }}
      </button>
    </template>
  </Modal>
</template>
