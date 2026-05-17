<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import Modal from '../Modal.vue'
import { startAccountLogin, verifyAccountLogin, updateAccount, startQrLogin, getQrLoginStatus, submitQrPassword, cancelQrLogin } from '../../lib/api'
import { useI18n } from '../../composables/useI18n'

const { t } = useI18n()

const props = defineProps<{ isOpen: boolean, initialMethod?: 'code' | 'qr', initialAccountName?: string }>()
const emit = defineEmits<{ (e: 'close'): void, (e: 'success'): void }>()

const loginMethod = ref<'code' | 'qr'>('code')

const form = ref({
  account_name: '',
  remark: '',
  phone_number: '',
  phone_code: '',
  password: '',
  proxy: ''
})

const loading = ref(false)
const error = ref('')

// Code login specific
const phoneCodeHash = ref('')
const codeSent = ref(false)

// QR login specific
const qrImage = ref('')
const loginId = ref('')
let pollInterval: any = null

const reset = async () => {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
  if (loginId.value) {
    try {
      const token = localStorage.getItem('tg-signer-token') || ''
      if (token) await cancelQrLogin(token, loginId.value)
    } catch (e) {}
  }
  form.value = { account_name: props.initialAccountName || '', remark: '', phone_number: '', phone_code: '', password: '', proxy: '' }
  phoneCodeHash.value = ''
  error.value = ''
  codeSent.value = false
  qrImage.value = ''
  loginId.value = ''
  loading.value = false
}

watch(() => props.isOpen, (val) => {
  if (val) {
    if (props.initialMethod) loginMethod.value = props.initialMethod
    reset()
  } else {
    reset()
  }
})

watch(loginMethod, () => {
  const accountName = form.value.account_name
  const remark = form.value.remark
  const password = form.value.password
  const proxy = form.value.proxy
  reset()
  form.value.account_name = accountName
  form.value.remark = remark
  form.value.password = password
  form.value.proxy = proxy
})

const handleClose = () => {
  reset()
  emit('close')
}

// ============ QR Login Logic ============

const pollStatus = async (token: string, lid: string) => {
  try {
    const res = await getQrLoginStatus(token, lid)
    if (res.status === 'success') {
      clearInterval(pollInterval)
      pollInterval = null
      if (form.value.remark) {
        try {
          await updateAccount(token, form.value.account_name, { remark: form.value.remark })
        } catch (err) {}
      }
      loading.value = false
      emit('success')
      handleClose()
    } else if (res.status === 'waiting_for_password' || res.status === 'password_required') {
      // 如果已经填了密码，自动提交
      if (form.value.password) {
        clearInterval(pollInterval)
        pollInterval = null
        handleQrPasswordSubmit(token, lid)
      } else {
        error.value = t('addAccount.needPassword')
        clearInterval(pollInterval)
        pollInterval = null
        loading.value = false
      }
    } else if (res.status === 'failed' || res.status === 'expired') {
      clearInterval(pollInterval)
      pollInterval = null
      error.value = res.message || t('addAccount.qrFailed')
      loading.value = false
    }
  } catch (e) {
    console.error('QR Poll error', e)
  }
}

const handleQrPasswordSubmit = async (token: string, lid: string) => {
  loading.value = true
  error.value = ''
  try {
    const res = await submitQrPassword(token, {
      login_id: lid,
      password: form.value.password
    })
    // 如果后端直接返回 success，说明登录已完成，无需再轮询
    if (res.success) {
      if (form.value.remark) {
        try {
          await updateAccount(token, form.value.account_name, { remark: form.value.remark })
        } catch (err) {}
      }
      loading.value = false
      emit('success')
      handleClose()
      return
    }
    // 否则继续轮询等待最终状态
    if (pollInterval) clearInterval(pollInterval)
    pollInterval = setInterval(() => pollStatus(token, lid), 3000)
  } catch (e: any) {
    error.value = e.message || t('addAccount.passwordFailed')
    loading.value = false
  }
}

