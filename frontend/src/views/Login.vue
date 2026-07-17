<script setup lang="ts">
import { ref, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { Github, Globe, Moon, Sun, Eye, EyeOff } from 'lucide-vue-next'
import { login } from '../lib/api'
import { useAuthStore } from '../stores/auth'
import { useI18n } from '../composables/useI18n'
import { useTheme } from '../composables/useTheme'
import { getErrorCode, getLocalizedErrorMessage } from '../lib/types'

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
    const code = getErrorCode(e) || ''
    const detail = getLocalizedErrorMessage(e, t)
    if (code === 'TOTP_REQUIRED_OR_INVALID' || detail.includes('TOTP') || detail.includes('两步验证')) {
      showTotp.value = true
      errorMsg.value = totpCode.value ? t('login.totpInvalid') : t('login.totpRequired')
      totpCode.value = ''
      await nextTick()
      totpInput.value?.focus()
    } else {
      errorMsg.value = mapLoginError(code || detail)
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
  <div class="min-h-screen flex flex-col items-center justify-center font-sans px-4 py-10">
    <div class="w-full max-w-sm ui-card shadow-[var(--sp-shadow-md)] px-8 py-10">
      <div class="mb-8 text-center">
        <div class="ui-brand-mark w-12 h-12 mx-auto text-lg mb-4">TG</div>
        <h1 class="text-xl font-medium text-gray-900 dark:text-gray-100 tracking-[0.2em]">SIGNPULSE</h1>
        <p class="text-xs text-gray-500 mt-2 leading-relaxed">{{ t('login.subtitle') }}</p>
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
            class="ui-input"
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
              class="ui-input pr-10"
            >
            <button
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-gray-400 hover:text-gray-700 dark:hover:text-gray-200 rounded"
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
            class="ui-input tracking-[0.35em] text-center font-mono"
          >
        </div>

        <div
          v-if="errorMsg"
          role="alert"
          class="text-xs text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-500/10 p-2.5 border border-rose-200 dark:border-rose-800/40"
        >
          {{ errorMsg }}
        </div>

        <button
          type="submit"
          :disabled="loading || !username.trim() || !password"
          class="ui-btn-primary w-full mt-2 py-2.5"
        >
          <span v-if="loading" class="ui-spinner !w-4 !h-4 !border-2" />
          {{ loading ? t('login.authenticating') : t('login.signIn') }}
        </button>
      </form>

      <div class="flex items-center justify-center gap-2 mt-7 pt-5 border-t border-gray-200 dark:border-gray-800/60">
        <button
          type="button"
          class="ui-icon-btn"
          :title="t('common.github')"
          :aria-label="t('common.github')"
          @click="openGithub"
        >
          <Github class="w-4 h-4" />
        </button>
        <button
          type="button"
          class="ui-icon-btn"
          :title="locale === 'zh' ? 'English' : '中文'"
          :aria-label="t('common.changeLanguage')"
          @click="toggleLanguage"
        >
          <Globe class="w-4 h-4" />
        </button>
        <button
          type="button"
          class="ui-icon-btn"
          :title="isDark ? t('common.lightMode') : t('common.darkMode')"
          :aria-label="isDark ? t('common.lightMode') : t('common.darkMode')"
          @click="toggleTheme($event)"
        >
          <Moon v-if="!isDark" class="w-4 h-4" />
          <Sun v-else class="w-4 h-4" />
        </button>
      </div>
    </div>
  </div>
</template>
