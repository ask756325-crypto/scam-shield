"use client";

import {
  Gavel,
  Network,
  Globe,
  Activity,
  AppWindow,
  Building2,
  ChevronsUpDown,
  ClipboardCheck,
  History,
  LayoutDashboard,
  LogOut,
  MailWarning,
  Menu,
  Plug,
  Plus,
  Radar,
  ScanSearch,
  Settings,
  Users,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, beginSignOut } from "@/lib/api";
import { sourceLabel } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Scan, SourceHealth } from "@/lib/types";
import { Wordmark } from "../logo";
import { useToast } from "../toast";
import { Badge, Button, ProgressBar, cx } from "../ui";
import { SOURCE_HEALTH_LABEL, SOURCE_STATE_LABEL, sourceDot, StatusDot } from "./bits";
import { useBrands, useScans, useSession } from "./providers";

const NAV: { section: string; items: { href: string; label: string; icon: typeof Activity; badge?: "review" }[] }[] = [
  {
    section: "Monitor",
    items: [
      { href: "/app", label: "Overview", icon: LayoutDashboard },
      { href: "/app/social", label: "Social Monitoring", icon: Users },
      { href: "/app/apps", label: "App Store Monitoring", icon: AppWindow },
      { href: "/app/domains", label: "Domain Monitoring", icon: Globe },
    ],
  },
  {
    section: "Investigate",
    items: [
      { href: "/app/review", label: "Review Queue", icon: ClipboardCheck, badge: "review" },
      { href: "/app/investigations", label: "Investigations", icon: ScanSearch },
      { href: "/app/campaigns", label: "Campaigns", icon: Network },
      { href: "/app/scans", label: "Scan History", icon: History },
      { href: "/app/takedowns", label: "Takedowns", icon: Gavel },
    ],
  },
  {
    section: "Configure",
    items: [
      { href: "/app/brands", label: "Brand Profiles", icon: Building2 },
      { href: "/app/sources", label: "Sources & Integrations", icon: Plug },
      { href: "/app/settings", label: "Settings", icon: Settings },
    ],
  },
];

function isActive(pathname: string, href: string) {
  return href === "/app" ? pathname === "/app" : pathname === href || pathname.startsWith(href + "/");
}

function BrandSwitcher() {
  const { brands, selected, select, loading } = useBrands();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);
  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex w-full items-center gap-2.5 rounded-md border border-ink-700 bg-ink-850 px-2.5 py-2 text-left transition-colors hover:border-ink-600"
      >
        <span className="grid size-6 shrink-0 place-items-center rounded-[5px] bg-forest-700 text-[11px] font-semibold text-forest-100">
          {selected ? selected.name.slice(0, 1).toUpperCase() : "—"}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-[10.5px] tracking-wide text-ink-400 uppercase">Brand</span>
          <span className="block truncate text-[13px] font-medium text-ink-100">{loading ? "Loading…" : selected?.name ?? "No brand yet"}</span>
        </span>
        {selected?.is_demo && <Badge tone="med" className="!h-4 !px-1 !text-[10px]">Demo</Badge>}
        <ChevronsUpDown className="size-3.5 text-ink-400" />
      </button>
      {open && (
        <div role="listbox" className="absolute top-full right-0 left-0 z-30 mt-1 overflow-hidden rounded-md border border-ink-700 bg-ink-850 py-1 shadow-pop animate-fade-in">
          {brands.map((b) => (
            <button
              key={b.id}
              role="option"
              aria-selected={b.id === selected?.id}
              onClick={() => {
                select(b.id);
                setOpen(false);
              }}
              className={cx("flex w-full items-center gap-2 px-3 py-1.5 text-left text-[13px] text-ink-200 hover:bg-ink-800", b.id === selected?.id && "bg-ink-800 text-white")}
            >
              <span className="min-w-0 flex-1 truncate">{b.name}</span>
              {b.is_demo && <span className="text-[10.5px] text-[#d9b65a]">Demo</span>}
              {!!b.stats.open_review && <span className="tabular text-[11px] text-ink-400">{b.stats.open_review}</span>}
            </button>
          ))}
          <div className="my-1 border-t border-ink-700" />
          <Link href="/app/brands/new" onClick={() => setOpen(false)} className="flex items-center gap-2 px-3 py-1.5 text-[13px] text-ink-300 hover:bg-ink-800 hover:text-white">
            <Plus className="size-3.5" /> New brand profile
          </Link>
        </div>
      )}
    </div>
  );
}

