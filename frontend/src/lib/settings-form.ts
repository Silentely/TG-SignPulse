/**
 * 系统设置表单纯函数：分段 payload 与脏检查快照。
 * 供 Settings.vue 使用，并便于单元测试。
 */

export type SettingsFormState = {
  checkInterval: string
  logDays: number
  dataDir: string
  proxy: string
  concurrency: number
  deviceKeepaliveEnabled: boolean
  deviceKeepaliveIntervalDays: number
  botEnabled: boolean
  botLoginNotify: boolean
  botTaskFailure: boolean
  botTaskSuccess: boolean
  quietEnabled: boolean
  quietStart: string
  quietEnd: string
  botToken: string
  botChatId: string
  botThreadId: string
  timezone: string
  execTimeout: string | number
  accountCooldown: string | number
  flowRetry: string | number
  historyMaxAge: string | number
  aiVisionTimeout: string | number
  aiVisionRetry: string | number
  autoBackupEnabled: boolean
  autoBackupInterval: number
  autoBackupKeep: number
}

export type TgFormState = { api_id: string; api_hash: string }
export type AiFormState = { base_url: string; model: string; api_key: string }

export type SettingsSection = 'general' | 'bot' | 'advanced' | 'tg' | 'ai'

export function emptyToNull(v: string | number | '' | null | undefined): number | null {
  if (v === '' || v === null || v === undefined) return null
  const n = typeof v === 'number' ? v : parseInt(String(v), 10)
  return Number.isFinite(n) ? n : null
}

export function buildGeneralPayload(s: SettingsFormState) {
  return {
    sign_interval: s.checkInterval ? parseInt(String(s.checkInterval), 10) : null,
    log_retention_days: s.logDays,
    data_dir: s.dataDir || null,
    global_proxy: s.proxy || null,
    tg_global_concurrency: s.concurrency || 1,
    device_keepalive_enabled: s.deviceKeepaliveEnabled,
    device_keepalive_interval_days: s.deviceKeepaliveIntervalDays || 30,
    timezone: s.timezone,
  }
}

export function buildBotPayload(s: SettingsFormState) {
  return {
    telegram_bot_notify_enabled: s.botEnabled,
    telegram_bot_login_notify_enabled: s.botLoginNotify,
    telegram_bot_task_failure_enabled: s.botTaskFailure,
    telegram_bot_task_success_enabled: s.botTaskSuccess,
    telegram_bot_quiet_hours_enabled: s.quietEnabled,
    telegram_bot_quiet_hours_start: s.quietStart || '23:00',
    telegram_bot_quiet_hours_end: s.quietEnd || '07:00',
    telegram_bot_token: s.botToken || null,
    telegram_bot_chat_id: s.botChatId || null,
    telegram_bot_message_thread_id: s.botThreadId
      ? parseInt(s.botThreadId, 10)
      : null,
  }
}

export function buildAdvancedPayload(s: SettingsFormState) {
  return {
    sign_task_execution_timeout: emptyToNull(s.execTimeout),
    sign_task_account_cooldown: emptyToNull(s.accountCooldown),
    sign_task_flow_retry_attempts: emptyToNull(s.flowRetry),
    sign_task_history_max_age_days: emptyToNull(s.historyMaxAge),
    ai_vision_timeout: emptyToNull(s.aiVisionTimeout),
    ai_vision_retry_attempts: emptyToNull(s.aiVisionRetry),
    auto_backup_enabled: s.autoBackupEnabled,
    auto_backup_interval_hours: s.autoBackupInterval || 24,
    auto_backup_keep: s.autoBackupKeep || 3,
  }
}

/** 分段快照：仅比较该区块相关字段 */
export function snapSection(
  section: SettingsSection,
  s: SettingsFormState,
  tg: TgFormState,
  ai: AiFormState,
): string {
  switch (section) {
    case 'general':
      return JSON.stringify({
        checkInterval: s.checkInterval,
        logDays: s.logDays,
        dataDir: s.dataDir,
        proxy: s.proxy,
        concurrency: s.concurrency,
        deviceKeepaliveEnabled: s.deviceKeepaliveEnabled,
        deviceKeepaliveIntervalDays: s.deviceKeepaliveIntervalDays,
        timezone: s.timezone,
      })
    case 'bot':
      return JSON.stringify({
        botEnabled: s.botEnabled,
        botLoginNotify: s.botLoginNotify,
        botTaskFailure: s.botTaskFailure,
        botTaskSuccess: s.botTaskSuccess,
        quietEnabled: s.quietEnabled,
        quietStart: s.quietStart,
        quietEnd: s.quietEnd,
        botToken: s.botToken ? '***set***' : '',
        botChatId: s.botChatId,
        botThreadId: s.botThreadId,
      })
    case 'advanced':
      return JSON.stringify({
        execTimeout: s.execTimeout,
        accountCooldown: s.accountCooldown,
        flowRetry: s.flowRetry,
        historyMaxAge: s.historyMaxAge,
        aiVisionTimeout: s.aiVisionTimeout,
        aiVisionRetry: s.aiVisionRetry,
        autoBackupEnabled: s.autoBackupEnabled,
        autoBackupInterval: s.autoBackupInterval,
        autoBackupKeep: s.autoBackupKeep,
      })
    case 'tg':
      return JSON.stringify({
        api_id: tg.api_id ? '***set***' : '',
        api_hash: tg.api_hash ? '***set***' : '',
      })
    case 'ai':
      return JSON.stringify({
        base_url: ai.base_url,
        model: ai.model,
        api_key: ai.api_key ? '***set***' : '',
      })
  }
}

export function snapAllSections(
  s: SettingsFormState,
  tg: TgFormState,
  ai: AiFormState,
): Record<SettingsSection, string> {
  return {
    general: snapSection('general', s, tg, ai),
    bot: snapSection('bot', s, tg, ai),
    advanced: snapSection('advanced', s, tg, ai),
    tg: snapSection('tg', s, tg, ai),
    ai: snapSection('ai', s, tg, ai),
  }
}

export function isAnySectionDirty(
  baseline: Record<SettingsSection, string> | null,
  current: Record<SettingsSection, string>,
): boolean {
  if (!baseline) return false
  return (Object.keys(current) as SettingsSection[]).some(
    (k) => baseline[k] !== current[k],
  )
}

export function dirtySectionLabels(
  baseline: Record<SettingsSection, string> | null,
  current: Record<SettingsSection, string>,
  labels: Record<SettingsSection, string>,
): string[] {
  if (!baseline) return []
  return (Object.keys(current) as SettingsSection[])
    .filter((k) => baseline[k] !== current[k])
    .map((k) => labels[k])
}
