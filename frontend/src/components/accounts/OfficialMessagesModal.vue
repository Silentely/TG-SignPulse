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
      <div class="flex items-start justify-between gap-3 p-3 bg-blue-50 dark:bg-blue-500/10 border border-blue-100 dark:border-blue-800/40">
        <div class="flex items-start gap-2 min-w-0">
          <ShieldCheck class="w-4 h-4 text-blue-500 mt-0.5 shrink-0" />
          <div class="text-xs text-blue-700 dark:text-blue-300 leading-relaxed">
            <div class="font-medium">{{ t('accounts.officialMessagesHintTitle') }}</div>
            <div class="mt-1">{{ t('accounts.officialMessagesHint') }}</div>
          </div>
        </div>
        <button
          @click="loadMessages"
          :disabled="loading"
          class="inline-flex items-center gap-1 px-2 py-1 text-xs text-blue-600 dark:text-blue-300 bg-white dark:bg-gray-900 border border-blue-100 dark:border-blue-800/40 hover:bg-blue-50 dark:hover:bg-blue-500/10 disabled:opacity-50"
        >
          <RefreshCw class="w-3 h-3" :class="loading ? 'animate-spin' : ''" />
          {{ t('accounts.refresh') }}
        </button>
      </div>

      <div v-if="error" class="p-3 text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-500/10 border border-red-100 dark:border-red-800/40">
        {{ error }}
      </div>

      <div v-if="loading && !messages.length" class="py-10 text-center text-sm text-gray-500">
        {{ t('accounts.loadingOfficialMessages') }}
      </div>

      <div v-else-if="!messages.length" class="py-10 text-center text-sm text-gray-500">
        {{ t('accounts.noOfficialMessages') }}
      </div>

      <div v-else class="max-h-[60vh] overflow-auto space-y-3 pr-1">
        <div
          v-for="message in messages"
          :key="message.id || `${message.date}-${message.text}`"
          class="p-3 bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-gray-800/60"
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
