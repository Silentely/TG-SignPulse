"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import {
  CaretDown,
  Check,
  DotsSixVertical,
  ListNumbers,
  Plus,
  Spinner,
  Trash,
} from "@phosphor-icons/react";
import { getToken } from "../../../../lib/auth";
import {
  createSignTask,
  getAccountChats,
  listAccounts,
  searchAccountChats,
  type AccountInfo,
  type ChatInfo,
  type SignTask,
  updateSignTask,
} from "../../../../lib/api";
import { ToastContainer, useToast } from "../../../../components/ui/toast";
import { useLanguage } from "../../../../context/LanguageContext";

type CreateSignTaskContentProps = {
  compact?: boolean;
  mode?: "create" | "edit";
  initialTask?: SignTask | null;
  onCancel?: () => void;
  onSuccess?: () => void;
  token?: string | null;
  notifyOnFailure?: boolean;
  onNotifyOnFailureChange?: (nextValue: boolean) => void;
  showInlineNotifyToggle?: boolean;
};

type ScheduleMode = "scheduled" | "listen";
type MatchMode = "contains" | "exact" | "regex";
type ListenerPushChannel = "continue" | "telegram" | "forward" | "bark" | "custom";
type SequenceActionType =
  | "send_text"
  | "click_text_button"
  | "vision_send"
  | "vision_click"
  | "calc_send"
  | "calc_click"
  | "delay";

type SequenceActionItem = {
  id: string;
  type: SequenceActionType;
  value: string;
  aiPrompt: string;
};

