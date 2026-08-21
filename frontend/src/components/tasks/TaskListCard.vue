<script setup lang="ts">
import { computed } from 'vue'
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
  /** 单任务启停请求在途的键（匹配 task.name 时禁用按钮防连点竞态） */
  toggleBusyKey?: string
  /** 触发运行请求在途的键（格式 `${task.name}:${account}`，匹配则禁用并转圈） */
  runBusyKey?: string
  /** 删除请求在途的键（匹配 task.name 时禁用删除按钮防连点） */
  deleteBusyKey?: string
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

/** 该任务任一账号的运行请求在途（runBusyKey 形如 `${task.name}:${account}`） */
const runTaskBusy = computed(() => Boolean(props.runBusyKey?.startsWith(`${props.task.name}:`)))
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
          :aria-label="t('tasks.selectTask', { name: task.name })"
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
            class="ui-badge !text-[10px] font-mono ui-chip-sky max-w-[min(12rem,100%)] truncate"
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
            class="ui-badge !text-[11px] ui-chip-violet"
            :title="task.targetStr"
          >
            {{ t('tasks.extraTargets', { n: task.targetCount - 1 }) }}
          </span>
          <button
            v-if="task.isListenMode && (task.hitCount || 0) > 0"
            type="button"
            class="ui-badge !text-[11px] ui-chip-emerald cursor-pointer hover:opacity-90"
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
        :disabled="toggleBusyKey === task.name"
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
            : (!task.enabled ? t('tasks.pausedHint')
              : (task.raw.execution_mode === 'listen' ? t('tasks.executeListenHint') : t('tasks.executeNow')))"
          :disabled="!task.enabled || task.raw.execution_mode === 'listen' || hasInvalidAccount || runTaskBusy"
          @click="task.enabled && task.raw.execution_mode !== 'listen' && !hasInvalidAccount && !runTaskBusy && emit('run', task)"
        >
          <span
            v-if="runTaskBusy"
            class="ui-spinner !w-3.5 !h-3.5 !border-2"
            aria-hidden="true"
          />
          <Play v-else class="w-3.5 h-3.5" />
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
            class="w-full text-left px-3 py-1.5 text-xs text-gray-700 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/[0.04] transition-colors truncate disabled:opacity-50 disabled:cursor-not-allowed"
            :disabled="runBusyKey === `${task.name}:${acc}`"
            @click="runBusyKey !== `${task.name}:${acc}` && emit('run-account', task, acc)"
          >
            <span v-if="runBusyKey === `${task.name}:${acc}`" class="ui-spinner !w-3 !h-3 !border-2 mr-1 align-middle" aria-hidden="true" />
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
        :disabled="deleteBusyKey === task.name"
        @click="deleteBusyKey !== task.name && emit('delete', task)"
      >
        <span
          v-if="deleteBusyKey === task.name"
          class="ui-spinner !w-3.5 !h-3.5 !border-2"
          aria-hidden="true"
        />
        <Trash2 v-else class="w-3.5 h-3.5" />
        <span>{{ t('tasks.delete') }}</span>
      </button>
    </div>
  </div>
</template>
