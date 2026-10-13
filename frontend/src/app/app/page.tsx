"use client";

import { Beaker, Building2, FileText, Radar } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { CandidatesChart } from "@/components/app/charts";
import {
  DetectionsTable,
  MetricsStrip,
  RANGES,
  RecentScans,
  ReviewSummary,
  ScanStatusPanel,
  SeverityPlatformMatrix,
  SourceHealthCard,
  rangeLabel,
  type RangeValue,
} from "@/components/app/dashboard";
import { StatusDot } from "@/components/app/bits";
import { useBrands, useScans } from "@/components/app/providers";
import { ScanNow } from "@/components/app/shell";
import { useToast } from "@/components/toast";
import { Badge, Button, ButtonLink, Card, CardHeader, EmptyState, ErrorState, PageHeader, Segmented, Select, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { relTime, sourceLabel } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Brand, Dashboard } from "@/lib/types";

function Onboarding() {
  const { reloadBrands, select } = useBrands();
  const toast = useToast();
  const [loading, setLoading] = useState(false);
  return (
    <div className="mx-auto max-w-3xl pt-6">
      <PageHeader eyebrow="Get started" title="Set up your first brand profile" description="ScamShield compares what it finds on public sources against a brand profile: names, official domains, accounts, apps and logo." />
      <div className="grid gap-4 md:grid-cols-2">
        <Card className="p-5">
          <Building2 className="size-5 text-forest-600" />
          <h3 className="mt-3 text-[14px] font-semibold text-ink-900">Create a brand profile</h3>
          <p className="mt-1 text-[12.5px] leading-relaxed text-ink-500">Add your brand’s names, official domains, social handles and app IDs, then run a live scan of Bluesky, Mastodon, the App Store and Google Play.</p>
          <ButtonLink href="/app/brands/new" variant="primary" className="mt-4">New brand profile</ButtonLink>
        </Card>
        <Card className="p-5">
          <Beaker className="size-5 text-med" />
          <h3 className="mt-3 text-[14px] font-semibold text-ink-900">Explore with the demo brand</h3>
          <p className="mt-1 text-[12.5px] leading-relaxed text-ink-500">Load “Northvale Pay”, a fictional brand with a clearly labelled synthetic dataset. It runs through the same detection engine and works offline.</p>
          <Button
            className="mt-4"
            loading={loading}
            onClick={async () => {
              setLoading(true);
              try {
                const b = await api<Brand>("/demo/brand", { method: "POST" });
                await reloadBrands();
                select(b.id);
                toast({ tone: "success", title: "Demo brand created", description: "Run a scan to generate synthetic findings." });
              } catch (e) {
                toast({ tone: "error", title: "Could not create demo brand", description: (e as Error).message });
              } finally {
                setLoading(false);
              }
            }}
          >
            Load demo brand
          </Button>
        </Card>
      </div>
    </div>
  );
}


function useRange(): [RangeValue, (r: RangeValue) => void] {
  const params = useSearchParams();
  const router = useRouter();
  const pathname = usePathname();
  const raw = params.get("range");
  const range = (RANGES.some((r) => r.value === raw) ? raw : "30") as RangeValue;
  const set = (r: RangeValue) => {
    const p = new URLSearchParams(params.toString());
    p.set("range", r);
    router.replace(`${pathname}?${p.toString()}`, { scroll: false });
  };
  return [range, set];
}

function Header({ d, range, setRange }: { d?: Dashboard; range: RangeValue; setRange: (r: RangeValue) => void }) {
  const { brands, selected, select } = useBrands();
  const { active } = useScans();
  const running = active.find((s) => s.brand_id === selected?.id);
  const last = d?.last_completed_scan;
  const health = d?.source_health ?? [];
  const enabled = health.filter((h) => h.enabled);
  const ok = enabled.filter((h) => h.status === "ok").length;
  return (
    <div className="mb-4 flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <label htmlFor="brand-select" className="sr-only">Brand</label>
          <Select
            id="brand-select"
            value={selected?.id ?? ""}
            onChange={(e) => select(Number(e.target.value))}
            className="h-9 w-auto max-w-full border-transparent !bg-transparent pl-0 text-[21px] font-semibold tracking-[-0.02em] text-ink-950 hover:border-ink-200 focus:pl-2"
          >
            {brands.map((b) => (
              <option key={b.id} value={b.id}>{b.name}{b.is_demo ? " (demo)" : ""}</option>
            ))}
          </Select>
          {selected?.is_demo && <Badge tone="med">Demo · synthetic data</Badge>}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12.5px] text-ink-500">
          <span className="inline-flex items-center gap-1.5">
            {running ? (
              <><StatusDot status="running" /> Scanning now · {Math.round(running.progress * 100)}%</>
            ) : last ? (
              <>
                <StatusDot status={last.status} />
                Last completed scan{" "}
                <a href={`/app/scans/${last.id}`} className="text-ink-800 hover:underline">#{last.id}</a> · {relTime(last.finished_at)}
                {last.status === "partial" && <span className="text-med">· some sources failed</span>}
              </>
            ) : (
              "No completed scans yet"
            )}
          </span>
          {enabled.length > 0 && (
            <a href="/app/sources" className="inline-flex items-center gap-1.5 hover:text-ink-800" title={enabled.map((h) => `${h.label}: ${h.status}`).join("\n")}>
              <span className="inline-flex gap-0.5" aria-hidden>
                {enabled.map((h) => <StatusDot key={h.name} status={h.status} />)}
              </span>
              {ok}/{enabled.length} sources operational
            </a>
          )}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Segmented label="Date range" value={range} onChange={setRange} options={RANGES.map((r) => ({ value: r.value, label: r.label }))} />
        <a href={`/api/reports/executive?days=${range === "all" ? 365 : range === "1" ? 7 : range}`} target="_blank" rel="noopener noreferrer"
          className="inline-flex h-8 items-center gap-1.5 rounded-md border border-ink-200 bg-white px-2.5 text-[12.5px] font-medium text-ink-700 hover:border-ink-300"
          title="Print-ready summary for the selected period (all brands)">
          <FileText className="size-3.5" /> Executive report
        </a>
        <ScanNow />
      </div>
    </div>
  );
}

