<script setup lang="ts">
/**
 * JEV / 语义接口配置区块：
 * - 模式单选：官方接口（默认） / 自定义接口
 * - 官方模式：只显示 API Key（base url 用官方默认隐藏，模型名与超时放进高级折叠）
 * - 自定义模式：显示 Base URL（提示需包含 /v1）、API Key、模型名（默认 jev）
 * - 保存调 PATCH /semantic/config；测试连接调 POST /semantic/test
 * - 渲染状态行：✅ 连接成功 · 3.9s / ❌ 连接失败 · 401 · Invalid api key
 */
import { ref, onMounted } from 'vue'
import { Cpu, Eye, EyeOff, ChevronDown, ChevronUp } from 'lucide-vue-next'
import { useI18n } from '../../composables/useI18n'
import { useToast } from '../../composables/useToast'
import { getAuthToken } from '../../lib/api/core'
import {
  getSemanticConfig,
  updateSemanticConfig,
  testSemanticConnection,
  type SemanticConfig,
} from '../../lib/api/semantic'
import SettingsFieldHint from './SettingsFieldHint.vue'

const { t } = useI18n()
const toast = useToast()

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const revealKey = ref(false)
const showAdvanced = ref(false)

interface JevFormState {
  enabled: boolean
  mode: 'official' | 'custom'
  base_url: string
  model: string
  api_key: string
  timeout_seconds: number
  has_api_key: boolean
  api_key_masked: string
}

const form = ref<JevFormState>({
  enabled: true,
  mode: 'official',
  base_url: 'https://api.typesafe.ai/v1',
  model: 'jev-1.13.0',
  api_key: '',
  timeout_seconds: 8.0,
  has_api_key: false,
  api_key_masked: '',
})

interface TestResultState {
  type: 'success' | 'error'
  text: string
}

const testResult = ref<TestResultState | null>(null)

const setMode = (mode: 'official' | 'custom') => {
  form.value.mode = mode
  if (mode === 'official') {
    form.value.base_url = 'https://api.typesafe.ai/v1'
    if (form.value.model === 'jev' || !form.value.model) {
      form.value.model = 'jev-1.13.0'
    }
  } else {
    if (
      !form.value.base_url ||
      form.value.base_url === 'https://api.typesafe.ai/v1'
    ) {
      form.value.base_url = ''
    }
    if (form.value.model === 'jev-1.13.0' || !form.value.model) {
      form.value.model = 'jev'
    }
  }
}

const loadConfig = async () => {
  const token = getAuthToken()
  if (!token) return
  loading.value = true
  try {
    const data: SemanticConfig = await getSemanticConfig(token)
    form.value.enabled = data.enabled ?? true
    form.value.mode = data.mode || (data.base_url && data.base_url !== 'https://api.typesafe.ai/v1' ? 'custom' : 'official')
    form.value.base_url = data.base_url || 'https://api.typesafe.ai/v1'
    form.value.model = data.model || (form.value.mode === 'official' ? 'jev-1.13.0' : 'jev')
    form.value.timeout_seconds = data.timeout_seconds ?? 8.0
    form.value.has_api_key = data.has_api_key ?? false
    form.value.api_key_masked = data.api_key_masked ?? ''
    form.value.api_key = ''
  } catch {
    // 忽略加载异常，采用默认值
  } finally {
    loading.value = false
  }
}

const handleSave = async (showSuccessToast = true): Promise<boolean> => {
  const token = getAuthToken()
  if (!token) return false
  saving.value = true
  try {
    const isOfficial = form.value.mode === 'official'
    const patch: Record<string, any> = {
      enabled: form.value.enabled,
      mode: form.value.mode,
      base_url: isOfficial ? 'https://api.typesafe.ai/v1' : form.value.base_url.trim(),
      model: form.value.model.trim() || (isOfficial ? 'jev-1.13.0' : 'jev'),
      timeout_seconds: Math.max(1, Math.min(30, Number(form.value.timeout_seconds) || 8.0)),
    }
    if (form.value.api_key.trim()) {
      patch.api_key = form.value.api_key.trim()
    }
    const updated = await updateSemanticConfig(patch, token)
    form.value.has_api_key = updated.has_api_key
    form.value.api_key_masked = updated.api_key_masked
    form.value.api_key = ''
    if (showSuccessToast) {
      toast.success(t('settings.jevSaveSuccess'))
    }
    return true
  } catch (err: any) {
    toast.error(err?.message || t('settings.jevSaveFailed'))
    return false
  } finally {
    saving.value = false
  }
}

