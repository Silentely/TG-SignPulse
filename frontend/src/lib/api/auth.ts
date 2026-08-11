/**
 * 认证 API：登录。
 */
import type { TokenResponse } from "../types";
import { request } from "./core";

export const login = (payload: {
  username: string;
  password: string;
  totp_code?: string;
}) =>
  request<TokenResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
