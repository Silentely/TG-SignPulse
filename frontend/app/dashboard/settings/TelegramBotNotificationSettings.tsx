"use client";

import { Robot, Spinner } from "@phosphor-icons/react";
import type { GlobalSettings } from "../../../lib/api";

type Props = {
  settings: GlobalSettings;
  setSettings: (settings: GlobalSettings) => void;
  loading: boolean;
  onSave: () => void;
  t: (key: string) => string;
};

function formatNotifyTarget(settings: GlobalSettings) {
  if (!settings.telegram_bot_chat_id) return "";
  return settings.telegram_bot_message_thread_id
    ? `${settings.telegram_bot_chat_id}/${settings.telegram_bot_message_thread_id}`
    : settings.telegram_bot_chat_id;
}

function parseNotifyTarget(value: string) {
  const trimmed = value.trim();
  if (!trimmed) {
    return {
      telegram_bot_chat_id: null,
      telegram_bot_message_thread_id: null,
    };
  }

  const [chatIdPart, threadIdPart] = trimmed.split("/", 2);
  const chatId = chatIdPart?.trim() || null;
  const threadId = threadIdPart?.trim();

  return {
    telegram_bot_chat_id: chatId,
    telegram_bot_message_thread_id:
      threadId && /^\d+$/.test(threadId) ? parseInt(threadId, 10) : null,
  };
}

function SettingSwitch({
  checked,
  onToggle,
  title,
  description,
}: {
  checked: boolean;
  onToggle: () => void;
  title: string;
  description?: string;
}) {
  return (
    <div className="demo-switch-card">
      <div className="min-w-0">
        <div className="text-sm font-medium text-main">{title}</div>
        {description ? <div className="mt-1 text-xs text-main/50">{description}</div> : null}
      </div>
      <button
        type="button"
        className="demo-switch-wrapper shrink-0"
        onClick={onToggle}
        aria-label={title}
      >
        <span className={`demo-switch ${checked ? "is-on" : ""}`} />
      </button>
    </div>
  );
}

export function TelegramBotNotificationSettings({
  settings,
  setSettings,
  loading,
  onSave,
  t,
}: Props) {
  return (
    <section className="glass-panel demo-surface-card">
      <div className="demo-surface-header flex items-center justify-between gap-3">
        <h3 className="demo-section-title !mb-0">
          <Robot weight="fill" size={16} className="text-[#2AABEE]" />
          <span>{t("telegram_bot_notify")}</span>
        </h3>
        <button
          type="button"
          className="demo-switch-wrapper"
          onClick={() =>
            setSettings({
              ...settings,
              telegram_bot_notify_enabled: !settings.telegram_bot_notify_enabled,
            })
          }
          aria-label={t("telegram_bot_master_switch")}
        >
          <span className={`demo-switch ${settings.telegram_bot_notify_enabled ? "is-on" : ""}`} />
        </button>
      </div>

      <div className="demo-surface-body space-y-4">
        <div>
          <label>{t("telegram_bot_token")}</label>
          <input
            type="password"
            value={settings.telegram_bot_token || ""}
            onChange={(e) =>
              setSettings({
                ...settings,
                telegram_bot_token: e.target.value.trim() || null,
              })
            }
            placeholder={t("telegram_bot_token_placeholder")}
          />
        </div>

        <div>
          <label>{`${t("telegram_bot_chat_id")} / ${t("telegram_bot_thread_id")}`}</label>
          <input
            value={formatNotifyTarget(settings)}
            onChange={(e) =>
              setSettings({
                ...settings,
                ...parseNotifyTarget(e.target.value),
              })
            }
            placeholder="-1003820990608/67"
          />
          <p className="demo-form-note">-1003820990608 或 -1003820990608/67</p>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <SettingSwitch
            checked={Boolean(settings.telegram_bot_login_notify_enabled)}
            onToggle={() =>
              setSettings({
                ...settings,
                telegram_bot_login_notify_enabled: !settings.telegram_bot_login_notify_enabled,
              })
            }
            title={t("telegram_login_notify")}
            description={t("telegram_login_notify_desc")}
          />

          <SettingSwitch
            checked={settings.telegram_bot_task_failure_enabled !== false}
            onToggle={() =>
              setSettings({
                ...settings,
                telegram_bot_task_failure_enabled: !(settings.telegram_bot_task_failure_enabled !== false),
              })
            }
            title={t("telegram_task_failure_notify")}
            description={t("telegram_task_failure_notify_desc")}
          />
        </div>

        <button type="button" className="btn-gradient" onClick={onSave} disabled={loading}>
          {loading ? <Spinner className="animate-spin" size={16} /> : null}
          <span>{t("save")}</span>
        </button>
      </div>
    </section>
  );
}
