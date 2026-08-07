<script setup lang="ts">
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
}>()

const emit = defineEmits<{
  (e: 'update:searchQuery', v: string): void
  (e: 'update:modeFilter', v: TaskListModeFilter): void
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
</script>

<template>
  <div
    class="ui-card p-3 space-y-2.5"
    :class="selectedCount ? 'ring-1 ring-sky-400/30 border-sky-300/40 dark:border-sky-700/40' : ''"
    role="toolbar"
    :aria-label="t('tasks.selectAll')"
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
          :value="searchQuery"
          type="search"
          class="ui-input !pl-8 !h-9 !text-xs"
          :placeholder="t('common.searchPlaceholder')"
          :aria-label="t('common.search')"
          @input="emit('update:searchQuery', ($event.target as HTMLInputElement).value)"
        >
      </div>
      <div class="flex items-center gap-1 shrink-0 text-[11px]">
        <button
          type="button"
          class="px-2 py-1 rounded-sm border transition-colors"
          :class="modeFilter === 'all'
            ? 'border-sky-400 text-sky-700 dark:text-sky-300 bg-sky-50 dark:bg-sky-950/30'
            : 'border-gray-200 dark:border-gray-700 text-gray-500'"
          @click="emit('update:modeFilter', 'all')"
        >
          {{ t('tasks.filterAll') }}
        </button>
        <button
          type="button"
          class="px-2 py-1 rounded-sm border transition-colors"
          :class="modeFilter === 'listen'
            ? 'border-orange-400 text-orange-700 dark:text-orange-300 bg-orange-50 dark:bg-orange-950/30'
            : 'border-gray-200 dark:border-gray-700 text-gray-500'"
          @click="emit('update:modeFilter', 'listen')"
        >
          {{ t('tasks.filterListen') }}
          <span v-if="listenTaskCount" class="font-mono opacity-80">({{ listenTaskCount }})</span>
        </button>
        <button
          type="button"
          class="px-2 py-1 rounded-sm border transition-colors"
          :class="modeFilter === 'scheduled'
            ? 'border-violet-400 text-violet-700 dark:text-violet-300 bg-violet-50 dark:bg-violet-950/30'
            : 'border-gray-200 dark:border-gray-700 text-gray-500'"
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
      <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1" :disabled="!selectedCount || batchBusy" @click="emit('batch', 'enable')">
        <Power class="w-3.5 h-3.5" />
        {{ t('tasks.batchEnable') }}
      </button>
      <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1" :disabled="!selectedCount || batchBusy" @click="emit('batch', 'disable')">
        <Pause class="w-3.5 h-3.5" />
        {{ t('tasks.batchDisable') }}
      </button>
      <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1" :disabled="!selectedCount || batchBusy" @click="emit('batch', 'run')">
        <Play class="w-3.5 h-3.5" />
        {{ t('tasks.batchRun') }}
      </button>
      <button type="button" class="ui-btn-danger !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1" :disabled="!selectedCount || batchBusy" @click="emit('batch', 'delete')">
        <Trash2 class="w-3.5 h-3.5" />
        {{ t('tasks.batchDelete') }}
      </button>
      <div class="relative ml-auto" @click.stop>
        <button type="button" class="ui-btn-secondary !px-2.5 !py-1.5 !text-xs inline-flex items-center gap-1" @click="emit('toggle-template-menu')">
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
      v-if="hasListFilters"
      class="flex flex-wrap items-center gap-1.5 pt-0.5 border-t border-gray-100 dark:border-gray-800/50"
    >
      <span class="text-[10px] text-gray-400 shrink-0">{{ t('common.activeFilters') }}</span>
      <button
        v-if="searchQuery.trim()"
        type="button"
        class="inline-flex items-center gap-1 max-w-[14rem] px-2 py-0.5 rounded-sm text-[11px] ui-chip-sky"
        :title="t('common.clearFilters')"
        @click="emit('update:searchQuery', '')"
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
