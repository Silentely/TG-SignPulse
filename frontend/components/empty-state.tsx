"use client";

import type { Icon } from "@phosphor-icons/react";

type EmptyStateProps = {
  icon: Icon;
  title: string;
  description: string;
  action?: React.ReactNode;
  compact?: boolean;
};

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  compact = false,
}: EmptyStateProps) {
  return (
    <div
      className={`glass-panel border-dashed border-2 border-[#2AABEE]/18 text-center ${
        compact ? "p-8 rounded-2xl" : "p-12 sm:p-16 rounded-[28px]"
      }`}
    >
      <div className="mx-auto flex max-w-xl flex-col items-center">
        <div
          className={`mb-5 flex items-center justify-center rounded-[24px] bg-[#2AABEE]/10 text-[#2AABEE] ${
            compact ? "h-16 w-16" : "h-20 w-20"
          }`}
        >
          <Icon weight="fill" size={compact ? 28 : 34} />
        </div>

        <div className="text-[11px] font-bold uppercase tracking-[0.22em] text-[#2AABEE]">
          SignPulse
        </div>

        <h3 className={`mt-3 font-bold tracking-tight text-main ${compact ? "text-xl" : "text-2xl"}`}>
          {title}
        </h3>

        <p className={`mt-3 max-w-lg leading-7 text-main/50 ${compact ? "text-sm" : "text-[15px]"}`}>
          {description}
        </p>

        {action ? <div className="mt-7">{action}</div> : null}
      </div>
    </div>
  );
}
