<script setup lang="ts">
withDefaults(
  defineProps<{
    /** 高度 class，如 h-4 / h-10 */
    h?: string
    /** 宽度 class，如 w-full / w-32 */
    w?: string
    /** 圆角 class */
    rounded?: string
    className?: string
  }>(),
  {
    h: 'h-4',
    w: 'w-full',
    rounded: '',
    className: '',
  }
)
</script>

<template>
  <div
    class="ui-skeleton"
    :class="[h, w, rounded, className]"
    aria-hidden="true"
  />
</template>
