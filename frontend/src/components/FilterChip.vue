<script setup lang="ts">
/**
 * 可一键清除的筛选条件 chip。
 * 之前各页面各自堆一套 tailwind 配色（sky/orange/violet/teal/amber/rose/gray），
 * 结构完全一致：图标 + 截断文案 + 关闭叉；抽出来统一走 ui-chip-* 色板。
 */
import { X } from 'lucide-vue-next'

defineProps<{
  /** 色板名，对应 style.css 中的 ui-chip-<tone> */
  tone?: 'sky' | 'violet' | 'emerald' | 'orange' | 'amber' | 'rose' | 'teal' | 'gray'
  /** 文案可能较长（账号名 / 任务名 / 搜索词），需要 truncate 与宽度上限 */
  truncate?: boolean
  /** 悬浮提示，一般放「清除筛选」 */
  title?: string
}>()

const emit = defineEmits<{
  (e: 'clear'): void
}>()
</script>

<template>
  <button
    type="button"
    class="inline-flex items-center gap-1 px-2 py-0.5 rounded-sm text-[11px]"
    :class="[`ui-chip-${tone || 'sky'}`, truncate ? 'max-w-[12rem]' : '']"
    :title="title"
    @click="emit('clear')"
  >
    <span :class="truncate ? 'truncate' : ''"><slot /></span>
    <X class="w-3 h-3 shrink-0 opacity-70" />
  </button>
</template>
