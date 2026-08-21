<script setup lang="ts">
/**
 * 任务表单：关键词监听配置区块（仅 listen 模式展示由父级控制）。
 */
import CustomSelect from '../CustomSelect.vue'
import { useI18n } from '../../composables/useI18n'

const { t } = useI18n()

defineProps<{
  keywords: string
  matchMode: string
  pushChannel: string
  ignoreSelf: boolean
  timeWindowEnabled: boolean
  activeTimeStart: string
  activeTimeEnd: string
  forwardChatId: string
  forwardThreadId: string
  barkUrl: string
  serverChanKey: string
  customUrl: string
}>()

const emit = defineEmits<{
  (e: 'update:keywords', v: string): void
  (e: 'update:matchMode', v: string): void
  (e: 'update:pushChannel', v: string): void
  (e: 'update:ignoreSelf', v: boolean): void
  (e: 'update:timeWindowEnabled', v: boolean): void
  (e: 'update:activeTimeStart', v: string): void
  (e: 'update:activeTimeEnd', v: string): void
  (e: 'update:forwardChatId', v: string): void
  (e: 'update:forwardThreadId', v: string): void
  (e: 'update:barkUrl', v: string): void
  (e: 'update:serverChanKey', v: string): void
  (e: 'update:customUrl', v: string): void
}>()
</script>

<template>
  <div class="ui-form-section !bg-[var(--sp-bg-elevated)]">
    <div class="ui-form-step mb-4">
      <span class="ui-form-step-num">03</span>
      <h4 class="ui-form-step-title text-emerald-600 dark:text-emerald-400">{{ t('taskForm.keywordListener') }}</h4>
    </div>
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div class="md:col-span-2 space-y-1.5">
        <label class="ui-label" for="task-form-keywords">{{ t('taskForm.keywords') }}</label>
        <textarea
          id="task-form-keywords"
          :value="keywords"
          rows="3"
          :placeholder="t('taskForm.keywordsPlaceholder')"
          class="ui-input !h-auto py-2.5"
          @input="emit('update:keywords', ($event.target as HTMLTextAreaElement).value)"
        />
      </div>
      <div class="space-y-1.5">
        <label class="ui-label">{{ t('taskForm.matchMode') }}</label>
        <CustomSelect
          :model-value="matchMode"
          :aria-label="t('taskForm.matchMode')"
          :options="[
            { label: t('taskForm.matchContains'), value: 'contains' },
            { label: t('taskForm.matchExact'), value: 'exact' },
            { label: t('taskForm.matchRegex'), value: 'regex' },
          ]"
          @update:model-value="emit('update:matchMode', String($event))"
        />
      </div>
      <div class="space-y-1.5">
        <label class="ui-label">{{ t('taskForm.afterMatch') }}</label>
        <CustomSelect
          :model-value="pushChannel"
          :aria-label="t('taskForm.afterMatch')"
          :options="[
            { label: t('taskForm.continueActions'), value: 'continue' },
            { label: t('taskForm.telegramNotify'), value: 'telegram' },
            { label: t('taskForm.forwardToChat'), value: 'forward' },
            { label: t('taskForm.barkPush'), value: 'bark' },
            { label: t('tasks.pushServerChan'), value: 'server_chan' },
            { label: t('taskForm.customWebhook'), value: 'custom' },
          ]"
          @update:model-value="emit('update:pushChannel', String($event))"
        />
      </div>
      <div class="md:col-span-2 flex flex-col gap-1">
        <label class="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400 cursor-pointer select-none">
          <input
            type="checkbox"
            class="ui-checkbox"
            :checked="ignoreSelf"
            @change="emit('update:ignoreSelf', ($event.target as HTMLInputElement).checked)"
          />
          {{ t('taskForm.ignoreSelfMessages') }}
        </label>
        <p class="text-[10px] text-gray-500 leading-relaxed pl-6">{{ t('taskForm.ignoreSelfHint') }}</p>
      </div>
      <div class="md:col-span-2 space-y-2">
        <label class="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400 cursor-pointer select-none">
          <input
            type="checkbox"
            class="ui-checkbox"
            :checked="timeWindowEnabled"
            @change="emit('update:timeWindowEnabled', ($event.target as HTMLInputElement).checked)"
          />
          {{ t('taskForm.timeWindowEnabled') }}
        </label>
        <div v-if="timeWindowEnabled" class="grid grid-cols-2 gap-3 pl-6">
          <div class="space-y-1">
            <label class="ui-label" for="task-form-time-start">{{ t('taskForm.timeWindowStart') }}</label>
            <input
              id="task-form-time-start"
              type="time"
              class="ui-input"
              :value="activeTimeStart"
              @input="emit('update:activeTimeStart', ($event.target as HTMLInputElement).value)"
            />
          </div>
          <div class="space-y-1">
            <label class="ui-label" for="task-form-time-end">{{ t('taskForm.timeWindowEnd') }}</label>
            <input
              id="task-form-time-end"
              type="time"
              class="ui-input"
              :value="activeTimeEnd"
              @input="emit('update:activeTimeEnd', ($event.target as HTMLInputElement).value)"
            />
          </div>
        </div>
        <p class="text-[10px] text-gray-500 leading-relaxed pl-6">{{ t('taskForm.timeWindowHint') }}</p>
      </div>
      <template v-if="pushChannel === 'forward'">
        <div class="space-y-1.5">
          <label class="ui-label" for="task-form-forward-chat">{{ t('taskForm.forwardChatId') }}</label>
          <input
            id="task-form-forward-chat"
            :value="forwardChatId"
            placeholder="-10012345678"
            class="ui-input"
            @input="emit('update:forwardChatId', ($event.target as HTMLInputElement).value)"
          />
        </div>
        <div class="space-y-1.5">
          <label class="ui-label" for="task-form-forward-thread">{{ t('taskForm.forwardThreadId') }}</label>
          <input
            id="task-form-forward-thread"
            :value="forwardThreadId"
            :placeholder="t('taskForm.forwardThreadIdPlaceholder')"
            class="ui-input"
            @input="emit('update:forwardThreadId', ($event.target as HTMLInputElement).value)"
          />
        </div>
      </template>
      <div v-if="pushChannel === 'bark'" class="md:col-span-2 space-y-1.5">
        <label class="ui-label" for="task-form-bark-url">{{ t('taskForm.barkUrl') }}</label>
        <input
          id="task-form-bark-url"
          :value="barkUrl"
          placeholder="https://api.day.app/xxx"
          class="ui-input"
          @input="emit('update:barkUrl', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <div v-if="pushChannel === 'server_chan'" class="md:col-span-2 space-y-1.5">
        <label class="ui-label" for="task-form-server-chan">{{ t('tasks.serverChanKey') }}</label>
        <input
          id="task-form-server-chan"
          :value="serverChanKey"
          placeholder="SCTxxxx"
          class="ui-input"
          @input="emit('update:serverChanKey', ($event.target as HTMLInputElement).value)"
        />
      </div>
      <div v-if="pushChannel === 'custom'" class="md:col-span-2 space-y-1.5">
        <label class="ui-label" for="task-form-webhook">{{ t('taskForm.webhookUrl') }}</label>
        <input
          id="task-form-webhook"
          :value="customUrl"
          :placeholder="t('taskForm.webhookPlaceholder')"
          class="ui-input"
          @input="emit('update:customUrl', ($event.target as HTMLInputElement).value)"
        />
      </div>
    </div>
  </div>
</template>
