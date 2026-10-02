<script setup lang="ts">
import { computed, onUnmounted } from 'vue'
import { Copy, Check } from 'lucide-vue-next'
import { ref } from 'vue'
import {
  buildTaskLogViewModel,
  formatLastTargetMessage,
  normalizeFlowLogLines,
} from '../lib/task-log-format'
import { useI18n } from '../composables/useI18n'
import { useToast } from '../composables/useToast'
import { copyToClipboard } from '../lib/clipboard'

const props = withDefaults(
  defineProps<{
    lines?: string[] | null
    lastTargetMessage?: string | null
    truncated?: boolean
    /** 紧凑模式：更小字号与更少间距 */
    compact?: boolean
    /** 是否显示复制按钮 */
    showCopy?: boolean
    /** 无内容时的回退文案 */
    emptyText?: string
  }>(),
  {
    lines: () => [],
    truncated: false,
    compact: false,
    showCopy: true,
  }
)

const { t } = useI18n()
const toast = useToast()
const copied = ref(false)
/** 复制成功提示延时句柄：卸载时清理，避免操作已卸载组件 */
let copiedTimer: number | undefined

onUnmounted(() => {
  if (copiedTimer !== undefined) {
    window.clearTimeout(copiedTimer)
    copiedTimer = undefined
  }
})

const viewModel = computed(() =>
  buildTaskLogViewModel(props.lines || [], props.lastTargetMessage || undefined)
)

const lastTargetItems = computed(() =>
  formatLastTargetMessage(viewModel.value.lastTargetMessage)
)

const hasContent = computed(
  () =>
    lastTargetItems.value.length > 0 ||
    viewModel.value.blocks.length > 0 ||
    (props.lines && props.lines.length > 0)
)

const copyText = computed(() => {
  const parts: string[] = []
  if (viewModel.value.lastTargetMessage) {
    parts.push(`${t('taskLogs.lastResponse')}\n${viewModel.value.lastTargetMessage}`)
  }
  const normalized = normalizeFlowLogLines(props.lines || [])
  if (normalized.length) {
    parts.push(`${t('taskLogs.logDetail')}\n${normalized.join('\n')}`)
  }
  return parts.join('\n\n').trim()
})

const copyLogs = async () => {
  const text = copyText.value
  if (!text) return
  try {
    const ok = await copyToClipboard(text)
    if (!ok) throw new Error('copy failed')
    copied.value = true
    toast.success(t('logs.copied'))
    // 重入时先清旧定时器：否则上一次复制到点会把本次的对勾提前复位
    if (copiedTimer !== undefined) window.clearTimeout(copiedTimer)
    copiedTimer = window.setTimeout(() => {
      copied.value = false
      copiedTimer = undefined
    }, 1500)
  } catch {
    toast.error(t('logs.copyFailed'))
  }
}

/** 实时/原始行着色 (Warp 终端调色规范) */
function lineTone(text: string): string {
  const s = text.toLowerCase()
  if (/失败|错误|exception|error|failed|traceback/.test(s)) {
    return 'text-rose-400 font-medium'
  }
  if (/成功|完成|success|done|ok\b/.test(s)) {
    return 'text-emerald-400'
  }
  if (/警告|warning|warn|超时|timeout|retry|重试/.test(s)) {
    return 'text-amber-400'
  }
  return 'text-[var(--sp-text-muted)]'
}
</script>

<template>
  <div class="space-y-3 font-sans">
    <!-- 最后返回 -->
    <div v-if="lastTargetItems.length > 0">
      <div class="flex items-center justify-between mb-1.5">
        <div class="ui-section-label">{{ t('taskLogs.lastResponse') }}</div>
      </div>
      <div
        class="p-3 bg-emerald-950/20 border border-emerald-500/25 rounded-[var(--sp-radius)] text-xs whitespace-pre-wrap break-all max-h-40 overflow-y-auto text-emerald-100 font-mono shadow-inner"
        :class="compact ? 'text-[11px]' : ''"
      >
        <div v-for="(item, i) in lastTargetItems" :key="i" class="leading-relaxed">
          {{ item }}
        </div>
      </div>
    </div>

    <!-- 结构化流程 (Warp Stepped Obsidian Terminal) -->
    <div v-if="viewModel.blocks.length > 0 || (lines && lines.length > 0)">
      <div class="flex items-center justify-between mb-1.5">
        <div class="ui-section-label">{{ t('taskLogs.logDetail') }}</div>
        <button
          v-if="showCopy && copyText"
          type="button"
          class="inline-flex items-center gap-1 text-[11px] text-[var(--sp-text-muted)] hover:text-[var(--sp-text)] transition-colors px-2 py-0.5 rounded-[var(--sp-radius-sm)] hover:bg-[var(--sp-surface-muted)] cursor-pointer"
          @click="copyLogs"
        >
          <Check v-if="copied" class="w-3 h-3 text-emerald-500" />
          <Copy v-else class="w-3 h-3" />
          {{ copied ? t('logs.copied') : t('logs.copy') }}
        </button>
      </div>

      <div
        class="ui-terminal space-y-2.5"
        :class="compact ? 'text-[11px] !max-h-48' : ''"
      >
        <template v-if="viewModel.blocks.length > 0">
          <div v-for="(block, bi) in viewModel.blocks" :key="bi">
            <div
              v-if="block.kind === 'line'"
              class="leading-relaxed break-all"
              :class="lineTone(block.text)"
            >
              {{ block.text }}
            </div>

            <div v-else class="ui-terminal-block">
              <div class="flex items-center gap-2 px-3 py-1.5 border-b border-[var(--sp-terminal-border)] bg-[var(--sp-terminal-surface)]">
                <span
                  class="inline-flex items-center justify-center w-4 h-4 text-[10px] font-mono font-semibold rounded-[var(--sp-radius-sm)] bg-sky-500/15 text-sky-300 border border-sky-500/30 shrink-0"
                >
                  {{ block.label }}
                </span>
                <span class="text-[var(--sp-text)] text-[11px] font-medium truncate">{{ block.title }}</span>
              </div>
              <div class="px-3 py-2 space-y-1">
                <div
                  v-for="(item, ii) in block.items"
                  :key="`${bi}-${ii}-${item.slice(0, 64)}`"
                  class="leading-relaxed break-all pl-2 border-l border-[var(--sp-border)]"
                  :class="lineTone(item)"
                >
                  {{ item }}
                </div>
              </div>
            </div>
          </div>
        </template>

        <template v-else>
          <div
            v-for="(line, i) in lines || []"
            :key="`${i}-${String(line).slice(0, 64)}`"
            class="leading-relaxed break-all whitespace-pre-wrap"
            :class="lineTone(String(line))"
          >
            {{ line }}
          </div>
        </template>

        <div v-if="truncated" class="text-[var(--sp-text-muted)] italic pt-1.5 border-t border-[var(--sp-terminal-border)]">
          {{ t('taskLogs.truncated') }}
        </div>
      </div>
    </div>

    <div
      v-else-if="!hasContent"
      class="text-xs text-[var(--sp-text-muted)] py-6 text-center border border-dashed border-[var(--sp-border)] rounded-[var(--sp-radius)]"
    >
      {{ emptyText || t('logs.noDetail') }}
    </div>
  </div>
</template>
