<script setup lang="ts">
/**
 * 运行状态徽章：tone 由 lib/run-status.badgeTone 统一推导，
 * 避免 Dashboard / 任务卡 / 日志弹窗各自拼一套 tailwind 配色后与后端状态契约脱节。
 */
import { computed } from 'vue'
import { badgeTone, badgeToneClass, type SignTaskRunStatusLike } from '../lib/run-status'

const props = defineProps<{
  /** 签到运行状态；null 时回落中性色 */
  status?: SignTaskRunStatusLike | null
  /** 调用方按场景补充的字号 / 截断 / 间距等 class */
  extraClass?: string
  /** 运行中显示脉冲圆点 */
  pulse?: boolean
}>()

const toneClass = computed(() => badgeToneClass(badgeTone(props.status)))
</script>

<template>
  <span class="ui-badge border shrink-0" :class="[toneClass, extraClass]">
    <span v-if="pulse" class="ui-pulse-dot !bg-sky-500" />
    <slot />
  </span>
</template>
