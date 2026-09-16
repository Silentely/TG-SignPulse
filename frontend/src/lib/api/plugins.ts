/**
 * 插件管理 API：获取已加载插件列表、测试运行、重新加载、源码只读查看、模板创建与安全删除。
 */
import { API_BASE, request } from './core'

export interface PluginParamSchema {
  name: string
  label?: string
  type?: 'string' | 'number' | 'boolean' | 'select' | 'bool' | 'int'
  default?: unknown
  placeholder?: string
  options?: Array<{ label: string; value: unknown }>
  description?: string
  required?: boolean
}

export interface PluginMetrics {
  run_count: number
  success_count: number
  failure_count: number
  last_run_at: string | null
  last_duration_ms: number
  avg_duration_ms: number
  success_rate: number
  last_error: string | null
}

export interface PluginInfo {
  name: string
  mode: 'reactive' | 'active'
  description: string
  version?: string
  updated_at?: string
  author?: string
  source_path?: string | null
  params_schema?: PluginParamSchema[]
  enabled?: boolean
  builtin?: boolean
  permissions?: string[]
  doc?: string | null
  category?: string | null
  tags?: string[]
  icon?: string | null
  homepage?: string | null
  recent_results?: boolean[]
  metrics?: PluginMetrics | null
}

export interface PluginStorageRecord {
  key: string
  value: unknown
  expires_at?: number | null
  ttl_remaining?: number | null
}

export interface PluginStorageNamespaceData {
  namespace: string
  is_test: boolean
  chat_id?: string | null
  records: PluginStorageRecord[]
}

export interface PluginStorageResponse {
  plugin_name: string
  total_records: number
  namespaces: PluginStorageNamespaceData[]
}

export interface ClearPluginStorageResponse {
  success: boolean
  plugin_name: string
  deleted_count: number
  message: string
}

export interface PluginSourceResponse {
  name: string
  version?: string
  updated_at?: string
  author?: string
  builtin?: boolean
  source_path?: string | null
  source: string
}

export interface PluginDependency {
  module: string
  installed: boolean
  version?: string | null
  install_command?: string | null
}

export interface PluginDependenciesResponse {
  name: string
  dependencies: PluginDependency[]
}

export interface PluginManifestItem {
  name: string
  mode: string
  description: string
  version: string
  updated_at: string
  author: string
  enabled: boolean
  builtin: boolean
  permissions: string[]
  params_schema: Array<Record<string, unknown>>
  doc?: string | null
}

export interface AuditPluginWarning {
  line: number
  column: number
  severity: string
  rule: string
  message: string
}

export interface AuditPluginResponse {
  passed: boolean
  score?: number
  risk_level?: string
  warnings: AuditPluginWarning[]
  detected_capabilities?: string[]
  declared_permissions?: string[]
  undeclared_capabilities?: string[]
  can_save_safely?: boolean
}

export interface FormatPluginSourceResponse {
  formatted: string
  changed: boolean
  /** 实际使用的格式化器：black（无损）或 ast（有损，丢失注释） */
  formatter: string
  /** 降级为 ast.unparse 时为 true，格式化结果会丢失全部注释 */
  lossy: boolean
}

export interface CheckSyntaxResponse {
  valid: boolean
  line?: number | null
  column?: number | null
  error?: string | null
}

export interface ImportBundleResponse {
  imported_count: number
  files: string[]
  errors: string[]
}

export interface MarketPluginItem {
  id: string
  name: string
  version: string
  mode: "reactive" | "active"
  category: "utility" | "notification" | "message" | "captcha" | "helper" | "entertainment" | string
  description: string
  author: string
  homepage?: string | null
  icon?: string | null
  tags?: string[]
  min_app_version?: string | null
  permissions?: string[]
  params_schema?: PluginParamSchema[]
  download_url: string
  sha256?: string | null
  size?: number
  readme?: string | null
  updated_at?: string | null
  installed: boolean
  installed_version?: string | null
  installed_is_builtin: boolean
  status: "not_installed" | "installed" | "upgradable"
}

