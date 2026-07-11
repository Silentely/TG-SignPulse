<script setup lang="ts">
import { X } from 'lucide-vue-next'
import { onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from '../composables/useI18n'

const props = defineProps<{
  title: string
  isOpen: boolean
  maxWidthClass?: string
}>()

const emit = defineEmits<{
  (e: 'close'): void
}>()

const { t } = useI18n()

const onKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && props.isOpen) {
    e.stopPropagation()
    emit('close')
  }
}

watch(
  () => props.isOpen,
  (open) => {
    if (typeof document === 'undefined') return
    document.body.style.overflow = open ? 'hidden' : ''
  },
  { immediate: true }
)

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  if (typeof document !== 'undefined') {
    document.body.style.overflow = ''
  }
})
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="isOpen"
        class="fixed inset-0 z-[100] flex items-center justify-center p-4"
        role="presentation"
      >
        <!-- Backdrop -->
        <div
          class="absolute inset-0 bg-gray-900/40 dark:bg-black/60 backdrop-blur-sm"
          aria-hidden="true"
          @click="emit('close')"
        />

        <!-- Modal Panel -->
        <div
          role="dialog"
          aria-modal="true"
          :aria-label="title"
          :class="[
            'relative w-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 shadow-xl overflow-hidden flex flex-col max-h-[90vh]',
            maxWidthClass || 'max-w-md',
          ]"
        >
          <!-- Header -->
          <div class="flex items-center justify-between px-5 h-14 border-b border-gray-200 dark:border-gray-800/60 bg-gray-50 dark:bg-gray-900 shrink-0">
            <div class="flex items-center gap-3 min-w-0">
              <h3 class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{{ title }}</h3>
              <slot name="header-extra" />
            </div>
            <button
              type="button"
              class="text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 transition-colors p-1 rounded shrink-0 focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-400"
              :aria-label="t('common.close')"
              @click="emit('close')"
            >
              <X class="w-4 h-4" />
            </button>
          </div>

          <!-- Content -->
          <div class="p-5 overflow-y-auto max-h-[70vh] custom-scrollbar">
            <slot />
          </div>

          <!-- Footer -->
          <div
            v-if="$slots.footer"
            class="px-5 py-4 border-t border-gray-200 dark:border-gray-800/60 bg-gray-50 dark:bg-gray-900 flex justify-end gap-3 shrink-0"
          >
            <slot name="footer" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.modal-enter-active,
.modal-leave-active {
  transition: all 0.2s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
  transform: scale(0.98);
}
</style>
