<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { Plus, Power, Pause, Play, Trash2, Search, X, LayoutTemplate } from 'lucide-vue-next'
import { BUILT_IN_TEMPLATES } from '../../lib/task-templates'
import type { TaskListModeFilter } from '../../lib/task-list-filter'
import { useI18n } from '../../composables/useI18n'

const props = defineProps<{
  searchQuery: string
  modeFilter: TaskListModeFilter
  allSelected: boolean
  selectedCount: number
  batchBusy: boolean
  listenTaskCount: number
  hasListFilters: boolean
  accountFilter: string
  showTemplateMenu: boolean
  allTags?: string[]
  selectedTag?: string
}>()

const emit = defineEmits<{
  (e: 'update:searchQuery', v: string): void
  (e: 'update:modeFilter', v: TaskListModeFilter): void
  (e: 'update:selectedTag', v: string): void
  (e: 'toggle-select-all'): void
  (e: 'clear-selection'): void
  (e: 'batch', action: 'enable' | 'disable' | 'run' | 'delete'): void
  (e: 'toggle-template-menu'): void
  (e: 'pick-template', id: string): void
  (e: 'open-add'): void
  (e: 'clear-list-filters'): void
  (e: 'clear-account-filter'): void
}>()

const { t } = useI18n()

const localSearchQuery = ref(props.searchQuery)

watch(
  () => props.searchQuery,
  (value) => {
    localSearchQuery.value = value
  },
)

// 批量操作禁用原因提示：未选中时引导先选择，处理中提示等待
const batchDisabledTitle = computed(() =>
  props.batchBusy ? t('common.processing') : props.selectedCount ? undefined : t('tasks.selectFirstHint'),
)

// 模板下拉菜单：点击外部自动关闭（capture 阶段先于容器 @click.stop）
const menuRef = ref<HTMLElement | null>(null)
const closeTemplateMenuOnOutside = (e: MouseEvent) => {
  if (!props.showTemplateMenu) return
  const target = e.target as Node
  if (menuRef.value?.contains(target)) return
  emit('toggle-template-menu')
}
// Esc 关闭下拉（与 CustomSelect 等下拉控件语义一致，避免键盘用户卡在菜单里）
const closeTemplateMenuOnEsc = (e: KeyboardEvent) => {
  if (e.key !== 'Escape') return
  if (!props.showTemplateMenu) return
  e.stopPropagation()
  emit('toggle-template-menu')
}
watch(
  () => props.showTemplateMenu,
  (open) => {
    if (open) {
      document.addEventListener('click', closeTemplateMenuOnOutside, true)
      window.addEventListener('keydown', closeTemplateMenuOnEsc)
    } else {
      document.removeEventListener('click', closeTemplateMenuOnOutside, true)
      window.removeEventListener('keydown', closeTemplateMenuOnEsc)
    }
  },
)
const handleSearchInput = (e: Event) => {
  const val = (e.target as HTMLInputElement).value
  localSearchQuery.value = val
  emit('update:searchQuery', val)
}

const clearSearch = () => {
  localSearchQuery.value = ''
  emit('update:searchQuery', '')
}

onUnmounted(() => {
  document.removeEventListener('click', closeTemplateMenuOnOutside, true)
  window.removeEventListener('keydown', closeTemplateMenuOnEsc)
})
</script>

