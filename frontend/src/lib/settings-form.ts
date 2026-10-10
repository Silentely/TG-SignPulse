/**
 * Settings 表单状态与分段保存/脏状态检测辅助。
 *
 * 页面将全局设置拆分为：通用、Bot 通知、高级（自动备份/WebDAV）、AI（运行时参数）。
 * 此处集中定义表单类型、分段 payload 构造、字段归一化及比较基准快照。
 */
export type SettingsSection = 'general' | 'tg' | 'ai' | 'bot' | 'advanced'

export type SettingsFormState = {
  checkInterval: string
  logDays: number | ''
  dataDir: string
  proxy: string
  /** 显式请求清空代理（输入框变空后保存时向后端下发 null） */
  proxyClearRequested?: boolean
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
  aiVisionReasoningEffort: string
  autoBackupEnabled: boolean
  autoBackupInterval: number | ''
  autoBackupKeep: number | ''
  webdavUrl: string
  webdavUsername: string
  webdavPassword: string
  webdavRemoteDir: string
  backupTarget: 'auto' | 'webdav'
  executionEngine?: string
}

export type TgFormState = { api_id: string; api_hash: string }

export type AiFormState = {
  base_url: string
  model: string
  api_key: string
  /** 备用 AI 节点（故障转移）：api_key 留空表示沿用已保存密钥 */
  fallback_providers: Array<{
    base_url: string
    model: string
    api_key: string
    api_key_masked?: string | null
  }>
}

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

export function clampNumber(
  v: string | number | '' | null | undefined,
  lo: number,
  hi: number,
): number | null {
  const n = emptyToNull(v)
  if (n == null) return null
  return Math.min(hi, Math.max(lo, n))
}

export function buildGeneralPayload(s: SettingsFormState): {
  sign_interval: number | null
  log_retention_days: number
  data_dir: string | null
  global_proxy?: string | null
  tg_global_concurrency: number
  device_keepalive_enabled: boolean
  device_keepalive_interval_days: number
  timezone: string
  execution_engine: string
} {
  return {
    sign_interval: emptyToNull(s.checkInterval),
    log_retention_days: emptyToNull(s.logDays) ?? 7,
    data_dir: s.dataDir || null,
    ...(s.proxyClearRequested
      ? { global_proxy: null }
      : s.proxy.trim()
        ? { global_proxy: s.proxy.trim() }
        : {}),
    tg_global_concurrency: clampNumber(s.concurrency, 1, 10) ?? 1,
    device_keepalive_enabled: s.deviceKeepaliveEnabled,
    device_keepalive_interval_days: clampNumber(s.deviceKeepaliveIntervalDays, 1, 170) ?? 30,
    timezone: s.timezone,
    execution_engine: s.executionEngine || 'v3',
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
    sign_task_execution_timeout: clampNumber(s.execTimeout, 30, 3600),
    sign_task_account_cooldown: clampNumber(s.accountCooldown, 0, 600),
    sign_task_flow_retry_attempts: clampNumber(s.flowRetry, 1, 10),
    sign_task_history_max_age_days: clampNumber(s.historyMaxAge, 1, 90),
    ai_vision_timeout: clampNumber(s.aiVisionTimeout, 3, 120),
    ai_vision_retry_attempts: clampNumber(s.aiVisionRetry, 1, 8),
    ai_vision_reasoning_effort: s.aiVisionReasoningEffort || null,
  }
}

/** 数据管理区块：自动备份 + WebDAV，由「保存备份设置」提交 */
export function buildBackupPayload(s: SettingsFormState) {
  return {
    auto_backup_enabled: s.autoBackupEnabled,
    auto_backup_interval_hours: clampNumber(s.autoBackupInterval, 1, 168) ?? 24,
    auto_backup_keep: clampNumber(s.autoBackupKeep, 1, 30) ?? 3,
    webdav_url: s.webdavUrl || null,
    webdav_username: s.webdavUsername || null,
    // 空密码表示不覆盖服务端已有值
    ...(s.webdavPassword ? { webdav_password: s.webdavPassword } : {}),
    webdav_remote_dir: s.webdavRemoteDir || 'tg-signpulse-backups',
    backup_target: s.backupTarget || 'auto',
  }
}

