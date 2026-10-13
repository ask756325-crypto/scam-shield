"use client";

import { Link2, Network } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { PlatformGlyph, RiskBadge, StatusBadge } from "@/components/app/bits";
import { useBrands, useScans } from "@/components/app/providers";
import { Badge, Card, EmptyState, ErrorState, Notice, PageHeader, Segmented, Skeleton } from "@/components/ui";
import { relTime, sourceLabel } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { FindingStatus, RiskLevel } from "@/lib/types";

interface Campaign {
  id: string; label: string; size: number; max_risk: RiskLevel; platforms: string[]; confirmed: number; open: number; synthetic: boolean;
  first_observed_at: string; last_observed_at: string;
  shared_indicators: { kind: string; label: string; value: string; findings: number; strong: boolean }[];
  findings: { finding_id: number; name: string; handle: string | null; kind: string; platform: string; brand_name: string; risk_level: RiskLevel; risk_score: number; status: FindingStatus; source_type: string }[];
}

export default function CampaignsPage() {
  const { selected } = useBrands();
  const { version } = useScans();
  const [scope, setScope] = useState<"brand" | "all">("brand");
  const { data, error, loading, reload } = useApi<{ campaigns: Campaign[]; ignored_common_indicators: number; note: string }>("/campaigns", { brand_id: scope === "brand" ? selected?.id : undefined });
  useEffect(() => {
    if (version) reload(true);
  }, [version, reload]);

  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader
        eyebrow="Investigate"
        title="Possible campaigns"
        description="Findings grouped because they share the same observable values: a phishing link, phone number, email, messaging contact, developer account, or a handle reused across platforms."
        actions={<Segmented label="Scope" value={scope} onChange={setScope} options={[{ value: "brand", label: selected?.name ?? "This brand" }, { value: "all", label: "All brands" }]} />}
      />
      <Notice tone="teal">A shared value is an observation worth investigating. It does not by itself prove the accounts have the same owner or are coordinated.</Notice>
      {error && <ErrorState error={error} onRetry={() => reload()} />}
      {loading && !data ? <Skeleton className="h-48" /> : data && data.campaigns.length === 0 ? (
        <Card><EmptyState icon={<Network className="size-5" />} title="No linked findings" description="No two findings share a strong indicator (or two weaker ones). Groups appear here as scans collect more evidence." /></Card>
      ) : (
        data?.campaigns.map((c) => (
          <Card key={c.id} className="overflow-hidden">
            <div className="flex flex-wrap items-start justify-between gap-3 border-b border-ink-150 px-4 py-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-[14px] font-semibold text-ink-950">{c.label}</h2>
                  {c.synthetic && <Badge tone="med">Synthetic</Badge>}
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12px] text-ink-500">
                  <span className="inline-flex items-center gap-1">{c.platforms.map((p) => <PlatformGlyph key={p} platform={p} />)} {c.platforms.map(sourceLabel).join(", ")}</span>
                  <span>{c.open} open · {c.confirmed} confirmed</span>
                  <span>active {relTime(c.first_observed_at)} → {relTime(c.last_observed_at)}</span>
                </div>
              </div>
              <RiskBadge level={c.max_risk} />
            </div>
            <div className="flex flex-wrap gap-1.5 border-b border-ink-150 bg-ink-50/50 px-4 py-2.5">
              {c.shared_indicators.map((i) => (
                <span key={i.kind + i.value} className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-ink-150 bg-white px-2 py-1 text-[11.5px]" title={`${i.label} — in ${i.findings} findings`}>
                  <Link2 className="size-3 text-ink-400" />
                  <span className="text-ink-500">{i.label.replace("Same ", "")}</span>
                  <code className="truncate font-mono text-ink-800">{i.value}</code>
                  <span className="tabular text-ink-400">×{i.findings}</span>
                </span>
              ))}
            </div>
            <ul className="divide-y divide-ink-150">
              {c.findings.map((f) => (
                <li key={f.finding_id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2 text-[12.5px]">
                  <PlatformGlyph platform={f.platform} className="text-ink-500" />
                  <Link href={`/app/investigations/${f.finding_id}`} className="font-medium text-teal-700 hover:underline">{f.name}</Link>
                  <span className="text-ink-500">{f.handle ? `@${f.handle}` : sourceLabel(f.platform)}{scope === "all" ? ` · ${f.brand_name}` : ""}</span>
                  <span className="ml-auto inline-flex items-center gap-2"><RiskBadge level={f.risk_level} score={f.risk_score} /><StatusBadge status={f.status} level={f.risk_level} /></span>
                </li>
              ))}
            </ul>
          </Card>
        ))
      )}
      {data && data.ignored_common_indicators > 0 && (
        <p className="text-[11.5px] text-ink-500">{data.ignored_common_indicators} value(s) shared by more than 25 findings were ignored as too common to be meaningful.</p>
      )}
    </div>
  );
}
