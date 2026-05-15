<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { ChevronDown, Check } from 'lucide-vue-next'
import { useI18n } from '../composables/useI18n'

const { t } = useI18n()

const props = defineProps<{
  modelValue: string[]
  options: { label: string, value: string }[]
  placeholder?: string
  disabled?: boolean
  className?: string
  allMode?: boolean
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', val: string[]): void
  (e: 'update:allMode', val: boolean): void
}>()

const isOpen = ref(false)
const selectRef = ref<HTMLElement | null>(null)

const toggle = () => {
  if (props.disabled) return
  isOpen.value = !isOpen.value
}

const toggleAllMode = () => {
  if (props.allMode) {
    // Deselect all mode, clear selection
    emit('update:allMode', false)
    emit('update:modelValue', [])
  } else {
    // Enable all mode
    emit('update:allMode', true)
    emit('update:modelValue', props.options.map(o => o.value))
  }
  isOpen.value = false
}

const select = (val: string) => {
  // If in allMode, clicking individual item exits allMode
  if (props.allMode) {
    emit('update:allMode', false)
  }
  const next = [...props.modelValue]
  const idx = next.indexOf(val)
  if (idx > -1) next.splice(idx, 1)
  else next.push(val)
  emit('update:modelValue', next)
}

const handleClickOutside = (e: MouseEvent) => {
  if (selectRef.value && !selectRef.value.contains(e.target as Node)) {
    isOpen.value = false
  }
}

onMounted(() => document.addEventListener('click', handleClickOutside))
onUnmounted(() => document.removeEventListener('click', handleClickOutside))

const selectedLabel = computed(() => {
  if (props.allMode) return t('multiSelect.allAccounts')
  if (props.modelValue.length === 0) return props.placeholder || t('multiSelect.placeholder')
  if (props.modelValue.length === 1) return props.options.find(o => o.value === props.modelValue[0])?.label || props.modelValue[0]
  return `${props.modelValue.length} ${t('multiSelect.selected')}`
})
</script>
<template>
  <div class="relative" ref="selectRef" :class="className || 'w-full'">
    <button type="button" @click="toggle" :disabled="disabled"
      class="w-full flex items-center justify-between h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-gray-400 disabled:opacity-50 disabled:cursor-not-allowed">
      <span class="truncate" :class="allMode ? 'text-blue-600 dark:text-blue-400 font-medium' : ''">{{ selectedLabel }}</span>
      <ChevronDown class="w-4 h-4 text-gray-400 transition-transform" :class="isOpen ? 'rotate-180' : ''" />
    </button>

    <div v-if="isOpen" class="absolute z-[60] w-full mt-1 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 shadow-lg py-1 max-h-60 overflow-y-auto">
      <!-- All Accounts option (first, independent) -->
      <button type="button" @click.stop="toggleAllMode"
        class="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-800/50 flex items-center justify-between border-b border-gray-100 dark:border-gray-800/40 mb-1"
        :class="allMode ? 'text-blue-600 dark:text-blue-400 bg-blue-50/50 dark:bg-blue-500/10' : 'text-gray-700 dark:text-gray-300'">
        <span class="truncate font-medium">{{ t('multiSelect.allAccounts') }}</span>
        <Check v-if="allMode" class="w-4 h-4 flex-shrink-0" />
      </button>
      <!-- Individual accounts -->
      <button v-for="opt in options" :key="opt.value" type="button"
        @click.stop="select(opt.value)"
        class="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-800/50 flex items-center justify-between"
        :class="[
          allMode ? 'opacity-40 pointer-events-none' : '',
          !allMode && modelValue.includes(opt.value) ? 'text-blue-600 dark:text-blue-400 bg-blue-50/50 dark:bg-blue-500/10' : 'text-gray-700 dark:text-gray-300'
        ]">
        <span class="truncate">{{ opt.label }}</span>
        <Check v-if="!allMode && modelValue.includes(opt.value)" class="w-4 h-4 flex-shrink-0" />
      </button>
      <div v-if="!options.length" class="px-3 py-2 text-sm text-gray-400">{{ t('multiSelect.noOptions') }}</div>
    </div>
  </div>
</template>
