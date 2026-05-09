"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";
import {
  ArrowUDownLeft,
  DownloadSimple,
  Gear,
  Robot,
  Spinner,
  Terminal,
  Trash,
} from "@phosphor-icons/react";
import {
  deleteAIConfig,
  exportAllConfigs,
  getAIConfig,
  getGlobalSettings,
  getTelegramConfig,
  importAllConfigs,
  resetTelegramConfig,
  saveAIConfig,
  saveGlobalSettings,
  saveTelegramConfig,
  testAIConnection,
  type AIConfig,
  type GlobalSettings,
  type TelegramConfig,
} from "../../../lib/api";
import { getToken } from "../../../lib/auth";
import { DashboardShell } from "../../../components/dashboard-shell";
import { ToastContainer, useToast } from "../../../components/ui/toast";
import { useLanguage } from "../../../context/LanguageContext";
import { TelegramBotNotificationSettings } from "./TelegramBotNotificationSettings";

function SettingsSection({
  title,
  icon,
  action,
  children,
}: {
  title: ReactNode;
  icon: ReactNode;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="glass-panel demo-surface-card">
      <div className="demo-surface-header flex items-center justify-between gap-3">
        <h3 className="demo-section-title !mb-0">
          {icon}
          <span>{title}</span>
        </h3>
        {action}
      </div>
      <div className="demo-surface-body">{children}</div>
    </section>
  );
}