const handleGetQr = async () => {
  if (!form.value.account_name) {
    error.value = t('addAccount.nameRequired')
    return
  }
  const token = localStorage.getItem('tg-signer-token')
  if (!token) return

  loading.value = true
  error.value = ''
  try {
    const res = await startQrLogin(token, {
      account_name: form.value.account_name,
      proxy: form.value.proxy || undefined
    })
    loginId.value = res.login_id
    qrImage.value = res.qr_image || ''
    
    if (pollInterval) clearInterval(pollInterval)
    pollInterval = setInterval(() => pollStatus(token, res.login_id), 3000)
  } catch (e: any) {
    error.value = e.message || t('addAccount.getQrFailed')
  } finally {
    loading.value = false
  }
}

// ============ Code Login Logic ============

const handleSendCode = async () => {
  if (!form.value.account_name || !form.value.phone_number) {
    error.value = t('addAccount.namePhoneRequired')
    return
  }
  const token = localStorage.getItem('tg-signer-token')
  if (!token) return

  loading.value = true
  error.value = ''
  try {
    const res = await startAccountLogin(token, {
      account_name: form.value.account_name,
      phone_number: form.value.phone_number,
      proxy: form.value.proxy || undefined
    })
    phoneCodeHash.value = res.phone_code_hash
    codeSent.value = true
    error.value = t('addAccount.codeSent')
    setTimeout(() => { if (error.value === t('addAccount.codeSent')) error.value = '' }, 3000)
  } catch (e: any) {
    error.value = e.message || t('addAccount.sendCodeFailed')
  } finally {
    loading.value = false
  }
}

const handleSave = async () => {
  const token = localStorage.getItem('tg-signer-token')
  if (!token) return

  loading.value = true
  error.value = ''

  if (loginMethod.value === 'code') {
    if (!phoneCodeHash.value) {
      error.value = t('addAccount.getCodeFirst')
      loading.value = false
      return
    }
    if (!form.value.phone_code) {
      error.value = t('addAccount.enterCode')
      loading.value = false
      return
    }
    try {
      await verifyAccountLogin(token, {
        account_name: form.value.account_name,
        phone_number: form.value.phone_number,
        phone_code: form.value.phone_code,
        phone_code_hash: phoneCodeHash.value,
        password: form.value.password || undefined,
        proxy: form.value.proxy || undefined
      })
      if (form.value.remark) {
        try { await updateAccount(token, form.value.account_name, { remark: form.value.remark }) } catch (err) {}
      }
      loading.value = false
      emit('success')
      handleClose()
    } catch (e: any) {
      // 如果错误提示包含2FA相关信息，显示密码提示
      const msg = e.message || ''
      if (msg.includes('两步验证') || msg.includes('2FA') || msg.includes('SESSION_PASSWORD_NEEDED')) {
        error.value = t('addAccount.needPassword')
      } else {
        error.value = msg || t('addAccount.verifyFailed')
      }
      loading.value = false
    }
  } else {
    // QR Login Save (submit password if waiting)
    if (!loginId.value) {
      error.value = t('addAccount.scanFirst')
      loading.value = false
      return
    }
    if (form.value.password) {
      await handleQrPasswordSubmit(token, loginId.value)
    } else {
      // 没有密码时，检查当前轮询是否还在运行
      // 如果轮询在运行，说明还在等待后端确认，不需要用户操作
      if (pollInterval) {
        // 轮询中，等待自动完成
        loading.value = false
        return
      }
      error.value = t('addAccount.enterPasswordOrWait')
      loading.value = false
    }
  }
}

onUnmounted(() => {
  if (pollInterval) clearInterval(pollInterval)
})
</script>

