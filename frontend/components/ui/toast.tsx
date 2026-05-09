"use client";

import { CheckCircle, Info, X, XCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";

interface ToastProps {
  message: string;
  type?: "success" | "error" | "info";
  duration?: number;
  onClose: () => void;
}

function getTone(type: NonNullable<ToastProps["type"]>) {
  switch (type) {
    case "success":
      return {
        accent: "#10b981",
        iconWrap: "bg-emerald-50 text-emerald-600",
        Icon: CheckCircle,
      };
    case "error":
      return {
        accent: "#f43f5e",
        iconWrap: "bg-rose-50 text-rose-600",
        Icon: XCircle,
      };
    default:
      return {
        accent: "#2AABEE",
        iconWrap: "bg-sky-50 text-[#2AABEE]",
        Icon: Info,
      };
  }
}

export function Toast({
  message,
  type = "info",
  duration = 4000,
  onClose,
}: ToastProps) {
  const [isExiting, setIsExiting] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setIsExiting(true);
      window.setTimeout(onClose, 220);
    }, duration);

    return () => window.clearTimeout(timer);
  }, [duration, onClose]);

  const tone = getTone(type);
  const Icon = tone.Icon;

  return (
    <div
      className={`w-full max-w-[360px] overflow-hidden rounded-2xl border transition-all duration-200 ${
        isExiting ? "translate-y-2 opacity-0" : "translate-y-0 opacity-100"
      }`}
      style={{
        background: "var(--glass-bg)",
        borderColor: "var(--glass-border)",
        color: "var(--text-main)",
        boxShadow: "0 18px 40px rgba(15, 23, 42, 0.14)",
      }}
    >
      <div className="flex items-center gap-3 p-3.5">
        <div
          className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${tone.iconWrap}`}
          style={{ boxShadow: `inset 0 0 0 1px ${tone.accent}1f` }}
        >
          <Icon weight="fill" size={18} />
        </div>

        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-medium leading-5 text-inherit">{message}</div>
        </div>

        <button
          type="button"
          onClick={() => {
            setIsExiting(true);
            window.setTimeout(onClose, 220);
          }}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border text-slate-400 transition-colors hover:text-slate-700"
          style={{
            borderColor: "var(--glass-border)",
            background: "transparent",
          }}
          aria-label="Close notification"
        >
          <X weight="bold" size={14} />
        </button>
      </div>
    </div>
  );
}

interface ToastContainerProps {
  toasts: Array<{ id: string; message: string; type: "success" | "error" | "info" }>;
  removeToast: (id: string) => void;
}

export function ToastContainer({ toasts, removeToast }: ToastContainerProps) {
  return (
    <div className="pointer-events-none fixed bottom-5 right-5 z-[1000] flex w-[calc(100vw-24px)] max-w-sm flex-col gap-3 sm:bottom-6 sm:right-6">
      {toasts.map((toast) => (
        <div key={toast.id} className="pointer-events-auto">
          <Toast
            message={toast.message}
            type={toast.type}
            onClose={() => removeToast(toast.id)}
          />
        </div>
      ))}
    </div>
  );
}

export function useToast() {
  const [toasts, setToasts] = useState<
    Array<{ id: string; message: string; type: "success" | "error" | "info" }>
  >([]);

  const addToast = useCallback((
    message: string,
    type: "success" | "error" | "info" = "info",
  ) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    setToasts((prev) => [...prev, { id, message, type }]);
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id));
  }, []);

  return { toasts, addToast, removeToast };
}
