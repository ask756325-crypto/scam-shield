"use client";

import clsx from "clsx";
import { Loader2, X } from "lucide-react";
import Link from "next/link";
import { forwardRef, useEffect, useId, useRef, useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type TextareaHTMLAttributes } from "react";

export const cx = clsx;

// ---------------------------------------------------------------- Button

type Variant = "primary" | "secondary" | "ghost" | "danger" | "subtle";
type Size = "sm" | "md" | "lg";

const variants: Record<Variant, string> = {
  primary: "bg-forest-700 text-white hover:bg-forest-600 active:bg-forest-800 border border-forest-800/60 shadow-[inset_0_1px_0_rgba(255,255,255,0.08)]",
  secondary: "bg-paper text-ink-900 border border-ink-200 hover:border-ink-300 hover:bg-white shadow-card",
  ghost: "text-ink-700 hover:bg-ink-100 hover:text-ink-900 border border-transparent",
  subtle: "bg-ink-100 text-ink-800 hover:bg-ink-150 border border-transparent",
  danger: "bg-crit text-white hover:bg-[#912a19] border border-[#7f2415]",
};
const sizes: Record<Size, string> = {
  sm: "h-7 px-2.5 text-[12.5px] gap-1.5",
  md: "h-8.5 px-3.5 text-[13px] gap-2",
  lg: "h-10 px-4.5 text-sm gap-2",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, icon, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cx(
        "inline-flex items-center justify-center rounded-md font-medium whitespace-nowrap transition-colors duration-150 select-none",
        "disabled:opacity-55 disabled:pointer-events-none",
        variants[variant],
        sizes[size],
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
});

export function ButtonLink({ href, variant = "secondary", size = "md", className, children, icon }: { href: string; variant?: Variant; size?: Size; className?: string; children: ReactNode; icon?: ReactNode }) {
  return (
    <Link href={href} className={cx("inline-flex items-center justify-center rounded-md font-medium whitespace-nowrap transition-colors duration-150", variants[variant], sizes[size], className)}>
      {icon}
      {children}
    </Link>
  );
}

// ---------------------------------------------------------------- Card / layout

export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx("rounded-lg border border-ink-150 bg-paper shadow-card", className)} {...rest}>
      {children}
    </div>
  );
}

export function CardHeader({ title, description, actions, className }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; className?: string }) {
  return (
    <div className={cx("flex flex-wrap items-start justify-between gap-x-4 gap-y-2 border-b border-ink-150 px-4 py-3", className)}>
      <div className="min-w-[10rem] flex-1">
        <h2 className="text-[13px] font-semibold tracking-[-0.005em] text-ink-900">{title}</h2>
        {description && <p className="mt-0.5 text-[12px] text-ink-500">{description}</p>}
      </div>
      {actions && <div className="flex max-w-full flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function PageHeader({ title, description, actions, eyebrow }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; eyebrow?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 text-[11.5px] font-medium tracking-wide text-ink-500 uppercase">{eyebrow}</div>}
        <h1 className="text-[21px] font-semibold tracking-[-0.02em] text-ink-950">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-[13px] leading-relaxed text-ink-500">{description}</p>}
      </div>
      {actions && <div className="flex max-w-full min-w-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

// ---------------------------------------------------------------- Badges

type Tone = "neutral" | "forest" | "teal" | "crit" | "high" | "med" | "low" | "outline" | "dark";
const tones: Record<Tone, string> = {
  neutral: "bg-ink-100 text-ink-700 border-ink-150",
  forest: "bg-forest-50 text-forest-700 border-forest-100",
  teal: "bg-teal-100 text-teal-700 border-teal-200",
  crit: "bg-crit-bg text-crit border-[#efcdc4]",
  high: "bg-high-bg text-high border-[#f0d6bd]",
  med: "bg-med-bg text-med border-[#ebdcae]",
  low: "bg-low-bg text-low border-ink-150",
  outline: "bg-transparent text-ink-600 border-ink-200",
  dark: "bg-ink-800 text-ink-100 border-ink-700",
};

export function Badge({ tone = "neutral", children, className, dot, title }: { tone?: Tone; children: ReactNode; className?: string; dot?: boolean; title?: string }) {
  return (
    <span title={title} className={cx("inline-flex h-5 items-center gap-1 rounded-[4px] border px-1.5 text-[11.5px] font-medium whitespace-nowrap", tones[tone], className)}>
      {dot && <span className="size-1.5 rounded-full bg-current" aria-hidden />}
      {children}
    </span>
  );
}

// ---------------------------------------------------------------- Form controls

const fieldBox =
  "rounded-md border border-ink-200 bg-white px-3 text-[13px] text-ink-900 placeholder:text-ink-400 transition-colors hover:border-ink-300 focus:border-teal-500 focus:outline-none focus:ring-3 focus:ring-teal-500/15 disabled:bg-ink-50 disabled:text-ink-500 aria-[invalid=true]:border-crit aria-[invalid=true]:focus:border-crit aria-[invalid=true]:focus:ring-crit/15";
const fieldBase = cx("w-full", fieldBox);

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...rest }, ref) {
  return <input ref={ref} className={cx(fieldBase, "h-9", className)} {...rest} />;
});

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cx(fieldBase, "min-h-20 py-2 leading-relaxed", className)} {...rest} />;
});

