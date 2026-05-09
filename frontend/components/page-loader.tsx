"use client";

import { Spinner } from "@phosphor-icons/react";

type PageLoaderProps = {
  label: string;
  compact?: boolean;
};

export function PageLoader({ label, compact = false }: PageLoaderProps) {
  return (
    <div
      className={`flex flex-col items-center justify-center text-main/28 ${
        compact ? "py-12" : "py-20"
      }`}
    >
      <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-[22px] bg-[#2AABEE]/10 text-[#2AABEE]">
        <Spinner size={32} weight="bold" className="animate-spin" />
      </div>
      <p className="text-[11px] font-bold uppercase tracking-[0.24em]">{label}</p>
    </div>
  );
}