function OverviewInner() {
  const { brands, selected, loading: brandsLoading } = useBrands();
  const { version, active, startScan } = useScans();
  const [range, setRange] = useRange();
  const { data, error, loading, reload } = useApi<Dashboard>(selected ? "/dashboard" : null, {
    brand_id: selected?.id,
    days: range === "all" ? undefined : range,
  });
  const running = active.find((s) => s.brand_id === selected?.id);

  // Refresh after each tracked scan finishes, and every few seconds while one is running.
  useEffect(() => {
    if (version) reload(true);
  }, [version, reload]);
  useEffect(() => {
    if (!running) return;
    const id = setInterval(() => reload(true), 4000);
    return () => clearInterval(id);
  }, [running, reload]);

  if (brandsLoading) return <Skeleton className="h-64" />;
  if (!brands.length) return <Onboarding />;
  if (!selected) return null;

  return (
    <div className="animate-fade-in space-y-4">
      <Header d={data} range={range} setRange={setRange} />
      <ScanStatusPanel brandId={selected.id} />
      {error && <ErrorState error={error} onRetry={() => reload()} />}
      {!data ? (
        loading && (
          <div className="space-y-4">
            <Skeleton className="h-[92px]" />
            <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_340px]"><Skeleton className="h-80" /><Skeleton className="h-80" /></div>
          </div>
        )
      ) : data.metrics.scans_total === 0 && !running ? (
        <Card>
          <EmptyState
            icon={<Radar className="size-5" />}
            title="Run the first scan"
            description={
              selected.is_demo
                ? "The demo brand scans a bundled synthetic dataset — no network needed. Results are labelled “Simulated”."
                : "ScamShield will query each enabled source with bounded look-alike search terms derived from this brand’s names and aliases."
            }
            action={<Button variant="primary" icon={<Radar className="size-3.5" />} onClick={() => startScan(selected.id)}>Scan now</Button>}
          />
        </Card>
      ) : (
        <>
          <MetricsStrip d={data} brandId={selected.id} range={range} />
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
            <DetectionsTable brandId={selected.id} range={range} />
            <div className="min-w-0 space-y-4">
              <ReviewSummary d={data} />
              <SourceHealthCard d={data} />
            </div>
          </div>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_340px]">
            <SeverityPlatformMatrix d={data} range={range} />
            <Card className="min-w-0">
              <CardHeader title="Candidates per scan" description={`Unique accounts and apps collected · ${rangeLabel(range)}`} />
              <div className="px-2 pt-2 pb-1">
                {data.scan_series.length ? (
                  <CandidatesChart series={data.scan_series} />
                ) : (
                  <EmptyState title="No completed scans in this period" className="py-10" />
                )}
              </div>
            </Card>
            <div className="lg:col-span-2 xl:col-span-1">
              <RecentScans d={data} range={range} />
            </div>
          </div>
          <p className="text-[11.5px] text-ink-400">
            “Period” figures cover {rangeLabel(range)}; “now” figures are current state. Scores are heuristic evidence for triage, not probabilities.
            {data.unavailable_sources.length > 0 && <> Findings from {data.unavailable_sources.map(sourceLabel).join(", ")} may be stale until the source recovers.</>}
          </p>
        </>
      )}
    </div>
  );
}

export default function OverviewPage() {
  return (
    <Suspense fallback={<Skeleton className="h-64" />}>
      <OverviewInner />
    </Suspense>
  );
}