export function Select({ className, children, ...rest }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={cx(fieldBox, className ?? "w-full", "h-9 appearance-none bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%2212%22 height=%2212%22 viewBox=%220 0 24 24%22 fill=%22none%22 stroke=%22%236a6f72%22 stroke-width=%222%22><path d=%22m6 9 6 6 6-6%22/></svg>')] bg-[right_10px_center] bg-no-repeat pr-8", className)} {...rest}>
      {children}
    </select>
  );
}

export function Field({ label, hint, error, children, htmlFor, optional }: { label: ReactNode; hint?: ReactNode; error?: string | null; children: ReactNode; htmlFor?: string; optional?: boolean }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="flex items-baseline justify-between text-[12.5px] font-medium text-ink-800">
        <span>{label}</span>
        {optional && <span className="text-[11.5px] font-normal text-ink-400">Optional</span>}
      </label>
      {children}
      {error ? <p className="text-[12px] text-crit" role="alert">{error}</p> : hint ? <p className="text-[12px] leading-snug text-ink-500">{hint}</p> : null}
    </div>
  );
}

export function Checkbox({ checked, onChange, label, description, disabled }: { checked: boolean; onChange: (v: boolean) => void; label: ReactNode; description?: ReactNode; disabled?: boolean }) {
  const id = useId();
  return (
    <label htmlFor={id} className={cx("flex cursor-pointer items-start gap-2.5", disabled && "cursor-not-allowed opacity-60")}>
      <input id={id} type="checkbox" className="mt-0.5 size-4 accent-forest-700" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>
        <span className="block text-[13px] font-medium text-ink-900">{label}</span>
        {description && <span className="block text-[12px] text-ink-500">{description}</span>}
      </span>
    </label>
  );
}

/** Chip-style list editor: Enter or comma adds a value. */
export function TagInput({ value, onChange, placeholder, id, max = 50 }: { value: string[]; onChange: (v: string[]) => void; placeholder?: string; id?: string; max?: number }) {
  const [draft, setDraft] = useState("");
  const add = (raw: string) => {
    const parts = raw.split(/[,\n]/).map((s) => s.trim()).filter(Boolean);
    if (!parts.length) return;
    const next = [...value];
    for (const p of parts) if (!next.some((x) => x.toLowerCase() === p.toLowerCase()) && next.length < max) next.push(p);
    onChange(next);
    setDraft("");
  };
  return (
    <div className={cx(fieldBase, "flex min-h-9 flex-wrap items-center gap-1 px-1.5 py-1 focus-within:border-teal-500 focus-within:ring-3 focus-within:ring-teal-500/15")}>
      {value.map((v, i) => (
        <span key={v + i} className="inline-flex h-6 items-center gap-1 rounded-[4px] bg-ink-100 pr-1 pl-2 text-[12px] text-ink-800">
          {v}
          <button type="button" aria-label={`Remove ${v}`} className="rounded-sm p-0.5 text-ink-500 hover:bg-ink-200 hover:text-ink-900" onClick={() => onChange(value.filter((_, j) => j !== i))}>
            <X className="size-3" />
          </button>
        </span>
      ))}
      <input
        id={id}
        value={draft}
        placeholder={value.length ? "" : placeholder}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault();
            add(draft);
          } else if (e.key === "Backspace" && !draft && value.length) onChange(value.slice(0, -1));
        }}
        onBlur={() => add(draft)}
        className="h-6 min-w-24 flex-1 bg-transparent px-1 text-[13px] outline-none placeholder:text-ink-400"
      />
    </div>
  );
}

// ---------------------------------------------------------------- Feedback

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cx("size-4 animate-spin text-ink-400", className)} aria-label="Loading" />;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton", className)} aria-hidden />;
}