const TIME_RANGE_PATTERN = /^(\d{2}:\d{2}(?::\d{2})?)(-(\d{2}:\d{2}(?::\d{2})?))?$/;
const DELAY_PATTERN = /^\d+(?:\.\d+)?(?:-\d+(?:\.\d+)?)?$/;
const INVALID_TASK_NAME_PATTERN = /[<>:"/\\|?*\u0000-\u001f]+/g;

function createActionId() {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function createSequenceAction(
  type: SequenceActionType = "send_text",
  value = "",
  aiPrompt = "",
): SequenceActionItem {
  return { id: createActionId(), type, value, aiPrompt };
}

function isAISequenceActionType(type: SequenceActionType) {
  return (
    type === "vision_send" ||
    type === "vision_click" ||
    type === "calc_send" ||
    type === "calc_click"
  );
}

function sanitizeTaskName(raw: string) {
  const cleaned = raw
    .trim()
    .replace(INVALID_TASK_NAME_PATTERN, " ")
    .replace(/\s+/g, " ")
    .replace(/[ .]+$/g, "")
    .slice(0, 64);
  if (!cleaned || cleaned === "." || cleaned === "..") {
    return "";
  }
  return cleaned;
}

function stripBotPrefix(value: string) {
  return String(value || "").replace(/^\s*🤖\s*/, "").trim();
}

function getChatDisplayName(
  chat?: Partial<ChatInfo> & {
    chat_id?: number;
    name?: string;
  },
) {
  const raw =
    chat?.title ??
    chat?.name ??
    chat?.username ??
    (chat?.id !== undefined ? String(chat.id) : undefined) ??
    (chat?.chat_id !== undefined ? String(chat.chat_id) : "");
  return stripBotPrefix(String(raw || "").trim());
}

function splitKeywordInput(value: string, matchMode: MatchMode) {
  const splitter = matchMode === "regex" ? /\n/ : /\n|,/;
  return value
    .split(splitter)
    .map((item) => item.trim())
    .filter(Boolean);
}

type BuildActionResult =
  | { ok: true; actions: Array<Record<string, any>> }
  | { ok: false; message: string };

function buildSequenceActions(
  items: SequenceActionItem[],
  labels: {
    invalidDelay: string;
    emptyDelay: string;
    consecutiveDelay: string;
    trailingDelay: string;
    emptyText: string;
    emptyActions: string;
  },
): BuildActionResult {
  const built: Array<Record<string, any>> = [];
  let pendingDelay = "";

  for (const item of items) {
    if (item.type === "delay") {
      const delayValue = item.value.trim();
      if (!delayValue) {
        return { ok: false, message: labels.emptyDelay };
      }
      if (!DELAY_PATTERN.test(delayValue)) {
        return { ok: false, message: labels.invalidDelay };
      }
      if (pendingDelay) {
        return { ok: false, message: labels.consecutiveDelay };
      }
      pendingDelay = delayValue;
      continue;
    }

    let nextAction: Record<string, any> | null = null;
    if (item.type === "send_text") {
      const text = item.value.trim();
      if (!text) {
        return { ok: false, message: labels.emptyText };
      }
      nextAction = { action: 1, text };
    }
    if (item.type === "click_text_button") {
      const text = item.value.trim();
      if (!text) {
        return { ok: false, message: labels.emptyText };
      }
      nextAction = { action: 3, text };
    }
    if (item.type === "vision_send") {
      nextAction = { action: 6 };
    }
    if (item.type === "vision_click") {
      nextAction = { action: 4 };
    }
    if (item.type === "calc_send") {
      nextAction = { action: 5 };
    }
    if (item.type === "calc_click") {
      nextAction = { action: 7 };
    }

    if (!nextAction) {
      continue;
    }

    if (isAISequenceActionType(item.type)) {
      const aiPrompt = item.aiPrompt.trim();
      if (aiPrompt) {
        nextAction.ai_prompt = aiPrompt;
      }
    }

    if (pendingDelay) {
      nextAction.delay = pendingDelay;
      pendingDelay = "";
    }
    built.push(nextAction);
  }

  if (pendingDelay) {
    return { ok: false, message: labels.trailingDelay };
  }

  if (!built.length) {
    return { ok: false, message: labels.emptyActions };
  }

  return { ok: true, actions: built };
}

function getTaskAccounts(task: SignTask): string[] {
  const rawAccounts =
    task.account_names && task.account_names.length > 0
      ? task.account_names
      : [task.account_name];

  return rawAccounts
    .map((accountName) => String(accountName || "").trim())
    .filter(Boolean);
}

function parseSequenceActions(items: Array<Record<string, any>>): SequenceActionItem[] {
  const parsed: SequenceActionItem[] = [];

  for (const item of items || []) {
    const delayValue = String(item?.delay || "").trim();
    const aiPrompt = String(item?.ai_prompt || "");
    if (delayValue) {
      parsed.push(createSequenceAction("delay", delayValue));
    }

    const actionId = Number(item?.action);
    if (actionId === 1) {
      parsed.push(createSequenceAction("send_text", String(item?.text || "")));
      continue;
    }
    if (actionId === 3) {
      parsed.push(createSequenceAction("click_text_button", String(item?.text || "")));
      continue;
    }
    if (actionId === 4) {
      parsed.push(createSequenceAction("vision_click", "", aiPrompt));
      continue;
    }
    if (actionId === 5) {
      parsed.push(createSequenceAction("calc_send", "", aiPrompt));
      continue;
    }
    if (actionId === 6) {
      parsed.push(createSequenceAction("vision_send", "", aiPrompt));
      continue;
    }
    if (actionId === 7) {
      parsed.push(createSequenceAction("calc_click", "", aiPrompt));
      continue;
    }
  }

  return parsed.length > 0 ? parsed : [createSequenceAction()];
}

export function CreateSignTaskContent({
  compact = false,
  mode = "create",
  initialTask = null,
  onCancel,
  onSuccess,
  token: providedToken = null,
  notifyOnFailure: controlledNotifyOnFailure,
  onNotifyOnFailureChange,
  showInlineNotifyToggle = true,
}: CreateSignTaskContentProps) {
  const router = useRouter();
  const { language } = useLanguage();
  const { toasts, addToast, removeToast } = useToast();
  const isZh = language === "zh";
  const isEditMode = mode === "edit" && Boolean(initialTask);
  const handleCancel = onCancel ?? (() => router.back());

  const [token, setToken] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [taskName, setTaskName] = useState("");
  const [internalNotifyOnFailure, setInternalNotifyOnFailure] = useState(true);
  const [scheduleMode, setScheduleMode] = useState<ScheduleMode>("scheduled");
  const [timeRange, setTimeRange] = useState("08:00-19:00");
  const [accounts, setAccounts] = useState<AccountInfo[]>([]);
  const [selectedAccounts, setSelectedAccounts] = useState<string[]>([]);
  const [accountDropdownOpen, setAccountDropdownOpen] = useState(false);
  const [selectedAccount, setSelectedAccount] = useState("");
  const [availableChats, setAvailableChats] = useState<ChatInfo[]>([]);
  const [refreshingChats, setRefreshingChats] = useState(false);
  const [chatSearch, setChatSearch] = useState("");
  const [chatSearchResults, setChatSearchResults] = useState<ChatInfo[]>([]);
  const [chatSearchLoading, setChatSearchLoading] = useState(false);
  const [selectedChatId, setSelectedChatId] = useState<number>(0);
  const [selectedChatName, setSelectedChatName] = useState("");
  const [messageThreadId, setMessageThreadId] = useState("");
  const [actions, setActions] = useState<SequenceActionItem[]>([createSequenceAction()]);
  const [draggingActionId, setDraggingActionId] = useState<string | null>(null);
  const [listenerKeywords, setListenerKeywords] = useState("");
  const [listenerMatchMode, setListenerMatchMode] = useState<MatchMode>("contains");
  const [listenerPushChannel, setListenerPushChannel] =
    useState<ListenerPushChannel>("continue");
  const [listenerForwardChatId, setListenerForwardChatId] = useState("");
  const [listenerForwardThreadId, setListenerForwardThreadId] = useState("");
  const [listenerBarkUrl, setListenerBarkUrl] = useState("");
  const [listenerCustomUrl, setListenerCustomUrl] = useState("");
  const loadedTokenRef = useRef<string | null>(null);

  const text = useMemo(
    () => ({
      title: isEditMode ? (isZh ? "编辑任务" : "Edit Task") : (isZh ? "创建任务" : "Create Task"),
      notifyOnFailure: isZh ? "失败通知" : "Failure Notify",
      taskName: isZh ? "任务名称" : "Task Name",
      taskNamePlaceholder: isZh ? "留空使用默认名称" : "Leave empty to use default name",
      taskNameReadonly: isZh ? "当前版本暂不支持直接修改任务名称" : "Task rename is not supported in this version",
      linkedAccounts: isZh ? "关联账号" : "Linked Accounts",
      allAccounts: isZh ? "全部账号" : "All Accounts",
      selectAccount: isZh ? "选择账号" : "Select Accounts",
      closeDropdown: isZh ? "收起" : "Close",
      scheduleMode: isZh ? "调度模式" : "Schedule Mode",
      scheduled: isZh ? "按时执行" : "Scheduled",
      listen: isZh ? "常驻监听" : "Always Listening",
      timeRange: isZh ? "时间范围" : "Time Range",
      timePlaceholder: isZh ? "例如 08:00、08:00:08 或 08:00-19:00" : "For example 08:00, 08:00:08, or 08:00-19:00",
      sourceAccount: isZh ? "会话来源账号" : "Source Account",
      searchChat: isZh ? "搜索会话" : "Search Chat",
      searchChatPlaceholder: isZh ? "输入名称 / 用户名 / Chat ID" : "Name / username / Chat ID",
      selectFromList: isZh ? "从列表选择" : "Select from List",
      selectFromListPlaceholder: isZh ? "从列表选择..." : "Select from list...",
      topicId: isZh ? "话题 ID（可选）" : "Topic ID (Optional)",
      topicPlaceholder: isZh ? "留空表示不指定话题" : "Leave blank to use the default thread",
      currentChat: isZh ? "当前会话" : "Current Chat",
      noChatSelected: isZh ? "未选择会话" : "No chat selected",
      refreshList: isZh ? "刷新列表" : "Refresh",
      refreshing: isZh ? "刷新中..." : "Refreshing...",
      targetChat: isZh ? "目标会话设置" : "Target Chat Settings",
      keywordSettings: isZh ? "关键词监听配置" : "Keyword Listener",
      keywordPlaceholder: isZh ? "每行一个关键词，也支持逗号分隔" : "One keyword per line, comma separated also works",
      keywordMatchMode: isZh ? "匹配方式" : "Match Mode",
      matchContains: isZh ? "包含" : "Contains",
      matchExact: isZh ? "完全匹配" : "Exact",
      matchRegex: isZh ? "正则" : "Regex",
      listenerActionMode: isZh ? "命中后行为" : "After Match",
      continueActions: isZh ? "执行动作序列" : "Run Action Sequence",
      telegramNotify: isZh ? "仅发送通知" : "Send Notification Only",
      actionSequence: isZh ? "有序动作序列" : "Ordered Actions",
      continueSequence: isZh ? "命中后动作序列" : "Actions After Match",
      addAction: isZh ? "添加动作" : "Add Action",
      sendText: isZh ? "发送文本消息" : "Send Text Message",
      clickTextButton: isZh ? "点击文字按钮" : "Click Text Button",
      delay: isZh ? "延迟" : "Delay",
      aiVision: isZh ? "AI识图" : "AI Vision",
      aiCalc: isZh ? "AI计算" : "AI Calculate",
      visionSend: isZh ? "识图后发文本" : "Vision -> Send Text",
      visionClick: isZh ? "识图后点按钮" : "Vision -> Click Button",
      calcSend: isZh ? "计算后发文本" : "Math -> Send Text",
      calcClick: isZh ? "计算后点按钮" : "Math -> Click Button",
      aiPromptLabel: isZh ? "AI 提示词（可选）" : "AI Prompt (Optional)",
      aiPromptHint:
        isZh
          ? "留空使用默认提示词；填写后仅作用于当前这个 AI 动作。"
          : "Leave empty to use the default prompt. A custom prompt only applies to this AI action.",
      aiVisionPromptPlaceholder:
        isZh
          ? "可选：自定义识图 system prompt，例如强调诗词填空、按钮顺序或忽略图片 LOGO。"
          : "Optional: custom vision system prompt, e.g. emphasize poem completion, button order, or ignoring logos.",
      aiCalcPromptPlaceholder:
        isZh
          ? "可选：自定义计算/答题 system prompt，例如只返回按钮文字或只输出最终答案。"
          : "Optional: custom math/QA system prompt, e.g. return only the button text or only the final answer.",
      textPlaceholder: isZh ? "发送的文本内容" : "Text to send",
      buttonPlaceholder: isZh ? "输入按钮文字，不要表情" : "Button text to click, no emoji",
      delayPlaceholder: isZh ? "输入 1 或 1-3" : "Use 1 or 1-3",
      noExtraInput: isZh ? "该动作无需额外输入" : "No extra input required",
      cancel: isZh ? "取消" : "Cancel",
      save: isEditMode ? (isZh ? "保存修改" : "Save Changes") : (isZh ? "保存任务" : "Save Task"),
      loadAccountsFailed: isZh ? "加载账号失败" : "Failed to load accounts",
      loadChatsFailed: isZh ? "加载会话失败" : "Failed to load chats",
      searchChatsFailed: isZh ? "搜索会话失败" : "Failed to search chats",
      sessionInvalid: isZh ? "账号登录状态已失效，请重新登录" : "Account session expired. Please log in again.",
      selectLinkedAccountFirst: isZh ? "请先选择关联账号" : "Select an account first",
      createSuccess: isZh ? "任务创建成功" : "Task created successfully",
      createFailed: isZh ? "创建任务失败" : "Failed to create task",
      updateSuccess: isZh ? "任务更新成功" : "Task updated successfully",
      updateFailed: isZh ? "任务更新失败" : "Failed to update task",
      emptyAccount: isZh ? "暂无可用账号" : "No available accounts",
      noSearchResult: isZh ? "没有搜索结果" : "No results",
      searching: isZh ? "搜索中..." : "Searching...",
      invalidTime: isZh ? "请输入有效时间，例如 08:00、08:00:08 或 08:00-19:00" : "Enter a valid time such as 08:00, 08:00:08, or 08:00-19:00",
      selectAccountError: isZh ? "请至少选择一个关联账号" : "Select at least one linked account",
      selectChatError: isZh ? "请选择目标会话" : "Select a target chat",
      emptyKeyword: isZh ? "请输入至少一个关键词" : "Enter at least one keyword",
      invalidDelay: isZh ? "延迟格式无效，请输入 1 或 1-3" : "Invalid delay. Use 1 or 1-3.",
      emptyDelay: isZh ? "延迟动作需要填写延迟值" : "Delay action requires a value.",
      consecutiveDelay: isZh ? "两个延迟动作不能直接相邻" : "Two delay actions cannot be adjacent.",
      trailingDelay: isZh ? "延迟动作后面需要跟一个实际动作" : "Delay must be followed by a real action.",
      emptyActionText: isZh ? "文本动作需要填写内容" : "Text actions require content.",
      emptyActions: isZh ? "请至少添加一个有效动作" : "Add at least one valid action.",
      scheduleAuto24H: isZh ? "24H" : "24H",
      defaultListenName: isZh ? "关键词监听任务" : "Keyword Listener Task",
      defaultTaskNameFallback: isZh ? "未命名任务" : "Untitled Task",
    }),
    [isEditMode, isZh],
  );

  const invalidTaskNameMessage = isZh
    ? "任务名称不能包含 < > : \" / \\ | ? *，且不能以空格或点结尾"
    : "Task name cannot contain < > : \" / \\ | ? * or end with a space or dot";

  const listenerLabels = useMemo(
    () => ({
      forwardNotify: isZh ? "转发到指定会话" : "Forward to Chat",
      barkNotify: "Bark",
      customNotify: isZh ? "自定义推送 URL" : "Custom Push URL",
      forwardChatId: isZh ? "转发 Chat ID" : "Forward Chat ID",
      forwardChatIdPlaceholder: isZh ? "例如 -1001234567890" : "For example -1001234567890",
      forwardThreadId: isZh ? "转发话题 ID（可选）" : "Forward Topic ID (Optional)",
      forwardThreadIdPlaceholder: isZh ? "留空则不指定话题" : "Leave blank to skip topic",
      barkUrl: isZh ? "Bark URL" : "Bark URL",
      barkUrlPlaceholder: isZh ? "输入 Bark 推送地址" : "Enter Bark push URL",
      customPushUrl: isZh ? "自定义推送 URL" : "Custom Push URL",
      customPushUrlPlaceholder:
        isZh
          ? "支持 {title} / {body} / {url} 占位符模板地址"
          : "Supports template URLs with {title}, {body}, and {url}",
      emptyForwardChatId: isZh ? "请输入转发目标 Chat ID" : "Enter a forward target chat ID",
      emptyBarkUrl: isZh ? "请输入 Bark URL" : "Enter a Bark URL",
      emptyCustomUrl: isZh ? "请输入自定义推送 URL" : "Enter a custom push URL",
    }),
    [isZh],
  );

  const notifyOnFailure =
    typeof controlledNotifyOnFailure === "boolean"
      ? controlledNotifyOnFailure
      : internalNotifyOnFailure;

  const setNotifyOnFailureValue = useCallback(
    (nextValue: boolean) => {
      if (typeof controlledNotifyOnFailure === "boolean") {
        onNotifyOnFailureChange?.(nextValue);
        return;
      }
      setInternalNotifyOnFailure(nextValue);
    },
    [controlledNotifyOnFailure, onNotifyOnFailureChange],
  );

  const formatErrorMessage = useCallback(
    (base: string, err?: any) => {
      const detail =
        typeof err?.message === "string" ? String(err.message).trim() : "";
      const code = err?.code;
      if (detail) {
        return code ? `${base}: ${detail} (${code})` : `${base}: ${detail}`;
      }
      return code ? `${base} (${code})` : base;
    },
    [],
  );

  const parsedSchedule = useMemo(() => {
    if (scheduleMode === "listen") {
      return {
        executionMode: "listen" as const,
        signAt: "00:00:00",
        rangeStart: "",
        rangeEnd: "",
      };
    }

    const trimmed = timeRange.trim();
    const match = trimmed.match(TIME_RANGE_PATTERN);
    if (!match) return null;

    const start = match[1];
    const end = match[3];

    if (end) {
      return {
        executionMode: "range" as const,
        signAt: start,
        rangeStart: start,
        rangeEnd: end,
      };
    }

    return {
      executionMode: "fixed" as const,
      signAt: start,
      rangeStart: "",
      rangeEnd: "",
    };
  }, [scheduleMode, timeRange]);

  const selectedAccountSummary = useMemo(() => {
    if (!selectedAccounts.length) {
      return text.selectAccount;
    }
    if (selectedAccounts.length === accounts.length) {
      return `${text.allAccounts} (${selectedAccounts.length})`;
    }
    if (selectedAccounts.length === 1) {
      return selectedAccounts[0];
    }
    return isZh
      ? `已选择 ${selectedAccounts.length} 个账号`
      : `${selectedAccounts.length} accounts selected`;
  }, [accounts.length, isZh, selectedAccounts, text.allAccounts, text.selectAccount]);

  const toggleSelectedAccount = useCallback((accountName: string) => {
    setSelectedAccounts((prev) => {
      const exists = prev.includes(accountName);
      const next = exists ? prev.filter((name) => name !== accountName) : [...prev, accountName];
      return next;
    });
  }, []);

  const handleAccountSessionInvalid = useCallback(
    (err: any) => {
      if (err?.code !== "ACCOUNT_SESSION_INVALID") return false;
      addToast(text.sessionInvalid, "error");
      setTimeout(() => {
        router.replace("/dashboard/accounts");
      }, 800);
      return true;
    },
    [addToast, router, text.sessionInvalid],
  );

  const loadChats = useCallback(
    async (tokenStr: string, accountName: string, forceRefresh = false) => {
      if (!accountName) {
        setAvailableChats([]);
        return;
      }

      try {
        const chatsData = await getAccountChats(tokenStr, accountName, forceRefresh);
        setAvailableChats(chatsData);
      } catch (err: any) {
        if (handleAccountSessionInvalid(err)) return;
        addToast(formatErrorMessage(text.loadChatsFailed, err), "error");
      }
    },
    [addToast, formatErrorMessage, handleAccountSessionInvalid, text.loadChatsFailed],
  );

  const loadAccounts = useCallback(
    async (tokenStr: string) => {
      try {
        const data = await listAccounts(tokenStr);
        const accountNames = data.accounts.map((account) => account.name);
        const taskAccounts = isEditMode && initialTask ? getTaskAccounts(initialTask) : [];
        const nextSelectedAccounts = taskAccounts.length
          ? taskAccounts.filter((accountName) => accountNames.includes(accountName))
          : accountNames;
        const sourceAccount = (
          isEditMode && initialTask
            ? String(initialTask.account_name || nextSelectedAccounts[0] || "")
            : (nextSelectedAccounts[0] || "")
        );
        setAccounts(data.accounts);
        setSelectedAccounts(nextSelectedAccounts);
        setSelectedAccount(sourceAccount);
        if (sourceAccount) {
          await loadChats(tokenStr, sourceAccount);
        } else {
          setAvailableChats([]);
        }
      } catch (err: any) {
        if (handleAccountSessionInvalid(err)) return;
        setAccounts([]);
        setSelectedAccounts([]);
        setSelectedAccount("");
        setAvailableChats([]);
      }
    },
    [handleAccountSessionInvalid, initialTask, isEditMode, loadChats],
  );

  useEffect(() => {
    const tokenStr = providedToken || getToken();
    if (!tokenStr) {
      return;
    }
    if (loadedTokenRef.current === tokenStr) {
      return;
    }
    loadedTokenRef.current = tokenStr;
    setToken(tokenStr);
    void loadAccounts(tokenStr);
  }, [loadAccounts, providedToken, router]);

  useEffect(() => {
    if (!selectedAccounts.length) {
      setSelectedAccount("");
      setAvailableChats([]);
      return;
    }

    if (!selectedAccounts.includes(selectedAccount)) {
      const fallback = selectedAccounts[0];
      setSelectedAccount(fallback);
      if (token) {
        void loadChats(token, fallback);
      }
    }
  }, [loadChats, selectedAccount, selectedAccounts, token]);

  useEffect(() => {
    if (!isEditMode || !initialTask) {
      return;
    }

    const chat = initialTask.chats[0];
    const taskAccounts = getTaskAccounts(initialTask);
    const listenAction = chat?.actions?.find((action) => Number(action?.action) === 8);
    const nextScheduleMode: ScheduleMode =
      initialTask.execution_mode === "listen" ? "listen" : "scheduled";
    const nextTimeRange =
      initialTask.execution_mode === "range" && initialTask.range_start && initialTask.range_end
        ? `${initialTask.range_start}-${initialTask.range_end}`
        : (initialTask.sign_at || "08:00-19:00");

    setTaskName(initialTask.name || "");
    setScheduleMode(nextScheduleMode);
    setTimeRange(nextTimeRange);
    setSelectedAccounts(taskAccounts);
    setSelectedAccount(String(initialTask.account_name || taskAccounts[0] || ""));
    setSelectedChatId(Number(chat?.chat_id || 0));
    setSelectedChatName(getChatDisplayName(chat));
    setMessageThreadId(
      chat?.message_thread_id === undefined || chat?.message_thread_id === null
        ? ""
        : String(chat.message_thread_id)
    );
    setNotifyOnFailureValue(Boolean(initialTask.notify_on_failure ?? true));

    if (listenAction) {
      const keywords = Array.isArray(listenAction.keywords)
        ? listenAction.keywords
        : splitKeywordInput(String(listenAction.keywords || ""), listenAction.match_mode || "contains");
      const nextPushChannel = (listenAction.push_channel || "continue") as ListenerPushChannel;
      setListenerKeywords(keywords.join("\n"));
      setListenerMatchMode((listenAction.match_mode || "contains") as MatchMode);
      setListenerPushChannel(nextPushChannel);
      setListenerForwardChatId(String(listenAction.forward_chat_id || ""));
      setListenerForwardThreadId(
        listenAction.forward_message_thread_id === undefined || listenAction.forward_message_thread_id === null
          ? ""
          : String(listenAction.forward_message_thread_id)
      );
      setListenerBarkUrl(String(listenAction.bark_url || ""));
      setListenerCustomUrl(String(listenAction.custom_url || ""));
      setActions(parseSequenceActions(Array.isArray(listenAction.continue_actions) ? listenAction.continue_actions : []));
      return;
    }

    setListenerKeywords("");
    setListenerMatchMode("contains");
    setListenerPushChannel("continue");
    setListenerForwardChatId("");
    setListenerForwardThreadId("");
    setListenerBarkUrl("");
    setListenerCustomUrl("");
    setActions(parseSequenceActions(Array.isArray(chat?.actions) ? chat.actions : []));
  }, [initialTask, isEditMode, setNotifyOnFailureValue]);

  useEffect(() => {
    if (scheduleMode !== "listen") return;
    if (actions.length === 1 && actions[0].type === "send_text" && !actions[0].value.trim()) {
      setActions([createSequenceAction("send_text", "{keyword}")]);
    }
  }, [actions, scheduleMode]);

  useEffect(() => {
    if (!token || !selectedAccount) return;

    const query = chatSearch.trim();
    if (!query) {
      setChatSearchResults([]);
      setChatSearchLoading(false);
      return;
    }

    let cancelled = false;
    setChatSearchLoading(true);

    const timer = window.setTimeout(async () => {
      try {
        const res = await searchAccountChats(token, selectedAccount, query, 50, 0);
        if (!cancelled) {
          setChatSearchResults(res.items || []);
        }
      } catch (err: any) {
        if (!cancelled) {
          if (handleAccountSessionInvalid(err)) return;
          addToast(formatErrorMessage(text.searchChatsFailed, err), "error");
          setChatSearchResults([]);
        }
      } finally {
        if (!cancelled) {
          setChatSearchLoading(false);
        }
      }
    }, 240);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [
    addToast,
    chatSearch,
    formatErrorMessage,
    handleAccountSessionInvalid,
    selectedAccount,
    text.searchChatsFailed,
    token,
  ]);

  const handleSelectedAccountChange = async (accountName: string) => {
    setSelectedAccount(accountName);
    if (token) {
      await loadChats(token, accountName);
    }
  };

  const handleRefreshChats = async () => {
    if (!token || !selectedAccount) return;
    try {
      setRefreshingChats(true);
      await loadChats(token, selectedAccount, true);
    } finally {
      setRefreshingChats(false);
    }
  };

  const selectChat = (chat: ChatInfo) => {
    setSelectedChatId(chat.id);
    setSelectedChatName(getChatDisplayName(chat));
    setChatSearch("");
    setChatSearchResults([]);
  };

  const handleSelectFromList = (chatId: string) => {
    const nextId = parseInt(chatId, 10);
    const chat = availableChats.find((item) => item.id === nextId);
    setSelectedChatId(nextId);
    setSelectedChatName(getChatDisplayName(chat) || String(nextId));
  };

  const addAction = () => {
    setActions((prev) => [...prev, createSequenceAction()]);
  };

  const updateAction = (actionId: string, patch: Partial<SequenceActionItem>) => {
    setActions((prev) =>
      prev.map((item) => (item.id === actionId ? { ...item, ...patch } : item)),
    );
  };

  const removeAction = (actionId: string) => {
    setActions((prev) => (prev.length <= 1 ? prev : prev.filter((item) => item.id !== actionId)));
  };

  const moveAction = (fromId: string, toId: string) => {
    if (fromId === toId) return;
    setActions((prev) => {
      const fromIndex = prev.findIndex((item) => item.id === fromId);
      const toIndex = prev.findIndex((item) => item.id === toId);
      if (fromIndex < 0 || toIndex < 0) return prev;
      const next = [...prev];
      const [moved] = next.splice(fromIndex, 1);
      next.splice(toIndex, 0, moved);
      return next;
    });
  };

  const handleActionTypeChange = (actionId: string, nextType: SequenceActionType) => {
    setActions((prev) =>
      prev.map((item) => {
        if (item.id !== actionId) return item;
        if (nextType === "delay") {
          return {
            ...item,
            type: nextType,
            value: item.type === "delay" ? item.value : "",
            aiPrompt: "",
          };
        }
        if (
          nextType === "send_text" ||
          nextType === "click_text_button"
        ) {
          return {
            ...item,
            type: nextType,
            value: item.type === "delay" ? "" : item.value,
            aiPrompt: "",
          };
        }
        return {
          ...item,
          type: nextType,
          value: "",
          aiPrompt: isAISequenceActionType(item.type) ? item.aiPrompt : "",
        };
      }),
    );
  };

  const buildTaskName = () => {
    const trimmed = taskName.trim();
    if (trimmed) return trimmed;
    if (scheduleMode === "listen") {
      return sanitizeTaskName(
        selectedChatName
        ? `${text.defaultListenName} - ${selectedChatName}`
        : text.defaultListenName,
      );
    }
    if (selectedChatName) {
      return sanitizeTaskName(selectedChatName);
    }
    return sanitizeTaskName(text.defaultTaskNameFallback);
  };

  const handleSubmit = async () => {
    if (!token) return;
    const rawTaskName = taskName.trim();
    if (rawTaskName && sanitizeTaskName(rawTaskName) !== rawTaskName) {
      addToast(invalidTaskNameMessage, "error");
      return;
    }
    const finalTaskName = rawTaskName || buildTaskName();
    if (!finalTaskName) {
      addToast(invalidTaskNameMessage, "error");
      return;
    }

    if (!selectedAccounts.length) {
      addToast(text.selectAccountError, "error");
      return;
    }

    if (!selectedChatId || !selectedChatName) {
      addToast(text.selectChatError, "error");
      return;
    }

    if (scheduleMode === "scheduled" && !parsedSchedule) {
      addToast(text.invalidTime, "error");
      return;
    }

    let payloadActions: Array<Record<string, any>> = [];
    if (scheduleMode === "listen") {
      const keywords = splitKeywordInput(listenerKeywords, listenerMatchMode);
      if (!keywords.length) {
        addToast(text.emptyKeyword, "error");
        return;
      }

      const keywordAction: Record<string, any> = {
        action: 8,
        keywords,
        match_mode: listenerMatchMode,
        ignore_case: true,
        push_channel: listenerPushChannel,
      };

      if (listenerPushChannel === "continue") {
        const built = buildSequenceActions(actions, {
          invalidDelay: text.invalidDelay,
          emptyDelay: text.emptyDelay,
          consecutiveDelay: text.consecutiveDelay,
          trailingDelay: text.trailingDelay,
          emptyText: text.emptyActionText,
          emptyActions: text.emptyActions,
        });
        if (built.ok === false) {
          addToast(built.message, "error");
          return;
        }
        keywordAction.continue_actions = built.actions;
        keywordAction.continue_action_interval = 1;
      }

      if (listenerPushChannel === "forward") {
        if (!listenerForwardChatId.trim()) {
          addToast(listenerLabels.emptyForwardChatId, "error");
          return;
        }
        keywordAction.forward_chat_id = listenerForwardChatId.trim();
        if (listenerForwardThreadId.trim()) {
          keywordAction.forward_message_thread_id = parseInt(listenerForwardThreadId.trim(), 10);
        }
      }

      if (listenerPushChannel === "bark") {
        if (!listenerBarkUrl.trim()) {
          addToast(listenerLabels.emptyBarkUrl, "error");
          return;
        }
        keywordAction.bark_url = listenerBarkUrl.trim();
      }

      if (listenerPushChannel === "custom") {
        if (!listenerCustomUrl.trim()) {
          addToast(listenerLabels.emptyCustomUrl, "error");
          return;
        }
        keywordAction.custom_url = listenerCustomUrl.trim();
      }

      payloadActions = [keywordAction];
    } else {
      const built = buildSequenceActions(actions, {
        invalidDelay: text.invalidDelay,
        emptyDelay: text.emptyDelay,
        consecutiveDelay: text.consecutiveDelay,
        trailingDelay: text.trailingDelay,
        emptyText: text.emptyActionText,
        emptyActions: text.emptyActions,
      });
      if (built.ok === false) {
        addToast(built.message, "error");
        return;
      }
      payloadActions = built.actions;
    }

    const schedule = parsedSchedule ?? {
      executionMode: "fixed" as const,
      signAt: "08:00",
      rangeStart: "",
      rangeEnd: "",
    };

    try {
      setLoading(true);
      const payload = {
        account_name: selectedAccounts[0],
        account_names: selectedAccounts,
        sign_at: schedule.signAt,
        chats: [
          {
            chat_id: selectedChatId,
            name: selectedChatName,
            actions: payloadActions,
            action_interval: 1,
            message_thread_id: messageThreadId.trim()
              ? parseInt(messageThreadId.trim(), 10)
              : undefined,
          },
        ],
        random_seconds: 0,
        sign_interval: 1,
        execution_mode: schedule.executionMode,
        range_start: schedule.rangeStart,
        range_end: schedule.rangeEnd,
        notify_on_failure: notifyOnFailure,
      };

      if (isEditMode && initialTask) {
        await updateSignTask(token, initialTask.name, payload, initialTask.account_name);
        addToast(text.updateSuccess, "success");
      } else {
        await createSignTask(token, {
          ...payload,
          name: finalTaskName,
        });
        addToast(text.createSuccess, "success");
      }

      setTimeout(() => {
        if (onSuccess) {
          void onSuccess();
        } else {
          router.push("/dashboard/sign-tasks");
        }
      }, 700);
    } catch (err: any) {
      addToast(
        formatErrorMessage(isEditMode ? text.updateFailed : text.createFailed, err),
        "error",
      );
    } finally {
      setLoading(false);
    }
  };

  if (!token) {
    return null;
  }

  const rootClassName = compact
    ? "flex h-full min-h-0 flex-col"
    : "dialog-panel flex max-h-[calc(100vh-40px)] min-h-0 flex-col rounded-[16px]";
  const contentClassName = compact
    ? "task-dialog-scroll min-h-0 flex-1 space-y-6 overflow-y-auto p-6"
    : "dialog-body task-dialog-scroll min-h-0 flex-1 space-y-6 overflow-y-auto p-6";
  const actionSectionTitle =
    scheduleMode === "listen" ? text.continueSequence : text.actionSequence;

  return (
    <>
      <div className={rootClassName}>
        <div className={contentClassName}>
          {showInlineNotifyToggle ? (
            <div className="flex justify-end">
              <label className="mb-0 inline-flex items-center gap-2 text-sm font-medium text-main/75">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-slate-300 text-[#2AABEE] focus:ring-[#2AABEE]"
                  checked={notifyOnFailure}
                  onChange={(e) => setNotifyOnFailureValue(e.target.checked)}
                />
                <span>{text.notifyOnFailure}</span>
              </label>
            </div>
          ) : null}

          <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-xs font-medium text-slate-500">
                {text.taskName}
              </label>
              <input
                className={`!mb-0 !h-11 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900 ${
                  isEditMode ? "cursor-not-allowed !bg-slate-100 dark:!bg-slate-800" : ""
                }`}
                value={taskName}
                onChange={(e) => setTaskName(e.target.value)}
                placeholder={text.taskNamePlaceholder}
                disabled={isEditMode}
              />
              {isEditMode ? (
                <div className="mt-1 text-[11px] text-slate-400">{text.taskNameReadonly}</div>
              ) : null}
            </div>

            <div className="relative">
              <label className="mb-1.5 block text-xs font-medium text-slate-500">
                {text.linkedAccounts}
              </label>
              <button
                type="button"
                onClick={() => setAccountDropdownOpen((prev) => !prev)}
                className="flex h-11 w-full items-center justify-between rounded-lg border border-slate-300 bg-white px-4 text-left text-sm text-slate-700 transition-colors hover:border-[#2AABEE] dark:border-slate-700 dark:bg-slate-900 dark:text-slate-100"
              >
                <span className="truncate">{selectedAccountSummary}</span>
                <CaretDown
                  size={16}
                  className={`shrink-0 transition-transform ${accountDropdownOpen ? "rotate-180" : ""}`}
                />
              </button>

              {accountDropdownOpen ? (
                <div className="absolute left-0 right-0 top-[calc(100%+8px)] z-30 rounded-xl border border-slate-200 bg-white p-3 shadow-[0_18px_36px_rgba(15,23,42,0.12)] dark:border-slate-700 dark:bg-slate-900">
                  <div className="mb-2 flex items-center justify-between gap-3">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-400">
                      {text.linkedAccounts}
                    </div>
                    <button
                      type="button"
                      className="text-[11px] font-medium text-[#2AABEE]"
                      onClick={() => setAccountDropdownOpen(false)}
                    >
                      {text.closeDropdown}
                    </button>
                  </div>

                  {!accounts.length ? (
                    <div className="rounded-lg border border-dashed border-slate-200 px-3 py-3 text-sm text-slate-400 dark:border-slate-700">
                      {text.emptyAccount}
                    </div>
                  ) : (
                    <div className="space-y-1.5">
                      {accounts.map((account) => {
                        const checked = selectedAccounts.includes(account.name);
                        return (
                          <button
                            key={account.name}
                            type="button"
                            onClick={() => toggleSelectedAccount(account.name)}
                            className={`flex w-full items-center justify-between rounded-lg px-3 py-2 text-sm transition-colors ${
                              checked
                                ? "bg-sky-50 text-sky-700 dark:bg-sky-950/40 dark:text-sky-300"
                                : "bg-slate-50 text-slate-600 hover:bg-slate-100 dark:bg-slate-800/60 dark:text-slate-300 dark:hover:bg-slate-800"
                            }`}
                          >
                            <span className="truncate">{account.name}</span>
                            {checked ? <Check size={14} weight="bold" /> : null}
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
              ) : null}
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-slate-500">
                {text.scheduleMode}
              </label>
              <select
                className="!mb-0 !h-11 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900"
                value={scheduleMode}
                onChange={(e) => setScheduleMode(e.target.value as ScheduleMode)}
              >
                <option value="scheduled">{text.scheduled}</option>
                <option value="listen">{text.listen}</option>
              </select>
            </div>

            <div>
              <label className="mb-1.5 block text-xs font-medium text-slate-500">
                {text.timeRange}
              </label>
              <input
                className={`!mb-0 !h-11 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900 ${
                  scheduleMode === "listen" ? "cursor-not-allowed !bg-slate-100 dark:!bg-slate-800" : ""
                }`}
                value={scheduleMode === "listen" ? text.scheduleAuto24H : timeRange}
                disabled={scheduleMode === "listen"}
                onChange={(e) => setTimeRange(e.target.value)}
                placeholder={text.timePlaceholder}
              />
            </div>
          </div>

          <section className="rounded-xl border border-sky-100 bg-sky-50/60 p-5 dark:border-slate-700 dark:bg-slate-800/40">
            <h4 className="mb-4 text-xs font-bold uppercase tracking-[0.24em] text-[#2AABEE]">
              {text.targetChat}
            </h4>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-500">
                  {text.sourceAccount}
                </label>
                <select
                  className="!mb-0 !h-11 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900"
                  value={selectedAccount}
                  onChange={(e) => {
                    void handleSelectedAccountChange(e.target.value);
                  }}
                  disabled={!selectedAccounts.length}
                >
                  {selectedAccounts.length ? (
                    selectedAccounts.map((accountName) => (
                      <option key={accountName} value={accountName}>
                        {accountName}
                      </option>
                    ))
                  ) : (
                    <option value="">{text.selectLinkedAccountFirst}</option>
                  )}
                </select>
              </div>

              <div>
                <div className="mb-1.5 flex items-center justify-between gap-3">
                  <label className="mb-0 block text-xs font-medium text-slate-500">
                    {text.selectFromList}
                  </label>
                  <button
                    type="button"
                    onClick={handleRefreshChats}
                    disabled={!selectedAccount || refreshingChats}
                    className="text-xs font-medium text-[#2AABEE] transition-colors hover:text-[#169adf] disabled:opacity-40"
                  >
                    {refreshingChats ? text.refreshing : text.refreshList}
                  </button>
                </div>
                <select
                  className="!mb-0 !h-11 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900"
                  value={selectedChatId || 0}
                  onChange={(e) => handleSelectFromList(e.target.value)}
                  disabled={!selectedAccount}
                >
                  <option value={0}>{text.selectFromListPlaceholder}</option>
                  {availableChats.map((chat) => (
                    <option key={chat.id} value={chat.id}>
                      {getChatDisplayName(chat) || chat.id}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-500">
                  {text.searchChat}
                </label>
                <input
                  className="!mb-0 !h-11 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900"
                  placeholder={text.searchChatPlaceholder}
                  value={chatSearch}
                  onChange={(e) => setChatSearch(e.target.value)}
                  disabled={!selectedAccount}
                />

                {chatSearch.trim() ? (
                  <div className="mt-2 max-h-40 overflow-y-auto rounded-lg border border-slate-200 bg-white dark:border-slate-700 dark:bg-slate-900">
                    {chatSearchLoading ? (
                      <div className="px-3 py-2 text-xs text-slate-400">{text.searching}</div>
                    ) : chatSearchResults.length ? (
                      chatSearchResults.map((chat) => (
                        <button
                          key={chat.id}
                          type="button"
                          onClick={() => selectChat(chat)}
                          className="block w-full border-b border-slate-100 px-3 py-2 text-left hover:bg-slate-50 last:border-b-0 dark:border-slate-800 dark:hover:bg-slate-800/60"
                        >
                          <div className="truncate text-sm font-medium text-slate-700 dark:text-slate-100">
                            {getChatDisplayName(chat) || String(chat.id)}
                          </div>
                          <div className="truncate text-[11px] font-mono text-slate-400">
                            {chat.id}
                            {chat.username ? ` | @${chat.username}` : ""}
                          </div>
                        </button>
                      ))
                    ) : (
                      <div className="px-3 py-2 text-xs text-slate-400">{text.noSearchResult}</div>
                    )}
                  </div>
                ) : null}
              </div>

              <div>
                <label className="mb-1.5 block text-xs font-medium text-slate-500">
                  {text.topicId}
                </label>
                <input
                  className="!mb-0 !h-11 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900"
                  inputMode="numeric"
                  value={messageThreadId}
                  onChange={(e) => setMessageThreadId(e.target.value.replace(/[^0-9]/g, ""))}
                  placeholder={text.topicPlaceholder}
                />
              </div>
            </div>
          </section>

          {scheduleMode === "listen" ? (
            <section className="rounded-xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
              <h4 className="mb-4 text-xs font-bold uppercase tracking-[0.24em] text-[#2AABEE]">
                {text.keywordSettings}
              </h4>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div className="md:col-span-2">
                  <label className="mb-1.5 block text-xs font-medium text-slate-500">
                    {isZh ? "关键词" : "Keywords"}
                  </label>
                  <textarea
                    className="min-h-[92px] w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm outline-none transition-colors focus:border-[#2AABEE] dark:border-slate-700 dark:bg-slate-900"
                    value={listenerKeywords}
                    onChange={(e) => setListenerKeywords(e.target.value)}
                    placeholder={text.keywordPlaceholder}
                  />
                </div>

                <div>
                  <label className="mb-1.5 block text-xs font-medium text-slate-500">
                    {text.keywordMatchMode}
                  </label>
                  <select
                    className="!mb-0 !h-11 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900"
                    value={listenerMatchMode}
                    onChange={(e) => setListenerMatchMode(e.target.value as MatchMode)}
                  >
                    <option value="contains">{text.matchContains}</option>
                    <option value="exact">{text.matchExact}</option>
                    <option value="regex">{text.matchRegex}</option>
                  </select>
                </div>

                <div>
                  <label className="mb-1.5 block text-xs font-medium text-slate-500">
                    {text.listenerActionMode}
                  </label>
                  <select
                    className="!mb-0 !h-11 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900"
                    value={listenerPushChannel}
                    onChange={(e) =>
                      setListenerPushChannel(e.target.value as ListenerPushChannel)
                    }
                  >
                    <option value="continue">{text.continueActions}</option>
                    <option value="telegram">{text.telegramNotify}</option>
                    <option value="forward">{listenerLabels.forwardNotify}</option>
                    <option value="bark">{listenerLabels.barkNotify}</option>
                    <option value="custom">{listenerLabels.customNotify}</option>
                  </select>
                </div>

                {listenerPushChannel === "forward" ? (
                  <>
                    <div>
                      <label className="mb-1.5 block text-xs font-medium text-slate-500">
                        {listenerLabels.forwardChatId}
                      </label>
                      <input
                        className="!mb-0 !h-11 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900"
                        value={listenerForwardChatId}
                        onChange={(e) => setListenerForwardChatId(e.target.value)}
                        placeholder={listenerLabels.forwardChatIdPlaceholder}
                      />
                    </div>
                    <div>
                      <label className="mb-1.5 block text-xs font-medium text-slate-500">
                        {listenerLabels.forwardThreadId}
                      </label>
                      <input
                        className="!mb-0 !h-11 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900"
                        inputMode="numeric"
                        value={listenerForwardThreadId}
                        onChange={(e) =>
                          setListenerForwardThreadId(e.target.value.replace(/[^0-9]/g, ""))
                        }
                        placeholder={listenerLabels.forwardThreadIdPlaceholder}
                      />
                    </div>
                  </>
                ) : null}

                {listenerPushChannel === "bark" ? (
                  <div className="md:col-span-2">
                    <label className="mb-1.5 block text-xs font-medium text-slate-500">
                      {listenerLabels.barkUrl}
                    </label>
                    <input
                      className="!mb-0 !h-11 !rounded-lg !border-slate-300 !bg-white !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-900"
                      value={listenerBarkUrl}
                      onChange={(e) => setListenerBarkUrl(e.target.value)}
                      placeholder={listenerLabels.barkUrlPlaceholder}
                    />
                  </div>
                ) : null}

                {listenerPushChannel === "custom" ? (
                  <div className="md:col-span-2">
                    <label className="mb-1.5 block text-xs font-medium text-slate-500">
                      {listenerLabels.customPushUrl}
                    </label>
                    <textarea
                      className="min-h-[92px] w-full rounded-lg border border-slate-300 bg-white px-4 py-3 text-sm outline-none transition-colors focus:border-[#2AABEE] dark:border-slate-700 dark:bg-slate-900"
                      value={listenerCustomUrl}
                      onChange={(e) => setListenerCustomUrl(e.target.value)}
                      placeholder={listenerLabels.customPushUrlPlaceholder}
                    />
                  </div>
                ) : null}
              </div>
            </section>
          ) : null}

          {scheduleMode === "scheduled" || listenerPushChannel === "continue" ? (
            <section>
              <div className="mb-3 flex items-center justify-between gap-4">
                <div className="flex items-center gap-2 text-slate-700 dark:text-slate-100">
                  <ListNumbers weight="bold" size={18} className="text-slate-400" />
                  <h4 className="text-lg font-bold">{actionSectionTitle}</h4>
                </div>
                <button
                  type="button"
                  onClick={addAction}
                  className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 text-xs font-medium text-slate-600 shadow-sm transition-colors hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
                >
                  <Plus weight="bold" size={12} />
                  <span>{text.addAction}</span>
                </button>
              </div>

              <div className="space-y-3">
                {actions.map((action, index) => (
                  <div
                    key={action.id}
                    draggable
                    onDragStart={() => setDraggingActionId(action.id)}
                    onDragOver={(e) => e.preventDefault()}
                    onDrop={() => {
                      if (!draggingActionId) return;
                      moveAction(draggingActionId, action.id);
                      setDraggingActionId(null);
                    }}
                    onDragEnd={() => setDraggingActionId(null)}
                    className={`rounded-xl border bg-white p-3 shadow-sm transition-colors dark:bg-slate-900 ${
                      draggingActionId === action.id
                        ? "border-[#2AABEE]/50"
                        : "border-slate-200 dark:border-slate-700"
                    }`}
                  >
                    <div className="flex flex-col gap-3 md:flex-row md:items-center">
                      <div className="flex items-center gap-3 md:w-[340px]">
                        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-slate-100 text-xs font-bold text-slate-500 dark:bg-slate-800 dark:text-slate-300">
                          {index + 1}
                        </div>
                        <button
                          type="button"
                          className="cursor-grab text-slate-300 dark:text-slate-600"
                          aria-label="drag"
                        >
                          <DotsSixVertical weight="bold" size={18} />
                        </button>
                        <select
                          className="!mb-0 !h-10 !rounded-lg !border-slate-200 !bg-slate-50 !px-3 !text-sm !font-medium dark:!border-slate-700 dark:!bg-slate-950"
                          value={action.type}
                          onChange={(e) =>
                            handleActionTypeChange(action.id, e.target.value as SequenceActionType)
                          }
                        >
                          <option value="send_text">{text.sendText}</option>
                          <option value="click_text_button">{text.clickTextButton}</option>
                          <option value="delay">{text.delay}</option>
                          <optgroup label={text.aiVision}>
                            <option value="vision_send">{text.visionSend}</option>
                            <option value="vision_click">{text.visionClick}</option>
                          </optgroup>
                          <optgroup label={text.aiCalc}>
                            <option value="calc_send">{text.calcSend}</option>
                            <option value="calc_click">{text.calcClick}</option>
                          </optgroup>
                        </select>
                      </div>

                      <div className="flex min-w-0 flex-1 items-start gap-3">
                        {(action.type === "send_text" || action.type === "click_text_button") ? (
                          <input
                            className="!mb-0 !h-10 !rounded-lg !border-slate-200 !bg-slate-50 !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-950"
                            value={action.value}
                            onChange={(e) => updateAction(action.id, { value: e.target.value })}
                            placeholder={
                              action.type === "send_text"
                                ? text.textPlaceholder
                                : text.buttonPlaceholder
                            }
                          />
                        ) : action.type === "delay" ? (
                          <input
                            className="!mb-0 !h-10 !rounded-lg !border-slate-200 !bg-slate-50 !px-4 !text-sm dark:!border-slate-700 dark:!bg-slate-950"
                            value={action.value}
                            onChange={(e) =>
                              updateAction(action.id, {
                                value: e.target.value.replace(/[^\d.\-]/g, ""),
                              })
                            }
                            placeholder={text.delayPlaceholder}
                          />
                        ) : isAISequenceActionType(action.type) ? (
                          <div className="min-w-0 flex-1 space-y-1.5">
                            <label className="block text-[11px] font-medium text-slate-500">
                              {text.aiPromptLabel}
                            </label>
                            <textarea
                              className="min-h-[92px] w-full resize-y rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-sm text-slate-700 outline-none transition-colors focus:border-[#2AABEE] dark:border-slate-700 dark:bg-slate-950 dark:text-slate-100"
                              value={action.aiPrompt}
                              onChange={(e) =>
                                updateAction(action.id, { aiPrompt: e.target.value })
                              }
                              placeholder={
                                action.type === "vision_send" || action.type === "vision_click"
                                  ? text.aiVisionPromptPlaceholder
                                  : text.aiCalcPromptPlaceholder
                              }
                            />
                            <div className="text-[11px] text-slate-400">
                              {text.aiPromptHint}
                            </div>
                          </div>
                        ) : (
                          <div className="flex h-10 flex-1 items-center rounded-lg border border-slate-200 bg-slate-50 px-4 text-sm text-slate-400 dark:border-slate-700 dark:bg-slate-950">
                            {text.noExtraInput}
                          </div>
                        )}

                        <button
                          type="button"
                          onClick={() => removeAction(action.id)}
                          disabled={actions.length <= 1}
                          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg text-slate-400 transition-colors hover:bg-rose-50 hover:text-rose-500 disabled:opacity-35 dark:hover:bg-rose-950/40"
                          title={isZh ? "删除动作" : "Delete action"}
                        >
                          <Trash weight="bold" size={15} />
                        </button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ) : null}
        </div>

        <div className="dialog-footer flex items-center gap-3 px-6 py-4">
          <button
            type="button"
            onClick={handleCancel}
            className="inline-flex h-11 min-w-[96px] items-center justify-center rounded-lg border border-slate-300 bg-white px-6 text-sm font-medium text-slate-600 shadow-sm transition-colors hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-slate-700"
          >
            {text.cancel}
          </button>
          <div className="flex-1" />
          <button
            type="button"
            onClick={handleSubmit}
            disabled={loading}
            className="inline-flex h-11 min-w-[176px] items-center justify-center rounded-lg bg-[#2AABEE] px-8 text-sm font-semibold text-white shadow-[0_10px_24px_rgba(42,171,238,0.22)] transition-colors hover:bg-[#199ddd] disabled:opacity-60"
          >
            {loading ? <Spinner className="animate-spin" /> : text.save}
          </button>
        </div>
      </div>

      <ToastContainer toasts={toasts} removeToast={removeToast} />
    </>
  );
}
