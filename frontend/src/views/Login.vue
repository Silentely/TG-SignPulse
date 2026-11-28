<script setup lang="ts">
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Github, Globe, Moon, Sun, Eye, EyeOff } from 'lucide-vue-next'
import { login } from '../lib/api'
import { useAuthStore } from '../stores/auth'
import { useI18n } from '../composables/useI18n'
import { useTheme } from '../composables/useTheme'
import { getErrorCode, getLocalizedErrorMessage } from '../lib/types'

const router = useRouter()
const authStore = useAuthStore()
const { locale, toggleLanguage, t, te } = useI18n()
const { isDark, toggleTheme } = useTheme()

const username = ref('')
const password = ref('')
const totpCode = ref('')
const showTotp = ref(false)
const showPassword = ref(false)
const errorMsg = ref('')
const loading = ref(false)
const totpInput = ref<HTMLInputElement | null>(null)

const usernameInput = ref<HTMLInputElement | null>(null)
const isTotpValid = computed(() => /^[0-9]{6}$/.test(totpCode.value))

const handleTotpInput = () => {
  errorMsg.value = ''
}

const promptTotp = async () => {
  showTotp.value = true
  showPassword.value = false
  // 请求已完成，先解除禁用再聚焦验证码输入框。
  loading.value = false
  await nextTick()
  totpInput.value?.focus()
  totpInput.value?.select()
}

const backToCredentials = async () => {
  if (loading.value) return
  showTotp.value = false
  totpCode.value = ''
  errorMsg.value = ''
  await nextTick()
  usernameInput.value?.focus()
}

onMounted(() => {
  if (authStore.isAuthenticated && !authStore.isTokenExpired()) {
    router.replace('/dashboard').catch(() => {
      window.location.href = '/dashboard'
    })
  }
})

watch(
  () => authStore.isAuthenticated,
  (authed) => {
    if (authed && !authStore.isTokenExpired()) {
      router.replace('/dashboard').catch(() => {
        window.location.href = '/dashboard'
      })
    }
  },
)

const mapLoginError = (detail: string): string => {
  const code = detail.trim()
  const key = `login.errors.${code}`
  if (te && te(key)) return t(key)
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
  if (loading.value) return
  if (!username.value.trim() || !password.value) return
  if (showTotp.value && !isTotpValid.value) return
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
    if ('requires_totp' in res && res.requires_totp) {
      await promptTotp()
      return
    }
    if ('access_token' in res && res.access_token) {
      authStore.setToken(res.access_token)
      try {
        await router.replace('/dashboard')
      } catch {
        window.location.href = '/dashboard'
      }
      return
    }
  } catch (e: unknown) {
    const code = getErrorCode(e) || ''
    const detail = getLocalizedErrorMessage(e, t)
    // 兼容旧版后端的挑战错误码；新版缺少验证码走正常响应分支。
    if (code === 'TOTP_INVALID' || code === 'TOTP_REQUIRED_OR_INVALID') {
      errorMsg.value = totpCode.value ? t('login.totpInvalid') : ''
      await promptTotp()
    } else {
      errorMsg.value = mapLoginError(code || detail)
    }
  } finally {
    loading.value = false
  }
}

const openGithub = () => {
  window.open('https://github.com/Silentely/TG-SignPulse', '_blank', 'noopener,noreferrer')
}
</script>

<template>
  <div class="min-h-screen flex flex-col items-center justify-center font-sans px-4 py-10">
    <div class="w-full max-w-sm ui-card shadow-[var(--sp-shadow-md)] px-8 py-10">
      <div class="mb-8 text-center">
        <div class="ui-brand-mark w-12 h-12 mx-auto text-lg mb-4">TG</div>
        <h1 class="text-xl font-medium text-[var(--sp-text)] font-semibold tracking-[0.2em]">SIGNPULSE</h1>
        <p class="text-xs text-[var(--sp-text-muted)] mt-2 leading-relaxed">{{ t('login.subtitle') }}</p>
      </div>

      <form class="space-y-4" @submit.prevent="handleLogin">
        <div v-show="!showTotp">
          <label class="block text-xs text-[var(--sp-text-muted)] mb-1.5" for="login-username">{{ t('login.username') }}</label>
          <input
            id="login-username"
            ref="usernameInput"
            :disabled="loading"
            v-model="username"
            type="text"
            required
            autocomplete="username"
            autofocus
            :placeholder="t('login.usernamePlaceholder')"
            class="ui-input"
          >
        </div>
        <div v-show="!showTotp">
          <label class="block text-xs text-[var(--sp-text-muted)] mb-1.5" for="login-password">{{ t('login.password') }}</label>
          <div class="relative">
            <input
              id="login-password"
              :disabled="loading"
              v-model="password"
              :type="showPassword ? 'text' : 'password'"
              required
              autocomplete="current-password"
              :placeholder="t('login.passwordPlaceholder')"
              class="ui-input pr-10"
            >
            <button
              type="button"
              class="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-[var(--sp-text-muted)] hover:text-[var(--sp-text)] rounded-[var(--sp-radius-sm)] cursor-pointer"
              :aria-label="showPassword ? t('login.hidePassword') : t('login.showPassword')"
              @click="showPassword = !showPassword"
            >
              <EyeOff v-if="showPassword" class="w-4 h-4" />
              <Eye v-else class="w-4 h-4" />
            </button>
          </div>
        </div>

        <p v-if="showTotp" id="login-totp-hint" role="status" class="text-xs text-[var(--sp-text-muted)] leading-relaxed">
          {{ t('login.totpRequired') }}
        </p>

        <div v-if="showTotp">
          <label class="block text-xs text-[var(--sp-text-muted)] mb-1.5" for="login-totp">{{ t('login.totpCode') }}</label>
          <input
            id="login-totp"
            ref="totpInput"
            v-model="totpCode"
            type="text"
            inputmode="numeric"
            autocomplete="one-time-code"
            maxlength="6"
            minlength="6"
            pattern="[0-9]{6}"
            :disabled="loading"
            aria-describedby="login-totp-hint"
            :aria-invalid="Boolean(errorMsg)"
            required
            aria-required="true"
            :placeholder="t('login.totpPlaceholder')"
            class="ui-input tracking-[0.35em] text-center font-mono"
            @input="handleTotpInput"
          >
        </div>

        <div
          v-if="errorMsg"
          role="alert"
          class="text-xs p-2.5 border rounded-[var(--sp-radius-sm)] text-rose-600 dark:text-rose-400 bg-rose-50 dark:bg-rose-500/10 border-rose-200 dark:border-rose-800/40"
        >
          {{ errorMsg }}
        </div>

        <button
          type="submit"
          :disabled="loading || !username.trim() || !password || (showTotp && !isTotpValid)"
          class="ui-btn-primary w-full mt-2 py-2.5 cursor-pointer"
        >
          <span v-if="loading" class="ui-spinner !w-4 !h-4 !border-2" />
          {{ loading ? t('login.authenticating') : showTotp ? t('login.verifyAndSignIn') : t('login.nextStep') }}
        </button>
        <button
          v-if="showTotp"
          type="button"
          data-testid="login-back"
          :disabled="loading"
          class="ui-btn-secondary w-full cursor-pointer"
          @click="backToCredentials"
        >
          {{ t('login.backToCredentials') }}
        </button>
      </form>

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
  </div>
</template>
