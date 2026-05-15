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
}>()
const emit = defineEmits<{ (e: 'update:modelValue', val: string[]): void }>()

const isOpen = ref(false)
const selectRef = ref<HTMLElement | null>(null)

const toggle = () => {
 if (props.disabled) return
 isOpen.value = !isOpen.value
}

const selectAll = () => {
 if (props.modelValue.length === props.options.length) {
 emit('update:modelValue', [])
 } else {
 emit('update:modelValue', props.options.map(o => o.value))
 }
}

const select = (val: string) => {
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
 if (props.modelValue.length === 0) return props.placeholder || t('multiSelect.placeholder')
 if (props.modelValue.length === props.options.length) return `${t('multiSelect.all')} (${props.modelValue.length})`
 if (props.modelValue.length === 1) return props.options.find(o => o.value === props.modelValue[0])?.label || props.modelValue[0]
 return `${props.modelValue.length} ${t('multiSelect.selected')}`
})
</script>
<template>
 <div class="relative" ref="selectRef" :class="className || 'w-full'">
 <button type="button" @click="toggle" :disabled="disabled"
 class="w-full flex items-center justify-between h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-gray-400 disabled:opacity-50 disabled:cursor-not-allowed">
 <span class="truncate">{{ selectedLabel }}</span>
 <ChevronDown class="w-4 h-4 text-gray-400 transition-transform" :class="isOpen ? 'rotate-180' : ''" />
 </button>
 
 <div v-if="isOpen" class="absolute z-[60] w-full mt-1 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 shadow-lg py-1 max-h-60 overflow-y-auto">
 <button v-if="options.length > 0" type="button" @click.stop="selectAll"
 class="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-800/50 flex items-center justify-between border-b border-gray-100 dark:border-gray-800/60/50 mb-1"
 :class="modelValue.length === options.length ? 'text-blue-600 dark:text-blue-400 bg-blue-50/50 dark:bg-blue-500/10' : 'text-gray-700 dark:text-gray-300'">
 <span class="truncate font-medium">{{ t('multiSelect.allAccounts') }}</span>
 <Check v-if="modelValue.length === options.length" class="w-4 h-4 flex-shrink-0" />
 </button>
 <button v-for="opt in options" :key="opt.value" type="button"
 @click.stop="select(opt.value)"
 class="w-full text-left px-3 py-2 text-sm hover:bg-gray-50 dark:hover:bg-gray-800/50 flex items-center justify-between"
 :class="modelValue.includes(opt.value) ? 'text-blue-600 dark:text-blue-400 bg-blue-50/50 dark:bg-blue-500/10' : 'text-gray-700 dark:text-gray-300'">
 <span class="truncate">{{ opt.label }}</span>
 <Check v-if="modelValue.includes(opt.value)" class="w-4 h-4 flex-shrink-0" />
 </button>
 <div v-if="!options.length" class="px-3 py-2 text-sm text-gray-400">{{ t('multiSelect.noOptions') }}</div>
 </div>
 </div>
</template>

