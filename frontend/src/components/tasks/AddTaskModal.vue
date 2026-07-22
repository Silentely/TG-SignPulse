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
  /** 预填账号名（账号卡片深链或列表第一个） */
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
      formKey.value = `blank-${props.preferAccount || 'all'}`
    }
  } else {
    templateSeed.value = undefined
  }
})

/** 有效 chat_id：Telegram 群/频道为负数，不能用 > 0 判断 */
const isValidChatId = (raw: unknown): boolean => {
  const id = Number(raw)
  return Number.isFinite(id) && id !== 0
}

/** 独立任务名：去路径分隔符、控制长度，后缀用 chatId 保证可区分 */
const buildSplitTaskName = (baseName: string, chatId: number, used: Set<string>): string => {
  const cleaned = baseName.replace(/[/\\]/g, '_').trim() || `task_${Date.now()}`
  const suffix = String(chatId).replace(/^-/, 'n')
  // 预留后缀空间，避免 slice 后撞名
  const maxBase = Math.max(8, 80 - suffix.length - 1)
  let name = `${cleaned.slice(0, maxBase)}_${suffix}`
  if (!used.has(name)) {
    used.add(name)
    return name
  }
  let i = 2
  while (used.has(`${name}_${i}`) && i < 1000) i += 1
  name = `${name}_${i}`.slice(0, 80)
  used.add(name)
  return name
}

const handleSave = async () => {
  const token = authStore.token
  if (!token) return

  // 保存前同步刷新 payload，避免防抖延迟导致提交旧值
  taskFormRef.value?.flushPayload?.()
  const built = taskFormRef.value?.buildPayload?.() as CreateSignTaskRequest | undefined
  const body = (built || payload.value) as CreateSignTaskRequest
  // defineExpose 的 ref 在父组件侧通常已被解包为原始值
  const exposedMode = taskFormRef.value?.createMode as unknown
  const createMode =
    typeof exposedMode === 'string'
      ? exposedMode
      : (exposedMode as { value?: string } | undefined)?.value || 'shared'

  const chats = body.chats || []
  // 去重 + 过滤无效 id（群组 chat_id 为负）
  const seenIds = new Set<number>()
  const validChats = chats.filter((c) => {
    if (!isValidChatId(c.chat_id)) return false
    const id = Number(c.chat_id)
    if (seenIds.has(id)) return false
    seenIds.add(id)
    return true
  })
  if (!validChats.length) {
    error.value = t('taskModal.needChat')
    return
  }

  loading.value = true
  error.value = ''
  try {
    const base = {
      ...body,
      notify_on_failure: notifyOnFailure.value,
      notify_on_success: notifyOnSuccess.value,
    } as CreateSignTaskRequest

    if (createMode === 'split' && validChats.length > 1) {
      // 按会话拆成多个独立任务：同名后缀 _chatId，共享动作配置
      const baseName = (base.name || `task_${Date.now()}`).trim()
      const usedNames = new Set<string>()
      let ok = 0
      let fail = 0
      const errors: string[] = []
      for (const chat of validChats) {
        const chatId = Number(chat.chat_id)
        const taskName = buildSplitTaskName(baseName, chatId, usedNames)
        try {
          await createSignTask(token, {
            ...base,
            name: taskName,
            chats: [chat],
          })
          ok += 1
        } catch (e: unknown) {
          fail += 1
          errors.push(getLocalizedErrorMessage(e, t))
        }
      }
      if (fail === 0) {
        emit('success')
        emit('close')
      } else if (ok > 0) {
        error.value = t('tasks.splitCreatePartial', { ok, fail })
        emit('success')
        // 部分成功时保持弹窗，便于用户看到错误摘要
      } else {
        error.value = errors[0] || t('taskModal.addFailed')
      }
    } else {
      await createSignTask(token, {
        ...base,
        chats: validChats,
      })
      emit('success')
      emit('close')
    }
  } catch (e: unknown) {
    error.value = getLocalizedErrorMessage(e, t, t('taskModal.addFailed'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <Modal :isOpen="isOpen" @close="$emit('close')" :title="modalTitle" maxWidthClass="max-w-3xl">
    <div class="space-y-4">
      <p v-if="templateId" class="text-[11px] text-gray-500 leading-relaxed">
        {{ t('taskModal.templatePrefillHint') }}
      </p>
      <TaskForm
        :key="formKey"
        ref="taskForm"
        :initial-task="templateSeed"
        :prefer-account="preferAccount"
        @update:payload="payload = $event"
      />
      <div class="flex flex-wrap gap-4 pt-1">
        <label class="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400 cursor-pointer">
          <input v-model="notifyOnFailure" type="checkbox" class="ui-checkbox" />
          {{ t('taskForm.notifyOnFailure') }}
        </label>
        <label class="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400 cursor-pointer">
          <input v-model="notifyOnSuccess" type="checkbox" class="ui-checkbox" />
          {{ t('taskForm.notifyOnSuccess') }}
        </label>
      </div>
      <p v-if="error" class="text-xs text-rose-600 dark:text-rose-400">{{ error }}</p>
    </div>
    <template #footer>
      <button type="button" class="ui-btn-secondary !border-transparent !bg-transparent !px-4 !py-2" @click="$emit('close')">
        {{ t('common.cancel') }}
      </button>
      <button type="button" class="ui-btn-primary !px-4 !py-2" :disabled="loading" @click="handleSave">
        {{ loading ? t('taskModal.saving') : t('taskModal.confirmAdd') }}
      </button>
    </template>
  </Modal>
</template>
