<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { Github, Globe, Moon, Sun, Eye, EyeOff } from 'lucide-vue-next'
import { login } from '../lib/api'
import { useAuthStore } from '../stores/auth'
import { useI18n } from '../composables/useI18n'
import { useTheme } from '../composables/useTheme'
import { getErrorMessage } from '../lib/types'

const router = useRouter()
const authStore = useAuthStore()
const { locale, toggleLanguage, t } = useI18n()
const { isDark, toggleTheme } = useTheme()

const username = ref('')
const password = ref('')
const totpCode = ref('')
const showTotp = ref(true)
const showPassword = ref(false)
const errorMsg = ref('')
const loading = ref(false)
const totpInput = ref<HTMLInputElement | null>(null)

const mapLoginError = (detail: string): string => {
  const code = detail.trim()
  const key = `login.errors.${code}`
  const translated = t(key)
  if (translated !== key) return translated
  // 常见 detail 子串
  if (code.includes('TOTP') || code === 'TOTP_REQUIRED_OR_INVALID') {
    return totpCode.value ? t('login.totpInvalid') : t('login.totpRequired')
  }
  if (code.includes('INVALID_USERNAME') || code.includes('password')) {
    return t('login.errors.INVALID_USERNAME_OR_PASSWORD')
  }
  if (code.includes('RATE_LIMIT')) {
    return t('login.errors.RATE_LIMITED')
  }
  return detail || t('login.failed')
}

const handleLogin = async () => {
  if (!username.value.trim() || !password.value) return
  try {
    loading.value = true
    errorMsg.value = ''
    const payload: { username: string; password: string; totp_code?: string } = {
      username: username.value.trim(),
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
  } catch (e: unknown) {
    const detail = getErrorMessage(e)
    if (detail === 'TOTP_REQUIRED_OR_INVALID' || detail.includes('TOTP')) {
      showTotp.value = true
      errorMsg.value = totpCode.value ? t('login.totpInvalid') : t('login.totpRequired')
      totpCode.value = ''
      await nextTick()
      totpInput.value?.focus()
    } else {
      errorMsg.value = mapLoginError(detail)
    }
  } finally {
    loading.value = false
  }
}

const openGithub = () => {
  window.open('https://github.com/Silentely/TG-SignPulse', '_blank')
}
</script>

<template>
  <div class="min-h-screen bg-gray-50 dark:bg-gray-950 flex flex-col items-center justify-center font-sans px-4">
    <div class="w-full max-w-sm px-8 py-10 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 shadow-sm">
      <div class="mb-8 text-center">
        <div class="w-12 h-12 bg-gray-900 dark:bg-gray-100 mx-auto flex items-center justify-center text-white dark:text-gray-950 font-bold text-lg mb-4">TG</div>
        <h1 class="text-xl font-medium text-gray-900 dark:text-gray-100 tracking-wide">SIGNPULSE</h1>
        <p class="text-xs text-gray-500 mt-2">{{ t('login.subtitle') }}</p>
      </div>

      <form class="space-y-4" @submit.prevent="handleLogin">
        <div>
          <label class="block text-xs text-gray-500 mb-1.5" for="login-username">{{ t('login.username') }}</label>
          <input
            id="login-username"
            v-model="username"
            type="text"
            required
            autocomplete="username"
            :placeholder="t('login.usernamePlaceholder')"
            class="w-full bg-white dark:bg-gray-950 border border-gray-300 dark:border-gray-800/60 text-gray-900 dark:text-gray-200 px-3 py-2 outline-none focus:border-gray-500 dark:focus:border-gray-600 transition-colors focus-visible:ring-2 focus-visible:ring-gray-300 dark:focus-visible:ring-gray-700"
          >
        </div>
        <div>
          <label class="block text-xs text-gray-500 mb-1.5" for="login-password">{{ t('login.password') }}</label>
          <div class="relative">
            <input
              id="login-password"
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              required
              autocomplete="current-password"
              :placeholder="t('login.passwordPlaceholder')"
              class="w-full bg-white dark:bg-gray-950 border border-gray-300 dark:border-gray-800/60 text-gray-900 dark:text-gray-200 px-3 py-2 pr-10 outline-none focus:border-gray-500 dark:focus:border-gray-600 transition-colors focus-visible:ring-2 focus-visible:ring-gray-300 dark:focus-visible:ring-gray-700"
            >
            <button
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
              :aria-label="showPassword ? t('login.hidePassword') : t('login.showPassword')"
              @click="showPassword = !showPassword"
            >
              <EyeOff v-if="showPassword" class="w-4 h-4" />
              <Eye v-else class="w-4 h-4" />
            </button>
          </div>
        </div>

        <div v-if="showTotp">
          <label class="block text-xs text-gray-500 mb-1.5" for="login-totp">{{ t('login.totpCode') }}</label>
          <input
            id="login-totp"
            ref="totpInput"
            v-model="totpCode"
            type="text"
            inputmode="numeric"
            autocomplete="one-time-code"
            maxlength="6"
            :placeholder="t('login.totpPlaceholder')"
            class="w-full bg-white dark:bg-gray-950 border border-gray-300 dark:border-gray-800/60 text-gray-900 dark:text-gray-200 px-3 py-2 outline-none focus:border-gray-500 dark:focus:border-gray-600 transition-colors tracking-widest text-center font-mono focus-visible:ring-2 focus-visible:ring-gray-300 dark:focus-visible:ring-gray-700"
          >
        </div>

        <div
          v-if="errorMsg"
          role="alert"
          class="text-xs text-rose-600 dark:text-rose-500 bg-rose-50 dark:bg-rose-500/10 p-2 border border-rose-200 dark:border-transparent"
        >
          {{ errorMsg }}
        </div>

        <button
          type="submit"
          :disabled="loading || !username.trim() || !password"
          class="w-full mt-4 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-950 py-2 font-medium hover:bg-gray-800 dark:hover:bg-white transition-colors disabled:opacity-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-gray-500"
        >
          {{ loading ? t('login.authenticating') : t('login.signIn') }}
        </button>
      </form>

      <div class="flex items-center justify-center gap-3 mt-6 pt-4 border-t border-gray-200 dark:border-gray-800/60">
        <button
          type="button"
          class="w-8 h-8 flex items-center justify-center text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 transition-colors rounded"
          :title="t('common.github')"
          :aria-label="t('common.github')"
          @click="openGithub"
        >
          <Github class="w-4 h-4" />
        </button>
        <button
          type="button"
          class="w-8 h-8 flex items-center justify-center text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 transition-colors rounded"
          :title="locale === 'zh' ? 'English' : '中文'"
          :aria-label="t('common.changeLanguage')"
          @click="toggleLanguage"
        >
          <Globe class="w-4 h-4" />
        </button>
        <button
          type="button"
          class="w-8 h-8 flex items-center justify-center text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 transition-colors rounded"
          :title="isDark ? t('common.lightMode') : t('common.darkMode')"
          :aria-label="isDark ? t('common.lightMode') : t('common.darkMode')"
          @click="toggleTheme"
        >
          <Moon v-if="!isDark" class="w-4 h-4" />
          <Sun v-else class="w-4 h-4" />
        </button>
      </div>
    </div>
  </div>
</template>
