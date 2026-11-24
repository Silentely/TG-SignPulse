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

export function validateAccountApiCredentials(
  apiId: string | number | null | undefined,
  apiHash: string | null | undefined,
  options: ValidateApiCredentialsOptions = {},
): ApiCredentialValidation {
  const id = String(apiId ?? '').trim()
  const hash = String(apiHash ?? '').trim()

  if (id && !hash) {
    if (options.canKeepExistingHash) {
      return { valid: true, missing: null, error: null }
    }
    return { valid: false, missing: 'api_hash', error: 'pair' }
  }

  if (!id && hash) {
    return { valid: false, missing: 'api_id', error: 'pair' }
  }

  if (id && !/^[1-9]\d*$/.test(id)) {
    return { valid: false, missing: 'api_id', error: 'id' }
  }

  return { valid: true, missing: null, error: null }
}