export default function SettingsPage() {
  const { language, t } = useLanguage();
  const { toasts, addToast, removeToast } = useToast();
  const [token, setToken] = useState<string | null>(null);
  const [checking, setChecking] = useState(true);
  const [configLoading, setConfigLoading] = useState(false);
  const [telegramLoading, setTelegramLoading] = useState(false);
  const [aiTesting, setAiTesting] = useState(false);
  const [importConfig, setImportConfig] = useState("");
  const [overwriteConfig, setOverwriteConfig] = useState(false);
  const [aiConfig, setAiConfig] = useState<AIConfig | null>(null);
  const [aiTestResult, setAiTestResult] = useState<string | null>(null);
  const [aiTestStatus, setAiTestStatus] = useState<"success" | "error" | null>(null);
  const [aiForm, setAiForm] = useState({
    api_key: "",
    base_url: "",
    model: "gpt-4o",
  });
  const [globalSettings, setGlobalSettings] = useState<GlobalSettings>({
    sign_interval: null,
    log_retention_days: 7,
    data_dir: null,
    global_proxy: null,
    telegram_bot_notify_enabled: false,
    telegram_bot_login_notify_enabled: false,
    telegram_bot_task_failure_enabled: true,
    telegram_bot_token: null,
    telegram_bot_chat_id: null,
    telegram_bot_message_thread_id: null,
  });
  const [telegramForm, setTelegramForm] = useState({
    api_id: "",
    api_hash: "",
  });
  const [telegramConfig, setTelegramConfig] = useState<TelegramConfig | null>(null);

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
    void Promise.all([
      loadAiConfig(tokenStr),
      loadGlobalSettings(tokenStr),
      loadTelegramConfig(tokenStr),
    ]);
  }, []);

  const loadAiConfig = async (tokenStr: string) => {
    try {
      const config = await getAIConfig(tokenStr);
      setAiConfig(config);
      if (config) {
        setAiForm({
          api_key: "",
          base_url: config.base_url || "",
          model: config.model || "gpt-4o",
        });
      }
    } catch {
      setAiConfig(null);
    }
  };

  const loadGlobalSettings = async (tokenStr: string) => {
    try {
      const settings = await getGlobalSettings(tokenStr);
      setGlobalSettings(settings);
    } catch {
      // keep defaults
    }
  };

  const loadTelegramConfig = async (tokenStr: string) => {
    try {
      const config = await getTelegramConfig(tokenStr);
      setTelegramConfig(config);
      setTelegramForm({
        api_id: config.api_id?.toString() || "",
        api_hash: config.api_hash || "",
      });
    } catch {
      setTelegramConfig(null);
    }
  };

  const handleSaveGlobal = async () => {
    if (!token) return;
    try {
      setConfigLoading(true);
      await saveGlobalSettings(token, globalSettings);
      addToast(t("global_save_success"), "success");
    } catch (err: any) {
      addToast(formatErrorMessage("save_failed", err), "error");
    } finally {
      setConfigLoading(false);
    }
  };

  const handleSaveAi = async () => {
    if (!token) return;
    try {
      setConfigLoading(true);
      const payload: { api_key?: string; base_url?: string; model?: string } = {
        base_url: aiForm.base_url.trim() || undefined,
        model: aiForm.model.trim() || undefined,
      };
      if (aiForm.api_key.trim()) {
        payload.api_key = aiForm.api_key.trim();
      }
      await saveAIConfig(token, payload);
      addToast(t("ai_save_success"), "success");
      await loadAiConfig(token);
    } catch (err: any) {
      addToast(formatErrorMessage("save_failed", err), "error");
    } finally {
      setConfigLoading(false);
    }
  };

  const handleTestAi = async () => {
    if (!token) return;
    try {
      setAiTesting(true);
      setAiTestResult(null);
      setAiTestStatus(null);
      const result = await testAIConnection(token);
      setAiTestStatus(result.success ? "success" : "error");
      setAiTestResult(result.success ? t("connect_success") : t("connect_failed"));
    } catch (err: any) {
      setAiTestStatus("error");
      setAiTestResult(formatErrorMessage("test_failed", err));
    } finally {
      setAiTesting(false);
    }
  };

  const handleDeleteAi = async () => {
    if (!token || !confirm(t("confirm_delete_ai"))) return;
    try {
      setConfigLoading(true);
      await deleteAIConfig(token);
      addToast(t("ai_delete_success"), "success");
      setAiConfig(null);
      setAiForm({ api_key: "", base_url: "", model: "gpt-4o" });
    } catch (err: any) {
      addToast(formatErrorMessage("delete_failed", err), "error");
    } finally {
      setConfigLoading(false);
    }
  };

  const handleSaveTelegram = async () => {
    if (!token) return;
    if (!telegramForm.api_id || !telegramForm.api_hash) {
      addToast(t("form_incomplete"), "error");
      return;
    }

    try {
      setTelegramLoading(true);
      await saveTelegramConfig(token, telegramForm);
      addToast(t("telegram_save_success"), "success");
      await loadTelegramConfig(token);
    } catch (err: any) {
      addToast(formatErrorMessage("save_failed", err), "error");
    } finally {
      setTelegramLoading(false);
    }
  };

  const handleResetTelegram = async () => {
    if (!token || !confirm(t("confirm_reset_telegram"))) return;
    try {
      setTelegramLoading(true);
      await resetTelegramConfig(token);
      addToast(t("config_reset"), "success");
      await loadTelegramConfig(token);
    } catch (err: any) {
      addToast(formatErrorMessage("operation_failed", err), "error");
    } finally {
      setTelegramLoading(false);
    }
  };

  const handleExport = async () => {
    if (!token) return;
    try {
      setConfigLoading(true);
      const config = await exportAllConfigs(token);
      const blob = new Blob([config], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "tg-signer-config.json";
      anchor.click();
      addToast(t("export_success"), "success");
    } catch (err: any) {
      addToast(formatErrorMessage("export_failed", err), "error");
    } finally {
      setConfigLoading(false);
    }
  };

  const handleImport = async () => {
    if (!token) return;
    if (!importConfig.trim()) {
      addToast(t("import_empty"), "error");
      return;
    }

    try {
      setConfigLoading(true);
      await importAllConfigs(token, importConfig, overwriteConfig);
      addToast(t("import_success"), "success");
      setImportConfig("");
      await Promise.all([
        loadAiConfig(token),
        loadGlobalSettings(token),
        loadTelegramConfig(token),
      ]);
    } catch (err: any) {
      addToast(formatErrorMessage("import_failed", err), "error");
    } finally {
      setConfigLoading(false);
    }
  };

  if (!token || checking) {
    return null;
  }

  return (
    <>
      <DashboardShell
        title={language === "zh" ? "系统设置" : "System Settings"}
        activeNav="settings"
        contentClassName="mx-auto max-w-4xl"
      >
        <div className="space-y-6 pb-10">
          <div className="grid gap-6 md:grid-cols-2">
            <SettingsSection
              title={t("global_settings")}
              icon={<Gear weight="fill" size={16} className="text-[#2AABEE]" />}
            >
              <div className="space-y-4">
                <div>
                  <label>{t("log_retention")}</label>
                  <input
                    type="number"
                    value={globalSettings.log_retention_days ?? 7}
                    onChange={(e) =>
                      setGlobalSettings((prev) => ({
                        ...prev,
                        log_retention_days: parseInt(e.target.value, 10) || 0,
                      }))
                    }
                  />
                </div>
                <div>
                  <label>{t("data_dir")}</label>
                  <input
                    value={globalSettings.data_dir || ""}
                    onChange={(e) =>
                      setGlobalSettings((prev) => ({
                        ...prev,
                        data_dir: e.target.value || null,
                      }))
                    }
                  />
                </div>
                <div>
                  <label>{t("global_proxy")}</label>
                  <input
                    value={globalSettings.global_proxy || ""}
                    onChange={(e) =>
                      setGlobalSettings((prev) => ({
                        ...prev,
                        global_proxy: e.target.value || null,
                      }))
                    }
                    placeholder={t("global_proxy_placeholder")}
                  />
                </div>
                <button
                  type="button"
                  className="btn-gradient"
                  onClick={handleSaveGlobal}
                  disabled={configLoading}
                >
                  {configLoading ? <Spinner className="animate-spin" size={16} /> : null}
                  <span>{language === "zh" ? "保存设置" : "Save Settings"}</span>
                </button>
              </div>
            </SettingsSection>

            <SettingsSection
              title={t("tg_api_config")}
              icon={<Terminal weight="fill" size={16} className="text-[#2AABEE]" />}
              action={
                <button
                  type="button"
                  className="action-btn"
                  onClick={handleResetTelegram}
                  title={t("restore_default")}
                  disabled={telegramLoading}
                >
                  {telegramLoading ? (
                    <Spinner className="animate-spin" size={14} />
                  ) : (
                    <ArrowUDownLeft weight="bold" size={14} />
                  )}
                </button>
              }
            >
              <div className="space-y-4">
                <p className="demo-section-subtitle !mb-0">
                  {language === "zh"
                    ? "用于面板的 Telegram 核心连接，如无自定义需求请保持默认。"
                    : "Used for the panel's Telegram core connection. Keep the default values unless you need custom credentials."}
                </p>
                {telegramConfig ? (
                  <p className="demo-form-note !mt-0">
                    {telegramConfig.is_custom
                      ? (language === "zh"
                        ? "当前正在使用自定义 API 凭据。"
                        : "Custom API credentials are currently active.")
                      : (language === "zh"
                        ? "当前正在使用默认 API 凭据。"
                        : "Default API credentials are currently active.")}
                  </p>
                ) : null}
                <div>
                  <label>{t("api_id")}</label>
                  <input
                    className="font-mono"
                    value={telegramForm.api_id}
                    onChange={(e) =>
                      setTelegramForm((prev) => ({ ...prev, api_id: e.target.value }))
                    }
                  />
                </div>
                <div>
                  <label>{t("api_hash")}</label>
                  <input
                    className="font-mono"
                    value={telegramForm.api_hash}
                    onChange={(e) =>
                      setTelegramForm((prev) => ({ ...prev, api_hash: e.target.value }))
                    }
                  />
                </div>
                <div className="demo-alert">
                  <Terminal weight="fill" size={16} />
                  <span>{t("tg_config_warning")}</span>
                </div>
                <button
                  type="button"
                  className="btn-secondary !w-full"
                  onClick={handleSaveTelegram}
                  disabled={telegramLoading}
                >
                  {telegramLoading ? <Spinner className="animate-spin" size={16} /> : null}
                  <span>{language === "zh" ? "保存 API 凭据" : "Save API Credentials"}</span>
                </button>
              </div>
            </SettingsSection>
          </div>

          <SettingsSection
            title={t("ai_config")}
            icon={<Robot weight="fill" size={16} className="text-[#2AABEE]" />}
            action={
              aiConfig ? (
                <button
                  type="button"
                  className="action-btn"
                  onClick={handleDeleteAi}
                  title={t("delete_ai_config")}
                  disabled={configLoading}
                >
                  <Trash weight="bold" size={14} />
                </button>
              ) : undefined
            }
          >
            <div className="space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="md:col-span-2">
                  <label>{t("api_key")}</label>
                  <input
                    type="password"
                    value={aiForm.api_key}
                    onChange={(e) =>
                      setAiForm((prev) => ({ ...prev, api_key: e.target.value }))
                    }
                    placeholder={aiConfig?.api_key_masked || t("api_key")}
                  />
                </div>
                <div>
                  <label>{t("base_url")}</label>
                  <input
                    value={aiForm.base_url}
                    onChange={(e) =>
                      setAiForm((prev) => ({ ...prev, base_url: e.target.value }))
                    }
                  />
                </div>
                <div>
                  <label>{t("model")}</label>
                  <input
                    value={aiForm.model}
                    onChange={(e) =>
                      setAiForm((prev) => ({ ...prev, model: e.target.value }))
                    }
                  />
                </div>
              </div>
              <div className="flex flex-col gap-3 md:flex-row">
                <button
                  type="button"
                  className="btn-gradient md:!w-auto"
                  onClick={handleSaveAi}
                  disabled={configLoading}
                >
                  {configLoading ? <Spinner className="animate-spin" size={16} /> : null}
                  <span>{t("save")}</span>
                </button>
                <button
                  type="button"
                  className="btn-secondary md:!w-auto"
                  onClick={handleTestAi}
                  disabled={configLoading || aiTesting}
                >
                  {aiTesting ? <Spinner className="animate-spin" size={16} /> : null}
                  <span>{t("test_connection")}</span>
                </button>
              </div>
              {aiTestResult ? (
                <div
                  className={`rounded-lg border px-4 py-3 text-sm ${
                    aiTestStatus === "success"
                      ? "border-emerald-200 bg-emerald-50 text-emerald-600 dark:border-emerald-900/40 dark:bg-emerald-900/20 dark:text-emerald-400"
                      : "border-rose-200 bg-rose-50 text-rose-600 dark:border-rose-900/40 dark:bg-rose-900/20 dark:text-rose-400"
                  }`}
                >
                  {aiTestResult}
                </div>
              ) : null}
            </div>
          </SettingsSection>

          <TelegramBotNotificationSettings
            settings={globalSettings}
            setSettings={setGlobalSettings}
            loading={configLoading}
            onSave={handleSaveGlobal}
            t={t}
          />

          <SettingsSection
            title={t("backup_migration")}
            icon={<DownloadSimple weight="fill" size={16} className="text-[#2AABEE]" />}
          >
            <div className="grid gap-6 md:grid-cols-2">
              <div>
                <label>{t("export_config")}</label>
                <p className="demo-form-note">{t("export_desc")}</p>
                <button
                  type="button"
                  className="btn-secondary mt-3 !w-full"
                  onClick={handleExport}
                  disabled={configLoading}
                >
                  {configLoading ? <Spinner className="animate-spin" size={16} /> : null}
                  <span>{t("download_json")}</span>
                </button>
              </div>

              <div className="space-y-3">
                <div className="flex items-center justify-between gap-3">
                  <label className="!mb-0">{t("import_config")}</label>
                  <label className="cursor-pointer text-xs font-semibold text-[#2AABEE]">
                    {t("upload_json")}
                    <input
                      type="file"
                      accept=".json"
                      className="hidden"
                      onChange={(e) => {
                        const file = e.target.files?.[0];
                        if (!file) return;
                        const reader = new FileReader();
                        reader.onload = (event) => {
                          setImportConfig((event.target?.result as string) || "");
                        };
                        reader.readAsText(file);
                      }}
                    />
                  </label>
                </div>
                <textarea
                  className="min-h-[120px] font-mono text-xs"
                  placeholder={t("paste_json")}
                  value={importConfig}
                  onChange={(e) => setImportConfig(e.target.value)}
                />
                <button
                  type="button"
                  className="flex items-center gap-3 text-left"
                  onClick={() => setOverwriteConfig((prev) => !prev)}
                >
                  <span className={`demo-switch ${overwriteConfig ? "is-on" : ""}`} />
                  <span className="text-sm text-main/70">{t("overwrite_conflict")}</span>
                </button>
                <button
                  type="button"
                  className="btn-gradient !w-full"
                  onClick={handleImport}
                  disabled={configLoading}
                >
                  {configLoading ? <Spinner className="animate-spin" size={16} /> : null}
                  <span>{t("execute_import")}</span>
                </button>
              </div>
            </div>
          </SettingsSection>
        </div>
      </DashboardShell>

      <ToastContainer toasts={toasts} removeToast={removeToast} />
    </>
  );
}
