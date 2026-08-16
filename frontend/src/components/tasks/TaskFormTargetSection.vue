<script setup lang="ts">
/**
 * 任务表单：目标会话选择 / 多目标 Tab / 批量勾选。
 */
import { ref } from 'vue'
import { RefreshCw } from 'lucide-vue-next'
import CustomSelect from '../CustomSelect.vue'
import type { ChatInfo } from '../../lib/api'
import { useI18n } from '../../composables/useI18n'

export type TargetChatDraft = {
  id: number
  chatId: number
  chatName: string
  messageThreadId: string
  senderFilter: string
  sourceAccount: string
}

const { t } = useI18n()

/** 会话搜索结果键盘导航：高亮项下标（-1 未定位） */
const activeSearchIndex = ref(-1)

/** 输入框键盘：方向键移动高亮、Enter 选中、Escape 收起 */
const onSearchKeydown = (e: KeyboardEvent) => {
  const results = props.chatSearchResults
  if (!props.chatSearch.trim() || !results.length) {
    if (e.key === 'Escape') {
      activeSearchIndex.value = -1
    }
    return
  }
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    activeSearchIndex.value = Math.min(activeSearchIndex.value + 1, results.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeSearchIndex.value = Math.max(activeSearchIndex.value - 1, 0)
  } else if (e.key === 'Enter' && activeSearchIndex.value >= 0) {
    e.preventDefault()
    emit('select-chat', results[activeSearchIndex.value])
    activeSearchIndex.value = -1
  } else if (e.key === 'Escape') {
    activeSearchIndex.value = -1
  }
}

/** 结果列表打开/关闭时复位高亮 */
const resetSearchActive = () => {
  activeSearchIndex.value = -1
}

const props = defineProps<{
  isEditing: boolean
  createMode: 'shared' | 'split'
  targetChats: TargetChatDraft[]
  activeChatIndex: number
  selectedAccount: string
  selectedAccounts: string[]
  selectedChatId: number
  messageThreadId: string
  senderFilter: string
  showAdvanced: boolean
  availableChats: ChatInfo[]
  chatSearch: string
  chatSearchResults: ChatInfo[]
  chatSearchLoading: boolean
  chatListRefreshing: boolean
  chatListError: string
  bulkSelectedChatIds: number[]
}>()

const emit = defineEmits<{
  (e: 'add-target'): void
  (e: 'remove-target', idx: number): void
  (e: 'update:activeChatIndex', v: number): void
  (e: 'update:createMode', v: 'shared' | 'split'): void
  (e: 'update:selectedAccount', v: string): void
  (e: 'update:selectedChatId', v: number): void
  (e: 'update:selectedChatName', v: string): void
  (e: 'update:messageThreadId', v: string): void
  (e: 'update:senderFilter', v: string): void
  (e: 'update:chatSearch', v: string): void
  (e: 'refresh-chats'): void
  (e: 'select-chat', chat: ChatInfo): void
  (e: 'toggle-bulk-chat', chatId: number): void
  (e: 'apply-bulk-picked'): void
}>()

const onChatIdUpdate = (id: number) => {
  emit('update:selectedChatId', id)
  const found = props.availableChats.find((c) => c.id === id)
  emit('update:selectedChatName', found?.title || found?.username || String(id))
}
</script>