export function EmptyState({ icon, title, description, action, className }: { icon?: ReactNode; title: ReactNode; description?: ReactNode; action?: ReactNode; className?: string }) {
  return (
    <div className={cx("flex flex-col items-center justify-center px-6 py-12 text-center", className)}>
      {icon && <div className="mb-3 grid size-10 place-items-center rounded-lg border border-ink-150 bg-ink-50 text-ink-500">{icon}</div>}
      <h3 className="text-[14px] font-semibold text-ink-900">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-[12.5px] leading-relaxed text-ink-500">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-[#efcdc4] bg-crit-bg px-3.5 py-2.5 text-[12.5px] text-crit">
      <span>{msg}</span>
      {onRetry && (
        <Button size="sm" variant="secondary" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

export function Notice({ tone = "neutral", icon, children, className }: { tone?: "neutral" | "teal" | "warn"; icon?: ReactNode; children: ReactNode; className?: string }) {
  const t = { neutral: "border-ink-150 bg-ink-50 text-ink-700", teal: "border-teal-200 bg-teal-100/60 text-teal-700", warn: "border-[#ebdcae] bg-med-bg text-med" }[tone];
  return <div className={cx("flex items-start gap-2.5 rounded-md border px-3.5 py-2.5 text-[12.5px] leading-relaxed", t, className)}>{icon && <span className="mt-0.5 shrink-0">{icon}</span>}<div className="min-w-0">{children}</div></div>;
}

export function ProgressBar({ value, className, indeterminate }: { value: number; className?: string; indeterminate?: boolean }) {
  return (
    <div className={cx("h-1.5 w-full overflow-hidden rounded-full bg-ink-100", className)} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(value * 100)}>
      <div
        className={cx("h-full rounded-full bg-gradient-to-r from-forest-600 to-teal-500 transition-[width] duration-500 ease-out", indeterminate && "animate-pulse")}
        style={{ width: `${Math.max(3, Math.min(100, value * 100))}%` }}
      />
    </div>
  );
}

export function Kbd({ children }: { children: ReactNode }) {
  return <kbd className="inline-grid h-[18px] min-w-[18px] place-items-center rounded-[4px] border border-ink-200 bg-white px-1 font-mono text-[10.5px] text-ink-600 shadow-[0_1px_0_var(--color-ink-200)]">{children}</kbd>;
}

// ---------------------------------------------------------------- Dialog

export function Dialog({ open, onClose, title, description, children, footer, width = "max-w-md" }: { open: boolean; onClose: () => void; title: ReactNode; description?: ReactNode; children?: ReactNode; footer?: ReactNode; width?: string }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const prev = document.activeElement as HTMLElement | null;
    const node = ref.current;
    const focusables = () => Array.from(node?.querySelectorAll<HTMLElement>('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])') ?? []).filter((el) => !el.hasAttribute("disabled"));
    (node?.querySelector<HTMLElement>("textarea, input, select") ?? focusables()[0])?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const f = focusables();
        if (!f.length) return;
        const first = f[0], last = f[f.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      prev?.focus();
    };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink-950/35 p-4 pt-[12vh] animate-fade-in" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div ref={ref} role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined} className={cx("w-full rounded-lg border border-ink-150 bg-paper shadow-pop animate-rise", width)}>
        <div className="flex items-start justify-between gap-4 px-5 pt-4">
          <div>
            <h2 className="text-[15px] font-semibold text-ink-950">{title}</h2>
            {description && <p className="mt-1 text-[12.5px] leading-relaxed text-ink-500">{description}</p>}
          </div>
          <button aria-label="Close" onClick={onClose} className="rounded p-1 text-ink-400 hover:bg-ink-100 hover:text-ink-800">
            <X className="size-4" />
          </button>
        </div>
        {children && <div className="px-5 py-4">{children}</div>}
        {footer && <div className="flex justify-end gap-2 border-t border-ink-150 bg-ink-50/60 px-5 py-3 rounded-b-lg">{footer}</div>}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- Segmented control

export function Segmented<T extends string>({ value, onChange, options, label }: { value: T; onChange: (v: T) => void; options: { value: T; label: ReactNode; count?: number }[]; label: string }) {
  return (
    // Scrolls inside itself on narrow screens instead of widening the page.
    <div role="radiogroup" aria-label={label} className="scrollbar-none inline-flex h-8 max-w-full items-center gap-0.5 overflow-x-auto rounded-md border border-ink-150 bg-ink-100/70 p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cx(
            "inline-flex h-full shrink-0 items-center gap-1.5 rounded-[5px] px-2.5 text-[12.5px] font-medium whitespace-nowrap transition-colors",
            value === o.value ? "bg-paper text-ink-950 shadow-card" : "text-ink-600 hover:text-ink-900",
          )}
        >
          {o.label}
          {o.count !== undefined && <span className="tabular text-[11px] text-ink-400">{o.count}</span>}
        </button>
      ))}
    </div>
  );
}
