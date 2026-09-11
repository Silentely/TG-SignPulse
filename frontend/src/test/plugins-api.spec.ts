import { describe, expect, it, vi, beforeEach } from 'vitest'
import * as coreApi from '../lib/api/core'
import {
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
} from '../lib/api/plugins'

describe('plugins api 扩展接口', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('getPluginSource 发起 GET 请求并携带 token', async () => {
    const mockResp = {
      name: 'math_solver',
      version: '1.0.0',
      updated_at: '2026-09-11',
      author: 'TG-SignPulse Team',
      builtin: true,
      source: 'print("hello")',
    }
    const requestSpy = vi.spyOn(coreApi, 'request').mockResolvedValueOnce(mockResp)

    const result = await getPluginSource('math_solver', 'test-token')
    expect(requestSpy).toHaveBeenCalledWith('/plugins/math_solver/source', {}, 'test-token')
    expect(result).toEqual(mockResp)
  })

  it('deletePlugin 发起 DELETE 请求并携带 token', async () => {
    const mockResp = { success: true, name: 'custom_calc', message: '已删除' }
    const requestSpy = vi.spyOn(coreApi, 'request').mockResolvedValueOnce(mockResp)

    const result = await deletePlugin('custom_calc', 'test-token')
    expect(requestSpy).toHaveBeenCalledWith(
      '/plugins/custom_calc',
      { method: 'DELETE' },
      'test-token'
    )
    expect(result).toEqual(mockResp)
  })

  it('createPlugin 发起 POST /plugins/create 并传递 JSON 负载', async () => {
    const payload = {
      name: 'my_plugin',
      mode: 'reactive' as const,
      template: 'basic_reactive' as const,
      description: '描述',
      author: 'Tester',
      version: '1.0.0',
    }
    const mockResp = {
      name: 'my_plugin',
      mode: 'reactive' as const,
      description: '描述',
      version: '1.0.0',
      updated_at: '2026-09-11',
      author: 'Tester',
      builtin: false,
    }
    const requestSpy = vi.spyOn(coreApi, 'request').mockResolvedValueOnce(mockResp)

    const result = await createPlugin(payload, 'test-token')
    expect(requestSpy).toHaveBeenCalledWith(
      '/plugins/create',
      {
        method: 'POST',
        body: JSON.stringify(payload),
      },
      'test-token'
    )
    expect(result).toEqual(mockResp)
  })

  it('getPluginDiagnostics 发起 GET /plugins/diagnostics 请求并携带 token', async () => {
    const mockDiag = {
      total_loaded: 5,
      total_errors: 1,
      load_errors: [
        {
          file_path: 'broken.py',
          plugin_name: 'broken',
          error_type: 'missing_dependency',
          error_message: '缺少依赖 requests',
          missing_module: 'requests',
          suggested_command: 'pip install requests',
        },
      ],
    }
    const requestSpy = vi.spyOn(coreApi, 'request').mockResolvedValueOnce(mockDiag)

    const result = await getPluginDiagnostics('test-token')
    expect(requestSpy).toHaveBeenCalledWith('/plugins/diagnostics', {}, 'test-token')
    expect(result).toEqual(mockDiag)
  })
  it('exportPlugin 发起 GET /api/plugins/:name/export 并返回 Blob', async () => {
    const mockBlob = new Blob(['code'], { type: 'text/x-python' })
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      blob: async () => mockBlob,
    } as Response)

    const blob = await exportPlugin('math_solver', 'test-token')
    expect(fetchSpy).toHaveBeenCalledWith('/api/plugins/math_solver/export', {
      headers: { Authorization: 'Bearer test-token' },
    })
    expect(blob).toBe(mockBlob)
  })

  it('uploadPlugin 发起 POST /api/plugins/upload 携带 FormData', async () => {
    const mockFile = new File(['content'], 'custom.py', { type: 'text/x-python' })
    const mockInfo = { name: 'custom', mode: 'reactive' as const, description: '' }
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      json: async () => mockInfo,
    } as Response)

    const result = await uploadPlugin(mockFile, 'test-token')
    expect(fetchSpy).toHaveBeenCalledWith('/api/plugins/upload', expect.objectContaining({
      method: 'POST',
      headers: { Authorization: 'Bearer test-token' },
    }))
    expect(result).toEqual(mockInfo)
  })

  it('updatePluginSource 发起 PUT /plugins/:name/source 传递源码', async () => {
    const mockInfo = { name: 'custom_calc', mode: 'reactive' as const, description: 'updated' }
    const requestSpy = vi.spyOn(coreApi, 'request').mockResolvedValueOnce(mockInfo)

    const result = await updatePluginSource('custom_calc', 'print("new")', 'test-token')
    expect(requestSpy).toHaveBeenCalledWith(
      '/plugins/custom_calc/source',
      {
        method: 'PUT',
        body: JSON.stringify({ source: 'print("new")' }),
      },
      'test-token',
    )
    expect(result).toEqual(mockInfo)
  })

  it('resetPluginMetrics 发起 POST /plugins/:name/reset-metrics', async () => {
    const mockResp = { success: true, name: 'math_solver', message: '已重置' }
    const requestSpy = vi.spyOn(coreApi, 'request').mockResolvedValueOnce(mockResp)

    const result = await resetPluginMetrics('math_solver', 'test-token')
    expect(requestSpy).toHaveBeenCalledWith(
      '/plugins/math_solver/reset-metrics',
      { method: 'POST' },
      'test-token',
    )
    expect(result).toEqual(mockResp)
  })

  it('batchTogglePlugins 发起 POST /plugins/batch-toggle 传递 enabled', async () => {
    const mockResp = { success: true, count: 2, enabled: true }
    const requestSpy = vi.spyOn(coreApi, 'request').mockResolvedValueOnce(mockResp)

    const result = await batchTogglePlugins(true, 'test-token')
    expect(requestSpy).toHaveBeenCalledWith(
      '/plugins/batch-toggle',
      {
        method: 'POST',
        body: JSON.stringify({ enabled: true }),
      },
      'test-token',
    )
    expect(result).toEqual(mockResp)
  })

  it('resetAllPluginMetrics 发起 POST /plugins/reset-all-metrics', async () => {
    const mockResp = { success: true, message: '已重置' }
    const requestSpy = vi.spyOn(coreApi, 'request').mockResolvedValueOnce(mockResp)

    const result = await resetAllPluginMetrics('test-token')
    expect(requestSpy).toHaveBeenCalledWith(
      '/plugins/reset-all-metrics',
      { method: 'POST' },
      'test-token',
    )
    expect(result).toEqual(mockResp)
  })
})
