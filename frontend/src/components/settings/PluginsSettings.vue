<script setup lang="ts">
/**
 * 自定义插件概览、演练调试与重载区块：
 * 1. 展示已挂载 Action 插件清单（名称、模式、描述、路径、参数 Schema）；
 * 2. 提供「测试演练」弹窗，免打卡即时输入测试文本单测插件逻辑并回显日志；
 * 3. 提供「重新加载」按钮，触发服务端重新扫描插件目录。
 */
import { ref, onMounted } from 'vue'
import { Puzzle, RefreshCw, Folder, Info, Play, CheckCircle2, AlertCircle, Clock } from 'lucide-vue-next'
import Modal from '../Modal.vue'
import {
  getPlugins,
  reloadPlugins,
  testPlugin,
  type PluginInfo,
  type PluginTestResponse,
} from '../../lib/api'
import { useI18n } from '../../composables/useI18n'
import { useToast } from '../../composables/useToast'
import { withToken } from '../../lib/api/core'

const { t } = useI18n()
const toast = useToast()

const plugins = ref<PluginInfo[]>([])
const loading = ref(false)
const reloadLoading = ref(false)

// 测试演练弹窗状态
const isTestModalOpen = ref(false)
const currentTestPlugin = ref<PluginInfo | null>(null)
const testInputText = ref('')
const testParams = ref<Record<string, unknown>>({})
const testRunning = ref(false)
const testResult = ref<PluginTestResponse | null>(null)

const loadPluginList = async () => {
  loading.value = true
  try {
    plugins.value = await withToken((token) => getPlugins(token)) ?? []
  } catch {
    // 允许离线或降级
  } finally {
    loading.value = false
  }
}

const handleReload = async () => {
  reloadLoading.value = true
  try {
    const res = await withToken((token) => reloadPlugins(token))
    if (!res) return
    plugins.value = res.plugins
    toast.success(t('settings.pluginsReloadSuccess', { count: res.count }))
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    toast.error(`${t('settings.pluginsReloadFailed')}: ${msg}`)
  } finally {
    reloadLoading.value = false
  }
}

const openTestModal = (plugin: PluginInfo) => {
  currentTestPlugin.value = plugin
  testResult.value = null

  // 设置智能示例输入
  if (plugin.name === 'math_solver') {
    testInputText.value = '请在 30 秒内输入 2*31 的答案'
  } else if (plugin.name === 'regex_reply') {
    testInputText.value = '本次验证码为：9527，请在 60 秒内输入'
  } else {
    testInputText.value = ''
  }

  // 初始化参数
  const initialParams: Record<string, unknown> = {}
  if (plugin.params_schema) {
    for (const field of plugin.params_schema) {
      if (field.default !== undefined) {
        initialParams[field.name] = field.default
      }
    }
  }
  testParams.value = initialParams
  isTestModalOpen.value = true
}

const runPluginTest = async () => {
  if (!currentTestPlugin.value) return
  testRunning.value = true
  testResult.value = null

  try {
    const res = await withToken((token) =>
      testPlugin(currentTestPlugin.value!.name, {
        text: testInputText.value,
        params: testParams.value,
      }, token),
    )
    if (!res) return
    testResult.value = res
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    testResult.value = {
      name: currentTestPlugin.value.name,
      success: false,
      handled: false,
      isolation: undefined,
      killed: false,
      logs: [`[error] 接口调用异常: ${msg}`],
      duration_ms: 0,
      error: msg,
    }
  } finally {
    testRunning.value = false
  }
}

onMounted(() => {
  void loadPluginList()
})
</script>

