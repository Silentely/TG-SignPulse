<script setup lang="ts">
/**
 * 签到日志弹窗：关键词命中列表 / 分组视图。
 */
import type { KeywordHitRecord, KeywordHitGroup } from '../../lib/api'
import { useI18n } from '../../composables/useI18n'

const { t } = useI18n()

defineProps<{
  hitsLoading: boolean
  hitsLoadingMore: boolean
  hitsView: 'list' | 'groups'
  hitGroupBy: 'task' | 'account' | 'chat'
  hitRecords: KeywordHitRecord[]
  hitGroups: KeywordHitGroup[]
  hitTotal: number
  canLoadMoreHits: boolean
  formatDate: (dateStr: string) => string
  hitLink: (hit: KeywordHitRecord) => string | null
}>()

const emit = defineEmits<{
  (e: 'update:hitsView', v: 'list' | 'groups'): void
  (e: 'update:hitGroupBy', v: 'task' | 'account' | 'chat'): void
  (e: 'clear-hits'): void
  (e: 'load-more'): void
}>()
</script>

<template>
  <div class="mb-3 flex flex-wrap items-center gap-2">
    <div class="flex items-center gap-1 text-[11px]">
      <button
        type="button"
        class="px-2 py-1 rounded-sm border"
        :class="hitsView === 'list' ? 'border-sky-400 text-sky-700 dark:text-sky-300' : 'border-gray-200 dark:border-gray-700 text-gray-500'"
        @click="emit('update:hitsView', 'list')"
      >
        {{ t('taskLogs.hitsList') }}
      </button>
      <button
        type="button"
        class="px-2 py-1 rounded-sm border"
        :class="hitsView === 'groups' ? 'border-sky-400 text-sky-700 dark:text-sky-300' : 'border-gray-200 dark:border-gray-700 text-gray-500'"
        @click="emit('update:hitsView', 'groups')"
      >
        {{ t('taskLogs.hitsGroups') }}
      </button>
    </div>
    <select
      v-if="hitsView === 'groups'"
      class="ui-input !h-8 !text-xs !w-auto"
      :value="hitGroupBy"
      @change="emit('update:hitGroupBy', ($event.target as HTMLSelectElement).value as 'task' | 'account' | 'chat')"
    >
      <option value="chat">{{ t('taskLogs.groupByChat') }}</option>
      <option value="account">{{ t('taskLogs.groupByAccount') }}</option>
      <option value="task">{{ t('taskLogs.groupByTask') }}</option>
    </select>
    <span class="text-[10px] text-gray-400 hidden md:inline">{{ t('taskLogs.hitsAutoRefreshHint') }}</span>
    <button
      type="button"
      class="ml-auto text-[11px] text-rose-600 dark:text-rose-400 hover:underline"
      @click="emit('clear-hits')"
    >
      {{ t('taskLogs.hitsClear') }}
    </button>
  </div>

  <div v-if="hitsLoading" class="ui-page-loading !py-10">
    <div class="ui-spinner" />
  </div>
  <div v-else-if="hitsView === 'list' && hitRecords.length === 0" class="ui-empty !py-10">
    <p class="ui-empty-desc">{{ t('taskLogs.hitsEmpty') }}</p>
  </div>
  <div v-else-if="hitsView === 'groups' && hitGroups.length === 0" class="ui-empty !py-10">
    <p class="ui-empty-desc">{{ t('taskLogs.hitsEmpty') }}</p>
  </div>

  <div v-else-if="hitsView === 'list'" class="space-y-2">
    <div
      v-for="hit in hitRecords"
      :key="hit.id"
      class="ui-card p-3 text-xs space-y-1.5"
    >
      <div class="flex items-center justify-between gap-2">
        <span class="font-mono text-sky-700 dark:text-sky-300 truncate">{{ hit.keyword || '-' }}</span>
        <span class="text-gray-500 font-mono shrink-0">{{ formatDate(hit.time) }}</span>
      </div>
      <div class="text-gray-600 dark:text-gray-400 truncate">
        {{ hit.chat_title || hit.chat_id || '-' }}
        <span v-if="hit.sender" class="text-gray-400"> · {{ hit.sender }}</span>
        <span v-if="hit.push_channel" class="text-gray-400"> · {{ hit.push_channel }}</span>
      </div>
      <div class="text-gray-700 dark:text-gray-300 whitespace-pre-wrap break-all line-clamp-3">
        {{ hit.message_text || '-' }}
      </div>
      <template v-if="hitLink(hit)">
        <a
          :href="hitLink(hit)!"
          target="_blank"
          rel="noopener noreferrer"
          class="text-sky-600 dark:text-sky-400 hover:underline"
        >{{ t('taskLogs.hitsOpenMessage') }}</a>
      </template>
    </div>
    <div v-if="canLoadMoreHits" class="pt-1 flex justify-center">
      <button
        type="button"
        class="ui-btn-secondary !px-3 !py-1.5 !text-xs"
        :disabled="hitsLoadingMore"
        @click="emit('load-more')"
      >
        <span v-if="hitsLoadingMore" class="ui-spinner !w-3 !h-3 !border-2 mr-1" />
        {{ t('taskLogs.hitsLoadMore') }}
        <span class="font-mono opacity-70 ml-1">({{ hitRecords.length }}/{{ hitTotal }})</span>
      </button>
    </div>
  </div>

  <div v-else class="space-y-3">
    <div
      v-for="group in hitGroups"
      :key="group.key"
      class="ui-card p-3 space-y-2"
    >
      <div class="flex items-center justify-between gap-2 text-xs">
        <span class="font-medium text-gray-900 dark:text-gray-100 truncate">{{ group.label }}</span>
        <span class="ui-badge ui-badge-neutral !text-[11px] font-mono">{{ group.count }}</span>
      </div>
      <div class="space-y-1.5 border-t border-gray-100 dark:border-gray-800/50 pt-2">
        <div
          v-for="hit in group.items"
          :key="hit.id"
          class="text-[11px] flex items-start justify-between gap-2"
        >
          <div class="min-w-0">
            <span class="font-mono text-sky-700 dark:text-sky-300">{{ hit.keyword || '-' }}</span>
            <span class="text-gray-500 ml-1 truncate">{{ hit.message_text || '' }}</span>
          </div>
          <span class="text-gray-400 font-mono shrink-0">{{ formatDate(hit.time) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
