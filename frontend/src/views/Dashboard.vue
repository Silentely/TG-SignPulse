<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Users, Zap, Terminal, Settings } from 'lucide-vue-next'
import type {
  ActiveRunSummary,
  KeywordHitRecord,
  AccountStatusJob,
} from '../lib/api'
import { useI18n } from '../composables/useI18n'
import { useDashboardData } from '../composables/useDashboardData'
import type { DashboardLog } from '../lib/types'
import Modal from '../components/Modal.vue'
import {
  badgeTone,
  badgeToneClass,
  failureCategoryLabel as mapFailureCategoryLabel,
  formatPhaseDetail,
  phaseLabel,
} from '../lib/run-status'
import { formatShortDateTime } from '../lib/datetime'

const quickLinks = [
  { name: 'accounts', icon: Users, titleKey: 'dashboard.goAccounts', descKey: 'dashboard.goAccountsDesc' },
  { name: 'tasks', icon: Zap, titleKey: 'dashboard.goTasks', descKey: 'dashboard.goTasksDesc' },
  { name: 'logs', icon: Terminal, titleKey: 'dashboard.goLogs', descKey: 'dashboard.goLogsDesc' },
  { name: 'settings', icon: Settings, titleKey: 'dashboard.goSettings', descKey: 'dashboard.goSettingsDesc' },
]

const { t } = useI18n()
const router = useRouter()
const selectedLog = ref<DashboardLog | null>(null)

const {
  pageLoading,
  liveConnected,
  stats,
  logs,
  upcomingJobs,
  activeRuns,
  failureBreakdown,
  recentHits,
  statusJobs,
  formatTime,
} = useDashboardData()

/** 跳转到日志页并按账号筛选，附带任务/时间/失败分类以便自动打开详情 */
const goToLogs = (log: DashboardLog) => {
  router.push({
    name: 'logs',
    query: {
      account: log.account && log.account !== '-' ? log.account : undefined,
      task: log.task && log.task !== '-' ? log.task : undefined,
      at: log.created_at || undefined,
      category:
        log.status === 'error' && log.failure_category
          ? log.failure_category
          : undefined,
    },
  })
}

/** 日志行稳定 key：SSE 前插/轮询替换时避免 index 复用错位 */
const logKey = (log: DashboardLog) =>
  `${log.created_at || log.time}|${log.account}|${log.task}|${(log.text || '').length}`

const formatJobTime = (iso?: string | null) => formatShortDateTime(iso)
const jobKindLabel = (kind: string) => {
  if (kind === 'sign') return t('dashboard.jobKindSign')
  if (kind === 'system') return t('dashboard.jobKindSystem')
  if (kind === 'legacy_db') return t('dashboard.jobKindLegacy')
  return kind
}

const failureCategoryLabel = (cat?: string) => mapFailureCategoryLabel(cat, t)

const openActiveRun = (run: ActiveRunSummary) => {
  router.push({
    name: 'tasks',
    query: {
      account: run.account_name || undefined,
      task: run.task_name || undefined,
    },
  })
}

const openFailureCategory = (category: string) => {
  if (category === 'session_invalid') {
    router.push({ name: 'accounts' })
    return
  }
  router.push({
    name: 'logs',
    query: { category: category || undefined },
  })
}

const openKeywordHit = (hit: KeywordHitRecord) => {
  router.push({
    name: 'tasks',
    query: {
      account: hit.account_name || undefined,
      task: hit.task_name || undefined,
      tab: 'hits',
    },
  })
}

const openStatusJob = () => {
  router.push({ name: 'accounts' })
}

const statusJobLabel = (job: AccountStatusJob) => {
  const done = job.progress?.done ?? 0
  const total = job.progress?.total ?? 0
  const ok = job.progress?.ok ?? job.summary?.ok ?? 0
  const fail = job.progress?.fail ?? job.summary?.fail ?? 0
  if (job.status === 'running' || job.status === 'canceling') {
    return `${done}/${total} · ${ok}/${fail}`
  }
  return `${job.summary?.ok ?? ok}/${job.summary?.fail ?? fail}`
}
</script>