<template>
  <section class="ui-card p-6">
    <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex items-start justify-between gap-3">
      <div class="flex items-start gap-3 min-w-0">
        <span class="ui-section-icon" aria-hidden="true"><Puzzle class="w-3.5 h-3.5" /></span>
        <div class="min-w-0">
          <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.pluginsTitle') }}</h2>
          <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.pluginsDesc') }}</p>
        </div>
      </div>
      <button
        type="button"
        class="ui-btn-secondary shrink-0 !px-3 !py-1 !text-xs inline-flex items-center gap-1.5"
        :disabled="reloadLoading || loading"
        @click="handleReload"
      >
        <RefreshCw class="w-3.5 h-3.5" :class="reloadLoading ? 'animate-spin' : ''" />
        {{ reloadLoading ? t('settings.pluginsReloading') : t('settings.pluginsReload') }}
      </button>
    </div>

    <!-- 挂载目录与说明 -->
    <div class="mb-4 p-3 border border-sky-200/60 dark:border-sky-800/40 bg-sky-50/40 dark:bg-sky-500/5 text-xs text-gray-600 dark:text-gray-400 space-y-1">
      <div class="flex items-center gap-1.5 font-medium text-sky-700 dark:text-sky-300">
        <Folder class="w-3.5 h-3.5 shrink-0" />
        <span>{{ t('settings.pluginsMountTipTitle') }}</span>
      </div>
      <p class="text-[11px] leading-relaxed text-gray-500 dark:text-gray-400">
        {{ t('settings.pluginsMountTip') }}
      </p>
    </div>

    <!-- 插件清单 -->
    <div v-if="loading && !plugins.length" class="space-y-3">
      <div class="ui-skeleton h-12 w-full" />
      <div class="ui-skeleton h-12 w-full" />
    </div>

    <div v-else-if="!plugins.length" class="p-6 text-center border border-dashed border-gray-200 dark:border-gray-800 rounded text-xs text-gray-400">
      <Info class="w-5 h-5 mx-auto mb-2 text-gray-300 dark:text-gray-600" />
      <p>{{ t('settings.pluginsEmpty') }}</p>
    </div>

    <div v-else class="space-y-2.5">
      <div
        v-for="plugin in plugins"
        :key="plugin.name"
        class="p-3 border border-gray-100 dark:border-gray-800/60 bg-gray-50/60 dark:bg-white/[0.02] flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs transition-colors hover:border-gray-300 dark:hover:border-gray-700"
      >
        <div class="min-w-0 space-y-1">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="font-mono font-semibold text-gray-900 dark:text-gray-100 text-xs">
              {{ plugin.name }}
            </span>
            <span
              v-if="plugin.mode === 'reactive'"
              class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-sky-100 dark:bg-sky-950/80 text-sky-700 dark:text-sky-300 border border-sky-200 dark:border-sky-800/50"
            >
              {{ t('settings.pluginsReactive') }}
            </span>
            <span
              v-else
              class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-emerald-100 dark:bg-emerald-950/80 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/50"
            >
              {{ t('settings.pluginsActive') }}
            </span>
            <span
              v-if="plugin.params_schema && plugin.params_schema.length"
              class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300"
            >
              {{ plugin.params_schema.length }} {{ t('settings.pluginsParamsCount') }}
            </span>
          </div>
          <p class="text-gray-600 dark:text-gray-300 text-[11px] leading-relaxed">
            {{ plugin.description || t('settings.pluginsNoDesc') }}
          </p>
          <div v-if="plugin.source_path" class="text-[10px] text-gray-400 dark:text-gray-500 font-mono truncate max-w-lg">
            {{ plugin.source_path }}
          </div>
        </div>

        <div class="shrink-0 flex items-center gap-2">
          <button
            type="button"
            class="ui-btn-secondary !py-1 !px-2.5 !text-xs inline-flex items-center gap-1 text-sky-600 dark:text-sky-400 hover:text-sky-700"
            @click="openTestModal(plugin)"
          >
            <Play class="w-3 h-3 fill-current" />
            {{ t('settings.pluginsPlaygroundBtn') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 演练调试弹窗 -->
    <Modal
      :title="`${t('settings.pluginsPlaygroundTitle')}: ${currentTestPlugin?.name ?? ''}`"
      :is-open="isTestModalOpen"
      max-width-class="max-w-xl"
      @close="isTestModalOpen = false"
    >
      <div v-if="currentTestPlugin" class="space-y-4 text-xs">
        <p class="text-gray-500 dark:text-gray-400 text-[11px]">
          {{ currentTestPlugin.description }}
        </p>

        <!-- 模拟消息输入 -->
        <div class="space-y-1">
          <label class="font-medium text-gray-700 dark:text-gray-300">
            {{ t('settings.pluginsTestInputLabel') }}
          </label>
          <textarea
            v-model="testInputText"
            rows="3"
            class="ui-input !h-auto !py-2 !px-2.5 !text-xs w-full font-mono"
            :placeholder="t('settings.pluginsTestInputPlaceholder')"
          />
        </div>

        <!-- 参数配置表单 (若存在 schema) -->
        <div v-if="currentTestPlugin.params_schema && currentTestPlugin.params_schema.length" class="p-3 bg-gray-50/80 dark:bg-white/[0.02] border border-gray-200 dark:border-gray-800/80 rounded space-y-2">
          <div class="font-medium text-[11px] text-gray-700 dark:text-gray-300">
            {{ t('settings.pluginsTestParamsLabel') }}
          </div>
          <div
            v-for="field in currentTestPlugin.params_schema"
            :key="field.name"
            class="flex flex-col gap-1"
          >
            <div class="flex justify-between text-[10px] text-gray-500">
              <span>{{ field.label || field.name }}</span>
              <span class="font-mono text-gray-400">{{ field.name }}</span>
            </div>
            <label v-if="field.type === 'bool'" class="inline-flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                :checked="Boolean(testParams[field.name])"
                class="rounded text-sky-600 focus:ring-sky-500 h-3.5 w-3.5"
                @change="testParams[field.name] = ($event.target as HTMLInputElement).checked"
              />
              <span class="text-[11px] text-gray-600 dark:text-gray-300">
                {{ testParams[field.name] ? t('common.enabled') : t('common.disabled') }}
              </span>
            </label>
            <input
              v-else-if="field.type === 'int'"
              type="number"
              :value="testParams[field.name]"
              :placeholder="field.placeholder || String(field.default ?? '')"
              class="ui-input !h-8 !text-xs !px-2 w-full"
              @input="testParams[field.name] = Number(($event.target as HTMLInputElement).value)"
            />
            <input
              v-else
              type="text"
              :value="String(testParams[field.name] ?? '')"
              :placeholder="field.placeholder || String(field.default ?? '')"
              class="ui-input !h-8 !text-xs !px-2 w-full"
              @input="testParams[field.name] = ($event.target as HTMLInputElement).value"
            />
          </div>
        </div>

        <!-- 执行按钮 -->
        <div class="flex justify-end">
          <button
            type="button"
            class="ui-btn-primary !px-4 !py-1.5 !text-xs inline-flex items-center gap-1.5"
            :disabled="testRunning"
            @click="runPluginTest"
          >
            <RefreshCw v-if="testRunning" class="w-3.5 h-3.5 animate-spin" />
            <Play v-else class="w-3.5 h-3.5 fill-current" />
            {{ testRunning ? t('settings.pluginsTestRunning') : t('settings.pluginsRunTest') }}
          </button>
        </div>

        <!-- 测试结果回显 -->
        <div v-if="testResult" class="p-3 border rounded space-y-2.5 transition-all" :class="testResult.success && testResult.handled ? 'border-emerald-500/50 bg-emerald-50/20 dark:bg-emerald-950/20' : (testResult.error ? 'border-red-500/50 bg-red-50/20 dark:bg-red-950/20' : 'border-amber-500/50 bg-amber-50/20 dark:bg-amber-950/20')">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-1.5 font-medium">
              <CheckCircle2 v-if="testResult.success && testResult.handled" class="w-4 h-4 text-emerald-600 dark:text-emerald-400" />
              <AlertCircle v-else class="w-4 h-4 text-amber-600 dark:text-amber-400" />
              <span>
                {{ testResult.handled ? t('settings.pluginsHandledTrue') : (testResult.error ? t('settings.pluginsHandledError') : t('settings.pluginsHandledFalse')) }}
              </span>
              <span
                v-if="testResult.killed"
                class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-red-100 dark:bg-red-950/80 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800/50"
              >
                ⛔ {{ t('settings.pluginsHardKilled') }}
              </span>
            </div>
            <div class="flex items-center gap-1.5 text-[11px] text-gray-500 font-mono">
              <span
                v-if="testResult.isolation"
                class="px-1 py-0.5 rounded text-[10px] font-mono bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400"
              >
                {{ t('settings.pluginsIsolation') }}: {{ testResult.isolation }}
              </span>
              <Clock class="w-3 h-3" />
              <span>{{ testResult.duration_ms }} ms</span>
            </div>
          </div>

          <div v-if="testResult.reply_text !== undefined && testResult.reply_text !== null" class="p-2 bg-white/80 dark:bg-black/30 rounded border border-gray-200 dark:border-gray-800">
            <span class="text-[10px] text-gray-400 block mb-0.5">{{ t('settings.pluginsReplyOutput') }}</span>
            <div class="font-mono text-xs text-sky-600 dark:text-sky-300 font-semibold select-all">
              {{ testResult.reply_text }}
            </div>
          </div>

          <div v-if="testResult.logs && testResult.logs.length" class="space-y-1">
            <span class="text-[10px] text-gray-400 block">{{ t('settings.pluginsLogsLabel') }}</span>
            <div class="p-2 bg-gray-900 text-gray-200 rounded font-mono text-[11px] max-h-36 overflow-y-auto space-y-0.5 select-all">
              <div v-for="(log, idx) in testResult.logs" :key="idx" class="leading-relaxed">
                {{ log }}
              </div>
            </div>
          </div>
        </div>
      </div>
    </Modal>
  </section>
</template>
