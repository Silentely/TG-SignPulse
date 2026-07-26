<script setup lang="ts">
import { Play, FileText, Edit2, Trash2, Power, Square, Copy } from 'lucide-vue-next'
import type { TaskUiItem } from '../../lib/types'
import type { ActiveRunSummary } from '../../lib/api'
import { useI18n } from '../../composables/useI18n'
import {
  badgeTone,
  badgeToneClass,
  isRunInProgress,
} from '../../lib/run-status'

const props = defineProps<{
  task: TaskUiItem
  selected: boolean
  cloneBusy?: boolean
  cancelBusyKey?: string
  runMenuOpen?: boolean
  runMenuAccounts?: string[]
  taskActiveRun: ActiveRunSummary | null
  taskActiveRuns: ActiveRunSummary[]
  activeRunBadgeText: string
  activeRunTooltip: string
  hasInvalidAccount: boolean
}>()

const emit = defineEmits<{
  (e: 'toggle-select', id: string): void
  (e: 'toggle-enabled', task: TaskUiItem): void
  (e: 'cancel-run', task: TaskUiItem): void
  (e: 'run', task: TaskUiItem): void
  (e: 'run-account', task: TaskUiItem, account: string): void
  (e: 'open-logs', task: TaskUiItem, tab?: 'history' | 'hits' | null): void
  (e: 'clone', task: TaskUiItem): void
  (e: 'edit', task: TaskUiItem): void
  (e: 'delete', task: TaskUiItem): void
}>()

const { t } = useI18n()

const cancelKey = () => {
  const ar = props.taskActiveRun
  return `${props.task.name}:${ar?.account_name || ''}`
}
</script>

