<script setup lang="ts">
import { computed, watchEffect } from 'vue'
import { useRouter } from 'vue-router'
import { FileQuestion, ArrowLeft, RotateCcw, Github, Globe, Moon, Sun } from 'lucide-vue-next'
import { useAuthStore } from '../stores/auth'
import { useI18n } from '../composables/useI18n'
import { useTheme } from '../composables/useTheme'

const router = useRouter()
const authStore = useAuthStore()
const { locale, toggleLanguage, t } = useI18n()
const { isDark, toggleTheme } = useTheme()

watchEffect(() => {
  document.title = `404 ${t('notFound.title')} - TG-SignPulse`
})

const isAuthed = computed(() => {
  return !!authStore.token && !authStore.isTokenExpired()
})

const hasHistory = typeof window !== 'undefined' && window.history.length > 1

const handleRedirect = () => {
  if (isAuthed.value) {
    router.push('/dashboard')
  } else {
    router.push('/login')
  }
}

const handleGoBack = () => {
  if (hasHistory) {
    router.back()
  } else {
    handleRedirect()
  }
}

const openGithub = () => {
  window.open('https://github.com/Silentely/TG-SignPulse', '_blank')
}
</script>

<template>
  <main class="min-h-screen flex flex-col items-center justify-center font-sans px-4 py-10" role="main">
    <div class="w-full max-w-sm ui-card shadow-[var(--sp-shadow-md)] px-8 py-10 text-center">
      <div class="w-14 h-14 bg-[var(--sp-surface-muted)] border border-[var(--sp-border)] mx-auto flex items-center justify-center text-[var(--sp-text-muted)] mb-6 rounded-full">
        <FileQuestion class="w-7 h-7 stroke-[1.5]" />
      </div>

      <div class="text-5xl font-mono font-bold text-[var(--sp-text)] tracking-wider mb-2">404</div>
      <h1 class="text-base font-medium text-[var(--sp-text)] mb-2">{{ t('notFound.title') }}</h1>
      <p class="text-xs text-[var(--sp-text-muted)] mb-8 leading-relaxed">{{ t('notFound.desc') }}</p>

      <div class="space-y-2.5">
        <button
          type="button"
          @click="handleRedirect"
          class="ui-btn-primary w-full py-2.5 flex items-center justify-center gap-2 cursor-pointer"
        >
          <ArrowLeft class="w-4 h-4" />
          <span>{{ isAuthed ? t('notFound.backHome') : t('notFound.goToLogin') }}</span>
        </button>

        <button
          v-if="hasHistory"
          type="button"
          @click="handleGoBack"
          class="ui-btn-secondary w-full py-2 flex items-center justify-center gap-2 text-xs cursor-pointer"
        >
          <RotateCcw class="w-3.5 h-3.5" />
          <span>{{ t('notFound.goBack') }}</span>
        </button>
      </div>

      <!-- Footer icons -->
      <div class="flex items-center justify-center gap-2 mt-7 pt-5 border-t border-[var(--sp-border)]">
        <button
          type="button"
          class="ui-icon-btn cursor-pointer"
          :title="t('common.github')"
          :aria-label="t('common.github')"
          @click="openGithub"
        >
          <Github class="w-4 h-4" />
        </button>
        <button
          type="button"
          class="ui-icon-btn cursor-pointer"
          :title="locale === 'zh' ? t('language.switchToEn') : t('language.switchToZh')"
          :aria-label="t('common.changeLanguage')"
          @click="toggleLanguage"
        >
          <Globe class="w-4 h-4" />
        </button>
        <button
          type="button"
          class="ui-icon-btn cursor-pointer"
          :title="isDark ? t('common.lightMode') : t('common.darkMode')"
          :aria-label="isDark ? t('common.lightMode') : t('common.darkMode')"
          @click="toggleTheme($event)"
        >
          <Moon v-if="!isDark" class="w-4 h-4" />
          <Sun v-else class="w-4 h-4" />
        </button>
      </div>
    </div>
  </main>
</template>