export interface MarketSourceConfig {
  source_type: "github" | "jsdelivr" | "ghproxy" | "local" | "custom"
  custom_url?: string | null
  active_url: string
}

export interface MarketCatalogResponse {
  total: number
  source_type: string
  source_url: string
  plugins: MarketPluginItem[]
  cached: boolean
}

export interface PluginExecutionRecord {
  timestamp: string
  duration_ms: number
  success: boolean
  trigger_type: string
  error?: string | null
  log_summary?: string | null
}

export interface PluginHistoryResponse {
  name: string
  history: PluginExecutionRecord[]
}

export interface ClonePluginRequest {
  new_name: string
  description?: string
}

export interface CreatePluginRequest {
  name: string
  mode?: 'reactive' | 'active'
  template?: 'basic_reactive' | 'basic_active' | 'storage_counter' | 'regex_extractor' | 'webhook_alert' | 'http_api_fetcher' | 'command_router' | 'keyword_reply'
  description?: string
  author?: string
  version?: string
}

export interface PluginLoadErrorItem {
  file_path: string
  plugin_name: string
  error_type: "missing_dependency" | "syntax_error" | "load_error" | string
  error_message: string
  missing_module?: string | null
  suggested_command?: string | null
  timestamp?: string
}

export interface PluginDiagnosticsResponse {
  total_loaded: number
  total_errors: number
  load_errors: PluginLoadErrorItem[]
}

export interface ReloadPluginsResponse {
  count: number
  plugins: PluginInfo[]
}

export interface PluginTestRequest {
  text?: string
  params?: Record<string, unknown>
  reset_storage?: boolean
  chat_id?: number | string
  sender_name?: string
  timeout?: number
}

export interface PluginTestResponse {
  name: string
  mode?: "reactive" | "active" | string
  success: boolean
  handled: boolean
  isolation?: string
  killed?: boolean
  reply_text?: string | null
  sent_messages?: string[]
  reacted_emojis?: string[]
  logs?: string[]
  duration_ms: number
  error?: string | null
  traceback?: string | null
  error_line?: number | null
  param_warnings?: string[]
}

export interface PluginFilterParams {
  mode?: 'reactive' | 'active'
  category?: string
  enabled?: boolean
  search?: string
}

export async function getPlugins(token: string, filters?: PluginFilterParams): Promise<PluginInfo[]> {
  const query = new URLSearchParams()
  if (filters?.mode) query.set('mode', filters.mode)
  if (filters?.category) query.set('category', filters.category)
  if (filters?.enabled !== undefined) query.set('enabled', String(filters.enabled))
  if (filters?.search) query.set('search', filters.search)
  const qs = query.toString()
  return request<PluginInfo[]>(qs ? `/plugins?${qs}` : '/plugins', {}, token)
}

export async function reloadPlugins(
  token: string,
): Promise<ReloadPluginsResponse> {
  return request<ReloadPluginsResponse>('/plugins/reload', {
    method: 'POST',
  }, token)
}

export async function togglePlugin(
  name: string,
  token: string,
): Promise<PluginInfo> {
  return request<PluginInfo>(`/plugins/${encodeURIComponent(name)}/toggle`, {
    method: 'POST',
  }, token)
}

export async function testPlugin(
  name: string,
  payload: PluginTestRequest,
  token: string,
): Promise<PluginTestResponse> {
  return request<PluginTestResponse>(`/plugins/${encodeURIComponent(name)}/test`, {
    method: 'POST',
    body: JSON.stringify(payload),
  }, token)
}

export async function installRemotePlugin(
  url: string,
  filename: string | undefined,
  token: string,
): Promise<PluginInfo> {
  return request<PluginInfo>('/plugins/install-remote', {
    method: 'POST',
    body: JSON.stringify({ url, filename }),
  }, token)
}

