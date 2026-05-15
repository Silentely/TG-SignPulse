<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getGlobalSettings, saveGlobalSettings, getTelegramConfig, saveTelegramConfig, resetTelegramConfig, getAIConfig, saveAIConfig, testAIConnection, exportAllConfigs, importAllConfigs } from '../lib/api'
import { useI18n } from '../composables/useI18n'

const { t } = useI18n()

const settings = ref({
  checkInterval: '',
  logDays: 7,
  dataDir: '',
  proxy: '',
  botEnabled: false,
  botLoginNotify: false,
  botTaskFailure: false,
  botToken: '',
  botChatId: '',
  botThreadId: ''
})

const tgConfig = ref({
  api_id: '',
  api_hash: ''
})

const aiConfig = ref({
  base_url: '',
  model: '',
  api_key: ''
})

const loading = ref(false)
const tgLoading = ref(false)
const aiLoading = ref(false)
const dataLoading = ref(false)
const toastMsg = ref('')

const showToast = (msg: string) => {
  toastMsg.value = msg
  setTimeout(() => toastMsg.value = '', 3000)
}

onMounted(async () => {
  const token = localStorage.getItem('tg-signer-token') || ''
  if (!token) return

  try {
    const [res, tgRes, aiRes] = await Promise.all([
      getGlobalSettings(token),
      getTelegramConfig(token).catch(() => null),
      getAIConfig(token).catch(() => null)
    ])
    settings.value.checkInterval = res.sign_interval ? String(res.sign_interval) : ''
    settings.value.logDays = res.log_retention_days || 7
    settings.value.dataDir = res.data_dir || ''
    settings.value.proxy = res.global_proxy || ''
    settings.value.botEnabled = res.telegram_bot_notify_enabled || false
    settings.value.botLoginNotify = res.telegram_bot_login_notify_enabled || false
    settings.value.botTaskFailure = res.telegram_bot_task_failure_enabled || false
    settings.value.botToken = res.telegram_bot_token || ''
    settings.value.botChatId = res.telegram_bot_chat_id || ''
    settings.value.botThreadId = res.telegram_bot_message_thread_id ? String(res.telegram_bot_message_thread_id) : ''

    if (tgRes && tgRes.is_custom) {
      tgConfig.value.api_id = tgRes.api_id
      tgConfig.value.api_hash = tgRes.api_hash
    }

    if (aiRes && aiRes.has_config) {
      aiConfig.value.base_url = aiRes.base_url || ''
      aiConfig.value.model = aiRes.model || ''
    }

  } catch (e) {
    console.error('Failed to load settings', e)
  }
})

const saveSettings = async () => {
  const token = localStorage.getItem('tg-signer-token') || ''
  if (!token) return

  loading.value = true
  try {
    await saveGlobalSettings(token, {
      sign_interval: settings.value.checkInterval ? parseInt(settings.value.checkInterval) : null,
      log_retention_days: settings.value.logDays,
      data_dir: settings.value.dataDir || null,
      global_proxy: settings.value.proxy || null,
    })
    showToast(t('settings.saveSuccess'))
  } catch (e: any) {
    showToast(e.message || t('settings.saveFailed'))
  } finally {
    loading.value = false
  }
}

const botLoading = ref(false)

const saveBotSettings = async () => {
  const token = localStorage.getItem('tg-signer-token') || ''
  if (!token) return

  botLoading.value = true
  try {
    await saveGlobalSettings(token, {
      telegram_bot_notify_enabled: settings.value.botEnabled,
      telegram_bot_login_notify_enabled: settings.value.botLoginNotify,
      telegram_bot_task_failure_enabled: settings.value.botTaskFailure,
      telegram_bot_token: settings.value.botToken || null,
      telegram_bot_chat_id: settings.value.botChatId || null,
      telegram_bot_message_thread_id: settings.value.botThreadId ? parseInt(settings.value.botThreadId) : null,
    })
    showToast(t('settings.saveSuccess'))
  } catch (e: any) {
    showToast(e.message || t('settings.saveFailed'))
  } finally {
    botLoading.value = false
  }
}

const saveTgConfig = async () => {
  const token = localStorage.getItem('tg-signer-token') || ''
  tgLoading.value = true
  try {
    await saveTelegramConfig(token, { api_id: tgConfig.value.api_id, api_hash: tgConfig.value.api_hash })
    showToast(t('settings.tgConfigSaved'))
  } catch (e: any) {
    showToast(e.message || t('settings.saveFailed'))
  } finally {
    tgLoading.value = false
  }
}

