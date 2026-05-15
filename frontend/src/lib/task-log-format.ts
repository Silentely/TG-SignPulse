export type TaskLogBlock =
  | {
      kind: "line";
      text: string;
    }
  | {
      kind: "section";
      label: string;
      title: string;
      items: string[];
    };

const LOG_TIMESTAMP_PREFIX =
  /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:,\d+)?\s*-\s*/;
const LOG_TASK_CONTEXT_PREFIX =
  /^账户「[^」]+」\s*-\s*任务「[^」]+」:\s*/;
const LOG_DECORATION_PATTERN = /^[\s|╔╗╚╝╟╢╠╣║═─]+$/;
const LOG_SKIP_PATTERNS = [
  /^Message:$/i,
  /^text:$/i,
  /^InlineKeyboard:$/i,
  /^adding message handlers for chats:/i,
  /^当前时间:/,
  /^开始执行:\s*$/i,
  /^Chat ID:\s*/i,
  /^Name:\s*/i,
  /^Delete After:\s*/i,
  /^Actions Flow:\s*$/i,
  /^\d+\.\s*\[/,
  /^收到来自「.*」(?:的消息|对消息的更新，消息):/,
];
const LAST_TARGET_PREFIX = "任务对象最后一条消息:";

function getSectionLabel(index: number) {
  return String.fromCharCode(65 + index);
}

export function formatLastTargetMessage(value?: string) {
  return String(value || "")
    .trim()
    .split(/\s+·\s+|\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function sanitizeFlowLogLine(value?: string) {
  let text = String(value || "").replace(/\r/g, "").trim();
  if (!text) {
    return "";
  }
  text = text.replace(LOG_TIMESTAMP_PREFIX, "").trim();
  text = text.replace(LOG_TASK_CONTEXT_PREFIX, "").trim();
  if (!text || LOG_DECORATION_PATTERN.test(text)) {
    return "";
  }
  if (LOG_SKIP_PATTERNS.some((pattern) => pattern.test(text))) {
    return "";
  }
  return text.replace(/\s+/g, " ").trim();
}

export function normalizeFlowLogLines(lines?: string[]) {
  if (!Array.isArray(lines)) {
    return [];
  }
  const normalized: string[] = [];
  for (const raw of lines) {
    const parts = String(raw || "").split(/\r?\n/);
    for (const part of parts) {
      const clean = sanitizeFlowLogLine(part);
      if (!clean || normalized[normalized.length - 1] === clean) {
        continue;
      }
      normalized.push(clean);
    }
  }
  return normalized;
}

function extractLastTargetMessageFromLines(lines: string[]) {
  const startIndex = lines.findIndex((line) => line.startsWith(LAST_TARGET_PREFIX));
  if (startIndex < 0) {
    return {
      content: "",
      remainingLines: lines,
    };
  }

  const firstLine = lines[startIndex].slice(LAST_TARGET_PREFIX.length).trim();
  const messageLines = [firstLine, ...lines.slice(startIndex + 1)].filter(Boolean);
  return {
    content: messageLines.join("\n").trim(),
    remainingLines: lines.slice(0, startIndex),
  };
}

type TaskLogViewModel = {
  blocks: TaskLogBlock[];
  lastTargetMessage: string;
};

function toActionCompletionText(line: string) {
  if (line.includes("发送文本消息")) {
    return "发送完成";
  }
  if (line.includes("发送骰子")) {
    return "发送完成";
  }
  if (line.includes("点击文字按钮")) {
    return "";
  }
  return line;
}

function toDisplayText(line: string) {
  if (line.startsWith("开始登录")) {
    return "执行登录...";
  }
  if (line.startsWith("开始执行任务对象:")) {
    return `确认任务对象: ${line.slice("开始执行任务对象:".length).trim()}`;
  }
  if (line.startsWith("已发送文本消息到 ")) {
    return line.replace(/^已发送/, "");
  }
  if (line.startsWith("已发送骰子到 ")) {
    return line.replace(/^已发送/, "");
  }
  if (/^第 \d+\/\d+ 步执行完成：/.test(line)) {
    return toActionCompletionText(line);
  }
  return line;
}

export function buildTaskLogViewModel(
  lines?: string[],
  explicitLastTargetMessage?: string,
): TaskLogViewModel {
  const normalizedLines = normalizeFlowLogLines(lines);
  const extracted = extractLastTargetMessageFromLines(normalizedLines);
  const lastTargetMessage = String(explicitLastTargetMessage || extracted.content).trim();
  const sourceLines = extracted.remainingLines;

  const blocks: TaskLogBlock[] = [];
  let currentSection: Extract<TaskLogBlock, { kind: "section" }> | null = null;
  let sectionIndex = 0;

  const pushSection = () => {
    if (currentSection && currentSection.items.length > 0) {
      blocks.push(currentSection);
    }
    currentSection = null;
  };

  const beginSection = (title: string) => {
    pushSection();
    currentSection = {
      kind: "section",
      label: getSectionLabel(sectionIndex),
      title,
      items: [],
    };
    sectionIndex += 1;
  };

  const ensureInitSection = () => {
    if (currentSection?.title === "任务初始化") {
      return currentSection;
    }
    if (currentSection) {
      pushSection();
    }
    currentSection = {
      kind: "section",
      label: getSectionLabel(sectionIndex),
      title: "任务初始化",
      items: [],
    };
    sectionIndex += 1;
    return currentSection;
  };

  const ensureFlowSection = () => {
    if (!currentSection) {
      beginSection("执行过程");
    }
    return currentSection!;
  };

  const addLineBlock = (text: string) => {
    pushSection();
    blocks.push({ kind: "line", text });
  };

  const addSectionItem = (text: string, section: "init" | "flow" = "flow") => {
    const targetSection =
      section === "init" ? ensureInitSection() : ensureFlowSection();
    if (!text || targetSection.items[targetSection.items.length - 1] === text) {
      return;
    }
    targetSection.items.push(text);
  };

  for (const rawLine of sourceLines) {
    const line = toDisplayText(rawLine);
    if (!line) {
      continue;
    }

    if (
      line.startsWith("开始执行任务:") ||
      line.startsWith("消息更新监听:") ||
      line.startsWith("关键词监听说明:") ||
      line.startsWith("关键词后台监听已启动") ||
      line.startsWith("关键词后台监听已停止")
    ) {
      addLineBlock(line);
      continue;
    }

    if (line.startsWith("执行登录...") || line.startsWith("确认任务对象:")) {
      addSectionItem(line, "init");
      continue;
    }

    if (/^开始第 \d+\/\d+ 次脚本流程尝试$/.test(line)) {
      beginSection(line);
      continue;
    }

    if (/^第 \d+\/\d+ 步将在 .*秒后执行：/.test(line)) {
      continue;
    }

    if (/^正在执行第 \d+\/\d+ 步：发送(?:文本消息|骰子)：/.test(line)) {
      continue;
    }

    if (
      line.startsWith("收到图片：") ||
      line.startsWith("按钮所在任务对象消息:") ||
      line.startsWith("收到的任务对象消息暂未匹配当前步骤")
    ) {
      continue;
    }

    if (line.startsWith("检测到任务已完成，停止执行后续动作")) {
      continue;
    }

    if (/^第 \d+\/\d+ 步执行完成：点击文字按钮：/.test(line)) {
      continue;
    }

    if (/^第 \d+\/\d+ 步执行完成：/.test(line)) {
      const completionText = toActionCompletionText(line);
      if (completionText) {
        addSectionItem(completionText);
      }
      continue;
    }

    if (line.startsWith("任务执行完成")) {
      addSectionItem(line);
      continue;
    }

    if (line.startsWith("任务执行出错:") || line.startsWith("任务最终状态:")) {
      addLineBlock(line);
      continue;
    }

    addSectionItem(line);
  }

  pushSection();

  return {
    blocks,
    lastTargetMessage,
  };
}
