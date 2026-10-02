<script setup lang="ts">
import { ref, computed, watch, onUnmounted } from 'vue'
import { Plus, Power, Pause, Play, Trash2, Search, LayoutTemplate } from 'lucide-vue-next'
import FilterChip from '../FilterChip.vue'
import { BUILT_IN_TEMPLATES } from '../../lib/task-templates'
import type { TaskListModeFilter } from '../../lib/task-list-filter'
import { useI18n } from '../../composables/useI18n'
import { useEscClose } from '../../composables/useEscClose'

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
useEscClose(
  () => props.showTemplateMenu,
  () => emit('toggle-template-menu'),
)
watch(
  () => props.showTemplateMenu,
  (open) => {
    if (open) {
      document.addEventListener('click', closeTemplateMenuOnOutside, true)
    } else {
      document.removeEventListener('click', closeTemplateMenuOnOutside, true)
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

onUnmounted(() => document.removeEventListener('click', closeTemplateMenuOnOutside, true))
</script>

<template>
  <div
    class="ui-card p-3 space-y-2.5"
    :class="selectedCount ? 'ring-1 ring-[var(--sp-accent)]/30 border-[var(--sp-accent)]/40' : ''"
    role="toolbar"
    :aria-label="t('tasks.toolbarLabel')"
  >
    <div class="flex flex-col sm:flex-row sm:items-center gap-2">
      <label
        class="flex items-center gap-2 text-xs text-[var(--sp-text-secondary)] cursor-pointer select-none shrink-0"
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
        <Search class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[var(--sp-text-muted)] pointer-events-none" />
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
          class="px-2.5 py-1 rounded-[var(--sp-radius-sm)] border transition-colors cursor-pointer"
          :aria-pressed="modeFilter === 'all'"
          :class="modeFilter === 'all'
            ? 'border-sky-400 text-[var(--sp-accent)] bg-sky-50 dark:bg-sky-950/40 border-[var(--sp-accent)]'
            : 'border-[var(--sp-border)] text-[var(--sp-text-secondary)] hover:border-[var(--sp-border-strong)] hover:bg-[var(--sp-surface-muted)]'"
          @click="emit('update:modeFilter', 'all')"
        >
          {{ t('tasks.filterAll') }}
        </button>
        <button
          type="button"
          class="px-2.5 py-1 rounded-[var(--sp-radius-sm)] border transition-colors cursor-pointer"
          :aria-pressed="modeFilter === 'listen'"
          :class="modeFilter === 'listen'
            ? 'border-orange-400 text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/40 border-amber-400 dark:border-amber-600'
            : 'border-[var(--sp-border)] text-[var(--sp-text-secondary)] hover:border-[var(--sp-border-strong)] hover:bg-[var(--sp-surface-muted)]'"
          @click="emit('update:modeFilter', 'listen')"
        >
          {{ t('tasks.filterListen') }}
          <span v-if="listenTaskCount" class="font-mono opacity-80">({{ listenTaskCount }})</span>
        </button>
        <button
          type="button"
          class="px-2.5 py-1 rounded-[var(--sp-radius-sm)] border transition-colors cursor-pointer"
          :aria-pressed="modeFilter === 'scheduled'"
          :class="modeFilter === 'scheduled'
            ? 'border-violet-400 text-indigo-700 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-950/40 border-indigo-400 dark:border-indigo-600'
            : 'border-[var(--sp-border)] text-[var(--sp-text-secondary)] hover:border-[var(--sp-border-strong)] hover:bg-[var(--sp-surface-muted)]'"
          @click="emit('update:modeFilter', 'scheduled')"
        >
          {{ t('tasks.filterScheduled') }}
        </button>
      </div>
      <div v-if="selectedCount" class="flex items-center gap-2 shrink-0">
        <span class="text-xs font-mono text-[var(--sp-accent)]">
          {{ t('tasks.selectedCount') }}: {{ selectedCount }}
        </span>
        <button
          type="button"
          class="text-[11px] text-[var(--sp-text-muted)] hover:text-[var(--sp-text)] underline-offset-2 hover:underline cursor-pointer"
          @click="emit('clear-selection')"
        >
          {{ t('common.cancel') }}
        </button>
      </div>
    </div>
    <div class="flex flex-wrap items-center gap-1.5">
      <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1 cursor-pointer" :disabled="!selectedCount || batchBusy" :title="batchDisabledTitle" :aria-disabled="!selectedCount || batchBusy" @click="emit('batch', 'enable')">
        <Power class="w-3.5 h-3.5" />
        {{ t('tasks.batchEnable') }}
      </button>
      <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1 cursor-pointer" :disabled="!selectedCount || batchBusy" :title="batchDisabledTitle" :aria-disabled="!selectedCount || batchBusy" @click="emit('batch', 'disable')">
        <Pause class="w-3.5 h-3.5" />
        {{ t('tasks.batchDisable') }}
      </button>
      <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1 cursor-pointer" :disabled="!selectedCount || batchBusy" :title="batchDisabledTitle" :aria-disabled="!selectedCount || batchBusy" @click="emit('batch', 'run')">
        <Play class="w-3.5 h-3.5" />
        {{ t('tasks.batchRun') }}
      </button>
      <button type="button" class="ui-btn-danger !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1 cursor-pointer" :disabled="!selectedCount || batchBusy" :title="batchDisabledTitle" :aria-disabled="!selectedCount || batchBusy" @click="emit('batch', 'delete')">
        <Trash2 class="w-3.5 h-3.5" />
        {{ t('tasks.batchDelete') }}
      </button>
      <div class="relative ml-auto" ref="menuRef" @click.stop>
        <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1 cursor-pointer" :aria-expanded="showTemplateMenu" aria-haspopup="menu" @click="emit('toggle-template-menu')">
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
            class="w-full text-left px-3 py-2 text-xs hover:bg-[var(--sp-surface-muted)] rounded-[var(--sp-radius-sm)] cursor-pointer"
            @click="emit('pick-template', tpl.id)"
          >
            <div class="font-medium">{{ t(tpl.nameKey) }}</div>
            <div class="text-[10px] text-[var(--sp-text-muted)]">{{ t(tpl.descKey) }}</div>
          </button>
        </div>
      </div>
      <button type="button" class="ui-btn-primary !px-2.5 !py-1.5 !text-xs cursor-pointer" @click="emit('open-add')">
        <Plus class="w-3.5 h-3.5" /> {{ t('taskModal.addTitle') }}
      </button>
      <span v-if="batchBusy" class="ui-spinner !w-3.5 !h-3.5 !border-2" aria-hidden="true" />
    </div>
    <div
      v-if="allTags && allTags.length > 0"
      class="flex flex-wrap items-center gap-1.5 pt-1.5 border-t border-[var(--sp-border)] text-[11px]"
    >
      <span class="text-[10px] text-[var(--sp-text-muted)] shrink-0">{{ t('tasks.tagsLabel') || '标签' }}:</span>
      <button
        v-for="tag in allTags"
        :key="tag"
        type="button"
        class="px-2 py-0.5 rounded-[var(--sp-radius-sm)] text-[10px] font-mono transition-colors cursor-pointer"
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
        class="text-[10px] text-[var(--sp-text-muted)] hover:text-[var(--sp-text-secondary)] dark:hover:text-[var(--sp-text)] underline ml-1"
        @click="emit('update:selectedTag', '')"
      >
        {{ t('common.clear') }}
      </button>
    </div>
    <div
      v-if="hasListFilters"
      class="flex flex-wrap items-center gap-1.5 pt-0.5 border-t border-[var(--sp-border)] dark:border-[var(--sp-border)]"
    >
      <span class="text-[10px] text-[var(--sp-text-muted)] shrink-0">{{ t('common.activeFilters') }}</span>
      <FilterChip
        v-if="searchQuery.trim()"
        tone="sky"
        truncate
        :title="t('common.clearFilters')"
        @clear="clearSearch"
      >
        {{ t('common.search') }}: {{ searchQuery.trim() }}
      </FilterChip>
      <FilterChip
        v-if="modeFilter === 'listen'"
        tone="orange"
        @clear="emit('update:modeFilter', 'all')"
      >
        {{ t('tasks.filterListen') }}
      </FilterChip>
      <FilterChip
        v-if="modeFilter === 'scheduled'"
        tone="violet"
        @clear="emit('update:modeFilter', 'all')"
      >
        {{ t('tasks.filterScheduled') }}
      </FilterChip>
      <FilterChip
        v-if="selectedTag"
        tone="teal"
        @clear="emit('update:selectedTag', '')"
      >
        #{{ selectedTag }}
      </FilterChip>
      <FilterChip
        v-if="accountFilter"
        tone="sky"
        truncate
        :title="t('tasks.clearAccountFilter')"
        @clear="emit('clear-account-filter')"
      >
        {{ t('tasks.accountFilter') }}: {{ accountFilter }}
      </FilterChip>
      <button
        type="button"
        class="text-[11px] text-[var(--sp-text-muted)] hover:text-[var(--sp-text)] underline-offset-2 hover:underline cursor-pointer ml-auto shrink-0"
        @click="emit('clear-list-filters')"
      >
        {{ t('common.clearFilters') }}
      </button>
    </div>
  </div>
</template>
