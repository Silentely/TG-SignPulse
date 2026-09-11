<script setup lang="ts">
/**
 * 自定义插件管理与全生命周期开发中心：
 * 1. 展示已挂载 Action 插件清单（名称、模式、描述、路径、版本、更新日期、作者、参数 Schema、启用/停用状态）；
 * 2. 提供插件软开关（动态启用/停用），无需修改或移动文件；
 * 3. 提供「查看源码」只读代码抽屉与一键复制功能；
 * 4. 提供「插件调试」弹窗，免打卡即时输入测试文本单测插件逻辑，支持回显表情表态 (Reactions) 与运行日志；
 * 5. 提供自定义插件的「安全删除」功能（官方内置插件受保护不可删除）；
 * 6. 提供「新建插件」在线模板脚手架快速生成能力；
 * 7. 提供面向开发者的「开发参考」指导指南；
 * 8. 支持 URL 查询参数 (?testPlugin=xxx&testInput=yyy) 快捷唤起调试台。
 */
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import {
  Puzzle,
  RefreshCw,
  Folder,
  Info,
  Play,
  CheckCircle2,
  AlertCircle,
  Clock,
  Power,
  Code,
  Trash2,
  Plus,
  BookOpen,
  Copy,
  Check,
} from 'lucide-vue-next'
import Modal from '../Modal.vue'
import {
  getPlugins,
  reloadPlugins,
  togglePlugin,
  testPlugin,
  getPluginSource,
  deletePlugin,
  createPlugin,
  type PluginInfo,
  type PluginTestResponse,
  type CreatePluginRequest,
} from '../../lib/api'
import { useI18n } from '../../composables/useI18n'
import { useToast } from '../../composables/useToast'
import { useConfirm } from '../../composables/useConfirm'
import { withToken } from '../../lib/api/core'

const { t } = useI18n()
const toast = useToast()
const route = useRoute()
const { confirm } = useConfirm()

const plugins = ref<PluginInfo[]>([])
const loading = ref(false)
const reloadLoading = ref(false)
const togglingPluginName = ref<string | null>(null)
const deletingPluginName = ref<string | null>(null)

// 源码查看弹窗状态
const isSourceModalOpen = ref(false)
const currentSourcePlugin = ref<PluginInfo | null>(null)
const sourceCode = ref('')
const sourceLoading = ref(false)
const sourceCopied = ref(false)

// 调试弹窗状态
const isTestModalOpen = ref(false)
const currentTestPlugin = ref<PluginInfo | null>(null)
const testInputText = ref('')
const testParams = ref<Record<string, unknown>>({})
const testRunning = ref(false)
const testResult = ref<PluginTestResponse | null>(null)

// 新建插件弹窗状态
const isCreateModalOpen = ref(false)
const createLoading = ref(false)
const createForm = ref<CreatePluginRequest>({
  name: '',
  mode: 'reactive',
  template: 'basic_reactive',
  description: '',
  author: '',
  version: '1.0.0',
})

// 开发者指南弹窗状态
const isDevGuideOpen = ref(false)

const checkRouteForTestPlugin = () => {
  const targetName = route.query.testPlugin as string | undefined
  if (!targetName) return
  const found = plugins.value.find((p) => p.name === targetName)
  if (found) {
    openTestModal(found)
    const customInput = route.query.testInput as string | undefined
    if (customInput) {
      testInputText.value = customInput
    }
  }
}