function SourceStrip() {
  const { version } = useScans();
  const { data, reload } = useApi<{ sources: SourceHealth[] }>("/sources", undefined, { pollMs: 60000 });
  useEffect(() => {
    if (version) reload(true);
  }, [version, reload]);
  const live = (data?.sources ?? []).filter((s) => s.name !== "demo");
  return (
    <Link href="/app/sources" className="block rounded-md border border-ink-800 px-2.5 py-2 transition-colors hover:border-ink-700 hover:bg-ink-850">
      <div className="mb-1.5 flex items-center justify-between text-[10.5px] tracking-wide text-ink-400 uppercase">
        <span>Source health</span>
        <Radar className="size-3" />
      </div>
      <ul className="space-y-1">
        {live.map((s) => (
          <li key={s.name} className="flex items-center gap-2 text-[12px] text-ink-300" title={`${SOURCE_STATE_LABEL[s.state]} · ${SOURCE_HEALTH_LABEL[s.health] ?? s.health}${s.health_detail ? " — " + s.health_detail : ""}`}>
            <StatusDot status={sourceDot(s)} />
            <span className="flex-1 truncate">{sourceLabel(s.name)}</span>
            <span className="text-[11px] text-ink-500">{!s.enabled ? "Off" : s.state === "unavailable" ? (s.health === "rate_limited" ? "Rate limited" : "Unavailable") : SOURCE_HEALTH_LABEL[s.health] ?? s.health}</span>
          </li>
        ))}
        {!data && <li className="text-[12px] text-ink-500">Checking…</li>}
      </ul>
    </Link>
  );
}

export function ScanNow({ compact }: { compact?: boolean }) {
  const { selected } = useBrands();
  const { active, startScan } = useScans();
  const [open, setOpen] = useState(false);
  const [starting, setStarting] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const scan: Scan | undefined = active.find((s) => s.brand_id === selected?.id);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);
  if (!selected) return null;
  if (!scan)
    return (
      <Button
        variant="primary"
        size={compact ? "sm" : "md"}
        loading={starting}
        icon={<Radar className="size-3.5" />}
        onClick={async () => {
          setStarting(true);
          const s = await startScan(selected.id);
          setStarting(false);
          if (s) setOpen(true);
        }}
      >
        Scan now
      </Button>
    );
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen((o) => !o)} className="flex h-8.5 items-center gap-2.5 rounded-md border border-teal-200 bg-teal-100/60 px-3 text-[12.5px] font-medium text-teal-700" aria-expanded={open}>
        <StatusDot status="running" />
        <span className="hidden sm:inline">{scan.stage}</span>
        <span className="tabular">{Math.round(scan.progress * 100)}%</span>
      </button>
      {open && (
        <div className="absolute top-full right-0 z-40 mt-1.5 w-[340px] rounded-lg border border-ink-150 bg-paper p-3.5 shadow-pop animate-rise">
          <div className="mb-2 flex items-center justify-between">
            <div className="text-[13px] font-semibold text-ink-900">Scanning {scan.brand_name}</div>
            <span className="tabular text-[12px] text-ink-500">{Math.round(scan.progress * 100)}%</span>
          </div>
          <ProgressBar value={scan.progress} />
          <div className="mt-1.5 text-[12px] text-ink-500">{scan.stage}</div>
          <ul className="mt-3 space-y-1.5 border-t border-ink-150 pt-3">
            {scan.sources.map((s) => (
              <li key={s.source} className="flex items-center gap-2 text-[12.5px]">
                <StatusDot status={s.status} />
                <span className="flex-1 text-ink-800">{sourceLabel(s.source)}</span>
                <span className="tabular text-[11.5px] text-ink-500">
                  {s.queries_done}/{s.queries_total} queries · {s.candidates}
                </span>
              </li>
            ))}
          </ul>
          <Link href={`/app/scans/${scan.id}`} className="mt-3 block text-[12px] font-medium text-teal-700 hover:underline">
            Open scan details →
          </Link>
        </div>
      )}
    </div>
  );
}

function VerifyEmailBanner() {
  const { session } = useSession();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  if (!session || session.user.email_verified || dismissed) return null;
  return (
    <div role="status" className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-[#ebdcae] bg-med-bg px-4 py-2 text-[12.5px] text-med md:px-6">
      <MailWarning className="size-4 shrink-0" />
      <span className="flex-1">
        Verify <span className="font-medium">{session.user.email}</span> to confirm you own this address. Check your inbox for the link.
      </span>
      <button
        className="font-medium underline underline-offset-2 disabled:opacity-50"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          try {
            const r = await api<{ delivery?: string }>("/auth/resend-verification", { method: "POST" });
            toast({
              tone: "success",
              title: "Verification link sent",
              description: r.delivery === "server_log" ? "Development mode: the link is in the backend server log." : r.delivery === "unavailable" ? "Email isn’t configured on this deployment — ask an administrator." : undefined,
            });
          } catch (e) {
            toast({ tone: "error", title: "Couldn’t resend", description: (e as Error).message });
          } finally {
            setBusy(false);
          }
        }}
      >
        Resend link
      </button>
      <button aria-label="Dismiss for now" onClick={() => setDismissed(true)} className="rounded p-0.5 hover:bg-[#ebdcae]">
        <X className="size-3.5" />
      </button>
    </div>
  );
}

