"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getToken } from "../../lib/auth";
import {
  type AccountInfo,
  type AccountLog,
  type SignTask,
  clearRecentAccountLogs,
  getRecentAccountLogs,
  listAccounts,
  listSignTasks,
} from "../../lib/api";
import { DashboardShell } from "../../components/dashboard-shell";
import { ToastContainer, useToast } from "../../components/ui/toast";
import { useLanguage } from "../../context/LanguageContext";
import {
  CheckCircle,
  ListChecks,
  Spinner,
  UsersThree,
  WarningCircle,
} from "@phosphor-icons/react";

const LOGS_PER_PAGE = 30;

function isSameDay(left: Date, right: Date) {
  return (
    left.getFullYear() === right.getFullYear() &&
    left.getMonth() === right.getMonth() &&
    left.getDate() === right.getDate()
  );
}

function formatDashboardTime(value: string, language: "zh" | "en") {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  const now = new Date();
  const yesterday = new Date();
  yesterday.setDate(now.getDate() - 1);

  const timePart = date.toLocaleTimeString(language === "zh" ? "zh-CN" : "en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });

  if (isSameDay(date, now)) {
    return language === "zh" ? `今天 ${timePart}` : `Today ${timePart}`;
  }

  if (isSameDay(date, yesterday)) {
    return language === "zh" ? `昨天 ${timePart}` : `Yesterday ${timePart}`;
  }

  return date.toLocaleString(language === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export default function DashboardOverviewPage() {
  const { language } = useLanguage();
  const { toasts, addToast, removeToast } = useToast();
  const [token, setToken] = useState<string | null>(null);
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);
  const [tasks, setTasks] = useState<SignTask[]>([]);
  const [logs, setLogs] = useState<AccountLog[]>([]);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(true);
  const [currentPage, setCurrentPage] = useState(1);
  const [clearingLogs, setClearingLogs] = useState(false);

  const addToastRef = useRef(addToast);

  useEffect(() => {
    addToastRef.current = addToast;
  }, [addToast]);

  const labels = useMemo(() => {
    if (language === "zh") {
      return {
        title: "仪表盘",
        loadFailed: "加载仪表盘失败",
        recentLogs: "最近任务执行日志",
        emptyLogsTitle: "暂无执行日志",
        emptyLogsDesc: "登录账号并运行任务后，这里会显示最近的执行记录。",
        loading: "正在加载仪表盘...",
        activeAccounts: "活跃账号",
        totalTasks: "编排任务",
        todaySuccess: "今日成功",
        failedTasks: "失败告警",
        noDetails: "无详细输出",
        executedAt: "执行时间",
        account: "关联账号",
        task: "任务名称",
        status: "状态",
        output: "最后回复/捕获",
        success: "成功",
        failure: "失败",
        clearLogs: "清空日志",
        clearingLogs: "清空中...",
        clearLogsConfirm: "确认清空全部最近任务执行日志吗？",
        clearLogsSuccess: "最近任务执行日志已清空",
        clearLogsFailed: "清空日志失败",
        previousPage: "上一页",
        nextPage: "下一页",
        pageInfo: "第 {current} / {total} 页",
      };
    }

    return {
      title: "Dashboard",
      loadFailed: "Failed to load dashboard",
      recentLogs: "Recent Task Logs",
      emptyLogsTitle: "No execution logs yet",
      emptyLogsDesc: "Recent task results will appear here after accounts start running tasks.",
      loading: "Loading dashboard...",
      activeAccounts: "Active Accounts",
      totalTasks: "Scheduled Tasks",
      todaySuccess: "Today Success",
      failedTasks: "Failures",
      noDetails: "No details",
      executedAt: "Executed At",
      account: "Account",
      task: "Task",
      status: "Status",
      output: "Latest Output",
      success: "Success",
      failure: "Failure",
      clearLogs: "Clear Logs",
      clearingLogs: "Clearing...",
      clearLogsConfirm: "Clear all recent task logs?",
      clearLogsSuccess: "Recent task logs cleared",
      clearLogsFailed: "Failed to clear logs",
      previousPage: "Previous",
      nextPage: "Next",
      pageInfo: "Page {current} / {total}",
    };
  }, [language]);

  const formatErrorMessage = useCallback((err?: any) => {
    const code = err?.code;
    return code ? `${labels.loadFailed} (${code})` : labels.loadFailed;
  }, [labels.loadFailed]);

  const loadData = useCallback(async (tokenStr: string) => {
    setLoading(true);

    try {
      const [accountsData, tasksData, logsData] = await Promise.all([
        listAccounts(tokenStr),
        listSignTasks(tokenStr),
        getRecentAccountLogs(tokenStr, 200),
      ]);

      const nextAccounts = Array.isArray(accountsData?.accounts) ? accountsData.accounts : [];
      const nextTasks = Array.isArray(tasksData) ? tasksData : [];
      const nextLogs = Array.isArray(logsData) ? logsData : [];

      setAccounts(nextAccounts);
      setTasks(nextTasks);
      setLogs(nextLogs);
    } catch (err: any) {
      addToastRef.current(formatErrorMessage(err), "error");
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

    setToken(tokenStr);
    setChecking(false);
    loadData(tokenStr);
  }, [loadData]);

  const activeAccountCount = useMemo(() => {
    return accounts.filter((account) => !account.needs_relogin && account.status !== "invalid" && account.status !== "not_found").length;
  }, [accounts]);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(logs.length / LOGS_PER_PAGE)),
    [logs.length],
  );

  const recentLogs = useMemo(() => {
    const start = (currentPage - 1) * LOGS_PER_PAGE;
    return logs.slice(start, start + LOGS_PER_PAGE);
  }, [currentPage, logs]);

  const todayMetrics = useMemo(() => {
    const start = new Date();
    start.setHours(0, 0, 0, 0);

    const todayLogs = logs.filter((log) => {
      const time = new Date(log.created_at).getTime();
      return !Number.isNaN(time) && time >= start.getTime();
    });

    return {
      success: todayLogs.filter((log) => log.success).length,
      failure: todayLogs.filter((log) => !log.success).length,
    };
  }, [logs]);

  useEffect(() => {
    setCurrentPage((prev) => Math.min(prev, totalPages));
  }, [totalPages]);

  const handleClearLogs = useCallback(async () => {
    if (!token || !logs.length) {
      return;
    }
    if (!confirm(labels.clearLogsConfirm)) {
      return;
    }

    try {
      setClearingLogs(true);
      await clearRecentAccountLogs(token);
      setLogs([]);
      setCurrentPage(1);
      addToast(labels.clearLogsSuccess, "success");
      await loadData(token);
    } catch (err: any) {
      const code = err?.code;
      addToast(code ? `${labels.clearLogsFailed} (${code})` : labels.clearLogsFailed, "error");
    } finally {
      setClearingLogs(false);
    }
  }, [
    addToast,
    labels.clearLogsConfirm,
    labels.clearLogsFailed,
    labels.clearLogsSuccess,
    loadData,
    logs.length,
    token,
  ]);

  if (!token || checking) {
    return null;
  }

  return (
    <>
      <DashboardShell title={labels.title} activeNav="dashboard">
        <div className="space-y-8">
          <div className="grid grid-cols-2 gap-3 md:gap-4 lg:grid-cols-4">
            <div className="glass-panel demo-stat-card">
              <div className="demo-stat-label">
                <UsersThree weight="fill" size={18} />
                <span>{labels.activeAccounts}</span>
              </div>
              <div className="demo-stat-value">
                {activeAccountCount}
                <span className="demo-stat-subvalue">/ {accounts.length}</span>
              </div>
            </div>

            <div className="glass-panel demo-stat-card">
              <div className="demo-stat-label">
                <ListChecks weight="fill" size={18} />
                <span>{labels.totalTasks}</span>
              </div>
              <div className="demo-stat-value">{tasks.length}</div>
            </div>

            <div className="glass-panel demo-stat-card">
              <div className="demo-stat-label">
                <CheckCircle weight="bold" size={18} />
                <span>{labels.todaySuccess}</span>
              </div>
              <div className="demo-stat-value !text-emerald-500">{todayMetrics.success}</div>
            </div>

            <div className="glass-panel demo-stat-card">
              <div className="demo-stat-label">
                <WarningCircle weight="fill" size={18} />
                <span>{labels.failedTasks}</span>
              </div>
              <div className="demo-stat-value !text-rose-500">{todayMetrics.failure}</div>
            </div>
          </div>

          <div className="glass-panel overflow-hidden">
            <div className="demo-table-header flex items-center justify-between gap-4">
              <span>{labels.recentLogs}</span>
              <button
                type="button"
                onClick={handleClearLogs}
                disabled={clearingLogs || logs.length === 0}
                className="inline-flex items-center rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 transition-colors hover:border-rose-200 hover:bg-rose-50 hover:text-rose-600 disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700 dark:text-slate-200 dark:hover:border-rose-500/40 dark:hover:bg-rose-500/10 dark:hover:text-rose-300"
              >
                {clearingLogs ? labels.clearingLogs : labels.clearLogs}
              </button>
            </div>

            {loading && logs.length === 0 ? (
              <div className="flex flex-col items-center justify-center px-6 py-24 text-main/35">
                <Spinner className="mb-4 animate-spin" size={30} />
                <div>{labels.loading}</div>
              </div>
            ) : recentLogs.length === 0 ? (
              <div className="px-6 py-20 text-center">
                <div className="text-base font-semibold text-main/75">{labels.emptyLogsTitle}</div>
                <div className="mt-2 text-sm text-main/45">{labels.emptyLogsDesc}</div>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="demo-table min-w-[980px]">
                  <thead>
                    <tr>
                      <th>{labels.executedAt}</th>
                      <th>{labels.account}</th>
                      <th>{labels.task}</th>
                      <th>{labels.status}</th>
                      <th>{labels.output}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recentLogs.map((log) => {
                      const summary = log.bot_message || log.summary || log.message || labels.noDetails;
                      return (
                        <tr key={log.id}>
                          <td>{formatDashboardTime(log.created_at, language)}</td>
                          <td className="font-mono text-[13px] text-main/80">{log.account_name}</td>
                          <td className="font-semibold">{log.task_name}</td>
                          <td>
                            <span
                              className={`demo-pill ${
                                log.success
                                  ? "bg-emerald-100 text-emerald-700"
                                  : "bg-rose-100 text-rose-600"
                              }`}
                            >
                              {log.success ? labels.success : labels.failure}
                            </span>
                          </td>
                          <td className={log.success ? "text-main/78" : "text-rose-500"}>
                            <div className="max-w-[420px] truncate" title={summary}>
                              {summary}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
                <div className="flex items-center justify-between gap-3 border-t border-slate-200 px-6 py-4 text-sm text-main/65 dark:border-white/10">
                  <span>
                    {labels.pageInfo
                      .replace("{current}", String(currentPage))
                      .replace("{total}", String(totalPages))}
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => setCurrentPage((prev) => Math.max(1, prev - 1))}
                      disabled={currentPage <= 1}
                      className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 transition-colors hover:border-[#2AABEE] hover:text-[#2AABEE] disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700 dark:text-slate-200 dark:hover:border-[#2AABEE] dark:hover:text-[#69c8ff]"
                    >
                      {labels.previousPage}
                    </button>
                    <button
                      type="button"
                      onClick={() => setCurrentPage((prev) => Math.min(totalPages, prev + 1))}
                      disabled={currentPage >= totalPages}
                      className="rounded-lg border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 transition-colors hover:border-[#2AABEE] hover:text-[#2AABEE] disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700 dark:text-slate-200 dark:hover:border-[#2AABEE] dark:hover:text-[#69c8ff]"
                    >
                      {labels.nextPage}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </DashboardShell>

      <ToastContainer toasts={toasts} removeToast={removeToast} />
    </>
  );
}