const resetTgConfig = async () => {
  const token = localStorage.getItem('tg-signer-token') || ''
  if (!confirm(t('settings.resetConfirm'))) return
  tgLoading.value = true
  try {
    await resetTelegramConfig(token)
    tgConfig.value.api_id = ''
    tgConfig.value.api_hash = ''
    showToast(t('settings.resetSuccess'))
  } catch (e: any) {
    showToast(e.message || t('settings.resetFailed'))
  } finally {
    tgLoading.value = false
  }
}

const saveAiConfig = async () => {
  const token = localStorage.getItem('tg-signer-token') || ''
  aiLoading.value = true
  try {
    await saveAIConfig(token, {
      base_url: aiConfig.value.base_url || undefined,
      model: aiConfig.value.model || undefined,
      api_key: aiConfig.value.api_key || undefined
    })
    showToast(t('settings.aiConfigSaved'))
  } catch (e: any) {
    showToast(e.message || t('settings.saveFailed'))
  } finally {
    aiLoading.value = false
  }
}

const testAi = async () => {
  const token = localStorage.getItem('tg-signer-token') || ''
  aiLoading.value = true
  try {
    const res = await testAIConnection(token)
    showToast(res.message || t('settings.testSuccess'))
  } catch (e: any) {
    showToast(e.message || t('settings.testFailed'))
  } finally {
    aiLoading.value = false
  }
}