const handleTest = async () => {
  const token = getAuthToken()
  if (!token) return

  testing.value = true
  testResult.value = null

  try {
    // 保存后「测试连接」：先保存当前变更，确保测试走保存的参数
    const saved = await handleSave(false)
    if (!saved) {
      testResult.value = {
        type: 'error',
        text: `❌ ${t('settings.jevConnectFailed')} · ${t('settings.jevSaveFailed')}`,
      }
      return
    }

    const res = await testSemanticConnection({}, token)
    if (res.success && res.status === 'ok') {
      const seconds = (res.elapsed_ms / 1000).toFixed(1)
      testResult.value = {
        type: 'success',
        text: `✅ ${t('settings.jevConnected')} · ${seconds}s`,
      }
    } else {
      const parts: string[] = [`❌ ${t('settings.jevConnectFailed')}`]
      if (res.http_status) {
        parts.push(String(res.http_status))
      } else if (res.reason_code) {
        parts.push(res.reason_code)
      }
      if (res.error_message) {
        parts.push(res.error_message)
      }
      testResult.value = {
        type: 'error',
        text: parts.join(' · '),
      }
    }
  } catch (err: any) {
    testResult.value = {
      type: 'error',
      text: `❌ ${t('settings.jevConnectFailed')} · ${err?.message || 'Network error'}`,
    }
  } finally {
    testing.value = false
  }
}

onMounted(() => {
  loadConfig()
})
</script>

