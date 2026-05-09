"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { getToken } from "../../../lib/auth";
import {
  listAccounts,
  startAccountLogin,
  startQrLogin,
  getQrLoginStatus,
  cancelQrLogin,
  submitQrPassword,
  updateAccount,
  verifyAccountLogin,
  deleteAccount,
  getAccountLogs,
  clearAccountLogs,
  listSignTasks,
  AccountInfo,
  AccountStatusItem,
  AccountLog,
  SignTask,
} from "../../../lib/api";
import {
  Lightning,
  Plus,
  ListDashes,
  Spinner,
  PencilSimple,
  PaperPlaneRight,
  Trash
} from "@phosphor-icons/react";
import { DashboardShell } from "../../../components/dashboard-shell";
import { DialogShell } from "../../../components/dialog-shell";
import { ToastContainer, useToast } from "../../../components/ui/toast";
import { useLanguage } from "../../../context/LanguageContext";

const EMPTY_LOGIN_DATA = {
  account_name: "",
  phone_number: "",
  proxy: "",
  phone_code: "",
  password: "",
  phone_code_hash: "",
};

export default function Dashboard() {
  const router = useRouter();
  const { t, language } = useLanguage();
  const { toasts, addToast, removeToast } = useToast();
  const [token, setLocalToken] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);
  const [tasks, setTasks] = useState<SignTask[]>([]);
  const [loading, setLoading] = useState(false);

  // 鏃ュ織寮圭獥
  const [showLogsDialog, setShowLogsDialog] = useState(false);
  const [logsAccountName, setLogsAccountName] = useState("");
  const [accountLogs, setAccountLogs] = useState<AccountLog[]>([]);
  const [logsLoading, setLogsLoading] = useState(false);

  // 娣诲姞璐﹀彿瀵硅瘽妗?
  const [showAddDialog, setShowAddDialog] = useState(false);
  const [loginData, setLoginData] = useState({ ...EMPTY_LOGIN_DATA });
  const [reloginAccountName, setReloginAccountName] = useState<string | null>(null);
  const [loginMode, setLoginMode] = useState<"phone" | "qr">("phone");
  const [qrLogin, setQrLogin] = useState<{
    login_id: string;
    qr_uri: string;
    qr_image?: string | null;
    expires_at: string;
  } | null>(null);
  type QrPhase = "idle" | "loading" | "ready" | "scanning" | "password" | "success" | "expired" | "error";
  const [qrStatus, setQrStatus] = useState<
    "waiting_scan" | "scanned_wait_confirm" | "password_required" | "success" | "expired" | "failed"
  >("waiting_scan");
  const [qrPhase, setQrPhase] = useState<QrPhase>("idle");
  const [qrMessage, setQrMessage] = useState<string>("");
  const [qrCountdown, setQrCountdown] = useState<number>(0);
  const [qrLoading, setQrLoading] = useState(false);
  const [qrPassword, setQrPassword] = useState("");
  const [qrPasswordLoading, setQrPasswordLoading] = useState(false);
  const qrPasswordRef = useRef("");
  const qrPasswordLoadingRef = useRef(false);

  const qrPollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const qrCountdownTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const qrPollDelayRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const qrActiveLoginIdRef = useRef<string | null>(null);
  const qrPollSeqRef = useRef(0);
  const qrToastShownRef = useRef<Record<string, { expired?: boolean; error?: boolean }>>({});
  const qrPollingActiveRef = useRef(false);
  const qrRestartingRef = useRef(false);
  const qrAutoRefreshRef = useRef(0);

  useEffect(() => {
    qrPasswordRef.current = qrPassword;
  }, [qrPassword]);

  useEffect(() => {
    qrPasswordLoadingRef.current = qrPasswordLoading;
  }, [qrPasswordLoading]);

  // 缂栬緫璐﹀彿瀵硅瘽妗?
  const [showEditDialog, setShowEditDialog] = useState(false);
  const [editData, setEditData] = useState({
    source_account_name: "",
    account_name: "",
    remark: "",
    proxy: "",
  });

  const normalizeAccountName = useCallback((name: string) => name.trim(), []);

  const sanitizeAccountName = (name: string) =>
    name.replace(/[^A-Za-z0-9\u4e00-\u9fff]/g, "");

  const isDuplicateAccountName = useCallback((name: string, allowedSameName?: string | null) => {
    const normalized = normalizeAccountName(name).toLowerCase();
    if (!normalized) return false;
    const allow = normalizeAccountName(allowedSameName || "").toLowerCase();
    return accounts.some((acc) => {
      const current = acc.name.toLowerCase();
      if (allow && current === allow && normalized === allow) {
        return false;
      }
      return current === normalized;
    });
  }, [accounts, normalizeAccountName]);

  const [checking, setChecking] = useState(true);
  const [accountStatusMap, setAccountStatusMap] = useState<Record<string, AccountStatusItem>>({});

  const addToastRef = useRef(addToast);
  const tRef = useRef(t);

  useEffect(() => {
    addToastRef.current = addToast;
  }, [addToast]);

  useEffect(() => {
    tRef.current = t;
  }, [t]);

  const formatErrorMessage = useCallback((key: string, err?: any) => {
    const base = tRef.current ? tRef.current(key) : key;
    const code = err?.code;
    return code ? `${base} (${code})` : base;
  }, []);

  const loadData = useCallback(async (tokenStr: string) => {
    try {
      setLoading(true);
      const [accountsData, tasksData] = await Promise.all([
        listAccounts(tokenStr),
        listSignTasks(tokenStr),
      ]);
      setAccounts(accountsData.accounts);
      setAccountStatusMap(() => {
        const next: Record<string, AccountStatusItem> = {};
        for (const acc of accountsData.accounts) {
          const rawStatus = acc.status || "connected";
          const needsRelogin = Boolean(acc.needs_relogin) || rawStatus === "invalid" || rawStatus === "not_found";
          const status = needsRelogin ? "invalid" : "connected";
          next[acc.name] = {
            account_name: acc.name,
            ok: !needsRelogin,
            status,
            message: acc.status_message || "",
            code: acc.status_code || undefined,
            checked_at: acc.status_checked_at || undefined,
            needs_relogin: needsRelogin,
          };
        }
        return next;
      });
      setTasks(tasksData);
    } catch (err: any) {
      addToastRef.current(formatErrorMessage("load_failed", err), "error");
    } finally {
      setLoading(false);
    }
  }, [formatErrorMessage]);

  useEffect(() => {
    const tokenStr = getToken();
    if (!tokenStr) {
      window.location.replace("/");
      return;
    }
    setLocalToken(tokenStr);
    setChecking(false);
    loadData(tokenStr);
  }, [loadData]);

  const getAccountTaskCount = (accountName: string) => {
    return tasks.filter(task => {
      const names = task.account_names && task.account_names.length > 0
        ? task.account_names
        : [task.account_name];
      return names.includes(accountName);
    }).length;
  };

  const openAddDialog = () => {
    setReloginAccountName(null);
    setLoginMode("phone");
    setLoginData({ ...EMPTY_LOGIN_DATA });
    setShowAddDialog(true);
  };

  const handleStartLogin = async () => {
    if (!token) return;
    const trimmedAccountName = normalizeAccountName(loginData.account_name);
    if (!trimmedAccountName || !loginData.phone_number) {
      addToast(t("account_name_phone_required"), "error");
      return;
    }
    if (isDuplicateAccountName(trimmedAccountName, reloginAccountName)) {
      addToast(t("account_name_duplicate"), "error");
      return;
    }
    try {
      setLoading(true);
      const res = await startAccountLogin(token, {
        phone_number: loginData.phone_number,
        account_name: trimmedAccountName,
        proxy: loginData.proxy || undefined,
      });
      setLoginData({ ...loginData, account_name: trimmedAccountName, phone_code_hash: res.phone_code_hash });
      addToast(t("code_sent"), "success");
    } catch (err: any) {
      addToast(formatErrorMessage("send_code_failed", err), "error");
    } finally {
      setLoading(false);
    }
  };

  const handleVerifyLogin = useCallback(async () => {
    if (!token) return;
    if (!loginData.phone_code) {
      addToast(t("login_code_required"), "error");
      return;
    }
    const trimmedAccountName = normalizeAccountName(loginData.account_name);
    if (!trimmedAccountName) {
      addToast(t("account_name_required"), "error");
      return;
    }
    if (isDuplicateAccountName(trimmedAccountName, reloginAccountName)) {
      addToast(t("account_name_duplicate"), "error");
      return;
    }
    try {
      setLoading(true);
      await verifyAccountLogin(token, {
        account_name: trimmedAccountName,
        phone_number: loginData.phone_number,
        phone_code: loginData.phone_code,
        phone_code_hash: loginData.phone_code_hash,
        password: loginData.password || undefined,
        proxy: loginData.proxy || undefined,
      });
      addToast(t("login_success"), "success");
      setAccountStatusMap((prev) => ({
        ...prev,
        [trimmedAccountName]: {
          account_name: trimmedAccountName,
          ok: true,
          status: "connected",
          message: "",
          code: "OK",
          checked_at: new Date().toISOString(),
          needs_relogin: false,
        },
      }));
      setReloginAccountName(null);
      setLoginData({ ...EMPTY_LOGIN_DATA });
      setShowAddDialog(false);
      loadData(token);
    } catch (err: any) {
      addToast(formatErrorMessage("verify_failed", err), "error");
    } finally {
      setLoading(false);
    }
  }, [
    token,
    loginData.account_name,
    loginData.phone_number,
    loginData.phone_code,
    loginData.phone_code_hash,
    loginData.password,
    loginData.proxy,
    addToast,
    formatErrorMessage,
    isDuplicateAccountName,
    loadData,
    normalizeAccountName,
    reloginAccountName,
    t,
  ]);

  const handleDeleteAccount = async (name: string) => {
    if (!token) return;
    if (!confirm(t("confirm_delete_account").replace("{name}", name))) return;
    try {
      setLoading(true);
      await deleteAccount(token, name);
      addToast(t("account_deleted"), "success");
      loadData(token);
    } catch (err: any) {
      addToast(formatErrorMessage("delete_failed", err), "error");
    } finally {
      setLoading(false);
    }
  };

  const handleEditAccount = (acc: AccountInfo) => {
    setEditData({
      source_account_name: acc.name,
      account_name: acc.name,
      remark: acc.remark || "",
      proxy: acc.proxy || "",
    });
    setShowEditDialog(true);
  };

  const handleSaveEdit = async () => {
    if (!token) return;
    const sourceAccountName = normalizeAccountName(editData.source_account_name);
    const nextAccountName = normalizeAccountName(editData.account_name);
    if (!sourceAccountName || !nextAccountName) {
      addToast(t("account_name_required"), "error");
      return;
    }
    if (isDuplicateAccountName(nextAccountName, sourceAccountName)) {
      addToast(t("account_name_duplicate"), "error");
      return;
    }
    try {
      setLoading(true);
      await updateAccount(token, sourceAccountName, {
        new_account_name: nextAccountName,
        remark: editData.remark || "",
        proxy: editData.proxy || "",
      });
      addToast(t("save_changes"), "success");
      setShowEditDialog(false);
      loadData(token);
    } catch (err: any) {
      addToast(formatErrorMessage("save_failed", err), "error");
    } finally {
      setLoading(false);
    }
  };

  const debugQr = useCallback((payload: Record<string, any>) => {
    if (process.env.NODE_ENV !== "production") {
      // eslint-disable-next-line no-console
      console.debug("[qr-login]", payload);
    }
  }, []);

  const clearQrPollingTimers = useCallback(() => {
    if (qrPollTimerRef.current) {
      clearInterval(qrPollTimerRef.current);
      qrPollTimerRef.current = null;
    }
    if (qrPollDelayRef.current) {
      clearTimeout(qrPollDelayRef.current);
      qrPollDelayRef.current = null;
    }
    qrPollingActiveRef.current = false;
  }, []);

  const clearQrCountdownTimer = useCallback(() => {
    if (qrCountdownTimerRef.current) {
      clearInterval(qrCountdownTimerRef.current);
      qrCountdownTimerRef.current = null;
    }
  }, []);

  const clearQrTimers = useCallback(() => {
    clearQrPollingTimers();
    clearQrCountdownTimer();
  }, [clearQrPollingTimers, clearQrCountdownTimer]);

  const setQrPhaseSafe = useCallback((next: QrPhase, reason: string, extra?: Record<string, any>) => {
    setQrPhase((prev) => {
      if (prev !== next) {
        debugQr({
          login_id: qrActiveLoginIdRef.current,
          prev,
          next,
          reason,
          ...extra,
        });
      }
      return next;
    });
  }, [debugQr]);

  const markToastShown = useCallback((loginId: string, kind: "expired" | "error") => {
    if (!loginId) return;
    if (!qrToastShownRef.current[loginId]) {
      qrToastShownRef.current[loginId] = {};
    }
    qrToastShownRef.current[loginId][kind] = true;
  }, []);

  const hasToastShown = useCallback((loginId: string, kind: "expired" | "error") => {
    if (!loginId) return false;
    return Boolean(qrToastShownRef.current[loginId]?.[kind]);
  }, []);

  const resetQrState = useCallback(() => {
    clearQrTimers();
    qrActiveLoginIdRef.current = null;
    qrRestartingRef.current = false;
    qrAutoRefreshRef.current = 0;
    setQrLogin(null);
    setQrStatus("waiting_scan");
    setQrPhase("idle");
    setQrMessage("");
    setQrCountdown(0);
    setQrLoading(false);
    setQrPassword("");
    setQrPasswordLoading(false);
  }, [clearQrTimers]);

  const openReloginDialog = useCallback((acc: AccountInfo, showToast: boolean = true) => {
    resetQrState();
    setReloginAccountName(acc.name);
    setLoginMode("phone");
    setLoginData({
      ...EMPTY_LOGIN_DATA,
      account_name: acc.name,
      proxy: acc.proxy || "",
    });
    setShowAddDialog(true);
    if (showToast) {
      addToast(t("account_relogin_required"), "error");
    }
  }, [addToast, resetQrState, t]);

  const handleAccountCardClick = useCallback((acc: AccountInfo) => {
    const statusInfo = accountStatusMap[acc.name];
    const needsRelogin = Boolean(statusInfo?.needs_relogin || acc.needs_relogin);
    const status = statusInfo?.status || acc.status;
    if (needsRelogin || status === "invalid") {
      openReloginDialog(acc);
      return;
    }
    router.push(`/dashboard/sign-tasks?account=${encodeURIComponent(acc.name)}`);
  }, [accountStatusMap, openReloginDialog, router]);

  const performQrLoginStart = useCallback(async (options?: { autoRefresh?: boolean; silent?: boolean; reason?: string }) => {
    if (!token) return null;
    const trimmedAccountName = normalizeAccountName(loginData.account_name);
    if (!trimmedAccountName) {
      if (!options?.silent) {
        addToast(t("account_name_required"), "error");
      }
      return null;
    }
    if (isDuplicateAccountName(trimmedAccountName, reloginAccountName)) {
      if (!options?.silent) {
        addToast(t("account_name_duplicate"), "error");
      }
      return null;
    }
    try {
      if (options?.autoRefresh) {
        qrRestartingRef.current = true;
      }
      clearQrTimers();
      setQrLoading(true);
      setQrPhaseSafe("loading", options?.reason ?? "start");
      const res = await startQrLogin(token, {
        account_name: trimmedAccountName,
        proxy: loginData.proxy || undefined,
      });
      setLoginData((prev) => ({ ...prev, account_name: trimmedAccountName }));
      setQrLogin(res);
      qrActiveLoginIdRef.current = res.login_id;
      qrToastShownRef.current[res.login_id] = {};
      setQrStatus("waiting_scan");
      setQrPhaseSafe("ready", "qr_ready", { expires_at: res.expires_at });
      setQrMessage("");
      return res;
    } catch (err: any) {
      setQrPhaseSafe("error", "start_failed");
      if (!options?.silent) {
        addToast(formatErrorMessage("qr_create_failed", err), "error");
      }
      return null;
    } finally {
      setQrLoading(false);
      qrRestartingRef.current = false;
    }
  }, [
    token,
    loginData.account_name,
    loginData.proxy,
    addToast,
    clearQrTimers,
    formatErrorMessage,
    isDuplicateAccountName,
    normalizeAccountName,
    reloginAccountName,
    setQrPhaseSafe,
    t,
  ]);

  const handleSubmitQrPassword = useCallback(async (passwordOverride?: string) => {
    if (!token || !qrLogin?.login_id) return;
    const passwordValue = passwordOverride ?? qrPasswordRef.current;
    if (!passwordValue) {
      const msg = t("qr_password_missing");
      addToast(msg, "error");
      setQrMessage(msg);
      return;
    }
    try {
      setQrPasswordLoading(true);
      await submitQrPassword(token, {
        login_id: qrLogin.login_id,
        password: passwordValue,
      });
      addToast(t("login_success"), "success");
      const doneAccount = normalizeAccountName(loginData.account_name);
      if (doneAccount) {
        setAccountStatusMap((prev) => ({
          ...prev,
          [doneAccount]: {
            account_name: doneAccount,
            ok: true,
            status: "connected",
            message: "",
            code: "OK",
            checked_at: new Date().toISOString(),
            needs_relogin: false,
          },
        }));
      }
      setReloginAccountName(null);
      setLoginData({ ...EMPTY_LOGIN_DATA });
      resetQrState();
      setShowAddDialog(false);
      loadData(token);
    } catch (err: any) {
      const errMsg = err?.message ? String(err.message) : "";
      const fallback = formatErrorMessage("qr_login_failed", err);
      let message = errMsg || fallback;
      const lowerMsg = errMsg.toLowerCase();
      if (errMsg.includes("鐎靛棛鐖滈柨娆掝嚖") || errMsg.includes("娑撱倖顒炴宀冪槈") || lowerMsg.includes("2fa")) {
        message = t("qr_password_invalid");
      }
      addToast(message, "error");
      if (message === t("qr_password_invalid")) {
        resetQrState();
        return;
      }
      setQrMessage(message);
    } finally {
      setQrPasswordLoading(false);
    }
  }, [
    token,
    qrLogin?.login_id,
    addToast,
    resetQrState,
    loadData,
    t,
    formatErrorMessage,
    loginData.account_name,
    normalizeAccountName,
  ]);

  const startQrPolling = useCallback((loginId: string, reason: string = "effect") => {
    if (!token || !loginId) return;
    if (loginMode !== "qr" || !showAddDialog) return;
    if (qrPollingActiveRef.current && qrActiveLoginIdRef.current === loginId) {
      debugQr({ login_id: loginId, poll: "skip", reason });
      return;
    }

    clearQrPollingTimers();
    qrActiveLoginIdRef.current = loginId;
    qrPollingActiveRef.current = true;
    qrPollSeqRef.current += 1;
    const seq = qrPollSeqRef.current;
    let stopped = false;

    const stopPolling = () => {
      if (stopped) return;
      stopped = true;
      clearQrPollingTimers();
    };

    const shouldAutoRefresh = () => {
      const now = Date.now();
      if (now - qrAutoRefreshRef.current < 1200) {
        return false;
      }
      qrAutoRefreshRef.current = now;
      return true;
    };

    const poll = async () => {
      try {
        if (qrRestartingRef.current) return;
        const res = await getQrLoginStatus(token, loginId);
        if (stopped) return;
        if (qrActiveLoginIdRef.current !== loginId) return;
        if (qrPollSeqRef.current !== seq) return;

        const status = res.status as "waiting_scan" | "scanned_wait_confirm" | "password_required" | "success" | "expired" | "failed";
        debugQr({ login_id: loginId, pollResult: status, message: res.message || "" });
        setQrStatus(status);
        if (status !== "password_required") {
          setQrMessage("");
        }
        if (res.expires_at) {
          setQrLogin((prev) => (prev ? { ...prev, expires_at: res.expires_at } : prev));
        }

        if (status === "success") {
          setQrPhaseSafe("success", "poll_success", { status });
          addToast(t("login_success"), "success");
          const doneAccount = normalizeAccountName(loginData.account_name);
          if (doneAccount) {
            setAccountStatusMap((prev) => ({
              ...prev,
              [doneAccount]: {
                account_name: doneAccount,
                ok: true,
                status: "connected",
                message: "",
                code: "OK",
                checked_at: new Date().toISOString(),
                needs_relogin: false,
              },
            }));
          }
          setReloginAccountName(null);
          setLoginData({ ...EMPTY_LOGIN_DATA });
          stopPolling();
          resetQrState();
          setShowAddDialog(false);
          loadData(token);
          return;
        }

        if (status === "password_required") {
          setQrPhaseSafe("password", "poll_password_required", { status });
          stopPolling();
          setQrMessage(t("qr_password_required"));
          return;
        }

        if (status === "scanned_wait_confirm") {
          setQrPhaseSafe("scanning", "poll_scanned", { status });
          return;
        }

        if (status === "waiting_scan") {
          setQrPhaseSafe("ready", "poll_waiting", { status });
          return;
        }

        if (status === "expired") {
          stopPolling();
          setQrPhaseSafe("loading", "auto_refresh", { status });
          if (!shouldAutoRefresh()) {
            return;
          }
          const refreshed = await performQrLoginStart({
            autoRefresh: true,
            silent: true,
            reason: "auto_refresh",
          });
          if (refreshed?.login_id) {
            startQrPolling(refreshed.login_id, "auto_refresh");
            return;
          }
          setQrPhaseSafe("expired", "auto_refresh_failed", { status });
          if (!hasToastShown(loginId, "expired")) {
            addToast(t("qr_expired_not_found"), "error");
            markToastShown(loginId, "expired");
          }
          return;
        }

        if (status === "failed") {
          setQrPhaseSafe("error", "poll_terminal", { status });
          stopPolling();
          if (!hasToastShown(loginId, "error")) {
            addToast(t("qr_login_failed"), "error");
            markToastShown(loginId, "error");
          }
        }
      } catch (err: any) {
        if (stopped) return;
        if (qrActiveLoginIdRef.current !== loginId) return;
        if (qrPollSeqRef.current !== seq) return;
        debugQr({ login_id: loginId, pollError: err?.message || String(err) });
        if (!hasToastShown(loginId, "error")) {
          addToast(formatErrorMessage("qr_status_failed", err), "error");
          markToastShown(loginId, "error");
        }
      }
    };

    qrPollDelayRef.current = setTimeout(() => {
      poll();
      qrPollTimerRef.current = setInterval(poll, 1500);
    }, 0);

    return stopPolling;
  }, [
    token,
    loginMode,
    showAddDialog,
    addToast,
    clearQrPollingTimers,
    debugQr,
    formatErrorMessage,
    hasToastShown,
    loadData,
    markToastShown,
    loginData.account_name,
    normalizeAccountName,
    performQrLoginStart,
    resetQrState,
    setQrPhaseSafe,
    t,
  ]);

  const handleStartQrLogin = async () => {
    const res = await performQrLoginStart();
    if (res?.login_id) {
      startQrPolling(res.login_id, "start_success");
    }
  };

  const handleCancelQrLogin = async () => {
    if (!token || !qrLogin?.login_id) {
      resetQrState();
      return;
    }
    try {
      setQrLoading(true);
      await cancelQrLogin(token, qrLogin.login_id);
    } catch (err: any) {
      addToast(formatErrorMessage("cancel_failed", err), "error");
    } finally {
      setQrLoading(false);
      resetQrState();
    }
  };


  // 鎵嬪姩鎻愪氦 2FA锛堥伩鍏嶈嚜鍔ㄩ噸璇曞鑷撮噸澶嶈姹傦級

  const handleCloseAddDialog = () => {
    if (qrLogin?.login_id) {
      handleCancelQrLogin();
    }
    setReloginAccountName(null);
    setLoginData({ ...EMPTY_LOGIN_DATA });
    setLoginMode("phone");
    setShowAddDialog(false);
  };

  const handleShowLogs = async (name: string) => {
    if (!token) return;
    setLogsAccountName(name);
    setShowLogsDialog(true);
    setLogsLoading(true);
    try {
      const logs = await getAccountLogs(token, name, 100);
      setAccountLogs(logs);
    } catch (err: any) {
      addToast(formatErrorMessage("logs_fetch_failed", err), "error");
    } finally {
      setLogsLoading(false);
    }
  };

  const handleClearLogs = async () => {
    if (!token || !logsAccountName) return;
    if (!confirm(t("clear_logs_confirm").replace("{name}", logsAccountName))) return;
    try {
      setLoading(true);
      await clearAccountLogs(token, logsAccountName);
      addToast(t("clear_logs_success"), "success");
      setLogsLoading(true);
      const logs = await getAccountLogs(token, logsAccountName, 100);
      setAccountLogs(logs);
    } catch (err: any) {
      addToast(formatErrorMessage("clear_logs_failed", err), "error");
    } finally {
      setLogsLoading(false);
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!qrLogin?.expires_at || !qrActiveLoginIdRef.current) {
      setQrCountdown(0);
      clearQrTimers();
      return;
    }
    if (!(qrPhase === "ready" || qrPhase === "scanning")) {
      setQrCountdown(0);
      if (qrCountdownTimerRef.current) {
        clearInterval(qrCountdownTimerRef.current);
        qrCountdownTimerRef.current = null;
      }
      return;
    }
    const update = () => {
      const expires = new Date(qrLogin.expires_at).getTime();
      const diff = Math.max(0, Math.floor((expires - Date.now()) / 1000));
      setQrCountdown(diff);
    };
    update();
    if (qrCountdownTimerRef.current) {
      clearInterval(qrCountdownTimerRef.current);
    }
    qrCountdownTimerRef.current = setInterval(update, 1000);
    return () => {
      if (qrCountdownTimerRef.current) {
        clearInterval(qrCountdownTimerRef.current);
        qrCountdownTimerRef.current = null;
      }
    };
  }, [qrLogin?.expires_at, qrPhase, clearQrTimers]);

  useEffect(() => {
    if (!token || !qrLogin?.login_id || loginMode !== "qr" || !showAddDialog) return;
    if (qrPhase === "success" || qrPhase === "expired" || qrPhase === "error" || qrPhase === "password") return;
    if (qrRestartingRef.current) return;
    const stop = startQrPolling(qrLogin.login_id, "effect");
    return () => {
      if (stop) stop();
    };
  }, [token, qrLogin?.login_id, loginMode, showAddDialog, qrPhase, startQrPolling]);

  if (!token || checking) {
    return null;
  }

  const activeAccountCount = accounts.filter((acc) => {
    const statusInfo = accountStatusMap[acc.name];
    const rawStatus = statusInfo?.status || acc.status || "connected";
    const needsRelogin = Boolean(statusInfo?.needs_relogin || acc.needs_relogin);
    return !needsRelogin && rawStatus !== "invalid" && rawStatus !== "not_found";
  }).length;
  const invalidAccountCount = Math.max(accounts.length - activeAccountCount, 0);
  void activeAccountCount;
  void invalidAccountCount;

  return (
    <>
      <DashboardShell
        title={language === "zh" ? "账号管理" : "Accounts"}
        activeNav="accounts"
      >
        <div className="space-y-6">
        {loading && accounts.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-main/30">
            <Spinner className="animate-spin mb-4" size={32} />
            <p>{t("loading")}</p>
          </div>
        ) : accounts.length === 0 ? (
          <div className="glass-panel demo-simple-empty">{language === "zh" ? "暂无账号" : "No accounts"}</div>
        ) : (
          <div className="card-grid">
            {accounts.map((acc) => {
              const initial = acc.name.charAt(0).toUpperCase();
              const statusInfo = accountStatusMap[acc.name];
              const rawStatus = statusInfo?.status || acc.status || "connected";
              const needsRelogin = Boolean(statusInfo?.needs_relogin || acc.needs_relogin);
              const isInvalid = needsRelogin || rawStatus === "invalid" || rawStatus === "not_found";
              const statusKey = isInvalid ? "account_status_invalid" : "connected";
              return (
                <div
                  key={acc.name}
                  className={`glass-panel card group cursor-pointer ${isInvalid ? "border-rose-200 bg-rose-50/40" : ""}`}
                  onClick={() => handleAccountCardClick(acc)}
                >
                  <div className={`absolute right-5 top-5 h-3 w-3 rounded-full ${isInvalid ? "bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.35)]" : "bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.35)]"}`} />
                  <div className="flex items-start gap-5">
                    <div className={`account-avatar ${isInvalid ? "!bg-slate-200 !text-slate-400" : ""}`}>{initial}</div>
                    <div className="min-w-0 pt-1">
                      <div className={`truncate text-[16px] font-bold ${isInvalid ? "text-main/70 line-through decoration-1" : "text-main"}`}>{acc.name}</div>
                      <div className={`mt-2 truncate text-[15px] ${isInvalid ? "text-rose-400" : "font-mono text-main/72"}`}>
                        {isInvalid ? (statusInfo?.message || t(statusKey)) : (acc.remark || t(statusKey))}
                      </div>
                    </div>
                  </div>

                  <div className="flex-1"></div>

                  <div className="space-y-4">
                    {isInvalid ? (
                      <button
                        type="button"
                        className="w-full rounded-xl border border-rose-200 bg-rose-50 py-3 text-sm font-medium text-rose-500 transition-colors hover:bg-rose-100"
                        onClick={(e) => {
                          e.stopPropagation();
                          openReloginDialog(acc, false);
                        }}
                      >
                        {language === "zh" ? "重新登录" : "Relogin"}
                      </button>
                    ) : null}

                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                      <button
                        type="button"
                        className="inline-flex h-10 items-center justify-center gap-1.5 whitespace-nowrap rounded-xl border border-slate-200 bg-white px-3 text-xs font-medium text-slate-600 shadow-sm transition-colors hover:border-[#2AABEE]/35 hover:bg-sky-50 hover:text-[#2AABEE] dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                        onClick={(e) => {
                          e.stopPropagation();
                          router.push(`/dashboard/sign-tasks?account=${encodeURIComponent(acc.name)}`);
                        }}
                      >
                        <Lightning weight="fill" size={16} className="shrink-0" />
                        <span className="whitespace-nowrap">{language === "zh" ? "任务" : "Tasks"} {`(${getAccountTaskCount(acc.name)})`}</span>
                      </button>
                      <button
                        type="button"
                        className="inline-flex h-10 items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 text-xs font-medium text-slate-600 shadow-sm transition-colors hover:border-[#2AABEE]/35 hover:bg-sky-50 hover:text-[#2AABEE] dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleShowLogs(acc.name);
                        }}
                      >
                        <ListDashes weight="bold" size={16} className="shrink-0" />
                        <span className="whitespace-nowrap">{t("logs")}</span>
                      </button>
                      <button
                        type="button"
                        className="inline-flex h-10 items-center justify-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 text-xs font-medium text-slate-600 shadow-sm transition-colors hover:border-emerald-200 hover:bg-emerald-50 hover:text-emerald-600 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200 dark:hover:bg-slate-800"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleEditAccount(acc);
                        }}
                      >
                        <PencilSimple weight="bold" size={16} className="shrink-0" />
                        <span className="whitespace-nowrap">{t("edit")}</span>
                      </button>
                      <button
                        type="button"
                        className="inline-flex h-10 items-center justify-center gap-1.5 rounded-xl border border-rose-100 bg-rose-50 px-3 text-xs font-medium text-rose-500 shadow-sm transition-colors hover:bg-rose-100 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-300"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleDeleteAccount(acc.name);
                        }}
                      >
                        <Trash weight="bold" size={16} className="shrink-0" />
                        <span className="whitespace-nowrap">{t("delete")}</span>
                      </button>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
        </div>
      </DashboardShell>

      <button
        type="button"
        onClick={openAddDialog}
        className="floating-fab"
        title={t("add_account")}
      >
        <Plus weight="bold" size={24} />
      </button>

      {showAddDialog && (
        <DialogShell
          title={reloginAccountName ? t("relogin_account") : t("add_account")}
          icon={Plus}
          size="md"
          onClose={handleCloseAddDialog}
          panelClassName="max-w-[560px]"
          bodyClassName="animate-float-up !p-6"
          bodyScrollable={false}
        >
          <div className="space-y-3">
            <div className="flex gap-2">
              <button
                className={`flex-1 h-9 rounded-lg text-xs font-semibold ${
                  loginMode === "phone"
                    ? "bg-[#2AABEE] text-white shadow-[0_10px_24px_rgba(42,171,238,0.22)]"
                    : "border border-slate-300 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
                }`}
                onClick={() => {
                  if (loginMode !== "phone" && qrLogin?.login_id) {
                    handleCancelQrLogin();
                  }
                  setLoginMode("phone");
                }}
              >
                {t("login_method_phone")}
              </button>
              <button
                className={`flex-1 rounded-lg px-4 py-2.5 text-xs font-semibold ${
                  loginMode === "qr"
                    ? "bg-[#2AABEE] text-white shadow-[0_10px_24px_rgba(42,171,238,0.22)]"
                    : "border border-slate-300 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
                }`}
                onClick={() => setLoginMode("qr")}
              >
                {t("login_method_qr")}
              </button>
            </div>

            {loginMode === "phone" ? (
              <div className="space-y-4">
                <div className="space-y-3">
                  <div>
                    <label className="mb-1 block text-[11px] font-medium text-slate-500">{t("session_name")}</label>
                    <input
                      type="text"
                      className="!mb-0 !h-10 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900"
                      placeholder={t("account_name_placeholder")}
                      value={loginData.account_name}
                      onChange={(e) => {
                        const cleaned = sanitizeAccountName(e.target.value);
                        setLoginData({ ...loginData, account_name: cleaned });
                      }}
                    />
                  </div>

                  <div>
                    <label className="mb-1 block text-[11px] font-medium text-slate-500">{t("phone_number")}</label>
                    <input
                      type="text"
                      className="!mb-0 !h-10 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900"
                      placeholder={t("phone_number_placeholder")}
                      value={loginData.phone_number}
                      onChange={(e) => setLoginData({ ...loginData, phone_number: e.target.value })}
                    />
                  </div>

                  <div>
                    <label className="mb-1 block text-[11px] font-medium text-slate-500">{t("login_code")}</label>
                    <div className="flex items-center gap-2">
                      <input
                        type="text"
                        className="!mb-0 !h-10 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900"
                        placeholder={t("login_code_placeholder")}
                        value={loginData.phone_code}
                        onChange={(e) => setLoginData({ ...loginData, phone_code: e.target.value })}
                      />
                      <button
                        className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-[#2AABEE] text-white shadow-[0_10px_24px_rgba(42,171,238,0.22)]"
                        onClick={handleStartLogin}
                        disabled={loading}
                        title={t("send_code")}
                      >
                        {loading ? <Spinner className="animate-spin" size={16} /> : <PaperPlaneRight weight="bold" />}
                      </button>
                    </div>
                  </div>

                  <div>
                    <label className="mb-1 block text-[11px] font-medium text-slate-500">{t("two_step_pass")}</label>
                    <input
                      type="password"
                      className="!mb-0 !h-10 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900"
                      placeholder={t("two_step_placeholder")}
                      value={loginData.password}
                      onChange={(e) => setLoginData({ ...loginData, password: e.target.value })}
                    />
                  </div>

                  <div>
                    <label className="mb-1 block text-[11px] font-medium text-slate-500">{t("proxy")}</label>
                    <input
                      type="text"
                      className="!mb-0 !h-10 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900"
                      placeholder={t("proxy_placeholder")}
                      value={loginData.proxy}
                      onChange={(e) => setLoginData({ ...loginData, proxy: e.target.value })}
                    />
                  </div>
                </div>

                <div className="flex gap-3">
                  <button
                    className="inline-flex h-10 flex-1 items-center justify-center rounded-lg border border-slate-300 bg-white px-4 text-xs font-medium text-slate-600 shadow-sm transition-colors hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
                    onClick={handleCloseAddDialog}
                  >
                    {t("cancel")}
                  </button>
                  <button
                    className="inline-flex h-10 flex-1 items-center justify-center rounded-lg bg-[#2AABEE] px-4 text-xs font-semibold text-white shadow-[0_10px_24px_rgba(42,171,238,0.22)] transition-colors hover:bg-[#199ddd] disabled:opacity-60"
                    onClick={handleVerifyLogin}
                    disabled={loading || !loginData.phone_code.trim()}
                  >
                    {loading ? <Spinner className="animate-spin" /> : t("confirm_connect")}
                  </button>
                </div>
              </div>
            ) : (
              <div className="space-y-3">
                <div className="space-y-3">
                  <div>
                    <label className="mb-1 block text-[11px] font-medium text-slate-500">{t("session_name")}</label>
                    <input
                      type="text"
                      className="!mb-0 !h-10 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900"
                      placeholder={t("account_name_placeholder")}
                      value={loginData.account_name}
                      onChange={(e) => {
                        const cleaned = sanitizeAccountName(e.target.value);
                        setLoginData({ ...loginData, account_name: cleaned });
                      }}
                    />
                  </div>

                  <div>
                    <label className="mb-1 block text-[11px] font-medium text-slate-500">{t("two_step_pass")}</label>
                    <input
                      type="password"
                      className="!mb-0 !h-10 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900"
                      placeholder={t("two_step_placeholder")}
                      value={qrPassword}
                      onChange={(e) => setQrPassword(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key !== "Enter") return;
                        if (qrPhase !== "password") return;
                        if (!qrPassword || qrPasswordLoading) return;
                        e.preventDefault();
                        handleSubmitQrPassword(qrPassword);
                      }}
                    />
                  </div>

                  <div>
                    <label className="mb-1 block text-[11px] font-medium text-slate-500">{t("proxy")}</label>
                    <input
                      type="text"
                      className="!mb-0 !h-10 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900"
                      placeholder={t("proxy_placeholder")}
                      value={loginData.proxy}
                      onChange={(e) => setLoginData({ ...loginData, proxy: e.target.value })}
                    />
                  </div>
                </div>

                <div className="rounded-xl border border-sky-100 bg-sky-50/60 p-3.5 dark:border-slate-700 dark:bg-slate-800/40">
                  <div className="space-y-3">
                    <div className="flex items-center justify-between gap-3">
                      <div className="text-xs text-main/60">{t("qr_tip")}</div>
                      <button
                        className="inline-flex h-8 items-center justify-center rounded-lg border border-slate-300 bg-white px-3 text-[11px] font-medium text-slate-600 hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
                        onClick={handleStartQrLogin}
                        disabled={qrLoading}
                      >
                        {qrLoading ? <Spinner className="animate-spin" /> : (qrLogin ? t("qr_refresh") : t("qr_start"))}
                      </button>
                    </div>
                    <div className="flex items-center justify-center">
                      {qrLogin?.qr_image ? (
                        <Image
                          src={qrLogin.qr_image}
                          alt={t("qr_alt")}
                          width={148}
                          height={148}
                          className="rounded-lg border border-slate-200 bg-slate-50 p-2 dark:border-slate-700 dark:bg-slate-950/90"
                        />
                      ) : (
                        <div className="flex h-[148px] w-[148px] items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-xs text-slate-400 dark:border-slate-700 dark:bg-slate-950/90">
                          {t("qr_start")}
                        </div>
                      )}
                    </div>
                    {qrLogin && (qrPhase === "ready" || qrPhase === "scanning") ? (
                      <div className="text-center font-mono text-[11px] text-main/40">
                        {t("qr_expires_in").replace("{seconds}", qrCountdown.toString())}
                      </div>
                    ) : null}
                    <div className="text-center text-xs font-semibold text-main/80">
                      {(qrPhase === "loading" || qrPhase === "ready") && t("qr_waiting")}
                      {qrPhase === "scanning" && t("qr_scanned")}
                      {qrPhase === "password" && t("qr_password_required")}
                      {qrPhase === "success" && t("qr_success")}
                      {qrPhase === "expired" && t("qr_expired")}
                      {qrPhase === "error" && t("qr_failed")}
                    </div>
                    {qrMessage ? (
                      <div className="text-center text-[11px] text-rose-400">{qrMessage}</div>
                    ) : null}
                  </div>
                </div>

                <div className="flex gap-3">
                  <button
                    className="inline-flex h-10 flex-1 items-center justify-center rounded-lg border border-slate-300 bg-white px-4 text-xs font-medium text-slate-600 shadow-sm transition-colors hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
                    onClick={handleCloseAddDialog}
                  >
                    {t("cancel")}
                  </button>
                  <button
                    className="inline-flex h-10 flex-1 items-center justify-center rounded-lg bg-[#2AABEE] px-4 text-xs font-semibold text-white shadow-[0_10px_24px_rgba(42,171,238,0.22)] transition-colors hover:bg-[#199ddd] disabled:opacity-60"
                    onClick={() => handleSubmitQrPassword(qrPassword)}
                    disabled={qrPhase !== "password" || !qrPassword || qrPasswordLoading}
                  >
                    {qrPasswordLoading ? <Spinner className="animate-spin" /> : t("confirm_connect")}
                  </button>
                </div>
              </div>
            )}
          </div>
        </DialogShell>
      )}

      {showEditDialog && (
        <DialogShell
          title={t("edit_account")}
          icon={PencilSimple}
          size="sm"
          onClose={() => setShowEditDialog(false)}
          bodyClassName="animate-float-up space-y-4"
        >
              <div>
                <label className="text-[11px] mb-1">{t("session_name")}</label>
                <input
                  type="text"
                  className="!py-2.5 !px-4 !mb-4"
                  value={editData.account_name}
                  onChange={(e) => {
                    const cleaned = sanitizeAccountName(e.target.value);
                    setEditData({ ...editData, account_name: cleaned });
                  }}
                />

                <label className="text-[11px] mb-1">{t("remark")}</label>
                <input
                  type="text"
                  className="!py-2.5 !px-4 !mb-4"
                  placeholder={t("remark_placeholder")}
                  value={editData.remark}
                  onChange={(e) => setEditData({ ...editData, remark: e.target.value })}
                />

                <label className="text-[11px] mb-1">{t("proxy")}</label>
                <input
                  type="text"
                  className="!py-2.5 !px-4"
                  placeholder={t("proxy_placeholder")}
                  style={{ marginBottom: 0 }}
                  value={editData.proxy}
                  onChange={(e) => setEditData({ ...editData, proxy: e.target.value })}
                />
              </div>

              <div className="flex gap-3 mt-6">
                <button 
                  className="btn-secondary flex-1 h-10 !py-0 !text-xs !bg-amber-500/10 !text-amber-500 hover:!bg-amber-500/20" 
                  onClick={() => {
                    setShowEditDialog(false);
                    openReloginDialog({ name: editData.account_name, proxy: editData.proxy } as any, false);
                  }}
                >
                  {t("relogin") || "Re-login"}
                </button>
                <button className="btn-secondary flex-1 h-10 !py-0 !text-xs" onClick={() => setShowEditDialog(false)}>{t("cancel")}</button>
                <button className="btn-gradient flex-1 h-10 !py-0 !text-xs" onClick={handleSaveEdit} disabled={loading}>
                  {loading ? <Spinner className="animate-spin" /> : t("save")}
                </button>
              </div>
        </DialogShell>
      )}

      {showLogsDialog && (
        <DialogShell
          title={`${logsAccountName} ${t("running_logs")}`}
          icon={ListDashes}
          size="2xl"
          panelClassName="max-h-[90vh]"
          onClose={() => setShowLogsDialog(false)}
          bodyClassName="bg-black/10 font-mono text-[13px] custom-scrollbar !p-0"
          footer={
            <div className="text-center">
              <button className="btn-secondary px-8 h-9 !py-0 mx-auto !text-xs" onClick={() => setShowLogsDialog(false)}>
                {t("close")}
              </button>
            </div>
          }
        >
          <div className="px-5 py-3 border-b border-white/5 flex justify-between items-center bg-white/2">
            <div className="text-[10px] text-main/30 font-bold uppercase tracking-wider">
              {t("logs_summary")
                .replace("{count}", accountLogs.length.toString())
                .replace("{days}", "3")}
            </div>
            {accountLogs.length > 0 && (
              <button
                onClick={handleClearLogs}
                disabled={loading}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-500/10 text-rose-400 text-[10px] font-bold hover:bg-rose-500/20 transition-all disabled:opacity-50"
              >
                <Trash weight="bold" size={14} />
                {t("clear_logs")}
              </button>
            )}
          </div>

          <div className="p-5">
            {logsLoading ? (
              <div className="flex flex-col items-center justify-center py-20 text-main/30">
                <Spinner className="animate-spin mb-4" size={32} />
                {t("loading")}
              </div>
            ) : accountLogs.length === 0 ? (
              <div className="text-center py-20 text-main/20 font-sans">{t("no_logs")}</div>
            ) : (
              <div className="space-y-3">
                {accountLogs.map((log, i) => (
                  <div key={i} className="p-4 rounded-xl bg-white/2 border border-white/5 group hover:border-white/10 transition-colors">
                    <div className="flex justify-between items-center mb-2.5 text-[10px] uppercase tracking-wider font-bold">
                      <span className="text-main/20 group-hover:text-main/40 transition-colors">{new Date(log.created_at).toLocaleString()}</span>
                      <span className={`px-2 py-0.5 rounded-md ${log.success ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}`}>
                        {log.success ? t("success") : t("failure")}
                      </span>
                    </div>
                    <div className="text-main/70 font-semibold mb-2">
                      {`${t("task_label")}: ${log.task_name} ${log.success ? t("task_exec_success") : t("task_exec_failed")}`}
                    </div>
                    {log.bot_message ? (
                      <div className="text-main/60 leading-relaxed whitespace-pre-wrap break-words mb-2">
                        <span className="text-main/35">{t("bot_reply")}: </span>
                        {log.bot_message}
                      </div>
                    ) : null}
                    {log.message && !["Success", "Failed", t("task_exec_success"), t("task_exec_failed")].includes(log.message.trim()) ? (
                      <pre className="whitespace-pre-wrap text-main/45 leading-relaxed overflow-x-auto max-h-[120px] scrollbar-none font-medium">
                        {log.message}
                      </pre>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </div>
        </DialogShell>
      )}

      <ToastContainer toasts={toasts} removeToast={removeToast} />
    </>
  );
}
