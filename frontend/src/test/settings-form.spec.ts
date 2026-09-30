import { describe, it, expect } from 'vitest'
import {
  emptyToNull,
  parseNumberInputValue,
  applyGlobalSettingsToForm,
  buildGeneralPayload,
  buildBotPayload,
  buildAdvancedPayload,
  buildAiRuntimePayload,
  buildBackupPayload,
  snapAllSections,
  isAnySectionDirty,
  dirtySectionLabels,
  type SettingsFormState,
  type TgFormState,
  type AiFormState,
} from '../lib/settings-form'

const baseSettings = (): SettingsFormState => ({
  checkInterval: '30',
  logDays: 7,
  dataDir: '/data',
  proxy: '',
  concurrency: 2,
  deviceKeepaliveEnabled: true,
  deviceKeepaliveIntervalDays: 30,
  botEnabled: false,
  botLoginNotify: false,
  botTaskFailure: true,
  botTaskSuccess: false,
  quietEnabled: false,
  quietStart: '23:00',
  quietEnd: '07:00',
  botToken: '',
  botChatId: '',
  botThreadId: '',
  timezone: 'Asia/Hong_Kong',
  execTimeout: '',
  accountCooldown: '',
  flowRetry: '',
  historyMaxAge: '',
  aiVisionTimeout: '',
  aiVisionRetry: '',
  aiVisionReasoningEffort: '',
  autoBackupEnabled: false,
  autoBackupInterval: 24,
  autoBackupKeep: 3,
  webdavUrl: '',
  webdavUsername: '',
  webdavPassword: '',
  webdavRemoteDir: 'tg-signpulse-backups',
  backupTarget: 'auto',
})

