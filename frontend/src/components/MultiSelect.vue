<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
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
const dropdownRef = ref<HTMLElement | null>(null)
const dropdownStyle = ref<Record<string, string>>({})

const toggle = () => {
  if (props.disabled) return
  isOpen.value = !isOpen.value
}

const toggleAllMode = () => {
  if (props.allMode) {
    emit('update:allMode', false)
    emit('update:modelValue', [])
  } else {
    emit('update:allMode', true)
    emit('update:modelValue', props.options.map(o => o.value))
  }
  isOpen.value = false
}

const select = (val: string) => {
  if (props.allMode) {
    emit('update:allMode', false)
  }
  const next = [...props.modelValue]
  const idx = next.indexOf(val)
  if (idx > -1) next.splice(idx, 1)
  else next.push(val)
  emit('update:modelValue', next)
}

const updateDropdownPosition = () => {
  if (!selectRef.value || !isOpen.value) return
  const rect = selectRef.value.getBoundingClientRect()
  const dropdownH = 240
  const spaceBelow = window.innerHeight - rect.bottom
  const spaceAbove = rect.top

  if (spaceBelow < dropdownH && spaceAbove > spaceBelow) {
    dropdownStyle.value = {
      position: 'fixed',
      left: rect.left + 'px',
      bottom: (window.innerHeight - rect.top) + 'px',
      width: rect.width + 'px',
      zIndex: '9999',
    }
  } else {
    dropdownStyle.value = {
      position: 'fixed',
      left: rect.left + 'px',
      top: rect.bottom + 4 + 'px',
      width: rect.width + 'px',
      zIndex: '9999',
    }
  }
}

watch(isOpen, async (v) => {
  if (v) {
    await nextTick()
    if (!isOpen.value) return
    updateDropdownPosition()
    window.addEventListener('scroll', updateDropdownPosition, true)
    window.addEventListener('resize', updateDropdownPosition)
  } else {
    window.removeEventListener('scroll', updateDropdownPosition, true)
    window.removeEventListener('resize', updateDropdownPosition)
  }
})

const handleClickOutside = (e: MouseEvent) => {
  const target = e.target as Node
  if (selectRef.value?.contains(target)) return
  if (dropdownRef.value?.contains(target)) return
  isOpen.value = false
}

onMounted(() => document.addEventListener('click', handleClickOutside))
onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  window.removeEventListener('scroll', updateDropdownPosition, true)
  window.removeEventListener('resize', updateDropdownPosition)
})

const selectedLabel = computed(() => {
  if (props.allMode) return t('multiSelect.allAccounts')
  if (props.modelValue.length === 0) return props.placeholder || t('multiSelect.placeholder')
  if (props.modelValue.length === 1) return props.options.find(o => o.value === props.modelValue[0])?.label || props.modelValue[0]
  return `${props.modelValue.length} ${t('multiSelect.selected')}`
})
</script>
<template>
  <div class="relative" ref="selectRef" :class="className || 'w-full'">
    <button
      type="button"
      class="ui-select-trigger"
      :class="isOpen ? 'ui-select-trigger-open' : ''"
      :disabled="disabled"
      :aria-expanded="isOpen"
      aria-haspopup="listbox"
      @click="toggle"
    >
      <span
        class="truncate"
        :class="allMode
          ? 'text-sky-600 dark:text-sky-400 font-medium'
          : modelValue.length === 0 ? 'text-gray-400 dark:text-gray-500' : ''"
      >{{ selectedLabel }}</span>
      <ChevronDown class="w-4 h-4 text-gray-400 transition-transform duration-200 shrink-0" :class="isOpen ? 'rotate-180' : ''" />
    </button>

    <Teleport to="body">
      <Transition name="dropdown">
        <div v-if="isOpen" ref="dropdownRef" :style="dropdownStyle" class="ui-dropdown" role="listbox">
          <button
            type="button"
            class="ui-dropdown-item border-b border-gray-100 dark:border-gray-800/50 mb-0.5"
            :class="allMode ? 'ui-dropdown-item-active !text-sky-600 dark:!text-sky-400' : ''"
            @click.stop="toggleAllMode"
          >
            <span class="truncate font-medium">{{ t('multiSelect.allAccounts') }}</span>
            <Check v-if="allMode" class="w-3.5 h-3.5 shrink-0 text-sky-500" />
          </button>
          <button
            v-for="opt in options"
            :key="opt.value"
            type="button"
            class="ui-dropdown-item"
            :class="[
              allMode ? 'opacity-40 pointer-events-none' : '',
              !allMode && modelValue.includes(opt.value) ? 'ui-dropdown-item-active !text-sky-600 dark:!text-sky-400' : '',
            ]"
            @click.stop="select(opt.value)"
          >
            <span class="truncate">{{ opt.label }}</span>
            <Check v-if="!allMode && modelValue.includes(opt.value)" class="w-3.5 h-3.5 shrink-0 text-sky-500" />
          </button>
          <div v-if="!options.length" class="px-3 py-2.5 text-sm text-gray-400">{{ t('multiSelect.noOptions') }}</div>
        </div>
      </Transition>
    </Teleport>
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
