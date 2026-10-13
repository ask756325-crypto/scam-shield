"use client";

import clsx from "clsx";
import { ArrowRight, Menu, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Wordmark } from "../logo";
import { NAV_LINKS } from "./links";


let sessionCheck: Promise<boolean> | null = null;

/** Asks the backend whether the visitor has a valid session (cookie presence alone is not trusted).
 *  One request per page load, shared by every CTA. */
export function useSignedIn() {
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  useEffect(() => {
    let alive = true;
    sessionCheck ??= fetch("/api/auth/session", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : { authenticated: false }))
      .then((d: { authenticated?: boolean }) => !!d.authenticated)
      .catch(() => false);
    sessionCheck.then((v) => alive && setSignedIn(v));
    return () => {
      alive = false;
    };
  }, []);
  return signedIn;
}

export function PrimaryCta({ className, size = "md", tone = "light" }: { className?: string; size?: "md" | "lg"; tone?: "light" | "forest" }) {
  const signedIn = useSignedIn();
  return (
    <Link
      href={signedIn ? "/app" : "/signup"}
      className={clsx(
        "group inline-flex items-center justify-center gap-2 rounded-md font-medium whitespace-nowrap transition-colors",
        size === "lg" ? "h-11 px-5 text-[14px]" : "h-9 px-3.5 text-[13px]",
        tone === "forest"
          ? "bg-forest-600 text-white shadow-[inset_0_1px_0_rgba(255,255,255,0.12)] hover:bg-forest-500"
          : "bg-ink-50 text-ink-950 hover:bg-white",
        className,
      )}
    >
      {signedIn ? "Open dashboard" : "Start monitoring"}
      <ArrowRight className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" aria-hidden />
    </Link>
  );
}

export function MarketingNav() {
  const signedIn = useSignedIn();
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!open) return;
    menuRef.current?.querySelector<HTMLElement>("a")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open]);

  useEffect(() => {
    const mq = window.matchMedia("(min-width: 1024px)");
    const close = () => mq.matches && setOpen(false);
    mq.addEventListener("change", close);
    return () => mq.removeEventListener("change", close);
  }, []);

  return (
    <header
      className={clsx(
        "fixed inset-x-0 top-0 z-40 transition-[background-color,border-color,backdrop-filter] duration-300",
        scrolled || open ? "border-b border-white/[0.06] bg-ink-900/85 backdrop-blur-md" : "border-b border-transparent",
      )}
    >
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-paper focus:px-3 focus:py-2 focus:text-ink-900">
        Skip to content
      </a>
      <div className="mx-auto flex h-16 max-w-[1200px] items-center justify-between gap-6 px-5 md:px-8">
        <Link href="/" aria-label="ScamShield AI home" className="rounded-md">
          <Wordmark dark />
        </Link>
        <nav aria-label="Primary" className="hidden items-center gap-1 lg:flex">
          {NAV_LINKS.map((l) => (
            <a key={l.href} href={l.href} className="rounded-md px-3 py-1.5 text-[13px] whitespace-nowrap text-ink-300 transition-colors hover:bg-white/[0.05] hover:text-white">
              {l.label}
            </a>
          ))}
        </nav>
        <div className="hidden items-center gap-2 lg:flex">
          {signedIn === false && (
            <Link href="/signin" className="rounded-md px-3 py-1.5 text-[13px] whitespace-nowrap text-ink-200 transition-colors hover:text-white">
              Sign in
            </Link>
          )}
          <PrimaryCta />
        </div>
        <button
          ref={buttonRef}
          className="grid size-9 place-items-center rounded-md text-ink-200 hover:bg-white/[0.06] lg:hidden"
          aria-label={open ? "Close menu" : "Open menu"}
          aria-expanded={open}
          aria-controls="mobile-menu"
          onClick={() => setOpen((o) => !o)}
        >
          {open ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
      </div>
      {open && (
        <div id="mobile-menu" ref={menuRef} className="h-[calc(100dvh-4rem)] overflow-y-auto border-t border-white/[0.06] bg-ink-900 px-5 pt-4 pb-8 lg:hidden animate-fade-in">
          <nav aria-label="Mobile" className="flex flex-col">
            {NAV_LINKS.map((l) => (
              <a key={l.href} href={l.href} onClick={() => setOpen(false)} className="border-b border-white/[0.06] py-3.5 text-[16px] text-ink-100">
                {l.label}
              </a>
            ))}
          </nav>
          <div className="mt-6 flex flex-col gap-2">
            <PrimaryCta size="lg" tone="forest" />
            {signedIn === false && (
              <Link href="/signin" className="inline-flex h-11 items-center justify-center rounded-md border border-ink-700 text-[14px] text-ink-100">
                Sign in
              </Link>
            )}
          </div>
        </div>
      )}
    </header>
  );
}
