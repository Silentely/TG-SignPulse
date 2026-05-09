"use client";

import { useEffect, useState } from "react";
import { Lock, ShieldCheck, Spinner, User, WarningCircle } from "@phosphor-icons/react";
import {
  changePassword,
  changeUsername,
  disableTOTP,
  enableTOTP,
  fetchTOTPQRCode,
  getTOTPStatus,
  setupTOTP,
} from "../../../lib/api";
import { getToken } from "../../../lib/auth";
import { DashboardShell } from "../../../components/dashboard-shell";
import { ToastContainer, useToast } from "../../../components/ui/toast";
import { useLanguage } from "../../../context/LanguageContext";

export default function ProfilePage() {
  const { language, t } = useLanguage();
  const { toasts, addToast, removeToast } = useToast();
  const [token, setToken] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);
  const [userLoading, setUserLoading] = useState(false);
  const [passwordLoading, setPasswordLoading] = useState(false);
  const [totpLoading, setTotpLoading] = useState(false);
  const [totpEnabled, setTotpEnabled] = useState(false);
  const [showTotpSetup, setShowTotpSetup] = useState(false);
  const [totpSecret, setTotpSecret] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [totpQrUrl, setTotpQrUrl] = useState<string | null>(null);
  const [usernameForm, setUsernameForm] = useState({
    newUsername: "",
    password: "",
  });
  const [passwordForm, setPasswordForm] = useState({
    oldPassword: "",
    newPassword: "",
    confirmPassword: "",
  });

  const formatErrorMessage = (key: string, err?: any) => {
    const base = t(key);
    const code = err?.code;
    return code ? `${base} (${code})` : base;
  };

  useEffect(() => {
    const tokenStr = getToken();
    if (!tokenStr) {
      window.location.replace("/");
      return;
    }

    setToken(tokenStr);
    setChecking(false);
    void loadTOTPStatus(tokenStr);
  }, []);

  useEffect(() => {
    if (!token || !showTotpSetup) return;

    let cancelled = false;
    void (async () => {
      try {
        const qrUrl = await fetchTOTPQRCode(token);
        if (cancelled) {
          window.URL.revokeObjectURL(qrUrl);
          return;
        }
        setTotpQrUrl((prev) => {
          if (prev) window.URL.revokeObjectURL(prev);
          return qrUrl;
        });
      } catch {
        if (!cancelled) {
          setTotpQrUrl((prev) => {
            if (prev) window.URL.revokeObjectURL(prev);
            return null;
          });
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [showTotpSetup, token]);

  useEffect(() => {
    if (showTotpSetup) return;
    setTotpQrUrl((prev) => {
      if (prev) window.URL.revokeObjectURL(prev);
      return null;
    });
  }, [showTotpSetup]);

  useEffect(() => {
    return () => {
      if (totpQrUrl) {
        window.URL.revokeObjectURL(totpQrUrl);
      }
    };
  }, [totpQrUrl]);

  const loadTOTPStatus = async (tokenStr: string) => {
    try {
      const res = await getTOTPStatus(tokenStr);
      setTotpEnabled(res.enabled);
    } catch {
      setTotpEnabled(false);
    }
  };

  const handleChangeUsername = async () => {
    if (!token) return;
    if (!usernameForm.newUsername || !usernameForm.password) {
      addToast(t("form_incomplete"), "error");
      return;
    }

    try {
      setUserLoading(true);
      const res = await changeUsername(token, usernameForm.newUsername, usernameForm.password);
      addToast(t("username_changed"), "success");
      if (res.access_token) {
        localStorage.setItem("tg-signer-token", res.access_token);
        setToken(res.access_token);
      }
      setUsernameForm({ newUsername: "", password: "" });
    } catch (err: any) {
      addToast(formatErrorMessage("change_failed", err), "error");
    } finally {
      setUserLoading(false);
    }
  };

  const handleChangePassword = async () => {
    if (!token) return;
    if (!passwordForm.oldPassword || !passwordForm.newPassword) {
      addToast(t("form_incomplete"), "error");
      return;
    }
    if (passwordForm.newPassword !== passwordForm.confirmPassword) {
      addToast(t("password_mismatch"), "error");
      return;
    }

    try {
      setPasswordLoading(true);
      await changePassword(token, passwordForm.oldPassword, passwordForm.newPassword);
      addToast(t("password_changed"), "success");
      setPasswordForm({ oldPassword: "", newPassword: "", confirmPassword: "" });
    } catch (err: any) {
      addToast(formatErrorMessage("change_failed", err), "error");
    } finally {
      setPasswordLoading(false);
    }
  };

  const handleSetupTOTP = async () => {
    if (!token) return;
    try {
      setTotpLoading(true);
      const res = await setupTOTP(token);
      setTotpSecret(res.secret);
      setShowTotpSetup(true);
    } catch (err: any) {
      addToast(formatErrorMessage("setup_failed", err), "error");
    } finally {
      setTotpLoading(false);
    }
  };

  const handleEnableTOTP = async () => {
    if (!token) return;
    if (!totpCode) {
      addToast(t("login_code_required"), "error");
      return;
    }

    try {
      setTotpLoading(true);
      await enableTOTP(token, totpCode);
      addToast(t("two_factor_enabled"), "success");
      setTotpEnabled(true);
      setShowTotpSetup(false);
      setTotpCode("");
    } catch (err: any) {
      addToast(formatErrorMessage("enable_failed", err), "error");
    } finally {
      setTotpLoading(false);
    }
  };

  const handleDisableTOTP = async () => {
    if (!token) return;
    const code = prompt(t("two_factor_disable_prompt"));
    if (!code) return;

    try {
      setTotpLoading(true);
      await disableTOTP(token, code);
      addToast(t("two_factor_disabled"), "success");
      setTotpEnabled(false);
      setShowTotpSetup(false);
      setTotpSecret("");
      setTotpCode("");
    } catch (err: any) {
      addToast(formatErrorMessage("disable_failed", err), "error");
    } finally {
      setTotpLoading(false);
    }
  };

  if (!token || checking) {
    return null;
  }

  return (
    <>
      <DashboardShell
        title={language === "zh" ? "个人中心" : "Profile"}
        activeNav={null}
        contentClassName="mx-auto max-w-4xl"
      >
        <div className="space-y-6">
          <section className="glass-panel demo-surface-card">
            <div className="demo-surface-header">
              <div className="flex items-center gap-2">
                <ShieldCheck weight="fill" size={16} />
                <span>{language === "zh" ? "账户安全" : "Account Security"}</span>
              </div>
            </div>

            <div className="demo-surface-body grid gap-8 md:grid-cols-2">
              <div className="space-y-4">
                <h4 className="text-sm font-bold text-main">{language === "zh" ? "修改用户名" : "Change Username"}</h4>
                <div className="space-y-3">
                  <input
                    type="text"
                    placeholder={language === "zh" ? "新用户名" : "New username"}
                    value={usernameForm.newUsername}
                    onChange={(e) => setUsernameForm((prev) => ({ ...prev, newUsername: e.target.value }))}
                  />
                  <input
                    type="password"
                    placeholder={language === "zh" ? "当前密码" : "Current password"}
                    value={usernameForm.password}
                    onChange={(e) => setUsernameForm((prev) => ({ ...prev, password: e.target.value }))}
                  />
                </div>
                <button type="button" className="btn-secondary !w-full" onClick={handleChangeUsername} disabled={userLoading}>
                  {userLoading ? <Spinner className="animate-spin" size={16} /> : <User weight="bold" size={16} />}
                  <span>{language === "zh" ? "保存用户名" : "Save Username"}</span>
                </button>
              </div>

              <div className="space-y-4">
                <h4 className="text-sm font-bold text-main">{language === "zh" ? "修改密码" : "Change Password"}</h4>
                <div className="space-y-3">
                  <input
                    type="password"
                    placeholder={language === "zh" ? "旧密码" : "Old password"}
                    value={passwordForm.oldPassword}
                    onChange={(e) => setPasswordForm((prev) => ({ ...prev, oldPassword: e.target.value }))}
                  />
                  <div className="grid gap-3 md:grid-cols-2">
                    <input
                      type="password"
                      placeholder={language === "zh" ? "新密码" : "New password"}
                      value={passwordForm.newPassword}
                      onChange={(e) => setPasswordForm((prev) => ({ ...prev, newPassword: e.target.value }))}
                    />
                    <input
                      type="password"
                      placeholder={language === "zh" ? "确认新密码" : "Confirm new password"}
                      value={passwordForm.confirmPassword}
                      onChange={(e) => setPasswordForm((prev) => ({ ...prev, confirmPassword: e.target.value }))}
                    />
                  </div>
                </div>
                <button type="button" className="btn-secondary !w-full" onClick={handleChangePassword} disabled={passwordLoading}>
                  {passwordLoading ? <Spinner className="animate-spin" size={16} /> : <Lock weight="bold" size={16} />}
                  <span>{language === "zh" ? "更新密码" : "Update Password"}</span>
                </button>
              </div>
            </div>
          </section>

          <section className="glass-panel demo-surface-card">
            <div className="demo-surface-header">
              <div className="flex items-center gap-2">
                <ShieldCheck weight="fill" size={16} className="text-[#2AABEE]" />
                <span>{language === "zh" ? "两步验证 (2FA)" : "Two-Factor Authentication"}</span>
              </div>
            </div>

            <div className="demo-surface-body space-y-5">
              <div className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                <div>
                  <p className="text-sm text-main/55">
                    {language === "zh"
                      ? "绑定身份验证器应用，提升账户安全。"
                      : "Use an authenticator app to improve account security."}
                  </p>
                </div>

                {totpEnabled ? (
                  <button type="button" className="btn-secondary !w-auto" onClick={handleDisableTOTP} disabled={totpLoading}>
                    {totpLoading ? <Spinner className="animate-spin" size={16} /> : null}
                    <span>{language === "zh" ? "停用验证器" : "Disable Authenticator"}</span>
                  </button>
                ) : (
                  <button type="button" className="btn-secondary !w-auto" onClick={handleSetupTOTP} disabled={totpLoading}>
                    {totpLoading ? <Spinner className="animate-spin" size={16} /> : null}
                    <span>{language === "zh" ? "绑定验证器" : "Bind Authenticator"}</span>
                  </button>
                )}
              </div>

              {!totpEnabled && !showTotpSetup ? (
                <div className="demo-alert">
                  <WarningCircle weight="fill" size={16} />
                  <span>
                    {language === "zh"
                      ? "启用后，登录时除了密码外，还需要输入身份验证器生成的一次性验证码。"
                      : "When enabled, sign-in will require a one-time code from your authenticator app."}
                  </span>
                </div>
              ) : null}

              {showTotpSetup ? (
                <div className="demo-switch-card !items-start !rounded-xl">
                  <div className="w-full space-y-4">
                    <div className="flex flex-col gap-4 md:flex-row">
                      <div className="shrink-0 rounded-lg bg-white p-2">
                        {totpQrUrl ? (
                          <>
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img
                              src={totpQrUrl}
                              alt="TOTP QR"
                              className="h-28 w-28"
                            />
                          </>
                        ) : (
                          <div className="flex h-28 w-28 items-center justify-center text-main/35">
                            <Spinner className="animate-spin" size={20} />
                          </div>
                        )}
                      </div>

                      <div className="min-w-0 flex-1 space-y-3">
                        <div>
                          <div className="text-xs font-bold text-main">{language === "zh" ? "扫描二维码" : "Scan QR Code"}</div>
                          <div className="demo-form-note">
                            {language === "zh"
                              ? "使用 Google Authenticator 或其他验证器应用扫描。"
                              : "Scan it with Google Authenticator or another authenticator app."}
                          </div>
                        </div>
                        <div>
                          <div className="text-xs font-bold text-main">{language === "zh" ? "备用密钥" : "Backup Secret"}</div>
                          <input
                            readOnly
                            value={totpSecret}
                            className="mt-2 font-mono text-sm"
                            onClick={(e) => (e.target as HTMLInputElement).select()}
                          />
                        </div>
                      </div>
                    </div>

                    <div className="grid gap-3 md:grid-cols-[1fr_auto]">
                      <input
                        type="text"
                        placeholder={language === "zh" ? "输入 6 位验证码" : "Enter 6-digit code"}
                        value={totpCode}
                        onChange={(e) => setTotpCode(e.target.value)}
                      />
                      <button type="button" className="btn-gradient !w-auto" onClick={handleEnableTOTP} disabled={totpLoading}>
                        {totpLoading ? <Spinner className="animate-spin" size={16} /> : null}
                        <span>{language === "zh" ? "验证并启用" : "Verify and Enable"}</span>
                      </button>
                    </div>
                  </div>
                </div>
              ) : null}
            </div>
          </section>
        </div>
      </DashboardShell>

      <ToastContainer toasts={toasts} removeToast={removeToast} />
    </>
  );
}
