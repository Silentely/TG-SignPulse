"use client";

import {
  buildTaskLogViewModel,
  formatLastTargetMessage,
} from "../lib/task-log-format";

type TaskLogViewProps = {
  lines?: string[];
  lastTargetMessage?: string;
  lastTargetLabel: string;
  fallbackText?: string;
};

export function TaskLogView({
  lines,
  lastTargetMessage,
  lastTargetLabel,
  fallbackText,
}: TaskLogViewProps) {
  const model = buildTaskLogViewModel(lines || [], lastTargetMessage);
  const lastMessageLines = formatLastTargetMessage(model.lastTargetMessage);

  if (model.blocks.length === 0 && lastMessageLines.length === 0) {
    return fallbackText ? (
      <div className="text-main/50">{fallbackText}</div>
    ) : null;
  }

  return (
    <div className="space-y-4">
      {model.blocks.map((block, index) =>
        block.kind === "line" ? (
          <div key={`${block.kind}-${index}`} className="text-[12px] font-medium text-main/85">
            {block.text}
          </div>
        ) : (
          <div
            key={`${block.kind}-${block.label}-${index}`}
            className="rounded-xl border border-white/6 bg-white/[0.035] px-3 py-3"
          >
            <div className="text-[12px] font-semibold text-[#2AABEE]">
              {block.label}.{block.title}
            </div>
            <div className="mt-2 space-y-2">
              {block.items.map((item, itemIndex) => (
                <div
                  key={`${block.label}-${itemIndex}`}
                  className="flex items-start gap-3 text-[12px] text-main/80"
                >
                  <span className="w-5 shrink-0 text-right text-main/35">
                    {itemIndex + 1}.
                  </span>
                  <span className="min-w-0 flex-1 break-words leading-5">
                    {item}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ),
      )}

      {lastMessageLines.length > 0 ? (
        <div className="rounded-xl border border-[#2AABEE]/15 bg-[#2AABEE]/10 px-3 py-2 text-main/85">
          <div className="text-[10px] uppercase tracking-wider text-[#2AABEE]">
            {lastTargetLabel}
          </div>
          <div className="mt-2 space-y-1">
            {lastMessageLines.map((line, lineIndex) => (
              <div key={lineIndex} className="whitespace-pre-wrap break-words leading-relaxed">
                {line}
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
