"use client";

import { CheckCircle2, AlertTriangle, Info, X } from "lucide-react";
import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { cx } from "./ui";

type ToastTone = "success" | "error" | "info";
interface Toast { id: number; tone: ToastTone; title: string; description?: string }

const ToastCtx = createContext<(t: Omit<Toast, "id">) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setToasts((x) => [...x.slice(-3), { ...t, id }]);
    setTimeout(() => setToasts((x) => x.filter((y) => y.id !== id)), t.tone === "error" ? 7000 : 4200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed right-4 bottom-4 z-[60] flex w-[340px] max-w-[calc(100vw-2rem)] flex-col gap-2">
        {toasts.map((t) => {
          const Icon = t.tone === "success" ? CheckCircle2 : t.tone === "error" ? AlertTriangle : Info;
          return (
            <div key={t.id} className="pointer-events-auto flex items-start gap-2.5 rounded-lg border border-ink-700 bg-ink-900 px-3.5 py-3 text-ink-100 shadow-pop animate-rise">
              <Icon className={cx("mt-0.5 size-4 shrink-0", t.tone === "success" ? "text-teal-400" : t.tone === "error" ? "text-[#f0907d]" : "text-ink-300")} />
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-medium">{t.title}</div>
                {t.description && <div className="mt-0.5 text-[12px] leading-snug text-ink-300">{t.description}</div>}
              </div>
              <button aria-label="Dismiss" className="text-ink-400 hover:text-ink-100" onClick={() => setToasts((x) => x.filter((y) => y.id !== t.id))}>
                <X className="size-3.5" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastCtx.Provider>
  );
}

export const useToast = () => useContext(ToastCtx);
