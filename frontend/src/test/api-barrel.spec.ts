import { describe, it, expect } from 'vitest'
import * as api from '../lib/api'

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
  })
  it('sign-tasks API 导出', () => {
    expect(typeof api.listSignTasks).toBe('function')
    expect(typeof api.createSignTask).toBe('function')
    expect(typeof api.deleteSignTask).toBe('function')
    expect(typeof api.cloneSignTask).toBe('function')
    expect(typeof api.batchSignTasks).toBe('function')
  })
  it('keyword-hits API 导出', () => {
    expect(typeof api.listKeywordHits).toBe('function')
    expect(typeof api.exportKeywordHitsUrl).toBe('function')
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
})