export async function getPluginSource(
  name: string,
  token: string,
): Promise<PluginSourceResponse> {
  return request<PluginSourceResponse>(`/plugins/${encodeURIComponent(name)}/source`, {}, token)
}

export async function deletePlugin(
  name: string,
  token: string,
): Promise<{ success: boolean; name: string; message: string }> {
  return request<{ success: boolean; name: string; message: string }>(`/plugins/${encodeURIComponent(name)}`, {
    method: 'DELETE',
  }, token)
}

export async function createPlugin(
  payload: CreatePluginRequest,
  token: string,
): Promise<PluginInfo> {
  return request<PluginInfo>('/plugins/create', {
    method: 'POST',
    body: JSON.stringify(payload),
  }, token)
}

export async function getPluginDiagnostics(token: string): Promise<PluginDiagnosticsResponse> {
  return request<PluginDiagnosticsResponse>('/plugins/diagnostics', {}, token)
}

export async function exportPlugin(name: string, token: string): Promise<Blob> {
  const url = `${API_BASE}/plugins/${encodeURIComponent(name)}/export`
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(url, { headers })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `Failed to export plugin: ${res.statusText}`)
  }
  return res.blob()
}

export async function uploadPlugin(file: File, token: string): Promise<PluginInfo> {
  const formData = new FormData()
  formData.append('file', file)
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${API_BASE}/plugins/upload`, {
    method: 'POST',
    headers,
    body: formData,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || 'Upload failed')
  }
  return res.json()
}

export async function updatePluginSource(
  name: string,
  source: string,
  token: string,
  force = false,
): Promise<PluginInfo> {
  return request<PluginInfo>(`/plugins/${encodeURIComponent(name)}/source`, {
    method: 'PUT',
    body: JSON.stringify({ source, force }),
  }, token)
}

export async function resetPluginMetrics(
  name: string,
  token: string,
): Promise<{ success: boolean; name: string; message: string }> {
  return request<{ success: boolean; name: string; message: string }>(`/plugins/${encodeURIComponent(name)}/reset-metrics`, {
    method: 'POST',
  }, token)
}

export async function batchTogglePlugins(
  enabled: boolean,
  token: string,
): Promise<{ success: boolean; count: number; enabled: boolean }> {
  return request<{ success: boolean; count: number; enabled: boolean }>('/plugins/batch-toggle', {
    method: 'POST',
    body: JSON.stringify({ enabled }),
  }, token)
}

export async function resetAllPluginMetrics(
  token: string,
): Promise<{ success: boolean; message: string }> {
  return request<{ success: boolean; message: string }>('/plugins/reset-all-metrics', {
    method: 'POST',
  }, token)
}

export async function getPluginHistory(
  name: string,
  token: string,
  limit = 20,
): Promise<PluginHistoryResponse> {
  return request<PluginHistoryResponse>(`/plugins/${encodeURIComponent(name)}/history?limit=${limit}`, {}, token)
}

export async function clonePlugin(
  name: string,
  data: ClonePluginRequest,
  token: string,
): Promise<PluginInfo> {
  return request<PluginInfo>(`/plugins/${encodeURIComponent(name)}/clone`, {
    method: 'POST',
    body: JSON.stringify(data),
  }, token)
}
export async function getPluginDependencies(
  name: string,
  token: string,
): Promise<PluginDependenciesResponse> {
  return request<PluginDependenciesResponse>(`/plugins/${encodeURIComponent(name)}/dependencies`, {}, token)
}

export async function exportAllPlugins(token: string): Promise<Blob> {
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${API_BASE}/plugins/export-all`, { headers })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to export all plugins')
  }
  return res.blob()
}