export function buildAdvancedPayload(s: SettingsFormState) {
  return {
    ...buildAiRuntimePayload(s),
    ...buildBackupPayload(s),
  }
}

/**
 * 针对各区块生成「脱敏后」的比较快照。
 * 密码/Token 字段仅用「是否有输入」占位，避免密码留空保存时误判为 dirty。
 */
export function snapSection(
  sec: SettingsSection,
  s: SettingsFormState,
  tg: TgFormState,
  ai: AiFormState,
): string {
  switch (sec) {
    case 'general':
      return JSON.stringify({
        checkInterval: s.checkInterval,
        logDays: s.logDays,
        dataDir: s.dataDir,
        proxy: s.proxy,
        proxyClearRequested: !!s.proxyClearRequested,
        concurrency: s.concurrency,
        deviceKeepaliveEnabled: s.deviceKeepaliveEnabled,
        deviceKeepaliveIntervalDays: s.deviceKeepaliveIntervalDays,
        timezone: s.timezone,
        executionEngine: s.executionEngine || 'v3',
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
        autoBackupEnabled: s.autoBackupEnabled,
        autoBackupInterval: s.autoBackupInterval,
        autoBackupKeep: s.autoBackupKeep,
        webdavUrl: s.webdavUrl,
        webdavUsername: s.webdavUsername,
        webdavPassword: s.webdavPassword ? '***set***' : '',
        webdavRemoteDir: s.webdavRemoteDir,
        backupTarget: s.backupTarget || 'auto',
      })
    case 'tg':
      return JSON.stringify({
        api_id: tg.api_id,
        api_hash: tg.api_hash,
      })
    case 'ai':
      return JSON.stringify({
        base_url: ai.base_url,
        model: ai.model,
        api_key: ai.api_key ? '***set***' : '',
        fallback_providers: (ai.fallback_providers || []).map((p) => ({
          base_url: p.base_url,
          model: p.model,
          api_key: p.api_key ? '***set***' : (p.api_key_masked || ''),
        })),
        execTimeout: s.execTimeout,
        accountCooldown: s.accountCooldown,
        flowRetry: s.flowRetry,
        historyMaxAge: s.historyMaxAge,
        aiVisionTimeout: s.aiVisionTimeout,
        aiVisionRetry: s.aiVisionRetry,
        aiVisionReasoningEffort: s.aiVisionReasoningEffort,
      })
  }
}

export type SectionSnapshots = Record<SettingsSection, string>

export function snapAllSections(
  s: SettingsFormState,
  tg: TgFormState,
  ai: AiFormState,
): SectionSnapshots {
  return {
    general: snapSection('general', s, tg, ai),
    tg: snapSection('tg', s, tg, ai),
    ai: snapSection('ai', s, tg, ai),
    bot: snapSection('bot', s, tg, ai),
    advanced: snapSection('advanced', s, tg, ai),
  }
}

export function isSectionDirty(
  sec: SettingsSection,
  baseline: SectionSnapshots | null | undefined,
  current: SectionSnapshots | null | undefined,
): boolean {
  if (!baseline || !current) return false
  return baseline[sec] !== current[sec]
}

export function isAnySectionDirty(
  baseline: SectionSnapshots | null | undefined,
  current: SectionSnapshots | null | undefined,
): boolean {
  if (!baseline || !current) return false
  return (['general', 'tg', 'ai', 'bot', 'advanced'] as SettingsSection[]).some((k) =>
    isSectionDirty(k, baseline, current),
  )
}

