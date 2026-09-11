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
  template?: 'basic_reactive' | 'basic_active' | 'storage_counter'
  description?: string
  author?: string
  version?: string
}

export interface ReloadPluginsResponse {
  count: number
  plugins: PluginInfo[]
}

export interface PluginTestRequest {
  text?: string
  params?: Record<string, unknown>
}

export interface PluginTestResponse {
  name: string
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
