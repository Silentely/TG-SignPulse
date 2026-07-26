import { describe, it, expect } from 'vitest'
import * as api from '../lib/api'
import * as core from '../lib/api/core'

describe('api barrel 完整性', () => {
  it('认证 API 导出', () => {
    expect(typeof api.login).toBe('function')
    expect(typeof api.getMe).toBe('function')
    expect(typeof api.resetTOTP).toBe('function')
  })
  it('账号 API 导出', () => {
    expect(typeof api.listAccounts).toBe('function')
    expect(typeof api.startAccountLogin).toBe('function')
    expect(typeof api.deleteAccount).toBe('function')
    expect(typeof api.updateAccount).toBe('function')
    expect(typeof api.startQrLogin).toBe('function')
    expect(typeof api.fetchAccountAvatar).toBe('function')
  })
  it('sign-tasks API 导出', () => {
    expect(typeof api.listSignTasks).toBe('function')
    expect(typeof api.createSignTask).toBe('function')
    expect(typeof api.deleteSignTask).toBe('function')
    expect(typeof api.cloneSignTask).toBe('function')
    expect(typeof api.batchSignTasks).toBe('function')
    expect(typeof api.fetchChatAvatar).toBe('function')
  })
  it('keyword-hits API 导出', () => {
    expect(typeof api.listKeywordHits).toBe('function')
    expect(typeof api.exportKeywordHitsUrl).toBe('function')
    expect(typeof api.exportKeywordHitsBlob).toBe('function')
    expect(typeof api.clearKeywordHits).toBe('function')
  })
  it('config API 导出', () => {
    expect(typeof api.listConfigTasks).toBe('function')
    expect(typeof api.exportAllConfigs).toBe('function')
    expect(typeof api.importConfigPreview).toBe('function')
  })
  it('settings API 导出', () => {
    expect(typeof api.changePassword).toBe('function')
    expect(typeof api.getAIConfig).toBe('function')
    expect(typeof api.getGlobalSettings).toBe('function')
    expect(typeof api.runDeviceKeepalive).toBe('function')
  })
  it('logs API 导出', () => {
    expect(typeof api.getLoginAuditLogs).toBe('function')
    expect(typeof api.getTaskHistoryLogs).toBe('function')
  })
  it('ops API 导出', () => {
    expect(typeof api.listScheduledJobs).toBe('function')
    expect(typeof api.getMemoryStats).toBe('function')
    expect(typeof api.getAppVersion).toBe('function')
  })

  it('core 工具函数不通过 barrel 对外暴露', () => {
    expect((api as Record<string, unknown>).request).toBeUndefined()
    expect((api as Record<string, unknown>).requestBlob).toBeUndefined()
    expect((api as Record<string, unknown>).API_BASE).toBeUndefined()
    expect((api as Record<string, unknown>).toRecord).toBeUndefined()
    expect((api as Record<string, unknown>).DEFAULT_TIMEOUT_MS).toBeUndefined()
  })

  it('core 内部导出完整性（域文件直接 import）', () => {
    expect(typeof core.request).toBe('function')
    expect(typeof core.requestBlob).toBe('function')
    expect(typeof core.requestText).toBe('function')
    expect(typeof core.fetchWithAuth).toBe('function')
    expect(typeof core.API_BASE).toBe('string')
    expect(typeof core.toRecord).toBe('function')
    expect(typeof core.DEFAULT_TIMEOUT_MS).toBe('number')
    expect(typeof core.LONG_TIMEOUT_MS).toBe('number')
    expect(typeof core.MEDIUM_TIMEOUT_MS).toBe('number')
    expect(core.LONG_TIMEOUT_MS).toBeGreaterThan(core.DEFAULT_TIMEOUT_MS)
    expect(core.MEDIUM_TIMEOUT_MS).toBeGreaterThan(core.DEFAULT_TIMEOUT_MS)
    expect(core.MEDIUM_TIMEOUT_MS).toBeLessThan(core.LONG_TIMEOUT_MS)
  })

  it('barrel 导出函数数量 >= 80（防意外删减）', () => {
    const fns = Object.values(api).filter(v => typeof v === 'function')
    expect(fns.length).toBeGreaterThanOrEqual(80)
  })
})
