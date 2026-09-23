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
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
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
  Search,
  AlertTriangle,
  ChevronDown,
  ChevronUp,
  Upload,
  Download,
  Activity,
  History,
  Package,
  Archive,
  ShieldCheck,
  Sparkles,
  FileText,
  GitCompare,
  RotateCcw,
  Edit2,
  Save,
  Eye,
  Store,
  Globe,
  ExternalLink,
  Database,
  Zap,
  MoreHorizontal,
  Maximize2,
  Minimize2,
  Bookmark,
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
  getPluginDiagnostics,
  exportPlugin,
  uploadPlugin,
  updatePluginSource,
  resetPluginMetrics,
  batchTogglePlugins,
  resetAllPluginMetrics,
  getPluginHistory,
  clonePlugin,
  getPluginDependencies,
  exportAllPlugins,
  importPluginsBundle,
  getPluginsManifest,
  checkPluginSyntax,
  clearPluginHistory,
  auditPluginSource,
  formatPluginSource,
  type AuditPluginWarning,
  type PluginDependency,
  type PluginExecutionRecord,
  type PluginInfo,
  type PluginTestResponse,
  type CreatePluginRequest,
  type PluginLoadErrorItem,
  getMarketCatalog,
  getMarketSource,
  updateMarketSource,
  getMarketPluginReadme,
  installMarketPlugin,
  updateMarketPlugin,
  uninstallMarketPlugin,
  type MarketPluginItem,
  type MarketSourceConfig,
  getPluginStorage,
  clearPluginStorage,
  type PluginStorageResponse,
  type PluginStorageRecord,
} from '../../lib/api'
import { useI18n } from '../../composables/useI18n'
import { useToast } from '../../composables/useToast'
import { useConfirm } from '../../composables/useConfirm'
import { withToken } from '../../lib/api/core'
import { computeLineDiff, type DiffLine } from '../../lib/diff'
import { copyToClipboard } from '../../lib/clipboard'
import { getLocalizedErrorMessage } from '../../lib/types'

const { t } = useI18n()
const toast = useToast()
const route = useRoute()
const router = useRouter()
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
const isEditingSource = ref(false)
const editedSourceCode = ref('')
const savingSource = ref(false)
const resettingMetricsPlugin = ref<string | null>(null)
const batchToggling = ref(false)
const resettingAllMetrics = ref(false)

// 克隆插件
const isCloneModalOpen = ref(false)
const cloningPlugin = ref<PluginInfo | null>(null)
const cloneForm = ref({ new_name: '', description: '' })
const submittingClone = ref(false)

const openCloneModal = (plugin: PluginInfo) => {
  cloningPlugin.value = plugin
  cloneForm.value = {
    new_name: `${plugin.name}_copy`,
    description: plugin.description || '',
  }
  isCloneModalOpen.value = true
}

const submitClonePlugin = async () => {
  if (!cloningPlugin.value) return
  const newName = cloneForm.value.new_name.trim()
  if (!newName || !/^[a-zA-Z0-9_]{3,32}$/.test(newName)) {
    toast.error(t('settings.pluginsCreateNamePlaceholder'))
    return
  }
  submittingClone.value = true
  try {
    const res = await withToken((token) => clonePlugin(cloningPlugin.value!.name, {
      new_name: newName,
      description: cloneForm.value.description.trim() || undefined,
    }, token))
    if (res) {
      toast.success(t('settings.pluginsCloneSuccess'))
      isCloneModalOpen.value = false
      await loadPluginList()
    }
  } catch (err: unknown) {
    const msg = getLocalizedErrorMessage(err, t)
    toast.error(msg)
  } finally {
    submittingClone.value = false
  }
}

// 调用历史
const isHistoryModalOpen = ref(false)
const historyPluginName = ref<string>('')
const executionHistory = ref<PluginExecutionRecord[]>([])
const loadingHistory = ref(false)
const clearingHistory = ref(false)

let historyRequestSeq = 0

// 分类筛选
const filterCategory = ref<string>('all')

const availableCategories = computed(() => {
  const counts: Record<string, number> = {
    all: plugins.value.length,
    utility: 0,
    message: 0,
    notification: 0,
    helper: 0,
    entertainment: 0,
    other: 0,
  }
  for (const p of plugins.value) {
    const cat = (p.category || 'utility').toLowerCase()
    if (cat in counts) {
      counts[cat]++
    } else {
      counts.other++
    }
  }
  return [
    { key: 'all', label: t('settings.pluginsCategoryAll'), count: counts.all },
    { key: 'utility', label: t('settings.pluginsCategoryUtility'), count: counts.utility },
    { key: 'message', label: t('settings.pluginsCategoryMessage'), count: counts.message },
    { key: 'notification', label: t('settings.pluginsCategoryNotification'), count: counts.notification },
    { key: 'helper', label: t('settings.pluginsCategoryHelper'), count: counts.helper },
    { key: 'entertainment', label: t('settings.pluginsCategoryEntertainment'), count: counts.entertainment },
    { key: 'other', label: t('settings.pluginsCategoryOther'), count: counts.other },
  ]
})

// 持久化存储状态与操作
const isStorageModalOpen = ref(false)
const currentStoragePlugin = ref<PluginInfo | null>(null)
const storageLoading = ref(false)
const storageClearing = ref(false)
const storageData = ref<PluginStorageResponse | null>(null)
const selectedStorageNamespace = ref<string>('all')

const openStorageModal = async (plugin: PluginInfo) => {
  currentStoragePlugin.value = plugin
  selectedStorageNamespace.value = 'all'
  storageData.value = null
  isStorageModalOpen.value = true
  await refreshPluginStorage()
}

const refreshPluginStorage = async () => {
  if (!currentStoragePlugin.value) return
  storageLoading.value = true
  try {
    const res = await withToken((token) => getPluginStorage(currentStoragePlugin.value!.name, token))
    if (res) {
      storageData.value = res
    }
  } catch (err: unknown) {
    const msg = getLocalizedErrorMessage(err, t)
    toast.error(msg)
  } finally {
    storageLoading.value = false
  }
}

const handleDeleteStorageKey = async (ns: string, key: string) => {
  if (!currentStoragePlugin.value) return
  const confirmed = await confirm({
    title: t('settings.pluginsStorageDeleteKey'),
    message: t('settings.pluginsStorageDeleteKeyConfirm', { key }),
    confirmText: t('common.delete'),
    cancelText: t('common.cancel'),
    danger: true,
  })
  if (!confirmed) return

  try {
    await withToken((token) => clearPluginStorage(currentStoragePlugin.value!.name, token, { namespace: ns, key }))
    toast.success(t('settings.pluginsStorageDeleteKeySuccess'))
    await refreshPluginStorage()
  } catch (err: unknown) {
    const msg = getLocalizedErrorMessage(err, t)
    toast.error(msg)
  }
}

const handleClearAllStorage = async () => {
  if (!currentStoragePlugin.value) return
  const confirmed = await confirm({
    title: t('settings.pluginsStorageClearAll'),
    message: t('settings.pluginsStorageClearConfirm', { name: currentStoragePlugin.value.name }),
    confirmText: t('common.delete'),
    cancelText: t('common.cancel'),
    danger: true,
  })
  if (!confirmed) return

  storageClearing.value = true
  try {
    const res = await withToken((token) => clearPluginStorage(currentStoragePlugin.value!.name, token))
    if (res?.success) {
      toast.success(t('settings.pluginsStorageClearSuccess'))
      await refreshPluginStorage()
    }
  } catch (err: unknown) {
    const msg = getLocalizedErrorMessage(err, t)
    toast.error(msg)
  } finally {
    storageClearing.value = false
  }
}

const visibleStorageRecords = computed(() => {
  if (!storageData.value) return []
  const results: Array<{ namespace: string; is_test: boolean; record: PluginStorageRecord }> = []
  for (const ns of storageData.value.namespaces) {
    if (selectedStorageNamespace.value !== 'all' && ns.namespace !== selectedStorageNamespace.value) {
      continue
    }
    for (const r of ns.records) {
      results.push({
        namespace: ns.namespace,
        is_test: ns.is_test,
        record: r,
      })
    }
  }
  return results
})

const isValidHttpUrl = (url?: string | null): boolean => {
  if (!url) return false
  try {
    const parsed = new URL(url)
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
  } catch {
    return false
  }
}

const copyStorageValue = async (val: unknown) => {
  const valText = typeof val === 'object' ? JSON.stringify(val, null, 2) : String(val)
  if (await copyToClipboard(valText)) {
    toast.success(t('common.copied'))
  } else {
    toast.error(t('common.copyFailed'))
  }
}

const openHistoryModal = async (plugin: PluginInfo) => {
  const seq = ++historyRequestSeq
  historyPluginName.value = plugin.name
  isHistoryModalOpen.value = true
  loadingHistory.value = true
  executionHistory.value = []
  try {
    const res = await withToken((token) => getPluginHistory(plugin.name, token))
    if (seq !== historyRequestSeq) return
    if (res) {
      executionHistory.value = res.history || []
    }
  } catch (err: unknown) {
    if (seq !== historyRequestSeq) return
    const msg = getLocalizedErrorMessage(err, t)
    toast.error(msg)
  } finally {
    if (seq === historyRequestSeq) loadingHistory.value = false
  }
}

const handleClearHistory = async () => {
  if (!historyPluginName.value) return
  const confirmed = await confirm({
    title: t('settings.pluginsHistoryClear'),
    message: t('settings.pluginsHistoryClearConfirm'),
    confirmText: t('common.delete'),
    cancelText: t('common.cancel'),
    danger: true,
  })
  if (!confirmed) return

  clearingHistory.value = true
  try {
    await withToken((token) => clearPluginHistory(historyPluginName.value, token))
    executionHistory.value = []
    toast.success(t('settings.pluginsHistoryClearSuccess'))
  } catch (err: unknown) {
    const msg = getLocalizedErrorMessage(err, t)
    toast.error(msg)
  } finally {
    clearingHistory.value = false
  }
}

// 触发类型展示标签：映射调试与任务执行两类来源
const triggerTypeLabel = (triggerType: string) => {
  if (triggerType === 'manual_test') return t('settings.pluginsHistoryTriggerManual')
  if (triggerType === 'reactive') return t('settings.pluginsHistoryTriggerReactive')
  if (triggerType === 'active') return t('settings.pluginsHistoryTriggerActive')
  return triggerType
}

const handleCopyHistoryLogs = async () => {
  if (!executionHistory.value.length) return
  const delimiter = "\n---------------------\n\n"
  const content = executionHistory.value.map((rec, i) => {
    const status = rec.success ? '[SUCCESS]' : '[FAILED]'
    const errPart = rec.error ? `Error: ${rec.error}\n` : ''
    const logPart = rec.log_summary ? `Logs:\n${rec.log_summary}\n` : ''
    return `#${i + 1} [${rec.timestamp}] ${status} (${rec.duration_ms}ms, ${triggerTypeLabel(rec.trigger_type)})\n` + errPart + logPart
  }).join(delimiter)
  if (await copyToClipboard(content)) {
    toast.success(t('settings.pluginsHistoryExportSuccess'))
  } else {
    toast.error(t('common.copyFailed'))
  }
}
interface TestSnapshot {
  text: string
  params: Record<string, unknown>
}

const testSnapshots = ref<Record<string, TestSnapshot[]>>({})

const saveTestSnapshot = (pluginName: string, text: string, params: Record<string, unknown>) => {
  if (!text.trim() && Object.keys(params).length === 0) return
  const list = testSnapshots.value[pluginName] || []
  const exists = list.some(item => item.text === text && JSON.stringify(item.params) === JSON.stringify(params))
  if (!exists) {
    list.unshift({ text, params: { ...params } })
    if (list.length > 3) list.pop()
    testSnapshots.value[pluginName] = list
  }
}

const applyTestSnapshot = (item: TestSnapshot) => {
  testInputText.value = item.text
  testParams.value = { ...item.params }
}

const handleBatchToggle = async (enabled: boolean) => {
  batchToggling.value = true
  try {
    const res = await withToken((token) => batchTogglePlugins(enabled, token))
    if (res) {
      toast.success(t('settings.pluginsBatchSuccess', { count: res.count }))
      await loadPluginList()
    }
  } catch (err: unknown) {
    const msg = getLocalizedErrorMessage(err, t)
    toast.error(msg)
  } finally {
    batchToggling.value = false
  }
}

const handleResetAllMetrics = async () => {
  const confirmed = await confirm({
    title: t('settings.pluginsResetAllMetrics'),
    message: t('settings.pluginsResetAllMetricsConfirm'),
    confirmText: t('common.confirm'),
    cancelText: t('common.cancel'),
    danger: true,
  })
  if (!confirmed) return

  resettingAllMetrics.value = true
  try {
    await withToken((token) => resetAllPluginMetrics(token))
    toast.success(t('settings.pluginsResetAllMetricsSuccess'))
    await loadPluginList()
  } catch (err: unknown) {
    const msg = getLocalizedErrorMessage(err, t)
    toast.error(msg)
  } finally {
    resettingAllMetrics.value = false
  }
}

// 导入/导出状态
const fileInputRef = ref<HTMLInputElement | null>(null)
const uploadingPlugin = ref(false)
const exportingPluginName = ref<string | null>(null)

// 调试弹窗状态
const isTestModalOpen = ref(false)
const currentTestPlugin = ref<PluginInfo | null>(null)
const testInputText = ref('')
const testParams = ref<Record<string, unknown>>({})
const testRunning = ref(false)
const testResult = ref<PluginTestResponse | null>(null)
const resetStorage = ref(false)
const showAdvancedMock = ref(false)
const mockChatId = ref('')
const mockSenderName = ref('')
const mockTimeout = ref('')

// 诊断状态
const loadErrors = ref<PluginLoadErrorItem[]>([])
const isDiagOpen = ref(false)
const copiedDiagIndex = ref<number | null>(null)

// 组件卸载时清理复制状态的延时回调，避免悬挂定时器
const copyTimers = new Set<ReturnType<typeof setTimeout>>()
const registerCopyTimer = (fn: () => void, delay: number) => {
  const id = setTimeout(() => {
    copyTimers.delete(id)
    fn()
  }, delay)
  copyTimers.add(id)
}
onBeforeUnmount(() => {
  for (const id of copyTimers) clearTimeout(id)
  copyTimers.clear()
})

const copyInstallCommand = async (cmd: string, idx: number) => {
  if (!(await copyToClipboard(cmd))) {
    toast.error(cmd)
    return
  }
  copiedDiagIndex.value = idx
  toast.success(t('settings.pluginsDiagCopied'))
  registerCopyTimer(() => {
    if (copiedDiagIndex.value === idx) copiedDiagIndex.value = null
  }, 2000)
}

// 卡片轻量化、编辑器与试验场打磨状态
const activeMoreDropdownPlugin = ref<string | null>(null)
const isEditorFullscreen = ref(false)
const showSnippetDropdown = ref(false)

function toggleMoreDropdown(pluginName: string) {
  activeMoreDropdownPlugin.value = activeMoreDropdownPlugin.value === pluginName ? null : pluginName
}

function handleDocumentClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (!target.closest('.plugin-more-dropdown-container')) {
    activeMoreDropdownPlugin.value = null
  }
  if (!target.closest('.plugin-snippet-dropdown-container')) {
    showSnippetDropdown.value = false
  }
}

const SDK_SNIPPETS = [
  {
    labelKey: 'settings.pluginsSnippetParam',
    code: 'target_param = ctx.get_param("param_key", default="default_value")',
  },
  {
    labelKey: 'settings.pluginsSnippetStorageGet',
    code: 'val = await ctx.storage.get("key", default=None)',
  },
  {
    labelKey: 'settings.pluginsSnippetStorageSet',
    code: 'await ctx.storage.set("key", "stored_value")',
  },
  {
    labelKey: 'settings.pluginsSnippetGlobalStorage',
    code: 'await ctx.global_storage.set("global_cache_key", "cached_value")',
  },
  {
    labelKey: 'settings.pluginsSnippetSendMsg',
    code: 'await ctx.send_message("主动推送消息内容")',
  },
  {
    labelKey: 'settings.pluginsSnippetReply',
    code: 'await ctx.reply("已接收并处理您的指令")',
  },
  {
    labelKey: 'settings.pluginsSnippetEditMsg',
    code: 'await ctx.edit_message("已更新处理状态")',
  },
  {
    labelKey: 'settings.pluginsSnippetDeleteMsg',
    code: 'await ctx.delete_message()',
  },
  {
    labelKey: 'settings.pluginsSnippetLog',
    code: 'ctx.log("[自定义日志] 处理完毕")',
  },
]

function insertSnippet(code: string) {
  showSnippetDropdown.value = false
  if (!editedSourceCode.value) {
    editedSourceCode.value = code
  } else {
    editedSourceCode.value = editedSourceCode.value + '\n\n' + code
  }
  toast.success(t('settings.pluginsSnippetInserted'))
}

function savePlaygroundPreset() {
  if (!currentTestPlugin.value) return
  const key = `tg_signer_test_preset_${currentTestPlugin.value.name}`
  const payload = {
    testInput: testInputText.value,
    testParams: testParams.value,
    mockChatId: mockChatId.value,
    mockSenderName: mockSenderName.value,
    mockTimeout: mockTimeout.value,
    resetStorage: resetStorage.value,
  }
  localStorage.setItem(key, JSON.stringify(payload))
  toast.success(t('settings.pluginsPlaygroundPresetSaved'))
}

function loadPlaygroundPreset() {
  if (!currentTestPlugin.value) return
  const key = `tg_signer_test_preset_${currentTestPlugin.value.name}`
  const saved = localStorage.getItem(key)
  if (!saved) {
    toast.info(t('settings.pluginsPlaygroundNoPreset'))
    return
  }
  try {
    const data = JSON.parse(saved)
    if (data.testInput !== undefined) testInputText.value = data.testInput
    if (data.testParams) testParams.value = { ...testParams.value, ...data.testParams }
    if (data.mockChatId !== undefined) mockChatId.value = data.mockChatId
    if (data.mockSenderName !== undefined) mockSenderName.value = data.mockSenderName
    if (data.mockTimeout !== undefined) mockTimeout.value = data.mockTimeout
    if (data.resetStorage !== undefined) resetStorage.value = data.resetStorage
    toast.success(t('settings.pluginsPlaygroundPresetLoaded'))
  } catch {
    toast.error(t('settings.pluginsPlaygroundPresetCorrupted'))
  }
}

