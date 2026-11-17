/**
 * 认证 API：登录。
 */
import type { LoginResponse } from "../types";
import { request } from "./core";

export const login = (payload: {
  username: string;
  password: string;
  totp_code?: string;
}) =>
  request<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
