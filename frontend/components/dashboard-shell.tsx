"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  ChartPieSlice,
  Gear,
  List,
  ListChecks,
  Moon,
  SignOut,
  Sun,
  TelegramLogo,
  UserCircle,
  UsersThree,
} from "@phosphor-icons/react";
import { useLanguage } from "../context/LanguageContext";
import { useTheme } from "../context/ThemeContext";
import { logout } from "../lib/auth";

type DashboardNavKey = "dashboard" | "accounts" | "tasks" | "settings";

type DashboardShellProps = {
  title: string;
  subtitle?: string;
  activeNav?: DashboardNavKey | null;
  headerActions?: ReactNode;
  contentClassName?: string;
  children: ReactNode;
};

const navItems: Array<{
  key: DashboardNavKey;
  href: string;
  icon: typeof ChartPieSlice;
  label: {
    zh: string;
    en: string;
  };
}> = [
  { key: "dashboard", href: "/dashboard", icon: ChartPieSlice, label: { zh: "仪表盘", en: "Dashboard" } },
  { key: "accounts", href: "/dashboard/accounts", icon: UsersThree, label: { zh: "账号管理", en: "Accounts" } },
  { key: "tasks", href: "/dashboard/sign-tasks", icon: ListChecks, label: { zh: "任务编排", en: "Tasks" } },
  { key: "settings", href: "/dashboard/settings", icon: Gear, label: { zh: "系统设置", en: "Settings" } },
];

export function DashboardShell({
  title,
  subtitle,
  activeNav,
  headerActions,
  contentClassName,
  children,
}: DashboardShellProps) {
  const pathname = usePathname();
  const router = useRouter();
  const { language, t } = useLanguage();
  const { theme, toggleTheme } = useTheme();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [profileMenuOpen, setProfileMenuOpen] = useState(false);
  const profileMenuRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const handleOutsideClick = (event: MouseEvent) => {
      if (!profileMenuRef.current) return;
      if (!profileMenuRef.current.contains(event.target as Node)) {
        setProfileMenuOpen(false);
      }
    };

    document.addEventListener("mousedown", handleOutsideClick);
    return () => document.removeEventListener("mousedown", handleOutsideClick);
  }, []);

  const resolvedActiveNav =
    activeNav !== undefined
      ? activeNav
      : pathname === "/dashboard"
        ? "dashboard"
        : pathname.startsWith("/dashboard/accounts") ||
            pathname.startsWith("/dashboard/account-tasks")
          ? "accounts"
          : pathname.startsWith("/dashboard/sign-tasks")
            ? "tasks"
            : pathname.startsWith("/dashboard/settings")
              ? "settings"
              : null;

  const profileLabel = language === "zh" ? "个人中心" : "Profile";

  return (
    <div className="app-shell">
      <div
        className={`app-sidebar-overlay ${sidebarOpen ? "is-open" : ""}`}
        onClick={() => setSidebarOpen(false)}
      />

      <aside className={`app-sidebar ${sidebarOpen ? "is-open" : ""}`}>
        <div className="app-sidebar-top">
          <Link href="/dashboard" className="app-brand" onClick={() => setSidebarOpen(false)}>
            <div className="app-brand-mark">
              <TelegramLogo weight="fill" size={20} />
            </div>
            <div className="app-brand-name">TG-SignPulse</div>
          </Link>
        </div>

        <nav className="app-nav">
          {navItems.map(({ key, href, icon: Icon, label }) => {
            const isActive = resolvedActiveNav === key;
            return (
              <Link
                key={key}
                href={href}
                className={`app-nav-item ${isActive ? "is-active" : ""}`}
                onClick={() => setSidebarOpen(false)}
              >
                <Icon weight={isActive ? "fill" : "bold"} className="app-nav-icon" size={20} />
                <span>{label[language]}</span>
              </Link>
            );
          })}
        </nav>
      </aside>

      <div className="app-main">
        <header className="app-header">
          <div className="app-header-left">
            <button
              type="button"
              className="app-mobile-toggle lg:hidden"
              onClick={() => setSidebarOpen(true)}
              title={language === "zh" ? "打开导航" : "Open navigation"}
              aria-label={language === "zh" ? "打开导航" : "Open navigation"}
            >
              <List weight="bold" size={20} />
            </button>
            <div className="app-header-copy">
              <h1 className="app-header-title">{title}</h1>
              {subtitle ? <p className="sr-only">{subtitle}</p> : null}
            </div>
          </div>

          <div className="app-header-right">
            {headerActions ? <div className="app-header-tools">{headerActions}</div> : null}

            <button
              type="button"
              className="app-header-circle-btn"
              onClick={toggleTheme}
              title={theme === "dark" ? t("switch_to_light") : t("switch_to_dark")}
            >
              {theme === "dark" ? <Sun weight="fill" size={16} /> : <Moon weight="fill" size={16} />}
            </button>

            <div className="relative" ref={profileMenuRef}>
              <button
                type="button"
                className="app-profile-trigger"
                onClick={() => setProfileMenuOpen((prev) => !prev)}
                title={profileLabel}
              >
                <div className="app-profile-avatar">A</div>
              </button>

              {profileMenuOpen ? (
                <div className="app-profile-menu">
                  <Link
                    href="/dashboard/profile"
                    className="app-profile-menu-item"
                    onClick={() => {
                      setProfileMenuOpen(false);
                      setSidebarOpen(false);
                    }}
                  >
                    <UserCircle weight="bold" size={16} />
                    <div className="app-profile-menu-title">{profileLabel}</div>
                  </Link>

                  <button
                    type="button"
                    className="app-profile-menu-item is-danger"
                    onClick={() => {
                      logout();
                      router.push("/");
                    }}
                  >
                    <SignOut weight="bold" size={16} />
                    <div className="app-profile-menu-title">{t("logout")}</div>
                  </button>
                </div>
              ) : null}
            </div>
          </div>
        </header>

        <div className="app-page-scroll">
          <div className={`app-page-inner ${contentClassName || ""}`}>{children}</div>
        </div>
      </div>
    </div>
  );
}
