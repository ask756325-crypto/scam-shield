import cx from "clsx";

/** ScamShield mark: a shield cut by a scanning line. */
export function LogoMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={cx("size-6", className)} aria-hidden>
      <defs>
        <linearGradient id="ssg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#3a7a5c" />
          <stop offset="1" stopColor="#4c8c82" />
        </linearGradient>
      </defs>
      <path d="M16 2.5 4.5 6.8v8.4c0 7.1 4.9 12.4 11.5 14.3 6.6-1.9 11.5-7.2 11.5-14.3V6.8L16 2.5Z" fill="url(#ssg)" />
      <path d="M16 2.5v27c6.6-1.9 11.5-7.2 11.5-14.3V6.8L16 2.5Z" fill="#000" opacity=".14" />
      <rect x="8" y="14.6" width="16" height="2" rx="1" fill="#f4f2ec" />
      <circle cx="21.5" cy="15.6" r="2.6" fill="none" stroke="#f4f2ec" strokeWidth="1.8" />
    </svg>
  );
}

export function Wordmark({ className, dark }: { className?: string; dark?: boolean }) {
  return (
    <span className={cx("inline-flex items-center gap-2 whitespace-nowrap", className)}>
      <LogoMark />
      <span className={cx("text-[15px] font-semibold tracking-[-0.02em]", dark ? "text-ink-50" : "text-ink-950")}>
        ScamShield<span className={dark ? "text-teal-400" : "text-teal-600"}> AI</span>
      </span>
    </span>
  );
}
