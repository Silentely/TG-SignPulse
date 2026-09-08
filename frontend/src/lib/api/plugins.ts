/**
 * 插件管理 API：获取已加载插件列表、测试运行与重新加载插件。
 */
import { request } from './core'

export interface PluginParamSchema {
  name: string
  label: string
  type: 'string' | 'int' | 'bool' | 'select'
  default?: string | number | boolean
  placeholder?: string
  options?: Array<{ label: string; value: string | number }>
}

export interface PluginInfo {
  name: string
  mode: 'reactive' | 'active'
  description: string
  source_path?: string | null
  params_schema?: PluginParamSchema[]
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
  reply_text?: string | null
  sent_messages?: string[]
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