<template>
  <div class="ui-form-section ui-form-section-accent">
    <div class="mb-4 flex items-center justify-between gap-2">
      <div class="ui-form-step">
        <span class="ui-form-step-num">02</span>
        <h4 class="ui-form-step-title text-sky-600 dark:text-sky-400">{{ t('taskForm.targetChat') }}</h4>
      </div>
      <button type="button" class="text-[11px] text-sky-600 dark:text-sky-400 hover:underline font-medium" @click="emit('add-target')">
        + {{ t('taskForm.addTargetChat') }}
      </button>
    </div>
    <div v-if="!isEditing" class="mb-4 space-y-1.5">
      <label class="ui-label">{{ t('taskForm.targetCreateMode') }}</label>
      <CustomSelect
        :model-value="createMode"
        :options="[
          { label: t('tasks.createModeShared'), value: 'shared' },
          { label: t('tasks.createModeSplit'), value: 'split' },
        ]"
        @update:model-value="emit('update:createMode', $event as 'shared' | 'split')"
      />
      <p class="text-[10px] text-gray-500 leading-relaxed">{{ t('tasks.createModeHint') }}</p>
    </div>
    <div v-if="targetChats.length > 1" class="flex flex-wrap gap-2 mb-4">
      <div
        v-for="(chat, idx) in targetChats"
        :key="chat.id"
        class="flex items-center max-w-[16rem] border transition-colors"
        :class="activeChatIndex === idx
          ? 'border-sky-400 bg-sky-50 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300'
          : 'border-gray-200 dark:border-gray-700 text-gray-500'"
      >
        <button
          type="button"
          class="flex-1 min-w-0 px-2.5 py-1 text-[11px] truncate"
          @click="emit('update:activeChatIndex', idx)"
        >
          {{ chat.chatName || chat.chatId || `${t('taskForm.targetChat')} ${idx + 1}` }}
        </button>
        <button
          type="button"
          class="shrink-0 pl-0.5 pr-1.5 py-1 text-[11px] text-gray-400 hover:text-rose-500 rounded-sm"
          :aria-label="t('taskForm.removeTargetChat', { name: chat.chatName || chat.chatId || String(idx + 1) })"
          :title="t('taskForm.removeTargetChat', { name: chat.chatName || chat.chatId || String(idx + 1) })"
          @click="emit('remove-target', idx)"
        >×</button>
      </div>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="space-y-1.5">
        <label class="ui-label">{{ t('taskForm.chatSourceAccount') }}</label>
        <CustomSelect
          :model-value="selectedAccount"
          :options="selectedAccounts.map((a) => ({ label: a, value: a }))"
          @update:model-value="emit('update:selectedAccount', String($event))"
        />
      </div>
      <div class="space-y-1.5">
        <div class="flex items-center justify-between gap-2">
          <label class="ui-label mb-0">{{ t('taskForm.selectFromList') }}</label>
          <button
            type="button"
            class="flex items-center gap-1 text-[10px] text-sky-500 hover:text-sky-700 dark:hover:text-sky-300 font-medium disabled:opacity-50 disabled:cursor-not-allowed"
            :disabled="chatListRefreshing || !selectedAccount"
            @click="emit('refresh-chats')"
          >
            <RefreshCw class="w-3 h-3" :class="chatListRefreshing ? 'animate-spin' : ''" />
            {{ t('taskForm.refreshChats') }}
          </button>
        </div>
        <CustomSelect
          :model-value="selectedChatId"
          :disabled="chatListRefreshing"
          :options="[
            { label: chatListRefreshing ? t('taskForm.loadingChats') : t('taskForm.selectChat'), value: 0 },
            ...availableChats.map((c) => ({ label: c.title || c.username || String(c.id), value: c.id })),
          ]"
          @update:model-value="onChatIdUpdate($event as number)"
        />
        <p v-if="chatListError" class="text-xs text-amber-600 dark:text-amber-400 mt-1">{{ chatListError }}</p>
      </div>
      <div class="space-y-1.5 relative">
        <label class="ui-label">{{ t('taskForm.searchChat') }}</label>
        <div class="relative">
          <input
            :value="chatSearch"
            :placeholder="t('taskForm.searchPlaceholder')"
            class="ui-input"
            role="combobox"
            aria-autocomplete="list"
            :aria-expanded="chatSearch.trim() !== '' && chatSearchResults.length > 0"
            aria-controls="task-form-chat-search-list"
            :aria-activedescendant="activeSearchIndex >= 0 ? `task-form-chat-search-opt-${activeSearchIndex}` : undefined"
            @input="resetSearchActive; emit('update:chatSearch', ($event.target as HTMLInputElement).value)"
            @keydown="onSearchKeydown"
          />
          <div
            v-if="chatSearch.trim()"
            id="task-form-chat-search-list"
            role="listbox"
            class="absolute top-11 left-0 right-0 z-10 max-h-40 overflow-y-auto ui-dropdown shadow-[var(--sp-shadow-md)]"
          >
            <div v-if="chatSearchLoading" class="p-3 text-xs text-gray-400">{{ t('taskForm.searching') }}</div>
            <template v-else>
              <button
                v-for="(chat, idx) in chatSearchResults"
                :key="chat.id"
                :id="`task-form-chat-search-opt-${idx}`"
                type="button"
                role="option"
                :aria-selected="activeSearchIndex === idx"
                class="w-full text-left p-2 border-b border-gray-100 dark:border-gray-800/60 hover:bg-gray-50 dark:hover:bg-gray-800/50 cursor-pointer text-sm"
                :class="activeSearchIndex === idx ? 'bg-gray-50 dark:bg-gray-800/60' : ''"
                @mouseenter="activeSearchIndex = idx"
                @click="activeSearchIndex = -1; emit('select-chat', chat)"
              >
                <span class="block font-medium truncate">{{ chat.title || chat.username || chat.id }}</span>
                <span class="block text-[10px] text-gray-400 font-mono">{{ chat.id }}</span>
              </button>
              <div v-if="!chatSearchResults.length" class="p-3 text-xs text-gray-400">{{ t('taskForm.noResults') }}</div>
            </template>
          </div>
        </div>
      </div>
    </div>
    <div
      v-if="showAdvanced"
      class="mt-3 grid grid-cols-1 md:grid-cols-2 gap-4 pt-3 border-t border-dashed border-gray-200 dark:border-gray-700/60"
    >
      <div class="space-y-1.5">
        <label class="ui-label" for="task-form-thread">{{ t('taskForm.threadId') }}</label>
        <input
          id="task-form-thread"
          :value="messageThreadId"
          :placeholder="t('taskForm.threadIdPlaceholder')"
          class="ui-input"
          @input="emit('update:messageThreadId', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <div class="space-y-1.5">
        <label class="ui-label" for="task-form-sender">{{ t('taskForm.senderFilter') }}</label>
        <input
          id="task-form-sender"
          :value="senderFilter"
          :placeholder="t('taskForm.senderFilterPlaceholder')"
          class="ui-input"
          @input="emit('update:senderFilter', ($event.target as HTMLInputElement).value)"
        />
      </div>
    </div>
    <div v-if="availableChats.length" class="mt-4 border border-dashed border-gray-200 dark:border-gray-700/60 p-3 space-y-2">
      <div class="flex items-center justify-between gap-2">
        <div>
          <div class="text-[11px] font-medium text-gray-700 dark:text-gray-300">{{ t('taskForm.pickFromChatList') }}</div>
          <p class="text-[10px] text-gray-500">{{ t('taskForm.bulkPickHint') }}</p>
        </div>
        <button
          type="button"
          class="ui-btn-secondary !px-2.5 !py-1 !text-[11px]"
          :disabled="!bulkSelectedChatIds.length"
          @click="emit('apply-bulk-picked')"
        >
          {{ t('taskForm.bulkPickChats') }}
          <span v-if="bulkSelectedChatIds.length">({{ bulkSelectedChatIds.length }})</span>
        </button>
      </div>
      <div class="max-h-36 overflow-y-auto space-y-1">
        <label
          v-for="chat in availableChats.slice(0, 40)"
          :key="chat.id"
          class="flex items-center gap-2 px-1.5 py-1 text-xs text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-white/[0.03] cursor-pointer rounded-sm"
        >
          <input
            type="checkbox"
            class="ui-checkbox"
            :checked="bulkSelectedChatIds.includes(chat.id)"
            @change="emit('toggle-bulk-chat', chat.id)"
          />
          <span class="truncate flex-1">{{ chat.title || chat.username || chat.id }}</span>
          <span class="font-mono text-[10px] text-gray-400 shrink-0">{{ chat.id }}</span>
        </label>
        <p
          v-if="availableChats.length > 40"
          class="px-1.5 py-1 text-[10px] text-gray-400"
        >
          {{ t('taskForm.bulkPickTruncated', { shown: 40, total: availableChats.length }) }}
        </p>
      </div>
    </div>
  </div>
</template>