function UserMenu() {
  const { session } = useSession();
  return (
    <div className="flex items-center gap-2.5 rounded-md px-1.5 py-1.5">
      <span className="grid size-7 place-items-center rounded-full bg-ink-700 text-[11px] font-semibold text-ink-200">
        {(session?.user.name ?? "?").slice(0, 1).toUpperCase()}
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[12.5px] font-medium text-ink-200">{session?.user.name ?? "…"}</div>
        <div className="truncate text-[11px] text-ink-500">{session?.organization?.name}</div>
      </div>
      <button
        aria-label="Sign out"
        title="Sign out"
        className="rounded p-1.5 text-ink-400 hover:bg-ink-800 hover:text-ink-100"
        onClick={async () => {
          beginSignOut();
          await api("/auth/logout", { method: "POST" }).catch(() => {});
          window.location.replace("/signin?signedout=1"); // full reload drops all in-memory app state
        }}
      >
        <LogOut className="size-3.5" />
      </button>
    </div>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { brands } = useBrands();
  const reviewCount = brands.reduce((n, b) => n + (b.stats.open_review ?? 0), 0);
  return (
    <div className="flex h-full flex-col gap-4 bg-ink-900 px-3 py-4">
      <Link href="/app" className="px-1.5" onClick={onNavigate}>
        <Wordmark dark />
      </Link>
      <BrandSwitcher />
      <nav aria-label="Main" className="scrollbar-thin -mx-1 flex-1 space-y-4 overflow-y-auto px-1">
        {NAV.map((g) => (
          <div key={g.section}>
            <div className="mb-1 px-2 text-[10.5px] font-medium tracking-[0.08em] text-ink-500 uppercase">{g.section}</div>
            <ul className="space-y-px">
              {g.items.map((it) => {
                const active = isActive(pathname, it.href);
                const Icon = it.icon;
                return (
                  <li key={it.href}>
                    <Link
                      href={it.href}
                      onClick={onNavigate}
                      aria-current={active ? "page" : undefined}
                      className={cx(
                        "group relative flex h-8 items-center gap-2.5 rounded-md px-2 text-[13px] transition-colors",
                        active ? "bg-ink-800 font-medium text-white" : "text-ink-300 hover:bg-ink-850 hover:text-ink-100",
                      )}
                    >
                      {active && <span className="absolute top-1.5 bottom-1.5 -left-1 w-[2px] rounded-full bg-teal-400" />}
                      <Icon className={cx("size-4", active ? "text-teal-400" : "text-ink-500 group-hover:text-ink-300")} />
                      <span className="flex-1">{it.label}</span>
                      {it.badge === "review" && reviewCount > 0 && <span className="tabular rounded-[4px] bg-ink-700 px-1.5 text-[11px] text-ink-200">{reviewCount}</span>}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
      <SourceStrip />
      <div className="border-t border-ink-800 pt-2">
        <UserMenu />
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const { selected } = useBrands();
  const pathname = usePathname();
  useEffect(() => setMobileOpen(false), [pathname]);
  return (
    <div className="min-h-dvh">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-paper focus:px-3 focus:py-2">
        Skip to content
      </a>
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[248px] border-r border-ink-950 lg:block">
        <Sidebar />
      </aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-ink-950/50 animate-fade-in" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-[264px] animate-rise">
            <Sidebar onNavigate={() => setMobileOpen(false)} />
            <button aria-label="Close menu" onClick={() => setMobileOpen(false)} className="absolute top-4 -right-10 rounded bg-ink-900 p-1.5 text-ink-200">
              <X className="size-4" />
            </button>
          </aside>
        </div>
      )}
      <div className="lg:pl-[248px]">
        <header className="sticky top-0 z-20 flex h-13 items-center gap-3 border-b border-ink-150 bg-ink-50/85 px-4 backdrop-blur-md md:px-6">
          <button aria-label="Open menu" className="rounded p-1.5 text-ink-600 hover:bg-ink-100 lg:hidden" onClick={() => setMobileOpen(true)}>
            <Menu className="size-4.5" />
          </button>
          <div className="flex min-w-0 flex-1 items-center gap-2 text-[12.5px] text-ink-500">
            {selected ? (
              <>
                <span className="hidden sm:inline">Monitoring</span>
                <span className="truncate font-medium text-ink-900">{selected.name}</span>
                {selected.is_demo && <Badge tone="med" title="Demo brand — synthetic data">Demo<span className="hidden sm:inline"> · synthetic data</span></Badge>}
                {selected.schedule && selected.schedule.state !== "disabled" && (
                  <Link href={`/app/brands/${selected.id}?tab=monitoring`} className="hidden items-center gap-1 text-[11.5px] text-ink-500 hover:text-ink-800 md:inline-flex" title="Monitoring schedule">
                    <History className="size-3" /> {selected.schedule.state === "paused" ? "Schedule paused" : selected.schedule.description}
                  </Link>
                )}
              </>
            ) : (
              <span>No brand selected</span>
            )}
          </div>
          {pathname !== "/app" && <ScanNow />}
        </header>
        <VerifyEmailBanner />
        <main id="main" className="mx-auto w-full max-w-[1320px] px-4 py-6 md:px-6 md:py-7">
          {children}
        </main>
      </div>
    </div>
  );
}
