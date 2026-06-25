<script setup lang="ts">
import { Globe } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'

const { locale } = useI18n()

// 切换语言并在 localStorage 中持久化
const toggleLanguage = () => {
  const newLocale = locale.value === 'zh-CN' ? 'en-US' : 'zh-CN'
  locale.value = newLocale
  localStorage.setItem('tg-signer-locale', newLocale === 'zh-CN' ? 'zh' : 'en')
}
</script>

<template>
  <button
    @click="toggleLanguage"
    class="w-8 h-8 flex items-center justify-center text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 hover:bg-gray-200 dark:hover:bg-gray-900 transition-colors rounded"
    :title="locale === 'zh-CN' ? 'English' : '中文'"
  >
    <Globe class="w-4 h-4" />
  </button>
</template>
