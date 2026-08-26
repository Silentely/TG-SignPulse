<script setup lang="ts">
import { ref, watch, onUnmounted } from 'vue'
import { Phone, QrCode } from 'lucide-vue-next'
import Modal from '../Modal.vue'
import { startAccountLogin, verifyAccountLogin, updateAccount, startQrLogin, getQrLoginStatus, submitQrPassword, cancelQrLogin } from '../../lib/api'
import { getAuthToken } from '../../lib/api/core'
import { useI18n } from '../../composables/useI18n'
import { useToast } from '../../composables/useToast'
import { startChainPoll, type ChainPollHandle } from '../../lib/chain-poll'
import { getErrorCode, getLocalizedErrorMessage } from '../../lib/types'
import { devLog } from '../../lib/devLog'

const { t } = useI18n()
const toast = useToast()

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

// 验证码重发倒计时：防止重复点击触发 Telegram 限流
const codeCountdown = ref(0)
let codeTimer: number | undefined

const stopCodeCountdown = () => {
  if (codeTimer !== undefined) {
    window.clearInterval(codeTimer)
    codeTimer = undefined
  }
}

const startCodeCountdown = () => {
  stopCodeCountdown()
  codeCountdown.value = 60
  codeTimer = window.setInterval(() => {
    codeCountdown.value -= 1
    if (codeCountdown.value <= 0) stopCodeCountdown()
  }, 1000)
}

// Code login specific
const phoneCodeHash = ref('')
const codeSent = ref(false)

// QR login specific
const qrImage = ref('')
const loginId = ref('')
/** 二维码加载失败/已过期：清空图片后展示错误占位与重新获取入口 */
const qrLoadFailed = ref(false)
let pollHandle: ChainPollHandle | null = null

const handleQrImageError = () => {
  qrImage.value = ''
  qrLoadFailed.value = true
}

