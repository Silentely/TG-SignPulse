<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ChevronDown, ChevronLeft, ChevronRight, X } from 'lucide-vue-next'
import { useI18n } from '../composables/useI18n'

const { locale, t } = useI18n()

const props = defineProps<{
  modelValue: string
  placeholder?: string
}>()
const emit = defineEmits<{ (e: 'update:modelValue', val: string): void }>()

const isOpen = ref(false)
const pickerRef = ref<HTMLElement | null>(null)

const viewYear = ref(new Date().getFullYear())
const viewMonth = ref(new Date().getMonth())

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

const onKeydown = (e: KeyboardEvent) => {
  if (e.key === 'Escape' && isOpen.value) {
    e.preventDefault()
    isOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
  window.addEventListener('keydown', onKeydown)
})
onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  window.removeEventListener('keydown', onKeydown)
})

// 周起点：2026-08-02（UTC）为周日，作为 getDay()=0 的稳定基准生成星期缩写
const SUNDAY_UTC = Date.UTC(2026, 7, 2)

const weekDays = computed(() => {
  // zh 用窄格式保持单字视觉（日一二…），en 用短格式（Sun Mon…），不再硬编码数组
  const fmt = new Intl.DateTimeFormat(locale.value === 'zh' ? 'zh-CN' : 'en-US', {
    weekday: locale.value === 'zh' ? 'narrow' : 'short',
    timeZone: 'UTC',
  })
  return Array.from({ length: 7 }, (_, i) => fmt.format(new Date(SUNDAY_UTC + i * 86_400_000)))
})

const monthLabel = computed(() => {
  const d = new Date(viewYear.value, viewMonth.value, 1)
  const isZh = locale.value === 'zh'
  const month = isZh
    ? viewMonth.value + 1
    : d.toLocaleDateString('en-US', { month: 'short' })
  return t('datePicker.monthLabel', { year: viewYear.value, month })
})

const days = computed(() => {
  const firstDay = new Date(viewYear.value, viewMonth.value, 1).getDay()
  const daysInMonth = new Date(viewYear.value, viewMonth.value + 1, 0).getDate()
  const result: { day: number; date: string; isToday: boolean; isSelected: boolean }[] = []

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

const goToday = () => {
  const today = new Date()
  const dateStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`
  viewYear.value = today.getFullYear()
  viewMonth.value = today.getMonth()
  emit('update:modelValue', dateStr)
  isOpen.value = false
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
    <div class="flex items-center gap-1">
      <button
        type="button"
        class="ui-select-trigger flex-1 min-w-0"
        :class="isOpen ? 'ui-select-trigger-open' : ''"
        :aria-expanded="isOpen"
        aria-haspopup="dialog"
        @click="toggle"
      >
        <span class="truncate" :class="!modelValue ? 'text-gray-400 dark:text-gray-400' : ''">
          {{ displayValue || placeholder || t('datePicker.selectDate') }}
        </span>
        <ChevronDown class="w-4 h-4 text-gray-400 transition-transform duration-200 shrink-0" :class="isOpen ? 'rotate-180' : ''" />
      </button>
      <!-- 清除按钮独立于触发按钮，避免 button 嵌套的无效 HTML -->
      <button
        v-if="modelValue"
        type="button"
        class="ui-icon-btn !w-8 !h-8 shrink-0"
        :aria-label="t('datePicker.clearDate')"
        @click="clear"
      >
        <X class="w-3 h-3" />
      </button>
    </div>

    <Transition name="dropdown">
      <div
        v-if="isOpen"
        class="absolute z-[60] mt-1 ui-card shadow-[var(--sp-shadow-md)] p-3 w-[272px] right-0"
        role="dialog"
        :aria-label="monthLabel"
      >
        <div class="flex items-center justify-between mb-2.5">
          <button type="button" class="ui-icon-btn !w-7 !h-7" :aria-label="t('datePicker.prevMonth')" @click="prevMonth">
            <ChevronLeft class="w-4 h-4" />
          </button>
          <span class="text-xs font-medium text-gray-900 dark:text-gray-100 tracking-wide">{{ monthLabel }}</span>
          <button type="button" class="ui-icon-btn !w-7 !h-7" :aria-label="t('datePicker.nextMonth')" @click="nextMonth">
            <ChevronRight class="w-4 h-4" />
          </button>
        </div>

        <div class="grid grid-cols-7 gap-0 mb-1">
          <div v-for="wd in weekDays" :key="wd" class="text-center text-[10px] text-gray-400 font-medium py-1">{{ wd }}</div>
        </div>

        <div class="grid grid-cols-7 gap-0.5">
          <button
            v-for="(item, idx) in days"
            :key="idx"
            type="button"
            :disabled="!item.day"
            :aria-label="item.day
              ? locale === 'zh'
                ? `${viewYear}年${viewMonth + 1}月${item.day}日`
                : `${monthLabel} ${item.day}`
              : undefined"
            class="h-8 w-8 mx-auto flex items-center justify-center text-xs rounded-sm transition-colors"
            :class="[
              !item.day ? 'invisible' : '',
              item.isSelected ? 'bg-sky-500 text-white font-medium shadow-sm' : '',
              item.isToday && !item.isSelected ? 'border border-sky-400/60 text-sky-700 dark:text-sky-300' : '',
              !item.isSelected && !item.isToday && item.day ? 'text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/[0.06]' : '',
            ]"
            @click="selectDate(item.date)"
          >
            {{ item.day || '' }}
          </button>
        </div>

        <div class="mt-2.5 pt-2 border-t border-gray-100 dark:border-gray-800/60 flex justify-end">
          <button
            type="button"
            class="text-[11px] text-sky-600 dark:text-sky-400 hover:underline font-medium"
            @click="goToday"
          >
            {{ t('datePicker.today') }}
          </button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.dropdown-enter-active,
.dropdown-leave-active {
  transition: opacity 0.12s ease, transform 0.12s ease;
}
.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
