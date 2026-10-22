import { getAuthToken, request } from './core'

export interface SemanticConfig {
  enabled: boolean
  drift_enabled: boolean
  mode: 'official' | 'custom'
  base_url: string
  model: string
  has_api_key: boolean
  api_key_masked: string
  timeout_seconds: number
  max_concurrency: number
  max_calls_per_run: number
  max_calls_per_minute: number
  retain_evidence: boolean
  generation: number
  monitor_keys_usage: {
    count: number
    capacity: number
    is_full: boolean
  }
}

export interface SemanticObservation {
  id: string
  scope: string
  run_id: string
  kind: string
  request_key: string
  observed_at: string
  model: string
  selected: string
  probabilities: Record<string, number>
  confidence: number
  accepted: boolean
  reason_code: string
  elapsed_ms: number
  input_tokens: number
  rule_result: string
  human_label?: string
}

export interface RuleSuggestion {
  id: string
  scope: string
  account_name: string
  task_name: string
  kind: string
  status: 'pending' | 'applied' | 'dismissed'
  created_at: number
  base_revision?: string
  patch: {
    op: string
    path: string
    old?: any
    value: any
  }
  confidence?: number
  reason?: string
  applied_at?: number
  applied_by?: string
}

export interface SemanticTestResult {
  success: boolean
  status: string
  http_status: number | null
  selected: string
  elapsed_ms: number
  reason_code: string
  error_message: string
}

export const getSemanticConfig = (token: string = getAuthToken()) =>
  request<SemanticConfig>('/semantic/config', {}, token)

export const updateSemanticConfig = (patch: Partial<SemanticConfig> & { api_key?: string; clear_api_key?: boolean }, token: string = getAuthToken()) =>
  request<SemanticConfig>('/semantic/config', {
    method: 'PATCH',
    body: JSON.stringify(patch),
  }, token)

export const testSemanticConnection = (body?: { api_key?: string; base_url?: string; model?: string; timeout_seconds?: number }, token: string = getAuthToken()) =>
  request<SemanticTestResult>('/semantic/test', {
    method: 'POST',
    body: JSON.stringify(body || {}),
  }, token)

export const listSemanticObservations = (params: { account_name?: string; task_name?: string; limit?: number }, token: string = getAuthToken()) => {
  const query = new URLSearchParams()
  if (params.account_name) query.set('account_name', params.account_name)
  if (params.task_name) query.set('task_name', params.task_name)
  if (params.limit) query.set('limit', String(params.limit))
  return request<{ total: number; items: SemanticObservation[] }>(`/semantic/observations?${query.toString()}`, {}, token)
}

export const labelSemanticObservation = (
  id: string,
  body: { account_name: string; task_name: string; label: string; reviewer_intent?: string },
  token: string = getAuthToken(),
) =>
  request<{ id: string; label: string }>(`/semantic/observations/${encodeURIComponent(id)}/label`, {
    method: 'PUT',
    body: JSON.stringify(body),
  }, token)

export const listRuleSuggestions = (params: { account_name?: string; task_name?: string; status?: string }, token: string = getAuthToken()) => {
  const query = new URLSearchParams()
  if (params.account_name) query.set('account_name', params.account_name)
  if (params.task_name) query.set('task_name', params.task_name)
  if (params.status) query.set('status', params.status)
  return request<RuleSuggestion[]>(`/semantic/suggestions?${query.toString()}`, {}, token)
}

export const applyRuleSuggestion = (id: string, body?: { account_name?: string; task_name?: string }, token: string = getAuthToken()) =>
  request<{ status: string; suggestion_id: string; task: any }>(`/semantic/suggestions/${encodeURIComponent(id)}/apply`, {
    method: 'POST',
    body: JSON.stringify(body || {}),
  }, token)

export const dismissRuleSuggestion = (id: string, body?: { account_name?: string; task_name?: string }, token: string = getAuthToken()) =>
  request<{ status: string; id: string }>(`/semantic/suggestions/${encodeURIComponent(id)}/dismiss`, {
    method: 'POST',
    body: JSON.stringify(body || {}),
  }, token)