const reset = async () => {
  pollHandle?.stop()
  pollHandle = null
  if (loginId.value) {
    try {
      const token = getAuthToken()
      if (token) await cancelQrLogin(token, loginId.value)
    } catch (e: unknown) {
      devLog.warn('cancelQrLogin failed:', getLocalizedErrorMessage(e, t))
    }
  }
  form.value = { account_name: props.initialAccountName || '', remark: '', phone_number: '', phone_code: '', password: '', proxy: '' }
  phoneCodeHash.value = ''
  error.value = ''
  codeSent.value = false
  stopCodeCountdown()
  codeCountdown.value = 0
  qrImage.value = ''
  qrLoadFailed.value = false
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

// 仅在弹窗打开时切换登录方式才重置，避免 open 时赋值 method 与 reset 竞态
watch(loginMethod, () => {
  if (!props.isOpen) return
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

/** 登录成功后保存备注：失败仅告警，不阻断登录流程 */
const saveRemarkIfPresent = async (token: string) => {
  if (!form.value.remark) return
  try {
    await updateAccount(token, form.value.account_name, { remark: form.value.remark })
  } catch (err) {
    devLog.warn('登录成功但备注保存失败', err)
  }
}

// ============ QR Login Logic ============

const pollStatus = async (token: string, lid: string) => {
  try {
    const res = await getQrLoginStatus(token, lid)
    if (res.status === 'success') {
      pollHandle?.stop()
      pollHandle = null
      await saveRemarkIfPresent(token)
      loading.value = false
      toast.success(t('addAccount.loginSuccess'))
      emit('success')
      handleClose()
    } else if (res.status === 'waiting_for_password' || res.status === 'password_required') {
      // 如果已经填了密码，自动提交
      if (form.value.password) {
        pollHandle?.stop()
        pollHandle = null
        handleQrPasswordSubmit(token, lid)
      } else {
        error.value = t('addAccount.needPassword')
        pollHandle?.stop()
        pollHandle = null
        loading.value = false
      }
    } else if (res.status === 'failed' || res.status === 'expired') {
      pollHandle?.stop()
      pollHandle = null
      // 二维码已失效：清空图片避免用户继续扫描无意义的旧码
      qrImage.value = ''
      error.value = res.status === 'expired' ? t('addAccount.qrExpired') : (res.message || t('addAccount.qrFailed'))
      loading.value = false
    }
  } catch (e) {
    devLog.error('QR Poll error', e)
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
      await saveRemarkIfPresent(token)
      loading.value = false
      toast.success(t('addAccount.loginSuccess'))
      emit('success')
      handleClose()
      return
    }
    // 否则继续轮询等待最终状态
    pollHandle?.stop()
    pollHandle = startChainPoll(() => pollStatus(token, lid), { intervalMs: 3000 })
  } catch (e: unknown) {
    error.value = getLocalizedErrorMessage(e, t, t('addAccount.passwordFailed'))
    loading.value = false
  }
}

const handleGetQr = async () => {
  if (!form.value.account_name) {
    error.value = t('addAccount.nameRequired')
    return
  }
  const token = getAuthToken()
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
    qrLoadFailed.value = false
    
    pollHandle?.stop()
    pollHandle = startChainPoll(() => pollStatus(token, res.login_id), { intervalMs: 3000 })
  } catch (e: unknown) {
    error.value = getLocalizedErrorMessage(e, t, t('addAccount.getQrFailed'))
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
  const token = getAuthToken()
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
    toast.info(t('addAccount.codeSent'))
    startCodeCountdown()
  } catch (e: unknown) {
    error.value = getLocalizedErrorMessage(e, t, t('addAccount.sendCodeFailed'))
  } finally {
    loading.value = false
  }
}

const handleSave = async () => {
  const token = getAuthToken()
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
      await saveRemarkIfPresent(token)
      loading.value = false
      toast.success(t('addAccount.loginSuccess'))
      emit('success')
      handleClose()
    } catch (e: unknown) {
      // 按后端稳定错误码区分「首次需要 2FA 密码」与「2FA 密码错误」，
      // 不按本地化文案匹配（英文界面下中文子串永不命中）
      const code = getErrorCode(e)
      if (code === 'SESSION_PASSWORD_NEEDED') {
        error.value = t('addAccount.needPassword')
      } else if (code === 'PASSWORD_HASH_INVALID') {
        error.value = t('addAccount.passwordFailed')
      } else {
        error.value = getLocalizedErrorMessage(e, t) || t('addAccount.verifyFailed')
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
    } else if (pollHandle?.active) {
      // 没有密码但轮询仍在运行：保留轮询等待扫码完成，
      // 停掉后扫码完成不会再被 pollStatus 检测到
      loading.value = false
      error.value = t('addAccount.waitScan')
    } else {
      pollHandle = null
      error.value = t('addAccount.enterPasswordOrWait')
      loading.value = false
    }
  }
}

onUnmounted(() => {
  pollHandle?.stop(); pollHandle = null
  stopCodeCountdown()
})
</script>

