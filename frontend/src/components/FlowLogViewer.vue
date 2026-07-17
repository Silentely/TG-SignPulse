<script setup lang="ts">
import { computed } from 'vue'
import { Copy, Check } from 'lucide-vue-next'
import { ref } from 'vue'
import {
  buildTaskLogViewModel,
  formatLastTargetMessage,
  normalizeFlowLogLines,
} from '../lib/task-log-format'
import { useI18n } from '../composables/useI18n'
import { useToast } from '../composables/useToast'

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
    await navigator.clipboard.writeText(text)
    copied.value = true
    toast.success(t('logs.copied'))
    setTimeout(() => {
      copied.value = false
    }, 1500)
  } catch {
    toast.error(t('logs.copyFailed'))
  }
}

/** 实时/原始行着色 */
function lineTone(text: string): string {
  const s = text.toLowerCase()
  if (/失败|错误|exception|error|failed|traceback/.test(s)) {
    return 'text-rose-400'
  }
  if (/成功|完成|success|done|ok\b/.test(s)) {
    return 'text-emerald-400'
  }
  if (/警告|warning|warn|超时|timeout|retry|重试/.test(s)) {
    return 'text-amber-400'
  }
  return 'text-gray-300'
}
</script>

<template>
  <div class="space-y-3">
    <!-- 最后返回 -->
    <div v-if="lastTargetItems.length > 0">
      <div class="flex items-center justify-between mb-1.5">
        <div class="ui-section-label">{{ t('taskLogs.lastResponse') }}</div>
      </div>
      <div
        class="p-2.5 bg-emerald-50/80 dark:bg-emerald-950/30 border border-emerald-200/70 dark:border-emerald-900/40 text-xs whitespace-pre-wrap break-all max-h-40 overflow-y-auto text-gray-800 dark:text-gray-200"
        :class="compact ? 'text-[11px]' : ''"
      >
        <div v-for="(item, i) in lastTargetItems" :key="i" class="leading-relaxed">
          {{ item }}
        </div>
      </div>
    </div>

    <!-- 结构化流程 -->
    <div v-if="viewModel.blocks.length > 0 || (lines && lines.length > 0)">
      <div class="flex items-center justify-between mb-1.5">
        <div class="ui-section-label">{{ t('taskLogs.logDetail') }}</div>
        <button
          v-if="showCopy && copyText"
          type="button"
          class="inline-flex items-center gap-1 text-[11px] text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 transition-colors px-1.5 py-0.5 rounded-sm hover:bg-gray-100 dark:hover:bg-white/[0.05]"
          @click="copyLogs"
        >
          <Check v-if="copied" class="w-3 h-3 text-emerald-500" />
          <Copy v-else class="w-3 h-3" />
          {{ copied ? t('logs.copied') : t('logs.copy') }}
        </button>
      </div>

      <div
        class="ui-terminal space-y-2"
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
              <div class="flex items-center gap-2 px-2.5 py-1.5 border-b border-gray-800/80 bg-gray-900/90">
                <span
                  class="inline-flex items-center justify-center w-4 h-4 text-[10px] font-semibold rounded-sm bg-sky-500/15 text-sky-300 border border-sky-500/25"
                >
                  {{ block.label }}
                </span>
                <span class="text-gray-200 text-[11px] font-medium truncate">{{ block.title }}</span>
              </div>
              <div class="px-2.5 py-1.5 space-y-0.5">
                <div
                  v-for="(item, ii) in block.items"
                  :key="ii"
                  class="leading-relaxed break-all pl-1.5 border-l border-gray-700/80"
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
            :key="i"
            class="leading-relaxed break-all whitespace-pre-wrap"
            :class="lineTone(String(line))"
          >
            {{ line }}
          </div>
        </template>

        <div v-if="truncated" class="text-gray-500 italic pt-1 border-t border-gray-800/60">
          {{ t('taskLogs.truncated') }}
        </div>
      </div>
    </div>

    <div
      v-else-if="!hasContent"
      class="text-xs text-gray-500 py-4 text-center border border-dashed border-gray-200 dark:border-gray-800/60"
    >
      {{ emptyText || t('logs.noDetail') }}
    </div>
  </div>
</template>
