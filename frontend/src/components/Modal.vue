<script setup lang="ts">
import { X } from 'lucide-vue-next'

defineProps<{
  title: string
  isOpen: boolean
  maxWidthClass?: string
}>()

defineEmits<{
  (e: 'close'): void
}>()
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div v-if="isOpen" class="fixed inset-0 z-[100] flex items-center justify-center">
        <!-- Backdrop -->
        <div class="absolute inset-0 bg-gray-900/40 dark:bg-black/60 backdrop-blur-sm" @click="$emit('close')"></div>
        
        <!-- Modal Panel -->
        <div :class="['relative w-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 shadow-xl overflow-hidden flex flex-col', maxWidthClass || 'max-w-md']">
          <!-- Header -->
          <div class="flex items-center justify-between px-5 h-14 border-b border-gray-200 dark:border-gray-800/60 bg-gray-50 dark:bg-gray-900">
            <div class="flex items-center gap-3">
              <h3 class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ title }}</h3>
              <slot name="header-extra"></slot>
            </div>
            <button @click="$emit('close')" class="text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 transition-colors">
              <X class="w-4 h-4" />
            </button>
          </div>
          
          <!-- Content -->
          <div class="p-5 overflow-y-auto max-h-[70vh] custom-scrollbar">
            <slot></slot>
          </div>
          
          <!-- Footer -->
          <div v-if="$slots.footer" class="px-5 py-4 border-t border-gray-200 dark:border-gray-800/60 bg-gray-50 dark:bg-gray-900 flex justify-end gap-3">
            <slot name="footer"></slot>
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
