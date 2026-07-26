/**
 * 系统设置表单纯函数：分段 payload 与脏检查快照。
 * 供 Settings.vue 使用，并便于单元测试。
 */

export type SettingsFormState = {
  checkInterval: string
  logDays: number | ''
  dataDir: string
  proxy: string
  concurrency: number | ''
  deviceKeepaliveEnabled: boolean
  deviceKeepaliveIntervalDays: number | ''
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
  webdavUrl: string
  webdavUsername: string
  webdavPassword: string
  webdavRemoteDir: string
}

export type TgFormState = { api_id: string; api_hash: string }
export type AiFormState = { base_url: string; model: string; api_key: string }

export type SettingsSection = 'general' | 'bot' | 'advanced' | 'tg' | 'ai'

export function emptyToNull(v: string | number | '' | null | undefined): number | null {
  if (v === '' || v === null || v === undefined) return null
  const n = typeof v === 'number' ? v : parseInt(String(v), 10)
  return Number.isFinite(n) ? n : null
}

/**
 * 数字输入框 value → 表单值。
 * 空串保留 ''（由 payload 归一化默认值）；非法/NaN 同样回落为 ''，避免写入 NaN。
 */
export function parseNumberInputValue(raw: string): number | '' {
  if (raw === '') return ''
  const n = Number(raw)
  return Number.isFinite(n) ? n : ''
}

export function buildGeneralPayload(s: SettingsFormState) {
  return {
    sign_interval: emptyToNull(s.checkInterval),
    log_retention_days: emptyToNull(s.logDays) ?? 7,
    data_dir: s.dataDir || null,
    global_proxy: s.proxy || null,
    tg_global_concurrency: emptyToNull(s.concurrency) ?? 1,
    device_keepalive_enabled: s.deviceKeepaliveEnabled,
    device_keepalive_interval_days: emptyToNull(s.deviceKeepaliveIntervalDays) ?? 30,
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
    // 空 Token 表示不覆盖服务端已有值
    ...(s.botToken ? { telegram_bot_token: s.botToken } : {}),
    telegram_bot_chat_id: s.botChatId || null,
    telegram_bot_message_thread_id: emptyToNull(s.botThreadId),
  }
}

/** AI 区块内的运行时参数（任务超时/冷却/视觉等），由「保存 AI 配置」一并提交 */
export function buildAiRuntimePayload(s: SettingsFormState) {
  return {
    sign_task_execution_timeout: emptyToNull(s.execTimeout),
    sign_task_account_cooldown: emptyToNull(s.accountCooldown),
    sign_task_flow_retry_attempts: emptyToNull(s.flowRetry),
    sign_task_history_max_age_days: emptyToNull(s.historyMaxAge),
    ai_vision_timeout: emptyToNull(s.aiVisionTimeout),
    ai_vision_retry_attempts: emptyToNull(s.aiVisionRetry),
  }
}

/** 数据管理区块：自动备份 + WebDAV，由「保存备份设置」提交 */
export function buildBackupPayload(s: SettingsFormState) {
  return {
    auto_backup_enabled: s.autoBackupEnabled,
    auto_backup_interval_hours: s.autoBackupInterval || 24,
    auto_backup_keep: s.autoBackupKeep || 3,
    webdav_url: s.webdavUrl || null,
    webdav_username: s.webdavUsername || null,
    // 空密码表示不覆盖服务端已有值
    ...(s.webdavPassword ? { webdav_password: s.webdavPassword } : {}),
    webdav_remote_dir: s.webdavRemoteDir || 'tg-signpulse-backups',
  }
}

