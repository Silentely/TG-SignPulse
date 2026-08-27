<script setup lang="ts">
/**
 * 关于 / 版本信息区块：版本号、Git SHA、构建时间、Python 运行时、运行时状态、更新检查。
 * 父组件 Settings.vue 持有版本数据并实现检查更新逻辑；本组件仅负责展示与触发刷新。
 */
import { Info, RefreshCw, ExternalLink } from 'lucide-vue-next'
import { useI18n } from '../../composables/useI18n'
import type { AppVersionInfo, RuntimeStatus, MemoryStatsResponse } from '../../lib/api'
import { formatMemoryRssFromStats } from '../../lib/memory-format'
import { formatDateTime } from '../../lib/datetime'

type VersionBannerKind = 'update' | 'latest' | 'error' | 'info'
interface VersionBanner {
  kind: VersionBannerKind
  text: string
  url?: string | null
}

const props = defineProps<{
  appVersion: AppVersionInfo | null
  runtimeStatus: RuntimeStatus | null
  memoryStats: MemoryStatsResponse | null
  versionBanner: VersionBanner | null
  versionLoading?: boolean
  checkLoading?: boolean
}>()

const emit = defineEmits<{
  (e: 'check-update'): void
}>()

const { t } = useI18n()

const shortSha = (sha?: string) => {
  if (!sha) return t('settings.unknownValue')
  return sha.length > 12 ? sha.slice(0, 12) : sha
}

const formatMemoryRss = () => {
  return formatMemoryRssFromStats(
    props.memoryStats?.stats,
    t('settings.unknownValue'),
  )
}
</script>

<template>
  <section class="ui-card p-6">
    <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-start justify-between gap-3">
      <div class="flex items-start gap-3 min-w-0">
        <span class="ui-section-icon" aria-hidden="true"><Info class="w-3.5 h-3.5" /></span>
        <div class="min-w-0">
          <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.aboutTitle') }}</h2>
          <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.aboutDesc') }}</p>
        </div>
      </div>
      <button
        type="button"
        class="ui-btn-secondary shrink-0 !px-3 !py-1 !text-xs inline-flex items-center gap-1.5"
        :disabled="checkLoading || versionLoading || !appVersion"
        @click="emit('check-update')"
      >
        <RefreshCw class="w-3.5 h-3.5" :class="checkLoading ? 'animate-spin' : ''" />
        {{ checkLoading ? t('settings.checkingUpdate') : t('settings.checkUpdate') }}
      </button>
    </div>

    <div class="space-y-4">
      <div
        v-if="appVersion"
        class="p-3 border border-gray-200 dark:border-gray-800/60 bg-gray-50/50 dark:bg-white/[0.02] text-xs space-y-1.5 font-mono"
      >
        <div class="text-gray-600 dark:text-gray-400">
          <span class="text-gray-500">{{ t('settings.currentVersion') }}:</span>
          <span class="ml-1 text-gray-900 dark:text-gray-100 font-medium">v{{ appVersion.version }}</span>
        </div>
        <div class="text-gray-600 dark:text-gray-400">
          <span class="text-gray-500">{{ t('settings.gitSha') }}:</span>
          <span class="ml-1">{{ shortSha(appVersion.git_sha) }}</span>
        </div>
        <div class="text-gray-600 dark:text-gray-400">
          <span class="text-gray-500">{{ t('settings.gitBranch') }}:</span>
          <span class="ml-1">{{ appVersion.git_branch || t('settings.unknownValue') }}</span>
        </div>
        <div class="text-gray-600 dark:text-gray-400">
          <span class="text-gray-500">{{ t('settings.buildTime') }}:</span>
          <span class="ml-1">{{ appVersion.build_time ? formatDateTime(appVersion.build_time) : t('settings.unknownValue') }}</span>
        </div>
        <div class="text-gray-600 dark:text-gray-400">
          <span class="text-gray-500">{{ t('settings.pythonRuntime') }}:</span>
          <span class="ml-1">{{ appVersion.python }}</span>
        </div>
      </div>
      <p v-else-if="versionLoading" class="text-xs text-gray-500">{{ t('common.processing') }}</p>

      <!-- 运行时状态 -->
      <div v-if="runtimeStatus" class="p-3 border border-gray-200 dark:border-gray-800/60 bg-gray-50/50 dark:bg-white/[0.02] text-xs space-y-1.5">
        <div class="font-medium text-gray-700 dark:text-gray-300 mb-1">{{ t('settings.runtimeStatus') }}</div>
        <div class="text-gray-600 dark:text-gray-400">
          {{ t('settings.schedulerLock') }}:
          <span :class="runtimeStatus.scheduler_lock_held ? 'text-emerald-600 dark:text-emerald-400' : 'text-amber-600 dark:text-amber-400'">
            {{ runtimeStatus.scheduler_lock_held ? t('settings.lockHeld') : t('settings.lockNotHeld') }}
          </span>
        </div>
        <div class="text-gray-600 dark:text-gray-400">
          {{ t('settings.legacyApi') }}:
          <span class="text-emerald-600 dark:text-emerald-400">
            {{
              runtimeStatus.legacy_tasks_removed !== false
                ? t('settings.legacyRemoved')
                : runtimeStatus.legacy_tasks_writable
                  ? t('settings.yes')
                  : t('settings.no')
            }}
          </span>
        </div>
        <div class="text-gray-600 dark:text-gray-400">
          {{ t('settings.dbLabel') }}: {{ runtimeStatus.database_is_sqlite ? t('settings.dbSqlite') : t('settings.dbExternal') }}
          <span v-if="runtimeStatus.monitor_shard"> · {{ t('settings.monitorShard', { shard: runtimeStatus.monitor_shard }) }}</span>
        </div>
        <div v-if="memoryStats?.available" class="text-gray-600 dark:text-gray-400">
          {{ t('settings.memoryRss') }}: {{ formatMemoryRss() }}
        </div>
      </div>

      <div
        v-if="versionBanner"
        class="text-xs rounded-md px-3 py-2 border"
        :class="{
          'border-sky-300/80 bg-sky-50 text-sky-900 dark:border-sky-500/30 dark:bg-sky-500/10 dark:text-sky-100': versionBanner.kind === 'update' || versionBanner.kind === 'info',
          'border-emerald-300/80 bg-emerald-50 text-emerald-900 dark:border-emerald-500/30 dark:bg-emerald-500/10 dark:text-emerald-100': versionBanner.kind === 'latest',
          'border-amber-300/80 bg-amber-50 text-amber-900 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-100': versionBanner.kind === 'error',
        }"
      >
        <div class="font-medium">{{ versionBanner.text }}</div>
        <p v-if="versionBanner.kind === 'update'" class="mt-1 opacity-90">{{ t('settings.updateAvailableHint') }}</p>
        <p v-if="versionBanner.kind === 'update'" class="mt-1 opacity-80 font-mono">{{ t('settings.upgradeDockerHint') }}</p>
        <a
          v-if="versionBanner.url"
          :href="versionBanner.url"
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex items-center gap-1 mt-2 text-sky-700 dark:text-sky-300 underline-offset-2 hover:underline"
        >
          {{ t('settings.openRelease') }}
          <ExternalLink class="w-3 h-3" />
        </a>
      </div>
    </div>
  </section>
</template>
