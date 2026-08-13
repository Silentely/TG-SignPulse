<script setup lang="ts">
/**
 * 签到日志弹窗：实时流 + 历史执行记录。
 */
import { Loader2 } from 'lucide-vue-next'
import FlowLogViewer from '../FlowLogViewer.vue'
import type { SignTaskHistoryItem } from '../../lib/api'
import { useI18n } from '../../composables/useI18n'
import { formatPhaseDetail, stateLabel } from '../../lib/run-status'

const { t } = useI18n()

defineProps<{
  runAccount?: string
  isRunning: boolean
  livePhase: string | null
  livePhaseDetail: string
  liveState: string | null
  liveStatusLabel: string
  liveStatusToneClass: string
  realtimeLogs: string[]
  displayRealtimeLines: string[]
  loading: boolean
  logs: SignTaskHistoryItem[]
  expandedIdx: number | null
  formatDate: (dateStr: string) => string
  lineTone: (text: string) => string
}>()

const emit = defineEmits<{
  (e: 'toggle-expand', idx: number): void
  (e: 'set-log-container', el: HTMLElement | null): void
}>()

/** 追加式日志流的稳定 key：行号 + 内容前缀，避免整表替换时 DOM 复用错位 */
const realtimeLineKey = (i: number, line: string) => `${i}|${line.slice(0, 64)}`

/** 历史条目无后端 id，用 账号+时间+结果 组合稳定键 */
const historyItemKey = (log: SignTaskHistoryItem) =>
  `${log.account_name || '-'}|${log.time || log.created_at || ''}|${log.success ? 1 : 0}`
</script>

<template>
  <!-- 运行 phase 状态条（实时） -->
  <div
    v-if="runAccount && (isRunning || livePhaseDetail || livePhase)"
    class="mb-3 px-3 py-2 rounded-sm border text-xs flex flex-wrap items-center gap-2"
    :class="liveStatusToneClass"
  >
    <span class="font-medium">{{ formatPhaseDetail({ phase: livePhase, phase_detail: livePhaseDetail }, t) || liveStatusLabel }}</span>
    <span v-if="liveState && liveState !== 'running'" class="opacity-80">· {{ stateLabel(liveState, t) }}</span>
  </div>

  <!-- Real-time logs -->
  <div v-if="realtimeLogs.length > 0 || isRunning" class="mb-4">
    <div class="ui-section-label mb-2">{{ t('taskLogs.realtimeLogs') }}</div>
    <div
      class="ui-terminal whitespace-pre-wrap break-all !max-h-60"
      :ref="(el) => emit('set-log-container', el as HTMLElement | null)"
    >
      <div
        v-for="(line, i) in (displayRealtimeLines.length ? displayRealtimeLines : realtimeLogs)"
        :key="realtimeLineKey(i, String(line))"
        class="leading-relaxed"
        :class="lineTone(String(line))"
      >
        {{ line }}
      </div>
      <div v-if="isRunning && realtimeLogs.length === 0" class="text-gray-500 flex items-center gap-2">
        <Loader2 class="w-3 h-3 animate-spin" /> {{ t('taskLogs.waitingOutput') }}
      </div>
    </div>
  </div>

  <!-- Loading / empty -->
  <div v-if="loading && logs.length === 0 && realtimeLogs.length === 0" class="animate-pulse space-y-2 !py-4" role="status" :aria-label="t('common.loading')">
    <div v-for="i in 3" :key="i" class="flex items-center gap-3 px-2 py-2">
      <span class="h-3 w-24 shrink-0 rounded bg-gray-200 dark:bg-gray-800" />
      <span class="h-3 flex-1 min-w-0 rounded bg-gray-200 dark:bg-gray-800" />
    </div>
  </div>

  <div v-else-if="logs.length === 0 && realtimeLogs.length === 0 && !isRunning" class="ui-empty !py-10">
    <p class="ui-empty-desc">{{ t('taskLogs.noLogs') }}</p>
  </div>

  <!-- History -->
  <div v-if="logs.length > 0" class="space-y-3">
    <div class="ui-section-label mb-2">{{ t('taskLogs.history') }}</div>
    <div
      v-for="(log, idx) in logs"
      :key="historyItemKey(log)"
      class="ui-card p-3 text-sm"
    >
      <div class="flex items-center justify-between mb-2 gap-2">
        <span class="font-medium flex items-center gap-3 text-gray-900 dark:text-gray-200 flex-wrap">
          <span>{{ t('taskLogs.account') }}{{ log.account_name || t('taskLogs.unknown') }}</span>
          <span
            class="ui-badge"
            :class="log.success ? 'ui-badge-success' : 'ui-badge-error'"
          >
            <span class="ui-badge-dot" />
            {{ log.success ? t('taskLogs.success') : t('taskLogs.failed') }}
          </span>
        </span>
        <span class="text-xs text-gray-500 dark:text-gray-400 font-mono shrink-0">{{ formatDate(log.time || log.created_at || '') }}</span>
      </div>

      <div v-if="log.last_target_message || log.bot_message" class="mt-2 text-sm text-gray-700 dark:text-gray-300">
        <div class="ui-section-label mb-1">{{ t('taskLogs.lastResponse') }}</div>
        <div class="whitespace-pre-wrap break-all p-2 bg-white dark:bg-gray-950 border border-gray-200 dark:border-gray-800 text-xs">
          {{ log.last_target_message || log.bot_message }}
        </div>
      </div>

      <div v-if="(log.flow_logs && log.flow_logs.length > 0) || log.message || log.summary" class="mt-3">
        <button
          type="button"
          class="text-xs text-sky-600 dark:text-sky-400 hover:underline mb-2"
          @click="emit('toggle-expand', idx)"
        >
          {{ expandedIdx === idx ? t('taskLogs.collapseDetail') : t('taskLogs.expandDetail') }}
        </button>
        <FlowLogViewer
          v-if="expandedIdx === idx"
          :lines="log.flow_logs || (log.message || log.summary ? [String(log.message || log.summary)] : [])"
          :last-target-message="log.last_target_message || log.bot_message"
          :truncated="!!log.flow_truncated"
          compact
        />
      </div>
    </div>
  </div>
</template>