/** 兼容：运行时参数 + 备份/WebDAV 全量 advanced 字段（saveAll / WebDAV 操作） */
export function buildAdvancedPayload(s: SettingsFormState) {
  return {
    ...buildAiRuntimePayload(s),
    ...buildBackupPayload(s),
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
      // 仅备份/WebDAV（数据管理区）；AI 运行时参数归入 ai 段
      return JSON.stringify({
        autoBackupEnabled: s.autoBackupEnabled,
        autoBackupInterval: s.autoBackupInterval,
        autoBackupKeep: s.autoBackupKeep,
        webdavUrl: s.webdavUrl,
        webdavUsername: s.webdavUsername,
        webdavPassword: s.webdavPassword ? '***set***' : '',
        webdavRemoteDir: s.webdavRemoteDir,
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
        execTimeout: s.execTimeout,
        accountCooldown: s.accountCooldown,
        flowRetry: s.flowRetry,
        historyMaxAge: s.historyMaxAge,
        aiVisionTimeout: s.aiVisionTimeout,
        aiVisionRetry: s.aiVisionRetry,
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

/** 服务端全局设置 → 表单字段（不含密钥明文） */
export function applyGlobalSettingsToForm(
  s: SettingsFormState,
  res: {
    sign_interval?: number | null
    log_retention_days?: number
    data_dir?: string | null
    global_proxy?: string | null
    tg_global_concurrency?: number | null
    device_keepalive_enabled?: boolean
    device_keepalive_interval_days?: number
    telegram_bot_notify_enabled?: boolean
    telegram_bot_login_notify_enabled?: boolean
    telegram_bot_task_failure_enabled?: boolean
    telegram_bot_task_success_enabled?: boolean
    telegram_bot_quiet_hours_enabled?: boolean
    telegram_bot_quiet_hours_start?: string | null
    telegram_bot_quiet_hours_end?: string | null
    telegram_bot_token_set?: boolean
    telegram_bot_chat_id?: string | null
    telegram_bot_message_thread_id?: number | null
    timezone?: string
    sign_task_execution_timeout?: number | null
    sign_task_account_cooldown?: number | null
    sign_task_flow_retry_attempts?: number | null
    sign_task_history_max_age_days?: number | null
    ai_vision_timeout?: number | null
    ai_vision_retry_attempts?: number | null
    auto_backup_enabled?: boolean
    auto_backup_interval_hours?: number | null
    auto_backup_keep?: number | null
    webdav_url?: string | null
    webdav_username?: string | null
    webdav_password_set?: boolean
    webdav_remote_dir?: string | null
  },
): { botTokenSet: boolean; webdavPasswordSet: boolean } {
  s.checkInterval = res.sign_interval ? String(res.sign_interval) : ''
  s.logDays = res.log_retention_days || 7
  s.dataDir = res.data_dir || ''
  s.proxy = res.global_proxy || ''
  s.concurrency = res.tg_global_concurrency || 1
  s.deviceKeepaliveEnabled = res.device_keepalive_enabled !== false
  s.deviceKeepaliveIntervalDays = res.device_keepalive_interval_days || 30
  s.botEnabled = res.telegram_bot_notify_enabled || false
  s.botLoginNotify = res.telegram_bot_login_notify_enabled || false
  s.botTaskFailure = res.telegram_bot_task_failure_enabled || false
  s.botTaskSuccess = res.telegram_bot_task_success_enabled || false
  s.quietEnabled = res.telegram_bot_quiet_hours_enabled || false
  s.quietStart = res.telegram_bot_quiet_hours_start || '23:00'
  s.quietEnd = res.telegram_bot_quiet_hours_end || '07:00'
  s.botToken = ''
  s.botChatId = res.telegram_bot_chat_id || ''
  s.botThreadId = res.telegram_bot_message_thread_id
    ? String(res.telegram_bot_message_thread_id)
    : ''
  s.timezone = res.timezone || 'Asia/Hong_Kong'
  s.execTimeout = res.sign_task_execution_timeout ?? ''
  s.accountCooldown = res.sign_task_account_cooldown ?? ''
  s.flowRetry = res.sign_task_flow_retry_attempts ?? ''
  s.historyMaxAge = res.sign_task_history_max_age_days ?? ''
  s.aiVisionTimeout = res.ai_vision_timeout ?? ''
  s.aiVisionRetry = res.ai_vision_retry_attempts ?? ''
  s.autoBackupEnabled = res.auto_backup_enabled || false
  s.autoBackupInterval = res.auto_backup_interval_hours || 24
  s.autoBackupKeep = res.auto_backup_keep || 3
  s.webdavUrl = res.webdav_url || ''
  s.webdavUsername = res.webdav_username || ''
  s.webdavPassword = ''
  s.webdavRemoteDir = res.webdav_remote_dir || 'tg-signpulse-backups'
  return {
    botTokenSet: !!res.telegram_bot_token_set,
    webdavPasswordSet: !!res.webdav_password_set,
  }
}
