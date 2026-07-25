/**
 * 认证 API：登录、获取当前用户、重置 TOTP。
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

export const getMe = (token: string) =>
  request("/auth/me", {}, token);

export const resetTOTP = (payload: { username: string; password: string }) =>
  request<{ success: boolean; message: string }>("/auth/reset-totp", {
    method: "POST",
    body: JSON.stringify(payload),
  });