<template>
  <div class="space-y-6">
    <!-- Page Loading skeleton -->
    <div v-if="pageLoading" class="space-y-6" aria-busy="true" aria-live="polite">
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
        <div v-for="i in 4" :key="i" class="ui-card p-5 min-h-[96px] space-y-4">
          <div class="ui-skeleton h-3 w-16" />
          <div class="ui-skeleton h-8 w-20" />
        </div>
      </div>
      <div class="ui-card p-5 space-y-3">
        <div class="ui-skeleton h-3 w-28" />
        <div v-for="i in 3" :key="i" class="ui-skeleton h-8 w-full" />
      </div>
      <div class="ui-card p-5 space-y-3 min-h-[240px]">
        <div class="ui-skeleton h-3 w-24" />
        <div v-for="i in 6" :key="i" class="ui-skeleton h-7 w-full" />
      </div>
    </div>

    <template v-else>
    <!-- Stats（可点击跳转） -->
    <div class="grid grid-cols-2 md:grid-cols-4 gap-3 sm:gap-4">
      <button
        v-for="stat in stats"
        :key="stat.key"
        type="button"
        class="ui-card ui-card-hover ui-stat p-5 flex flex-col justify-between min-h-[96px] text-left"
        :style="{
          '--sp-stat-accent':
            stat.key === 'dashboard.activeAccounts' ? 'var(--sp-accent)'
            : stat.key === 'dashboard.totalTasks' ? 'var(--sp-violet)'
            : stat.key === 'dashboard.recentSuccess' ? 'var(--sp-success)'
            : 'var(--sp-danger)'
        }"
        @click="router.push({
          name: stat.key === 'dashboard.totalTasks' ? 'tasks'
            : stat.key === 'dashboard.activeAccounts' ? 'accounts'
            : 'logs'
        })"
      >
        <span class="ui-section-label">{{ t(stat.key) }}</span>
        <span
          class="text-2xl sm:text-3xl font-mono font-medium text-gray-900 dark:text-gray-100 mt-3 tracking-tight"
          :title="t(stat.hintKey)"
        >{{ stat.value }}</span>
      </button>
    </div>

    <!-- 快捷入口 -->
    <div>
      <div class="ui-section-label mb-3">{{ t('dashboard.quickActions') }}</div>
      <div class="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <button
          v-for="link in quickLinks"
          :key="link.name"
          type="button"
          class="ui-card ui-card-hover text-left p-4 group"
          @click="router.push({ name: link.name })"
        >
          <div class="flex items-center gap-2.5 mb-2">
            <span class="ui-section-icon !w-8 !h-8 group-hover:scale-105 transition-transform">
              <component :is="link.icon" class="w-3.5 h-3.5" stroke-width="1.75" />
            </span>
            <span class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ t(link.titleKey) }}</span>
          </div>
          <p class="text-[11px] text-gray-500 leading-relaxed line-clamp-2">{{ t(link.descKey) }}</p>
        </button>
      </div>
    </div>

    <!-- 活跃运行 + 失败分类 -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div class="ui-card p-5">
        <div class="ui-section-label mb-4">{{ t('dashboard.activeRuns') }}</div>
        <div v-if="activeRuns.length === 0" class="ui-empty !py-8">
          <p class="ui-empty-desc">{{ t('dashboard.noActiveRuns') }}</p>
        </div>
        <div v-else class="space-y-1">
          <button
            v-for="(run, idx) in activeRuns"
            :key="`${run.task_name}-${run.account_name}-${run.run_id}-${idx}`"
            type="button"
            class="ui-list-row w-full flex items-center gap-2 text-xs px-2 py-2 rounded-sm text-left"
            @click="openActiveRun(run)"
          >
            <span
              class="ui-badge shrink-0 border !text-[10px]"
              :class="badgeToneClass(badgeTone(run))"
            >
              <span class="ui-pulse-dot !bg-sky-500" />
              {{ phaseLabel(run.phase, t) || formatPhaseDetail(run, t) || t('runStatus.inProgress') }}
            </span>
            <span class="font-mono truncate text-gray-800 dark:text-gray-200" :title="run.task_name">{{ run.task_name || '-' }}</span>
            <span class="text-gray-500 truncate shrink-0 max-w-[6rem]" :title="run.account_name">{{ run.account_name || '-' }}</span>
            <span class="ml-auto text-[10px] text-gray-400 font-mono shrink-0 truncate max-w-[40%]" :title="formatPhaseDetail(run, t)">
              {{ formatPhaseDetail(run, t) }}
            </span>
          </button>
        </div>
      </div>
      <div class="ui-card p-5">
        <div class="ui-section-label mb-4">{{ t('dashboard.failureBreakdown') }}</div>
        <div v-if="failureBreakdown.length === 0" class="ui-empty !py-8">
          <p class="ui-empty-desc">{{ t('dashboard.noFailureBreakdown') }}</p>
        </div>
        <div v-else class="flex flex-wrap gap-2">
          <button
            v-for="item in failureBreakdown"
            :key="item.category"
            type="button"
            class="ui-badge ui-badge-error !text-[11px] cursor-pointer hover:opacity-90"
            @click="openFailureCategory(item.category)"
          >
            {{ failureCategoryLabel(item.category) || item.category }}: {{ item.count }}
          </button>
        </div>
      </div>
    </div>

    <!-- 最近关键词命中 + 账号状态 Job -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-4">
      <div class="ui-card p-5">
        <div class="ui-section-label mb-4 flex items-center justify-between gap-2">
          <span>{{ t('dashboard.recentHits') }}</span>
          <button
            type="button"
            class="text-[11px] text-sky-600 dark:text-sky-400 hover:underline"
            @click="router.push({ name: 'tasks' })"
          >
            {{ t('dashboard.viewTasks') }}
          </button>
        </div>
        <div v-if="recentHits.length === 0" class="ui-empty !py-8">
          <p class="ui-empty-desc">{{ t('dashboard.noRecentHits') }}</p>
        </div>
        <div v-else class="space-y-1">
          <button
            v-for="hit in recentHits"
            :key="hit.id"
            type="button"
            class="ui-list-row w-full flex items-center gap-2 text-xs px-2 py-2 rounded-sm text-left"
            @click="openKeywordHit(hit)"
          >
            <span class="font-mono text-sky-700 dark:text-sky-300 shrink-0 max-w-[5.5rem] truncate" :title="hit.keyword">
              {{ hit.keyword || '-' }}
            </span>
            <span class="truncate text-gray-700 dark:text-gray-300" :title="hit.task_name">
              {{ hit.task_name || '-' }}
            </span>
            <span class="text-gray-500 truncate shrink-0 max-w-[5rem]" :title="hit.account_name">
              {{ hit.account_name || '-' }}
            </span>
            <span class="ml-auto text-[10px] text-gray-400 font-mono shrink-0">
              {{ formatTime(hit.time) }}
            </span>
          </button>
        </div>
      </div>
      <div class="ui-card p-5">
        <div class="ui-section-label mb-4 flex items-center justify-between gap-2">
          <span>{{ t('dashboard.statusJobs') }}</span>
          <button
            type="button"
            class="text-[11px] text-sky-600 dark:text-sky-400 hover:underline"
            @click="openStatusJob"
          >
            {{ t('dashboard.goAccounts') }}
          </button>
        </div>
        <div v-if="statusJobs.length === 0" class="ui-empty !py-8">
          <p class="ui-empty-desc">{{ t('dashboard.noStatusJobs') }}</p>
        </div>
        <div v-else class="space-y-1">
          <button
            v-for="job in statusJobs"
            :key="job.job_id"
            type="button"
            class="ui-list-row w-full flex items-center gap-2 text-xs px-2 py-2 rounded-sm text-left"
            @click="openStatusJob"
          >
            <span
              class="ui-badge shrink-0 !text-[10px]"
              :class="job.status === 'running' || job.status === 'canceling'
                ? 'border-sky-200 text-sky-700 dark:border-sky-800 dark:text-sky-300 bg-sky-50 dark:bg-sky-950/40'
                : job.status === 'failed'
                  ? 'ui-badge-error'
                  : 'ui-badge-neutral'"
            >
              <span
                v-if="job.status === 'running' || job.status === 'canceling'"
                class="ui-pulse-dot !bg-sky-500"
              />
              {{ job.status }}
            </span>
            <span class="font-mono text-gray-700 dark:text-gray-300 truncate">
              {{ statusJobLabel(job) }}
            </span>
            <span class="ml-auto text-[10px] text-gray-400 font-mono shrink-0">
              {{ formatTime(job.updated_at || job.created_at || '') }}
            </span>
          </button>
        </div>
      </div>
    </div>

    <!-- Upcoming schedule -->
    <div class="ui-card p-5">
      <div class="ui-section-label mb-4">{{ t('dashboard.upcomingJobs') }}</div>
      <div v-if="upcomingJobs.length === 0" class="ui-empty !py-8">
        <p class="ui-empty-desc">{{ t('dashboard.noUpcoming') }}</p>
      </div>
      <div v-else class="space-y-0.5">
        <div
          v-for="job in upcomingJobs"
          :key="job.id"
          class="ui-list-row flex items-center gap-3 text-xs px-2 py-2 rounded-sm"
        >
          <span class="font-mono text-gray-500 w-28 shrink-0">{{ formatJobTime(job.next_run_time) }}</span>
          <span
            class="ui-badge shrink-0"
            :class="job.kind === 'sign' ? 'border-sky-200 text-sky-700 dark:border-sky-800 dark:text-sky-300 bg-sky-50 dark:bg-sky-950/40' : 'ui-badge-neutral'"
          >
            {{ jobKindLabel(job.kind) }}
          </span>
          <span class="truncate text-gray-800 dark:text-gray-200 font-mono" :title="job.id">{{ job.id }}</span>
        </div>
      </div>
    </div>

    <!-- Terminal Logs -->
    <div class="ui-card p-5 min-h-[400px]">
      <div class="ui-section-label mb-4 flex items-center gap-2 flex-wrap">
        <span>{{ t('dashboard.recentLogs') }}</span>
        <span
          class="ui-badge"
          :class="liveConnected ? 'ui-badge-success' : 'ui-badge-neutral'"
        >
          <span :class="liveConnected ? 'ui-pulse-dot' : 'ui-badge-dot'" />
          {{ liveConnected ? t('dashboard.liveOn') : t('dashboard.liveOff') }}
        </span>
      </div>
      <div v-if="logs.length === 0" class="ui-empty py-16">
        <p class="ui-empty-title !text-gray-500 font-normal">{{ t('logs.empty') }}</p>
        <p class="ui-empty-desc">{{ t('logs.emptyHint') }}</p>
      </div>
      <div v-else class="text-xs overflow-x-auto space-y-0">
        <div
          v-for="log in logs"
          :key="logKey(log)"
          class="ui-list-row flex items-center gap-3 px-2 py-2 cursor-pointer rounded-sm"
          :title="t('dashboard.openInLogs')"
          @click="selectedLog = log"
          @dblclick="goToLogs(log)"
        >
          <span class="font-mono text-gray-500 dark:text-gray-600 shrink-0 w-[72px] text-[11px]">{{ log.time }}</span>
          <span class="text-gray-700 dark:text-gray-400 shrink-0 w-24 truncate font-medium">{{ log.account }}</span>
          <span class="text-gray-600 dark:text-gray-500 shrink-0 w-28 truncate">{{ log.task }}</span>
          <span
            class="ui-badge shrink-0"
            :class="log.status === 'success' ? 'ui-badge-success' : 'ui-badge-error'"
          >
            <span class="ui-badge-dot" />
            {{ log.status === 'success' ? t('logs.success') : t('logs.failed') }}
          </span>
          <button
            v-if="log.status === 'error' && failureCategoryLabel(log.failure_category)"
            type="button"
            class="ui-badge ui-badge-warn shrink-0 cursor-pointer hover:opacity-90"
            :title="t('dashboard.openFailureInLogs')"
            @click.stop="openFailureCategory(String(log.failure_category))"
          >
            {{ failureCategoryLabel(log.failure_category) }}
          </button>
          <span
            class="truncate flex-1 min-w-0"
            :class="log.status === 'success' ? 'text-gray-700 dark:text-gray-300' : 'text-rose-600 dark:text-rose-400/90'"
            :title="log.text"
          >
            {{ log.text }}
          </span>
        </div>
      </div>
    </div>

    <!-- Log Detail Modal -->
    <Modal :isOpen="!!selectedLog" @close="selectedLog = null" :title="t('logs.detailTitle')" maxWidthClass="max-w-lg">
      <div v-if="selectedLog" class="space-y-3 text-sm">
        <div class="flex items-center gap-3">
          <span
            class="ui-badge text-xs"
            :class="selectedLog.status === 'success' ? 'ui-badge-success' : 'ui-badge-error'"
          >
            <span class="ui-badge-dot" />
            {{ selectedLog.status === 'success' ? t('logs.execSuccess') : t('logs.execFailed') }}
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
          <div v-if="selectedLog.status === 'error' && failureCategoryLabel(selectedLog.failure_category)" class="col-span-2 space-y-0.5">
            <div class="text-gray-500">{{ t('dashboard.failureCategory') }}</div>
            <button
              type="button"
              class="text-amber-700 dark:text-amber-400 hover:underline text-left"
              :title="t('dashboard.openFailureInLogs')"
              @click="openFailureCategory(String(selectedLog.failure_category)); selectedLog = null"
            >
              {{ failureCategoryLabel(selectedLog.failure_category) }}
            </button>
          </div>
        </div>
        <div class="pt-2 border-t border-gray-200 dark:border-gray-800/60">
          <div class="text-xs text-gray-500 mb-1.5 font-medium">{{ t('logs.execInfo') }}</div>
          <div class="p-2.5 bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-gray-800/60 text-xs whitespace-pre-wrap break-all max-h-60 overflow-y-auto text-gray-800 dark:text-gray-300">{{ selectedLog.text || t('logs.noDetail') }}</div>
        </div>
        <div class="pt-1 flex justify-end">
          <button
            type="button"
            class="text-xs text-sky-600 dark:text-sky-400 hover:underline"
            @click="goToLogs(selectedLog); selectedLog = null"
          >
            {{ t('dashboard.openInLogs') }}
          </button>
        </div>
      </div>
    </Modal>
    </template>
  </div>
</template>
