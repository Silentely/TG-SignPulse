"use client";

import Link from "next/link";
import { Compass, House, GithubLogo, Signpost } from "@phosphor-icons/react";
import { ThemeLanguageToggle } from "../components/ThemeLanguageToggle";
import { useLanguage } from "../context/LanguageContext";

export default function NotFoundPage() {
  const { language } = useLanguage();

  const title = language === "zh" ? "页面没有在当前路由里找到" : "This page was not found in the current route map.";
  const description = language === "zh"
    ? "你访问的地址不存在，或者界面结构已经调整。可以回到首页重新进入，也可以直接回到控制台。"
    : "The address does not exist, or the UI structure has moved. Return home or jump straight back to the console.";

  return (
    <main className="relative min-h-screen overflow-hidden px-4 py-6 sm:px-6 lg:px-8">
      <div className="pointer-events-none absolute inset-0 overflow-hidden">
        <div className="absolute left-[-80px] top-[-60px] h-[260px] w-[260px] rounded-full bg-[#2AABEE]/12 blur-3xl" />
        <div className="absolute bottom-[-100px] right-[-50px] h-[320px] w-[320px] rounded-full bg-sky-400/10 blur-3xl" />
      </div>

      <div className="relative mx-auto flex min-h-[calc(100vh-3rem)] max-w-5xl items-center justify-center">
        <div className="glass-panel w-full max-w-3xl rounded-[32px] border border-black/5 bg-white/84 p-8 text-center shadow-2xl dark:border-white/5 dark:bg-slate-950/72 sm:p-12">
          <div className="mb-6 flex items-center justify-between gap-4">
            <div className="inline-flex items-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#2AABEE]/12 text-[#2AABEE]">
                <Compass weight="fill" size={22} />
              </div>
              <div className="text-left">
                <div className="brand-text-grad !mt-0 text-2xl">SignPulse</div>
                <div className="mt-1 text-[10px] font-bold uppercase tracking-[0.26em] text-main/35">
                  Route Fallback
                </div>
              </div>
            </div>

            <div className="shrink-0">
              <ThemeLanguageToggle />
            </div>
          </div>

          <div className="mx-auto flex h-24 w-24 items-center justify-center rounded-[28px] bg-gradient-to-br from-[#2AABEE]/14 to-sky-400/14 text-[#2AABEE]">
            <Signpost weight="fill" size={42} />
          </div>

          <div className="mt-6 text-[11px] font-bold uppercase tracking-[0.24em] text-[#2AABEE]">
            404 / Not Found
          </div>

          <h1 className="mt-3 text-3xl font-extrabold tracking-[-0.04em] text-main sm:text-4xl">
            {title}
          </h1>

          <p className="mx-auto mt-4 max-w-2xl text-[15px] leading-8 text-main/55">
            {description}
          </p>

          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link href="/" className="btn-gradient !w-auto min-w-[160px] !rounded-2xl">
              <House weight="bold" />
              <span>{language === "zh" ? "返回首页" : "Go Home"}</span>
            </Link>
            <Link href="/dashboard" className="btn-secondary !w-auto min-w-[160px] !rounded-2xl">
              <Compass weight="bold" />
              <span>{language === "zh" ? "进入控制台" : "Open Console"}</span>
            </Link>
          </div>

          <div className="mt-8 border-t border-black/5 pt-5 dark:border-white/5">
            <a
              href="https://github.com/akasls/TG-SignPulse"
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-2 rounded-full border border-[#2AABEE]/18 bg-[#2AABEE]/10 px-3 py-1.5 text-[11px] font-semibold text-[#2AABEE] transition-colors hover:bg-[#2AABEE]/15"
            >
              <GithubLogo weight="bold" size={14} />
              <span>GitHub</span>
            </a>
          </div>
        </div>
      </div>
    </main>
  );
}
