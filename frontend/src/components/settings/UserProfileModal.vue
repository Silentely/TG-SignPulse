<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import Modal from '../Modal.vue'
import { changePassword, changeUsername, getTOTPStatus, setupTOTP, fetchTOTPQRCode, enableTOTP, disableTOTP } from '../../lib/api'
import { useI18n } from '../../composables/useI18n'

const { t } = useI18n()

const props = defineProps<{ isOpen: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()
const router = useRouter()

const activeTab = ref('username')
const form = ref({
  old_password: '',
  new_password: ''
})

const usernameForm = ref({
  new_username: '',
  password: ''
})

const loading = ref(false)
const error = ref('')
const successMessage = ref('')

const handleUsernameChange = async () => {
  const token = localStorage.getItem('tg-signer-token')
  if (!token) return

  loading.value = true
  error.value = ''
  successMessage.value = ''
  try {
    const res = await changeUsername(token, usernameForm.value.new_username, usernameForm.value.password)
    successMessage.value = t('profile.usernameChanged')
    usernameForm.value.new_username = ''
    usernameForm.value.password = ''
    // If a new token is returned, update it
    if (res.access_token) {
      localStorage.setItem('tg-signer-token', res.access_token)
    }
  } catch (e: any) {
    error.value = e.message || t('profile.changeFailed')
  } finally {
    loading.value = false
  }
}

const handlePasswordChange = async () => {
  const token = localStorage.getItem('tg-signer-token')
  if (!token) return

  loading.value = true
  error.value = ''
  successMessage.value = ''
  try {
    await changePassword(token, form.value.old_password, form.value.new_password)
    successMessage.value = t('profile.passwordChanged')
    form.value.old_password = ''
    form.value.new_password = ''
  } catch (e: any) {
    error.value = e.message || t('profile.changeFailed')
  } finally {
    loading.value = false
  }
}

// TOTP logic
const totpEnabled = ref(false)
const qrUrl = ref('')
const totpCode = ref('')
const totpSecret = ref('')

const checkTOTP = async () => {
  const token = localStorage.getItem('tg-signer-token')
  if (!token) return
  try {
    const res = await getTOTPStatus(token)
    totpEnabled.value = res.enabled
    if (!res.enabled) {
      // Must call setup first to generate a pending secret, then fetch QR
      const setupRes = await setupTOTP(token)
      totpSecret.value = setupRes.secret || ''
      qrUrl.value = await fetchTOTPQRCode(token)
    }
  } catch (e) {
    console.error('Failed to get TOTP status', e)
  }
}

watch(() => props.isOpen, (val) => {
  if (val) {
    checkTOTP()
  } else {
    // reset state
    qrUrl.value = ''
    totpCode.value = ''
    totpSecret.value = ''
    activeTab.value = 'username'
    error.value = ''
    successMessage.value = ''
  }
})

const handleEnableTOTP = async () => {
  if (!totpCode.value) return
  const token = localStorage.getItem('tg-signer-token')
  if (!token) return

  loading.value = true
  error.value = ''
  try {
    await enableTOTP(token, totpCode.value)
    successMessage.value = t('profile.totpEnableSuccess')
    totpCode.value = ''
    await checkTOTP()
  } catch (e: any) {
    error.value = e.message || t('profile.verifyFailed')
  } finally {
    loading.value = false
  }
}

const handleDisableTOTP = async () => {
  if (!totpCode.value) return
  const token = localStorage.getItem('tg-signer-token')
  if (!token) return

  loading.value = true
  error.value = ''
  try {
    await disableTOTP(token, totpCode.value)
    successMessage.value = t('profile.totpDisableSuccess')
    totpCode.value = ''
    await checkTOTP()
  } catch (e: any) {
    error.value = e.message || t('profile.disableFailed')
  } finally {
    loading.value = false
  }
}

const handleLogout = () => {
  localStorage.removeItem('tg-signer-token')
  router.push('/login')
}
</script>

<template>
  <Modal :isOpen="isOpen" @close="$emit('close')" :title="t('profile.title')">
    <div class="flex gap-4 mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-2 overflow-x-auto">
      <button 
        @click="activeTab = 'username'; error = ''; successMessage = ''"
        class="text-sm font-medium transition-colors whitespace-nowrap"
        :class="activeTab === 'username' ? 'text-gray-900 dark:text-gray-100' : 'text-gray-500 hover:text-gray-900 dark:hover:text-gray-300'"
      >{{ t('profile.changeUsername') }}</button>
      <button 
        @click="activeTab = 'password'; error = ''; successMessage = ''"
        class="text-sm font-medium transition-colors whitespace-nowrap"
        :class="activeTab === 'password' ? 'text-gray-900 dark:text-gray-100' : 'text-gray-500 hover:text-gray-900 dark:hover:text-gray-300'"
      >{{ t('profile.changePassword') }}</button>
      <button 
        @click="activeTab = 'totp'; error = ''; successMessage = ''"
        class="text-sm font-medium transition-colors whitespace-nowrap"
        :class="activeTab === 'totp' ? 'text-gray-900 dark:text-gray-100' : 'text-gray-500 hover:text-gray-900 dark:hover:text-gray-300'"
      >{{ t('profile.totp') }}</button>
    </div>

    <!-- Messages -->
    <div v-if="error" class="text-xs text-rose-600 dark:text-rose-500 bg-rose-50 dark:bg-rose-500/10 p-2 border border-rose-200 dark:border-transparent mb-4">
      {{ error }}
    </div>
    <div v-if="successMessage" class="text-xs text-emerald-600 dark:text-emerald-500 bg-emerald-50 dark:bg-emerald-500/10 p-2 border border-emerald-200 dark:border-transparent mb-4">
      {{ successMessage }}
    </div>

    <!-- Username Tab -->
    <div v-if="activeTab === 'username'" class="space-y-4">
      <div class="space-y-1.5">
        <label class="text-xs text-gray-500 block">{{ t('profile.newUsername') }}</label>
        <input v-model="usernameForm.new_username" type="text" :placeholder="t('profile.newUsernamePlaceholder')" class="w-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:bg-gray-50 dark:focus:bg-gray-800">
      </div>
      <div class="space-y-1.5">
        <label class="text-xs text-gray-500 block">{{ t('profile.currentPassword') }}</label>
        <input v-model="usernameForm.password" type="password" :placeholder="t('profile.currentPasswordPlaceholder')" class="w-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:bg-gray-50 dark:focus:bg-gray-800">
      </div>
      <button 
        @click="handleUsernameChange"
        :disabled="loading || !usernameForm.new_username || !usernameForm.password"
        class="w-full mt-2 px-4 py-2 text-sm bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-950 hover:bg-gray-800 dark:hover:bg-white transition-colors disabled:opacity-50"
      >
        {{ loading ? t('profile.changing') : t('profile.confirmChangeUsername') }}
      </button>
    </div>

    <!-- Password Tab -->
    <div v-else-if="activeTab === 'password'" class="space-y-4">
      <div class="space-y-1.5">
        <label class="text-xs text-gray-500 block">{{ t('profile.oldPassword') }}</label>
        <input v-model="form.old_password" type="password" class="w-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:bg-gray-50 dark:focus:bg-gray-800">
      </div>
      <div class="space-y-1.5">
        <label class="text-xs text-gray-500 block">{{ t('profile.newPassword') }}</label>
        <input v-model="form.new_password" type="password" class="w-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:bg-gray-50 dark:focus:bg-gray-800">
      </div>
      <button 
        @click="handlePasswordChange"
        :disabled="loading || !form.old_password || !form.new_password"
        class="w-full mt-2 px-4 py-2 text-sm bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-950 hover:bg-gray-800 dark:hover:bg-white transition-colors disabled:opacity-50"
      >
        {{ loading ? t('profile.changing') : t('profile.confirmChangePassword') }}
      </button>
    </div>

    <!-- TOTP Tab -->
    <div v-else class="space-y-4">
      <div v-if="totpEnabled" class="space-y-4">
        <div class="flex items-center gap-2 p-3 bg-emerald-50 dark:bg-emerald-500/10 border border-emerald-200 dark:border-emerald-800/50">
          <div class="w-2 h-2 rounded-full bg-emerald-500 shrink-0"></div>
          <p class="text-sm text-emerald-700 dark:text-emerald-400 font-medium">{{ t('profile.totpEnabled') }}</p>
        </div>
        <p class="text-xs text-gray-500">{{ t('profile.totpDisableHint') }}</p>
        <input v-model="totpCode" type="text" :placeholder="t('profile.totpCodePlaceholder')" maxlength="6" class="w-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm text-center font-mono tracking-widest outline-none transition-colors focus:bg-gray-50 dark:focus:bg-gray-800">
        <button 
          @click="handleDisableTOTP"
          :disabled="loading || !totpCode"
          class="w-full px-4 py-2 text-sm text-rose-600 dark:text-rose-500 bg-rose-50 dark:bg-rose-500/10 border border-rose-200 dark:border-rose-800/50 hover:bg-rose-100 dark:hover:bg-rose-500/20 transition-colors disabled:opacity-50"
        >
          {{ loading ? t('settings.processing') : t('profile.disableTotp') }}
        </button>
      </div>

      <div v-else class="space-y-4">
        <div class="flex items-center gap-2 p-3 bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-800/50">
          <div class="w-2 h-2 rounded-full bg-amber-500 shrink-0"></div>
          <p class="text-sm text-amber-700 dark:text-amber-400 font-medium">{{ t('profile.totpDisabled') }}</p>
        </div>
        <p class="text-xs text-gray-500">{{ t('profile.totpScanHint') }}</p>
        <div v-if="qrUrl" class="flex justify-center p-4 bg-white dark:bg-white mx-auto w-max border border-gray-200 dark:border-gray-300">
          <img :src="qrUrl" alt="TOTP QR Code" class="w-36 h-36" />
        </div>
        <p v-else class="text-xs text-gray-400 text-center py-4">{{ t('profile.loadingQr') }}</p>
        <div v-if="totpSecret" class="mt-2 p-2 bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 text-center">
          <p class="text-[10px] text-gray-500 mb-1">{{ t('profile.manualEntry') }}</p>
          <code class="text-xs font-mono text-gray-900 dark:text-gray-100 select-all break-all">{{ totpSecret }}</code>
        </div>
        <p class="text-xs text-gray-500">{{ t('profile.totpVerifyHint') }}</p>
        <input v-model="totpCode" type="text" :placeholder="t('profile.totpCodePlaceholder')" maxlength="6" class="w-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm text-center font-mono tracking-widest outline-none transition-colors focus:bg-gray-50 dark:focus:bg-gray-800">
        <button 
          @click="handleEnableTOTP"
          :disabled="loading || !totpCode"
          class="w-full px-4 py-2 text-sm bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-950 hover:bg-gray-800 dark:hover:bg-white transition-colors disabled:opacity-50"
        >
          {{ loading ? t('profile.verifying') : t('profile.enableTotp') }}
        </button>
      </div>
    </div>

    <template #footer>
      <button 
        @click="handleLogout"
        class="px-4 py-2 text-sm text-rose-600 dark:text-rose-500 hover:bg-rose-50 dark:hover:bg-rose-500/10 transition-colors"
      >
        {{ t('profile.logout') }}
      </button>
      <button 
        @click="$emit('close')"
        class="px-4 py-2 text-sm text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 transition-colors"
      >
        {{ t('profile.close') }}
      </button>
    </template>
  </Modal>
</template>
