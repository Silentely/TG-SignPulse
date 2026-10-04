<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'

const props = withDefaults(
  defineProps<{
    lines: string[]
    itemHeight?: number
    containerHeight?: number
    buffer?: number
    autoScroll?: boolean
    lineTone?: (line: string) => string
    emptyText?: string
  }>(),
  {
    lines: () => [],
    itemHeight: 24,
    containerHeight: 400,
    buffer: 5,
    autoScroll: true,
    emptyText: '',
  }
)

const containerRef = ref<HTMLElement | null>(null)
const scrollTop = ref(0)
const isAtBottom = ref(true)

const totalCount = computed(() => props.lines.length)

const startIndex = computed(() => {
  const raw = Math.floor(scrollTop.value / props.itemHeight) - props.buffer
  return Math.max(0, Math.min(totalCount.value, raw))
})

const endIndex = computed(() => {
  const visibleCount = Math.ceil(props.containerHeight / props.itemHeight)
  const raw = Math.floor(scrollTop.value / props.itemHeight) + visibleCount + props.buffer
  return Math.min(totalCount.value, Math.max(startIndex.value, raw))
})

const visibleItems = computed(() => {
  const start = startIndex.value
  const end = endIndex.value
  const result: { index: number; text: string }[] = []
  for (let i = start; i < end; i++) {
    result.push({
      index: i,
      text: props.lines[i] ?? '',
    })
  }
  return result
})

const topSpacerHeight = computed(() => startIndex.value * props.itemHeight)
const bottomSpacerHeight = computed(() => Math.max(0, (totalCount.value - endIndex.value) * props.itemHeight))

const handleScroll = (e: Event) => {
  const target = e.target as HTMLElement
  if (!target) return
  scrollTop.value = target.scrollTop
  const threshold = 16
  isAtBottom.value = target.scrollHeight - target.scrollTop - target.clientHeight <= threshold
}

const scrollToBottom = () => {
  if (containerRef.value) {
    containerRef.value.scrollTop = containerRef.value.scrollHeight
    scrollTop.value = containerRef.value.scrollTop
    isAtBottom.value = true
  }
}

watch(
  () => props.lines.length,
  (_newLen, oldLen) => {
    if (props.autoScroll && (isAtBottom.value || !oldLen)) {
      nextTick(() => {
        scrollToBottom()
      })
    }
  }
)

function defaultLineTone(text: string): string {
  const s = String(text || '').toLowerCase()
  if (/失败|错误|exception|error|failed|traceback/.test(s)) return 'text-rose-400 font-medium'
  if (/成功|完成|success|done|ok\b/.test(s)) return 'text-emerald-400'
  if (/警告|warning|warn|超时|timeout|retry|重试/.test(s)) return 'text-amber-400'
  return 'text-green-400'
}

const resolveLineTone = (text: string) => {
  if (props.lineTone) return props.lineTone(text)
  return defaultLineTone(text)
}

defineExpose({
  containerRef,
  scrollToBottom,
  scrollTop,
  startIndex,
  endIndex,
})
</script>

<template>
  <div
    ref="containerRef"
    class="virtual-log-viewer ui-terminal whitespace-pre select-text overflow-x-auto overflow-y-auto"
    :style="{ height: `${containerHeight}px`, maxHeight: `${containerHeight}px` }"
    tabindex="0"
    role="region"
    aria-label="Log viewer"
    @scroll="handleScroll"
  >
    <div
      v-if="topSpacerHeight > 0"
      :style="{ height: `${topSpacerHeight}px` }"
      class="virtual-spacer-top pointer-events-none"
      aria-hidden="true"
    />

    <div
      v-for="item in visibleItems"
      :key="item.index"
      class="log-line leading-relaxed"
      :class="resolveLineTone(item.text)"
      :style="{ height: `${itemHeight}px`, minHeight: `${itemHeight}px`, lineHeight: `${itemHeight}px` }"
      :data-index="item.index"
    >
      {{ item.text }}
    </div>

    <div
      v-if="bottomSpacerHeight > 0"
      :style="{ height: `${bottomSpacerHeight}px` }"
      class="virtual-spacer-bottom pointer-events-none"
      aria-hidden="true"
    />

    <div
      v-if="lines.length === 0 && emptyText"
      class="text-[var(--sp-text-muted)] italic py-2 text-center"
    >
      {{ emptyText }}
    </div>
  </div>
</template>
