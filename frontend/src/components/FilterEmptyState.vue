<script setup lang="ts">
/**
 * 筛选无结果空态：统一「标题 + 提示 + 清除筛选」结构，
 * 供 Tasks / Logs / Accounts 等列表页复用，避免逐页复制。
 * 外层容器类可通过 class 属性覆盖（Vue 自动合并）。
 */
defineProps<{
  title: string
  hint?: string
  /** 清除筛选按钮文案；不传则不渲染按钮 */
  actionText?: string
}>()

const emit = defineEmits<{
  (e: 'action'): void
}>()
</script>

<template>
  <div class="ui-empty">
    <p class="ui-empty-title !text-gray-500 font-normal">{{ title }}</p>
    <p v-if="hint" class="ui-empty-desc mb-3">{{ hint }}</p>
    <button
      v-if="actionText"
      type="button"
      class="ui-btn-secondary !text-xs !px-3 !py-2"
      @click="emit('action')"
    >
      {{ actionText }}
    </button>
    <slot />
  </div>
</template>
