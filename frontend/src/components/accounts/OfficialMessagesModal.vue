<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RefreshCw, ShieldCheck } from 'lucide-vue-next'
import Modal from '../Modal.vue'
import { listAccountOfficialMessages, type OfficialMessageInfo } from '../../lib/api'
import { useI18n } from '../../composables/useI18n'

const props = defineProps<{
  isOpen: boolean
  accountName: string
}>()

const emit = defineEmits<{
  close: []
}>()

const { t } = useI18n()
const loading = ref(false)
const error = ref('')
const messages = ref<OfficialMessageInfo[]>([])

const title = computed(() => `${t('accounts.officialMessages')} · ${props.accountName || '-'}`)

const formatTime = (value?: string | null) => {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

const loadMessages = async () => {
  const token = localStorage.getItem('tg-signer-token') || ''
  if (!token || !props.accountName) return

  loading.value = true
  error.value = ''
  try {
    const res = await listAccountOfficialMessages(token, props.accountName, 20)
    messages.value = res.messages || []
  } catch (e: any) {
    error.value = e.message || t('accounts.officialMessagesFailed')
  } finally {
    loading.value = false
  }
}

watch(
  () => props.isOpen,
  (open) => {
    if (open) loadMessages()
  }
)
</script>

<template>
  <Modal :isOpen="isOpen" :title="title" @close="emit('close')">
    <div class="space-y-4">
      <div class="flex items-start justify-between gap-3 p-3 bg-sky-50 dark:bg-sky-500/10 border border-sky-100 dark:border-sky-800/40">
        <div class="flex items-start gap-2 min-w-0">
          <ShieldCheck class="w-4 h-4 text-sky-500 mt-0.5 shrink-0" />
          <div class="text-xs text-sky-800 dark:text-sky-300 leading-relaxed">
            <div class="font-medium">{{ t('accounts.officialMessagesHintTitle') }}</div>
            <div class="mt-1 opacity-90">{{ t('accounts.officialMessagesHint') }}</div>
          </div>
        </div>
        <button
          type="button"
          class="ui-btn-secondary !px-2 !py-1 !text-xs shrink-0"
          :disabled="loading"
          @click="loadMessages"
        >
          <RefreshCw class="w-3 h-3" :class="loading ? 'animate-spin' : ''" />
          {{ t('accounts.refresh') }}
        </button>
      </div>

      <div v-if="error" class="ui-alert-error">
        {{ error }}
      </div>

      <div v-if="loading && !messages.length" class="ui-page-loading !py-10">
        <div class="ui-spinner" />
      </div>

      <div v-else-if="!messages.length" class="ui-empty !py-10">
        <p class="ui-empty-desc">{{ t('accounts.noOfficialMessages') }}</p>
      </div>

      <div v-else class="max-h-[60vh] overflow-auto space-y-3 pr-1">
        <div
          v-for="message in messages"
          :key="message.id || `${message.date}-${message.text}`"
          class="ui-card p-3"
        >
          <div class="flex items-center justify-between gap-3 mb-2">
            <span class="text-xs font-medium text-gray-700 dark:text-gray-200">Telegram · 777000</span>
            <span class="text-[10px] text-gray-500 shrink-0">{{ formatTime(message.date) }}</span>
          </div>
          <pre class="whitespace-pre-wrap break-words text-sm leading-relaxed text-gray-800 dark:text-gray-200 font-sans">{{ message.text || t('accounts.emptyMessage') }}</pre>
        </div>
      </div>
    </div>
  </Modal>
</template>
