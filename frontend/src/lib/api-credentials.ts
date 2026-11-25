/**
 * 账号级 Telegram API 凭据的前端校验。
 *
 * Telegram 的 api_id 与 api_hash 是严格绑定的签名对，单边填写无法与全局配置
 * 拼接使用，因此这里统一 fail-closed：只要最终会形成单边提交就阻断。
 */

export type ApiCredentialField = 'api_id' | 'api_hash'
export type ApiCredentialError = 'pair' | 'id'

export interface ApiCredentialValidation {
  valid: boolean
  /** 需要高亮的缺失/非法字段 */
  missing: ApiCredentialField | null
  error: ApiCredentialError | null
}

export interface ValidateApiCredentialsOptions {
  /**
   * 编辑已有账号时为 true：Hash 留空表示保留已保存的加密 Hash，
   * 只要已填写 api_id 就仍是完整凭据对。
   */
  canKeepExistingHash?: boolean
}

export interface KeepExistingHashOptions {
  /** 编辑/重登已有账号 */
  isExistingAccount: boolean
  /** 账号已保存专属 Hash */
  hasExistingHash: boolean
  /** 表单当前的 API ID */
  apiId: string | number | null | undefined
  /** 已保存 Hash 所属的 API ID */
  savedApiId: string | number | null | undefined
}

/**
 * 空 Hash 能否沿用已保存值。
 *
 * 只有 API ID 与已保存值一致时才允许：改了 ID 再留空 Hash 会拼出
 * 新的混合凭据对，必须让用户重新填写 Hash。
 *
 * 已保存记录缺少 API ID（只有 Hash 的遗留数据）时一律不放行：无法证明
 * 该 Hash 与当前 ID 同源，按 fail-closed 要求重新填写完整凭据对。
 */
export function canKeepExistingHash(options: KeepExistingHashOptions): boolean {
  if (!options.isExistingAccount || !options.hasExistingHash) return false
  const savedApiId = String(options.savedApiId ?? '').trim()
  if (!savedApiId) return false
  return String(options.apiId ?? '').trim() === savedApiId
}

export function validateAccountApiCredentials(
  apiId: string | number | null | undefined,
  apiHash: string | null | undefined,
  options: ValidateApiCredentialsOptions = {},
): ApiCredentialValidation {
  const id = String(apiId ?? '').trim()
  const hash = String(apiHash ?? '').trim()

  if (id && !/^[1-9]\d*$/.test(id)) {
    return { valid: false, missing: 'api_id', error: 'id' }
  }

  if (id && !hash) {
    if (options.canKeepExistingHash) {
      return { valid: true, missing: null, error: null }
    }
    return { valid: false, missing: 'api_hash', error: 'pair' }
  }

  if (!id && hash) {
    return { valid: false, missing: 'api_id', error: 'pair' }
  }

  return { valid: true, missing: null, error: null }
}
