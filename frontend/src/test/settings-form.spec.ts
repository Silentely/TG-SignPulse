import { describe, it, expect } from 'vitest'
import {
  emptyToNull,
  buildGeneralPayload,
  buildBotPayload,
  buildAdvancedPayload,
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
  autoBackupEnabled: false,
  autoBackupInterval: 24,
  autoBackupKeep: 3,
})

describe('settings-form', () => {
  it('emptyToNull handles empty and invalid', () => {
    expect(emptyToNull('')).toBeNull()
    expect(emptyToNull('12')).toBe(12)
    expect(emptyToNull('x')).toBeNull()
    expect(emptyToNull(0)).toBe(0)
  })

  it('buildGeneralPayload maps fields', () => {
    const p = buildGeneralPayload(baseSettings())
    expect(p.sign_interval).toBe(30)
    expect(p.log_retention_days).toBe(7)
    expect(p.timezone).toBe('Asia/Hong_Kong')
  })

  it('buildBotPayload parses thread id', () => {
    const s = baseSettings()
    s.botThreadId = '42'
    s.botEnabled = true
    const p = buildBotPayload(s)
    expect(p.telegram_bot_message_thread_id).toBe(42)
    expect(p.telegram_bot_notify_enabled).toBe(true)
  })

  it('buildAdvancedPayload nulls empty numbers', () => {
    const p = buildAdvancedPayload(baseSettings())
    expect(p.sign_task_execution_timeout).toBeNull()
    expect(p.auto_backup_keep).toBe(3)
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
})