const handleExport = async () => {
  const token = localStorage.getItem('tg-signer-token') || ''
  dataLoading.value = true
  try {
    const jsonStr = await exportAllConfigs(token)
    const blob = new Blob([jsonStr], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `tg-signpulse-export-${new Date().toISOString().split('T')[0]}.json`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    showToast(t('settings.exportSuccess'))
  } catch (e: any) {
    showToast(e.message || t('settings.exportFailed'))
  } finally {
    dataLoading.value = false
  }
}

const handleImport = async (e: Event) => {
  const target = e.target as HTMLInputElement
  if (!target.files || !target.files[0]) return
  const file = target.files[0]
  const reader = new FileReader()
  reader.onload = async (ev) => {
    const jsonStr = ev.target?.result as string
    const token = localStorage.getItem('tg-signer-token') || ''
    dataLoading.value = true
    try {
      await importAllConfigs(token, jsonStr, true)
      showToast(t('settings.importSuccess'))
    } catch (err: any) {
      showToast(err.message || t('settings.importFailed'))
    } finally {
      dataLoading.value = false
    }
  }
  reader.readAsText(file)
}
</script>

<template>
  <div class="max-w-7xl pb-10">
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      
      <!-- 通用设置 + Telegram API（左列） -->
      <div class="flex flex-col gap-6">
        <!-- 通用设置 -->
        <section class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 p-6">
          <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-center justify-between">
            <div>
              <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.general') }}</h2>
              <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.generalDesc') }}</p>
            </div>
            <span v-if="loading" class="text-xs text-gray-500">{{ t('settings.saving') }}</span>
          </div>
          <div class="space-y-5">
            <div class="space-y-1.5">
              <label class="text-xs text-gray-500 block">{{ t('settings.logRetention') }}</label>
              <input v-model="settings.logDays" type="number" class="w-full bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:bg-white dark:focus:bg-gray-800">
            </div>
            <div class="space-y-1.5">
              <label class="text-xs text-gray-500 block">{{ t('settings.dataDir') }}</label>
              <input v-model="settings.dataDir" type="text" placeholder="/data" class="w-full bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:bg-white dark:focus:bg-gray-800 placeholder:text-gray-400">
            </div>
            <div class="space-y-1.5">
              <label class="text-xs text-gray-500 block">{{ t('settings.proxy') }}</label>
              <input v-model="settings.proxy" type="text" placeholder="socks5://127.0.0.1:1080" class="w-full bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:bg-white dark:focus:bg-gray-800 placeholder:text-gray-400">
            </div>
            <div class="pt-2">
              <button @click="saveSettings" :disabled="loading" class="w-full py-2 text-sm bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-950 hover:bg-gray-800 dark:hover:bg-white transition-colors disabled:opacity-50">{{ loading ? t('settings.saving') : t('settings.saveGeneral') }}</button>
            </div>
          </div>
        </section>

        <!-- Telegram API -->
        <section class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 p-6 flex-1">
          <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-center justify-between">
            <div>
              <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.tgApi') }}</h2>
              <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.tgApiDesc') }}</p>
            </div>
            <button @click="resetTgConfig" :disabled="tgLoading" class="px-3 py-1 text-xs text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-gray-800/60 transition-colors disabled:opacity-50">{{ t('settings.resetDefault') }}</button>
          </div>
          <div class="space-y-5">
            <div class="space-y-1.5">
              <label class="text-xs text-gray-500 block">API ID</label>
              <input v-model="tgConfig.api_id" type="password" class="w-full bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:bg-white dark:focus:bg-gray-800">
            </div>
            <div class="space-y-1.5">
              <label class="text-xs text-gray-500 block">API Hash</label>
              <input v-model="tgConfig.api_hash" type="password" class="w-full bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:bg-white dark:focus:bg-gray-800">
            </div>
            <div class="p-3 bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-800/50 text-xs text-amber-700 dark:text-amber-400 leading-relaxed">
              <p>由于默认 API 可能存在大量自动化操作，如果该 API 的请求账号出现多个被封可能影响整个 API 权重！为了你的账号安全，我强烈建议你申请一个自己的开发者 API，申请地址：<a href="https://my.telegram.org/auth" target="_blank" rel="noopener" class="underline hover:text-amber-900 dark:hover:text-amber-300 font-medium">https://my.telegram.org/auth</a></p>
            </div>
            <div class="pt-2">
              <button @click="saveTgConfig" :disabled="tgLoading || !tgConfig.api_id || !tgConfig.api_hash" class="w-full py-2 text-sm bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-950 hover:bg-gray-800 dark:hover:bg-white transition-colors disabled:opacity-50">{{ tgLoading ? t('settings.saving') : t('settings.saveTgConfig') }}</button>
            </div>
          </div>
        </section>
      </div>

      <!-- AI 配置 + Bot 通知（右列） -->
      <div class="flex flex-col gap-6">
        <!-- AI 模型配置 -->
        <section class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 p-6">
          <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-center justify-between">
            <div>
              <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.aiConfig') }}</h2>
              <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.aiDesc') }}</p>
            </div>
            <button @click="testAi" :disabled="aiLoading" class="px-3 py-1 text-xs text-gray-500 hover:text-gray-900 dark:hover:text-gray-100 bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-gray-800/60 transition-colors disabled:opacity-50">{{ t('settings.testConnection') }}</button>
          </div>
          <div class="space-y-5">
            <div class="space-y-1.5">
              <label class="text-xs text-gray-500 block">{{ t('settings.apiBaseUrl') }}</label>
              <input v-model="aiConfig.base_url" type="text" placeholder="https://api.openai.com/v1" class="w-full bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:bg-white dark:focus:bg-gray-800">
            </div>
            <div class="space-y-1.5">
              <label class="text-xs text-gray-500 block">{{ t('settings.model') }}</label>
              <input v-model="aiConfig.model" type="text" placeholder="gpt-4" class="w-full bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:bg-white dark:focus:bg-gray-800">
            </div>
            <div class="space-y-1.5">
              <label class="text-xs text-gray-500 block">{{ t('settings.apiKey') }}</label>
              <input v-model="aiConfig.api_key" type="password" placeholder="sk-..." class="w-full bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:bg-white dark:focus:bg-gray-800">
            </div>
            <div class="pt-2">
              <button @click="saveAiConfig" :disabled="aiLoading" class="w-full py-2 text-sm bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-950 hover:bg-gray-800 dark:hover:bg-white transition-colors disabled:opacity-50">{{ aiLoading ? t('settings.saving') : t('settings.saveAiConfig') }}</button>
            </div>
          </div>
        </section>

        <!-- Telegram 机器人通知 -->
        <section class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 p-6 flex-1">
          <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-center justify-between">
            <div>
              <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.botNotify') }}</h2>
              <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.botDesc') }}</p>
            </div>
            <button 
              @click="settings.botEnabled = !settings.botEnabled"
              class="relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors focus:outline-none"
              :class="settings.botEnabled ? 'bg-blue-500' : 'bg-gray-300 dark:bg-gray-700'"
            >
              <span class="inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform" :class="settings.botEnabled ? 'translate-x-4' : 'translate-x-1'" />
            </button>
          </div>

          <div class="space-y-5">
            <div class="space-y-1.5">
              <label class="text-xs text-gray-500 block">{{ t('settings.botToken') }}</label>
              <input v-model="settings.botToken" type="password" placeholder="123456:ABC-DEF..." class="w-full bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:bg-white dark:focus:bg-gray-800">
            </div>
            <div class="space-y-1.5">
              <label class="text-xs text-gray-500 block">{{ t('settings.targetChatId') }}</label>
              <input v-model="settings.botChatId" type="text" placeholder="-1001234567890" class="w-full bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:bg-white dark:focus:bg-gray-800">
            </div>
            <div class="space-y-1.5">
              <label class="text-xs text-gray-500 block">{{ t('settings.threadId') }}</label>
              <input v-model="settings.botThreadId" type="text" :placeholder="t('settings.threadIdPlaceholder')" class="w-full bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-transparent text-gray-900 dark:text-gray-200 px-3 py-2 text-sm outline-none transition-colors focus:bg-white dark:focus:bg-gray-800">
            </div>
            <div class="flex flex-wrap gap-x-6 gap-y-3 pt-2">
              <label class="flex items-center gap-2 cursor-pointer group">
                <input v-model="settings.botLoginNotify" type="checkbox" class="w-4 h-4 text-gray-900 dark:text-gray-100 bg-gray-100 border-gray-300 rounded focus:ring-0 dark:bg-gray-800 dark:border-gray-600">
                <span class="text-sm text-gray-700 dark:text-gray-300 group-hover:text-gray-900 dark:group-hover:text-gray-100 transition-colors">{{ t('settings.loginFailNotify') }}</span>
              </label>
              <label class="flex items-center gap-2 cursor-pointer group">
                <input v-model="settings.botTaskFailure" type="checkbox" class="w-4 h-4 text-gray-900 dark:text-gray-100 bg-gray-100 border-gray-300 rounded focus:ring-0 dark:bg-gray-800 dark:border-gray-600">
                <span class="text-sm text-gray-700 dark:text-gray-300 group-hover:text-gray-900 dark:group-hover:text-gray-100 transition-colors">{{ t('settings.taskFailNotify') }}</span>
              </label>
            </div>
            <div class="pt-2">
              <button @click="saveBotSettings" :disabled="botLoading" class="w-full py-2 text-sm bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-950 hover:bg-gray-800 dark:hover:bg-white transition-colors disabled:opacity-50">{{ botLoading ? t('settings.saving') : t('settings.saveChanges') }}</button>
            </div>
          </div>
        </section>
      </div>

      <!-- 数据管理（全宽） -->
      <section class="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 p-6 lg:col-span-2">
        <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-center justify-between">
          <div>
            <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.dataManagement') }}</h2>
            <p class="text-xs text-gray-500 mt-1">{{ t('settings.dataManagementDesc') }}</p>
          </div>
        </div>
        <div class="flex flex-col sm:flex-row gap-4 max-w-lg">
          <button 
            @click="handleExport"
            :disabled="dataLoading"
            class="flex-1 px-4 py-2 text-sm bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-950 hover:bg-gray-800 dark:hover:bg-white transition-colors disabled:opacity-50"
          >
            {{ dataLoading ? t('settings.processing') : t('settings.exportJson') }}
          </button>

          <div class="relative flex-1">
            <input 
              type="file" 
              accept="application/json" 
              @change="handleImport"
              class="absolute inset-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-not-allowed"
              :disabled="dataLoading"
            />
            <button 
              :disabled="dataLoading"
              class="w-full px-4 py-2 text-sm text-gray-700 dark:text-gray-200 bg-gray-50 dark:bg-gray-950 border border-gray-200 dark:border-gray-800/60 hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors disabled:opacity-50"
            >
              {{ t('settings.importJson') }}
            </button>
          </div>
        </div>
      </section>

    </div>

    <!-- Toast Notification -->
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="opacity-0 translate-y-2"
      enter-to-class="opacity-100 translate-y-0"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="opacity-100 translate-y-0"
      leave-to-class="opacity-0 translate-y-2"
    >
      <div v-if="toastMsg" class="fixed bottom-10 right-10 bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-900 px-4 py-2 text-sm shadow-xl z-50">
        {{ toastMsg }}
      </div>
    </Transition>
  </div>
</template>
