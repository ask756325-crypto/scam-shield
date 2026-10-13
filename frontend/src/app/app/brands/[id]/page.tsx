"use client";

import { ArrowLeft, FileUp, ShieldCheck, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { BrandForm, brandToPayload } from "@/components/app/brand-form";
import { useBrands, useScans } from "@/components/app/providers";
import { AssetRegistry } from "@/components/app/registry";
import { ScheduleCard } from "@/components/app/schedule-card";
import { DeleteBrandDialog } from "@/components/app/delete-brand";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, Notice, PageHeader, Segmented, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { plural, relTime, sourceLabel } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { Brand } from "@/lib/types";

interface ExclusionRow { id: number; scan_id: number; source: string; external_id: string; name: string; url: string | null; rule: string; matched_value: string; created_at: string }
type Tab = "profile" | "registry" | "log" | "monitoring";

function ExclusionLog({ brandId, version }: { brandId: number; version: number }) {
  const { data, reload } = useApi<ExclusionRow[]>(`/brands/${brandId}/exclusions`, { limit: 200 });
  useEffect(() => {
    if (version) reload(true);
  }, [version, reload]);
  return (
    <Card id="exclusions">
      <CardHeader title="Exclusion log" description="Every candidate set aside as official before scoring, with the rule and value that matched." />
      {!data ? (
        <div className="p-4"><Skeleton className="h-16" /></div>
      ) : data.length === 0 ? (
        <EmptyState icon={<ShieldCheck className="size-5" />} title="Nothing excluded yet" description="When your official accounts or apps appear in scan results, they’ll be listed here with the rule that matched." />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-[12.5px]">
            <thead className="border-b border-ink-150 bg-ink-50/70 text-[11.5px] text-ink-500">
              <tr><th className="py-2 pr-3 pl-4 font-medium">Asset</th><th className="px-3 py-2 font-medium">Source</th><th className="px-3 py-2 font-medium">Rule</th><th className="px-3 py-2 font-medium">Matched value</th><th className="py-2 pr-4 pl-3 font-medium">Scan</th></tr>
            </thead>
            <tbody className="divide-y divide-ink-150">
              {data.map((e) => (
                <tr key={e.id}>
                  <td className="py-2 pr-3 pl-4 text-ink-900">{e.name}</td>
                  <td className="px-3 py-2 text-ink-600">{sourceLabel(e.source)}</td>
                  <td className="px-3 py-2"><code className="font-mono text-[11px] text-forest-700">{e.rule}</code></td>
                  <td className="max-w-[260px] truncate px-3 py-2 font-mono text-[11px] text-ink-500" title={e.matched_value}>{e.matched_value}</td>
                  <td className="py-2 pr-4 pl-3 text-ink-500"><Link href={`/app/scans/${e.scan_id}`} className="hover:underline">#{e.scan_id}</Link> · {relTime(e.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function BrandDetail() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const toast = useToast();
  const { reloadBrands, select } = useBrands();
  const { track, version } = useScans();
  const { data: brand, error, setData, reload } = useApi<Brand>(`/brands/${id}`);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [importing, setImporting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const tab = ((params.get("tab") as Tab) ?? "profile") as Tab;
  const setTab = (t: Tab) => router.replace(`${pathname}?tab=${t}`, { scroll: false });

  useEffect(() => {
    if (version) reload(true);
  }, [version, reload]);
  useEffect(() => {
    if (brand) select(brand.id);
  }, [brand?.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (window.location.hash === "#exclusions") setTab("log");
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (error) return <ErrorState error={error} />;
  if (!brand) return <Skeleton className="h-96" />;

  const importCsv = async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    setImporting(true);
    try {
      const r = await api<{ scan_id: number; rows: number }>(`/brands/${brand.id}/import`, { method: "POST", body: fd });
      track(r.scan_id);
      toast({ tone: "info", title: `Importing ${r.rows} rows`, description: "Imported records are scored by the same engine and labelled “Imported”." });
    } catch (e) {
      toast({ tone: "error", title: "Import failed", description: (e as Error).message });
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };
  const idCount = brand.official_accounts.length + brand.official_apps.length + brand.official_domains.length;

  return (
    <div className="animate-fade-in space-y-4">
      <Link href="/app/brands" className="inline-flex items-center gap-1.5 text-[12.5px] text-ink-500 hover:text-ink-900">
        <ArrowLeft className="size-3.5" /> Brand profiles
      </Link>
      <PageHeader
        title={<span className="inline-flex flex-wrap items-center gap-2">{brand.name}{brand.is_demo && <Badge tone="med">Demo · synthetic</Badge>}</span>}
        description={`${plural(brand.official_accounts.length, "official account")} · ${plural(brand.official_apps.length, "app")} · ${plural(brand.official_domains.length, "domain")} · updated ${relTime(brand.updated_at)}`}
        actions={
          <>
            <Button icon={<FileUp className="size-3.5" />} loading={importing} onClick={() => fileRef.current?.click()}>Import CSV</Button>
            <input ref={fileRef} type="file" accept=".csv,text/csv" className="hidden" aria-label="CSV file to import" onChange={(e) => e.target.files?.[0] && importCsv(e.target.files[0])} />
            <Button variant="ghost" icon={<Trash2 className="size-3.5" />} onClick={() => setConfirmDelete(true)}>Delete</Button>
          </>
        }
      />
      {brand.is_demo && <Notice tone="warn">This is the fictional demo brand. Its domains use the reserved <code>.example</code> TLD and its scans use bundled synthetic data only.</Notice>}
      {!brand.is_demo && idCount === 0 && (
        <Notice tone="teal">This profile has no official assets yet. That’s fine for a first scan, but adding your website, accounts and apps prevents your own assets from appearing as findings.</Notice>
      )}

      <Segmented
        label="Brand sections"
        value={tab}
        onChange={setTab}
        options={[
          { value: "profile", label: "Profile" },
          { value: "registry", label: "Asset registry" },
          { value: "log", label: "Exclusion log" },
          { value: "monitoring", label: "Monitoring" },
        ]}
      />

      {tab === "profile" && (
        <BrandForm
          key={brand.id}
          brand={brand}
          initial={brandToPayload(brand)}
          submitLabel="Save changes"
          onBrandChange={(b) => { setData(b); reloadBrands(); }}
          onSubmit={async (p) => {
            const b = await api<Brand>(`/brands/${brand.id}`, { method: "PUT", body: p });
            setData(b);
            await reloadBrands();
            toast({ tone: "success", title: "Brand profile saved", description: "Changes apply to the next scan." });
          }}
        />
      )}
      {tab === "registry" && <AssetRegistry brandId={brand.id} version={brand.updated_at} />}
      {tab === "log" && <ExclusionLog brandId={brand.id} version={version} />}
      {tab === "monitoring" && <ScheduleCard brand={brand} />}

      {tab === "profile" && (
        <Card>
          <CardHeader title="CSV import format" />
          <p className="p-4 text-[12.5px] leading-relaxed text-ink-600">
            Required columns: <code>platform</code> (bluesky, mastodon, apple, google_play, other), <code>kind</code> (account or app), <code>external_id</code>, <code>name</code>. Optional: <code>handle</code>, <code>url</code>, <code>description</code>, <code>publisher_name</code>, <code>publisher_id</code>, <code>track_id</code>, <code>links</code> (space separated), <code>avatar_url</code>. Max 2,000 rows / 2 MB.
          </p>
        </Card>
      )}

      <DeleteBrandDialog
        brand={brand}
        open={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        onDeleted={async () => {
          select(null);
          await reloadBrands();
          router.push("/app/brands");
        }}
      />
    </div>
  );
}

export default function BrandDetailPage() {
  return (
    <Suspense fallback={<Skeleton className="h-96" />}>
      <BrandDetail />
    </Suspense>
  );
}