const canFormatReplyJson = computed(() => {
  if (!testResult.value?.reply_text) return false
  const text = testResult.value.reply_text.trim()
  return (text.startsWith('{') && text.endsWith('}')) || (text.startsWith('[') && text.endsWith(']'))
})

function formatReplyJson() {
  if (!testResult.value?.reply_text) return
  try {
    const parsed = JSON.parse(testResult.value.reply_text)
    testResult.value.reply_text = JSON.stringify(parsed, null, 2)
  } catch {
    // ignore
  }
}

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
  // 命中后立即清除 URL 参数，避免后续 loadPluginList 反复自动弹出调试台
  void router.replace({ query: { ...route.query, testPlugin: undefined, testInput: undefined } })
}

const searchQuery = ref('')
const filterMode = ref<'all' | 'reactive' | 'active'>('all')
const filterType = ref<'all' | 'builtin' | 'custom' | 'issue'>('all')
const sortBy = ref<'default' | 'runs' | 'success_rate' | 'duration' | 'name'>('default')

const issuePluginsCount = computed(() =>
  plugins.value.filter((p) => p.metrics?.last_error || (p.metrics?.failure_count ?? 0) > 0).length,
)
const exportingAll = ref(false)

const exportingManifest = ref(false)
const handleExportManifest = async () => {
  exportingManifest.value = true
  try {
    const list = await withToken((token) => getPluginsManifest(token))
    if (!list) return
    const blob = new Blob([JSON.stringify(list, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `plugins-manifest-${new Date().toISOString().slice(0, 10)}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    toast.success(t('settings.pluginsExportManifestSuccess'))
  } catch (err: unknown) {
    const msg = getLocalizedErrorMessage(err, t)
    toast.error(msg)
  } finally {
    exportingManifest.value = false
  }
}

const handleExportAll = async () => {
  exportingAll.value = true
  try {
    const blob = await withToken((token) => exportAllPlugins(token))
    if (!blob) return
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `tg_signer_plugins_${new Date().toISOString().slice(0, 10)}.zip`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    toast.success(t('settings.pluginsExportAllSuccess'))
  } catch (err: unknown) {
    const msg = getLocalizedErrorMessage(err, t)
    toast.error(`${t('settings.pluginsExportAllFailed')}: ${msg}`)
  } finally {
    exportingAll.value = false
  }
}

const filteredPlugins = computed(() => {
  const list = plugins.value.filter((p) => {
    if (searchQuery.value.trim()) {
      const q = searchQuery.value.trim().toLowerCase()
      const matchName = p.name.toLowerCase().includes(q)
      const matchDesc = (p.description || '').toLowerCase().includes(q)
      const matchAuthor = (p.author || '').toLowerCase().includes(q)
      const matchCategory = (p.category || '').toLowerCase().includes(q)
      const matchTags = (p.tags || []).some((tag) => tag.toLowerCase().includes(q))
      if (!matchName && !matchDesc && !matchAuthor && !matchCategory && !matchTags) return false
    }
    if (filterMode.value !== 'all' && p.mode !== filterMode.value) {
      return false
    }
    if (filterCategory.value !== 'all') {
      const cat = (p.category || 'utility').toLowerCase()
      if (filterCategory.value === 'other') {
        if (['utility', 'message', 'notification', 'helper', 'entertainment'].includes(cat)) {
          return false
        }
      } else if (cat !== filterCategory.value) {
        return false
      }
    }
    if (filterType.value === 'builtin' && !p.builtin) return false
    if (filterType.value === 'custom' && p.builtin) return false
    if (filterType.value === 'issue' && !(p.metrics?.last_error || (p.metrics?.failure_count ?? 0) > 0)) return false
    return true
  })
  if (sortBy.value === 'runs') {
    return [...list].sort((a, b) => (b.metrics?.run_count || 0) - (a.metrics?.run_count || 0))
  } else if (sortBy.value === 'success_rate') {
    return [...list].sort((a, b) => (b.metrics?.success_rate || 0) - (a.metrics?.success_rate || 0))
  } else if (sortBy.value === 'duration') {
    return [...list].sort((a, b) => (b.metrics?.avg_duration_ms || 0) - (a.metrics?.avg_duration_ms || 0))
  } else if (sortBy.value === 'name') {
    return [...list].sort((a, b) => a.name.localeCompare(b.name))
  }
  return list
})

const openTestFromSource = async () => {
  if (!currentSourcePlugin.value) return
  // 与关闭弹窗相同的未保存守卫：编辑态有改动时先确认，防止静默丢弃
  if (isEditingSource.value && editedSourceCode.value !== sourceCode.value) {
    const confirmed = await confirm({
      title: t('settings.pluginsUnsavedChangesTitle'),
      message: t('settings.pluginsUnsavedChangesMsg'),
      confirmText: t('settings.pluginsDiscardAndClose'),
      cancelText: t('common.cancel'),
      danger: true,
    })
    if (!confirmed) return
  }
  const p = currentSourcePlugin.value
  isSourceModalOpen.value = false
  isEditingSource.value = false
  showDiffView.value = false
  openTestModal(p)
}

const loadPluginList = async () => {
  loading.value = true
  try {
    plugins.value = await withToken((token) => getPlugins(token)) ?? []
    checkRouteForTestPlugin()
    try {
      const diag = await withToken((token) => getPluginDiagnostics(token))
      if (diag) {
        loadErrors.value = diag.load_errors || []
      }
    } catch {
      // 诊断非核心阻断
    }
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
    try {
      const diag = await withToken((token) => getPluginDiagnostics(token))
      if (diag) {
        loadErrors.value = diag.load_errors || []
      }
    } catch {
      // 诊断非核心阻断
    }
    toast.success(t('settings.pluginsReloadSuccess', { count: res.count }))
  } catch (err: unknown) {
    const msg = getLocalizedErrorMessage(err, t)
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
    const msg = getLocalizedErrorMessage(err, t)
    toast.error(`${t('settings.pluginToggleFailed')}: ${msg}`)
  } finally {
    togglingPluginName.value = null
  }
}

// 查看源码
// 依赖体检状态
const pluginDeps = ref<PluginDependency[]>([])
const loadingDeps = ref(false)

const copyDepInstall = async (cmd: string) => {
  if (await copyToClipboard(cmd)) {
    toast.success(t('settings.pluginsDependencyCopied', { cmd }))
  } else {
    toast.error(cmd)
  }
}

// 调试参数恢复默认
const resetTestParamsToDefault = () => {
  if (!currentTestPlugin.value?.params_schema) return
  const defaults: Record<string, any> = {}
  for (const field of currentTestPlugin.value.params_schema) {
    if (field.name && field.default !== undefined) {
      defaults[field.name] = field.default
    }
  }
  testParams.value = defaults
  toast.success(t('settings.pluginsConfigResetSuccess'))
}

// 源码弹窗请求时序计数：快速切换插件时，晚到的过期响应不得覆盖当前插件
let sourceRequestSeq = 0

const openSourceModal = async (plugin: PluginInfo) => {
  const seq = ++sourceRequestSeq
  currentSourcePlugin.value = plugin
  sourceCode.value = ''
  sourceCopied.value = false
  isEditingSource.value = false
  editedSourceCode.value = ''
  // 一并清理编辑派生状态，避免上一插件的审计告警/Diff/语法结果泄漏到新插件
  auditWarnings.value = []
  auditCapabilities.value = []
  auditScore.value = null
  auditRiskLevel.value = 'safe'
  auditDeclared.value = []
  auditUndeclared.value = []
  auditCanSaveSafely.value = true
  showDiffView.value = false
  syntaxResult.value = null
  isSourceModalOpen.value = true
  sourceLoading.value = true
  pluginDeps.value = []
  loadingDeps.value = true
  void (async () => {
    try {
      const res = await withToken((token) => getPluginDependencies(plugin.name, token))
      if (seq !== sourceRequestSeq) return
      if (res && res.dependencies) {
        pluginDeps.value = res.dependencies
      }
    } catch {
      if (seq !== sourceRequestSeq) return
      pluginDeps.value = []
    } finally {
      if (seq === sourceRequestSeq) loadingDeps.value = false
    }
  })()

  try {
    const res = await withToken((token) => getPluginSource(plugin.name, token))
    if (seq !== sourceRequestSeq) return
    if (res) {
      sourceCode.value = res.source
    }
  } catch (err: unknown) {
    if (seq !== sourceRequestSeq) return
    const msg = getLocalizedErrorMessage(err, t)
    toast.error(`${t('settings.pluginsSourceLoading')}: ${msg}`)
  } finally {
    if (seq === sourceRequestSeq) sourceLoading.value = false
  }
}

const syntaxChecking = ref(false)
const syntaxResult = ref<{ valid: boolean; message: string } | null>(null)

const toggleEditSource = async () => {
  // 编辑 → 查看方向存在未保存改动时先确认，防止静默丢弃编辑内容
  if (isEditingSource.value && editedSourceCode.value !== sourceCode.value) {
    const confirmed = await confirm({
      title: t('settings.pluginsUnsavedChangesTitle'),
      message: t('settings.pluginsUnsavedChangesMsg'),
      confirmText: t('settings.pluginsDiscardAndClose'),
      cancelText: t('common.cancel'),
      danger: true,
    })
    if (!confirmed) return
  }
  isEditingSource.value = !isEditingSource.value
  syntaxResult.value = null
  if (isEditingSource.value) {
    editedSourceCode.value = sourceCode.value
  } else {
    showDiffView.value = false
  }
}

// 文档弹窗
const isDocModalOpen = ref(false)
const docPluginName = ref('')
const docPluginContent = ref('')

const openDocModal = (plugin: PluginInfo) => {
  docPluginName.value = plugin.name
  docPluginContent.value = plugin.doc || ''
  isDocModalOpen.value = true
}

// 静态安全审计
const auditingSource = ref(false)
const auditWarnings = ref<AuditPluginWarning[]>([])
const auditCapabilities = ref<string[]>([])
const auditScore = ref<number | null>(null)
const auditRiskLevel = ref<string>('safe')
const auditDeclared = ref<string[]>([])
const auditUndeclared = ref<string[]>([])
const auditCanSaveSafely = ref<boolean>(true)
const sourceEditorTextarea = ref<HTMLTextAreaElement | null>(null)

const jumpToSourceLine = (lineNo: number) => {
  if (!sourceEditorTextarea.value) return
  const lines = editedSourceCode.value.split('\n')
  const validLine = Math.max(1, Math.min(Math.floor(Number(lineNo) || 1), lines.length || 1))
  let pos = 0
  for (let i = 0; i < validLine - 1; i++) {
    pos += lines[i].length + 1
  }
  sourceEditorTextarea.value.focus()
  sourceEditorTextarea.value.setSelectionRange(pos, pos + (lines[validLine - 1]?.length || 0))
  const computedLineHeight = sourceEditorTextarea.value
    ? parseFloat(window.getComputedStyle(sourceEditorTextarea.value).lineHeight) || 18
    : 18
  sourceEditorTextarea.value.scrollTop = Math.max(0, (validLine - 4) * computedLineHeight)
}

const handleAuditSource = async () => {
  if (!editedSourceCode.value) return
  auditingSource.value = true
  auditWarnings.value = []
  auditCapabilities.value = []
  auditScore.value = null
  auditRiskLevel.value = 'safe'
  auditDeclared.value = []
  auditUndeclared.value = []
  auditCanSaveSafely.value = true
  try {
    const res = await withToken((token) => auditPluginSource(editedSourceCode.value, token))
    if (!res) return
    auditWarnings.value = res.warnings || []
    auditCapabilities.value = res.detected_capabilities || []
    auditDeclared.value = res.declared_permissions || []
    auditUndeclared.value = res.undeclared_capabilities || []
    auditScore.value = res.score ?? (res.passed ? 100 : 70)
    auditRiskLevel.value = res.risk_level ?? (res.passed ? 'safe' : 'warning')
    auditCanSaveSafely.value = res.can_save_safely !== false

    if (res.passed) {
      toast.success(t('settings.pluginsAuditSafe'))
    } else {
      toast.warning(t('settings.pluginsAuditWarnings', { n: res.warnings.length }))
    }
  } catch (err: unknown) {
    const msg = getLocalizedErrorMessage(err, t)
    toast.error(msg)
  } finally {
    auditingSource.value = false
  }
}

async function copyTraceback(tb?: string | null) {
  if (!tb) return
  if (await copyToClipboard(tb)) {
    toast.success(t('settings.pluginsPlaygroundCopiedTraceback'))
  } else {
    toast.error(t('settings.pluginsCopyFailed'))
  }
}

const formattingSource = ref(false)
const handleFormatSource = async () => {
  if (!editedSourceCode.value) return
  formattingSource.value = true
  try {
    const res = await withToken((token) => formatPluginSource(editedSourceCode.value, token))
    if (!res) return
    editedSourceCode.value = res.formatted
    if (res.lossy) {
      // 后端 black 缺失降级为 ast.unparse，注释已丢失，明确提示用户
      toast.warning(t('settings.pluginsFormatLossyWarning'))
    } else if (res.changed) {
      toast.success(t('settings.pluginsFormatSuccess'))
    } else {
      toast.info(t('settings.pluginsFormatUnchanged'))
    }
  } catch (err: unknown) {
    const msg = getLocalizedErrorMessage(err, t)
    toast.error(msg)
  } finally {
    formattingSource.value = false
  }
}

const handleResetPlaygroundInputs = () => {
  testInputText.value = ''
  testParams.value = {}
  mockChatId.value = ''
  mockSenderName.value = ''
  mockTimeout.value = ''
  testResult.value = null
  toast.info(t('settings.pluginsPlaygroundResetInputSuccess'))
}

const handleCopyTestResult = async () => {
  if (!testResult.value) return
  const r = testResult.value
  const lines = [
    `=== ${t('settings.pluginsCopyTestResultTitle', { name: r.name })} ===`,
    `${t('settings.pluginsCopyTestResultStatus')}: ${r.success ? t('common.success') : t('common.failed')} | ${t('settings.pluginsCopyTestResultHandled')}: ${r.handled ? t('common.yes') : t('common.no')} | ${t('settings.pluginsCopyTestResultDuration')}: ${r.duration_ms}ms`,
  ]
  if (r.reply_text) lines.push(`${t('settings.pluginsCopyTestResultReply')}: ${r.reply_text}`)
  if (r.error) lines.push(`${t('settings.pluginsCopyTestResultError')}: ${r.error}`)
  if (r.sent_messages?.length) lines.push(`${t('settings.pluginsCopyTestResultSent')}: ${r.sent_messages.length}`)
  if (r.reacted_emojis?.length) lines.push(`${t('settings.pluginsCopyTestResultReactions')}: ${r.reacted_emojis.join(', ')}`)
  if (r.logs?.length) {
    lines.push(`\n--- ${t('settings.pluginsCopyTestResultLogs')} ---`)
    lines.push(...r.logs)
  }
  if (await copyToClipboard(lines.join('\n'))) {
    toast.success(t('settings.pluginsCopyTestResultSuccess'))
  } else {
    toast.error(t('common.copyFailed'))
  }
}

const handleCopyMissingDeps = async () => {
  const missing = pluginDeps.value.filter((d) => !d.installed).map((d) => d.module)
  if (!missing.length) return
  const cmd = `pip install ${missing.join(' ')}`
  if (await copyToClipboard(cmd)) {
    toast.success(t('settings.pluginsCopyPipCommandSuccess'))
  } else {
    toast.error(t('common.copyFailed'))
  }
}

const handleCheckSyntax = async () => {
  if (!editedSourceCode.value) return
  syntaxChecking.value = true
  syntaxResult.value = null
  try {
    const res = await withToken((token) => checkPluginSyntax(editedSourceCode.value, token))
    if (!res) return
    if (res.valid) {
      syntaxResult.value = { valid: true, message: t('settings.pluginsSyntaxValid') }
      toast.success(t('settings.pluginsSyntaxValid'))
    } else {
      const msg = res.error || '语法错误'
      syntaxResult.value = { valid: false, message: msg }
      toast.error(msg)
    }
  } catch (err: unknown) {
    const msg = getLocalizedErrorMessage(err, t)
    syntaxResult.value = { valid: false, message: msg }
    toast.error(msg)
  } finally {
    syntaxChecking.value = false
  }
}

const showDiffView = ref(false)
const sourceDiffLines = computed<DiffLine[]>(() => {
  if (!showDiffView.value) return []
  return computeLineDiff(sourceCode.value, editedSourceCode.value)
})

const toggleDiffView = () => {
  showDiffView.value = !showDiffView.value
}

const handleCancelEditSource = async () => {
  if (editedSourceCode.value !== sourceCode.value) {
    const confirmed = await confirm({
      title: t('settings.pluginsUnsavedChangesTitle'),
      message: t('settings.pluginsUnsavedChangesMsg'),
      confirmText: t('settings.pluginsDiscardAndClose'),
      cancelText: t('common.cancel'),
      danger: true,
    })
    if (!confirmed) return
  }
  isEditingSource.value = false
  showDiffView.value = false
}

const handleCloseSourceModal = async () => {
  if (isEditingSource.value && editedSourceCode.value !== sourceCode.value) {
    const confirmed = await confirm({
      title: t('settings.pluginsUnsavedChangesTitle'),
      message: t('settings.pluginsUnsavedChangesMsg'),
      confirmText: t('settings.pluginsDiscardAndClose'),
      cancelText: t('common.cancel'),
      danger: true,
    })
    if (!confirmed) return
  }
  isSourceModalOpen.value = false
  isEditingSource.value = false
  showDiffView.value = false
}

const saveSourceCode = async (forceSave = false) => {
  if (!currentSourcePlugin.value) return
  savingSource.value = true
  try {
    const res = await withToken((token) => updatePluginSource(currentSourcePlugin.value!.name, editedSourceCode.value, token, forceSave))
    if (res) {
      sourceCode.value = editedSourceCode.value
      isEditingSource.value = false
      toast.success(t('settings.pluginsSaveSourceSuccess'))
      await loadPluginList()
    }
  } catch (err: unknown) {
    const errorObj = err as any
    const code = errorObj?.code || errorObj?.detail?.code || ''
    const msg = errorObj?.message || (typeof errorObj?.detail === 'string' ? errorObj.detail : errorObj?.detail?.message) || String(err)
    if (!forceSave && (code === 'PLUGIN_AUDIT_BLOCKED' || msg.includes('安全审查未通过') || msg.includes('高危') || msg.includes('critical'))) {
      const confirmed = await confirm({
        title: t('settings.pluginsAuditRiskAlertTitle'),
        message: `${msg}\n\n${t('settings.pluginsAuditRiskAlertConfirm')}`,
        confirmText: t('settings.pluginsAuditForceSave'),
        cancelText: t('common.cancel'),
        danger: true,
      })
      if (confirmed) {
        savingSource.value = false
        await saveSourceCode(true)
        return
      }
    }
    toast.error(`${t('settings.pluginsSaveSourceFailed')}: ${msg}`)
  } finally {
    savingSource.value = false
  }
}

const handleResetMetrics = async (plugin: PluginInfo) => {
  const confirmed = await confirm({
    title: t('settings.pluginsMetricsReset'),
    message: t('settings.pluginsMetricsResetConfirm', { name: plugin.name }),
    confirmText: t('settings.pluginsMetricsReset'),
    cancelText: t('common.cancel'),
    danger: true,
  })
  if (!confirmed) return
  resettingMetricsPlugin.value = plugin.name
  try {
    await withToken((token) => resetPluginMetrics(plugin.name, token))
    toast.success(t('settings.pluginsMetricsResetSuccess'))
    await loadPluginList()
  } catch (err: unknown) {
    const msg = getLocalizedErrorMessage(err, t)
    toast.error(`${t('settings.pluginsMetricsResetFailed')}: ${msg}`)
  } finally {
    resettingMetricsPlugin.value = null
  }
}

const copySourceCode = async () => {
  if (!sourceCode.value) return
  if (!(await copyToClipboard(sourceCode.value))) {
    toast.error(t('settings.pluginsSourceCopyFailed'))
    return
  }
  sourceCopied.value = true
  toast.success(t('settings.pluginsSourceCopied'))
  registerCopyTimer(() => {
    sourceCopied.value = false
  }, 2000)
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
    const msg = getLocalizedErrorMessage(err, t)
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
  if (createForm.value.template === 'basic_active' || createForm.value.template === 'http_api_fetcher') {
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
    const msg = getLocalizedErrorMessage(err, t)
    toast.error(`${t('settings.pluginsCreateFailed')}: ${msg}`)
  } finally {
    createLoading.value = false
  }
}

// 调试弹窗
const triggerUploadPlugin = () => {
  fileInputRef.value?.click()
}

const handleFileUpload = async (event: Event) => {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return

  const lowerName = file.name.toLowerCase()
  if (!lowerName.endsWith('.py') && !lowerName.endsWith('.zip')) {
    toast.error(`${t('settings.pluginsUploadFailed')}: ${t('settings.pluginsUploadTypeInvalid')}`)
    target.value = ''
    return
  }

  uploadingPlugin.value = true
  try {
    if (lowerName.endsWith('.zip')) {
      const res = await withToken((token) => importPluginsBundle(file, token))
      if (res) {
        toast.success(t('settings.pluginsImportBundleSuccess', { count: res.imported_count }))
        if (res.errors && res.errors.length) {
          toast.error(res.errors.join('; '))
        }
        await loadPluginList()
      }
    } else {
      await withToken((token) => uploadPlugin(file, token))
      toast.success(t('settings.pluginsUploadSuccess'))
      await loadPluginList()
    }
  } catch (err: unknown) {
    const msg = getLocalizedErrorMessage(err, t)
    toast.error(`${t('settings.pluginsUploadFailed')}: ${msg}`)
  } finally {
    uploadingPlugin.value = false
    target.value = ''
  }
}

const handleExportPlugin = async (plugin: PluginInfo) => {
  exportingPluginName.value = plugin.name
  try {
    const blob = await withToken((token) => exportPlugin(plugin.name, token))
    if (!blob) return
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${plugin.name}.py`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    toast.success(t('settings.pluginsExportSuccess'))
  } catch (err: unknown) {
    const msg = getLocalizedErrorMessage(err, t)
    toast.error(`${t('settings.pluginsExportFailed')}: ${msg}`)
  } finally {
    exportingPluginName.value = null
  }
}

const openTestModal = (plugin: PluginInfo) => {
  currentTestPlugin.value = plugin
  testResult.value = null
  resetStorage.value = false
  showAdvancedMock.value = false
  mockChatId.value = ''
  mockSenderName.value = ''
  mockTimeout.value = ''

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
  const testName = currentTestPlugin.value.name

  try {
    const res = await withToken((token) =>
      testPlugin(
        testName,
        {
          text: testInputText.value,
          params: testParams.value,
          reset_storage: resetStorage.value,
          chat_id: mockChatId.value ? mockChatId.value : undefined,
          sender_name: mockSenderName.value.trim() || undefined,
          // 输入钳制到后端契约上限，避免绕过 UI 约束
          timeout: mockTimeout.value ? Math.min(Number(mockTimeout.value), 300) : undefined,
        },
        token,
      ),
    )
    if (!res) return
    testResult.value = res
    saveTestSnapshot(testName, testInputText.value, testParams.value)
  } catch (err: unknown) {
    const msg = getLocalizedErrorMessage(err, t)
    // 仅当弹窗仍停留在发起请求的插件时才回填错误结果，防止过期覆盖
    if (currentTestPlugin.value?.name !== testName || !isTestModalOpen.value) return
    testResult.value = {
      name: testName,
      success: false,
      handled: false,
      isolation: undefined,
      killed: false,
      logs: [`[error] ${t('settings.pluginsTestApiError')}: ${msg}`],
      duration_ms: 0,
      error: msg,
    }
  } finally {
    testRunning.value = false
  }
}


// ==================== 插件市场 (Marketplace) 状态与逻辑 ====================
const activeTab = ref<'installed' | 'market'>('installed')
const marketCatalog = ref<MarketPluginItem[]>([])
const marketLoading = ref(false)
const marketCatalogError = ref<string | null>(null)
const marketSourceConfig = ref<MarketSourceConfig | null>(null)
const marketSourceType = ref<'github' | 'jsdelivr' | 'ghproxy' | 'local' | 'custom'>('github')
const marketCustomUrl = ref('')
const isSavingSource = ref(false)
const marketSearchQuery = ref('')
const marketSelectedCategory = ref('all')
const marketSelectedStatus = ref<'all' | 'not_installed' | 'installed' | 'upgradable'>('all')
const marketSortBy = ref<'default' | 'updated' | 'name' | 'status'>('default')
const installingPluginId = ref<string | null>(null)
const uninstallingPluginId = ref<string | null>(null)
const isUpdatingAll = ref(false)
const updateAllProgress = ref({ current: 0, total: 0, currentName: '' })

// 市场插件文档弹窗
const isMarketReadmeOpen = ref(false)
const marketReadmeTitle = ref('')
const marketReadmeContent = ref('')
const marketReadmePlugin = ref<MarketPluginItem | null>(null)
const loadingMarketReadme = ref(false)

async function fetchMarketCatalog(refresh = false) {
  marketLoading.value = true
  marketCatalogError.value = null
  try {
    await withToken(async (token) => {
      const res = await getMarketCatalog(token, refresh)
      marketCatalog.value = res.plugins
      if (!marketSourceConfig.value) {
        marketSourceConfig.value = {
          source_type: res.source_type as any,
          custom_url: '',
          active_url: res.source_url,
        }
        marketSourceType.value = res.source_type as any
      }
    })
  } catch (err: any) {
    const msg = err.message || t('settings.marketFetchFailed')
    marketCatalogError.value = msg
    toast.error(msg)
  } finally {
    marketLoading.value = false
  }
}

async function quickSwitchSource(newType: 'github' | 'jsdelivr' | 'ghproxy') {
  marketSourceType.value = newType
  await handleSourceChange()
}

const upgradableMarketPlugins = computed(() => {
  return marketCatalog.value.filter((p) => p.status === 'upgradable')
})

async function handleBatchUpdateAll() {
  const targets = upgradableMarketPlugins.value
  if (targets.length === 0 || isUpdatingAll.value) return

  const ok = await confirm({
    title: t('settings.marketUpdateAllConfirmTitle'),
    message: t('settings.marketUpdateAllConfirmMsg', { count: targets.length }),
    confirmText: t('settings.marketUpdateAllBtn', { count: targets.length }),
    cancelText: t('common.cancel'),
  })
  if (!ok) return

  isUpdatingAll.value = true
  updateAllProgress.value = { current: 0, total: targets.length, currentName: '' }
  let successCount = 0

  try {
    for (let i = 0; i < targets.length; i++) {
      const p = targets[i]
      updateAllProgress.value = { current: i + 1, total: targets.length, currentName: p.name }
      try {
        await withToken(async (token) => {
          await updateMarketPlugin(p.id, token)
        })
        successCount++
      } catch (err: any) {
        toast.error(`${p.name}: ${err.message || '更新失败'}`)
      }
    }
    if (successCount > 0) {
      toast.success(t('settings.marketUpdateAllSuccess', { count: successCount }))
      await Promise.all([loadPluginList(), fetchMarketCatalog(true)])
    }
  } finally {
    isUpdatingAll.value = false
    updateAllProgress.value = { current: 0, total: 0, currentName: '' }
  }
}

async function fetchMarketSource() {
  try {
    await withToken(async (token) => {
      const res = await getMarketSource(token)
      marketSourceConfig.value = res
      marketSourceType.value = res.source_type
      marketCustomUrl.value = res.custom_url || ''
    })
  } catch {
    // ignore
  }
}

async function handleSourceChange() {
  isSavingSource.value = true
  try {
    await withToken(async (token) => {
      const res = await updateMarketSource(
        marketSourceType.value,
        marketSourceType.value === 'custom' ? marketCustomUrl.value : undefined,
        token,
      )
      marketSourceConfig.value = res
      toast.success(t('settings.marketSourceSaveSuccess'))
      await fetchMarketCatalog(true)
    })
  } catch (err: any) {
    toast.error(err.message || '切换市场源失败')
  } finally {
    isSavingSource.value = false
  }
}

async function handleInstallMarketPlugin(item: MarketPluginItem) {
  installingPluginId.value = item.id
  try {
    await withToken(async (token) => {
      await installMarketPlugin(item.id, token)
      toast.success(t('settings.marketInstallSuccess', { name: item.name }))
      await Promise.all([loadPluginList(), fetchMarketCatalog(true)])
    })
  } catch (err: any) {
    toast.error(err.message || '安装插件失败')
  } finally {
    installingPluginId.value = null
  }
}

async function handleUpdateMarketPlugin(item: MarketPluginItem) {
  installingPluginId.value = item.id
  try {
    await withToken(async (token) => {
      await updateMarketPlugin(item.id, token)
      toast.success(t('settings.marketUpdateSuccess', { name: item.name }))
      await Promise.all([loadPluginList(), fetchMarketCatalog(true)])
    })
  } catch (err: any) {
    toast.error(err.message || '更新插件失败')
  } finally {
    installingPluginId.value = null
  }
}

async function handleUninstallMarketPlugin(item: MarketPluginItem) {
  const ok = await confirm({
    title: `${t('settings.marketUninstall')} ${item.name}`,
    message: `确定要卸载插件「${item.name}」吗？卸载后本地插件代码将被清除。`,
    confirmText: t('settings.marketUninstall'),
    cancelText: t('common.cancel'),
    danger: true,
  })
  if (!ok) return

  uninstallingPluginId.value = item.id
  try {
    await withToken(async (token) => {
      await uninstallMarketPlugin(item.id, token)
      toast.success(t('settings.marketUninstallSuccess', { name: item.name }))
      await Promise.all([loadPluginList(), fetchMarketCatalog(true)])
    })
  } catch (err: any) {
    toast.error(err.message || '卸载插件失败')
  } finally {
    uninstallingPluginId.value = null
  }
}

async function openMarketReadme(item: MarketPluginItem) {
  marketReadmePlugin.value = item
  marketReadmeTitle.value = item.name
  marketReadmeContent.value = item.readme || ''
  isMarketReadmeOpen.value = true
  if (!item.readme) {
    loadingMarketReadme.value = true
    try {
      await withToken(async (token) => {
        const res = await getMarketPluginReadme(item.id, token)
        marketReadmeContent.value = res.readme
      })
    } catch {
      marketReadmeContent.value = `# ${item.name}\n\n${item.description}`
    } finally {
      loadingMarketReadme.value = false
    }
  }
}

function switchTab(tab: 'installed' | 'market') {
  activeTab.value = tab
  if (tab === 'market' && marketCatalog.value.length === 0) {
    fetchMarketCatalog()
    fetchMarketSource()
  }
}

const filteredMarketPlugins = computed(() => {
  const list = marketCatalog.value.filter((p) => {
    if (marketSearchQuery.value.trim()) {
      const q = marketSearchQuery.value.toLowerCase().trim()
      const match =
        p.name.toLowerCase().includes(q) ||
        p.id.toLowerCase().includes(q) ||
        (p.description && p.description.toLowerCase().includes(q)) ||
        (p.author && p.author.toLowerCase().includes(q)) ||
        (p.tags && p.tags.some((t) => t.toLowerCase().includes(q)))
      if (!match) return false
    }
    if (marketSelectedCategory.value !== 'all') {
      if (p.category !== marketSelectedCategory.value) return false
    }
    if (marketSelectedStatus.value !== 'all') {
      if (p.status !== marketSelectedStatus.value) return false
    }
    return true
  })

  if (marketSortBy.value === 'updated') {
    return [...list].sort((a, b) => (b.updated_at || '').localeCompare(a.updated_at || ''))
  } else if (marketSortBy.value === 'name') {
    return [...list].sort((a, b) => a.name.localeCompare(b.name))
  } else if (marketSortBy.value === 'status') {
    const statusOrder: Record<string, number> = { upgradable: 0, not_installed: 1, installed: 2 }
    return [...list].sort((a, b) => (statusOrder[a.status] ?? 3) - (statusOrder[b.status] ?? 3))
  }
  return list
})

onMounted(() => {
  document.addEventListener('click', handleDocumentClick)
  void loadPluginList()
})

onBeforeUnmount(() => {
  document.removeEventListener('click', handleDocumentClick)
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
          class="ui-btn-secondary shrink-0 !px-3 !py-1 !text-xs inline-flex items-center gap-1.5 text-slate-700 dark:text-slate-300 hover:text-slate-900"
          :disabled="exportingManifest"
          :title="t('settings.pluginsExportManifest')"
          @click="handleExportManifest"
        >
          <RefreshCw v-if="exportingManifest" class="w-3.5 h-3.5 animate-spin" />
          <FileText v-else class="w-3.5 h-3.5" />
          {{ exportingManifest ? t('common.loading') : t('settings.pluginsExportManifest') }}
        </button>
        <button
          type="button"
          class="ui-btn-secondary shrink-0 !px-3 !py-1 !text-xs inline-flex items-center gap-1.5 text-amber-600 dark:text-amber-400 hover:text-amber-700"
          :disabled="exportingAll"
          @click="handleExportAll"
        >
          <RefreshCw v-if="exportingAll" class="w-3.5 h-3.5 animate-spin" />
          <Archive v-else class="w-3.5 h-3.5" />
          {{ exportingAll ? t('common.loading') : t('settings.pluginsExportAll') }}
        </button>
        <button
          type="button"
          class="ui-btn-secondary shrink-0 !px-3 !py-1 !text-xs inline-flex items-center gap-1.5 text-blue-600 dark:text-blue-400 hover:text-blue-700"
          :disabled="uploadingPlugin"
          @click="triggerUploadPlugin"
        >
          <RefreshCw v-if="uploadingPlugin" class="w-3.5 h-3.5 animate-spin" />
          <Upload v-else class="w-3.5 h-3.5" />
          {{ uploadingPlugin ? t('settings.pluginsReloading') : t('settings.pluginsUpload') }}
        </button>
        <input
          ref="fileInputRef"
          type="file"
          accept=".py,.zip"
          class="hidden"
          @change="handleFileUpload"
        />
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

    <!-- 顶部主标签页切换：已安装插件 / 插件市场 -->
    <div class="flex items-center gap-2 border-b border-gray-200 dark:border-gray-800/80 mb-5">
      <button
        type="button"
        class="pb-2.5 px-3 text-xs font-medium border-b-2 flex items-center gap-2 transition-colors"
        :class="activeTab === 'installed'
          ? 'border-indigo-600 text-indigo-600 dark:border-indigo-400 dark:text-indigo-400 font-semibold'
          : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'"
        @click="activeTab = 'installed'"
      >
        <Puzzle class="w-3.5 h-3.5" />
        {{ t('settings.pluginsTabInstalled') }}
        <span class="ml-1 px-1.5 py-0.2 text-[10px] rounded-full bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 font-mono">
          {{ plugins.length }}
        </span>
      </button>
      <button
        type="button"
        class="pb-2.5 px-3 text-xs font-medium border-b-2 flex items-center gap-2 transition-colors"
        :class="activeTab === 'market'
          ? 'border-indigo-600 text-indigo-600 dark:border-indigo-400 dark:text-indigo-400 font-semibold'
          : 'border-transparent text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200'"
        @click="switchTab('market')"
      >
        <Store class="w-3.5 h-3.5" />
        {{ t('settings.pluginsTabMarket') }}
        <span
          v-if="marketCatalog.length > 0"
          class="ml-1 px-1.5 py-0.2 text-[10px] rounded-full bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 font-medium font-mono"
        >
          {{ marketCatalog.length }}
        </span>
      </button>
    </div>

    <!-- 标签内容区：已安装插件 -->
    <div v-if="activeTab === 'installed'">

    <!-- 插件健康与依赖诊断警示面板 -->
    <div
      v-if="loadErrors.length > 0"
      class="mb-4 rounded-lg border border-amber-300 dark:border-amber-700/70 bg-amber-50/80 dark:bg-amber-950/30 p-3.5 text-xs transition-all"
    >
      <div class="flex items-center justify-between gap-2 flex-wrap">
        <div class="flex items-center gap-2 font-medium text-amber-800 dark:text-amber-300">
          <AlertTriangle class="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0" />
          <span>{{ t('settings.pluginsDiagTitle', { count: loadErrors.length }) }}</span>
        </div>
        <button
          type="button"
          class="ui-btn-secondary !py-0.5 !px-2 !text-[11px] inline-flex items-center gap-1 text-amber-700 dark:text-amber-300 border-amber-300 dark:border-amber-700/80"
          @click="isDiagOpen = !isDiagOpen"
        >
          <span>{{ isDiagOpen ? t('settings.pluginsDiagHide') : t('settings.pluginsDiagShow') }}</span>
          <ChevronUp v-if="isDiagOpen" class="w-3 h-3" />
          <ChevronDown v-else class="w-3 h-3" />
        </button>
      </div>

      <div v-if="isDiagOpen" class="mt-3 pt-3 border-t border-amber-200 dark:border-amber-800/60 space-y-2.5">
        <div
          v-for="(err, idx) in loadErrors"
          :key="idx"
          class="p-2.5 rounded bg-white/70 dark:bg-black/30 border border-amber-200/80 dark:border-amber-900/50 flex flex-col sm:flex-row sm:items-center justify-between gap-2 font-mono text-[11px]"
        >
          <div class="min-w-0 space-y-1">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="font-bold text-amber-900 dark:text-amber-200 font-sans">{{ err.plugin_name }}</span>
              <span
                class="px-1.5 py-0.2 rounded text-[10px]"
                :class="err.error_type === 'missing_dependency' ? 'bg-rose-100 dark:bg-rose-950 text-rose-700 dark:text-rose-300' : 'bg-amber-100 dark:bg-amber-900 text-amber-700 dark:text-amber-300'"
              >
                {{ err.error_type === 'missing_dependency' ? t('settings.pluginsDiagMissingDep') : (err.error_type === 'syntax_error' ? t('settings.pluginsDiagSyntaxErr') : t('settings.pluginsDiagLoadErr')) }}
              </span>
              <span class="text-[10px] text-gray-400 truncate max-w-xs">{{ err.file_path }}</span>
            </div>
            <div class="text-gray-600 dark:text-gray-400 font-sans text-xs">
              {{ err.error_message }}
            </div>
          </div>

          <div v-if="err.suggested_command" class="flex items-center gap-2 shrink-0">
            <code class="px-2 py-1 rounded bg-gray-900 text-amber-300 text-[11px]">
              {{ err.suggested_command }}
            </code>
            <button
              type="button"
              class="ui-btn-secondary !py-1 !px-2 !text-[11px] inline-flex items-center gap-1 shrink-0"
              @click="copyInstallCommand(err.suggested_command, idx)"
            >
              <Check v-if="copiedDiagIndex === idx" class="w-3 h-3 text-emerald-500" />
              <Copy v-else class="w-3 h-3" />
              <span>{{ copiedDiagIndex === idx ? t('settings.pluginsDiagCopied') : t('settings.pluginsDiagCopyCmd') }}</span>
            </button>
          </div>
        </div>
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

    <!-- 搜索与筛选工具条 -->
    <div class="mb-4 space-y-2.5">
      <!-- 第一行：搜索框与右侧排序选择，水平等高严格对齐 -->
      <div class="flex items-center justify-between gap-3">
        <div class="relative flex-1 max-w-sm">
          <Search class="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
          <input
            v-model="searchQuery"
            type="text"
            :placeholder="t('settings.pluginsSearchPlaceholder')"
            class="ui-input !pl-8 !h-8 !text-xs w-full"
          />
        </div>

        <select
          v-model="sortBy"
          aria-label="排序方式"
          class="ui-input !h-8 !text-xs !px-2.5 !py-0 !w-36 shrink-0 bg-gray-50/50 dark:bg-gray-900/50 border-gray-200 dark:border-gray-800"
        >
          <option value="default">{{ t('settings.pluginsSortDefault') }}</option>
          <option value="runs">{{ t('settings.pluginsSortRuns') }}</option>
          <option value="success_rate">{{ t('settings.pluginsSortSuccessRate') }}</option>
          <option value="duration">{{ t('settings.pluginsSortDuration') }}</option>
          <option value="name">{{ t('settings.pluginsSortName') }}</option>
        </select>
      </div>

      <!-- 第二行：维度过滤与批量操作工具组 -->
      <div class="flex items-center justify-between gap-2 flex-wrap text-xs">
        <div class="flex items-center gap-2 flex-wrap">
          <!-- 模式筛选 -->
          <div class="inline-flex rounded-lg border border-gray-200 dark:border-gray-800 p-0.5 bg-gray-50/50 dark:bg-gray-900/50">
            <button
              type="button"
              class="px-2 py-1 rounded text-[11px] font-medium transition-colors"
              :class="filterMode === 'all' ? 'bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 shadow-sm' : 'text-gray-500 hover:text-gray-900 dark:hover:text-gray-300'"
              @click="filterMode = 'all'"
            >
              {{ t('settings.pluginsFilterAll') }}
            </button>
            <button
              type="button"
              class="px-2 py-1 rounded text-[11px] font-medium transition-colors"
              :class="filterMode === 'reactive' ? 'bg-white dark:bg-gray-800 text-sky-600 dark:text-sky-400 shadow-sm' : 'text-gray-500 hover:text-gray-900 dark:hover:text-gray-300'"
              @click="filterMode = 'reactive'"
            >
              {{ t('settings.pluginsFilterReactive') }}
            </button>
            <button
              type="button"
              class="px-2 py-1 rounded text-[11px] font-medium transition-colors"
              :class="filterMode === 'active' ? 'bg-white dark:bg-gray-800 text-emerald-600 dark:text-emerald-400 shadow-sm' : 'text-gray-500 hover:text-gray-900 dark:hover:text-gray-300'"
              @click="filterMode = 'active'"
            >
              {{ t('settings.pluginsFilterActive') }}
            </button>
          </div>

          <!-- 来源筛选 -->
          <div class="inline-flex rounded-lg border border-gray-200 dark:border-gray-800 p-0.5 bg-gray-50/50 dark:bg-gray-900/50">
            <button
              type="button"
              class="px-2 py-1 rounded text-[11px] font-medium transition-colors"
              :class="filterType === 'all' ? 'bg-white dark:bg-gray-800 text-gray-900 dark:text-gray-100 shadow-sm' : 'text-gray-500 hover:text-gray-900 dark:hover:text-gray-300'"
              @click="filterType = 'all'"
            >
              {{ t('settings.pluginsFilterAll') }}
            </button>
            <button
              type="button"
              class="px-2 py-1 rounded text-[11px] font-medium transition-colors"
              :class="filterType === 'builtin' ? 'bg-white dark:bg-gray-800 text-purple-600 dark:text-purple-400 shadow-sm' : 'text-gray-500 hover:text-gray-900 dark:hover:text-gray-300'"
              @click="filterType = 'builtin'"
            >
              {{ t('settings.pluginsFilterBuiltin') }}
            </button>
            <button
              type="button"
              class="px-2 py-1 rounded text-[11px] font-medium transition-colors"
              :class="filterType === 'custom' ? 'bg-white dark:bg-gray-800 text-blue-600 dark:text-blue-400 shadow-sm' : 'text-gray-500 hover:text-gray-900 dark:hover:text-gray-300'"
              @click="filterType = 'custom'"
            >
              {{ t('settings.pluginsFilterCustom') }}
            </button>
          </div>

          <!-- 仅在存在异常/告警插件时动态出现的快速过滤胶囊 -->
          <button
            v-if="issuePluginsCount > 0"
            type="button"
            class="px-2 py-1 rounded-lg text-[11px] font-medium transition-colors border inline-flex items-center gap-1.5"
            :class="filterType === 'issue' ? 'bg-rose-50 dark:bg-rose-950/50 text-rose-600 dark:text-rose-400 border-rose-300 dark:border-rose-800 shadow-sm' : 'text-rose-600 dark:text-rose-400 bg-rose-50/40 dark:bg-rose-950/20 border-rose-200 dark:border-rose-900/60 hover:bg-rose-100 dark:hover:bg-rose-900/40'"
            @click="filterType = filterType === 'issue' ? 'all' : 'issue'"
          >
            <span>⚠️</span>
            <span>{{ t('settings.pluginsFilterTabIssue') }}</span>
            <span class="px-1 py-0.2 rounded-full text-[10px] bg-rose-200/80 dark:bg-rose-900 text-rose-700 dark:text-rose-200 font-bold leading-tight">
              {{ issuePluginsCount }}
            </span>
          </button>
        </div>

        <!-- 批量管理与指标复位 -->
        <div class="inline-flex items-center rounded-lg border border-gray-200 dark:border-gray-800 p-0.5 bg-gray-50/50 dark:bg-gray-900/50">
          <button
            type="button"
            class="px-2 py-1 rounded text-[11px] font-medium text-emerald-600 dark:text-emerald-400 hover:bg-white dark:hover:bg-gray-800 transition-colors disabled:opacity-50"
            :disabled="batchToggling"
            @click="handleBatchToggle(true)"
          >
            {{ t('settings.pluginsBatchEnable') }}
          </button>
          <button
            type="button"
            class="px-2 py-1 rounded text-[11px] font-medium text-gray-500 hover:text-gray-900 dark:hover:text-gray-300 hover:bg-white dark:hover:bg-gray-800 transition-colors disabled:opacity-50"
            :disabled="batchToggling"
            @click="handleBatchToggle(false)"
          >
            {{ t('settings.pluginsBatchDisable') }}
          </button>
          <button
            type="button"
            class="px-2 py-1 rounded text-[11px] font-medium text-amber-600 dark:text-amber-400 hover:bg-white dark:hover:bg-gray-800 transition-colors disabled:opacity-50 inline-flex items-center"
            :title="t('settings.pluginsResetAllMetrics')"
            :aria-label="t('settings.pluginsResetAllMetrics')"
            :disabled="resettingAllMetrics"
            @click="handleResetAllMetrics"
          >
            <RotateCcw class="w-3 h-3" :class="{ 'animate-spin': resettingAllMetrics }" />
          </button>
        </div>
      </div>

      <!-- 第三行：分类筛选 -->
      <div class="flex items-center gap-1.5 flex-wrap pt-1">
        <button
          v-for="cat in availableCategories"
          :key="cat.key"
          type="button"
          class="px-2.5 py-0.5 rounded-full text-[11px] font-medium transition-all"
          :class="filterCategory === cat.key
            ? 'bg-indigo-600 text-white shadow-xs font-semibold'
            : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-200 dark:hover:bg-gray-700'"
          @click="filterCategory = cat.key"
        >
          <span>{{ cat.label }}</span>
          <span v-if="cat.count !== undefined" class="ml-1 opacity-80 font-mono text-[10px]">
            {{ cat.count }}
          </span>
        </button>
      </div>
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
        v-for="plugin in filteredPlugins"
        :key="plugin.name"
        class="p-3 border rounded flex flex-col xl:flex-row xl:items-center justify-between gap-3 text-xs transition-colors"
        :class="plugin.enabled !== false
          ? 'border-gray-100 dark:border-gray-800/60 bg-gray-50/60 dark:bg-white/[0.02] hover:border-gray-300 dark:hover:border-gray-700'
          : 'border-dashed border-gray-300 dark:border-gray-700/60 bg-gray-100/40 dark:bg-white/[0.01] opacity-75'"
      >
        <div class="min-w-0 flex-1 space-y-1.5">
          <!-- 第一排：统一固定显示「插件名称 + 官方内置/自定义 + 版本号 + 停用状态」 -->
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
          </div>

          <!-- 第二排：统一以「执行模式标签（reactive/active）」开头，后接参数配置、更新日期等元数据 -->
          <div class="flex items-center gap-2 flex-wrap text-gray-500">
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
            <span
              v-if="plugin.permissions && plugin.permissions.length"
              class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-purple-50 dark:bg-purple-950/80 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800/50"
              :title="plugin.permissions.join(', ')"
            >
              {{ t('settings.pluginsPermissions') }}: {{ plugin.permissions.join(', ') }}
            </span>
            <span
              v-if="plugin.category"
              class="px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-50 dark:bg-blue-950/80 text-blue-700 dark:text-blue-300 border border-blue-200 dark:border-blue-800/50"
            >
              {{ plugin.category }}
            </span>
            <span
              v-for="tag in (plugin.tags || [])"
              :key="tag"
              class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-gray-100 dark:bg-gray-800 text-gray-500 dark:text-gray-400"
            >
              #{{ tag }}
            </span>
            <a
              v-if="isValidHttpUrl(plugin.homepage)"
              :href="plugin.homepage || undefined"
              target="_blank"
              rel="noopener noreferrer"
              class="text-[10px] text-indigo-600 dark:text-indigo-400 inline-flex items-center gap-0.5 hover:underline"
              :title="plugin.homepage || undefined"
            >
              <Globe class="w-3 h-3" />
              <span>{{ t('settings.pluginsHomepage') }}</span>
            </a>
          </div>
          <p class="text-gray-600 dark:text-gray-300 text-[11px] leading-relaxed">
            {{ plugin.description || t('settings.pluginsNoDesc') }}
          </p>
          <div v-if="plugin.source_path" class="text-[10px] text-gray-400 dark:text-gray-500 font-mono truncate max-w-lg">
            {{ plugin.source_path }}
          </div>

          <!-- 运行统计指标 -->
          <div
            v-if="plugin.metrics && (plugin.metrics.run_count > 0 || plugin.metrics.last_error)"
            class="mt-2 pt-1.5 border-t border-gray-200/50 dark:border-gray-800/50 flex flex-col gap-1.5"
          >
            <div class="flex items-center flex-wrap gap-2 text-[11px]">
            <span class="inline-flex items-center gap-1 font-mono text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded">
              <Activity class="w-3 h-3 text-blue-500" />
              {{ t('settings.pluginsMetricsRuns', { n: plugin.metrics.run_count }) }}
            </span>
            <span
              class="inline-flex items-center gap-1 font-mono px-1.5 py-0.5 rounded font-medium"
              :class="plugin.metrics.success_rate >= 95
                ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800/40'
                : 'bg-rose-50 text-rose-600 dark:bg-rose-950/50 dark:text-rose-400 border border-rose-200 dark:border-rose-800/40'"
            >
              {{ t('settings.pluginsMetricsSuccess', { rate: plugin.metrics.success_rate }) }}
            </span>
            <span class="inline-flex items-center gap-1 font-mono text-gray-600 dark:text-gray-300 bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded">
              <Clock class="w-3 h-3 text-amber-500" />
              {{ t('settings.pluginsMetricsAvg', { ms: plugin.metrics.avg_duration_ms }) }}
            </span>
            <span v-if="plugin.metrics.last_run_at" class="text-[10px] text-gray-400 dark:text-gray-500 font-mono">
              {{ t('settings.pluginsMetricsLastRun', { time: plugin.metrics.last_run_at.slice(11, 19) }) }}
            </span>
            <button
              type="button"
              class="ml-auto text-gray-400 hover:text-rose-500 transition-colors p-0.5"
              :title="t('settings.pluginsMetricsReset')"
              :disabled="resettingMetricsPlugin === plugin.name"
              @click.stop="handleResetMetrics(plugin)"
            >
              <RotateCcw class="w-3 h-3" :class="{ 'animate-spin': resettingMetricsPlugin === plugin.name }" />
            </button>
            </div>
            <!-- 运行健康度双色进度条 -->
            <div
              v-if="plugin.metrics.run_count > 0"
              class="w-full bg-rose-200 dark:bg-rose-950/80 rounded-full h-1 overflow-hidden flex"
              :title="`成功: ${plugin.metrics.success_count} / 失败: ${plugin.metrics.failure_count}`"
            >
              <div
                class="bg-emerald-500 h-full transition-all duration-300"
                :style="{ width: `${plugin.metrics.success_rate}%` }"
              />
            </div>
            <!-- 近期调用脉冲 -->
            <div
              v-if="plugin.recent_results && plugin.recent_results.length > 0"
              class="flex items-center gap-1 py-0.5"
              :title="t('settings.pluginsRecentRunsPulse')"
            >
              <span class="text-[10px] text-gray-400 font-mono mr-1">{{ t('settings.pluginsRecentRunsPulseLabel') }}:</span>
              <span
                v-for="(res, rIdx) in plugin.recent_results"
                :key="rIdx"
                class="w-2 h-2 rounded-full inline-block transition-transform hover:scale-125"
                :class="res ? 'bg-emerald-500 shadow-sm shadow-emerald-500/30' : 'bg-rose-500 shadow-sm shadow-rose-500/30'"
              />
            </div>

            <div
              v-if="plugin.metrics.last_error"
              class="text-[10px] text-rose-600 dark:text-rose-400 bg-rose-50/80 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/50 rounded px-2 py-0.5 flex items-start gap-1 font-mono break-all"
              :title="plugin.metrics.last_error"
            >
              <AlertCircle class="w-3 h-3 shrink-0 mt-0.5" />
              <span class="truncate max-w-xl">{{ t('settings.pluginsMetricsLastError') }}: {{ plugin.metrics.last_error }}</span>
            </div>
          </div>
        </div>

        <div class="shrink-0 flex items-center gap-1.5 flex-wrap">
          <!-- 启用/停用软开关 -->
          <button
            type="button"
            class="ui-btn-secondary !py-1 !px-2.5 !text-xs inline-flex items-center gap-1 transition-colors"
            :class="plugin.enabled !== false ? 'text-emerald-600 dark:text-emerald-400 hover:text-emerald-700 bg-emerald-50/40 dark:bg-emerald-950/20 border-emerald-200 dark:border-emerald-800/50' : 'text-gray-400 dark:text-gray-500 hover:text-gray-600'"
            :disabled="togglingPluginName === plugin.name"
            @click="handleToggle(plugin)"
          >
            <RefreshCw v-if="togglingPluginName === plugin.name" class="w-3 h-3 animate-spin" />
            <Power v-else class="w-3 h-3" />
            {{ plugin.enabled !== false ? t('settings.pluginsEnabled') : t('settings.pluginsDisabled') }}
          </button>

          <!-- 调试 -->
          <button
            type="button"
            class="ui-btn-secondary !py-1 !px-2.5 !text-xs inline-flex items-center gap-1 text-sky-600 dark:text-sky-400 hover:text-sky-700 bg-sky-50/50 dark:bg-sky-950/30 border-sky-200 dark:border-sky-800/60 hover:bg-sky-100 dark:hover:bg-sky-900/40 font-medium"
            @click="openTestModal(plugin)"
          >
            <Play class="w-3 h-3 fill-current" />
            {{ t('settings.pluginsPlaygroundBtn') }}
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

          <!-- 数据存储 -->
          <button
            type="button"
            class="ui-btn-secondary !py-1 !px-2.5 !text-xs inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400 hover:text-emerald-700 bg-emerald-50/50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800/60 hover:bg-emerald-100 dark:hover:bg-emerald-900/40 font-medium"
            :title="t('settings.pluginsStorageBtn')"
            @click="openStorageModal(plugin)"
          >
            <Database class="w-3 h-3" />
            {{ t('settings.pluginsStorageBtn') }}
          </button>

          <!-- 更多操作下拉菜单 -->
          <div class="relative plugin-more-dropdown-container">
            <button
              type="button"
              class="ui-btn-secondary !py-1 !px-2 !text-xs inline-flex items-center gap-1 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
              :title="t('settings.pluginsCardMoreActions')"
              @click.stop="toggleMoreDropdown(plugin.name)"
            >
              <MoreHorizontal class="w-3.5 h-3.5" />
            </button>

            <div
              v-show="activeMoreDropdownPlugin === plugin.name"
              class="absolute right-0 top-full mt-1 w-36 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg py-1 z-30 text-xs flex flex-col"
            >
              <!-- 调用历史 -->
              <button
                type="button"
                class="w-full text-left px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-700/60 flex items-center gap-2 text-indigo-600 dark:text-indigo-400"
                :title="t('settings.pluginsHistoryBtn')"
                @click="openHistoryModal(plugin); activeMoreDropdownPlugin = null"
              >
                <History class="w-3.5 h-3.5" />
                <span>{{ t('settings.pluginsHistoryBtn') }}</span>
              </button>

              <!-- 说明文档 -->
              <button
                v-if="plugin.doc"
                type="button"
                class="w-full text-left px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-700/60 flex items-center gap-2 text-teal-600 dark:text-teal-400"
                :title="t('settings.pluginsViewDoc')"
                @click="openDocModal(plugin); activeMoreDropdownPlugin = null"
              >
                <BookOpen class="w-3.5 h-3.5" />
                <span>{{ t('settings.pluginsViewDoc') }}</span>
              </button>

              <!-- 克隆 -->
              <button
                type="button"
                class="w-full text-left px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-700/60 flex items-center gap-2 text-purple-600 dark:text-purple-400"
                :title="t('settings.pluginsCloneBtn')"
                @click="openCloneModal(plugin); activeMoreDropdownPlugin = null"
              >
                <Copy class="w-3.5 h-3.5" />
                <span>{{ t('settings.pluginsCloneBtn') }}</span>
              </button>

              <!-- 导出源码 -->
              <button
                type="button"
                class="w-full text-left px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-700/60 flex items-center gap-2 text-slate-600 dark:text-slate-400"
                :disabled="exportingPluginName === plugin.name"
                :title="t('settings.pluginsExport')"
                @click="handleExportPlugin(plugin); activeMoreDropdownPlugin = null"
              >
                <RefreshCw v-if="exportingPluginName === plugin.name" class="w-3.5 h-3.5 animate-spin" />
                <Download v-else class="w-3.5 h-3.5" />
                <span>{{ t('settings.pluginsExport') }}</span>
              </button>

              <!-- 删除（仅自定义插件） -->
              <div v-if="!plugin.builtin" class="border-t border-gray-100 dark:border-gray-700 my-0.5"></div>
              <button
                v-if="!plugin.builtin"
                type="button"
                class="w-full text-left px-3 py-1.5 hover:bg-rose-50 dark:hover:bg-rose-950/40 flex items-center gap-2 text-rose-600 dark:text-rose-400"
                :disabled="deletingPluginName === plugin.name"
                :title="t('common.delete')"
                @click="handleDelete(plugin); activeMoreDropdownPlugin = null"
              >
                <RefreshCw v-if="deletingPluginName === plugin.name" class="w-3.5 h-3.5 animate-spin" />
                <Trash2 v-else class="w-3.5 h-3.5" />
                <span>{{ t('common.delete') }}</span>
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div
      v-if="!loading && plugins.length > 0 && filteredPlugins.length === 0"
      class="p-8 text-center text-xs text-gray-400 border border-dashed border-gray-200 dark:border-gray-800 rounded-lg"
    >
      {{ t('settings.pluginsEmptyFilter') }}
    </div>    </div>

    <!-- 标签内容区：插件市场 -->
    <div v-else-if="activeTab === 'market'" class="space-y-4">
      <!-- 市场源切换与贡献入口工具条 -->
      <div class="flex flex-col md:flex-row md:items-center justify-between gap-3 p-3 bg-slate-50/80 dark:bg-slate-900/40 rounded-lg border border-slate-200/70 dark:border-slate-800/60">
        <div class="flex items-center gap-2 flex-wrap text-xs">
          <Globe class="w-4 h-4 text-indigo-500 shrink-0" />
          <span class="font-medium text-slate-700 dark:text-slate-300">{{ t('settings.marketSourceLabel') }}:</span>
          <select
            v-model="marketSourceType"
            class="ui-input !py-1 !px-2 !text-xs !w-auto bg-white dark:bg-slate-800"
            @change="handleSourceChange"
          >
            <option value="github">{{ t('settings.marketSourceGithub') }}</option>
            <option value="jsdelivr">{{ t('settings.marketSourceJsdelivr') }}</option>
            <option value="ghproxy">{{ t('settings.marketSourceGhproxy') }}</option>
            <option value="local">{{ t('settings.marketSourceLocal') }}</option>
            <option value="custom">{{ t('settings.marketSourceCustom') }}</option>
          </select>
          <div v-if="marketSourceType === 'custom'" class="flex items-center gap-1">
            <input
              v-model="marketCustomUrl"
              type="text"
              placeholder="https://.../marketplace.json"
              class="ui-input !py-1 !px-2 !text-xs !w-56"
            />
            <button
              type="button"
              class="ui-btn-primary !px-2 !py-1 !text-xs"
              :disabled="isSavingSource"
              @click="handleSourceChange"
            >
              <Save class="w-3 h-3" />
            </button>
          </div>
          <span v-if="marketSourceConfig?.active_url" class="text-[10px] text-slate-400 truncate max-w-xs hidden sm:inline" :title="marketSourceConfig.active_url">
            ({{ marketSourceConfig.active_url }})
          </span>
        </div>

        <div class="flex items-center gap-2 shrink-0">
          <button
            v-if="upgradableMarketPlugins.length > 0"
            type="button"
            class="ui-btn-primary !px-2.5 !py-1 !text-xs !bg-amber-600 hover:!bg-amber-700 inline-flex items-center gap-1.5 shadow-xs"
            :disabled="isUpdatingAll || marketLoading"
            @click="handleBatchUpdateAll"
          >
            <RefreshCw v-if="isUpdatingAll" class="w-3.5 h-3.5 animate-spin" />
            <Sparkles v-else class="w-3.5 h-3.5" />
            <span>
              {{ isUpdatingAll
                ? `${t('settings.marketUpdating')} (${updateAllProgress.current}/${updateAllProgress.total})`
                : t('settings.marketUpdateAllBtn', { count: upgradableMarketPlugins.length }) }}
            </span>
          </button>
          <a
            href="https://github.com/Silentely/TG-SignPulse/tree/dev/community_plugins"
            target="_blank"
            rel="noopener noreferrer"
            class="ui-btn-secondary !px-2.5 !py-1 !text-xs inline-flex items-center gap-1.5 text-indigo-600 dark:text-indigo-400 hover:text-indigo-700"
            :title="t('settings.marketContributeTooltip')"
          >
            <ExternalLink class="w-3.5 h-3.5" />
            {{ t('settings.marketContributeBtn') }}
          </a>
          <button
            type="button"
            class="ui-btn-secondary !px-2.5 !py-1 !text-xs inline-flex items-center gap-1.5"
            :disabled="marketLoading"
            @click="fetchMarketCatalog(true)"
          >
            <RefreshCw class="w-3.5 h-3.5" :class="marketLoading ? 'animate-spin' : ''" />
            {{ t('settings.pluginsReload') }}
          </button>
        </div>
      </div>

      <!-- 搜索与筛选控制栏 -->
      <div class="flex flex-col lg:flex-row gap-3 items-start lg:items-center justify-between">
        <!-- 搜索框 -->
        <div class="relative w-full sm:w-72">
          <Search class="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            v-model="marketSearchQuery"
            type="text"
            class="ui-input !pl-8 !py-1.5 !text-xs w-full"
            :placeholder="t('settings.marketSearchPlaceholder')"
          />
        </div>

        <div class="flex items-center gap-3 flex-wrap w-full lg:w-auto justify-between lg:justify-end">
          <!-- 排序选择 -->
          <div class="flex items-center gap-1.5 text-xs text-gray-500">
            <span class="text-[11px] shrink-0">{{ t('settings.marketSortLabel') }}:</span>
            <select
              v-model="marketSortBy"
              class="ui-input !py-1 !px-2 !text-xs !w-auto"
            >
              <option value="default">{{ t('settings.marketSortDefault') }}</option>
              <option value="updated">{{ t('settings.marketSortUpdated') }}</option>
              <option value="name">{{ t('settings.marketSortName') }}</option>
              <option value="status">{{ t('settings.marketSortStatus') }}</option>
            </select>
          </div>

          <!-- 状态过滤器 -->
          <div class="flex items-center gap-1 flex-wrap text-xs">
            <button
              v-for="st in [
                { key: 'all', label: t('settings.marketStatusAll') },
                { key: 'not_installed', label: t('settings.marketStatusNotInstalled') },
                { key: 'installed', label: t('settings.marketStatusInstalled') },
                { key: 'upgradable', label: upgradableMarketPlugins.length ? `${t('settings.marketStatusUpgradable')} (${upgradableMarketPlugins.length})` : t('settings.marketStatusUpgradable') },
              ]"
              :key="st.key"
              type="button"
              class="px-2.5 py-1 rounded-full text-xs transition-colors"
              :class="marketSelectedStatus === st.key
                ? 'bg-indigo-600 text-white font-medium'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700'"
              @click="marketSelectedStatus = st.key as any"
            >
              {{ st.label }}
            </button>
          </div>
        </div>
      </div>

      <!-- 分类标签过滤器 -->
      <div class="flex items-center gap-1.5 flex-wrap text-xs pb-1">
        <button
          v-for="cat in [
            { key: 'all', label: t('settings.marketCategoryAll') },
            { key: 'utility', label: t('settings.marketCategoryUtility') },
            { key: 'notification', label: t('settings.marketCategoryNotification') },
            { key: 'message', label: t('settings.marketCategoryMessage') },
            { key: 'captcha', label: t('settings.marketCategoryCaptcha') },
            { key: 'helper', label: t('settings.marketCategoryHelper') },
            { key: 'entertainment', label: t('settings.marketCategoryEntertainment') },
          ]"
          :key="cat.key"
          type="button"
          class="px-2 py-0.5 rounded text-[11px] transition-colors"
          :class="marketSelectedCategory === cat.key
            ? 'bg-slate-800 text-white dark:bg-slate-200 dark:text-slate-900 font-medium'
            : 'text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800'"
          @click="marketSelectedCategory = cat.key"
        >
          {{ cat.label }}
        </button>
      </div>

      <!-- 镜像源网络拉取异常提示与快速切换 -->
      <div v-if="marketCatalogError && marketCatalog.length === 0" class="p-4 rounded-lg border border-rose-200 dark:border-rose-900/50 bg-rose-50/60 dark:bg-rose-950/20 text-xs space-y-2.5">
        <div class="flex items-start gap-2.5">
          <AlertCircle class="w-4 h-4 text-rose-600 dark:text-rose-400 shrink-0 mt-0.5" />
          <div class="space-y-1">
            <div class="font-medium text-rose-900 dark:text-rose-200">
              {{ t('settings.marketLoadFailedTitle') }}
            </div>
            <p class="text-[11px] text-rose-700 dark:text-rose-300/80">
              {{ marketCatalogError }}
            </p>
            <p class="text-[11px] text-rose-800 dark:text-rose-200 pt-0.5 font-medium">
              {{ t('settings.marketLoadFailedHint') }}
            </p>
          </div>
        </div>
        <div class="flex items-center gap-2 flex-wrap pl-6">
          <button
            v-if="marketSourceType !== 'jsdelivr'"
            type="button"
            class="ui-btn-secondary !text-xs !py-1 !px-2.5 inline-flex items-center gap-1.5 text-indigo-600 dark:text-indigo-400 hover:text-indigo-700"
            :disabled="isSavingSource"
            @click="quickSwitchSource('jsdelivr')"
          >
            <Zap class="w-3.5 h-3.5" />
            <span>{{ t('settings.marketSwitchToJsdelivr') }}</span>
          </button>
          <button
            v-if="marketSourceType !== 'ghproxy'"
            type="button"
            class="ui-btn-secondary !text-xs !py-1 !px-2.5 inline-flex items-center gap-1.5 text-indigo-600 dark:text-indigo-400 hover:text-indigo-700"
            :disabled="isSavingSource"
            @click="quickSwitchSource('ghproxy')"
          >
            <Zap class="w-3.5 h-3.5" />
            <span>{{ t('settings.marketSwitchToGhproxy') }}</span>
          </button>
          <button
            type="button"
            class="ui-btn-secondary !text-xs !py-1 !px-2.5 inline-flex items-center gap-1.5"
            :disabled="marketLoading"
            @click="fetchMarketCatalog(true)"
          >
            <RefreshCw class="w-3.5 h-3.5" :class="marketLoading ? 'animate-spin' : ''" />
            <span>{{ t('settings.pluginsReload') }}</span>
          </button>
        </div>
      </div>

      <!-- 加载状态 -->
      <div v-if="marketLoading" class="py-12 flex flex-col items-center justify-center gap-2 text-slate-400">
        <RefreshCw class="w-6 h-6 animate-spin text-indigo-500" />
        <span class="text-xs">{{ t('settings.pluginsReloading') }}</span>
      </div>

      <!-- 市场插件卡片网格 -->
      <div v-else-if="filteredMarketPlugins.length > 0" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        <div
          v-for="p in filteredMarketPlugins"
          :key="p.id"
          class="flex flex-col justify-between p-4 rounded-lg border border-gray-200/80 dark:border-gray-800/70 bg-white/50 dark:bg-gray-900/40 hover:border-indigo-300 dark:hover:border-indigo-700/60 transition-all hover:shadow-sm"
        >
          <!-- 卡片上部 -->
          <div class="space-y-2.5">
            <div class="flex items-start justify-between gap-2">
              <div class="flex items-center gap-2 min-w-0">
                <div class="w-8 h-8 rounded-lg bg-indigo-50 dark:bg-indigo-950/60 flex items-center justify-center text-indigo-600 dark:text-indigo-400 shrink-0 font-bold text-xs">
                  <Puzzle class="w-4 h-4" />
                </div>
                <div class="min-w-0">
                  <h3 class="font-medium text-xs text-gray-900 dark:text-gray-100 truncate" :title="p.name">
                    {{ p.name }}
                  </h3>
                  <div class="flex items-center gap-1.5 text-[10px] text-gray-400">
                    <span
                      v-if="p.status === 'upgradable'"
                      class="font-mono text-amber-600 dark:text-amber-400 font-semibold"
                      :title="`v${p.installed_version} → v${p.version}`"
                    >
                      v{{ p.installed_version }} → v{{ p.version }}
                    </span>
                    <span v-else class="font-mono">v{{ p.version }}</span>
                    <span>·</span>
                    <span class="truncate max-w-[8rem]">{{ p.author }}</span>
                  </div>
                </div>
              </div>

              <!-- 状态徽章 -->
              <span
                v-if="p.status === 'upgradable'"
                class="shrink-0 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 flex items-center gap-1 animate-pulse"
                :title="`可升级至 v${p.version}`"
              >
                <Sparkles class="w-3 h-3 text-amber-600 dark:text-amber-400" />
                {{ t('settings.marketStatusUpgradable') }} (v{{ p.version }})
              </span>
              <span
                v-else-if="p.status === 'installed'"
                class="shrink-0 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-400 flex items-center gap-1"
              >
                <Check class="w-3 h-3" />
                {{ t('settings.marketStatusInstalled') }}
              </span>
              <span
                v-else
                class="shrink-0 px-2 py-0.5 rounded-full text-[10px] font-medium bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400"
              >
                {{ t('settings.marketStatusNotInstalled') }}
              </span>
            </div>

            <!-- 描述 -->
            <p class="text-xs text-gray-600 dark:text-gray-400 line-clamp-2 min-h-[2.5rem]">
              {{ p.description || t('settings.pluginsNoDesc') }}
            </p>

            <!-- 模式与标签 -->
            <div class="flex items-center gap-1.5 flex-wrap">
              <span class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-sky-50 dark:bg-sky-950/50 text-sky-700 dark:text-sky-300 border border-sky-200/50 dark:border-sky-800/40">
                {{ p.mode }}
              </span>
              <span
                v-for="tag in (p.tags || []).slice(0, 3)"
                :key="tag"
                class="px-1.5 py-0.5 rounded text-[10px] bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400"
              >
                #{{ tag }}
              </span>
            </div>
          </div>

          <!-- 卡片下部操作栏 -->
          <div class="pt-3 mt-3 border-t border-gray-100 dark:border-gray-800/60 flex items-center justify-between gap-2">
            <button
              type="button"
              class="text-xs text-slate-600 hover:text-indigo-600 dark:text-slate-400 dark:hover:text-indigo-400 inline-flex items-center gap-1 transition-colors"
              @click="openMarketReadme(p)"
            >
              <Eye class="w-3.5 h-3.5" />
              {{ t('settings.marketDoc') }}
            </button>

            <div class="flex items-center gap-1.5">
              <!-- 未安装：安装按钮 -->
              <button
                v-if="p.status === 'not_installed'"
                type="button"
                class="ui-btn-primary !px-2.5 !py-1 !text-xs inline-flex items-center gap-1"
                :disabled="installingPluginId === p.id"
                @click="handleInstallMarketPlugin(p)"
              >
                <RefreshCw v-if="installingPluginId === p.id" class="w-3 h-3 animate-spin" />
                <Download v-else class="w-3 h-3" />
                {{ installingPluginId === p.id ? t('settings.marketInstalling') : t('settings.marketInstall') }}
              </button>

              <!-- 可更新：更新按钮 -->
              <button
                v-else-if="p.status === 'upgradable'"
                type="button"
                class="ui-btn-primary !px-2.5 !py-1 !text-xs !bg-amber-600 hover:!bg-amber-700 inline-flex items-center gap-1"
                :disabled="installingPluginId === p.id || isUpdatingAll"
                @click="handleUpdateMarketPlugin(p)"
              >
                <RefreshCw v-if="installingPluginId === p.id" class="w-3 h-3 animate-spin" />
                <Sparkles v-else class="w-3 h-3" />
                {{ installingPluginId === p.id ? t('settings.marketUpdating') : `${t('settings.marketUpdate')} v${p.version}` }}
              </button>

              <!-- 已安装：卸载按钮（非系统内置） -->
              <button
                v-if="p.installed && !p.installed_is_builtin"
                type="button"
                class="text-xs text-rose-500 hover:text-rose-700 dark:hover:text-rose-400 px-2 py-1 transition-colors inline-flex items-center gap-1"
                :disabled="uninstallingPluginId === p.id"
                @click="handleUninstallMarketPlugin(p)"
              >
                <RefreshCw v-if="uninstallingPluginId === p.id" class="w-3 h-3 animate-spin" />
                <Trash2 v-else class="w-3 h-3" />
                {{ uninstallingPluginId === p.id ? t('settings.marketUninstalling') : t('settings.marketUninstall') }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 空结果状态 -->
      <div
        v-else
        class="p-8 text-center text-xs text-gray-400 border border-dashed border-gray-200 dark:border-gray-800 rounded-lg"
      >
        {{ t('settings.marketEmpty') }}
      </div>
    </div>

    <!-- 源码查看弹窗 -->
    <Modal
      :title="`${t('settings.pluginsSourceTitle')}: ${currentSourcePlugin?.name ?? ''}`"
      :is-open="isSourceModalOpen"
      :max-width-class="isEditorFullscreen ? '!max-w-none !w-[98vw] !h-[94vh] !max-h-[94vh] !flex !flex-col' : 'max-w-3xl'"
      @close="handleCloseSourceModal"
    >
      <template #header-extra>
        <div class="flex items-center gap-1.5 ml-2">
          <button
            type="button"
            class="ui-btn-secondary !py-1 !px-2 !text-xs inline-flex items-center gap-1"
            :title="isEditorFullscreen ? t('settings.pluginsEditorExitFullscreen') : t('settings.pluginsEditorFullscreen')"
            @click="isEditorFullscreen = !isEditorFullscreen"
          >
            <Minimize2 v-if="isEditorFullscreen" class="w-3.5 h-3.5" />
            <Maximize2 v-else class="w-3.5 h-3.5" />
          </button>
          <button
            v-if="!currentSourcePlugin?.builtin"
            type="button"
            class="ui-btn-secondary !py-1 !px-2.5 !text-xs inline-flex items-center gap-1.5"
            :class="isEditingSource ? 'text-amber-600 dark:text-amber-400 border-amber-300 dark:border-amber-700' : ''"
            @click="toggleEditSource"
          >
            <Eye v-if="isEditingSource" class="w-3.5 h-3.5" />
            <Edit2 v-else class="w-3.5 h-3.5" />
            <span>{{ isEditingSource ? t('settings.pluginsViewSource') : t('settings.pluginsEditSource') }}</span>
          </button>
          <button
            type="button"
            class="ui-btn-secondary !py-1 !px-2.5 !text-xs inline-flex items-center gap-1.5 text-sky-600 dark:text-sky-400"
            @click="openTestFromSource"
          >
            <Play class="w-3.5 h-3.5" />
            <span>{{ t('settings.pluginsSourceOpenTest') }}</span>
          </button>
          <button
            type="button"
            class="ui-btn-secondary !py-1 !px-2.5 !text-xs inline-flex items-center gap-1.5"
            :disabled="!sourceCode || sourceLoading"
            @click="copySourceCode"
          >
            <Check v-if="sourceCopied" class="w-3.5 h-3.5 text-emerald-500" />
            <Copy v-else class="w-3.5 h-3.5" />
            <span>{{ sourceCopied ? t('settings.pluginsSourceCopied') : t('settings.pluginsSourceCopy') }}</span>
          </button>
        </div>
      </template>

      <div class="space-y-3 text-xs">
        <!-- 依赖体检栏 -->
        <div class="p-2 rounded bg-gray-50 dark:bg-gray-900 border border-gray-200/60 dark:border-gray-800 text-[11px] flex flex-col gap-1.5">
          <div class="flex items-center justify-between text-gray-500 dark:text-gray-400 font-medium">
            <span class="inline-flex items-center gap-1">
              <Package class="w-3.5 h-3.5 text-indigo-500" />
              {{ t('settings.pluginsDependenciesTitle') }}
            </span>
            <span v-if="loadingDeps" class="inline-flex items-center gap-1 text-[10px] text-gray-400">
              <RefreshCw class="w-3 h-3 animate-spin" />
              {{ t('common.loading') }}
            </span>
          </div>
          <div v-if="!loadingDeps && !pluginDeps.length" class="text-[10px] text-gray-400 dark:text-gray-500">
            {{ t('settings.pluginsDependenciesNone') }}
          </div>
          <div v-else-if="pluginDeps.length" class="flex items-center gap-1.5 flex-wrap">
            <button
              v-if="pluginDeps.some((d) => !d.installed)"
              type="button"
              class="ui-btn-secondary !py-0.5 !px-1.5 !text-[10px] inline-flex items-center gap-1 text-rose-600 dark:text-rose-400 font-mono mr-1"
              :title="t('settings.pluginsCopyPipCommand')"
              @click="handleCopyMissingDeps"
            >
              <Copy class="w-2.5 h-2.5" />
              <span>{{ t('settings.pluginsCopyPipCommand') }}</span>
            </button>
            <span
              v-for="dep in pluginDeps"
              :key="dep.module"
              class="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-mono cursor-pointer border transition-colors"
              :class="dep.installed
                ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-300 dark:border-emerald-800/50'
                : 'bg-rose-50 text-rose-700 border-rose-200 dark:bg-rose-950/40 dark:text-rose-300 dark:border-rose-800/50 hover:border-rose-400'"
              :title="dep.installed ? t('settings.pluginsDependencyInstalled') : t('settings.pluginsDependencyCopyInstall')"
              @click="dep.install_command && copyDepInstall(dep.install_command)"
            >
              <span>{{ dep.module }}{{ dep.version ? `@${dep.version}` : '' }}</span>
              <span class="text-[9px] px-1 rounded" :class="dep.installed ? 'bg-emerald-100 dark:bg-emerald-900/60' : 'bg-rose-100 dark:bg-rose-900/60'">
                {{ dep.installed ? t('settings.pluginsDependencyInstalled') : t('settings.pluginsDependencyMissing') }}
              </span>
            </span>
          </div>
        </div>

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
        <div v-else-if="isEditingSource" class="space-y-3">
          <!-- 改动差异对比视图 -->
          <div
            v-if="showDiffView"
            class="w-full h-96 overflow-auto font-mono text-[11px] bg-gray-950 text-gray-200 rounded-lg border border-gray-800 p-2 space-y-0.5 select-text"
          >
            <div v-if="!sourceDiffLines.some((l) => l.type !== 'same')" class="p-8 text-center text-gray-500">
              {{ t('settings.pluginsDiffNoChanges') }}
            </div>
            <div
              v-for="(diffLine, dIdx) in sourceDiffLines"
              :key="dIdx"
              class="flex items-start px-2 py-0.5 rounded leading-relaxed font-mono"
              :class="{
                'bg-emerald-950/60 text-emerald-300': diffLine.type === 'add',
                'bg-rose-950/60 text-rose-300': diffLine.type === 'del',
                'text-gray-400': diffLine.type === 'same'
              }"
            >
              <span class="w-10 shrink-0 select-none text-[10px] text-gray-600 text-right pr-2">
                <template v-if="diffLine.type === 'del'">-{{ diffLine.oldLine }}</template>
                <template v-else-if="diffLine.type === 'add'">+{{ diffLine.newLine }}</template>
                <template v-else>{{ diffLine.newLine }}</template>
              </span>
              <span
                class="w-4 shrink-0 select-none font-bold text-center"
                :class="{
                  'text-emerald-400': diffLine.type === 'add',
                  'text-rose-400': diffLine.type === 'del',
                  'text-transparent': diffLine.type === 'same'
                }"
              >
                {{ diffLine.type === 'add' ? '+' : (diffLine.type === 'del' ? '-' : ' ') }}
              </span>
              <span class="whitespace-pre-wrap break-all flex-1">{{ diffLine.text || ' ' }}</span>
            </div>
          </div>
          <textarea
            v-else
            ref="sourceEditorTextarea"
            v-model="editedSourceCode"
            :rows="isEditorFullscreen ? 30 : 18"
            class="w-full bg-gray-950 text-gray-100 font-mono text-[11px] leading-relaxed p-4 rounded-lg border border-gray-800 focus:outline-none focus:ring-1 focus:ring-amber-500 resize-y"
            spellcheck="false"
          ></textarea>

          <!-- 安全审计与全方位体检面板 -->
          <div
            v-if="auditWarnings.length > 0 || auditScore !== null"
            class="p-3 rounded-lg border text-[11px] font-mono space-y-2 transition-all"
            :class="{
              'bg-emerald-50/80 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800/60': auditRiskLevel === 'safe' && auditWarnings.length === 0,
              'bg-blue-50/80 dark:bg-blue-950/30 border-blue-200 dark:border-blue-800/60': auditRiskLevel === 'notice',
              'bg-amber-50/80 dark:bg-amber-950/40 border-amber-200 dark:border-amber-800/80': auditRiskLevel === 'warning',
              'bg-rose-50/80 dark:bg-rose-950/40 border-rose-200 dark:border-rose-800/80': auditRiskLevel === 'critical'
            }"
          >
            <!-- 头部：评分与风险等级徽章 -->
            <div class="flex items-center justify-between flex-wrap gap-2">
              <div
                class="flex items-center gap-1.5 font-semibold"
                :class="{
                  'text-emerald-700 dark:text-emerald-300': auditRiskLevel === 'safe' && auditWarnings.length === 0,
                  'text-blue-700 dark:text-blue-300': auditRiskLevel === 'notice',
                  'text-amber-700 dark:text-amber-300': auditRiskLevel === 'warning',
                  'text-rose-700 dark:text-rose-300': auditRiskLevel === 'critical'
                }"
              >
                <ShieldCheck v-if="auditRiskLevel === 'safe' && auditWarnings.length === 0" class="w-4 h-4 text-emerald-500" />
                <AlertTriangle v-else class="w-4 h-4" />
                <span>{{ t('settings.pluginsAuditTitle') }}</span>
                <span
                  v-if="auditScore !== null"
                  class="px-1.5 py-0.5 rounded text-[10px] font-bold"
                  :class="{
                    'bg-emerald-100 dark:bg-emerald-900/60 text-emerald-800 dark:text-emerald-200': auditScore >= 90,
                    'bg-amber-100 dark:bg-amber-900/60 text-amber-800 dark:text-amber-200': auditScore < 90 && auditScore >= 60,
                    'bg-rose-100 dark:bg-rose-900/60 text-rose-800 dark:text-rose-200': auditScore < 60
                  }"
                >
                  {{ auditScore }} {{ t('settings.pluginsAuditScoreUnit') }}
                </span>
                <span
                  class="px-1.5 py-0.5 rounded text-[10px] uppercase font-bold"
                  :class="{
                    'bg-emerald-100 dark:bg-emerald-900/60 text-emerald-800 dark:text-emerald-200': auditRiskLevel === 'safe',
                    'bg-blue-100 dark:bg-blue-900/60 text-blue-800 dark:text-blue-200': auditRiskLevel === 'notice',
                    'bg-amber-100 dark:bg-amber-900/60 text-amber-800 dark:text-amber-200': auditRiskLevel === 'warning',
                    'bg-rose-100 dark:bg-rose-900/60 text-rose-800 dark:text-rose-200': auditRiskLevel === 'critical'
                  }"
                >
                  {{ t(`settings.pluginsAuditRisk_${auditRiskLevel}`) }}
                </span>
              </div>
              <span v-if="auditWarnings.length > 0" class="text-xs text-gray-500 dark:text-gray-400">
                {{ t('settings.pluginsAuditWarnings', { n: auditWarnings.length }) }}
              </span>
              <span v-else class="text-xs text-emerald-600 dark:text-emerald-400">
                {{ t('settings.pluginsAuditSafe') }}
              </span>
            </div>

            <!-- 权限越界提示 -->
            <div
              v-if="auditUndeclared.length > 0"
              class="p-2 rounded bg-amber-100/60 dark:bg-amber-900/30 border border-amber-300 dark:border-amber-700/60 text-amber-900 dark:text-amber-200 text-xs flex items-start gap-1.5"
            >
              <AlertCircle class="w-3.5 h-3.5 shrink-0 mt-0.5 text-amber-600 dark:text-amber-400" />
              <div>
                <span class="font-semibold">{{ t('settings.pluginsAuditUndeclaredAlert') }}: </span>
                <span>{{ auditUndeclared.join(', ') }}（{{ t('settings.pluginsAuditUndeclaredHint') }}）</span>
              </div>
            </div>

            <!-- 告警条目清单（点击跳转行） -->
            <div v-if="auditWarnings.length > 0" class="space-y-1 max-h-36 overflow-y-auto pr-1">
              <div
                v-for="(warn, wIdx) in auditWarnings"
                :key="wIdx"
                class="flex items-start justify-between gap-2 p-1.5 rounded hover:bg-black/5 dark:hover:bg-white/5 cursor-pointer group transition-colors"
                @click="jumpToSourceLine(warn.line)"
                :title="t('settings.pluginsAuditClickJump')"
              >
                <div class="flex items-start gap-1.5 min-w-0 flex-1">
                  <span
                    class="px-1 py-0.2 rounded text-[9.5px] font-bold uppercase shrink-0"
                    :class="warn.severity === 'high' || warn.severity === 'critical' ? 'bg-rose-200 dark:bg-rose-900 text-rose-800 dark:text-rose-100' : 'bg-amber-200 dark:bg-amber-900 text-amber-800 dark:text-amber-100'"
                  >
                    {{ warn.severity }}
                  </span>
                  <span class="font-bold text-gray-700 dark:text-gray-300 shrink-0">L{{ warn.line }}:</span>
                  <span class="text-gray-800 dark:text-gray-200 break-words">{{ warn.message }}</span>
                </div>
                <span class="text-[10px] text-sky-600 dark:text-sky-400 opacity-0 group-hover:opacity-100 shrink-0 underline">
                  {{ t('settings.pluginsAuditJumpLine') }}
                </span>
              </div>
            </div>
          </div>

          <!-- 静态识别能力标签 -->
          <div v-if="auditCapabilities.length > 0" class="flex items-center gap-1.5 flex-wrap text-[11px] px-1">
            <span class="text-gray-400 font-medium">{{ t('settings.pluginsCapabilitiesDetected') }}:</span>
            <span
              v-for="cap in auditCapabilities"
              :key="cap"
              class="px-2 py-0.5 rounded bg-sky-50 dark:bg-sky-950/60 text-sky-700 dark:text-sky-300 border border-sky-200 dark:border-sky-800 text-[10.5px] font-mono font-medium"
            >
              {{ cap }}
            </span>
          </div>

          <div class="flex items-center justify-end gap-2">
            <div v-if="syntaxResult" class="mr-auto text-[11px] font-mono flex items-center gap-1 px-2 py-1 rounded" :class="syntaxResult.valid ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800' : 'bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300 border border-rose-200 dark:border-rose-800'">
              <span>{{ syntaxResult.message }}</span>
            </div>
            <!-- 快捷代码片段下拉 -->
            <div class="relative plugin-snippet-dropdown-container mr-auto">
              <button
                type="button"
                class="ui-btn-secondary !py-1.5 !px-2.5 !text-xs inline-flex items-center gap-1 text-emerald-600 dark:text-emerald-400"
                @click.stop="showSnippetDropdown = !showSnippetDropdown"
              >
                <Code class="w-3.5 h-3.5" />
                <span>{{ t('settings.pluginsSnippetsTitle') }}</span>
                <ChevronDown class="w-3 h-3 text-gray-400" />
              </button>

              <div
                v-if="showSnippetDropdown"
                class="absolute left-0 bottom-full mb-1 w-60 bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-xl py-1 z-30 text-xs flex flex-col"
              >
                <button
                  v-for="s in SDK_SNIPPETS"
                  :key="s.labelKey"
                  type="button"
                  class="w-full text-left px-3 py-1.5 hover:bg-gray-100 dark:hover:bg-gray-700/60 font-mono text-[11px] truncate"
                  @click="insertSnippet(s.code)"
                >
                  {{ t(s.labelKey) }}
                </button>
              </div>
            </div>

            <button
              type="button"
              class="ui-btn-secondary !py-1.5 !px-3 !text-xs inline-flex items-center gap-1.5 text-blue-600 dark:text-blue-400"
              :disabled="syntaxChecking || savingSource"
              @click="handleCheckSyntax"
            >
              <RefreshCw v-if="syntaxChecking" class="w-3.5 h-3.5 animate-spin" />
              <Check v-else class="w-3.5 h-3.5" />
              <span>{{ syntaxChecking ? t('common.loading') : t('settings.pluginsSyntaxCheck') }}</span>
            </button>
            <button
              type="button"
              class="ui-btn-secondary !py-1.5 !px-3 !text-xs inline-flex items-center gap-1.5 text-amber-600 dark:text-amber-400"
              :disabled="auditingSource || savingSource"
              @click="handleAuditSource"
            >
              <RefreshCw v-if="auditingSource" class="w-3.5 h-3.5 animate-spin" />
              <ShieldCheck v-else class="w-3.5 h-3.5" />
              <span>{{ auditingSource ? t('common.loading') : t('settings.pluginsAudit') }}</span>
            </button>
            <button
              type="button"
              class="ui-btn-secondary !py-1.5 !px-3 !text-xs inline-flex items-center gap-1.5 text-purple-600 dark:text-purple-400"
              :disabled="formattingSource || savingSource"
              @click="handleFormatSource"
            >
              <RefreshCw v-if="formattingSource" class="w-3.5 h-3.5 animate-spin" />
              <Sparkles v-else class="w-3.5 h-3.5" />
              <span>{{ formattingSource ? t('common.loading') : t('settings.pluginsFormatSource') }}</span>
            </button>
            <button
              type="button"
              class="ui-btn-secondary !py-1.5 !px-3 !text-xs inline-flex items-center gap-1.5 text-indigo-600 dark:text-indigo-400"
              :disabled="savingSource"
              @click="toggleDiffView"
            >
              <GitCompare class="w-3.5 h-3.5" />
              <span>{{ showDiffView ? t('settings.pluginsDiffExit') : t('settings.pluginsDiffToggle') }}</span>
            </button>
            <button
              type="button"
              class="ui-btn-secondary !py-1.5 !px-3 !text-xs"
              :disabled="savingSource"
              @click="handleCancelEditSource"
            >
              {{ t('common.cancel') }}
            </button>
            <button
              type="button"
              class="ui-btn-primary !py-1.5 !px-4 !text-xs inline-flex items-center gap-1.5 bg-amber-600 hover:bg-amber-700 text-white"
              :disabled="savingSource"
              @click="() => saveSourceCode(false)"
            >
              <RefreshCw v-if="savingSource" class="w-3.5 h-3.5 animate-spin" />
              <Save v-else class="w-3.5 h-3.5" />
              <span>{{ t('settings.pluginsSaveSource') }}</span>
            </button>
          </div>
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

        <!-- 模式提示与特性说明 -->
        <div
          class="p-2.5 rounded border text-[11px] leading-relaxed"
          :class="currentTestPlugin.mode === 'active' ? 'border-emerald-200/70 bg-emerald-50/40 dark:border-emerald-900/50 dark:bg-emerald-950/20 text-emerald-800 dark:text-emerald-300' : 'border-sky-200/70 bg-sky-50/40 dark:border-sky-900/50 dark:bg-sky-950/20 text-sky-800 dark:text-sky-300'"
        >
          {{ currentTestPlugin.mode === 'active' ? t('settings.pluginsPlaygroundModeActiveTip') : t('settings.pluginsPlaygroundModeReactiveTip') }}
        </div>

        <!-- 模拟消息输入 (仅 reactive 模式为主要必填，active 模式作为可选扩展) -->
        <div class="space-y-1">
          <div class="flex flex-wrap items-center justify-between gap-2 text-gray-700 dark:text-gray-300">
            <label class="font-medium">
              {{ t('settings.pluginsTestInputLabel') }}
              <span v-if="currentTestPlugin.mode === 'active'" class="text-gray-400 font-normal text-[10px]">({{ t('common.optional') }})</span>
            </label>
            <div class="flex items-center gap-2 flex-wrap">
              <!-- 最近调试用例快照 -->
              <div v-if="currentTestPlugin && testSnapshots[currentTestPlugin.name]?.length" class="flex items-center gap-1.5">
                <span class="text-[10px] text-purple-600 dark:text-purple-400 font-medium">⚡ {{ t('settings.pluginsPlaygroundRecentSnapshots') }}:</span>
                <button
                  v-for="(snap, sIdx) in testSnapshots[currentTestPlugin.name]"
                  :key="sIdx"
                  type="button"
                  class="px-1.5 py-0.5 rounded text-[10px] bg-purple-50 hover:bg-purple-100 dark:bg-purple-950/40 dark:hover:bg-purple-900/60 text-purple-700 dark:text-purple-300 font-mono transition-colors truncate max-w-[8rem]"
                  @click="applyTestSnapshot(snap)"
                >
                  {{ snap.text ? (snap.text.length > 10 ? snap.text.slice(0, 10) + '...' : snap.text) : '{params}' }}
                </button>
              </div>
              <div class="flex items-center gap-1.5">
              <span class="text-[10px] text-gray-400">{{ t('settings.pluginsQuickPresets') }}:</span>
              <button
                type="button"
                class="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
                @click="testInputText = '12 + 34 = ?'"
              >
                {{ t('settings.pluginsPresetMath') }}
              </button>
              <button
                type="button"
                class="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
                @click="testInputText = '【Telegram】您的验证码是 982143，请勿泄露'"
              >
                {{ t('settings.pluginsPresetCode') }}
              </button>
              <button
                type="button"
                class="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700 transition-colors"
                @click="testInputText = '/hello'"
              >
                {{ t('settings.pluginsPresetGreeting') }}
              </button>
              </div>
            </div>
          </div>
          <textarea
            v-model="testInputText"
            rows="2"
            class="ui-input !h-auto !py-1.5 !px-2.5 !text-xs w-full font-mono"
            :placeholder="t('settings.pluginsTestInputPlaceholder')"
          />
        </div>

        <!-- 参数配置表单 (若存在 schema) -->
        <div v-if="currentTestPlugin.params_schema && currentTestPlugin.params_schema.length" class="p-3 bg-gray-50/80 dark:bg-white/[0.02] border border-gray-200 dark:border-gray-800/80 rounded space-y-2">
          <div class="flex items-center justify-between font-medium text-[11px] text-gray-700 dark:text-gray-300">
            <span>{{ t('settings.pluginsTestParamsLabel') }}</span>
            <button
              type="button"
              class="text-[10px] text-indigo-600 dark:text-indigo-400 hover:underline inline-flex items-center gap-1 font-normal"
              @click="resetTestParamsToDefault"
            >
              <RotateCcw class="w-2.5 h-2.5" />
              {{ t('settings.pluginsConfigReset') }}
            </button>
          </div>
          <div
            v-for="field in currentTestPlugin.params_schema"
            :key="field.name"
            class="flex flex-col gap-1"
          >
            <div class="flex items-baseline gap-1.5 flex-wrap text-[10px] text-gray-500">
              <span class="font-medium text-gray-700 dark:text-gray-300" :title="field.name">{{ field.label || field.name }}</span>
              <span v-if="field.required" class="text-rose-500 text-xs font-bold leading-none" title="必填">*</span>
              <span v-if="field.description" class="text-[10px] text-gray-400 dark:text-gray-500 truncate" :title="field.description">
                - {{ field.description }}
              </span>
            </div>
            <label v-if="field.type === 'bool' || field.type === 'boolean'" class="inline-flex items-center gap-2 cursor-pointer">
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
            <select
              v-else-if="(field.type === 'select' || (field.options && field.options.length > 0)) && field.options"
              :value="testParams[field.name]"
              class="ui-input !h-8 !text-xs !px-2 w-full bg-white dark:bg-gray-900"
              @change="testParams[field.name] = ($event.target as HTMLSelectElement).value"
            >
              <option
                v-for="opt in field.options"
                :key="String(opt.value)"
                :value="opt.value"
              >
                {{ opt.label }}
              </option>
            </select>
            <input
              v-else-if="field.type === 'int' || field.type === 'number'"
              type="number"
              :value="testParams[field.name]"
              :placeholder="field.placeholder || String(field.default ?? '')"
              class="ui-input !h-8 !text-xs !px-2 w-full"
              @input="testParams[field.name] = ($event.target as HTMLInputElement).value === '' ? undefined : Number(($event.target as HTMLInputElement).value)"
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

        <!-- 高级会话模拟 -->
        <div class="border border-gray-200 dark:border-gray-800 rounded p-2.5 bg-gray-50/50 dark:bg-gray-900/30">
          <button
            type="button"
            class="w-full flex items-center justify-between text-xs font-medium text-gray-700 dark:text-gray-300"
            @click="showAdvancedMock = !showAdvancedMock"
          >
            <span class="inline-flex items-center gap-1.5">
              <span>⚙️ {{ t('settings.pluginsAdvancedMock') }}</span>
            </span>
            <ChevronDown v-if="!showAdvancedMock" class="w-3.5 h-3.5 text-gray-400" />
            <ChevronUp v-else class="w-3.5 h-3.5 text-gray-400" />
          </button>
          <div v-if="showAdvancedMock" class="mt-2.5 grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs">
            <div>
              <label class="block text-[11px] text-gray-500 dark:text-gray-400 mb-1">{{ t('settings.pluginsMockChatId') }}</label>
              <input
                v-model="mockChatId"
                type="text"
                placeholder="-1001234567890"
                class="ui-input !h-8 !text-xs !px-2 w-full font-mono"
              />
            </div>
            <div>
              <label class="block text-[11px] text-gray-500 dark:text-gray-400 mb-1">{{ t('settings.pluginsMockSender') }}</label>
              <input
                v-model="mockSenderName"
                type="text"
                placeholder="Tester"
                class="ui-input !h-8 !text-xs !px-2 w-full"
              />
            </div>
            <div>
              <label class="block text-[11px] text-gray-500 dark:text-gray-400 mb-1">{{ t('settings.pluginsPlaygroundTimeout') }}</label>
              <input
                v-model="mockTimeout"
                type="number"
                min="0.1"
                step="0.5"
                :placeholder="t('settings.pluginsPlaygroundTimeoutPlaceholder')"
                class="ui-input !h-8 !text-xs !px-2 w-full font-mono"
              />
            </div>
          </div>
        </div>

        <!-- 执行与存储重置控制 -->
        <div class="flex items-center justify-between gap-2 pt-1">
          <label class="inline-flex items-center gap-1.5 cursor-pointer text-[11px] text-gray-600 dark:text-gray-400" :title="t('settings.pluginsPlaygroundResetStorageTip')">
            <input
              v-model="resetStorage"
              type="checkbox"
              class="rounded text-sky-600 focus:ring-sky-500 h-3.5 w-3.5"
            />
            <span>{{ t('settings.pluginsPlaygroundResetStorage') }}</span>
          </label>

          <div class="flex items-center gap-1.5">
            <button
              type="button"
              class="ui-btn-secondary !px-2 !py-1.5 !text-xs inline-flex items-center gap-1 text-gray-600 dark:text-gray-300"
              :title="t('settings.pluginsPlaygroundLoadPreset')"
              @click="loadPlaygroundPreset"
            >
              <Bookmark class="w-3 h-3 text-indigo-500" />
              <span>{{ t('settings.pluginsPlaygroundLoadPreset') }}</span>
            </button>
            <button
              type="button"
              class="ui-btn-secondary !px-2 !py-1.5 !text-xs inline-flex items-center gap-1 text-gray-600 dark:text-gray-300"
              :title="t('settings.pluginsPlaygroundSavePreset')"
              @click="savePlaygroundPreset"
            >
              <Save class="w-3 h-3 text-amber-500" />
              <span>{{ t('settings.pluginsPlaygroundSavePreset') }}</span>
            </button>
            <button
              type="button"
              class="ui-btn-secondary !px-2 !py-1.5 !text-xs inline-flex items-center gap-1 text-gray-500 hover:text-gray-700"
              :disabled="testRunning"
              @click="handleResetPlaygroundInputs"
            >
              <RotateCcw class="w-3 h-3" />
              <span>{{ t('settings.pluginsPlaygroundResetInput') }}</span>
            </button>
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
        </div>

        <!-- 测试结果回显 -->
        <div v-if="testResult" class="p-3 border rounded space-y-2.5 transition-all" :class="testResult.success && testResult.handled ? 'border-emerald-500/50 bg-emerald-50/20 dark:bg-emerald-950/20' : (testResult.error ? 'border-red-500/50 bg-red-50/20 dark:bg-red-950/20' : 'border-amber-500/50 bg-amber-50/20 dark:bg-amber-950/20')">
          <div class="flex items-center justify-between gap-2 flex-wrap">
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
              <button
                type="button"
                class="ui-btn-secondary !py-0.5 !px-1.5 !text-[10px] inline-flex items-center gap-1 text-gray-600 dark:text-gray-300 ml-1"
                :title="t('settings.pluginsCopyTestResult')"
                @click="handleCopyTestResult"
              >
                <Copy class="w-2.5 h-2.5" />
                <span>{{ t('settings.pluginsCopyTestResult') }}</span>
              </button>
            </div>
          </div>

          <!-- 参数 Schema 校验警告 -->
          <div v-if="testResult.param_warnings && testResult.param_warnings.length" class="p-2 bg-amber-500/10 border border-amber-500/30 rounded text-amber-700 dark:text-amber-300 text-xs space-y-1">
            <div class="flex items-center gap-1.5 font-medium">
              <AlertTriangle class="w-3.5 h-3.5 shrink-0" />
              <span>{{ t('settings.pluginsPlaygroundParamWarnings') }}</span>
            </div>
            <ul class="list-disc list-inside space-y-0.5 text-[11px] font-mono">
              <li v-for="(pw, idx) in testResult.param_warnings" :key="idx">{{ pw }}</li>
            </ul>
          </div>

          <!-- 错误信息与精确 Traceback -->
          <div v-if="testResult.error || testResult.traceback" class="p-2.5 bg-red-500/10 border border-red-500/30 rounded space-y-2 text-xs text-red-700 dark:text-red-300">
            <div class="flex items-center justify-between gap-2 flex-wrap">
              <div class="flex items-center gap-1.5 font-semibold">
                <AlertCircle class="w-3.5 h-3.5 shrink-0" />
                <span>{{ testResult.error || '执行异常' }}</span>
              </div>
              <div class="flex items-center gap-2 text-[10px]">
                <span v-if="testResult.error_line" class="px-1.5 py-0.5 rounded bg-red-200/60 dark:bg-red-900/60 font-mono font-bold">
                  {{ t('settings.pluginsPlaygroundErrorLine', { line: testResult.error_line }) }}
                </span>
                <button
                  v-if="testResult.traceback"
                  type="button"
                  class="hover:underline text-red-600 dark:text-red-400 font-medium inline-flex items-center gap-1"
                  @click="copyTraceback(testResult.traceback)"
                >
                  <Copy class="w-2.5 h-2.5" />
                  <span>{{ t('settings.pluginsPlaygroundCopyTraceback') }}</span>
                </button>
              </div>
            </div>
            <div v-if="testResult.traceback" class="p-2 bg-black/80 dark:bg-black/90 text-red-300 rounded font-mono text-[10.5px] max-h-44 overflow-y-auto whitespace-pre-wrap select-all leading-relaxed">
              {{ testResult.traceback }}
            </div>
          </div>

          <!-- 回复文本 -->
          <div v-if="testResult.reply_text !== undefined && testResult.reply_text !== null" class="p-2 bg-white/80 dark:bg-black/30 rounded border border-gray-200 dark:border-gray-800">
            <div class="flex items-center justify-between mb-0.5">
              <span class="text-[10px] text-gray-400">{{ t('settings.pluginsReplyOutput') }}</span>
              <button
                v-if="canFormatReplyJson"
                type="button"
                class="text-[10px] text-indigo-600 dark:text-indigo-400 hover:underline inline-flex items-center gap-1"
                @click="formatReplyJson"
              >
                <Sparkles class="w-2.5 h-2.5" />
                <span>{{ t('settings.pluginsFormatJson') }}</span>
              </button>
            </div>
            <div class="font-mono text-xs text-sky-600 dark:text-sky-300 font-semibold select-all whitespace-pre-wrap">
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
              <option value="regex_extractor">{{ t('settings.pluginsTplRegexExtractor') }}</option>
              <option value="webhook_alert">{{ t('settings.pluginsTplWebhookAlert') }}</option>
              <option value="http_api_fetcher">{{ t('settings.pluginsTemplateHttpApi') }}</option>
              <option value="command_router">{{ t('settings.pluginsTemplateCommandRouter') }}</option>
              <option value="keyword_reply">{{ t('settings.pluginsTemplateKeywordReply') }}</option>
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
            {{ t('settings.pluginsGuideIntroTitle') }}
          </h4>
          <p class="text-[11px] text-gray-600 dark:text-gray-300">
            {{ t('settings.pluginsGuideIntroDesc') }}
          </p>
        </div>

        <!-- 2. 执行模式 -->
        <div class="space-y-2">
          <h4 class="font-semibold text-gray-900 dark:text-gray-100 text-[12px]">
            {{ t('settings.pluginsGuideModeTitle') }}
          </h4>
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
            <div class="p-2.5 border border-sky-200/80 dark:border-sky-800/50 rounded bg-sky-50/30 dark:bg-sky-950/10 space-y-1">
              <span class="font-mono font-bold text-sky-700 dark:text-sky-300 text-[11px]">{{ t('settings.pluginsGuideModeReactiveName') }}</span>
              <p class="text-[11px] text-gray-600 dark:text-gray-400">
                {{ t('settings.pluginsGuideModeReactiveDesc') }}
              </p>
            </div>
            <div class="p-2.5 border border-emerald-200/80 dark:border-emerald-800/50 rounded bg-emerald-50/30 dark:bg-emerald-950/10 space-y-1">
              <span class="font-mono font-bold text-emerald-700 dark:text-emerald-300 text-[11px]">{{ t('settings.pluginsGuideModeActiveName') }}</span>
              <p class="text-[11px] text-gray-600 dark:text-gray-400">
                {{ t('settings.pluginsGuideModeActiveDesc') }}
              </p>
            </div>
          </div>
        </div>

        <!-- 3. PluginContext 核心能力 -->
        <div class="space-y-2">
          <h4 class="font-semibold text-gray-900 dark:text-gray-100 text-[12px]">
            {{ t('settings.pluginsGuideContextTitle') }}
          </h4>
          <div class="border border-gray-200 dark:border-gray-800 rounded overflow-hidden">
            <table class="w-full text-left text-[11px]">
              <thead class="bg-gray-50 dark:bg-gray-800/60 text-gray-500 font-mono">
                <tr>
                  <th class="p-2 border-b border-gray-200 dark:border-gray-800">{{ t('settings.pluginsGuideContextMethod') }}</th>
                  <th class="p-2 border-b border-gray-200 dark:border-gray-800">{{ t('settings.pluginsGuideContextDesc') }}</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-gray-100 dark:divide-gray-800/60 font-mono">
                <tr>
                  <td class="p-2 text-sky-600 dark:text-sky-400 font-semibold">ctx.message</td>
                  <td class="p-2 text-gray-600 dark:text-gray-300 font-sans">{{ t('settings.pluginsGuideCtxMessage') }}</td>
                </tr>
                <tr>
                  <td class="p-2 text-sky-600 dark:text-sky-400 font-semibold">await ctx.reply(text)</td>
                  <td class="p-2 text-gray-600 dark:text-gray-300 font-sans">{{ t('settings.pluginsGuideCtxReply') }}</td>
                </tr>
                <tr>
                  <td class="p-2 text-sky-600 dark:text-sky-400 font-semibold">await ctx.send_message(text)</td>
                  <td class="p-2 text-gray-600 dark:text-gray-300 font-sans">{{ t('settings.pluginsGuideCtxSend') }}</td>
                </tr>
                <tr>
                  <td class="p-2 text-sky-600 dark:text-sky-400 font-semibold">await ctx.react(emoji)</td>
                  <td class="p-2 text-gray-600 dark:text-gray-300 font-sans">{{ t('settings.pluginsGuideCtxReact') }}</td>
                </tr>
                <tr>
                  <td class="p-2 text-sky-600 dark:text-sky-400 font-semibold">ctx.storage</td>
                  <td class="p-2 text-gray-600 dark:text-gray-300 font-sans">{{ t('settings.pluginsGuideCtxStorage') }}</td>
                </tr>
                <tr>
                  <td class="p-2 text-sky-600 dark:text-sky-400 font-semibold">ctx.log(message)</td>
                  <td class="p-2 text-gray-600 dark:text-gray-300 font-sans">{{ t('settings.pluginsGuideCtxLog') }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <!-- 4. 元数据规范 -->
        <div class="space-y-1.5">
          <h4 class="font-semibold text-gray-900 dark:text-gray-100 text-[12px]">
            {{ t('settings.pluginsGuideMetaTitle') }}
          </h4>
          <p class="text-[11px] text-gray-600 dark:text-gray-400">
            {{ t('settings.pluginsGuideMetaDesc') }}
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
    <!-- 克隆插件弹窗 -->
    <Modal
      :is-open="isCloneModalOpen"
      :title="t('settings.pluginsCloneTitle')"
      @close="isCloneModalOpen = false"
    >
      <form class="space-y-4 text-xs" @submit.prevent="submitClonePlugin">
        <div class="space-y-1">
          <label class="font-medium text-gray-700 dark:text-gray-300">
            {{ t('settings.pluginsCloneNewName') }}
          </label>
          <input
            v-model="cloneForm.new_name"
            type="text"
            class="ui-input !h-8 !text-xs !px-2.5 w-full font-mono"
            placeholder="my_custom_plugin"
            required
          />
        </div>
        <div class="space-y-1">
          <label class="font-medium text-gray-700 dark:text-gray-300">
            {{ t('settings.pluginsCloneDesc') }}
          </label>
          <input
            v-model="cloneForm.description"
            type="text"
            class="ui-input !h-8 !text-xs !px-2.5 w-full"
          />
        </div>
        <div class="flex items-center justify-end gap-2 pt-2">
          <button
            type="button"
            class="ui-btn-secondary !py-1 !px-3 !text-xs"
            @click="isCloneModalOpen = false"
          >
            {{ t('common.cancel') }}
          </button>
          <button
            type="submit"
            class="ui-btn-primary !py-1 !px-3 !text-xs inline-flex items-center gap-1.5"
            :disabled="submittingClone"
          >
            <RefreshCw v-if="submittingClone" class="w-3 h-3 animate-spin" />
            <span>{{ t('common.confirm') }}</span>
          </button>
        </div>
      </form>
    </Modal>

    <!-- 使用文档弹窗 -->
    <Modal
      :is-open="isDocModalOpen"
      :title="t('settings.pluginsDocTitle', { name: docPluginName })"
      @close="isDocModalOpen = false"
    >
      <div class="space-y-3 text-xs max-h-[60vh] overflow-y-auto pr-1">
        <div class="p-3.5 rounded-lg bg-gray-50 dark:bg-gray-900/60 border border-gray-200 dark:border-gray-800 text-gray-700 dark:text-gray-300 font-mono text-[11px] leading-relaxed whitespace-pre-wrap select-text">
          {{ docPluginContent || t('settings.pluginsDocEmpty') }}
        </div>
      </div>
    </Modal>

    <!-- 调用历史弹窗 -->
    <Modal
      :is-open="isHistoryModalOpen"
      :title="t('settings.pluginsHistoryTitle', { name: historyPluginName })"
      @close="isHistoryModalOpen = false"
    >
      <div class="space-y-3 text-xs max-h-[60vh] overflow-y-auto pr-1">
        <!-- 历史操作工具栏 -->
        <div v-if="executionHistory.length" class="flex items-center justify-between gap-2 pb-2 border-b border-gray-200/60 dark:border-gray-800/60">
          <span class="text-[11px] text-gray-500 font-mono">{{ t('settings.pluginsHistoryCount', { n: executionHistory.length }) }}</span>
          <div class="flex items-center gap-2">
            <button
              type="button"
              class="ui-btn-secondary !py-1 !px-2.5 !text-[11px] inline-flex items-center gap-1 text-sky-600 dark:text-sky-400"
              @click="handleCopyHistoryLogs"
            >
              <Copy class="w-3 h-3" />
              <span>{{ t('settings.pluginsHistoryExport') }}</span>
            </button>
            <button
              type="button"
              class="ui-btn-secondary !py-1 !px-2.5 !text-[11px] inline-flex items-center gap-1 text-rose-600 dark:text-rose-400 hover:text-rose-700"
              :disabled="clearingHistory"
              @click="handleClearHistory"
            >
              <Trash2 class="w-3 h-3" />
              <span>{{ clearingHistory ? t('common.loading') : t('settings.pluginsHistoryClear') }}</span>
            </button>
          </div>
        </div>
        <div v-if="loadingHistory" class="py-8 text-center text-gray-400 flex items-center justify-center gap-2">
          <RefreshCw class="w-4 h-4 animate-spin text-indigo-500" />
          <span>{{ t('common.loading') }}</span>
        </div>
        <div v-else-if="!executionHistory.length" class="py-8 text-center text-gray-400">
          {{ t('settings.pluginsHistoryEmpty') }}
        </div>
        <div v-else class="space-y-2">
          <div
            v-for="(rec, idx) in executionHistory"
            :key="idx"
            class="p-2.5 rounded border border-gray-200/80 dark:border-gray-800/80 bg-white/70 dark:bg-black/20 space-y-1.5"
          >
            <div class="flex items-center justify-between gap-2 flex-wrap text-[11px] font-mono">
              <div class="flex items-center gap-2">
                <span
                  class="px-1.5 py-0.2 rounded text-[10px] font-medium"
                  :class="rec.success ? 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/50 dark:text-emerald-400' : 'bg-rose-50 text-rose-600 dark:bg-rose-950/50 dark:text-rose-400'"
                >
                  {{ rec.success ? t('common.success') : t('common.failed') }}
                </span>
                <span class="text-gray-500">{{ rec.timestamp }}</span>
                <span class="text-gray-400">({{ rec.duration_ms }} ms)</span>
              </div>
              <span class="text-gray-400 text-[10px]">
                {{ triggerTypeLabel(rec.trigger_type) }}
              </span>
            </div>
            <div v-if="rec.error" class="text-rose-600 dark:text-rose-400 text-[10px] font-mono break-all bg-rose-50/50 dark:bg-rose-950/30 p-1.5 rounded">
              {{ rec.error }}
            </div>
            <div v-if="rec.log_summary" class="text-gray-600 dark:text-gray-300 text-[10px] font-mono break-all line-clamp-2">
              {{ rec.log_summary }}
            </div>
          </div>
        </div>
      </div>
    </Modal>

    <!-- 市场插件详情与文档弹窗 -->
    <Modal
      :title="marketReadmeTitle ? `${t('settings.marketDocTitle')}: ${marketReadmeTitle}` : t('settings.marketDocTitle')"
      :is-open="isMarketReadmeOpen"
      max-width-class="max-w-3xl"
      @close="isMarketReadmeOpen = false"
    >
      <div v-if="loadingMarketReadme" class="py-12 flex flex-col items-center justify-center gap-2 text-slate-400">
        <RefreshCw class="w-6 h-6 animate-spin text-indigo-500" />
        <span class="text-xs">{{ t('settings.pluginsReloading') }}</span>
      </div>
      <div v-else class="space-y-4 text-xs text-gray-700 dark:text-gray-300 leading-relaxed max-h-[70vh] overflow-y-auto pr-2 custom-scrollbar">
        <!-- 插件基础元信息卡片 -->
        <div v-if="marketReadmePlugin" class="p-3 bg-indigo-50/50 dark:bg-indigo-950/20 border border-indigo-200/60 dark:border-indigo-800/40 rounded space-y-2">
          <div class="flex items-center justify-between">
            <h4 class="font-semibold text-indigo-900 dark:text-indigo-200 text-sm">
              {{ marketReadmePlugin.name }} ({{ marketReadmePlugin.id }})
            </h4>
            <span class="text-xs font-mono font-bold text-indigo-600 dark:text-indigo-400">
              v{{ marketReadmePlugin.version }}
            </span>
          </div>
          <p class="text-xs text-gray-600 dark:text-gray-400">
            {{ marketReadmePlugin.description }}
          </p>
          <div class="flex items-center gap-3 text-[11px] text-gray-500 flex-wrap">
            <span>{{ t('common.author') || '作者' }}: {{ marketReadmePlugin.author }}</span>
            <span v-if="marketReadmePlugin.min_app_version">{{ t('settings.marketMinAppVersion', { v: marketReadmePlugin.min_app_version }) }}</span>
            <span v-if="marketReadmePlugin.updated_at">{{ t('settings.marketUpdatedAt', { d: marketReadmePlugin.updated_at }) }}</span>
            <a
              v-if="marketReadmePlugin.homepage"
              :href="marketReadmePlugin.homepage"
              target="_blank"
              rel="noopener noreferrer"
              class="text-indigo-600 dark:text-indigo-400 inline-flex items-center gap-1 hover:underline"
            >
              <ExternalLink class="w-3 h-3" />
              {{ t('settings.marketHomepage') }}
            </a>
          </div>
        </div>

        <!-- README Markdown 内容 -->
        <div class="p-4 bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-800 rounded-lg whitespace-pre-wrap font-sans text-xs leading-relaxed select-text">
          {{ marketReadmeContent }}
        </div>

        <!-- 参数配置规范提示 -->
        <div v-if="marketReadmePlugin?.params_schema && marketReadmePlugin.params_schema.length > 0" class="space-y-1.5">
          <h5 class="font-medium text-slate-800 dark:text-slate-200 text-xs">{{ t('settings.marketParamsSchemaTitle') }}</h5>
          <div class="border border-slate-200 dark:border-slate-800 rounded overflow-hidden">
            <table class="w-full text-[11px]">
              <thead class="bg-slate-100 dark:bg-slate-800/80 text-slate-600 dark:text-slate-400">
                <tr>
                  <th class="p-2 text-left font-medium">{{ t('settings.marketParamName') }}</th>
                  <th class="p-2 text-left font-medium">{{ t('settings.marketParamType') }}</th>
                  <th class="p-2 text-left font-medium">{{ t('settings.marketParamDesc') }}</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-200 dark:divide-slate-800">
                <tr v-for="param in marketReadmePlugin.params_schema" :key="param.name">
                  <td class="p-2 font-mono text-indigo-600 dark:text-indigo-400">{{ param.name }}</td>
                  <td class="p-2 font-mono text-slate-500">{{ param.type || 'string' }}</td>
                  <td class="p-2 text-slate-600 dark:text-slate-300">{{ param.description || param.label || '-' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <template #footer>
        <div class="flex items-center justify-between w-full">
          <button
            type="button"
            class="ui-btn-secondary !text-xs !py-1 !px-3"
            @click="isMarketReadmeOpen = false"
          >
            {{ t('settings.marketDocClose') }}
          </button>
          <div v-if="marketReadmePlugin" class="flex items-center gap-2">
            <button
              v-if="marketReadmePlugin.status === 'not_installed'"
              type="button"
              class="ui-btn-primary !text-xs !py-1 !px-3 inline-flex items-center gap-1"
              :disabled="installingPluginId === marketReadmePlugin.id"
              @click="handleInstallMarketPlugin(marketReadmePlugin); isMarketReadmeOpen = false"
            >
              <Download class="w-3.5 h-3.5" />
              {{ t('settings.marketInstall') }}
            </button>
            <button
              v-else-if="marketReadmePlugin.status === 'upgradable'"
              type="button"
              class="ui-btn-primary !text-xs !py-1 !px-3 !bg-amber-600 hover:!bg-amber-700 inline-flex items-center gap-1"
              :disabled="installingPluginId === marketReadmePlugin.id"
              @click="handleUpdateMarketPlugin(marketReadmePlugin); isMarketReadmeOpen = false"
            >
              <Sparkles class="w-3.5 h-3.5" />
              {{ t('settings.marketUpdate') }}
            </button>
          </div>
        </div>
      </template>
    </Modal>
      <!-- 插件持久化存储管理弹窗 -->
    <Modal
      :is-open="isStorageModalOpen"
      :title="t('settings.pluginsStorageTitle', { name: currentStoragePlugin?.name || '' })"
      max-width-class="max-w-3xl"
      @close="isStorageModalOpen = false"
    >
      <div class="space-y-3.5 text-xs max-h-[70vh] overflow-y-auto pr-1">
        <!-- 头部统计与操作 -->
        <div class="flex items-center justify-between gap-2 pb-2.5 border-b border-gray-200/60 dark:border-gray-800/60 flex-wrap">
          <div class="flex items-center gap-2 text-[11px] font-mono">
            <span class="px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300">
              {{ t('settings.pluginsStorageTotalRecords', { count: storageData?.total_records ?? 0 }) }}
            </span>
            <span class="px-2 py-0.5 rounded bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300">
              {{ t('settings.pluginsStorageTotalNamespaces', { count: storageData?.namespaces?.length ?? 0 }) }}
            </span>
          </div>

          <div class="flex items-center gap-2">
            <button
              type="button"
              class="ui-btn-secondary !py-1 !px-2.5 !text-[11px] inline-flex items-center gap-1"
              :disabled="storageLoading"
              @click="refreshPluginStorage"
            >
              <RefreshCw class="w-3 h-3" :class="{ 'animate-spin': storageLoading }" />
              <span>{{ t('settings.pluginsReload') }}</span>
            </button>
            <button
              type="button"
              class="ui-btn-secondary !py-1 !px-2.5 !text-[11px] inline-flex items-center gap-1 text-rose-600 dark:text-rose-400 hover:text-rose-700 border-rose-200 dark:border-rose-900/60"
              :disabled="storageClearing || !(storageData?.total_records)"
              @click="handleClearAllStorage"
            >
              <Trash2 class="w-3 h-3" />
              <span>{{ storageClearing ? t('common.loading') : t('settings.pluginsStorageClearAll') }}</span>
            </button>
          </div>
        </div>

        <!-- 命名空间标签筛选 -->
        <div v-if="(storageData?.namespaces?.length ?? 0) > 1" class="flex items-center gap-1.5 flex-wrap">
          <button
            type="button"
            class="px-2 py-0.5 rounded text-[11px] font-mono transition-colors"
            :class="selectedStorageNamespace === 'all'
              ? 'bg-indigo-600 text-white font-semibold'
              : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-200'"
            @click="selectedStorageNamespace = 'all'"
          >
            {{ t('settings.pluginsStorageFilterAll') }}
          </button>
          <button
            v-for="ns in storageData?.namespaces"
            :key="ns.namespace"
            type="button"
            class="px-2 py-0.5 rounded text-[11px] font-mono transition-colors inline-flex items-center gap-1"
            :class="selectedStorageNamespace === ns.namespace
              ? 'bg-indigo-600 text-white font-semibold'
              : 'bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-400 hover:bg-gray-200'"
            @click="selectedStorageNamespace = ns.namespace"
          >
            <span class="truncate max-w-[160px]">{{ ns.namespace }}</span>
            <span
              class="text-[9px] px-1 py-0.2 rounded"
              :class="ns.is_test ? 'bg-amber-200 dark:bg-amber-900 text-amber-800 dark:text-amber-200' : 'bg-emerald-200 dark:bg-emerald-900 text-emerald-800 dark:text-emerald-200'"
            >
              {{ ns.is_test ? t('settings.pluginsStorageIsTest') : t('settings.pluginsStorageIsProd') }}
            </span>
            <span class="opacity-75 text-[10px]">({{ ns.records.length }})</span>
          </button>
        </div>

        <!-- 加载中 -->
        <div v-if="storageLoading && !storageData" class="py-8 text-center text-gray-400 flex items-center justify-center gap-2">
          <RefreshCw class="w-4 h-4 animate-spin text-indigo-500" />
          <span>{{ t('common.loading') }}</span>
        </div>

        <!-- 空状态 -->
        <div v-else-if="!visibleStorageRecords.length" class="py-10 text-center text-gray-400 space-y-2">
          <Database class="w-8 h-8 mx-auto text-gray-300 dark:text-gray-600" />
          <p>{{ t('settings.pluginsStorageEmpty') }}</p>
        </div>

        <!-- 记录列表 -->
        <div v-else class="space-y-2">
          <div
            v-for="(item, idx) in visibleStorageRecords"
            :key="idx"
            class="p-2.5 rounded border border-gray-200/80 dark:border-gray-800/80 bg-white/70 dark:bg-black/20 space-y-1.5"
          >
            <div class="flex items-center justify-between gap-2 flex-wrap text-[11px]">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="font-mono font-bold text-gray-900 dark:text-gray-100">{{ item.record.key }}</span>
                <span class="text-[10px] font-mono px-1.5 py-0.2 rounded bg-gray-100 dark:bg-gray-800 text-gray-500">
                  {{ item.namespace }}
                </span>
                <span
                  v-if="item.is_test"
                  class="text-[9px] px-1 py-0.2 rounded bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-300 font-medium"
                >
                  {{ t('settings.pluginsStorageIsTest') }}
                </span>
              </div>

              <div class="flex items-center gap-2">
                <span
                  class="text-[10px] font-mono px-1.5 py-0.2 rounded"
                  :class="item.record.expires_at ? 'bg-amber-50 dark:bg-amber-950/40 text-amber-600 dark:text-amber-400 border border-amber-200 dark:border-amber-800/40' : 'bg-gray-50 dark:bg-gray-800/50 text-gray-400'"
                >
                  {{ item.record.expires_at ? `TTL: ${Math.round(item.record.ttl_remaining ?? 0)}s` : t('settings.pluginsStoragePermanent') }}
                </span>
                <button
                  type="button"
                  class="text-gray-400 hover:text-sky-500 transition-colors p-0.5"
                  :title="t('common.copy')"
                  @click="copyStorageValue(item.record.value)"
                >
                  <Copy class="w-3 h-3" />
                </button>
                <button
                  type="button"
                  class="text-gray-400 hover:text-rose-500 transition-colors p-0.5"
                  :title="t('settings.pluginsStorageDeleteKey')"
                  @click="handleDeleteStorageKey(item.namespace, item.record.key)"
                >
                  <Trash2 class="w-3 h-3" />
                </button>
              </div>
            </div>

            <!-- 值渲染 -->
            <pre class="p-2 rounded bg-gray-950 text-gray-200 font-mono text-[11px] overflow-x-auto max-h-32 custom-scrollbar select-text">{{ typeof item.record.value === 'object' ? JSON.stringify(item.record.value, null, 2) : item.record.value }}</pre>
          </div>
        </div>
      </div>
    </Modal>

  </section>
</template>
