<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import Modal from '../Modal.vue'
import { useI18n } from '../../composables/useI18n'
import type { PreviewFlowResponse } from '../../lib/types'
import { AlertCircle, AlertTriangle, CheckCircle2, GitFork, RefreshCw } from 'lucide-vue-next'

const props = defineProps<{
  isOpen: boolean
  previewData?: PreviewFlowResponse | null
  loading?: boolean
  error?: string | null
}>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'refresh'): void
}>()

const { t } = useI18n()
const mermaidContainer = ref<HTMLElement | null>(null)
const renderError = ref<string | null>(null)

watch(
  () => [props.isOpen, props.previewData?.mermaid],
  async ([open, mermaidCode]) => {
    if (!open || !mermaidCode) return
    renderError.value = null
    await nextTick()
    if (mermaidContainer.value) {
      mermaidContainer.value.innerHTML = `<pre class="text-xs p-3 font-mono bg-slate-900 text-slate-100 rounded overflow-x-auto">${escapeHtml(
        String(mermaidCode)
      )}</pre>`
    }
  },
  { immediate: true }
)

function escapeHtml(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;')
}
</script>

<template>
  <Modal
    :isOpen="isOpen"
    :title="t('flow.previewTitle') || '工作流拓扑预览'"
    maxWidthClass="max-w-2xl"
    @close="emit('close')"
  >
    <div class="space-y-4 py-2">
      <!-- Loading State -->
      <div v-if="loading" class="flex items-center justify-center py-8 text-slate-400 gap-2">
        <RefreshCw class="w-5 h-5 animate-spin" />
        <span>{{ t('common.loading') || '正在解析工作流...' }}</span>
      </div>

      <!-- Top-level Error State -->
      <div
        v-else-if="error"
        class="p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-400 flex items-start gap-2"
      >
        <AlertCircle class="w-5 h-5 shrink-0 mt-0.5" />
        <div>
          <div class="font-medium">{{ t('flow.validationFailed') || '流程校验失败' }}</div>
          <div class="mt-1 text-xs opacity-90">{{ error }}</div>
        </div>
      </div>

      <!-- Valid / Invalid Preview Content -->
      <div v-else-if="previewData" class="space-y-3">
        <!-- Summary Banner -->
        <div
          class="flex items-center justify-between p-3 rounded-lg border text-sm"
          :class="
            previewData.valid
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
              : 'bg-red-500/10 border-red-500/30 text-red-400'
          "
        >
          <div class="flex items-center gap-2">
            <CheckCircle2 v-if="previewData.valid" class="w-5 h-5" />
            <AlertCircle v-else class="w-5 h-5" />
            <span class="font-medium">
              {{
                previewData.valid
                  ? t('flow.graphValid') || '工作流图结构合法'
                  : t('flow.graphInvalid') || '工作流图结构存在错误'
              }}
            </span>
          </div>
          <div class="flex items-center gap-3 text-xs opacity-80">
            <span class="flex items-center gap-1">
              <GitFork class="w-3.5 h-3.5" />
              {{ t('flow.nodeCount') || '节点数' }}: {{ previewData.node_count }}
            </span>
            <span v-if="previewData.entry_node_id">
              {{ t('flow.entryNode') || '入口' }}: {{ previewData.entry_node_id }}
            </span>
          </div>
        </div>

        <!-- Issue List (Errors) -->
        <div
          v-if="previewData.errors && previewData.errors.length > 0"
          class="space-y-1.5 p-3 bg-red-950/20 border border-red-900/30 rounded-lg text-xs text-red-300"
        >
          <div class="font-medium text-red-400 flex items-center gap-1.5">
            <AlertCircle class="w-4 h-4" />
            {{ t('flow.errorsTitle') || '拓扑校验错误' }}
          </div>
          <ul class="list-disc list-inside space-y-1 pl-1">
            <li v-for="(err, idx) in previewData.errors" :key="idx">
              <span v-if="err.node_id" class="font-mono font-semibold">[{{ err.node_id }}] </span>
              {{ err.message }}
            </li>
          </ul>
        </div>

        <!-- Issue List (Warnings) -->
        <div
          v-if="previewData.warnings && previewData.warnings.length > 0"
          class="space-y-1.5 p-3 bg-amber-950/20 border border-amber-900/30 rounded-lg text-xs text-amber-300"
        >
          <div class="font-medium text-amber-400 flex items-center gap-1.5">
            <AlertTriangle class="w-4 h-4" />
            {{ t('flow.warningsTitle') || '拓扑校验告警' }}
          </div>
          <ul class="list-disc list-inside space-y-1 pl-1">
            <li v-for="(warn, idx) in previewData.warnings" :key="idx">
              <span v-if="warn.node_id" class="font-mono font-semibold">[{{ warn.node_id }}] </span>
              {{ warn.message }}
            </li>
          </ul>
        </div>

        <!-- Mermaid Diagram Container -->
        <div class="space-y-1.5">
          <div class="text-xs font-medium text-slate-400">
            {{ t('flow.diagramPreview') || 'Mermaid 拓扑表示' }}
          </div>
          <div
            ref="mermaidContainer"
            class="max-h-72 overflow-y-auto rounded-lg border border-slate-700 bg-slate-900/80 p-2"
          ></div>
        </div>
      </div>

      <!-- Footer Buttons -->
      <div class="flex justify-end gap-2 pt-2 border-t border-slate-800">
        <button
          type="button"
          class="px-3 py-1.5 text-xs text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 rounded transition"
          @click="emit('close')"
        >
          {{ t('common.close') || '关闭' }}
        </button>
      </div>
    </div>
  </Modal>
</template>
