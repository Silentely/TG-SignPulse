<script setup lang="ts">
/**
 * 设置字段说明文案（轻量复用，避免 Settings 页重复样式）。
 */
defineProps<{ text: string }>()
</script>

<template>
  <p class="text-[10px] text-gray-400 leading-relaxed">{{ text }}</p>
</template>
