"use client";

import { Ban, ChevronDown, ExternalLink, KeyRound, PlugZap } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { PlatformGlyph, SOURCE_HEALTH_LABEL, SOURCE_STATE_LABEL, sourceDot, StatusDot } from "@/components/app/bits";
import { useSession } from "@/components/app/providers";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, Checkbox, ErrorState, Field, Input, Notice, PageHeader, Skeleton, TagInput, cx } from "@/components/ui";
import { api, ApiError } from "@/lib/api";
import { dateTime, OUTCOME_LABELS, relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { SourceCheck, SourceHealth } from "@/lib/types";

interface SourcesResp {
  sources: SourceHealth[];
  unavailable: { name: string; label: string; category: string; reason: string }[];
  config: { enabled_sources: string[]; mastodon_instances: string[]; store_country: string };
}
type Cfg = SourcesResp["config"];

const STATE_TONE: Record<string, "forest" | "crit" | "outline" | "med"> = { live: "forest", unavailable: "crit", disabled: "outline", simulated: "med" };
const outcomeLabel = (o: string) => (o === "invalid_config" ? "Invalid configuration" : OUTCOME_LABELS[o] ?? o);

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-[10.5px] font-medium tracking-wide text-ink-500 uppercase">{label}</dt>
      <dd className="mt-0.5 text-[12px] leading-relaxed text-ink-800">{children}</dd>
    </div>
  );
}

function RateLimit({ s }: { s: SourceHealth }) {
  const obs = s.rate_limit.observed;
  const entries = obs ? Object.entries(obs.values ?? {}).filter(([, v]) => v && (v.limit != null || v.remaining != null)) : [];
  return (
    <>
      {entries.length > 0 ? (
        entries.map(([k, v]) => (
          <div key={k} className="tabular">
            {v.remaining ?? "?"}/{v.limit ?? "?"} remaining{k !== "default" ? ` on ${k}` : ""}
            {v.reset_in != null && <span className="text-ink-500"> · resets in {Math.max(0, Math.round(v.reset_in / 60))} min</span>}
            <span className="text-ink-400"> · seen {relTime(obs!.at)}</span>
          </div>
        ))
      ) : (
        <div className="text-ink-500">No quota headers observed yet</div>
      )}
      {s.rate_limit.last_rate_limited_at && <div className="text-med">Rate limited {relTime(s.rate_limit.last_rate_limited_at)}</div>}
      {s.rate_limit.documented && <div className="text-[11.5px] text-ink-500">Documented: {s.rate_limit.documented}</div>}
    </>
  );
}

function History({ name }: { name: string }) {
  const { data } = useApi<SourceCheck[]>(`/sources/${name}/checks`, { limit: 10 });
  if (!data) return <Skeleton className="h-10" />;
  if (!data.length) return <p className="text-[12px] text-ink-500">No connectivity tests yet.</p>;
  return (
    <ul className="space-y-1">
      {data.map((c) => (
        <li key={c.id} className="flex flex-wrap items-baseline gap-x-2 text-[12px]">
          <StatusDot status={c.outcome === "ok" || c.outcome === "empty" ? "ok" : c.outcome === "rate_limited" ? "partial" : "failed"} />
          <span className="font-medium text-ink-800">{outcomeLabel(c.outcome)}</span>
          <span className="text-ink-500" title={dateTime(c.at)}>{relTime(c.at)}</span>
          {c.latency_ms != null && <span className="tabular text-ink-400">{c.latency_ms} ms</span>}
          <span className="min-w-0 basis-full truncate pl-4 text-[11.5px] text-ink-500" title={c.detail}>{c.detail}</span>
        </li>
      ))}
    </ul>
  );
}

