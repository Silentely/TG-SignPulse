<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { ChevronDown, Check } from 'lucide-vue-next'

const props = defineProps<{
  modelValue: string | number
  options: { label: string, value: string | number, disabled?: boolean, indent?: boolean }[]
  placeholder?: string
  disabled?: boolean
  className?: string
}>()
const emit = defineEmits<{ (e: 'update:modelValue', val: string | number): void }>()

const isOpen = ref(false)
const selectRef = ref<HTMLElement | null>(null)

const toggle = () => {
  if (props.disabled) return
  isOpen.value = !isOpen.value
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

onMounted(() => document.addEventListener('click', handleClickOutside))
onUnmounted(() => document.removeEventListener('click', handleClickOutside))

const selectedLabel = computed(() => {
  const opt = props.options.find(o => o.value === props.modelValue)
  return opt ? opt.label : props.placeholder || '请选择'
})
</script>
<template>
  <div class="relative" ref="selectRef" :class="className || 'w-full'">
    <button type="button" @click="toggle" :disabled="disabled"
      class="w-full flex items-center justify-between h-9 sm:h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-gray-400 dark:focus:border-gray-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
      <span class="truncate">{{ selectedLabel }}</span>
      <ChevronDown class="w-4 h-4 text-gray-400 transition-transform" :class="isOpen ? 'rotate-180' : ''" />
    </button>
    
    <div v-if="isOpen" class="absolute z-[60] w-full mt-1 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 shadow-lg py-1 max-h-60 overflow-y-auto">
      <button v-for="opt in options" :key="opt.value" type="button"
        @click="!opt.disabled && select(opt.value)"
        class="w-full text-left py-2 text-sm flex items-center justify-between"
        :class="[
          opt.disabled ? 'text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase tracking-wider cursor-default pt-3 pb-1 px-3' : 'hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer',
          modelValue === opt.value ? 'text-gray-900 dark:text-gray-100 bg-gray-50 dark:bg-gray-800/50' : (!opt.disabled ? 'text-gray-700 dark:text-gray-300' : ''),
          opt.indent ? 'pl-6 pr-3' : 'px-3'
        ]">
        <span class="truncate">{{ opt.label }}</span>
        <Check v-if="modelValue === opt.value && !opt.disabled" class="w-4 h-4 flex-shrink-0" />
      </button>
      <div v-if="!options.length" class="px-3 py-2 text-sm text-gray-400">无选项</div>
    </div>
  </div>
</template>