const loadPluginList = async () => {
  loading.value = true
  try {
    plugins.value = await withToken((token) => getPlugins(token)) ?? []
    checkRouteForTestPlugin()
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

const handleToggle = async (plugin: PluginInfo) => {
  togglingPluginName.value = plugin.name
  try {
    const res = await withToken((token) => togglePlugin(plugin.name, token))
    if (!res) return
    plugin.enabled = res.enabled
    toast.success(
      res.enabled
        ? t('settings.pluginEnabledSuccess')
        : t('settings.pluginDisabledSuccess'),
    )
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    toast.error(`${t('settings.pluginToggleFailed')}: ${msg}`)
  } finally {
    togglingPluginName.value = null
  }
}

// 查看源码
const openSourceModal = async (plugin: PluginInfo) => {
  currentSourcePlugin.value = plugin
  sourceCode.value = ''
  sourceCopied.value = false
  isSourceModalOpen.value = true
  sourceLoading.value = true

  try {
    const res = await withToken((token) => getPluginSource(plugin.name, token))
    if (res) {
      sourceCode.value = res.source
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    toast.error(`${t('settings.pluginsSourceLoading')}: ${msg}`)
  } finally {
    sourceLoading.value = false
  }
}

const copySourceCode = async () => {
  if (!sourceCode.value) return
  try {
    await navigator.clipboard.writeText(sourceCode.value)
    sourceCopied.value = true
    toast.success(t('settings.pluginsSourceCopied'))
    setTimeout(() => {
      sourceCopied.value = false
    }, 2000)
  } catch {
    toast.error(t('settings.pluginsSourceCopyFailed'))
  }
}

// 删除自定义插件
const handleDelete = async (plugin: PluginInfo) => {
  if (plugin.builtin) return
  const confirmed = await confirm({
    title: t('settings.pluginsDeleteBtn'),
    message: t('settings.pluginsDeleteConfirm', { name: plugin.name }),
    danger: true,
  })
  if (!confirmed) return

  deletingPluginName.value = plugin.name
  try {
    const res = await withToken((token) => deletePlugin(plugin.name, token))
    if (res?.success) {
      toast.success(t('settings.pluginsDeleteSuccess', { name: plugin.name }))
      await loadPluginList()
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    toast.error(`${t('settings.pluginsDeleteFailed')}: ${msg}`)
  } finally {
    deletingPluginName.value = null
  }
}

// 新建插件
const openCreateModal = () => {
  createForm.value = {
    name: '',
    mode: 'reactive',
    template: 'basic_reactive',
    description: '',
    author: '',
    version: '1.0.0',
  }
  isCreateModalOpen.value = true
}

const handleTemplateChange = () => {
  if (createForm.value.template === 'basic_active') {
    createForm.value.mode = 'active'
  } else {
    createForm.value.mode = 'reactive'
  }
}

const submitCreatePlugin = async () => {
  const name = createForm.value.name.trim()
  if (!name || !/^[a-zA-Z0-9_]{3,32}$/.test(name)) {
    toast.error(t('settings.pluginsCreateNamePlaceholder'))
    return
  }

  createLoading.value = true
  try {
    const res = await withToken((token) =>
      createPlugin(
        {
          ...createForm.value,
          name,
        },
        token,
      ),
    )
    if (res) {
      toast.success(t('settings.pluginsCreateSuccess', { name: res.name }))
      isCreateModalOpen.value = false
      await loadPluginList()
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    toast.error(`${t('settings.pluginsCreateFailed')}: ${msg}`)
  } finally {
    createLoading.value = false
  }
}

// 调试弹窗
const openTestModal = (plugin: PluginInfo) => {
  currentTestPlugin.value = plugin
  testResult.value = null

  if (plugin.name === 'math_solver') {
    testInputText.value = '请在 30 秒内输入 2*31 的答案'
  } else if (plugin.name === 'regex_reply') {
    testInputText.value = '本次验证码为：9527，请在 60 秒内输入'
  } else {
    testInputText.value = ''
  }

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
      testPlugin(
        currentTestPlugin.value!.name,
        {
          text: testInputText.value,
          params: testParams.value,
        },
        token,
      ),
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
    <div class="mb-6 border-b border-gray-200 dark:border-gray-800/60 pb-3 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
      <div class="flex items-start gap-3 min-w-0">
        <span class="ui-section-icon" aria-hidden="true"><Puzzle class="w-3.5 h-3.5" /></span>
        <div class="min-w-0">
          <h2 class="text-base font-medium text-gray-900 dark:text-gray-100">{{ t('settings.pluginsTitle') }}</h2>
          <p class="text-[10px] text-gray-500 mt-1">{{ t('settings.pluginsDesc') }}</p>
        </div>
      </div>
      <div class="flex items-center gap-2 flex-wrap shrink-0">
        <button
          type="button"
          class="ui-btn-primary shrink-0 !px-3 !py-1 !text-xs inline-flex items-center gap-1.5"
          @click="openCreateModal"
        >
          <Plus class="w-3.5 h-3.5" />
          {{ t('settings.pluginsCreateBtn') }}
        </button>
        <button
          type="button"
          class="ui-btn-secondary shrink-0 !px-3 !py-1 !text-xs inline-flex items-center gap-1.5 text-indigo-600 dark:text-indigo-400 hover:text-indigo-700"
          @click="isDevGuideOpen = true"
        >
          <BookOpen class="w-3.5 h-3.5" />
          {{ t('settings.pluginsDevGuideBtn') }}
        </button>
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
        class="p-3 border rounded flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs transition-colors"
        :class="plugin.enabled !== false
          ? 'border-gray-100 dark:border-gray-800/60 bg-gray-50/60 dark:bg-white/[0.02] hover:border-gray-300 dark:hover:border-gray-700'
          : 'border-dashed border-gray-300 dark:border-gray-700/60 bg-gray-100/40 dark:bg-white/[0.01] opacity-75'"
      >
        <div class="min-w-0 space-y-1">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="font-mono font-semibold text-gray-900 dark:text-gray-100 text-xs">
              {{ plugin.name }}
            </span>
            <span
              class="px-1.5 py-0.5 rounded text-[10px] font-mono border"
              :class="plugin.builtin
                ? 'bg-purple-100 dark:bg-purple-950/80 text-purple-700 dark:text-purple-300 border-purple-200 dark:border-purple-800/50'
                : 'bg-indigo-100 dark:bg-indigo-950/80 text-indigo-700 dark:text-indigo-300 border-indigo-200 dark:border-indigo-800/50'"
            >
              {{ plugin.builtin ? t('settings.pluginsBuiltin') : t('settings.pluginsCustom') }}
            </span>
            <span
              v-if="plugin.version"
              class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 border border-slate-200 dark:border-slate-700"
            >
              v{{ plugin.version }}
            </span>
            <span
              v-if="plugin.enabled === false"
              class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-amber-100 dark:bg-amber-950/80 text-amber-700 dark:text-amber-300 border border-amber-200 dark:border-amber-800/50"
            >
              {{ t('settings.pluginsDisabledTag') }}
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
            <span
              v-if="plugin.updated_at"
              class="text-[10px] text-gray-400 dark:text-gray-500 font-mono"
            >
              {{ plugin.updated_at }}
            </span>
            <span
              v-if="plugin.author"
              class="text-[10px] text-gray-400 dark:text-gray-500"
            >
              {{ plugin.author }}
            </span>
          </div>
          <p class="text-gray-600 dark:text-gray-300 text-[11px] leading-relaxed">
            {{ plugin.description || t('settings.pluginsNoDesc') }}
          </p>
          <div v-if="plugin.source_path" class="text-[10px] text-gray-400 dark:text-gray-500 font-mono truncate max-w-lg">
            {{ plugin.source_path }}
          </div>
        </div>

        <div class="shrink-0 flex items-center gap-2 flex-wrap">
          <!-- 启用/停用软开关 -->
          <button
            type="button"
            class="ui-btn-secondary !py-1 !px-2.5 !text-xs inline-flex items-center gap-1 transition-colors"
            :class="plugin.enabled !== false ? 'text-emerald-600 dark:text-emerald-400 hover:text-emerald-700' : 'text-gray-400 dark:text-gray-500 hover:text-gray-600'"
            :disabled="togglingPluginName === plugin.name"
            @click="handleToggle(plugin)"
          >
            <RefreshCw v-if="togglingPluginName === plugin.name" class="w-3 h-3 animate-spin" />
            <Power v-else class="w-3 h-3" />
            {{ plugin.enabled !== false ? t('settings.pluginsEnabled') : t('settings.pluginsDisabled') }}
          </button>

          <!-- 查看源码 -->
          <button
            type="button"
            class="ui-btn-secondary !py-1 !px-2.5 !text-xs inline-flex items-center gap-1 text-slate-600 dark:text-slate-400 hover:text-slate-700"
            @click="openSourceModal(plugin)"
          >
            <Code class="w-3 h-3" />
            {{ t('settings.pluginsSourceBtn') }}
          </button>

          <!-- 调试 -->
          <button
            type="button"
            class="ui-btn-secondary !py-1 !px-2.5 !text-xs inline-flex items-center gap-1 text-sky-600 dark:text-sky-400 hover:text-sky-700"
            @click="openTestModal(plugin)"
          >
            <Play class="w-3 h-3 fill-current" />
            {{ t('settings.pluginsPlaygroundBtn') }}
          </button>

          <!-- 删除 (仅自定义插件) -->
          <button
            v-if="!plugin.builtin"
            type="button"
            class="ui-btn-secondary !py-1 !px-2.5 !text-xs inline-flex items-center gap-1 text-red-600 dark:text-red-400 hover:text-red-700"
            :disabled="deletingPluginName === plugin.name"
            @click="handleDelete(plugin)"
          >
            <Trash2 class="w-3 h-3" />
            {{ t('settings.pluginsDeleteBtn') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 源码查看弹窗 -->
    <Modal
      :title="`${t('settings.pluginsSourceTitle')}: ${currentSourcePlugin?.name ?? ''}`"
      :is-open="isSourceModalOpen"
      max-width-class="max-w-3xl"
      @close="isSourceModalOpen = false"
    >
      <template #header-extra>
        <button
          type="button"
          class="ui-btn-secondary !py-1 !px-2.5 !text-xs inline-flex items-center gap-1.5 ml-2"
          :disabled="!sourceCode || sourceLoading"
          @click="copySourceCode"
        >
          <Check v-if="sourceCopied" class="w-3.5 h-3.5 text-emerald-500" />
          <Copy v-else class="w-3.5 h-3.5" />
          <span>{{ sourceCopied ? t('settings.pluginsSourceCopied') : t('settings.pluginsSourceCopy') }}</span>
        </button>
      </template>

      <div class="space-y-3 text-xs">
        <div class="flex items-center gap-3 text-gray-500 dark:text-gray-400 text-[11px] font-mono flex-wrap">
          <span v-if="currentSourcePlugin?.version">v{{ currentSourcePlugin.version }}</span>
          <span v-if="currentSourcePlugin?.author">By {{ currentSourcePlugin.author }}</span>
          <span v-if="currentSourcePlugin?.updated_at">{{ currentSourcePlugin.updated_at }}</span>
          <span v-if="currentSourcePlugin?.source_path" class="text-gray-400 truncate max-w-md">
            {{ currentSourcePlugin.source_path }}
          </span>
        </div>

        <div v-if="sourceLoading" class="p-8 text-center text-gray-400">
          <RefreshCw class="w-5 h-5 mx-auto animate-spin mb-2" />
          <p>{{ t('settings.pluginsSourceLoading') }}</p>
        </div>
        <div v-else class="relative bg-gray-950 text-gray-100 rounded-lg p-4 font-mono text-[11px] leading-relaxed max-h-[60vh] overflow-y-auto border border-gray-800 select-all custom-scrollbar">
          <pre class="whitespace-pre overflow-x-auto">{{ sourceCode }}</pre>
        </div>
      </div>
    </Modal>

    <!-- 调试弹窗 -->
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

          <!-- 回复文本 -->
          <div v-if="testResult.reply_text !== undefined && testResult.reply_text !== null" class="p-2 bg-white/80 dark:bg-black/30 rounded border border-gray-200 dark:border-gray-800">
            <span class="text-[10px] text-gray-400 block mb-0.5">{{ t('settings.pluginsReplyOutput') }}</span>
            <div class="font-mono text-xs text-sky-600 dark:text-sky-300 font-semibold select-all">
              {{ testResult.reply_text }}
            </div>
          </div>

          <!-- 表情表态 (Reactions) -->
          <div v-if="testResult.reacted_emojis && testResult.reacted_emojis.length" class="p-2 bg-white/80 dark:bg-black/30 rounded border border-gray-200 dark:border-gray-800">
            <span class="text-[10px] text-gray-400 block mb-1">{{ t('settings.pluginsReactionOutput') }}</span>
            <div class="flex items-center gap-1.5 flex-wrap">
              <span
                v-for="(emoji, idx) in testResult.reacted_emojis"
                :key="idx"
                class="px-2 py-0.5 rounded-full text-base bg-sky-50 dark:bg-sky-950/60 border border-sky-200 dark:border-sky-800/60"
              >
                {{ emoji }}
              </span>
            </div>
          </div>

          <!-- 日志输出 -->
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

    <!-- 新建插件弹窗 -->
    <Modal
      :title="t('settings.pluginsCreateTitle')"
      :is-open="isCreateModalOpen"
      max-width-class="max-w-lg"
      @close="isCreateModalOpen = false"
    >
      <form class="space-y-3.5 text-xs" @submit.prevent="submitCreatePlugin">
        <div class="space-y-1">
          <label class="font-medium text-gray-700 dark:text-gray-300">
            {{ t('settings.pluginsCreateName') }} <span class="text-red-500">*</span>
          </label>
          <input
            v-model="createForm.name"
            type="text"
            required
            class="ui-input !h-8 !text-xs !px-2.5 w-full font-mono"
            :placeholder="t('settings.pluginsCreateNamePlaceholder')"
          />
        </div>

        <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
          <div class="space-y-1">
            <label class="font-medium text-gray-700 dark:text-gray-300">
              {{ t('settings.pluginsCreateTemplate') }}
            </label>
            <select
              v-model="createForm.template"
              class="ui-input !h-8 !text-xs !px-2.5 w-full"
              @change="handleTemplateChange"
            >
              <option value="basic_reactive">{{ t('settings.pluginsTemplateReactive') }}</option>
              <option value="basic_active">{{ t('settings.pluginsTemplateActive') }}</option>
              <option value="storage_counter">{{ t('settings.pluginsTemplateStorage') }}</option>
            </select>
          </div>

          <div class="space-y-1">
            <label class="font-medium text-gray-700 dark:text-gray-300">
              {{ t('settings.pluginsCreateVersion') }}
            </label>
            <input
              v-model="createForm.version"
              type="text"
              class="ui-input !h-8 !text-xs !px-2.5 w-full font-mono"
              placeholder="1.0.0"
            />
          </div>
        </div>

        <div class="space-y-1">
          <label class="font-medium text-gray-700 dark:text-gray-300">
            {{ t('settings.pluginsCreateDesc') }}
          </label>
          <input
            v-model="createForm.description"
            type="text"
            class="ui-input !h-8 !text-xs !px-2.5 w-full"
            :placeholder="t('settings.pluginsCreateDescPlaceholder')"
          />
        </div>

        <div class="space-y-1">
          <label class="font-medium text-gray-700 dark:text-gray-300">
            {{ t('settings.pluginsCreateAuthor') }}
          </label>
          <input
            v-model="createForm.author"
            type="text"
            class="ui-input !h-8 !text-xs !px-2.5 w-full"
            :placeholder="t('settings.pluginsCreateAuthorPlaceholder')"
          />
        </div>

        <div class="flex justify-end gap-2 pt-2 border-t border-gray-100 dark:border-gray-800">
          <button
            type="button"
            class="ui-btn-secondary !px-3 !py-1.5 !text-xs"
            @click="isCreateModalOpen = false"
          >
            {{ t('common.cancel') }}
          </button>
          <button
            type="submit"
            class="ui-btn-primary !px-4 !py-1.5 !text-xs inline-flex items-center gap-1.5"
            :disabled="createLoading"
          >
            <RefreshCw v-if="createLoading" class="w-3.5 h-3.5 animate-spin" />
            <span>{{ t('settings.pluginsCreateSubmit') }}</span>
          </button>
        </div>
      </form>
    </Modal>

    <!-- 开发者指南抽屉/弹窗 -->
    <Modal
      :title="t('settings.pluginsDevGuideTitle')"
      :is-open="isDevGuideOpen"
      max-width-class="max-w-3xl"
      @close="isDevGuideOpen = false"
    >
      <div class="space-y-4 text-xs text-gray-700 dark:text-gray-300 leading-relaxed max-h-[70vh] overflow-y-auto pr-2 custom-scrollbar">
        <!-- 1. 架构定位 -->
        <div class="p-3 bg-indigo-50/50 dark:bg-indigo-950/20 border border-indigo-200/60 dark:border-indigo-800/40 rounded space-y-1.5">
          <h4 class="font-semibold text-indigo-900 dark:text-indigo-200 text-[13px]">
            🌟 什么是 TG-SignPulse Action 插件？
          </h4>
          <p class="text-[11px] text-gray-600 dark:text-gray-300">
            Action 插件是系统针对 Telegram 群组/频道交互逻辑的异步可编程扩展机制。支持监听入站消息并应答（reactive），也支持在任务流水线中被显式调度执行（active）。
          </p>
        </div>

        <!-- 2. 执行模式 -->
        <div class="space-y-2">
          <h4 class="font-semibold text-gray-900 dark:text-gray-100 text-[12px]">
            1. 执行模式对比 (Execution Mode)
          </h4>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            <div class="p-2.5 border border-sky-200/80 dark:border-sky-800/50 rounded bg-sky-50/30 dark:bg-sky-950/10 space-y-1">
              <span class="font-mono font-bold text-sky-700 dark:text-sky-300 text-[11px]">reactive (监听响应式)</span>
              <p class="text-[11px] text-gray-600 dark:text-gray-400">
                每当账号收到 Telegram 文本消息时被流水线触发。handler 需返回 <code class="font-mono bg-white dark:bg-black/30 px-1 py-0.5 rounded">True</code> 告知系统“消息已被成功捕获并消费”。
              </p>
            </div>
            <div class="p-2.5 border border-emerald-200/80 dark:border-emerald-800/50 rounded bg-emerald-50/30 dark:bg-emerald-950/10 space-y-1">
              <span class="font-mono font-bold text-emerald-700 dark:text-emerald-300 text-[11px]">active (主动调度式)</span>
              <p class="text-[11px] text-gray-600 dark:text-gray-400">
                可被签到任务或外部动作显式调用。无进站消息事件触发，直接利用上下文发起出站推送或 HTTP Webhook 回调。
              </p>
            </div>
          </div>
        </div>

        <!-- 3. PluginContext 核心能力 -->
        <div class="space-y-2">
          <h4 class="font-semibold text-gray-900 dark:text-gray-100 text-[12px]">
            2. PluginContext 核心对象与上下文能力
          </h4>
          <div class="border border-gray-200 dark:border-gray-800 rounded overflow-hidden">
            <table class="w-full text-left text-[11px]">
              <thead class="bg-gray-50 dark:bg-gray-800/60 text-gray-500 font-mono">
                <tr>
                  <th class="p-2 border-b border-gray-200 dark:border-gray-800">方法 / 属性</th>
                  <th class="p-2 border-b border-gray-200 dark:border-gray-800">说明</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-100 dark:divide-gray-800/60 font-mono">
                <tr>
                  <td class="p-2 text-sky-600 dark:text-sky-400 font-semibold">ctx.message</td>
                  <td class="p-2 text-gray-600 dark:text-gray-300 font-sans">Telegram 进站消息对象（含 text, id, date, chat 等）</td>
                </tr>
                <tr>
                  <td class="p-2 text-sky-600 dark:text-sky-400 font-semibold">await ctx.reply(text)</td>
                  <td class="p-2 text-gray-600 dark:text-gray-300 font-sans">快捷回复当前进站消息</td>
                </tr>
                <tr>
                  <td class="p-2 text-sky-600 dark:text-sky-400 font-semibold">await ctx.send_message(text)</td>
                  <td class="p-2 text-gray-600 dark:text-gray-300 font-sans">向当前会话主动发送新文本消息</td>
                </tr>
                <tr>
                  <td class="p-2 text-sky-600 dark:text-sky-400 font-semibold">await ctx.react(emoji)</td>
                  <td class="p-2 text-gray-600 dark:text-gray-300 font-sans">对当前消息打上 Telegram Emoji 表态</td>
                </tr>
                <tr>
                  <td class="p-2 text-sky-600 dark:text-sky-400 font-semibold">ctx.storage</td>
                  <td class="p-2 text-gray-600 dark:text-gray-300 font-sans">按插件名隔离的状态持久化引擎 (get / set / increment)</td>
                </tr>
                <tr>
                  <td class="p-2 text-sky-600 dark:text-sky-400 font-semibold">ctx.log(message)</td>
                  <td class="p-2 text-gray-600 dark:text-gray-300 font-sans">安全输出日志流（会在调试弹窗和面板日志流中实时展示）</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- 4. 元数据规范 -->
        <div class="space-y-1.5">
          <h4 class="font-semibold text-gray-900 dark:text-gray-100 text-[12px]">
            3. 版本与元数据声明规范
          </h4>
          <p class="text-[11px] text-gray-600 dark:text-gray-400">
            推荐在插件 Python 脚本顶部声明模块级全局变量，或直接在 <code class="font-mono bg-gray-100 dark:bg-gray-800 px-1 py-0.5 rounded">@PluginRegistry.register</code> 中传入：
          </p>
          <pre class="p-3 bg-gray-950 text-gray-200 rounded font-mono text-[11px] leading-relaxed overflow-x-auto">VERSION = "1.0.0"
UPDATED_AT = "2026-09-11"
AUTHOR = "YourName"

@PluginRegistry.register(
    name="my_plugin",
    mode="reactive",
    description="插件描述",
    version=VERSION,
    updated_at=UPDATED_AT,
    author=AUTHOR,
    params_schema=[...],
)</pre>
        </div>
      </div>
    </Modal>
  </section>
</template>
