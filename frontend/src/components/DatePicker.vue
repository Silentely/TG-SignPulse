<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ChevronDown, ChevronLeft, ChevronRight, X } from 'lucide-vue-next'
import { useI18n } from '../composables/useI18n'

const { locale } = useI18n()

const props = defineProps<{
  modelValue: string
  placeholder?: string
}>()
const emit = defineEmits<{ (e: 'update:modelValue', val: string): void }>()

const isOpen = ref(false)
const pickerRef = ref<HTMLElement | null>(null)

// Current view month/year
const viewYear = ref(new Date().getFullYear())
const viewMonth = ref(new Date().getMonth()) // 0-indexed

const toggle = () => {
  isOpen.value = !isOpen.value
  if (isOpen.value && props.modelValue) {
    const d = new Date(props.modelValue + 'T00:00:00')
    viewYear.value = d.getFullYear()
    viewMonth.value = d.getMonth()
  }
}

const handleClickOutside = (e: MouseEvent) => {
  if (pickerRef.value && !pickerRef.value.contains(e.target as Node)) {
    isOpen.value = false
  }
}

onMounted(() => document.addEventListener('click', handleClickOutside))
onUnmounted(() => document.removeEventListener('click', handleClickOutside))

const weekDays = computed(() => {
  if (locale.value === 'zh') return ['日', '一', '二', '三', '四', '五', '六']
  return ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa']
})

const monthLabel = computed(() => {
  const d = new Date(viewYear.value, viewMonth.value, 1)
  if (locale.value === 'zh') {
    return `${viewYear.value}年${viewMonth.value + 1}月`
  }
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short' })
})

const days = computed(() => {
  const firstDay = new Date(viewYear.value, viewMonth.value, 1).getDay()
  const daysInMonth = new Date(viewYear.value, viewMonth.value + 1, 0).getDate()
  const result: { day: number; date: string; isToday: boolean; isSelected: boolean }[] = []
  
  // Empty slots before first day
  for (let i = 0; i < firstDay; i++) {
    result.push({ day: 0, date: '', isToday: false, isSelected: false })
  }
  
  const today = new Date()
  const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
  
  for (let d = 1; d <= daysInMonth; d++) {
    const dateStr = `${viewYear.value}-${String(viewMonth.value + 1).padStart(2, '0')}-${String(d).padStart(2, '0')}`
    result.push({
      day: d,
      date: dateStr,
      isToday: dateStr === todayStr,
      isSelected: dateStr === props.modelValue
    })
  }
  return result
})

const prevMonth = () => {
  if (viewMonth.value === 0) {
    viewMonth.value = 11
    viewYear.value--
  } else {
    viewMonth.value--
  }
}

const nextMonth = () => {
  if (viewMonth.value === 11) {
    viewMonth.value = 0
    viewYear.value++
  } else {
    viewMonth.value++
  }
}

const selectDate = (dateStr: string) => {
  if (!dateStr) return
  emit('update:modelValue', dateStr)
  isOpen.value = false
}

const clear = (e: Event) => {
  e.stopPropagation()
  emit('update:modelValue', '')
}

const displayValue = computed(() => {
  if (!props.modelValue) return ''
  const d = new Date(props.modelValue + 'T00:00:00')
  if (locale.value === 'zh') {
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  }
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
})
</script>

<template>
  <div class="relative" ref="pickerRef">
    <button type="button" @click="toggle"
      class="w-full flex items-center justify-between h-9 sm:h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-gray-400 dark:focus:border-gray-600 transition-colors">
      <span class="truncate" :class="!modelValue ? 'text-gray-400 dark:text-gray-600' : ''">{{ displayValue || placeholder || (locale === 'zh' ? '选择日期' : 'Select date') }}</span>
      <div class="flex items-center gap-1">
        <button v-if="modelValue" type="button" @click="clear" class="p-0.5 text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
          <X class="w-3 h-3" />
        </button>
        <ChevronDown class="w-4 h-4 text-gray-400 transition-transform" :class="isOpen ? 'rotate-180' : ''" />
      </div>
    </button>

    <div v-if="isOpen" class="absolute z-[60] mt-1 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 shadow-lg p-3 w-[260px] right-0">
      <!-- Month navigation -->
      <div class="flex items-center justify-between mb-2">
        <button type="button" @click="prevMonth" class="p-1 text-gray-500 hover:text-gray-900 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded transition-colors">
          <ChevronLeft class="w-4 h-4" />
        </button>
        <span class="text-xs font-medium text-gray-900 dark:text-gray-100">{{ monthLabel }}</span>
        <button type="button" @click="nextMonth" class="p-1 text-gray-500 hover:text-gray-900 dark:hover:text-gray-200 hover:bg-gray-100 dark:hover:bg-gray-800 rounded transition-colors">
          <ChevronRight class="w-4 h-4" />
        </button>
      </div>

      <!-- Week days header -->
      <div class="grid grid-cols-7 gap-0 mb-1">
        <div v-for="wd in weekDays" :key="wd" class="text-center text-[10px] text-gray-500 font-medium py-1">{{ wd }}</div>
      </div>

      <!-- Days grid -->
      <div class="grid grid-cols-7 gap-0">
        <button
          v-for="(item, idx) in days"
          :key="idx"
          type="button"
          @click="selectDate(item.date)"
          :disabled="!item.day"
          class="h-8 w-8 mx-auto flex items-center justify-center text-xs rounded transition-colors"
          :class="[
            !item.day ? 'invisible' : '',
            item.isSelected ? 'bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-950 font-medium' : '',
            item.isToday && !item.isSelected ? 'border border-gray-400 dark:border-gray-500 text-gray-900 dark:text-gray-100' : '',
            !item.isSelected && !item.isToday && item.day ? 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-800' : ''
          ]"
        >
          {{ item.day || '' }}
        </button>
      </div>
    </div>
  </div>
</template>
