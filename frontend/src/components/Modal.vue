<script setup lang="ts">
import { X } from 'lucide-vue-next'
import { onMounted, onUnmounted, watch, nextTick, ref } from 'vue'
import { useI18n } from '../composables/useI18n'
import { lockBodyScroll, unlockBodyScroll } from '../lib/body-scroll-lock'

const props = withDefaults(
  defineProps<{
    title: string
    isOpen: boolean
    maxWidthClass?: string
    /** 叠层层级，确认框等需高于普通业务弹窗 */
    zIndexClass?: string
  }>(),
  {
    maxWidthClass: 'max-w-md',
    zIndexClass: 'z-[100]',
  }
)

const emit = defineEmits<{
  (e: 'close'): void
}>()

const { t } = useI18n()
const panelRef = ref<HTMLElement | null>(null)
let previousActive: HTMLElement | null = null
let scrollLocked = false

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

const getFocusable = () =>
  panelRef.value
    ? Array.from(panelRef.value.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => !el.hasAttribute('disabled') && el.tabIndex !== -1
      )
    : []

const onKeydown = (e: KeyboardEvent) => {
  if (!props.isOpen) return
  if (e.key === 'Escape') {
    e.stopPropagation()
    e.preventDefault()
    emit('close')
    return
  }
  // 简易焦点陷阱：Tab 在对话框内循环
  if (e.key === 'Tab' && panelRef.value) {
    const focusable = getFocusable()
    if (!focusable.length) return
    const first = focusable[0]
    const last = focusable[focusable.length - 1]
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault()
      last.focus()
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault()
      first.focus()
    }
  }
}

const releaseScrollLock = () => {
  if (scrollLocked) {
    unlockBodyScroll()
    scrollLocked = false
  }
}

watch(
  () => props.isOpen,
  async (open) => {
    if (open) {
      if (!scrollLocked) {
        lockBodyScroll()
        scrollLocked = true
      }
      previousActive = document.activeElement as HTMLElement | null
      await nextTick()
      getFocusable()[0]?.focus()
    } else {
      releaseScrollLock()
      if (previousActive?.focus) {
        try {
          previousActive.focus()
        } catch {
          /* 节点可能已卸载 */
        }
        previousActive = null
      }
    }
  },
  { immediate: true }
)

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  releaseScrollLock()
})
</script>

<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="isOpen"
        class="fixed inset-0 flex items-center justify-center p-4"
        :class="zIndexClass"
        role="presentation"
      >
        <!-- Backdrop -->
        <div
          class="absolute inset-0 bg-gray-900/45 dark:bg-black/65 backdrop-blur-[3px]"
          aria-hidden="true"
          @click="emit('close')"
        />

        <!-- Modal Panel -->
        <div
          ref="panelRef"
          role="dialog"
          aria-modal="true"
          :aria-label="title"
          :class="[
            'relative w-full ui-card shadow-[var(--sp-shadow-md)] overflow-hidden flex flex-col max-h-[90vh]',
            maxWidthClass,
          ]"
        >
          <!-- Header -->
          <div class="flex items-center justify-between px-5 h-13 min-h-[3.25rem] border-b border-gray-200 dark:border-gray-800/60 bg-gray-50/80 dark:bg-white/[0.02] shrink-0">
            <div class="flex items-center gap-3 min-w-0">
              <h3 class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate">{{ title }}</h3>
              <slot name="header-extra" />
            </div>
            <button
              type="button"
              class="ui-icon-btn shrink-0"
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
            class="px-5 py-3.5 border-t border-gray-200 dark:border-gray-800/60 bg-gray-50/80 dark:bg-white/[0.02] flex justify-end gap-3 shrink-0"
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
  transition: opacity 0.2s ease;
}
.modal-enter-active > div:last-child,
.modal-leave-active > div:last-child {
  transition: transform 0.2s ease, opacity 0.2s ease;
}
.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
.modal-enter-from > div:last-child,
.modal-leave-to > div:last-child {
  opacity: 0;
  transform: translateY(8px) scale(0.98);
}
</style>
