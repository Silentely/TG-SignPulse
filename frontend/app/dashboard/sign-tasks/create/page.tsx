"use client";

import Link from "next/link";
import { CaretLeft } from "@phosphor-icons/react";
import { DashboardShell } from "../../../../components/dashboard-shell";
import { useLanguage } from "../../../../context/LanguageContext";
import { CreateSignTaskContent } from "./create-sign-task-content";

export default function CreateSignTaskPage() {
  const { t, language } = useLanguage();

  return (
    <DashboardShell
      title={t("add_task")}
      subtitle={
        language === "zh"
          ? "创建一个共享任务并绑定多个账号"
          : "Define one shared task flow and bind it to multiple accounts."
      }
      activeNav="tasks"
      contentClassName="max-w-5xl"
      headerActions={
        <Link href="/dashboard/sign-tasks" className="action-btn" title={t("cancel")}>
          <CaretLeft weight="bold" />
        </Link>
      }
    >
      <CreateSignTaskContent />
    </DashboardShell>
  );
}
