"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  Broadcast,
  Lightning,
  ListDashes,
  PencilSimple,
  Play,
  Plus,
  Spinner,
  Trash,
} from "@phosphor-icons/react";
import { getToken } from "../../../lib/auth";
import {
  deleteSignTask,
  getSignTaskRunStatus,
  getSignTaskHistory,
  listSignTasks,
  startSignTaskRun,
  type SignTask,
  type SignTaskHistoryItem,
} from "../../../lib/api";
import { DashboardShell } from "../../../components/dashboard-shell";
import { DialogShell } from "../../../components/dialog-shell";
import { PageLoader } from "../../../components/page-loader";
import { TaskLogView } from "../../../components/task-log-view";
import { ToastContainer, useToast } from "../../../components/ui/toast";
import { useLanguage } from "../../../context/LanguageContext";
import { normalizeFlowLogLines } from "../../../lib/task-log-format";
import { CreateSignTaskContent } from "./create/create-sign-task-content";

type RunPhase = "running" | "finalizing" | "done";

function sleep(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export default function SignTasksPage() {
  const { t, language } = useLanguage();
  const { toasts, addToast, removeToast } = useToast();
  const searchParams = useSearchParams();
  const [token, setToken] = useState<string | null>(null);
  const [tasks, setTasks] = useState<SignTask[]>([]);
  const [loading, setLoading] = useState(false);
  const [checking, setChecking] = useState(true);
  const [showCreateDialog, setShowCreateDialog] = useState(false);
  const [notifyOnFailure, setNotifyOnFailure] = useState(true);
  const [editingTask, setEditingTask] = useState<SignTask | null>(null);
  const [editNotifyOnFailure, setEditNotifyOnFailure] = useState(true);
  const [runningTask, setRunningTask] = useState<string | null>(null);
  const [runLogs, setRunLogs] = useState<string[]>([]);
  const [isDone, setIsDone] = useState(false);
  const [runPhase, setRunPhase] = useState<RunPhase>("running");
  const [runOutcome, setRunOutcome] = useState<"success" | "error" | null>(null);
  const [historyTask, setHistoryTask] = useState<SignTask | null>(null);
  const [historyLogs, setHistoryLogs] = useState<SignTaskHistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const runSocketRef = useRef<WebSocket | null>(null);

  const addToastRef = useRef(addToast);
  const tRef = useRef(t);

  useEffect(() => {
    addToastRef.current = addToast;
    tRef.current = t;
  }, [addToast, t]);

  useEffect(() => {
    return () => {
      runSocketRef.current?.close();
      runSocketRef.current = null;
    };
  }, []);

  const formatErrorMessage = useCallback((key: string, err?: any) => {
    const base = tRef.current(key);
    const detail =
      typeof err?.message === "string" ? String(err.message).trim() : "";
    const code = err?.code;
    if (detail) {
      return code ? `${base}: ${detail} (${code})` : `${base}: ${detail}`;
    }
    return code ? `${base} (${code})` : base;
  }, []);

  const normalizeRunOutput = useCallback((output?: string, error?: string) => {
    const source = typeof output === "string" && output.trim() ? output : error || "";
    return normalizeFlowLogLines(source.split(/\r?\n/));
  }, []);

  const mergeRunLogLines = useCallback((prev: string[], next: string[]) => {
    if (!next.length) {
      return prev;
    }
    if (!prev.length) {
      return next;
    }
    const merged = [...prev];
    for (const line of next) {
      if (!line || merged.includes(line)) {
        continue;
      }
      merged.push(line);
    }
    return merged;
  }, []);

  const getTaskAccounts = useCallback(
    (task: SignTask) =>
      (
        task.account_names && task.account_names.length > 0
          ? task.account_names
          : [task.account_name]
      ).filter(Boolean),
    [],
  );

  const getTaskScheduleLabel = useCallback(
    (task: SignTask) => {
      if ((task.execution_mode as string) === "listen") {
        return language === "zh" ? "常驻监听 (24H)" : "Always Listening (24H)";
      }
      if (task.execution_mode === "range" && task.range_start && task.range_end) {
        return `${language === "zh" ? "按时执行" : "Scheduled"} (${task.range_start}-${task.range_end})`;
      }
      return `${language === "zh" ? "按时执行" : "Scheduled"} (${task.sign_at})`;
    },
    [language],
  );

  const getTaskTargetLabel = useCallback(
    (task: SignTask) => {
      const chat = task.chats?.[0];
      if (!chat) {
        return t("no_data");
      }

      const chatIdLabel =
        chat.chat_id !== undefined && chat.chat_id !== null
          ? String(chat.chat_id)
          : chat.name || t("no_data");
      const topicId = chat.message_thread_id;

      if (topicId === undefined || topicId === null) {
        return chatIdLabel;
      }

      return `${chatIdLabel}|${topicId}`;
    },
    [t],
  );

  const loadData = useCallback(
    async (tokenStr: string) => {
      try {
        setLoading(true);
        const tasksData = await listSignTasks(tokenStr);
        setTasks(tasksData);
      } catch (err: any) {
        addToastRef.current(formatErrorMessage("load_failed", err), "error");
      } finally {
        setLoading(false);
      }
    },
    [formatErrorMessage],
  );

  useEffect(() => {
    const tokenStr = getToken();
    if (!tokenStr) {
      window.location.replace("/");
      return;
    }
    setToken(tokenStr);
    setChecking(false);
    void loadData(tokenStr);
  }, [loadData]);

  const handleDelete = async (task: SignTask) => {
    if (!token) return;
    if (!confirm(t("confirm_delete"))) return;

    try {
      setLoading(true);
      await deleteSignTask(token, task.name, task.account_name);
      addToast(t("task_deleted").replace("{name}", task.name), "success");
      await loadData(token);
    } catch (err: any) {
      addToast(formatErrorMessage("delete_failed", err), "error");
    } finally {
      setLoading(false);
    }
  };

  const handleRun = async (task: SignTask) => {
    if (!token) return;
    if ((task.execution_mode as string) === "listen") {
      addToast(
        language === "zh" ? "常驻监听任务创建后会自动运行" : "Listen tasks start automatically after saving",
        "success",
      );
      return;
    }

    const taskAccounts = getTaskAccounts(task);
    const accountName =
      taskAccounts.length === 1
        ? taskAccounts[0]
        : prompt(
            `${t("account_name_prompt")}\n${taskAccounts.join(", ")}`,
            taskAccounts[0] || "",
          );

    if (!accountName) return;
    if (!taskAccounts.includes(accountName)) {
      addToast(
        language === "zh"
          ? "请输入任务已关联的账号名称"
          : "Enter one of the linked account names",
        "error",
      );
      return;
    }

    try {
      setLoading(true);
      setRunningTask(task.name);
      setRunLogs([]);
      setIsDone(false);
      setRunPhase("running");
      setRunOutcome(null);
      runSocketRef.current?.close();
      runSocketRef.current = null;

      const finalizeRunResult = (result: {
        success?: boolean | null;
        output?: string;
        error?: string;
      }) => {
        const ok = Boolean(result.success);
        const finalLogs = normalizeRunOutput(result.output, result.error);
        const failureSummary =
          ok || !result.error
            ? []
            : [
                language === "zh"
                  ? `任务最终状态: 失败 - ${result.error}`
                  : `Final status: failed - ${result.error}`,
              ];
        setRunLogs((prev) =>
          mergeRunLogLines(prev, [...finalLogs, ...failureSummary]),
        );
        setIsDone(true);
        setRunPhase("done");
        setRunOutcome(ok ? "success" : "error");
        return ok;
      };

      const startedRun = await startSignTaskRun(token, task.name, accountName);
      const runId = String(startedRun.run_id || "").trim();

      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const host = window.location.host;
      const wsParams = new URLSearchParams({
        token,
        account_name: accountName,
      });
      const ws = new WebSocket(
        `${protocol}//${host}/api/sign-tasks/ws/${encodeURIComponent(task.name)}?${wsParams.toString()}`,
      );
      runSocketRef.current = ws;

      ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "logs") {
          const nextLogs = normalizeFlowLogLines(
            Array.isArray(data.data) ? data.data : [],
          );
          setRunLogs((prev) => mergeRunLogLines(prev, nextLogs));
        } else if (data.type === "done") {
          setRunPhase((prev) => (prev === "done" ? prev : "finalizing"));
          ws.close();
        }
      };

      ws.onerror = () => {
        setRunLogs((prev) =>
          prev.length > 0
            ? prev
            : [
                language === "zh"
                  ? "实时日志连接失败，任务完成后将显示最终日志。"
                  : "Live log connection failed. Final logs will be shown after completion.",
              ],
        );
      };

      ws.onclose = () => {
        if (runSocketRef.current === ws) {
          runSocketRef.current = null;
        }
      };

      let finalStatus = startedRun;
      const maxPollCount = 900;
      for (let attempt = 0; attempt < maxPollCount; attempt += 1) {
        const status = await getSignTaskRunStatus(
          token,
          task.name,
          accountName,
          runId || undefined,
        );
        finalStatus = status;
        if (status.state === "finished") {
          break;
        }
        if (status.state === "stale") {
          throw new Error(
            language === "zh"
              ? "任务运行状态已失效，请重新运行"
              : "Run status became stale. Please retry.",
          );
        }
        await sleep(1000);
      }

      if (finalStatus.state !== "finished") {
        throw new Error(
          language === "zh"
            ? "等待任务最终状态超时，请稍后查看历史日志"
            : "Timed out waiting for final task status. Check history logs shortly.",
        );
      }

      const succeeded = finalizeRunResult(finalStatus);
      ws.close();
      if (succeeded) {
        setRunOutcome("success");
        addToast(t("task_run_success").replace("{name}", task.name), "success");
        await loadData(token);
      } else {
        setRunOutcome("error");
        addToast(finalStatus.error || t("task_run_failed"), "error");
        await loadData(token);
      }
    } catch (err: any) {
      const detail =
        typeof err?.message === "string" && err.message.trim()
          ? err.message.trim()
          : t("task_run_failed");
      setRunLogs((prev) =>
        mergeRunLogLines(prev, [
          language === "zh"
            ? `任务最终状态: 失败 - ${detail}`
            : `Final status: failed - ${detail}`,
        ]),
      );
      setIsDone(true);
      setRunPhase("done");
      setRunOutcome("error");
      addToast(formatErrorMessage("task_run_failed", err), "error");
      runSocketRef.current?.close();
      runSocketRef.current = null;
      await loadData(token);
    } finally {
      setLoading(false);
    }
  };

  const closeRunDialog = useCallback(() => {
    runSocketRef.current?.close();
    runSocketRef.current = null;
    setRunLogs([]);
    setIsDone(false);
    setRunPhase("running");
    setRunOutcome(null);
    setRunningTask(null);
  }, []);

  const handleShowTaskHistory = async (task: SignTask) => {
    if (!token) return;
    setHistoryTask(task);
    setHistoryLogs([]);
    setHistoryLoading(true);

    try {
      const taskAccounts = getTaskAccounts(task);
      const logs = await getSignTaskHistory(
        token,
        task.name,
        taskAccounts.length === 1 ? taskAccounts[0] : undefined,
        30,
      );
      setHistoryLogs(
        logs.map((item) => ({
          ...item,
          flow_logs: normalizeFlowLogLines(item.flow_logs || []),
        })),
      );
    } catch (err: any) {
      addToast(formatErrorMessage("logs_fetch_failed", err), "error");
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleEdit = (task: SignTask) => {
    setEditNotifyOnFailure(Boolean(task.notify_on_failure ?? true));
    setEditingTask(task);
  };

  const accountFilter = (searchParams.get("account") || "").trim();
  const visibleTasks = accountFilter
    ? tasks.filter((task) => getTaskAccounts(task).includes(accountFilter))
    : tasks;
  const mobileTaskActionButtonClass =
    "inline-flex items-center gap-2 whitespace-nowrap rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-medium text-slate-600 transition-colors hover:border-[#2AABEE] hover:text-[#2AABEE] disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-200 dark:hover:border-[#2AABEE] dark:hover:text-[#69c8ff]";
  const desktopTaskActionButtonClass =
    "inline-flex h-10 w-10 items-center justify-center rounded-lg border border-slate-200 bg-slate-50 text-slate-600 transition-colors hover:border-[#2AABEE] hover:text-[#2AABEE] disabled:cursor-not-allowed disabled:opacity-40 dark:border-slate-700 dark:bg-slate-900/70 dark:text-slate-200 dark:hover:border-[#2AABEE] dark:hover:text-[#69c8ff]";
  const runStatusText = isDone
    ? runOutcome === "error"
      ? language === "zh"
        ? "执行失败"
        : "Failed"
      : language === "zh"
        ? "执行完成"
        : "Completed"
    : runPhase === "finalizing"
      ? language === "zh"
        ? "正在收尾..."
        : "Finalizing..."
      : t("task_executing");
  const runStatusClass = isDone
    ? runOutcome === "error"
      ? "text-rose-500 dark:text-rose-300"
      : "text-emerald-600 dark:text-emerald-300"
    : "text-[#2AABEE]";

  if (!token || checking) {
    return null;
  }

  return (
    <>
      <DashboardShell title={language === "zh" ? "任务编排" : "Tasks"} activeNav="tasks">
        <div className="space-y-3">
          {loading && visibleTasks.length === 0 ? (
            <PageLoader label={t("loading")} />
          ) : visibleTasks.length === 0 ? (
            <div className="glass-panel demo-simple-empty">
              {language === "zh" ? "暂无任务" : "No tasks"}
            </div>
          ) : (
            visibleTasks.map((task) => (
              <div
                key={task.task_group_id || `${task.name}-${task.account_name}`}
                className="glass-panel px-4 py-4 sm:px-5"
              >
                {(() => {
                  const isListenTask = (task.execution_mode as string) === "listen";
                  const TaskIcon = isListenTask ? Broadcast : Lightning;
                  const iconClass = isListenTask
                    ? "flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-emerald-200 bg-emerald-50 text-emerald-600 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300"
                    : "flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-sky-200 bg-sky-50 text-sky-600 dark:border-sky-500/20 dark:bg-sky-500/10 dark:text-sky-300";
                  const chipClass = isListenTask
                    ? "inline-flex items-center rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300"
                    : "inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold text-slate-700 dark:border-slate-700 dark:bg-slate-900/80 dark:text-slate-200";
                  const runLabel = language === "zh" ? "运行" : t("run");
                  const logsLabel = language === "zh" ? "日志" : t("task_history_logs");
                  const targetLabel = getTaskTargetLabel(task);

                  return (
                    <>
                      <div className="flex flex-col gap-3 md:hidden">
                        <div className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-x-3 gap-y-2">
                          <div className={`${iconClass} row-span-2 self-start`}>
                            <TaskIcon weight="fill" size={20} />
                          </div>

                          <div
                            className="min-w-0 truncate text-base font-bold text-slate-900 dark:text-slate-100"
                            title={task.name}
                          >
                            {task.name}
                          </div>
                          <div className="min-w-0 flex flex-wrap items-center gap-2">
                            <span className={chipClass}>{getTaskScheduleLabel(task)}</span>
                            <span
                              className={`${chipClass} max-w-full font-mono`}
                              title={targetLabel}
                            >
                              {targetLabel}
                            </span>
                          </div>
                        </div>

                        <div
                          className={`grid gap-2 border-t border-slate-200/80 pt-3 dark:border-slate-800 ${
                            isListenTask ? "grid-cols-3" : "grid-cols-4"
                          }`}
                        >
                          {isListenTask ? null : (
                            <button
                              type="button"
                              onClick={() => handleRun(task)}
                              disabled={loading}
                              className={`${mobileTaskActionButtonClass} w-full justify-center px-2.5 border-emerald-200 bg-emerald-50 text-emerald-700 hover:border-emerald-300 hover:text-emerald-800 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300 dark:hover:border-emerald-400/40 dark:hover:text-emerald-200`}
                              title={t("run")}
                            >
                              <Play weight="fill" size={16} />
                              <span>{runLabel}</span>
                            </button>
                          )}

                          <button
                            type="button"
                            onClick={() => handleShowTaskHistory(task)}
                            disabled={loading}
                            className={`${mobileTaskActionButtonClass} w-full justify-center px-2.5`}
                            title={t("task_history_logs")}
                          >
                            <ListDashes weight="bold" size={16} />
                            <span>{logsLabel}</span>
                          </button>

                          <button
                            type="button"
                            onClick={() => handleEdit(task)}
                            disabled={loading}
                            className={`${mobileTaskActionButtonClass} w-full justify-center px-2.5`}
                            title={t("edit")}
                          >
                            <PencilSimple weight="bold" size={16} />
                            <span>{t("edit")}</span>
                          </button>

                          <button
                            type="button"
                            onClick={() => handleDelete(task)}
                            disabled={loading}
                            className={`${mobileTaskActionButtonClass} w-full justify-center px-2.5 border-rose-200 bg-rose-50 text-rose-700 hover:border-rose-300 hover:text-rose-800 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-300 dark:hover:border-rose-400/40 dark:hover:text-rose-200`}
                            title={t("delete")}
                          >
                            <Trash weight="bold" size={16} />
                            <span>{t("delete")}</span>
                          </button>
                        </div>
                      </div>

                      <div className="hidden md:grid md:grid-cols-[auto_minmax(0,1fr)_auto] md:items-center md:gap-4">
                        <div className={iconClass}>
                          <TaskIcon weight="fill" size={20} />
                        </div>

                        <div className="min-w-0">
                          <div
                            className="truncate text-base font-bold text-slate-900 dark:text-slate-100"
                            title={task.name}
                          >
                            {task.name}
                          </div>
                          <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
                            <span className={chipClass}>{getTaskScheduleLabel(task)}</span>
                            <span className={`${chipClass} font-mono`} title={targetLabel}>
                              {targetLabel}
                            </span>
                          </div>
                        </div>

                        <div className="flex flex-wrap items-center justify-end gap-2">
                          {isListenTask ? null : (
                            <button
                              type="button"
                              onClick={() => handleRun(task)}
                              disabled={loading}
                              className={`${desktopTaskActionButtonClass} border-emerald-200 bg-emerald-50 text-emerald-700 hover:border-emerald-300 hover:text-emerald-800 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300 dark:hover:border-emerald-400/40 dark:hover:text-emerald-200`}
                              title={t("run")}
                            >
                              <Play weight="fill" size={16} />
                            </button>
                          )}

                          <button
                            type="button"
                            onClick={() => handleShowTaskHistory(task)}
                            disabled={loading}
                            className={desktopTaskActionButtonClass}
                            title={t("task_history_logs")}
                          >
                            <ListDashes weight="bold" size={16} />
                          </button>

                          <button
                            type="button"
                            onClick={() => handleEdit(task)}
                            disabled={loading}
                            className={desktopTaskActionButtonClass}
                            title={t("edit")}
                          >
                            <PencilSimple weight="bold" size={16} />
                          </button>

                          <button
                            type="button"
                            onClick={() => handleDelete(task)}
                            disabled={loading}
                            className={`${desktopTaskActionButtonClass} border-rose-200 bg-rose-50 text-rose-700 hover:border-rose-300 hover:text-rose-800 dark:border-rose-500/20 dark:bg-rose-500/10 dark:text-rose-300 dark:hover:border-rose-400/40 dark:hover:text-rose-200`}
                            title={t("delete")}
                          >
                            <Trash weight="bold" size={16} />
                          </button>
                        </div>
                      </div>
                    </>
                  );
                })()}
              </div>
            ))
          )}
        </div>
      </DashboardShell>

      <button
        type="button"
        onClick={() => {
          setNotifyOnFailure(true);
          setShowCreateDialog(true);
        }}
        className="floating-fab"
        title={language === "zh" ? "创建任务" : t("add_task")}
      >
        <Plus weight="bold" size={24} />
      </button>

      {showCreateDialog ? (
        <DialogShell
          title={language === "zh" ? "创建任务" : t("add_task")}
          icon={Lightning}
          size="3xl"
          panelClassName="h-[820px] max-h-[calc(100vh-40px)] max-w-[1120px]"
          bodyClassName="!min-h-0 !overflow-hidden !p-0"
          bodyScrollable={false}
          headerExtras={
            <label className="mb-0 ml-2 inline-flex items-center gap-2 text-sm font-medium text-main/75">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-slate-300 text-[#2AABEE] focus:ring-[#2AABEE]"
                checked={notifyOnFailure}
                onChange={(e) => setNotifyOnFailure(e.target.checked)}
              />
              <span>{language === "zh" ? "失败通知" : "Failure Notify"}</span>
            </label>
          }
          onClose={() => setShowCreateDialog(false)}
        >
          <CreateSignTaskContent
            compact
            token={token}
            notifyOnFailure={notifyOnFailure}
            onNotifyOnFailureChange={setNotifyOnFailure}
            showInlineNotifyToggle={false}
            onCancel={() => setShowCreateDialog(false)}
            onSuccess={async () => {
              setShowCreateDialog(false);
              await loadData(token);
            }}
          />
        </DialogShell>
      ) : null}

      {editingTask ? (
        <DialogShell
          title={language === "zh" ? "编辑任务" : t("edit")}
          icon={Lightning}
          size="3xl"
          panelClassName="h-[820px] max-h-[calc(100vh-40px)] max-w-[1120px]"
          bodyClassName="!min-h-0 !overflow-hidden !p-0"
          bodyScrollable={false}
          headerExtras={
            <label className="mb-0 ml-2 inline-flex items-center gap-2 text-sm font-medium text-main/75">
              <input
                type="checkbox"
                className="h-4 w-4 rounded border-slate-300 text-[#2AABEE] focus:ring-[#2AABEE]"
                checked={editNotifyOnFailure}
                onChange={(e) => setEditNotifyOnFailure(e.target.checked)}
              />
              <span>{language === "zh" ? "失败通知" : "Failure Notify"}</span>
            </label>
          }
          onClose={() => setEditingTask(null)}
        >
          <CreateSignTaskContent
            compact
            mode="edit"
            initialTask={editingTask}
            token={token}
            notifyOnFailure={editNotifyOnFailure}
            onNotifyOnFailureChange={setEditNotifyOnFailure}
            showInlineNotifyToggle={false}
            onCancel={() => setEditingTask(null)}
            onSuccess={async () => {
              setEditingTask(null);
              await loadData(token);
            }}
          />
        </DialogShell>
      ) : null}

      {runningTask ? (
        <DialogShell
          title={t("task_run_logs_title").replace("{name}", runningTask)}
          icon={Lightning}
          size="lg"
          panelClassName="h-[500px]"
          onClose={isDone ? closeRunDialog : undefined}
          bodyClassName="bg-black/20 font-mono text-[11px] leading-relaxed"
          footer={
            <div
              className={`flex items-center gap-3 ${isDone ? "justify-between" : "justify-end"}`}
            >
              {isDone ? (
                <span
                  className={`shrink-0 whitespace-nowrap text-xs font-semibold ${runStatusClass}`}
                >
                  {runStatusText}
                </span>
              ) : null}
              <button
                type="button"
                onClick={closeRunDialog}
                disabled={!isDone}
                className={`inline-flex min-w-[112px] shrink-0 items-center justify-center whitespace-nowrap rounded-xl px-5 py-2 text-xs font-bold transition-all ${
                  isDone
                    ? "btn-gradient !w-auto"
                    : "cursor-not-allowed border border-white/10 bg-white/5 text-main/20"
                }`}
              >
                {isDone ? t("close") : runStatusText}
              </button>
            </div>
          }
        >
          {runLogs.length === 0 ? (
            <div className="flex items-center gap-2 text-main/30 italic">
              <Spinner className="animate-spin" size={12} />
              {t("logs_waiting")}
            </div>
          ) : (
            <div className="space-y-2">
              <TaskLogView
                lines={runLogs}
                lastTargetLabel={language === "zh" ? "任务对象最后消息" : "Last Target Message"}
              />
              {!isDone ? (
                <div className="mt-2 flex items-center gap-2 italic text-[#2AABEE]">
                  <Spinner className="animate-spin" size={12} />
                  {runPhase === "finalizing"
                    ? language === "zh"
                      ? "正在收尾并同步最终结果..."
                      : "Finalizing and syncing final result..."
                    : t("task_running")}
                </div>
              ) : null}
            </div>
          )}
        </DialogShell>
      ) : null}

      {historyTask ? (
        <DialogShell
          title={t("task_history_logs_title").replace("{name}", historyTask.name)}
          icon={ListDashes}
          size="2xl"
          panelClassName="h-[78vh]"
          onClose={() => setHistoryTask(null)}
          bodyClassName="bg-black/20 font-mono text-[11px] leading-relaxed"
        >
          {historyLoading ? (
            <div className="flex items-center gap-2 text-main/30 italic">
              <Spinner className="animate-spin" size={12} />
              {t("loading")}
            </div>
          ) : historyLogs.length === 0 ? (
            <div className="text-main/30 italic">{t("task_history_empty")}</div>
          ) : (
            <div className="space-y-4">
              {historyLogs.map((log, index) => (
                <div
                  key={`${log.time}-${index}`}
                  className="overflow-hidden rounded-xl border border-white/5 bg-white/5"
                >
                  <div className="flex items-center justify-between border-b border-white/5 px-3 py-2 text-[10px]">
                    <div className="flex items-center gap-2 text-main/30">
                      <span>
                        {new Date(log.time).toLocaleString(
                          language === "zh" ? "zh-CN" : "en-US",
                        )}
                      </span>
                      {log.account_name ? (
                        <span className="inline-flex rounded-full border border-[#2AABEE]/20 bg-[#2AABEE]/10 px-2 py-0.5 text-[9px] font-medium text-[#2AABEE]">
                          {log.account_name}
                        </span>
                      ) : null}
                    </div>
                    <span className={log.success ? "text-emerald-400" : "text-rose-400"}>
                      {log.success ? t("success") : t("failure")}
                    </span>
                  </div>
                  <div className="space-y-1 p-3">
                    <TaskLogView
                      lines={log.flow_logs}
                      lastTargetMessage={log.last_target_message}
                      lastTargetLabel={language === "zh" ? "任务对象最后消息" : "Last Target Message"}
                      fallbackText={log.message || t("task_history_no_flow")}
                    />
                    {log.flow_truncated ? (
                      <div className="mt-2 text-[10px] text-amber-400/90">
                        {t("task_history_truncated").replace(
                          "{count}",
                          String(log.flow_line_count || 0),
                        )}
                      </div>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          )}
        </DialogShell>
      ) : null}

      <ToastContainer toasts={toasts} removeToast={removeToast} />
    </>
  );
}
