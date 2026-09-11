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
  getPluginHistory,
  clonePlugin,
  getPluginDependencies,
  getPluginConfig,
  updatePluginConfig,
  resetPluginConfig,
  exportAllPlugins,
  importPluginsBundle,
  checkPluginSyntax,
  clearPluginHistory,
  auditPluginSource,
  testPlugin,
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

  it('getPluginHistory 发起 GET /plugins/:name/history', async () => {
    const mockResp = { name: 'test_p', history: [] }
    const requestSpy = vi.spyOn(coreApi, 'request').mockResolvedValueOnce(mockResp)

    const result = await getPluginHistory('test_p', 'test-token', 10)
    expect(requestSpy).toHaveBeenCalledWith(
      '/plugins/test_p/history?limit=10',
      {},
      'test-token',
    )
    expect(result).toEqual(mockResp)
  })

  it('clonePlugin 发起 POST /plugins/:name/clone', async () => {
    const mockResp = { name: 'new_p', mode: 'reactive', enabled: true, builtin: false }
    const requestSpy = vi.spyOn(coreApi, 'request').mockResolvedValueOnce(mockResp)

    const result = await clonePlugin('old_p', { new_name: 'new_p', description: '克隆' }, 'test-token')
    expect(requestSpy).toHaveBeenCalledWith(
      '/plugins/old_p/clone',
      {
        method: 'POST',
        body: JSON.stringify({ new_name: 'new_p', description: '克隆' }),
      },
      'test-token',
    )
    expect(result).toEqual(mockResp)
  })

  it('getPluginDependencies 发起 GET /plugins/:name/dependencies', async () => {
    const mockResp = { name: 'dep_p', dependencies: [{ module: 'requests', installed: true }] }
    const requestSpy = vi.spyOn(coreApi, 'request').mockResolvedValueOnce(mockResp)

    const result = await getPluginDependencies('dep_p', 'test-token')
    expect(requestSpy).toHaveBeenCalledWith('/plugins/dep_p/dependencies', {}, 'test-token')
    expect(result).toEqual(mockResp)
  })

  it('getPluginConfig 发起 GET /plugins/:name/config', async () => {
    const mockResp = { name: 'cfg_p', params: { a: 1 }, is_customized: false }
    const requestSpy = vi.spyOn(coreApi, 'request').mockResolvedValueOnce(mockResp)

    const result = await getPluginConfig('cfg_p', 'test-token')
    expect(requestSpy).toHaveBeenCalledWith('/plugins/cfg_p/config', {}, 'test-token')
    expect(result).toEqual(mockResp)
  })

  it('updatePluginConfig 发起 PUT /plugins/:name/config', async () => {
    const mockResp = { name: 'cfg_p', params: { a: 2 }, is_customized: true }
    const requestSpy = vi.spyOn(coreApi, 'request').mockResolvedValueOnce(mockResp)

    const result = await updatePluginConfig('cfg_p', { a: 2 }, 'test-token')
    expect(requestSpy).toHaveBeenCalledWith(
      '/plugins/cfg_p/config',
      { method: 'PUT', body: JSON.stringify({ params: { a: 2 } }) },
      'test-token',
    )
    expect(result).toEqual(mockResp)
  })

  it('resetPluginConfig 发起 POST /plugins/:name/reset-config', async () => {
    const mockResp = { name: 'cfg_p', params: { a: 1 }, is_customized: false }
    const requestSpy = vi.spyOn(coreApi, 'request').mockResolvedValueOnce(mockResp)

    const result = await resetPluginConfig('cfg_p', 'test-token')
    expect(requestSpy).toHaveBeenCalledWith(
      '/plugins/cfg_p/reset-config',
      { method: 'POST' },
      'test-token',
    )
    expect(result).toEqual(mockResp)
  })

  it('exportAllPlugins 发起 GET /plugins/export-all 并返回 Blob', async () => {
    const mockBlob = new Blob(['zip content'], { type: 'application/zip' })
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      blob: async () => mockBlob,
    } as Response)

    const blob = await exportAllPlugins('test-token')
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining('/plugins/export-all'),
      expect.objectContaining({
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
      }),
    )
    expect(blob).toBe(mockBlob)
  })

  it('importPluginsBundle 发起 POST /plugins/import-bundle 上传 FormData', async () => {
    const mockResult = { imported_count: 2, files: ['p1', 'p2'], errors: [] }
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce({
      ok: true,
      json: async () => mockResult,
    } as Response)

    const mockFile = new File(['mock zip'], 'plugins.zip', { type: 'application/zip' })
    const result = await importPluginsBundle(mockFile, 'test-token')
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.stringContaining('/plugins/import-bundle'),
      expect.objectContaining({
        method: 'POST',
        headers: expect.objectContaining({ Authorization: 'Bearer test-token' }),
        body: expect.any(FormData),
      }),
    )
    expect(result).toEqual(mockResult)
  })

  it('checkPluginSyntax 发起 POST /plugins/check-syntax 传递 source', async () => {
    const mockResp = { valid: true }
    const requestSpy = vi.spyOn(coreApi, 'request').mockResolvedValueOnce(mockResp)

    const result = await checkPluginSyntax('import os', 'test-token')
    expect(requestSpy).toHaveBeenCalledWith(
      '/plugins/check-syntax',
      {
        method: 'POST',
        body: JSON.stringify({ source: 'import os' }),
      },
      'test-token',
    )
    expect(result).toEqual(mockResp)
  })

  it('clearPluginHistory 发起 POST /plugins/{name}/clear-history', async () => {
    const mockResp = { status: 'ok', name: 'demo_p', cleared_count: 5 }
    const requestSpy = vi.spyOn(coreApi, 'request').mockResolvedValueOnce(mockResp)

    const result = await clearPluginHistory('demo_p', 'test-token')
    expect(requestSpy).toHaveBeenCalledWith(
      '/plugins/demo_p/clear-history',
      {
        method: 'POST',
      },
      'test-token',
    )
    expect(result).toEqual(mockResp)
  })

  it('auditPluginSource 发起 POST /plugins/audit-source', async () => {
    const mockResp = {
      passed: false,
      warnings: [{ line: 10, column: 4, severity: 'high', rule: 'disallowed-call:eval', message: 'dangerous' }],
    }
    const requestSpy = vi.spyOn(coreApi, 'request').mockResolvedValueOnce(mockResp)

    const result = await auditPluginSource('eval("1")', 'test-token')
    expect(requestSpy).toHaveBeenCalledWith(
      '/plugins/audit-source',
      {
        method: 'POST',
        body: JSON.stringify({ source: 'eval("1")' }),
      },
      'test-token',
    )
    expect(result).toEqual(mockResp)
  })

  it('testPlugin 支持传递 timeout 超时参数', async () => {
    const mockResp = { name: 'timeout_p', success: true, handled: true, logs: [] }
    const requestSpy = vi.spyOn(coreApi, 'request').mockResolvedValueOnce(mockResp)

    const result = await testPlugin('timeout_p', { text: 'ping', timeout: 3.5 }, 'test-token')
    expect(requestSpy).toHaveBeenCalledWith(
      '/plugins/timeout_p/test',
      {
        method: 'POST',
        body: JSON.stringify({ text: 'ping', timeout: 3.5 }),
      },
      'test-token',
    )
    expect(result).toEqual(mockResp)
  })
})
