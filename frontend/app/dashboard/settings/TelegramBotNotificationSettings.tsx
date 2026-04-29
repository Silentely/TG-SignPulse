"use client";

import { Robot as BotIcon, Spinner } from "@phosphor-icons/react";
import { GlobalSettings } from "../../../lib/api";

type Props = {
    settings: GlobalSettings;
    setSettings: (settings: GlobalSettings) => void;
    loading: boolean;
    onSave: () => void;
    t: (key: string) => string;
};

function Toggle({
    checked,
    onChange,
    label,
}: {
    checked: boolean;
    onChange: () => void;
    label: string;
}) {
    return (
        <button
            type="button"
            className={`w-12 h-7 rounded-full relative transition-all shadow-sm border-2 ${checked ? "bg-[#8a3ffc] border-[#8a3ffc]" : "bg-black/20 dark:bg-white/10 border-black/10 dark:border-white/30"}`}
            onClick={onChange}
            aria-label={label}
        >
            <span className={`absolute top-0.5 w-5 h-5 rounded-full bg-white transition-all shadow-md ${checked ? "left-6" : "left-0.5"}`} />
        </button>
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
        <div className="glass-panel p-4">
            <div className="flex items-center gap-3 mb-4">
                <div className="p-2 bg-cyan-500/10 rounded-xl text-cyan-400">
                    <BotIcon weight="bold" size={18} />
                </div>
                <h2 className="text-lg font-bold">{t("telegram_bot_notify")}</h2>
            </div>

            <div className="space-y-4">
                <div className="rounded-xl border border-white/5 bg-white/3 p-3 flex items-center justify-between gap-3">
                    <div>
                        <label className="text-[11px] mb-1">{t("telegram_bot_master_switch")}</label>
                        <p className="text-[9px] text-[#9496a1]">{t("telegram_bot_notify_desc")}</p>
                    </div>
                    <Toggle
                        checked={Boolean(settings.telegram_bot_notify_enabled)}
                        label={t("telegram_bot_master_switch")}
                        onChange={() => setSettings({
                            ...settings,
                            telegram_bot_notify_enabled: !settings.telegram_bot_notify_enabled,
                        })}
                    />
                </div>

                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    <div>
                        <label className="text-[11px] mb-1">{t("telegram_bot_token")}</label>
                        <input
                            type="password"
                            className="!py-2 !px-4"
                            value={settings.telegram_bot_token || ""}
                            onChange={(e) => setSettings({ ...settings, telegram_bot_token: e.target.value || null })}
                            placeholder={t("telegram_bot_token_placeholder")}
                        />
                    </div>
                    <div>
                        <label className="text-[11px] mb-1">{t("telegram_bot_chat_id")}</label>
                        <input
                            className="!py-2 !px-4"
                            value={settings.telegram_bot_chat_id || ""}
                            onChange={(e) => setSettings({ ...settings, telegram_bot_chat_id: e.target.value || null })}
                            placeholder={t("telegram_bot_chat_id_placeholder")}
                        />
                    </div>
                    <div>
                        <label className="text-[11px] mb-1">{t("telegram_bot_thread_id")}</label>
                        <input
                            inputMode="numeric"
                            className="!py-2 !px-4"
                            value={settings.telegram_bot_message_thread_id ?? ""}
                            onChange={(e) => setSettings({
                                ...settings,
                                telegram_bot_message_thread_id: e.target.value ? parseInt(e.target.value) : null,
                            })}
                            placeholder={t("telegram_bot_thread_id_placeholder")}
                        />
                    </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                    <div className="rounded-xl border border-white/5 bg-black/5 p-3 flex items-center justify-between gap-3">
                        <div>
                            <label className="text-[11px] mb-1">{t("telegram_login_notify")}</label>
                            <p className="text-[9px] text-[#9496a1]">{t("telegram_login_notify_desc")}</p>
                        </div>
                        <Toggle
                            checked={Boolean(settings.telegram_bot_login_notify_enabled)}
                            label={t("telegram_login_notify")}
                            onChange={() => setSettings({
                                ...settings,
                                telegram_bot_login_notify_enabled: !settings.telegram_bot_login_notify_enabled,
                            })}
                        />
                    </div>

                    <div className="rounded-xl border border-white/5 bg-black/5 p-3 flex items-center justify-between gap-3">
                        <div>
                            <label className="text-[11px] mb-1">{t("telegram_task_failure_notify")}</label>
                            <p className="text-[9px] text-[#9496a1]">{t("telegram_task_failure_notify_desc")}</p>
                        </div>
                        <Toggle
                            checked={settings.telegram_bot_task_failure_enabled !== false}
                            label={t("telegram_task_failure_notify")}
                            onChange={() => setSettings({
                                ...settings,
                                telegram_bot_task_failure_enabled: !(settings.telegram_bot_task_failure_enabled !== false),
                            })}
                        />
                    </div>
                </div>

                <button className="btn-gradient w-fit px-5 !py-2 !text-[11px]" onClick={onSave} disabled={loading}>
                    {loading ? <Spinner className="animate-spin" /> : t("save")}
                </button>
            </div>
        </div>
    );
}
