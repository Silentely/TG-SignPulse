<script setup lang="ts">
import { ref, watch } from 'vue'
import Modal from '../Modal.vue'
import { useI18n } from '../../composables/useI18n'

const props = defineProps<{
  isOpen: boolean
  sourceName: string
  busy?: boolean
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'submit', newName: string): void
}>()

const { t } = useI18n()
const cloneName = ref('')

watch(
  () => [props.isOpen, props.sourceName] as const,
  ([open, name]) => {
    if (open) {
      cloneName.value = name ? `${name}_copy` : ''
    }
  },
)

const handleSubmit = () => {
  if (props.busy) return
  emit('submit', cloneName.value)
}
</script>

<template>
  <Modal :isOpen="isOpen" :title="t('tasks.cloneTitle')" maxWidthClass="max-w-sm" @close="emit('close')">
    <div class="space-y-3">
      <p class="text-xs text-gray-500">
        {{ t('tasks.cloneFrom', { name: sourceName || '' }) }}
      </p>
      <div class="space-y-1.5">
        <label class="ui-label" for="clone-task-name">{{ t('tasks.cloneName') }}</label>
        <input
          id="clone-task-name"
          v-model="cloneName"
          type="text"
          class="ui-input"
          autocomplete="off"
          @keyup.enter="handleSubmit"
        >
      </div>
    </div>
    <template #footer>
      <button type="button" class="ui-btn-secondary !border-transparent !bg-transparent !px-4 !py-2" @click="emit('close')">
        {{ t('common.cancel') }}
      </button>
      <button type="button" class="ui-btn-primary !px-4 !py-2" :disabled="busy" @click="handleSubmit">
        {{ busy ? t('tasks.cloning') : t('tasks.clone') }}
      </button>
    </template>
  </Modal>
</template>
