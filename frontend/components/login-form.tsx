"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { login } from "../lib/api";
import { setToken } from "../lib/auth";
import { GithubLogo, Moon, Spinner, Sun, TelegramLogo } from "@phosphor-icons/react";
import { useLanguage } from "../context/LanguageContext";
import { useTheme } from "../context/ThemeContext";

export default function LoginForm() {
  const router = useRouter();
  const { t, language } = useLanguage();
  const { theme, toggleTheme } = useTheme();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  const subtitle = "Telegram Automation Console";
  const totpLabel = language === "zh" ? "两步验证码 (可选)" : "Two-Factor Code (Optional)";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setErrorMsg("");

    try {
      const res = await login({ username, password, totp_code: totp || undefined });
      setToken(res.access_token);
      router.push("/dashboard");
    } catch (err: any) {
      const msg = err?.message || "";
      const lowerMsg = msg.toLowerCase();
      let displayMsg = t("login_failed");

      if (lowerMsg.includes("totp")) {
        displayMsg = t("totp_error");
      } else if (
        lowerMsg.includes("invalid") ||
        lowerMsg.includes("credentials") ||
        lowerMsg.includes("password")
      ) {
        displayMsg = t("user_or_pass_error");
      }

      setErrorMsg(displayMsg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen overflow-hidden px-4 py-6 sm:px-6">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute left-[-120px] top-[-80px] h-[260px] w-[260px] rounded-full bg-[#2AABEE]/12 blur-3xl" />
        <div className="absolute bottom-[-100px] right-[-80px] h-[300px] w-[300px] rounded-full bg-sky-400/10 blur-3xl" />
      </div>

      <div className="relative mx-auto flex min-h-[calc(100vh-3rem)] max-w-5xl items-center justify-center">
        <section className="w-full max-w-[460px] glass-panel border border-black/5 bg-white/86 p-6 shadow-2xl dark:border-white/5 dark:bg-slate-950/72 sm:p-7">
          <div className="flex flex-col items-center text-center">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-gradient-to-br from-[#2AABEE] to-sky-400 text-white shadow-[0_16px_36px_rgba(42,171,238,0.28)]">
              <TelegramLogo weight="fill" size={28} />
            </div>
            <div className="mt-4 text-3xl font-extrabold tracking-[-0.045em] text-main">
              TG-SignPulse
            </div>
            <div className="mt-2 text-[10px] font-bold uppercase tracking-[0.26em] text-main/38">
              {subtitle}
            </div>
          </div>

          <form onSubmit={handleSubmit} className="mt-8 space-y-4" autoComplete="off">
            <div>
              <label className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-main/58">
                {t("username")}
              </label>
              <input
                type="text"
                name="username"
                className="!mb-0 !rounded-2xl !border-black/5 !bg-black/5 !px-4 !py-3.5 dark:!border-white/10 dark:!bg-white/5"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder={t("username")}
                autoComplete="off"
              />
            </div>

            <div>
              <label className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-main/58">
                {t("password")}
              </label>
              <input
                type="password"
                name="password"
                className="!mb-0 !rounded-2xl !border-black/5 !bg-black/5 !px-4 !py-3.5 dark:!border-white/10 dark:!bg-white/5"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder={t("password")}
                autoComplete="new-password"
              />
            </div>

            <div>
              <label className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-main/58">
                {totpLabel}
              </label>
              <input
                type="text"
                name="totp"
                className="!mb-0 !rounded-2xl !border-black/5 !bg-black/5 !px-4 !py-3.5 !text-center !font-bold !tracking-[4px] dark:!border-white/10 dark:!bg-white/5"
                value={totp}
                onChange={(e) => setTotp(e.target.value)}
                placeholder={t("totp_placeholder")}
                autoComplete="off"
              />
            </div>

            {errorMsg ? (
              <div className="rounded-2xl border border-[#ff4757]/20 bg-[#ff4757]/10 px-3 py-3 text-center text-[11px] font-medium text-[#ff4757]">
                {errorMsg}
              </div>
            ) : null}

            <button
              className="btn-gradient w-full !rounded-2xl !py-3.5 font-bold shadow-xl transition-all"
              type="submit"
              disabled={loading}
            >
              {loading ? (
                <div className="flex items-center justify-center gap-2">
                  <Spinner className="animate-spin" size={18} />
                  <span>{t("login_loading")}</span>
                </div>
              ) : (
                <span className="text-sm">{t("login")}</span>
              )}
            </button>
          </form>

          <div className="mt-6 flex items-center justify-center gap-3 border-t border-black/5 pt-5 dark:border-white/5">
            <button
              type="button"
              onClick={toggleTheme}
              className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-black/5 bg-black/5 text-main/60 transition-colors hover:bg-black/8 hover:text-main dark:border-white/10 dark:bg-white/5 dark:text-main/70 dark:hover:bg-white/10"
              title={theme === "dark" ? t("switch_to_light") : t("switch_to_dark")}
              aria-label={theme === "dark" ? t("switch_to_light") : t("switch_to_dark")}
            >
              {theme === "dark" ? <Sun weight="bold" size={16} /> : <Moon weight="bold" size={16} />}
            </button>

            <a
              href="https://github.com/akasls/TG-SignPulse"
              target="_blank"
              rel="noreferrer"
              className="inline-flex h-10 w-10 items-center justify-center rounded-full border border-[#2AABEE]/18 bg-[#2AABEE]/10 text-[#2AABEE] transition-colors hover:bg-[#2AABEE]/16"
              aria-label="GitHub"
              title="GitHub"
            >
              <GithubLogo weight="bold" size={16} />
            </a>
          </div>
        </section>
      </div>
    </div>
  );
}