<template>
  <section class="ui-card p-6">
    <!-- 头部区：标题、说明与右上角测试连接按钮 -->
    <div class="mb-6 border-b border-[var(--sp-border)] pb-3 flex items-center justify-between gap-3">
      <div class="flex items-start gap-3 min-w-0">
        <span class="ui-section-icon" aria-hidden="true"><Cpu class="w-3.5 h-3.5" /></span>
        <div class="min-w-0">
          <h2 class="text-base font-semibold text-[var(--sp-text)]">{{ t('settings.jevConfig') }}</h2>
          <p class="text-[10px] text-[var(--sp-text-muted)] mt-1">{{ t('settings.jevDesc') }}</p>
        </div>
      </div>
      <button
        type="button"
        class="ui-btn-secondary !px-3 !py-1 !text-xs shrink-0"
        :disabled="loading || saving || testing"
        @click="handleTest"
      >
        {{ testing ? t('settings.jevTesting') : t('settings.jevTest') }}
      </button>
    </div>

    <!-- 表单区 -->
    <div class="space-y-5">
      <!-- 1. 模式单选：官方接口（默认） / 自定义接口 -->
      <div class="space-y-1.5">
        <label class="ui-label">{{ t('settings.jevMode') }}</label>
        <div class="flex flex-wrap items-center gap-6 pt-1">
          <label class="flex items-center gap-2 cursor-pointer text-xs text-[var(--sp-text)]">
            <input
              type="radio"
              name="jev-mode"
              value="official"
              :checked="form.mode === 'official'"
              @change="setMode('official')"
              class="text-[var(--sp-primary)] focus:ring-[var(--sp-primary)]"
            />
            <span>{{ t('settings.jevModeOfficial') }}</span>
          </label>
          <label class="flex items-center gap-2 cursor-pointer text-xs text-[var(--sp-text)]">
            <input
              type="radio"
              name="jev-mode"
              value="custom"
              :checked="form.mode === 'custom'"
              @change="setMode('custom')"
              class="text-[var(--sp-primary)] focus:ring-[var(--sp-primary)]"
            />
            <span>{{ t('settings.jevModeCustom') }}</span>
          </label>
        </div>
      </div>

      <!-- 2. 自定义模式特有：Base URL 输入框 + 包含 /v1 提示 -->
      <div v-if="form.mode === 'custom'" class="space-y-1.5">
        <label class="ui-label" for="jev-base-url">{{ t('settings.jevBaseUrl') }}</label>
        <input
          id="jev-base-url"
          v-model="form.base_url"
          type="text"
          :placeholder="t('settings.jevBaseUrlPlaceholder')"
          class="ui-input"
        />
        <p class="text-[11px] text-[var(--sp-text-muted)] leading-relaxed">
          {{ t('settings.jevBaseUrlHint') }}
        </p>
      </div>

      <!-- 3. API Key 输入框（官方与自定义模式通用） -->
      <div class="space-y-1.5">
        <label class="ui-label" for="jev-api-key">{{ t('settings.jevApiKey') }}</label>
        <div class="relative">
          <input
            id="jev-api-key"
            v-model="form.api_key"
            :type="revealKey ? 'text' : 'password'"
            :placeholder="form.has_api_key ? (form.api_key_masked ? t('settings.jevApiKeyKeepHint') + ' (' + form.api_key_masked + ')' : t('settings.jevApiKeyKeepHint')) : t('settings.jevApiKeyPlaceholder')"
            class="ui-input pr-10"
          />
          <button
            type="button"
            class="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-[var(--sp-text-muted)] hover:text-[var(--sp-text-secondary)] dark:hover:text-[var(--sp-text)]"
            :aria-label="revealKey ? t('settings.hideSecret') : t('settings.showSecret')"
            @click="revealKey = !revealKey"
          >
            <EyeOff v-if="revealKey" class="w-4 h-4" />
            <Eye v-else class="w-4 h-4" />
          </button>
        </div>
      </div>

      <!-- 4. 自定义模式：模型名直接展示 -->
      <div v-if="form.mode === 'custom'" class="space-y-1.5">
        <label class="ui-label" for="jev-model">{{ t('settings.jevModel') }}</label>
        <input
          id="jev-model"
          v-model="form.model"
          type="text"
          :placeholder="t('settings.jevModelPlaceholder')"
          class="ui-input"
        />
      </div>

      <!-- 5. 高级折叠：官方模式下模型名，以及两个模式通用的超时设置 -->
      <div class="pt-2 border-t border-[var(--sp-border)]">
        <button
          type="button"
          class="flex items-center gap-1.5 text-xs text-[var(--sp-text-muted)] hover:text-[var(--sp-text)] font-medium cursor-pointer"
          @click="showAdvanced = !showAdvanced"
        >
          <ChevronDown v-if="!showAdvanced" class="w-3.5 h-3.5" />
          <ChevronUp v-else class="w-3.5 h-3.5" />
          <span>{{ t('settings.jevAdvanced') }}</span>
        </button>

        <div v-show="showAdvanced" class="mt-3 space-y-4 pl-1">
          <!-- 官方模式模型名放进高级折叠 -->
          <div v-if="form.mode === 'official'" class="space-y-1.5">
            <label class="ui-label" for="jev-model-adv">{{ t('settings.jevModel') }}</label>
            <input
              id="jev-model-adv"
              v-model="form.model"
              type="text"
              placeholder="jev-1.13.0"
              class="ui-input"
            />
          </div>

          <!-- 超时调整：默认 8.0s，校验范围 1–30s -->
          <div class="space-y-1.5">
            <label class="ui-label" for="jev-timeout">{{ t('settings.jevTimeout') }}</label>
            <input
              id="jev-timeout"
              v-model.number="form.timeout_seconds"
              type="number"
              min="1"
              max="30"
              step="0.5"
              placeholder="8.0"
              class="ui-input"
            />
            <SettingsFieldHint :text="t('settings.jevTimeoutHint')" />
          </div>
        </div>
      </div>

      <!-- 6. 测试结果状态行展示（如：✅ 连接成功 · 3.9s 或 ❌ 连接失败 · 401 · Invalid api key） -->
      <div
        v-if="testResult"
        class="p-2.5 rounded-[var(--sp-radius-md)] text-xs flex items-center gap-2"
        :class="testResult.type === 'success'
          ? 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border border-emerald-500/20'
          : 'bg-red-500/10 text-red-700 dark:text-red-300 border border-red-500/20'"
        role="status"
      >
        <span class="font-medium font-mono text-xs">{{ testResult.text }}</span>
      </div>

      <!-- 7. 保存按钮 -->
      <div class="pt-2">
        <button
          type="button"
          class="ui-btn-primary w-full py-2.5 cursor-pointer"
          :disabled="loading || saving || testing"
          @click="() => handleSave(true)"
        >
          {{ saving ? t('common.saving') : t('settings.jevSave') }}
        </button>
      </div>
    </div>
  </section>
</template>