<template>
  <Modal :isOpen="isOpen" @close="handleClose" :title="loginMethod === 'code' ? t('addAccount.codeTitle') : t('addAccount.qrTitle')">
    <div class="space-y-4 pb-2">
      <!-- 登录方式分段切换 -->
      <div class="ui-segment" role="tablist" :aria-label="t('addAccount.loginMethod')">
        <button
          type="button"
          role="tab"
          class="ui-segment-btn"
          :class="loginMethod === 'code' ? 'ui-segment-btn-active' : ''"
          :aria-selected="loginMethod === 'code'"
          @click="loginMethod = 'code'"
        >
          <Phone class="w-3.5 h-3.5" />
          {{ t('accounts.codeLogin') }}
        </button>
        <button
          type="button"
          role="tab"
          class="ui-segment-btn"
          :class="loginMethod === 'qr' ? 'ui-segment-btn-active' : ''"
          :aria-selected="loginMethod === 'qr'"
          @click="loginMethod = 'qr'"
        >
          <QrCode class="w-3.5 h-3.5" />
          {{ t('accounts.qrLogin') }}
        </button>
      </div>

      <div v-if="error" class="ui-alert-error" role="alert">
        {{ error }}
      </div>

      <!-- Common Fields -->
      <div class="space-y-1.5">
        <label class="ui-label" for="add-account-name">{{ t('addAccount.accountName') }} <span class="text-rose-500">*</span></label>
        <input 
          id="add-account-name"
          v-model="form.account_name"
          type="text" 
          autocomplete="off"
          :placeholder="t('addAccount.accountNamePlaceholder')"
          class="ui-input"
        >
      </div>
      
      <div class="space-y-1.5">
        <label class="ui-label" for="add-account-remark">{{ t('addAccount.remark') }}</label>
        <input 
          id="add-account-remark"
          v-model="form.remark"
          type="text" 
          :placeholder="t('addAccount.remarkPlaceholder')"
          class="ui-input"
        >
      </div>

      <!-- Code specific fields -->
      <template v-if="loginMethod === 'code'">
        <div class="space-y-1.5">
          <label class="ui-label" for="add-account-phone">{{ t('addAccount.phone') }} <span class="text-rose-500">*</span></label>
          <input 
            id="add-account-phone"
            v-model="form.phone_number"
            type="tel" 
            autocomplete="tel"
            :placeholder="t('addAccount.phonePlaceholder')"
            class="ui-input"
          >
        </div>
        <div class="space-y-1.5">
          <label class="ui-label" for="add-account-code">{{ t('addAccount.verifyCode') }} <span class="text-rose-500">*</span></label>
          <div class="flex gap-2">
            <input 
              id="add-account-code"
              v-model="form.phone_code"
              type="text" 
              inputmode="numeric"
              autocomplete="one-time-code"
              :placeholder="t('addAccount.codePlaceholder')"
              class="ui-input flex-1"
            >
            <button 
              @click="handleSendCode"
              :disabled="loading || !form.account_name || !form.phone_number || codeCountdown > 0"
              class="ui-btn-secondary !px-4 !py-2 whitespace-nowrap"
            >
              {{ codeCountdown > 0 ? t('addAccount.resendIn', { s: codeCountdown }) : codeSent ? t('addAccount.resendCode') : t('addAccount.getCode') }}
            </button>
          </div>
        </div>
      </template>

      <!-- Cloud Password & Proxy for BOTH -->
      <div class="space-y-1.5">
        <label class="ui-label" for="add-account-2fa">{{ t('addAccount.cloudPassword') }}</label>
        <input 
          id="add-account-2fa"
          v-model="form.password"
          type="password" 
          autocomplete="new-password"
          :placeholder="t('addAccount.cloudPasswordPlaceholder')"
          class="ui-input"
        >
      </div>

      <div class="space-y-1.5">
        <label class="ui-label" for="add-account-proxy">{{ t('addAccount.proxy') }}</label>
        <input 
          id="add-account-proxy"
          v-model="form.proxy"
          type="text" 
          :placeholder="t('addAccount.proxyPlaceholder')"
          class="ui-input"
        >
      </div>

      <!-- QR specific block -->
      <div v-if="loginMethod === 'qr'" class="ui-form-section mt-2">
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
          <img v-if="qrImage" :src="qrImage" class="w-40 h-40" alt="" @error="handleQrImageError" />
          <div v-else class="flex flex-col items-center gap-2">
            <span class="text-sm text-gray-400">{{ qrLoadFailed ? t('addAccount.qrLoadFailed') : t('addAccount.qrArea') }}</span>
            <button
              v-if="qrLoadFailed"
              type="button"
              class="text-xs text-sky-600 dark:text-sky-400 hover:underline"
              :disabled="loading"
              @click="handleGetQr"
            >
              {{ t('addAccount.retry') }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <div class="w-full flex justify-end gap-3">
        <button 
          @click="handleClose"
          class="ui-btn-secondary !border-transparent !bg-transparent !px-5 !py-2"
        >
          {{ t('addAccount.cancel') }}
        </button>
        <button 
          @click="handleSave"
          :disabled="loading"
          class="ui-btn-primary !px-5 !py-2"
        >
          {{ loading ? t('addAccount.processing') : t('addAccount.confirmSave') }}
        </button>
      </div>
    </template>
  </Modal>
</template>
