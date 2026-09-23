/**
 * 流接入票据 API。
 *
 * 浏览器 `EventSource` 与 `WebSocket` 都无法设置 Authorization 头。
 * 长效 JWT 放进查询串会随 URL 落入访问日志、反代日志与浏览器历史，
 * 因此改为：先用 Bearer JWT 换一张短期一次性票据，再用票据建流。
 */
import { request } from "./core";

/** 票据用途，与后端 `backend/services/stream_tickets.py` 的常量保持一致 */
export const STREAM_TICKET_PURPOSE = {
  /** Dashboard 签到历史 SSE */
  signHistorySse: "sign_history_sse",
  /** 任务运行日志 WebSocket */
  taskRunWs: "task_run_ws",
} as const

export type StreamTicketPurpose =
  (typeof STREAM_TICKET_PURPOSE)[keyof typeof STREAM_TICKET_PURPOSE]

export interface StreamTicketResponse {
  ticket: string
  purpose: StreamTicketPurpose
  /** 票据剩余有效秒数 */
  expires_in: number
}

/**
 * 签发流接入票据。
 *
 * @param purpose 用途，后端会校验建流时声明的用途与此一致
 * @param resource 关联资源（如 task_name），进一步限制票据只能用于该条流
 */
export const issueStreamTicket = (
  purpose: StreamTicketPurpose,
  resource = "",
) =>
  request<StreamTicketResponse>("/events/ticket", {
    method: "POST",
    body: JSON.stringify({ purpose, resource }),
  })