export async function importPluginsBundle(
  file: File,
  token: string,
): Promise<ImportBundleResponse> {
  const formData = new FormData()
  formData.append('file', file)
  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(`${API_BASE}/plugins/import-bundle`, {
    method: 'POST',
    headers,
    body: formData,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Failed to import bundle')
  }
  return res.json()
}

export async function checkPluginSyntax(
  source: string,
  token: string,
): Promise<CheckSyntaxResponse> {
  return request<CheckSyntaxResponse>(
    '/plugins/check-syntax',
    {
      method: 'POST',
      body: JSON.stringify({ source }),
    },
    token,
  )
}

export async function clearPluginHistory(
  name: string,
  token: string,
): Promise<{ status: string; name: string; cleared_count: number }> {
  return request<{ status: string; name: string; cleared_count: number }>(
    `/plugins/${encodeURIComponent(name)}/clear-history`,
    {
      method: 'POST',
    },
    token,
  )
}

export async function auditPluginSource(
  source: string,
  token: string,
): Promise<AuditPluginResponse> {
  return request<AuditPluginResponse>(
    '/plugins/audit-source',
    {
      method: 'POST',
      body: JSON.stringify({ source }),
    },
    token,
  )
}

export async function getPluginsManifest(token: string): Promise<PluginManifestItem[]> {
  return request<PluginManifestItem[]>('/plugins/manifest', {}, token)
}

export async function formatPluginSource(
  source: string,
  token: string,
): Promise<FormatPluginSourceResponse> {
  return request<FormatPluginSourceResponse>(
    '/plugins/format-source',
    {
      method: 'POST',
      body: JSON.stringify({ source }),
    },
    token,
  )
}


export async function getMarketCatalog(
  token: string,
  refresh = false,
): Promise<MarketCatalogResponse> {
  return request<MarketCatalogResponse>(`/plugins/market?refresh=${refresh}`, {}, token)
}

export async function getMarketSource(token: string): Promise<MarketSourceConfig> {
  return request<MarketSourceConfig>('/plugins/market/source', {}, token)
}

export async function updateMarketSource(
  source_type: "github" | "jsdelivr" | "ghproxy" | "local" | "custom",
  custom_url: string | undefined,
  token: string,
): Promise<MarketSourceConfig> {
  return request<MarketSourceConfig>('/plugins/market/source', {
    method: 'PUT',
    body: JSON.stringify({ source_type, custom_url }),
  }, token)
}

export async function getMarketPluginReadme(
  pluginId: string,
  token: string,
): Promise<{ id: string; readme: string }> {
  return request<{ id: string; readme: string }>(`/plugins/market/${encodeURIComponent(pluginId)}/readme`, {}, token)
}

export async function installMarketPlugin(
  pluginId: string,
  token: string,
): Promise<PluginInfo> {
  return request<PluginInfo>(`/plugins/market/${encodeURIComponent(pluginId)}/install`, {
    method: 'POST',
  }, token)
}

export async function updateMarketPlugin(
  pluginId: string,
  token: string,
): Promise<PluginInfo> {
  return request<PluginInfo>(`/plugins/market/${encodeURIComponent(pluginId)}/update`, {
    method: 'POST',
  }, token)
}

export async function uninstallMarketPlugin(
  pluginId: string,
  token: string,
): Promise<{ success: boolean; message: string }> {
  return request<{ success: boolean; message: string }>(`/plugins/market/${encodeURIComponent(pluginId)}/uninstall`, {
    method: 'DELETE',
  }, token)
}

export async function getPluginStorage(
  name: string,
  token: string,
): Promise<PluginStorageResponse> {
  return request<PluginStorageResponse>(
    `/plugins/${encodeURIComponent(name)}/storage`,
    {},
    token,
  )
}

export async function clearPluginStorage(
  name: string,
  token: string,
  options?: { namespace?: string; key?: string },
): Promise<ClearPluginStorageResponse> {
  const params = new URLSearchParams()
  if (options?.namespace) params.set("namespace", options.namespace)
  if (options?.key) params.set("key", options.key)
  const qs = params.toString() ? `?${params.toString()}` : ""
  return request<ClearPluginStorageResponse>(
    `/plugins/${encodeURIComponent(name)}/storage${qs}`,
    {
      method: "DELETE",
    },
    token,
  )
}