describe('settings-form', () => {
  it('emptyToNull handles empty and invalid', () => {
    expect(emptyToNull('')).toBeNull()
    expect(emptyToNull('12')).toBe(12)
    expect(emptyToNull('x')).toBeNull()
    expect(emptyToNull(0)).toBe(0)
  })

  it('parseNumberInputValue treats empty string as empty', () => {
    expect(parseNumberInputValue('')).toBe('')
    expect(parseNumberInputValue('0')).toBe(0)
    expect(parseNumberInputValue('15')).toBe(15)
  })

  it('buildGeneralPayload clamps concurrency 1-10', () => {
    const s = baseSettings()
    s.concurrency = 99
    expect(buildGeneralPayload(s).tg_global_concurrency).toBe(10)
    s.concurrency = 0
    expect(buildGeneralPayload(s).tg_global_concurrency).toBe(1)
  })

  it('buildGeneralPayload maps device keepalive fields with clamp', () => {
    const s = baseSettings()
    s.deviceKeepaliveEnabled = false
    s.deviceKeepaliveIntervalDays = 200
    const p = buildGeneralPayload(s)
    expect(p.device_keepalive_enabled).toBe(false)
    expect(p.device_keepalive_interval_days).toBe(170)

    s.deviceKeepaliveIntervalDays = 0
    expect(buildGeneralPayload(s).device_keepalive_interval_days).toBe(1)

    s.deviceKeepaliveIntervalDays = ''
    expect(buildGeneralPayload(s).device_keepalive_interval_days).toBe(30)
  })

  it('buildGeneralPayload respects proxyClearRequested', () => {
    const s = baseSettings()
    s.proxy = 'http://127.0.0.1:7890'
    s.proxyClearRequested = true
    const p = buildGeneralPayload(s)
    expect(p.global_proxy).toBeNull()
  })

  it('buildGeneralPayload omits empty proxy to preserve existing', () => {
    const s = baseSettings()
    s.proxy = ''
    s.proxyClearRequested = false
    const p = buildGeneralPayload(s)
    expect('global_proxy' in p).toBe(false)
  })

  it('buildGeneralPayload includes trimmed non-empty proxy', () => {
    const s = baseSettings()
    s.proxy = ' socks5://proxy:1080 '
    s.proxyClearRequested = false
    const p = buildGeneralPayload(s)
    expect(p.global_proxy).toBe('socks5://proxy:1080')
  })

  it('buildGeneralPayload uses fallback defaults for empty numeric inputs', () => {
    const s = baseSettings()
    s.checkInterval = ''
    s.logDays = ''
    s.concurrency = ''
    s.deviceKeepaliveIntervalDays = ''

    const p = buildGeneralPayload(s)

    expect(p.sign_interval).toBeNull()
    expect(p.log_retention_days).toBe(7)
    expect(p.tg_global_concurrency).toBe(1)
    expect(p.device_keepalive_interval_days).toBe(30)
  })

  it('buildAiRuntimePayload clamps out-of-range numeric values and uses correct field names', () => {
    const s = baseSettings()
    s.execTimeout = 5 // 低于下限 30
    s.accountCooldown = 9999 // 高于上限 600
    s.flowRetry = 0 // 低于下限 1
    s.historyMaxAge = 200 // 高于上限 90
    s.aiVisionTimeout = 1 // 低于下限 3
    s.aiVisionRetry = 99 // 高于上限 8

    const p = buildAiRuntimePayload(s) as Record<string, unknown>

    expect(p.sign_task_execution_timeout).toBe(30)
    expect(p.sign_task_account_cooldown).toBe(600)
    expect(p.sign_task_flow_retry_attempts).toBe(1)
    expect(p.sign_task_history_max_age_days).toBe(90)
    expect('sign_history_max_age_days' in p).toBe(false)
    expect(p.ai_vision_timeout).toBe(3)
    expect(p.ai_vision_retry_attempts).toBe(8)
  })

  it('buildBotPayload parses thread id', () => {
    const s = baseSettings()
    s.botThreadId = '42'
    s.botEnabled = true
    const p = buildBotPayload(s)
    expect(p.telegram_bot_message_thread_id).toBe(42)
    expect(p.telegram_bot_notify_enabled).toBe(true)
  })

  it('buildBotPayload omits empty token (keep server value)', () => {
    const s = baseSettings()
    s.botToken = ''
    const p = buildBotPayload(s) as Record<string, unknown>
    expect('telegram_bot_token' in p).toBe(false)
    s.botToken = '123:ABC'
    const p2 = buildBotPayload(s) as Record<string, unknown>
    expect(p2.telegram_bot_token).toBe('123:ABC')
  })

  it('buildAdvancedPayload nulls empty numbers', () => {
    const p = buildAdvancedPayload(baseSettings())
    expect(p.sign_task_execution_timeout).toBeNull()
    expect(p.auto_backup_keep).toBe(3)
  })

  it('buildAiRuntimePayload only includes runtime fields', () => {
    const s = baseSettings()
    s.execTimeout = 120
    s.aiVisionTimeout = 20
    s.aiVisionReasoningEffort = 'none'
    s.autoBackupEnabled = true
    const p = buildAiRuntimePayload(s) as Record<string, unknown>
    expect(p.sign_task_execution_timeout).toBe(120)
    expect(p.ai_vision_timeout).toBe(20)
    expect(p.ai_vision_reasoning_effort).toBe('none')
    expect('auto_backup_enabled' in p).toBe(false)
    expect('webdav_url' in p).toBe(false)
  })

  it('buildAiRuntimePayload nulls empty reasoning effort', () => {
    const p = buildAiRuntimePayload(baseSettings())
    expect(p.ai_vision_reasoning_effort).toBeNull()
  })

  it('applyGlobalSettingsToForm maps reasoning effort', () => {
    const s = baseSettings()
    applyGlobalSettingsToForm(s, { ai_vision_reasoning_effort: 'high' })
    expect(s.aiVisionReasoningEffort).toBe('high')
    applyGlobalSettingsToForm(s, { ai_vision_reasoning_effort: null })
    expect(s.aiVisionReasoningEffort).toBe('')
  })

  it('buildBackupPayload only includes backup/webdav fields', () => {
    const s = baseSettings()
    s.execTimeout = 120
    s.webdavUrl = 'https://dav.example'
    s.webdavPassword = 'secret'
    const p = buildBackupPayload(s) as Record<string, unknown>
    expect(p.webdav_url).toBe('https://dav.example')
    expect(p.webdav_password).toBe('secret')
    expect('sign_task_execution_timeout' in p).toBe(false)
    expect('ai_vision_timeout' in p).toBe(false)
  })

  it('buildBackupPayload 与 applyGlobalSettingsToForm 正确处理 backup_target 及其类型守卫', () => {
    const s = baseSettings()
    s.backupTarget = 'webdav'
    const p = buildBackupPayload(s) as Record<string, unknown>
    expect(p.backup_target).toBe('webdav')

    // 测试类型守卫：合法值保留，非法值归一化为 auto
    const s2 = baseSettings()
    applyGlobalSettingsToForm(s2, { backup_target: 'webdav' })
    expect(s2.backupTarget).toBe('webdav')

    applyGlobalSettingsToForm(s2, { backup_target: 's3' as any })
    expect(s2.backupTarget).toBe('auto')

    applyGlobalSettingsToForm(s2, { backup_target: 'invalid-target' as any })
    expect(s2.backupTarget).toBe('auto')
  })

  it('buildBackupPayload 空密码不下发 webdav_password', () => {
    const p = buildBackupPayload(baseSettings()) as Record<string, unknown>
    expect('webdav_password' in p).toBe(false)
  })

  it('section dirty is independent', () => {
    const s = baseSettings()
    const tg: TgFormState = { api_id: '', api_hash: '' }
    const ai: AiFormState = { base_url: '', model: '', api_key: '' }
    const baseline = snapAllSections(s, tg, ai)

    const s2 = { ...s, botEnabled: true }
    const cur = snapAllSections(s2, tg, ai)
    expect(isAnySectionDirty(baseline, cur)).toBe(true)
    // 仅 bot 脏：general 快照应相同
    expect(cur.general).toBe(baseline.general)
    expect(cur.bot).not.toBe(baseline.bot)

    const labels = dirtySectionLabels(baseline, cur, {
      general: 'G',
      bot: 'B',
      advanced: 'A',
      tg: 'T',
      ai: 'I',
    })
    expect(labels).toEqual(['B'])
  })

  it('ai runtime fields dirty ai section; backup fields dirty advanced', () => {
    const s = baseSettings()
    const tg: TgFormState = { api_id: '', api_hash: '' }
    const ai: AiFormState = { base_url: '', model: '', api_key: '' }
    const baseline = snapAllSections(s, tg, ai)

    const sRuntime = { ...s, execTimeout: 90 }
    const curRuntime = snapAllSections(sRuntime, tg, ai)
    expect(curRuntime.ai).not.toBe(baseline.ai)
    expect(curRuntime.advanced).toBe(baseline.advanced)

    const sBackup = { ...s, autoBackupEnabled: true }
    const curBackup = snapAllSections(sBackup, tg, ai)
    expect(curBackup.advanced).not.toBe(baseline.advanced)
    expect(curBackup.ai).toBe(baseline.ai)
  })

  it('secret fields mask in snapshot (bot token / ai key)', () => {
    const s = baseSettings()
    s.botToken = '123:ABC'
    const tg: TgFormState = { api_id: '1', api_hash: 'h' }
    const ai: AiFormState = { base_url: 'u', model: 'm', api_key: 'sk' }
    const snap = snapAllSections(s, tg, ai)
    expect(snap.bot).toContain('***set***')
    expect(snap.bot).not.toContain('123:ABC')
    expect(snap.ai).toContain('***set***')
    expect(snap.ai).not.toContain('sk')
  })

  it('buildBotPayload ignores invalid thread id', () => {
    const s = baseSettings()
    s.botThreadId = 'abc'
    const p = buildBotPayload(s)
    expect(p.telegram_bot_message_thread_id).toBeNull()
  })
})

describe('applyGlobalSettingsToForm', () => {
  it('maps server payload into form fields without secrets', () => {
    const s = baseSettings()
    const flags = applyGlobalSettingsToForm(s, {
      sign_interval: 45,
      log_retention_days: 14,
      telegram_bot_token_set: true,
      webdav_password_set: true,
      telegram_bot_message_thread_id: 9,
      timezone: 'UTC',
    })
    expect(s.checkInterval).toBe('45')
    expect(s.logDays).toBe(14)
    expect(s.botToken).toBe('')
    expect(s.webdavPassword).toBe('')
    expect(s.botThreadId).toBe('9')
    expect(s.timezone).toBe('UTC')
    expect(flags.botTokenSet).toBe(true)
    expect(flags.webdavPasswordSet).toBe(true)
  })
})