function SourceRow({ s, cfg, setCfg, isOwner, onTested }: { s: SourceHealth; cfg: Cfg; setCfg: (c: Cfg) => void; isOwner: boolean; onTested: () => void }) {
  const toast = useToast();
  const [testing, setTesting] = useState(false);
  const [open, setOpen] = useState(false);
  const enabledDraft = cfg.enabled_sources.includes(s.name);
  const changed = enabledDraft !== s.enabled;

  const test = async () => {
    setTesting(true);
    try {
      const r = await api<SourceCheck & { status: string; enabled: boolean }>(`/sources/${s.name}/test`, { method: "POST" });
      const good = r.outcome === "ok" || r.outcome === "empty";
      toast({ tone: good ? "success" : "error", title: `${s.label}: ${outcomeLabel(r.outcome)}`, description: `${r.detail}${r.latency_ms != null ? ` · ${r.latency_ms} ms` : ""}` });
      onTested();
    } catch (e) {
      toast({ tone: "error", title: "Could not run the test", description: (e as Error).message });
    } finally {
      setTesting(false);
    }
  };

  return (
    <li className="px-4 py-4" aria-labelledby={`src-${s.name}`}>
      <div className="flex flex-wrap items-start gap-3">
        <span className="grid size-9 shrink-0 place-items-center rounded-md border border-ink-150 bg-ink-50 text-ink-600"><PlatformGlyph platform={s.name} className="size-4" /></span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 id={`src-${s.name}`} className="text-[13.5px] font-semibold text-ink-900">{s.label}</h3>
            <Badge tone={STATE_TONE[s.state]} dot>{SOURCE_STATE_LABEL[s.state]}</Badge>
            <Badge tone={s.reliability === "unofficial" ? "med" : "outline"}>{s.integration_type}</Badge>
            <span className="inline-flex items-center gap-1.5 text-[12px] text-ink-700"><StatusDot status={sourceDot(s)} />{SOURCE_HEALTH_LABEL[s.health] ?? s.health}</span>
          </div>
          <p className="mt-1 text-[12px] text-ink-600">{s.platform} · {s.integration}</p>
          <p className="mt-0.5 text-[11.5px] text-ink-500">{s.notes}</p>
          {s.docs_url && (
            <a href={s.docs_url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-1 text-[11.5px] text-teal-700 hover:underline">
              Documentation <ExternalLink className="size-3" />
            </a>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <Button size="sm" icon={<PlugZap className="size-3.5" />} loading={testing} onClick={test} title="Runs one real query and records the outcome">
            {s.health === "not_tested" ? "Run first test" : "Test connection"}
          </Button>
          <Checkbox
            checked={enabledDraft}
            disabled={!isOwner}
            onChange={(v) => setCfg({ ...cfg, enabled_sources: v ? [...cfg.enabled_sources, s.name] : cfg.enabled_sources.filter((x) => x !== s.name) })}
            label={changed ? "Enabled (unsaved)" : "Enabled"}
          />
        </div>
      </div>

      {s.state === "unavailable" && (
        <Notice tone="warn" className="mt-3">
          {s.config.valid
            ? <>Unavailable: the most recent {s.observed_via === "test" ? "connectivity test" : "scan"} {s.health === "rate_limited" ? "was rate limited" : "failed"}. Scans keep running other sources; this one will be retried on the next scan.</>
            : <>Unavailable: {s.config.problems.join("; ")}.</>}
        </Notice>
      )}

      <dl className="mt-3 grid gap-x-6 gap-y-3 rounded-md border border-ink-150 bg-white px-3 py-3 sm:grid-cols-2 lg:grid-cols-3">
        <Fact label="Authentication & configuration">
          <div className="flex items-start gap-1.5"><KeyRound className="mt-0.5 size-3.5 shrink-0 text-ink-400" />{s.auth.label}</div>
          {s.config.valid ? <div className="text-forest-700">Configuration valid</div> : s.config.problems.map((p) => <div key={p} className="text-crit">{p}</div>)}
        </Fact>
        <Fact label="Last successful request">
          {s.last_success ? (
            <>
              <span title={dateTime(s.last_success.at)}>{relTime(s.last_success.at)}</span>{" "}
              {s.last_success.scan_id ? <Link href={`/app/scans/${s.last_success.scan_id}`} className="text-teal-700 hover:underline">scan #{s.last_success.scan_id}</Link> : <span className="text-ink-500">connectivity test</span>}
              {s.last_success.detail && <div className="truncate text-[11.5px] text-ink-500" title={s.last_success.detail}>{s.last_success.detail}</div>}
            </>
          ) : (
            <span className="font-medium text-ink-600">Not tested</span>
          )}
        </Fact>
        <Fact label="Last error">
          {s.last_error ? (
            <>
              <span className="text-crit">{outcomeLabel(s.last_error.kind)}</span> <span className="text-ink-500" title={dateTime(s.last_error.at)}>· {relTime(s.last_error.at)}</span>
              {s.last_error.scan_id && <> · <Link href={`/app/scans/${s.last_error.scan_id}`} className="text-teal-700 hover:underline">scan #{s.last_error.scan_id}</Link></>}
              {s.last_error.message && <div className="line-clamp-2 text-[11.5px] text-ink-500" title={s.last_error.message}>{s.last_error.message}</div>}
            </>
          ) : (
            <span className="text-ink-500">None recorded</span>
          )}
        </Fact>
        <Fact label="Last attempted scan">
          {s.last_attempted_scan ? (
            <>
              <Link href={`/app/scans/${s.last_attempted_scan.scan_id}`} className="text-teal-700 hover:underline">#{s.last_attempted_scan.scan_id}</Link>{" "}
              <span className="text-ink-600">· {s.last_attempted_scan.status}</span>
              {s.last_attempted_scan.at && <span className="text-ink-500"> · {relTime(s.last_attempted_scan.at)}</span>}
              <div className="text-[11.5px] text-ink-500">{s.last_attempted_scan.candidates} candidate(s)</div>
            </>
          ) : (
            <span className="text-ink-500">Not used in a scan yet</span>
          )}
        </Fact>
        <Fact label="Last connectivity test">
          {s.last_test ? (
            <>
              {outcomeLabel(s.last_test.outcome)} <span className="text-ink-500">· {relTime(s.last_test.at)}{s.last_test.latency_ms != null ? ` · ${s.last_test.latency_ms} ms` : ""}</span>
              {s.last_test.result_count != null && <div className="text-[11.5px] text-ink-500">{s.last_test.result_count} result(s) for the test query</div>}
            </>
          ) : (
            <span className="text-ink-500">Not tested</span>
          )}
        </Fact>
        <Fact label="Rate limit / quota"><RateLimit s={s} /></Fact>
      </dl>
      <button type="button" onClick={() => setOpen((o) => !o)} aria-expanded={open} className="mt-2 inline-flex items-center gap-1 text-[12px] font-medium text-ink-600 hover:text-ink-900">
        <ChevronDown className={cx("size-3.5 transition-transform", open && "rotate-180")} /> Test history
      </button>
      {open && <div className="mt-2 rounded-md border border-ink-150 bg-ink-50/60 px-3 py-2"><History name={s.name} /></div>}
    </li>
  );
}

export default function SourcesPage() {
  const toast = useToast();
  const { session } = useSession();
  const isOwner = session?.role === "owner";
  const { data, error, loading, reload } = useApi<SourcesResp>("/sources");
  const [cfg, setCfg] = useState<Cfg | null>(null);
  const [saving, setSaving] = useState(false);
  const [fieldErr, setFieldErr] = useState<{ field?: string; message?: string }>({});
  useEffect(() => {
    if (data) setCfg(data.config);
  }, [data]);

  const save = async () => {
    if (!cfg) return;
    setSaving(true);
    setFieldErr({});
    try {
      await api("/sources/config", { method: "PUT", body: cfg });
      toast({ tone: "success", title: "Source settings saved", description: "Applies to the next scan of every brand." });
      reload(true);
    } catch (e) {
      const d = e instanceof ApiError ? (e.data as { detail?: { field?: string; message?: string } })?.detail : undefined;
      if (d && typeof d === "object") setFieldErr(d);
      toast({ tone: "error", title: "Settings not saved", description: (e as Error).message });
    } finally {
      setSaving(false);
    }
  };

  const live = data?.sources.filter((s) => s.name !== "demo") ?? [];
  const demo = data?.sources.find((s) => s.name === "demo");
  const dirty = !!(cfg && data && JSON.stringify(cfg) !== JSON.stringify(data.config));
  const count = (st: string) => live.filter((s) => s.state === st).length;
  const mastodon = live.find((s) => s.name === "mastodon");

  return (
    <div className="animate-fade-in space-y-4">
      <PageHeader
        eyebrow="Configure"
        title="Sources & Integrations"
        description="Where ScamShield looks. Only documented public endpoints are used and access restrictions are never bypassed. Every status below comes from a real scan or connectivity test — a source nobody has queried yet says “Not tested”."
      />
      {error && <ErrorState error={error} onRetry={() => reload()} />}
      {loading || !data || !cfg ? (
        <Skeleton className="h-96" />
      ) : (
        <>
          <div className="flex flex-wrap gap-2 text-[12px]">
            {(["live", "unavailable", "disabled"] as const).map((st) => (
              <span key={st} className="inline-flex items-center gap-1.5 rounded-md border border-ink-150 bg-white px-2.5 py-1">
                <Badge tone={STATE_TONE[st]} dot>{SOURCE_STATE_LABEL[st]}</Badge><span className="tabular text-ink-700">{count(st)}</span>
              </span>
            ))}
            <span className="inline-flex items-center gap-1.5 rounded-md border border-ink-150 bg-white px-2.5 py-1 text-ink-600">
              <StatusDot status="unknown" /> Not tested <span className="tabular text-ink-700">{live.filter((s) => s.health === "not_tested").length}</span>
            </span>
          </div>

          <Card>
            <CardHeader
              title="Source registry"
              description="Each source runs independently: requests have bounded timeouts, transient failures (timeouts, 5xx) are retried once, rate limits and access denials stop further queries, and a failing source never stops the others."
            />
            <ul className="divide-y divide-ink-150">
              {live.map((s) => <SourceRow key={s.name} s={s} cfg={cfg} setCfg={setCfg} isOwner={isOwner} onTested={() => reload(true)} />)}
            </ul>
            {dirty && (
              <div className="flex flex-wrap items-center justify-end gap-3 border-t border-ink-150 bg-ink-50/60 px-4 py-2.5">
                <span className="text-[12px] text-med">Unsaved changes to enabled sources</span>
                <Button variant="ghost" onClick={() => setCfg(data.config)}>Discard</Button>
                <Button variant="primary" loading={saving} disabled={!isOwner} onClick={save}>Save changes</Button>
              </div>
            )}
          </Card>

          <Card>
            <CardHeader title="Source settings" description={isOwner ? "Validated before saving: hostnames must be public Mastodon servers (checked live), and the storefront must be an ISO country code." : "Only organization owners can change source settings."} />
            <div className="grid gap-4 p-4 md:grid-cols-2">
              <Field label="Mastodon instances" htmlFor="inst" hint="Up to 3 instance hostnames to search. New instances are verified via GET /api/v2/instance before they are saved." error={fieldErr.field === "mastodon_instances" || fieldErr.field === "mastodon" ? fieldErr.message : null}>
                <TagInput id="inst" value={cfg.mastodon_instances} onChange={(v) => setCfg({ ...cfg, mastodon_instances: v.slice(0, 3) })} max={3} placeholder="mastodon.social" />
              </Field>
              <Field label="App store country" htmlFor="country" hint="Two-letter storefront code used for App Store and Google Play searches." error={fieldErr.field === "store_country" ? fieldErr.message : null}>
                <Input id="country" maxLength={2} value={cfg.store_country} onChange={(e) => setCfg({ ...cfg, store_country: e.target.value.toLowerCase() })} className="w-24 uppercase" disabled={!isOwner} />
              </Field>
            </div>
            <div className="flex justify-end border-t border-ink-150 px-4 py-3">
              <Button variant="primary" disabled={!isOwner || !dirty} loading={saving} onClick={save}>Save source settings</Button>
            </div>
          </Card>

          <Card>
            <CardHeader title="Credentials" description="None of the integrated sources require credentials. Optional secrets are configured on the server only — they are never sent to the browser, shown here, or written to logs." />
            <div className="space-y-2 p-4 text-[12.5px] text-ink-700">
              <p>
                <code className="rounded bg-ink-50 px-1 font-mono text-[11.5px]">SCAMSHIELD_MASTODON_ACCESS_TOKENS</code> — optional per-instance access tokens
                (<code className="font-mono text-[11.5px]">instance=token,…</code>, scope <code className="font-mono text-[11.5px]">read:search</code>). Each token is sent only to its own instance.
              </p>
              {mastodon && mastodon.auth.credentials.length > 0 && (
                <ul className="space-y-0.5 pl-1">
                  {mastodon.auth.credentials.map((c) => (
                    <li key={c.instance} className="flex items-center gap-2 text-[12px]">
                      <StatusDot status={c.configured ? "ok" : "unknown"} /> {c.instance}: <span className="text-ink-600">{c.configured ? "token configured on the server" : "public access (no token)"}</span>
                    </li>
                  ))}
                </ul>
              )}
              {mastodon?.auth.unused_tokens_for && mastodon.auth.unused_tokens_for.length > 0 && (
                <p className="text-[12px] text-med">A token is configured for {mastodon.auth.unused_tokens_for.join(", ")}, which is not in the instance list, so it is unused.</p>
              )}
            </div>
          </Card>

          <Card>
            <CardHeader title="Simulated and not integrated" description="Shown for completeness. None of these are ever presented as live data." />
            <ul className="divide-y divide-ink-150">
              {demo && (
                <li className="flex items-start gap-3 px-4 py-3">
                  <Badge tone="med" dot>Simulated</Badge>
                  <div className="text-[12px] text-ink-600">
                    <span className="font-medium text-ink-800">{demo.label}</span> — {demo.notes || "Bundled synthetic dataset for the demo brand only."} It makes no network requests, is used only by the demo brand, and is never a substitute for a failed live source.
                  </div>
                </li>
              )}
              {data.unavailable.map((u) => (
                <li key={u.name} className="flex items-start gap-3 px-4 py-3">
                  <Ban className="mt-0.5 size-4 shrink-0 text-ink-300" />
                  <div>
                    <div className="text-[13px] font-medium text-ink-800">{u.label} <span className="text-[11.5px] font-normal text-ink-400">· not integrated</span></div>
                    <div className="text-[12px] text-ink-500">{u.reason}</div>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </div>
  );
}
