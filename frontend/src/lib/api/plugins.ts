/**
 * 插件管理 API：获取已加载插件列表及重新加载插件。
 */
import { request } from './core'

export interface PluginInfo {
  name: string
  mode: 'reactive' | 'active'
  description: string
  source_path?: string | null
}

export interface ReloadPluginsResponse {
  count: number
  plugins: PluginInfo[]
}

export async function getPlugins(): Promise<PluginInfo[]> {
  return request<PluginInfo[]>('/plugins')
}

export async function reloadPlugins(): Promise<ReloadPluginsResponse> {
  return request<ReloadPluginsResponse>('/plugins/reload', {
    method: 'POST',
  })
}