<template>
  <Modal :isOpen="isOpen" @close="handleClose" :title="loginMethod === 'code' ? t('addAccount.codeTitle') : t('addAccount.qrTitle')">
    <div class="space-y-4 pb-2">
      
      <div v-if="error" class="text-xs text-rose-600 dark:text-rose-500 bg-rose-50 dark:bg-rose-500/10 p-2 border border-rose-200 dark:border-transparent rounded">
        {{ error }}
      </div>

      <!-- Common Fields -->
      <div class="space-y-1.5">
        <label class="text-xs text-gray-500 block">{{ t('addAccount.accountName') }} <span class="text-rose-500">*</span></label>
        <input 
          v-model="form.account_name"
          type="text" 
          :placeholder="t('addAccount.accountNamePlaceholder')"
          class="w-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:border-gray-500 dark:focus:border-gray-500 rounded-sm"
        >
      </div>
      
      <div class="space-y-1.5">
        <label class="text-xs text-gray-500 block">{{ t('addAccount.remark') }}</label>
        <input 
          v-model="form.remark"
          type="text" 
          :placeholder="t('addAccount.remarkPlaceholder')"
          class="w-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:border-gray-500 dark:focus:border-gray-500 rounded-sm"
        >
      </div>

      <!-- Code specific fields -->
      <template v-if="loginMethod === 'code'">
        <div class="space-y-1.5">
          <label class="text-xs text-gray-500 block">{{ t('addAccount.phone') }} <span class="text-rose-500">*</span></label>
          <input 
            v-model="form.phone_number"
            type="text" 
            :placeholder="t('addAccount.phonePlaceholder')"
            class="w-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:border-gray-500 dark:focus:border-gray-500 rounded-sm"
          >
        </div>
        <div class="space-y-1.5">
          <label class="text-xs text-gray-500 block">{{ t('addAccount.verifyCode') }} <span class="text-rose-500">*</span></label>
          <div class="flex gap-2">
            <input 
              v-model="form.phone_code"
              type="text" 
              :placeholder="t('addAccount.codePlaceholder')"
              class="flex-1 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:border-gray-500 dark:focus:border-gray-500 rounded-sm"
            >
            <button 
              @click="handleSendCode"
              :disabled="loading || !form.account_name || !form.phone_number"
              class="px-4 py-2 text-sm bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors border border-gray-200 dark:border-gray-700 rounded-sm whitespace-nowrap disabled:opacity-50"
            >
              {{ codeSent ? t('addAccount.resendCode') : t('addAccount.getCode') }}
            </button>
          </div>
        </div>
      </template>

      <!-- Cloud Password & Proxy for BOTH -->
      <div class="space-y-1.5">
        <label class="text-xs text-gray-500 block">{{ t('addAccount.cloudPassword') }}</label>
        <input 
          v-model="form.password"
          type="password" 
          :placeholder="t('addAccount.cloudPasswordPlaceholder')"
          class="w-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:border-gray-500 dark:focus:border-gray-500 rounded-sm"
        >
      </div>

      <div class="space-y-1.5">
        <label class="text-xs text-gray-500 block">{{ t('addAccount.proxy') }}</label>
        <input 
          v-model="form.proxy"
          type="text" 
          :placeholder="t('addAccount.proxyPlaceholder')"
          class="w-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800 text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:border-gray-500 dark:focus:border-gray-500 rounded-sm"
        >
      </div>

      <!-- QR specific block -->
      <div v-if="loginMethod === 'qr'" class="bg-gray-50 dark:bg-gray-800/50 rounded-lg p-4 border border-gray-200 dark:border-gray-800 relative mt-2">
        <div class="flex justify-between items-center mb-4">
          <span class="text-sm text-gray-700 dark:text-gray-300 font-medium">{{ t('addAccount.qrHint') }}</span>
          <button 
            @click="handleGetQr"
            :disabled="loading"
            class="px-3 py-1.5 text-xs bg-white dark:bg-gray-700 hover:bg-gray-100 dark:hover:bg-gray-600 text-gray-700 dark:text-gray-200 rounded-sm border border-gray-300 dark:border-gray-600 transition-colors disabled:opacity-50"
          >
            {{ t('addAccount.getQr') }}
          </button>
        </div>
        <div class="flex justify-center items-center h-48 w-full bg-white dark:bg-gray-900 rounded-md border border-gray-200 dark:border-gray-700">
          <img v-if="qrImage" :src="qrImage" class="w-40 h-40" />
          <span v-else class="text-sm text-gray-400">{{ t('addAccount.qrArea') }}</span>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="w-full flex justify-end gap-3">
        <button 
          @click="handleClose"
          class="px-5 py-2 text-sm text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 transition-colors"
        >
          {{ t('addAccount.cancel') }}
        </button>
        <button 
          @click="handleSave"
          :disabled="loading"
          class="px-5 py-2 text-sm bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-950 hover:bg-gray-800 dark:hover:bg-white transition-colors rounded-sm disabled:opacity-50"
        >
          {{ loading ? t('addAccount.processing') : t('addAccount.confirmSave') }}
        </button>
      </div>
    </template>
  </Modal>
</template>