<template>
  <div
    class="ui-card relative flex flex-col gap-3 p-4"
    :class="{
      'opacity-55': !task.enabled,
      'ring-1 ring-sky-400/40 border-sky-300/50 dark:border-sky-700/40': selected,
    }"
  >
    <div class="flex items-start gap-3 min-w-0">
      <label class="pt-1 shrink-0 cursor-pointer" @click.stop>
        <input
          type="checkbox"
          :checked="selected"
          class="ui-checkbox"
          @change="emit('toggle-select', task.id)"
        />
      </label>
      <div class="w-10 h-10 shrink-0 bg-gray-100 dark:bg-gray-800/80 flex items-center justify-center text-gray-500 border border-gray-200 dark:border-gray-700/60 overflow-hidden">
        <img v-if="task.chatAvatarUrl" :src="task.chatAvatarUrl" class="w-full h-full object-cover" alt="" />
        <component v-else :is="task.modeIcon" class="w-5 h-5 opacity-70" />
      </div>
      <div class="flex-1 min-w-0 space-y-1.5">
        <div class="text-sm font-medium text-gray-900 dark:text-gray-100 truncate" :title="task.name">
          {{ task.name }}
        </div>
        <div class="flex flex-wrap items-center gap-1.5 text-[11px] text-gray-500 dark:text-gray-400">
          <span
            class="ui-badge !text-[10px] font-mono bg-sky-50 text-sky-700 border-sky-100 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-800/50 max-w-[min(12rem,100%)] truncate"
            :title="task.scheduleMode"
          >
            {{ task.scheduleMode }}
          </span>
          <span
            class="ui-badge ui-badge-neutral !text-[10px] font-mono max-w-[min(16rem,100%)] truncate"
            :title="task.targetStr"
          >
            {{ task.targetStr }}
          </span>
          <span
            v-if="task.targetCount > 1"
            class="ui-badge !text-[11px] bg-violet-50 text-violet-700 border-violet-100 dark:bg-violet-950/40 dark:text-violet-300 dark:border-violet-800/50"
            :title="task.targetStr"
          >
            {{ t('tasks.extraTargets', { n: task.targetCount - 1 }) }}
          </span>
          <button
            v-if="task.isListenMode && (task.hitCount || 0) > 0"
            type="button"
            class="ui-badge !text-[11px] bg-emerald-50 text-emerald-700 border-emerald-100 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800/50 cursor-pointer hover:opacity-90"
            :title="t('tasks.hitsBadgeHint')"
            @click.stop="emit('open-logs', task, 'hits')"
          >
            {{ t('tasks.hitsBadge', { n: task.hitCount }) }}
          </button>
          <button
            v-if="task.lastRunSuccess === false"
            type="button"
            class="ui-badge ui-badge-error !text-[11px] max-w-full truncate cursor-pointer hover:opacity-90"
            :title="t('tasks.viewLogs')"
            @click.stop="emit('open-logs', task)"
          >
            {{ task.lastRunStr }}
          </button>
          <span
            v-else
            class="ui-badge !text-[11px] max-w-full truncate"
            :title="task.lastRunStr"
            :class="task.isListenMode && task.lastRunSuccess === null
              ? 'bg-orange-50 text-orange-600 border-orange-200 dark:bg-orange-900/30 dark:text-orange-400 dark:border-orange-800/50'
              : task.lastRunSuccess === null
                ? 'ui-badge-neutral'
                : 'ui-badge-success'"
          >
            {{ task.lastRunStr }}
          </span>
          <span
            v-if="taskActiveRun && isRunInProgress(taskActiveRun)"
            class="ui-badge !text-[11px] max-w-[16rem] truncate border"
            :class="badgeToneClass(badgeTone(taskActiveRun))"
            :title="activeRunTooltip || activeRunBadgeText"
          >
            <span class="ui-pulse-dot !bg-sky-500 mr-1" />
            {{ activeRunBadgeText }}
            <template v-if="taskActiveRuns.length > 1">
              ·{{ taskActiveRuns.length }}
            </template>
          </span>
          <span
            v-if="hasInvalidAccount"
            class="ui-badge ui-badge-error !text-[11px]"
            :title="t('tasks.accountInvalidHint')"
          >
            {{ t('tasks.accountInvalid') }}
          </span>
        </div>
      </div>
    </div>

    <div class="flex flex-wrap items-center gap-1 border-t border-gray-100 dark:border-gray-800/50 pt-2.5">
      <button
        type="button"
        class="ui-row-action"
        :class="task.enabled ? 'ui-row-action--positive' : ''"
        :title="task.enabled ? t('tasks.pause') : t('tasks.resume')"
        :aria-pressed="task.enabled"
        @click="emit('toggle-enabled', task)"
      >
        <Power class="w-3.5 h-3.5" />
        <span>{{ task.enabled ? t('tasks.pause') : t('tasks.resume') }}</span>
      </button>
      <button
        v-if="taskActiveRun && isRunInProgress(taskActiveRun)"
        type="button"
        class="ui-row-action ui-row-action--danger-strong"
        :title="t('tasks.cancelRun')"
        :disabled="cancelBusyKey === cancelKey()"
        @click="emit('cancel-run', task)"
      >
        <span
          v-if="cancelBusyKey === cancelKey()"
          class="ui-spinner !w-3.5 !h-3.5 !border-2"
          aria-hidden="true"
        />
        <Square v-else class="w-3.5 h-3.5" />
        <span>{{ t('tasks.cancelRun') }}</span>
      </button>
      <div class="relative" @click.stop>
        <button
          type="button"
          class="ui-row-action"
          :title="hasInvalidAccount
            ? t('tasks.accountInvalidHint')
            : (task.raw.execution_mode === 'listen' ? t('tasks.executeListenHint') : t('tasks.executeNow'))"
          :disabled="task.raw.execution_mode === 'listen' || hasInvalidAccount"
          @click="task.raw.execution_mode !== 'listen' && !hasInvalidAccount && emit('run', task)"
        >
          <Play class="w-3.5 h-3.5" />
          <span>{{ t('tasks.execute') }}</span>
        </button>
        <div
          v-if="runMenuOpen"
          class="absolute top-full left-0 mt-1 z-50 min-w-[140px] ui-card shadow-[var(--sp-shadow-md)] py-1"
        >
          <div class="px-3 py-1.5 text-[10px] text-gray-400 font-medium uppercase tracking-wide border-b border-gray-100 dark:border-gray-800">
            {{ t('tasks.selectAccount') }}
          </div>
          <button
            v-for="acc in (runMenuAccounts || [])"
            :key="acc"
            type="button"
            class="w-full text-left px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/[0.04] transition-colors truncate"
            @click="emit('run-account', task, acc)"
          >
            {{ acc }}
          </button>
        </div>
      </div>
      <button
        type="button"
        class="ui-row-action"
        :title="t('tasks.viewLogs')"
        @click="emit('open-logs', task)"
      >
        <FileText class="w-3.5 h-3.5" />
        <span>{{ t('tasks.logs') }}</span>
      </button>
      <button
        type="button"
        class="ui-row-action"
        :title="t('tasks.clone')"
        :disabled="cloneBusy"
        @click="emit('clone', task)"
      >
        <span v-if="cloneBusy" class="ui-spinner !w-3.5 !h-3.5 !border-2" aria-hidden="true" />
        <Copy v-else class="w-3.5 h-3.5" />
        <span>{{ t('tasks.clone') }}</span>
      </button>
      <button
        type="button"
        class="ui-row-action"
        :title="t('tasks.edit')"
        @click="emit('edit', task)"
      >
        <Edit2 class="w-3.5 h-3.5" />
        <span>{{ t('tasks.edit') }}</span>
      </button>
      <button
        type="button"
        class="ui-row-action ui-row-action--danger"
        :title="t('tasks.delete')"
        @click="emit('delete', task)"
      >
        <Trash2 class="w-3.5 h-3.5" />
        <span>{{ t('tasks.delete') }}</span>
      </button>
    </div>
  </div>
</template>