<template>
  <div
    class="ui-card p-3 space-y-2.5"
    :class="selectedCount ? 'ring-1 ring-sky-400/30 border-sky-300/40 dark:border-sky-700/40' : ''"
    role="toolbar"
    :aria-label="t('tasks.toolbarLabel')"
  >
    <div class="flex flex-col sm:flex-row sm:items-center gap-2">
      <label
        class="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400 cursor-pointer select-none shrink-0"
        :title="searchQuery.trim() ? t('tasks.selectAllFilteredHint') : undefined"
      >
        <input
          type="checkbox"
          :checked="allSelected"
          class="ui-checkbox"
          :aria-checked="allSelected"
          @change="emit('toggle-select-all')"
        />
        {{ searchQuery.trim() ? t('tasks.selectAllFiltered') : t('tasks.selectAll') }}
      </label>
      <div class="relative flex-1 min-w-0">
        <Search class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" />
        <input
          :value="localSearchQuery"
          type="search"
          class="ui-input !pl-8 !h-9 !text-xs"
          :placeholder="t('common.searchPlaceholder')"
          :aria-label="t('common.search')"
          @input="handleSearchInput"
        >
      </div>
      <div class="flex items-center gap-1 shrink-0 text-[11px]">
        <button
          type="button"
          class="px-2 py-1 rounded-sm border transition-colors"
          :aria-pressed="modeFilter === 'all'"
          :class="modeFilter === 'all'
            ? 'border-sky-400 text-sky-700 dark:text-sky-300 bg-sky-50 dark:bg-sky-950/30'
            : 'border-gray-200 dark:border-gray-700 text-gray-500 hover:border-gray-300 dark:hover:border-gray-600 hover:bg-gray-50 dark:hover:bg-white/[0.04]'"
          @click="emit('update:modeFilter', 'all')"
        >
          {{ t('tasks.filterAll') }}
        </button>
        <button
          type="button"
          class="px-2 py-1 rounded-sm border transition-colors"
          :aria-pressed="modeFilter === 'listen'"
          :class="modeFilter === 'listen'
            ? 'border-orange-400 text-orange-700 dark:text-orange-300 bg-orange-50 dark:bg-orange-950/30'
            : 'border-gray-200 dark:border-gray-700 text-gray-500 hover:border-gray-300 dark:hover:border-gray-600 hover:bg-gray-50 dark:hover:bg-white/[0.04]'"
          @click="emit('update:modeFilter', 'listen')"
        >
          {{ t('tasks.filterListen') }}
          <span v-if="listenTaskCount" class="font-mono opacity-80">({{ listenTaskCount }})</span>
        </button>
        <button
          type="button"
          class="px-2 py-1 rounded-sm border transition-colors"
          :aria-pressed="modeFilter === 'scheduled'"
          :class="modeFilter === 'scheduled'
            ? 'border-violet-400 text-violet-700 dark:text-violet-300 bg-violet-50 dark:bg-violet-950/30'
            : 'border-gray-200 dark:border-gray-700 text-gray-500 hover:border-gray-300 dark:hover:border-gray-600 hover:bg-gray-50 dark:hover:bg-white/[0.04]'"
          @click="emit('update:modeFilter', 'scheduled')"
        >
          {{ t('tasks.filterScheduled') }}
        </button>
      </div>
      <div v-if="selectedCount" class="flex items-center gap-2 shrink-0">
        <span class="text-xs font-mono text-sky-700 dark:text-sky-300">
          {{ t('tasks.selectedCount') }}: {{ selectedCount }}
        </span>
        <button
          type="button"
          class="text-[11px] text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 underline-offset-2 hover:underline"
          @click="emit('clear-selection')"
        >
          {{ t('common.cancel') }}
        </button>
      </div>
    </div>
    <div class="flex flex-wrap items-center gap-1.5">
      <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1" :disabled="!selectedCount || batchBusy" :title="batchDisabledTitle" :aria-disabled="!selectedCount || batchBusy" @click="emit('batch', 'enable')">
        <Power class="w-3.5 h-3.5" />
        {{ t('tasks.batchEnable') }}
      </button>
      <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1" :disabled="!selectedCount || batchBusy" :title="batchDisabledTitle" :aria-disabled="!selectedCount || batchBusy" @click="emit('batch', 'disable')">
        <Pause class="w-3.5 h-3.5" />
        {{ t('tasks.batchDisable') }}
      </button>
      <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1" :disabled="!selectedCount || batchBusy" :title="batchDisabledTitle" :aria-disabled="!selectedCount || batchBusy" @click="emit('batch', 'run')">
        <Play class="w-3.5 h-3.5" />
        {{ t('tasks.batchRun') }}
      </button>
      <button type="button" class="ui-btn-danger !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1" :disabled="!selectedCount || batchBusy" :title="batchDisabledTitle" :aria-disabled="!selectedCount || batchBusy" @click="emit('batch', 'delete')">
        <Trash2 class="w-3.5 h-3.5" />
        {{ t('tasks.batchDelete') }}
      </button>
      <div class="relative ml-auto" ref="menuRef" @click.stop>
        <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1" :aria-expanded="showTemplateMenu" aria-haspopup="menu" @click="emit('toggle-template-menu')">
          <LayoutTemplate class="w-3.5 h-3.5" />
          {{ t('tasks.fromTemplate') }}
        </button>
        <div
          v-if="showTemplateMenu"
          class="absolute right-0 top-full mt-1 z-30 min-w-[14rem] max-h-64 overflow-y-auto ui-dropdown shadow-[var(--sp-shadow-md)] p-1"
        >
          <button
            v-for="tpl in BUILT_IN_TEMPLATES"
            :key="tpl.id"
            type="button"
            class="w-full text-left px-3 py-2 text-xs hover:bg-gray-50 dark:hover:bg-white/[0.04] rounded-sm"
            @click="emit('pick-template', tpl.id)"
          >
            <div class="font-medium">{{ t(tpl.nameKey) }}</div>
            <div class="text-[10px] text-gray-500">{{ t(tpl.descKey) }}</div>
          </button>
        </div>
      </div>
      <button type="button" class="ui-btn-primary !px-2.5 !py-1.5 !text-xs" @click="emit('open-add')">
        <Plus class="w-3.5 h-3.5" /> {{ t('taskModal.addTitle') }}
      </button>
      <span v-if="batchBusy" class="ui-spinner !w-3.5 !h-3.5 !border-2" aria-hidden="true" />
    </div>
    <div
      v-if="allTags && allTags.length > 0"
      class="flex flex-wrap items-center gap-1.5 pt-1.5 border-t border-gray-100 dark:border-gray-800/40 text-[11px]"
    >
      <span class="text-[10px] text-gray-400 shrink-0">{{ t('tasks.tagsLabel') || '标签' }}:</span>
      <button
        v-for="tag in allTags"
        :key="tag"
        type="button"
        class="px-2 py-0.5 rounded text-[10px] font-mono transition-colors"
        :class="selectedTag === tag
          ? 'bg-teal-600 text-white dark:bg-teal-500 font-medium'
          : 'bg-teal-50 text-teal-700 dark:bg-teal-950/40 dark:text-teal-300 border border-teal-200 dark:border-teal-800/50 hover:bg-teal-100 dark:hover:bg-teal-900/40'"
        @click="emit('update:selectedTag', selectedTag === tag ? '' : tag)"
      >
        #{{ tag }}
      </button>
      <button
        v-if="selectedTag"
        type="button"
        class="text-[10px] text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 underline ml-1"
        @click="emit('update:selectedTag', '')"
      >
        {{ t('common.clear') }}
      </button>
    </div>
    <div
      v-if="hasListFilters"
      class="flex flex-wrap items-center gap-1.5 pt-0.5 border-t border-gray-100 dark:border-gray-800/50"
    >
      <span class="text-[10px] text-gray-400 shrink-0">{{ t('common.activeFilters') }}</span>
      <button
        v-if="searchQuery.trim()"
        type="button"
        class="inline-flex items-center gap-1 max-w-[14rem] px-2 py-0.5 rounded-sm text-[11px] ui-chip-sky"
        :title="t('common.clearFilters')"
        @click="clearSearch"
      >
        <span class="truncate">{{ t('common.search') }}: {{ searchQuery.trim() }}</span>
        <X class="w-3 h-3 shrink-0 opacity-70" />
      </button>
      <button
        v-if="modeFilter === 'listen'"
        type="button"
        class="inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-[11px] ui-chip-orange"
        @click="emit('update:modeFilter', 'all')"
      >
        {{ t('tasks.filterListen') }}
        <X class="w-3 h-3 shrink-0 opacity-70" />
      </button>
      <button
        v-if="modeFilter === 'scheduled'"
        type="button"
        class="inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-[11px] ui-chip-violet"
        @click="emit('update:modeFilter', 'all')"
      >
        {{ t('tasks.filterScheduled') }}
        <X class="w-3 h-3 shrink-0 opacity-70" />
      </button>
      <button
        v-if="selectedTag"
        type="button"
        class="inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-[11px] bg-teal-50 text-teal-700 dark:bg-teal-950/40 dark:text-teal-300 border border-teal-200 dark:border-teal-800/50"
        @click="emit('update:selectedTag', '')"
      >
        <span>#{{ selectedTag }}</span>
        <X class="w-3 h-3 shrink-0 opacity-70" />
      </button>
      <button
        v-if="accountFilter"
        type="button"
        class="inline-flex items-center gap-1 max-w-[12rem] px-2 py-0.5 rounded-sm text-[11px] ui-chip-sky"
        :title="t('tasks.clearAccountFilter')"
        @click="emit('clear-account-filter')"
      >
        <span class="truncate">{{ t('tasks.accountFilter') }}: {{ accountFilter }}</span>
        <X class="w-3 h-3 shrink-0 opacity-70" />
      </button>
      <button
        type="button"
        class="text-[11px] text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 underline-offset-2 hover:underline ml-auto shrink-0"
        @click="emit('clear-list-filters')"
      >
        {{ t('common.clearFilters') }}
      </button>
    </div>
  </div>
</template>
