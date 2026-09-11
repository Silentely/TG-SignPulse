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
import { ref, computed, onMounted } from 'vue'
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
  RotateCcw,
  Edit2,
  Save,
  Eye,
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
  checkPluginSyntax,
  clearPluginHistory,
  auditPluginSource,
  type AuditPluginWarning,
  type PluginDependency,
  type PluginExecutionRecord,
  type PluginInfo,
  type PluginTestResponse,
  type CreatePluginRequest,
  type PluginLoadErrorItem,
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
    const msg = err instanceof Error ? err.message : String(err)
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

const openHistoryModal = async (plugin: PluginInfo) => {
  historyPluginName.value = plugin.name
  isHistoryModalOpen.value = true
  loadingHistory.value = true
  executionHistory.value = []
  try {
    const res = await withToken((token) => getPluginHistory(plugin.name, token))
    if (res) {
      executionHistory.value = res.history || []
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    toast.error(msg)
  } finally {
    loadingHistory.value = false
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
    const msg = err instanceof Error ? err.message : String(err)
    toast.error(msg)
  } finally {
    clearingHistory.value = false
  }
}

const handleCopyHistoryLogs = async () => {
  if (!executionHistory.value.length) return
  try {
    const delimiter = "\n---------------------\n\n"
    const content = executionHistory.value.map((rec, i) => {
      const status = rec.success ? '[SUCCESS]' : '[FAILED]'
      const errPart = rec.error ? `Error: ${rec.error}\n` : ''
      const logPart = rec.log_summary ? `Logs:\n${rec.log_summary}\n` : ''
      return `#${i + 1} [${rec.timestamp}] ${status} (${rec.duration_ms}ms, ${rec.trigger_type})\n` + errPart + logPart
    }).join(delimiter)
    await navigator.clipboard.writeText(content)
    toast.success(t('settings.pluginsHistoryExportSuccess'))
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    toast.error(msg)
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
    const msg = err instanceof Error ? err.message : String(err)
    toast.error(msg)
  } finally {
    batchToggling.value = false
  }
}

const handleResetAllMetrics = async () => {
  resettingAllMetrics.value = true
  try {
    await withToken((token) => resetAllPluginMetrics(token))
    toast.success(t('settings.pluginsResetAllMetricsSuccess'))
    await loadPluginList()
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
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

// 诊断状态
const loadErrors = ref<PluginLoadErrorItem[]>([])
const isDiagOpen = ref(false)
const copiedDiagIndex = ref<number | null>(null)

const copyInstallCommand = async (cmd: string, idx: number) => {
  try {
    await navigator.clipboard.writeText(cmd)
    copiedDiagIndex.value = idx
    toast.success(t('settings.pluginsDiagCopied'))
    setTimeout(() => {
      if (copiedDiagIndex.value === idx) copiedDiagIndex.value = null
    }, 2000)
  } catch {
    toast.error(cmd)
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
}

const searchQuery = ref('')
const filterMode = ref<'all' | 'reactive' | 'active'>('all')
const filterType = ref<'all' | 'builtin' | 'custom' | 'issue'>('all')
const sortBy = ref<'default' | 'runs' | 'success_rate' | 'duration' | 'name'>('default')
const exportingAll = ref(false)

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
    const msg = err instanceof Error ? err.message : String(err)
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
      if (!matchName && !matchDesc && !matchAuthor) return false
    }
    if (filterMode.value !== 'all' && p.mode !== filterMode.value) {
      return false
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

const openTestFromSource = () => {
  if (!currentSourcePlugin.value) return
  const p = currentSourcePlugin.value
  isSourceModalOpen.value = false
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
// 依赖体检状态
const pluginDeps = ref<PluginDependency[]>([])
const loadingDeps = ref(false)

const copyDepInstall = async (cmd: string) => {
  try {
    await navigator.clipboard.writeText(cmd)
    toast.success(t('settings.pluginsDependencyCopied', { cmd }))
  } catch {
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

const openSourceModal = async (plugin: PluginInfo) => {
  currentSourcePlugin.value = plugin
  sourceCode.value = ''
  sourceCopied.value = false
  isEditingSource.value = false
  editedSourceCode.value = ''
  isSourceModalOpen.value = true
  sourceLoading.value = true
  pluginDeps.value = []
  loadingDeps.value = true
  void (async () => {
    try {
      const res = await withToken((token) => getPluginDependencies(plugin.name, token))
      if (res && res.dependencies) {
        pluginDeps.value = res.dependencies
      }
    } catch {
      pluginDeps.value = []
    } finally {
      loadingDeps.value = false
    }
  })()

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

const syntaxChecking = ref(false)
const syntaxResult = ref<{ valid: boolean; message: string } | null>(null)

const toggleEditSource = () => {
  isEditingSource.value = !isEditingSource.value
  syntaxResult.value = null
  if (isEditingSource.value) {
    editedSourceCode.value = sourceCode.value
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

const handleAuditSource = async () => {
  if (!editedSourceCode.value) return
  auditingSource.value = true
  auditWarnings.value = []
  try {
    const res = await withToken((token) => auditPluginSource(editedSourceCode.value, token))
    if (!res) return
    auditWarnings.value = res.warnings || []
    if (res.passed) {
      toast.success(t('settings.pluginsAuditSafe'))
    } else {
      toast.warning(t('settings.pluginsAuditWarnings', { n: res.warnings.length }))
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    toast.error(msg)
  } finally {
    auditingSource.value = false
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
    const msg = err instanceof Error ? err.message : String(err)
    syntaxResult.value = { valid: false, message: msg }
    toast.error(msg)
  } finally {
    syntaxChecking.value = false
  }
}

const saveSourceCode = async () => {
  if (!currentSourcePlugin.value) return
  savingSource.value = true
  try {
    const res = await withToken((token) => updatePluginSource(currentSourcePlugin.value!.name, editedSourceCode.value, token))
    if (res) {
      sourceCode.value = editedSourceCode.value
      isEditingSource.value = false
      toast.success(t('settings.pluginsSaveSourceSuccess'))
      await loadPluginList()
    }
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    toast.error(`${t('settings.pluginsSaveSourceFailed')}: ${msg}`)
  } finally {
    savingSource.value = false
  }
}

const handleResetMetrics = async (plugin: PluginInfo) => {
  resettingMetricsPlugin.value = plugin.name
  try {
    await withToken((token) => resetPluginMetrics(plugin.name, token))
    toast.success(t('settings.pluginsMetricsResetSuccess'))
    await loadPluginList()
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : String(err)
    toast.error(`${t('settings.pluginsMetricsResetFailed')}: ${msg}`)
  } finally {
    resettingMetricsPlugin.value = null
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
const triggerUploadPlugin = () => {
  fileInputRef.value?.click()
}

const handleFileUpload = async (event: Event) => {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return

  const lowerName = file.name.toLowerCase()
  if (!lowerName.endsWith('.py') && !lowerName.endsWith('.zip')) {
    toast.error(t('settings.pluginsUploadFailed') + ': 仅支持 .py 或 .zip 文件')
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
    const msg = err instanceof Error ? err.message : String(err)
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
    const msg = err instanceof Error ? err.message : String(err)
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
          reset_storage: resetStorage.value,
          chat_id: mockChatId.value ? mockChatId.value : undefined,
          sender_name: mockSenderName.value.trim() || undefined,
        },
        token,
      ),
    )
    if (!res) return
    testResult.value = res
    if (currentTestPlugin.value) {
      saveTestSnapshot(currentTestPlugin.value.name, testInputText.value, testParams.value)
    }
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
    <div class="mb-4 flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-2.5">
      <div class="relative flex-1 max-w-sm">
        <Search class="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
        <input
          v-model="searchQuery"
          type="text"
          :placeholder="t('settings.pluginsSearchPlaceholder')"
          class="ui-input !pl-8 !py-1.5 !text-xs w-full"
        />
      </div>

      <div class="flex items-center gap-2 flex-wrap text-xs">
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
          <button
            type="button"
            class="px-2 py-1 rounded text-[11px] font-medium transition-colors"
            :class="filterType === 'issue' ? 'bg-white dark:bg-gray-800 text-rose-600 dark:text-rose-400 shadow-sm' : 'text-gray-500 hover:text-gray-900 dark:hover:text-gray-300'"
            @click="filterType = 'issue'"
          >
            {{ t('settings.pluginsFilterTabIssue') }}
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
            :disabled="resettingAllMetrics"
            @click="handleResetAllMetrics"
          >
            <RotateCcw class="w-3 h-3" :class="{ 'animate-spin': resettingAllMetrics }" />
          </button>
        </div>

        <!-- 排序选择 -->
        <select
          v-model="sortBy"
          class="ui-input !h-7 !text-[11px] !px-2 !py-0 w-auto bg-gray-50/50 dark:bg-gray-900/50 border-gray-200 dark:border-gray-800"
        >
          <option value="default">{{ t('settings.pluginsSortDefault') }}</option>
          <option value="runs">{{ t('settings.pluginsSortRuns') }}</option>
          <option value="success_rate">{{ t('settings.pluginsSortSuccessRate') }}</option>
          <option value="duration">{{ t('settings.pluginsSortDuration') }}</option>
          <option value="name">{{ t('settings.pluginsSortName') }}</option>
        </select>
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
            <span
              v-if="plugin.permissions && plugin.permissions.length"
              class="px-1.5 py-0.5 rounded text-[10px] font-mono bg-purple-50 dark:bg-purple-950/80 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800/50"
              :title="plugin.permissions.join(', ')"
            >
              {{ t('settings.pluginsPermissions') }}: {{ plugin.permissions.join(', ') }}
            </span>
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

          <!-- 导出源码 -->
          <button
            type="button"
            class="ui-btn-secondary !py-1 !px-2.5 !text-xs inline-flex items-center gap-1 text-slate-600 dark:text-slate-400 hover:text-slate-700"
            :disabled="exportingPluginName === plugin.name"
            :title="t('settings.pluginsExport')"
            @click="handleExportPlugin(plugin)"
          >
            <RefreshCw v-if="exportingPluginName === plugin.name" class="w-3 h-3 animate-spin" />
            <Download v-else class="w-3 h-3" />
            {{ t('settings.pluginsExport') }}
          </button>

          <!-- 说明文档 -->
          <button
            v-if="plugin.doc"
            type="button"
            class="ui-btn-secondary !py-1 !px-2.5 !text-xs inline-flex items-center gap-1 text-teal-600 dark:text-teal-400 hover:text-teal-700"
            :title="t('settings.pluginsViewDoc')"
            @click="openDocModal(plugin)"
          >
            <BookOpen class="w-3 h-3" />
            {{ t('settings.pluginsViewDoc') }}
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

          <!-- 调用历史 -->
          <button
            type="button"
            class="ui-btn-secondary !py-1 !px-2.5 !text-xs inline-flex items-center gap-1 text-indigo-600 dark:text-indigo-400 hover:text-indigo-700"
            :title="t('settings.pluginsHistoryBtn')"
            @click="openHistoryModal(plugin)"
          >
            <History class="w-3 h-3" />
            {{ t('settings.pluginsHistoryBtn') }}
          </button>

          <!-- 克隆 -->
          <button
            type="button"
            class="ui-btn-secondary !py-1 !px-2.5 !text-xs inline-flex items-center gap-1 text-purple-600 dark:text-purple-400 hover:text-purple-700"
            :title="t('settings.pluginsCloneBtn')"
            @click="openCloneModal(plugin)"
          >
            <Copy class="w-3 h-3" />
            {{ t('settings.pluginsCloneBtn') }}
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

    <div
      v-if="!loading && plugins.length > 0 && filteredPlugins.length === 0"
      class="p-8 text-center text-xs text-gray-400 border border-dashed border-gray-200 dark:border-gray-800 rounded-lg"
    >
      {{ t('settings.pluginsEmptyFilter') }}
    </div>

    <!-- 源码查看弹窗 -->
    <Modal
      :title="`${t('settings.pluginsSourceTitle')}: ${currentSourcePlugin?.name ?? ''}`"
      :is-open="isSourceModalOpen"
      max-width-class="max-w-3xl"
      @close="isSourceModalOpen = false"
    >
      <template #header-extra>
        <div class="flex items-center gap-1.5 ml-2">
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
          <textarea
            v-model="editedSourceCode"
            rows="18"
            class="w-full bg-gray-950 text-gray-100 font-mono text-[11px] leading-relaxed p-4 rounded-lg border border-gray-800 focus:outline-none focus:ring-1 focus:ring-amber-500 resize-y"
            spellcheck="false"
          ></textarea>
          <!-- 安全审计风险提醒 -->
          <div v-if="auditWarnings.length > 0" class="p-2.5 rounded bg-amber-50/80 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800/80 text-[11px] font-mono space-y-1">
            <div class="flex items-center gap-1 text-amber-700 dark:text-amber-300 font-semibold">
              <AlertTriangle class="w-3.5 h-3.5" />
              <span>{{ t('settings.pluginsAuditWarnings', { n: auditWarnings.length }) }}</span>
            </div>
            <div v-for="(warn, wIdx) in auditWarnings" :key="wIdx" class="text-amber-800 dark:text-amber-200">
              L{{ warn.line }}: {{ warn.message }}
            </div>
          </div>

          <div class="flex items-center justify-end gap-2">
            <div v-if="syntaxResult" class="mr-auto text-[11px] font-mono flex items-center gap-1 px-2 py-1 rounded" :class="syntaxResult.valid ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800' : 'bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300 border border-rose-200 dark:border-rose-800'">
              <span>{{ syntaxResult.message }}</span>
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
              class="ui-btn-secondary !py-1.5 !px-3 !text-xs"
              :disabled="savingSource"
              @click="isEditingSource = false"
            >
              {{ t('common.cancel') }}
            </button>
            <button
              type="button"
              class="ui-btn-primary !py-1.5 !px-4 !text-xs inline-flex items-center gap-1.5 bg-amber-600 hover:bg-amber-700 text-white"
              :disabled="savingSource"
              @click="saveSourceCode"
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
          <div class="flex items-center justify-between text-gray-700 dark:text-gray-300">
            <label class="font-medium">
              {{ t('settings.pluginsTestInputLabel') }}
              <span v-if="currentTestPlugin.mode === 'active'" class="text-gray-400 font-normal text-[10px]">({{ t('common.optional') }})</span>
            </label>
            <!-- 最近调试用例快照 -->
            <div v-if="currentTestPlugin && testSnapshots[currentTestPlugin.name]?.length" class="flex items-center gap-1.5 mr-2">
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
          <div v-if="showAdvancedMock" class="mt-2.5 grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
            <div>
              <label class="block text-[11px] text-gray-500 dark:text-gray-400 mb-1">{{ t('settings.pluginsMockChatId') }}</label>
              <input
                v-model="mockChatId"
                type="text"
                placeholder="-1001234567890"
                class="ui-input !py-1 !text-xs w-full font-mono"
              />
            </div>
            <div>
              <label class="block text-[11px] text-gray-500 dark:text-gray-400 mb-1">{{ t('settings.pluginsMockSender') }}</label>
              <input
                v-model="mockSenderName"
                type="text"
                placeholder="Tester"
                class="ui-input !py-1 !text-xs w-full"
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
              <option value="regex_extractor">{{ t('settings.pluginsTplRegexExtractor') }}</option>
              <option value="webhook_alert">{{ t('settings.pluginsTplWebhookAlert') }}</option>
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
          <span class="text-[11px] text-gray-500 font-mono">{{ executionHistory.length }} 条记录</span>
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
                {{ rec.trigger_type === 'manual_test' ? t('settings.pluginsHistoryTriggerManual') : rec.trigger_type }}
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
  </section>
</template>
