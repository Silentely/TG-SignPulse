<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch } from 'vue'
import { ChevronDown, Check } from 'lucide-vue-next'
import { useI18n } from '../composables/useI18n'

const props = defineProps<{
  modelValue: string | number
  options: { label: string, value: string | number, disabled?: boolean, indent?: boolean }[]
  placeholder?: string
  disabled?: boolean
  className?: string
  /** 无障碍标签 */
  ariaLabel?: string
}>()
const emit = defineEmits<{ (e: 'update:modelValue', val: string | number): void }>()

const { t } = useI18n()
const isOpen = ref(false)
const selectRef = ref<HTMLElement | null>(null)
const activeIndex = ref(-1)

const selectableOptions = computed(() =>
  props.options.filter((o) => !o.disabled)
)

const toggle = () => {
  if (props.disabled) return
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    const idx = selectableOptions.value.findIndex((o) => o.value === props.modelValue)
    activeIndex.value = idx >= 0 ? idx : 0
  }
}

const select = (val: string | number) => {
  emit('update:modelValue', val)
  isOpen.value = false
}

const handleClickOutside = (e: MouseEvent) => {
  if (selectRef.value && !selectRef.value.contains(e.target as Node)) {
    isOpen.value = false
  }
}

const onKeydown = (e: KeyboardEvent) => {
  if (!isOpen.value) {
    if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      toggle()
    }
    return
  }
  const list = selectableOptions.value
  if (e.key === 'Escape') {
    e.preventDefault()
    isOpen.value = false
    return
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    activeIndex.value = Math.min(activeIndex.value + 1, list.length - 1)
    return
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeIndex.value = Math.max(activeIndex.value - 1, 0)
    return
  }
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    const opt = list[activeIndex.value]
    if (opt) select(opt.value)
  }
}

onMounted(() => document.addEventListener('click', handleClickOutside))
onUnmounted(() => document.removeEventListener('click', handleClickOutside))

watch(isOpen, (open) => {
  if (!open) activeIndex.value = -1
})

const selectedLabel = computed(() => {
  const opt = props.options.find(o => o.value === props.modelValue)
  return opt ? opt.label : (props.placeholder || t('common.selectPlaceholder'))
})
</script>
<template>
  <div class="relative" ref="selectRef" :class="className || 'w-full'">
    <button
      type="button"
      :disabled="disabled"
      class="w-full flex items-center justify-between h-9 sm:h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-gray-400 dark:focus:border-gray-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors focus-visible:ring-2 focus-visible:ring-gray-400"
      :aria-label="ariaLabel || placeholder || t('common.selectPlaceholder')"
      :aria-expanded="isOpen"
      aria-haspopup="listbox"
      @click="toggle"
      @keydown="onKeydown"
    >
      <span class="truncate">{{ selectedLabel }}</span>
      <ChevronDown class="w-4 h-4 text-gray-400 transition-transform shrink-0" :class="isOpen ? 'rotate-180' : ''" />
    </button>

    <div
      v-if="isOpen"
      role="listbox"
      class="absolute z-[60] w-full mt-1 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 shadow-lg py-1 max-h-60 overflow-y-auto"
    >
      <button
        v-for="opt in options"
        :key="String(opt.value)"
        type="button"
        role="option"
        :aria-selected="modelValue === opt.value"
        :disabled="opt.disabled"
        class="w-full text-left py-2 text-sm flex items-center justify-between"
        :class="[
          opt.disabled ? 'text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider cursor-default pt-3 pb-1 px-3' : 'hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer',
          modelValue === opt.value ? 'text-gray-900 dark:text-gray-100 bg-gray-50 dark:bg-gray-800/50' : (!opt.disabled ? 'text-gray-700 dark:text-gray-300' : ''),
          !opt.disabled && selectableOptions[activeIndex]?.value === opt.value ? 'ring-1 ring-inset ring-gray-300 dark:ring-gray-600' : '',
          opt.indent ? 'pl-6 pr-3' : 'px-3'
        ]"
        @click="!opt.disabled && select(opt.value)"
      >
        <span class="truncate">{{ opt.label }}</span>
        <Check v-if="modelValue === opt.value && !opt.disabled" class="w-4 h-4 flex-shrink-0" />
      </button>
      <div v-if="!options.length" class="px-3 py-2 text-sm text-gray-400">{{ t('common.noOptions') }}</div>
    </div>
  </div>
</template>
