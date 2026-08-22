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
  /** 无障碍名称；缺省回退到占位文案，再回退到多选默认文案 */
  ariaLabel?: string
}>()
const emit = defineEmits<{
  (e: 'update:modelValue', val: string[]): void
  (e: 'update:allMode', val: boolean): void
}>()

const isOpen = ref(false)
const selectRef = ref<HTMLElement | null>(null)
const dropdownRef = ref<HTMLElement | null>(null)
const dropdownStyle = ref<Record<string, string>>({})
/** 键盘导航当前项（对应 options 下标；-1 表示未定位） */
const activeIndex = ref(-1)

const toggle = () => {
  if (props.disabled) return
  isOpen.value = !isOpen.value
  if (isOpen.value) {
    // 重新打开时重置键盘位置到首项（全部账号），避免残留旧高亮
    activeIndex.value = -1
  }
}

const onKeydown = (e: KeyboardEvent) => {
  if (props.disabled) return
  if (!isOpen.value) {
    if (e.key === 'ArrowDown' || e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      toggle()
    }
    return
  }
  if (e.key === 'Escape') {
    // stopPropagation：阻止事件冒泡到 Modal 的全局 Escape 监听，
    // 避免收起下拉时把整个弹窗关掉、丢失未保存内容
    e.preventDefault()
    e.stopPropagation()
    isOpen.value = false
    return
  }
  const list = props.options
  // 下拉首项为「全部账号」：键盘导航用 -1 表示该项（该按钮始终渲染）
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    if (!list.length) {
      activeIndex.value = -1
      return
    }
    activeIndex.value = Math.min(activeIndex.value + 1, list.length - 1)
    scrollActiveIntoView()
    return
  }
  if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeIndex.value = Math.max(activeIndex.value - 1, -1)
    scrollActiveIntoView()
    return
  }
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    if (activeIndex.value === -1) {
      toggleAllMode()
      return
    }
    const opt = list[activeIndex.value]
    if (opt) select(opt.value)
  }
}

/** 键盘导航时保持焦点项在下拉可视区内（长列表滚动场景）。 */
const scrollActiveIntoView = () => {
  if (!dropdownRef.value) return
  if (activeIndex.value === -1) {
    // 全部账号项是下拉首个按钮
    const first = dropdownRef.value.querySelector<HTMLElement>('button')
    first?.scrollIntoView({ block: 'nearest' })
    return
  }
  const el = dropdownRef.value.querySelectorAll('button')[activeIndex.value + 1]
  el?.scrollIntoView({ block: 'nearest' })
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
    activeIndex.value = -1
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
      :aria-label="ariaLabel || placeholder || t('multiSelect.placeholder')"
      aria-haspopup="listbox"
      @click="toggle"
      @keydown="onKeydown"
    >
      <span
        class="truncate"
        :class="allMode
          ? 'text-sky-600 dark:text-sky-400 font-medium'
          : modelValue.length === 0 ? 'text-gray-400 dark:text-gray-400' : ''"
      >{{ selectedLabel }}</span>
      <ChevronDown class="w-4 h-4 text-gray-400 transition-transform duration-200 shrink-0" :class="isOpen ? 'rotate-180' : ''" />
    </button>

    <Teleport to="body">
      <Transition name="dropdown">
        <div v-if="isOpen" ref="dropdownRef" :style="dropdownStyle" class="ui-dropdown" role="listbox">
          <button
            type="button"
            class="ui-dropdown-item border-b border-gray-100 dark:border-gray-800/50 mb-0.5"
            :class="[
              allMode ? 'ui-dropdown-item-active !text-sky-600 dark:!text-sky-400' : '',
              activeIndex === -1 ? 'bg-gray-100 dark:bg-white/[0.06]' : '',
            ]"
            @click.stop="toggleAllMode"
          >
            <span class="truncate font-medium">{{ t('multiSelect.allAccounts') }}</span>
            <Check v-if="allMode" class="w-3.5 h-3.5 shrink-0 text-sky-500" />
          </button>
          <button
            v-for="(opt, idx) in options"
            :key="opt.value"
            type="button"
            class="ui-dropdown-item"
            :class="[
              allMode ? 'opacity-40 pointer-events-none' : '',
              !allMode && modelValue.includes(opt.value) ? 'ui-dropdown-item-active !text-sky-600 dark:!text-sky-400' : '',
              activeIndex === idx ? 'bg-gray-100 dark:bg-white/[0.06]' : '',
            ]"
            :aria-selected="!allMode && modelValue.includes(opt.value)"
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
