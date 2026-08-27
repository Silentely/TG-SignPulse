<script setup lang="ts">
import { Trash2, RefreshCw, X } from 'lucide-vue-next'
import { useI18n } from '../composables/useI18n'
import { useLogsPage } from '../composables/useLogsPage'
import Modal from '../components/Modal.vue'
import CustomSelect from '../components/CustomSelect.vue'
import DatePicker from '../components/DatePicker.vue'
import FlowLogViewer from '../components/FlowLogViewer.vue'
import FilterEmptyState from '../components/FilterEmptyState.vue'
import PageRetry from '../components/PageRetry.vue'

const { t } = useI18n()

const {
  activeTab,
  filterTask,
  filterAccount,
  filterDate,
  filterStatus,
  filterCategory,
  pageLoading,
  loadFailed,
  clearing,
  selectedLog,
  logDetail,
  detailLoading,
  loginLogs,
  logs,
  accountOptions,
  statusOptions,
  categoryOptions,
  failureCategoryLabel,
  hasActiveFilters,
  loadLogs,
  openLogDetail,
  handleClear,
  clearCategoryFilter,
  clearFilters,
} = useLogsPage()
</script>

<template>
  <div class="flex flex-col h-full">
    <!-- Tabs + actions -->
    <div class="flex items-end justify-between gap-4 mb-4 border-b border-gray-200 dark:border-gray-800/60">
      <div class="flex gap-1 sm:gap-6">
        <button
          type="button"
          class="px-1 pb-2.5 text-sm font-medium transition-colors border-b-2"
          :class="activeTab === 'tasks' ? 'border-sky-500 text-gray-900 dark:text-gray-100' : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'"
          @click="activeTab = 'tasks'"
        >
          {{ t('logs.taskLogs') }}
        </button>
        <button
          type="button"
          class="px-1 pb-2.5 text-sm font-medium transition-colors border-b-2"
          :class="activeTab === 'login' ? 'border-sky-500 text-gray-900 dark:text-gray-100' : 'border-transparent text-gray-500 hover:text-gray-700 dark:hover:text-gray-300'"
          @click="activeTab = 'login'"
        >
          {{ t('logs.auditLogs') }}
        </button>
      </div>

      <div class="flex items-center gap-0.5 pb-1.5">
        <button
          type="button"
          class="ui-icon-btn disabled:opacity-50"
          :title="t('common.refresh')"
          :aria-label="t('common.refresh')"
          :disabled="pageLoading"
          @click="loadLogs"
        >
          <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': pageLoading }" />
        </button>
        <button
          type="button"
          class="ui-icon-btn hover:!text-rose-600 dark:hover:!text-rose-400 hover:!bg-rose-50 dark:hover:!bg-rose-950/30 disabled:opacity-50"
          :title="t('logs.clear')"
          :aria-label="t('logs.clear')"
          :disabled="clearing || pageLoading"
          @click="handleClear"
        >
          <Trash2 class="w-4 h-4" />
        </button>
      </div>
    </div>

    <!-- Filters -->
    <div class="ui-card p-3 mb-5 space-y-2.5">
      <div
        class="grid gap-3"
        :class="activeTab === 'tasks' ? 'grid-cols-2 sm:grid-cols-4' : 'grid-cols-1 sm:grid-cols-2'"
      >
        <template v-if="activeTab === 'tasks'">
          <input
            v-model="filterTask"
            type="text"
            :placeholder="t('logs.taskName')"
            class="ui-input"
            :aria-label="t('logs.taskName')"
          >
          <CustomSelect v-model="filterAccount" :options="accountOptions" :ariaLabel="t('logs.colAccount')" />
          <CustomSelect v-model="filterStatus" :options="statusOptions" :ariaLabel="t('logs.colStatus')" />
          <CustomSelect v-model="filterCategory" :options="categoryOptions" :ariaLabel="t('logs.colCategory')" />
        </template>
        <DatePicker v-model="filterDate" />
      </div>
      <!-- 激活筛选 chip：失败分类 / 状态 / 账号 / 任务名 / 日期 可一键清 -->
      <div
        v-if="activeTab === 'tasks' && (filterCategory || filterTask.trim() || filterStatus === 'error' || filterAccount || filterDate)"
        class="flex flex-wrap items-center gap-1.5 pt-0.5 border-t border-gray-100 dark:border-gray-800/50"
      >
        <span class="text-[10px] text-gray-400 shrink-0">{{ t('common.activeFilters') }}</span>
        <button
          v-if="filterAccount"
          type="button"
          class="inline-flex items-center gap-1 max-w-[12rem] px-2 py-0.5 rounded-sm text-[11px] bg-sky-50 text-sky-800 border border-sky-100 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-800/50"
          @click="filterAccount = ''"
        >
          <span class="truncate">{{ t('logs.colAccount') }}: {{ filterAccount }}</span>
          <X class="w-3 h-3 shrink-0 opacity-70" />
        </button>
        <button
          v-if="filterCategory"
          type="button"
          class="inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-[11px] bg-amber-50 text-amber-900 border border-amber-100 dark:bg-amber-950/40 dark:text-amber-200 dark:border-amber-800/50"
          @click="clearCategoryFilter"
        >
          {{ failureCategoryLabel(filterCategory) || filterCategory }}
          <X class="w-3 h-3 shrink-0 opacity-70" />
        </button>
        <button
          v-if="filterStatus === 'error'"
          type="button"
          class="inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-[11px] bg-rose-50 text-rose-800 border border-rose-100 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-800/50"
          @click="filterStatus = ''"
        >
          {{ t('logs.failed') }}
          <X class="w-3 h-3 shrink-0 opacity-70" />
        </button>
        <button
          v-if="filterTask.trim()"
          type="button"
          class="inline-flex items-center gap-1 max-w-[12rem] px-2 py-0.5 rounded-sm text-[11px] bg-sky-50 text-sky-800 border border-sky-100 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-800/50"
          @click="filterTask = ''"
        >
          <span class="truncate">{{ t('logs.colTask') }}: {{ filterTask.trim() }}</span>
          <X class="w-3 h-3 shrink-0 opacity-70" />
        </button>
        <button
          v-if="filterDate"
          type="button"
          class="inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-[11px] bg-gray-100 dark:bg-gray-800/60 text-gray-700 dark:text-gray-300 border border-gray-200 dark:border-gray-700/60"
          :title="t('common.clearFilters')"
          @click="filterDate = ''"
        >
          {{ t('logs.colDate') }}: {{ filterDate }}
          <X class="w-3 h-3 shrink-0 opacity-70" />
        </button>
      </div>
    </div>

    <!-- Logs List -->
    <div class="ui-card p-3 sm:p-5 flex-1 min-h-[500px] overflow-y-auto">
      <div v-if="pageLoading" class="animate-pulse space-y-1.5" role="status" :aria-label="t('common.loading')">
        <div v-for="i in 6" :key="i" class="flex items-center gap-3 px-2 py-3">
          <span class="h-3 w-[140px] shrink-0 rounded bg-gray-200 dark:bg-gray-800" />
          <span class="h-3 w-24 shrink-0 rounded bg-gray-200 dark:bg-gray-800" />
          <span class="h-3 w-28 shrink-0 rounded bg-gray-200 dark:bg-gray-800" />
          <span class="h-4 w-12 shrink-0 rounded-full bg-gray-200 dark:bg-gray-800" />
          <span class="h-3 flex-1 min-w-0 rounded bg-gray-200 dark:bg-gray-800" />
        </div>
      </div>

      <!-- 首屏加载失败：错误态而非空列表，避免误导为暂无日志 -->
      <div v-else-if="loadFailed && logs.length === 0" class="max-w-xl mx-auto my-8">
        <PageRetry @retry="loadLogs" />
      </div>

      <!-- Task logs -->
      <div v-else-if="activeTab === 'tasks'" class="text-xs space-y-0">
        <div v-if="logs.length === 0" class="ui-empty !py-12">
          <FilterEmptyState
            v-if="hasActiveFilters"
            :title="t('common.filterNoResults')"
            :hint="t('common.filterNoResultsHint')"
            :action-text="t('common.clearAllFilters')"
            @action="clearFilters"
          />
          <template v-else>
            <p class="ui-empty-title !text-gray-500 dark:!text-gray-400 font-normal">{{ t('logs.empty') }}</p>
            <p class="ui-empty-desc">{{ t('logs.emptyHint') }}</p>
          </template>
        </div>
        <div v-else class="overflow-x-auto">
          <!-- header -->
          <div class="ui-table-head hidden sm:flex">
            <span class="w-[140px] shrink-0">{{ t('logs.colTime') }}</span>
            <span class="w-24 shrink-0">{{ t('logs.colAccount') }}</span>
            <span class="w-28 shrink-0">{{ t('logs.colTask') }}</span>
            <span class="w-16 shrink-0">{{ t('logs.colStatus') }}</span>
            <span class="flex-1">{{ t('logs.colSummary') }}</span>
          </div>
          <div
            v-for="log in logs"
            :key="`${log.account}-${log.task}-${log.created_at}-${log.id}`"
            class="ui-list-row flex items-center gap-3 px-2 py-2 cursor-pointer rounded-sm"
            role="button"
            tabindex="0"
            :aria-label="`${log.account} ${log.task} ${log.time}`"
            @click="openLogDetail(log)"
            @keydown.enter="openLogDetail(log)"
            @keydown.space.prevent="openLogDetail(log)"
          >
            <span class="font-mono text-gray-500 dark:text-gray-400 shrink-0 w-[140px] text-[11px]">{{ log.time }}</span>
            <span class="text-gray-700 dark:text-gray-400 shrink-0 w-24 truncate font-medium">{{ log.account }}</span>
            <span class="text-gray-600 dark:text-gray-500 shrink-0 w-28 truncate">{{ log.task }}</span>
            <span
              class="ui-badge shrink-0"
              :class="log.status === 'success' ? 'ui-badge-success' : 'ui-badge-error'"
            >
              <span class="ui-badge-dot" />
              {{ log.status === 'success' ? t('logs.success') : t('logs.failed') }}
            </span>
            <span
              class="truncate flex-1 min-w-0"
              :class="log.status === 'success' ? 'text-gray-700 dark:text-gray-300' : 'text-rose-600 dark:text-rose-400/90'"
              :title="log.text"
            >
              {{ log.text }}
            </span>
            <span
              v-if="log.status === 'error' && failureCategoryLabel(log.failure_category)"
              class="ui-badge ui-badge-warn hidden md:inline-flex shrink-0"
            >
              {{ failureCategoryLabel(log.failure_category) }}
            </span>
            <span
              v-if="log.flow_line_count > 0"
              class="hidden sm:inline shrink-0 text-[10px] text-gray-400 font-mono"
            >
              {{ log.flow_line_count }}{{ t('logs.linesSuffix') }}
            </span>
          </div>
        </div>
      </div>

      <!-- Login audit -->
      <div v-else class="text-xs space-y-0">
        <div v-if="loginLogs.length === 0" class="ui-empty !py-12">
          <p class="ui-empty-title !text-gray-500 dark:!text-gray-400 font-normal">{{ t('logs.emptyLogin') }}</p>
          <p class="ui-empty-desc">{{ t('logs.emptyLoginHint') }}</p>
        </div>
        <div v-else class="overflow-x-auto">
          <div class="ui-table-head hidden sm:flex">
            <span class="w-[140px] shrink-0">{{ t('logs.colTime') }}</span>
            <span class="w-24 shrink-0">{{ t('logs.colUser') }}</span>
            <span class="w-32 shrink-0">{{ t('logs.colIp') }}</span>
            <span class="w-16 shrink-0">{{ t('logs.colStatus') }}</span>
            <span class="flex-1">{{ t('logs.colSummary') }}</span>
          </div>
          <div
            v-for="log in loginLogs"
            :key="log.id"
            class="ui-list-row flex items-center gap-3 px-2 py-2 rounded-sm"
          >
            <span class="font-mono text-gray-500 dark:text-gray-400 shrink-0 w-[140px] text-[11px]">{{ log.time }}</span>
            <span class="text-gray-700 dark:text-gray-400 shrink-0 w-24 truncate font-medium">{{ log.username }}</span>
            <span class="text-gray-500 shrink-0 w-32 truncate font-mono text-[11px]">{{ log.ip }}</span>
            <span
              class="ui-badge shrink-0"
              :class="log.status === 'success' ? 'ui-badge-success' : 'ui-badge-error'"
            >
              <span class="ui-badge-dot" />
              {{ log.status === 'success' ? t('logs.success') : t('logs.failed') }}
            </span>
            <span
              class="truncate flex-1"
              :class="log.status === 'success' ? 'text-gray-700 dark:text-gray-300' : 'text-rose-600 dark:text-rose-400/90'"
            >
              {{ log.text }}
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Log Detail Modal -->
    <Modal
      :isOpen="!!selectedLog"
      :title="t('logs.detailTitle')"
      maxWidthClass="max-w-2xl"
      @close="selectedLog = null; logDetail = null"
    >
      <div v-if="selectedLog" class="space-y-3 text-sm">
        <div class="flex items-center gap-3 flex-wrap">
          <span
            class="ui-badge text-xs"
            :class="selectedLog.status === 'success' ? 'ui-badge-success' : 'ui-badge-error'"
          >
            <span class="ui-badge-dot" />
            {{ selectedLog.status === 'success' ? t('logs.execSuccess') : t('logs.execFailed') }}
          </span>
          <span
            v-if="selectedLog.status === 'error' && failureCategoryLabel(selectedLog.failure_category || logDetail?.failure_category)"
            class="ui-badge ui-badge-warn"
          >
            {{ failureCategoryLabel(selectedLog.failure_category || logDetail?.failure_category) }}
          </span>
        </div>
        <div class="grid grid-cols-2 gap-3 text-xs">
          <div class="space-y-0.5">
            <div class="text-gray-500">{{ t('logs.time') }}</div>
            <div class="text-gray-900 dark:text-gray-200 font-mono">{{ selectedLog.time }}</div>
          </div>
          <div class="space-y-0.5">
            <div class="text-gray-500">{{ t('logs.account') }}</div>
            <div class="text-gray-900 dark:text-gray-200">{{ selectedLog.account }}</div>
          </div>
          <div class="col-span-2 space-y-0.5">
            <div class="text-gray-500">{{ t('logs.task') }}</div>
            <div class="text-gray-900 dark:text-gray-200">{{ selectedLog.task }}</div>
          </div>
        </div>

        <div class="pt-2 border-t border-gray-200 dark:border-gray-800/60">
          <div v-if="detailLoading" class="flex items-center gap-2 text-xs text-gray-500 py-6 justify-center">
            <span class="ui-spinner !w-4 !h-4 !border-2" />
            {{ t('common.loading') }}
          </div>

          <FlowLogViewer
            v-else
            :lines="logDetail?.flow_logs || []"
            :last-target-message="logDetail?.last_target_message || logDetail?.bot_message || selectedLog.text"
            :truncated="!!logDetail?.flow_truncated"
            :empty-text="logDetail?.message || selectedLog.text || t('logs.noDetail')"
          />
        </div>
      </div>
    </Modal>
  </div>
</template>
