<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, watch, nextTick } from 'vue'
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
const dropdownRef = ref<HTMLElement | null>(null)
const activeIndex = ref(-1)
const dropdownStyle = ref<Record<string, string>>({})

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

const handleClickOutside = (e: MouseEvent) => {
  const target = e.target as Node
  if (selectRef.value?.contains(target)) return
  if (dropdownRef.value?.contains(target)) return
  isOpen.value = false
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
onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
  window.removeEventListener('scroll', updateDropdownPosition, true)
  window.removeEventListener('resize', updateDropdownPosition)
})

watch(isOpen, async (open) => {
  if (open) {
    await nextTick()
    if (!isOpen.value) return
    updateDropdownPosition()
    window.addEventListener('scroll', updateDropdownPosition, true)
    window.addEventListener('resize', updateDropdownPosition)
  } else {
    activeIndex.value = -1
    window.removeEventListener('scroll', updateDropdownPosition, true)
    window.removeEventListener('resize', updateDropdownPosition)
  }
})

const selectedLabel = computed(() => {
  const opt = props.options.find(o => o.value === props.modelValue)
  return opt ? opt.label : (props.placeholder || t('common.selectPlaceholder'))
})

const hasValue = computed(() => {
  const opt = props.options.find(o => o.value === props.modelValue)
  return !!opt
})
</script>
<template>
  <div class="relative" ref="selectRef" :class="className || 'w-full'">
    <button
      type="button"
      :disabled="disabled"
      class="ui-select-trigger"
      :class="isOpen ? 'ui-select-trigger-open' : ''"
      :aria-label="ariaLabel || placeholder || t('common.selectPlaceholder')"
      :aria-expanded="isOpen"
      aria-haspopup="listbox"
      @click="toggle"
      @keydown="onKeydown"
    >
      <span class="truncate" :class="!hasValue ? 'text-gray-400 dark:text-gray-500' : ''">{{ selectedLabel }}</span>
      <ChevronDown class="w-4 h-4 text-gray-400 transition-transform duration-200 shrink-0" :class="isOpen ? 'rotate-180' : ''" />
    </button>

    <Teleport to="body">
      <Transition name="dropdown">
        <div
          v-if="isOpen"
          ref="dropdownRef"
          role="listbox"
          :style="dropdownStyle"
          class="ui-dropdown"
        >
          <button
            v-for="opt in options"
            :key="String(opt.value)"
            type="button"
            role="option"
            :aria-selected="modelValue === opt.value"
            :disabled="opt.disabled"
            class="ui-dropdown-item"
            :class="[
              opt.disabled ? 'ui-dropdown-group' : '',
              modelValue === opt.value && !opt.disabled ? 'ui-dropdown-item-active' : '',
              !opt.disabled && selectableOptions[activeIndex]?.value === opt.value ? 'ui-dropdown-item-focus' : '',
              opt.indent ? '!pl-6' : '',
            ]"
            @click="!opt.disabled && select(opt.value)"
          >
            <span class="truncate">{{ opt.label }}</span>
            <Check v-if="modelValue === opt.value && !opt.disabled" class="w-3.5 h-3.5 shrink-0 text-sky-500" />
          </button>
          <div v-if="!options.length" class="px-3 py-2.5 text-sm text-gray-400">{{ t('common.noOptions') }}</div>
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