export function dirtySectionLabels(
  baseline: SectionSnapshots | null | undefined,
  current: SectionSnapshots | null | undefined,
  labels: Record<SettingsSection, string>,
): string[] {
  if (!baseline || !current) return []
  return (['general', 'tg', 'ai', 'bot', 'advanced'] as SettingsSection[])
    .filter((k) => isSectionDirty(k, baseline, current))
    .map((k) => labels[k])
}

export function applyGlobalSettingsToForm(
  s: SettingsFormState,
  res: {
    sign_interval?: number | null
    log_retention_days?: number | null
    data_dir?: string | null
    global_proxy?: string | null
    global_proxy_set?: boolean
    tg_global_concurrency?: number | null
    device_keepalive_enabled?: boolean
    device_keepalive_interval_days?: number | null
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
    ai_vision_reasoning_effort?: string | null
    auto_backup_enabled?: boolean
    auto_backup_interval_hours?: number | null
    auto_backup_keep?: number | null
    webdav_url?: string | null
    webdav_username?: string | null
    webdav_password_set?: boolean
    webdav_remote_dir?: string | null
    backup_target?: string | null
    execution_engine?: string | null
  },
): {
    botTokenSet: boolean
    webdavPasswordSet: boolean
    proxySet: boolean
  } {
  s.checkInterval = res.sign_interval ? String(res.sign_interval) : ''
  s.logDays = res.log_retention_days ?? 7
  s.dataDir = res.data_dir || ''
  s.proxy = res.global_proxy || ''
  s.proxyClearRequested = false
  s.concurrency = res.tg_global_concurrency ?? 1
  s.deviceKeepaliveEnabled = res.device_keepalive_enabled ?? true
  s.deviceKeepaliveIntervalDays = res.device_keepalive_interval_days ?? 30
  s.botEnabled = res.telegram_bot_notify_enabled || false
  s.botLoginNotify = res.telegram_bot_login_notify_enabled || false
  s.botTaskFailure = res.telegram_bot_task_failure_enabled !== false
  s.botTaskSuccess = res.telegram_bot_task_success_enabled || false
  s.quietEnabled = res.telegram_bot_quiet_hours_enabled || false
  s.quietStart = res.telegram_bot_quiet_hours_start || '23:00'
  s.executionEngine = res.execution_engine || 'v3'
  s.quietEnd = res.telegram_bot_quiet_hours_end || '07:00'
  s.botToken = ''
  s.botChatId = res.telegram_bot_chat_id || ''
  s.botThreadId = res.telegram_bot_message_thread_id ? String(res.telegram_bot_message_thread_id) : ''
  s.timezone = res.timezone || 'Asia/Hong_Kong'
  s.execTimeout = res.sign_task_execution_timeout ?? ''
  s.accountCooldown = res.sign_task_account_cooldown ?? ''
  s.flowRetry = res.sign_task_flow_retry_attempts ?? ''
  s.historyMaxAge = res.sign_task_history_max_age_days ?? ''
  s.aiVisionTimeout = res.ai_vision_timeout ?? ''
  s.aiVisionRetry = res.ai_vision_retry_attempts ?? ''
  s.aiVisionReasoningEffort = res.ai_vision_reasoning_effort || ''
  s.autoBackupEnabled = res.auto_backup_enabled || false
  s.autoBackupInterval = res.auto_backup_interval_hours || 24
  s.autoBackupKeep = res.auto_backup_keep || 3
  s.webdavUrl = res.webdav_url || ''
  s.webdavUsername = res.webdav_username || ''
  s.webdavPassword = ''
  s.webdavRemoteDir = res.webdav_remote_dir || 'tg-signpulse-backups'
  const bt = res.backup_target
  s.backupTarget = bt === 'webdav' ? 'webdav' : 'auto'
  return {
    botTokenSet: !!res.telegram_bot_token_set,
    webdavPasswordSet: !!res.webdav_password_set,
    proxySet: !!res.global_proxy_set,
  }
}
