/**
 * 插件管理 API：获取已加载插件列表、测试运行、重新加载、源码只读查看、模板创建与安全删除。
 */
import { request } from './core'

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
  metrics?: PluginMetrics | null
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

export interface CreatePluginRequest {
  name: string
  mode?: 'reactive' | 'active'
  template?: 'basic_reactive' | 'basic_active' | 'storage_counter' | 'regex_extractor' | 'webhook_alert'
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
}

export async function getPlugins(token: string): Promise<PluginInfo[]> {
  return request<PluginInfo[]>('/plugins', {}, token)
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
  const url = `/api/plugins/${encodeURIComponent(name)}/export`
  const res = await fetch(url, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
  })
  if (!res.ok) {
    throw new Error(`Failed to export plugin: ${res.statusText}`)
  }
  return res.blob()
}

export async function uploadPlugin(file: File, token: string): Promise<PluginInfo> {
  const formData = new FormData()
  formData.append('file', file)
  const res = await fetch('/api/plugins/upload', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
    },
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
): Promise<PluginInfo> {
  return request<PluginInfo>(`/plugins/${encodeURIComponent(name)}/source`, {
    method: 'PUT',
    body: JSON.stringify({ source }),
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
