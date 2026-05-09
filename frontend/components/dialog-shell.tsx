"use client";

import type { ReactNode } from "react";
import type { Icon } from "@phosphor-icons/react";
import { X } from "@phosphor-icons/react";

type DialogShellProps = {
  title: ReactNode;
  children: ReactNode;
  onClose?: () => void;
  footer?: ReactNode;
  icon?: Icon;
  iconClassName?: string;
  size?: "sm" | "md" | "lg" | "xl" | "2xl" | "3xl";
  panelClassName?: string;
  bodyClassName?: string;
  headerClassName?: string;
  titleClassName?: string;
  footerClassName?: string;
  headerExtras?: ReactNode;
  closeDisabled?: boolean;
  closeButtonClassName?: string;
  bodyScrollable?: boolean;
};

const sizeClassMap: Record<NonNullable<DialogShellProps["size"]>, string> = {
  sm: "max-w-[420px]",
  md: "max-w-xl",
  lg: "max-w-2xl",
  xl: "max-w-3xl",
  "2xl": "max-w-4xl",
  "3xl": "max-w-5xl",
};

export function DialogShell({
  title,
  children,
  onClose,
  footer,
  icon: Icon,
  iconClassName = "bg-[#2AABEE]/10 text-[#2AABEE]",
  size = "md",
  panelClassName = "",
  bodyClassName = "",
  headerClassName = "",
  titleClassName = "",
  footerClassName = "",
  headerExtras,
  closeDisabled = false,
  closeButtonClassName = "",
  bodyScrollable = true,
}: DialogShellProps) {
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm sm:p-6">
      <div
        className={`dialog-panel w-full ${sizeClassMap[size]} flex flex-col overflow-hidden animate-scale-in ${panelClassName}`}
        onClick={(e) => e.stopPropagation()}
      >
        <header
          className={`dialog-header flex items-center justify-between gap-4 px-6 py-4 ${headerClassName}`}
        >
          <div className={`flex min-w-0 items-center gap-3 ${titleClassName}`}>
            {Icon ? (
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl ${iconClassName}`}>
                <Icon weight="fill" size={18} />
              </div>
            ) : null}
            <div className="min-w-0 text-base font-bold tracking-tight text-main">{title}</div>
            {headerExtras}
          </div>

          {onClose ? (
            <button
              type="button"
              onClick={onClose}
              disabled={closeDisabled}
              className={`dialog-close-btn action-btn disabled:opacity-35 ${closeButtonClassName}`}
            >
              <X weight="bold" size={20} />
            </button>
          ) : null}
        </header>

        <div
          className={`dialog-body flex-1 min-h-0 ${bodyScrollable ? "overflow-y-auto" : "overflow-visible"} p-6 ${bodyClassName}`}
        >
          {children}
        </div>

        {footer ? (
          <footer className={`dialog-footer px-6 py-4 ${footerClassName}`}>{footer}</footer>
        ) : null}
      </div>
    </div>
  );
}
