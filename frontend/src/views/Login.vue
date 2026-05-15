<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Github, Globe, Moon, Sun } from 'lucide-vue-next'
import { login } from '../lib/api'
import { useAuthStore } from '../stores/auth'
import { useI18n } from '../composables/useI18n'
import { useTheme } from '../composables/useTheme'

const router = useRouter()
const authStore = useAuthStore()
const { locale, toggleLanguage, t } = useI18n()
const { isDark, toggleTheme } = useTheme()

const username = ref('')
const password = ref('')
const totpCode = ref('')
const showTotp = ref(true)
const errorMsg = ref('')
const loading = ref(false)

const handleLogin = async () => {
  if (!username.value || !password.value) return
  try {
    loading.value = true
    errorMsg.value = ''
    const payload: { username: string; password: string; totp_code?: string } = {
      username: username.value,
      password: password.value,
    }
    if (totpCode.value.trim()) {
      payload.totp_code = totpCode.value.trim()
    }
    const res = await login(payload)
    if (res.access_token) {
      authStore.setToken(res.access_token)
      router.push('/dashboard')
    }
  } catch (e: any) {
    const detail = e.message || ''
    if (detail === 'TOTP_REQUIRED_OR_INVALID' || detail.includes('TOTP')) {
      showTotp.value = true
      if (totpCode.value) {
        errorMsg.value = t('login.totpInvalid')
      } else {
        errorMsg.value = t('login.totpRequired')
      }
      totpCode.value = ''
    } else {
      errorMsg.value = detail || t('login.failed')
    }
  } finally {
    loading.value = false
  }
}

const openGithub = () => {
  window.open('https://github.com/akasls/TG-SignPulse', '_blank')
}
</script>

<template>
  <div class="min-h-screen bg-gray-50 dark:bg-gray-950 flex flex-col items-center justify-center font-sans">
    <div class="w-full max-w-sm px-8 py-10 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60">
      <div class="mb-8 text-center">
        <div class="w-12 h-12 bg-gray-900 dark:bg-gray-100 mx-auto flex items-center justify-center text-white dark:text-gray-950 font-bold text-lg mb-4">TG</div>
        <h1 class="text-xl font-medium text-gray-900 dark:text-gray-100 tracking-wide">SIGNPULSE</h1>
      </div>

      <form @submit.prevent="handleLogin" class="space-y-4">
        <div>
          <label class="block text-xs text-gray-500 mb-1.5">{{ t('login.username') }}</label>
          <input 
            v-model="username" 
            type="text" 
            required
            autocomplete="username"
            :placeholder="t('login.usernamePlaceholder')"
            class="w-full bg-white dark:bg-gray-950 border border-gray-300 dark:border-gray-800/60 text-gray-900 dark:text-gray-200 px-3 py-2 outline-none focus:border-gray-500 dark:focus:border-gray-600 transition-colors"
          >
        </div>
        <div>
          <label class="block text-xs text-gray-500 mb-1.5">{{ t('login.password') }}</label>
          <input 
            v-model="password" 
            type="password" 
            required
            autocomplete="current-password"
            :placeholder="t('login.passwordPlaceholder')"
            class="w-full bg-white dark:bg-gray-950 border border-gray-300 dark:border-gray-800/60 text-gray-900 dark:text-gray-200 px-3 py-2 outline-none focus:border-gray-500 dark:focus:border-gray-600 transition-colors"
          >
        </div>

        <div v-if="showTotp">
          <label class="block text-xs text-gray-500 mb-1.5">{{ t('login.totpCode') }}</label>
          <input 
            v-model="totpCode" 
            type="text" 
            inputmode="numeric"
            autocomplete="one-time-code"
            maxlength="6"
            :placeholder="t('login.totpPlaceholder')"
            class="w-full bg-white dark:bg-gray-950 border border-gray-300 dark:border-gray-800/60 text-gray-900 dark:text-gray-200 px-3 py-2 outline-none focus:border-gray-500 dark:focus:border-gray-600 transition-colors tracking-widest text-center font-mono"
          >
        </div>

        <div v-if="errorMsg" class="text-xs text-rose-600 dark:text-rose-500 bg-rose-50 dark:bg-rose-500/10 p-2 border border-rose-200 dark:border-transparent">
          {{ errorMsg }}
        </div>

        <button 
          type="submit" 
          :disabled="loading"
          class="w-full mt-4 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-950 py-2 font-medium hover:bg-gray-800 dark:hover:bg-white transition-colors disabled:opacity-50"
        >
          {{ loading ? t('login.authenticating') : t('login.signIn') }}
        </button>
      </form>

      <!-- Footer icons -->
      <div class="flex items-center justify-center gap-3 mt-6 pt-4 border-t border-gray-200 dark:border-gray-800/60">
        <button @click="openGithub" class="w-8 h-8 flex items-center justify-center text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 transition-colors rounded" title="GitHub">
          <Github class="w-4 h-4" />
        </button>
        <button @click="toggleLanguage" class="w-8 h-8 flex items-center justify-center text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 transition-colors rounded" :title="locale === 'zh' ? 'English' : '中文'">
          <Globe class="w-4 h-4" />
        </button>
        <button @click="toggleTheme" class="w-8 h-8 flex items-center justify-center text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 transition-colors rounded" :title="isDark ? t('common.lightMode') : t('common.darkMode')">
          <Moon v-if="!isDark" class="w-4 h-4" />
          <Sun v-else class="w-4 h-4" />
        </button>
      </div>
    </div>
  </div>
</template>
