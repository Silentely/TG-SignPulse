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

/**
 * 焦点逃逸拉回：模态对话框打开期间，若焦点意外落到对话框外
 * （如浏览器地址栏、扩展 UI、点击被遮罩遗漏的角落），立即拉回首个可聚焦元素。
 * 焦点落在任意 [role="dialog"]（含嵌套确认框）内时放行，避免外层把内层焦点抢回。
 * panel 本身可聚焦（tabindex=-1），纯展示型对话框也保证焦点不逃逸。
 */
const onFocusIn = (e: FocusEvent) => {
  if (!props.isOpen || !panelRef.value) return
  const target = e.target as HTMLElement | null
  if (!target || panelRef.value.contains(target)) return
  // 嵌套对话框：内层 dialog 内的焦点属于合法目标，放行
  if (target.closest('[role="dialog"]')) return
  const focusable = getFocusable()
  ;(focusable[0] ?? panelRef.value).focus()
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
      ;(getFocusable()[0] ?? panelRef.value)?.focus()
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
  document.addEventListener('focusin', onFocusIn)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  document.removeEventListener('focusin', onFocusIn)
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
          tabindex="-1"
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
