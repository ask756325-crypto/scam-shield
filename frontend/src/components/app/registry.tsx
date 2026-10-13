"use client";

import { CheckCircle2, Lock, ShieldCheck, ShieldOff } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { relTime, sourceLabel } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import type { ExclusionRule, Registry } from "@/lib/types";
import { useToast } from "../toast";
import { Badge, Button, Card, CardHeader, ErrorState, Field, Input, Notice, Select, Skeleton, cx } from "../ui";
import { PlatformGlyph } from "./bits";

const TYPE_LABEL: Record<string, string> = {
  domain: "Domain",
  handle: "Handle",
  profile_url: "Profile URL",
  account_id: "Account ID",
  app_id: "Bundle / package ID",
  track_id: "Apple track ID",
  publisher_id: "Publisher ID",
};

function Toggle({ checked, onChange, disabled, label }: { checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cx(
        "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full border transition-colors duration-200 disabled:cursor-not-allowed disabled:opacity-50",
        checked ? "border-forest-700 bg-forest-600" : "border-ink-200 bg-ink-150",
      )}
    >
      <span className={cx("inline-block size-3.5 rounded-full bg-white shadow transition-transform duration-200", checked ? "translate-x-[18px]" : "translate-x-[2px]")} />
    </button>
  );
}

function RulesCard({ reg, brandId, onSaved }: { reg: Registry; brandId: number; onSaved: (rules: ExclusionRule[]) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const setRule = async (id: string, enabled: boolean) => {
    setBusy(id);
    try {
      const r = await api<{ rules: ExclusionRule[] }>(`/brands/${brandId}/exclusion-rules`, { method: "PUT", body: { rules: { [id]: enabled } } });
      onSaved(r.rules);
      toast({ tone: "success", title: `${enabled ? "Enabled" : "Disabled"}: ${reg.rules.find((x) => x.id === id)?.label}`, description: "Applies from the next scan." });
    } catch (e) {
      toast({ tone: "error", title: "Could not update rule", description: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };
  return (
    <Card>
      <CardHeader
        title="Exclusion rules"
        description="Applied in order before scoring. Every rule compares an exact identifier — never a similar-looking name."
        actions={!reg.can_edit_rules && <Badge tone="outline"><Lock className="size-3" /> Owners can edit</Badge>}
      />
      <ul className="divide-y divide-ink-150">
        {reg.rules.map((r) => (
          <li key={r.id} className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 px-4 py-3">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[13px] font-medium text-ink-900">{r.label}</span>
                <Badge tone="outline">{r.kind === "app" ? "Apps" : "Accounts"}</Badge>
                {r.enabled !== r.default && <Badge tone="med">Changed from default</Badge>}
              </div>
              <p className="mt-0.5 text-[12px] leading-relaxed text-ink-500">{r.description}</p>
              <p className="mt-0.5 font-mono text-[11px] text-ink-400">
                {r.id} · {r.stats?.count ? `matched ${r.stats.count}× · last ${relTime(r.stats.last_at)}` : "no matches yet"}
              </p>
            </div>
            <div className="flex items-start pt-0.5">
              <Toggle checked={r.enabled} disabled={!reg.can_edit_rules || busy === r.id} onChange={(v) => setRule(r.id, v)} label={`${r.label} rule`} />
            </div>
          </li>
        ))}
      </ul>
    </Card>
  );
}

function CheckCard({ brandId }: { brandId: number }) {
  const [platform, setPlatform] = useState("bluesky");
  const [form, setForm] = useState({ handle: "", profile_url: "", account_id: "", app_id: "", track_id: "", publisher_id: "", verified_link: "" });
  const [result, setResult] = useState<{ excluded: boolean; rule: string | null; matched_value?: string; explanation: string } | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [busy, setBusy] = useState(false);
  const isApp = platform === "apple" || platform === "google_play";
  const f = (k: keyof typeof form) => ({ value: form[k], onChange: (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [k]: e.target.value }) });
  return (
    <Card>
      <CardHeader title="Check a candidate" description="Dry run: would an account or app with these identifiers be excluded? Uses the live rules above." />
      <form
        className="grid gap-3 p-4 sm:grid-cols-2"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          setResult(null);
          const body: Record<string, string> = { platform };
          for (const [k, v] of Object.entries(form)) if (v.trim()) body[k] = v.trim();
          try {
            setResult(await api(`/brands/${brandId}/registry/check`, { method: "POST", body }));
          } catch (err) {
            setError(err as Error);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field label="Platform" htmlFor="ck-platform">
          <Select id="ck-platform" value={platform} onChange={(e) => { setPlatform(e.target.value); setResult(null); }}>
            <option value="bluesky">Bluesky</option>
            <option value="mastodon">Mastodon</option>
            <option value="apple">App Store</option>
            <option value="google_play">Google Play</option>
          </Select>
        </Field>
        {isApp ? (
          <>
            <Field label="Bundle / package ID" htmlFor="ck-app"><Input id="ck-app" placeholder="com.example.app" {...f("app_id")} /></Field>
            {platform === "apple" && <Field label="Track ID" htmlFor="ck-track" optional><Input id="ck-track" {...f("track_id")} /></Field>}
            <Field label="Publisher ID" htmlFor="ck-pub" optional><Input id="ck-pub" {...f("publisher_id")} /></Field>
          </>
        ) : (
          <>
            <Field label="Handle" htmlFor="ck-handle"><Input id="ck-handle" placeholder={platform === "bluesky" ? "name.bsky.social" : "name@instance"} {...f("handle")} /></Field>
            <Field label="Profile URL" htmlFor="ck-url" optional><Input id="ck-url" {...f("profile_url")} /></Field>
            <Field label="Account ID" htmlFor="ck-id" optional><Input id="ck-id" placeholder={platform === "bluesky" ? "did:plc:…" : ""} {...f("account_id")} /></Field>
            {platform === "mastodon" && <Field label="Verified link on profile" htmlFor="ck-vl" optional><Input id="ck-vl" placeholder="https://…" {...f("verified_link")} /></Field>}
          </>
        )}
        <div className="flex items-end sm:col-span-2">
          <Button type="submit" loading={busy}>Check</Button>
        </div>
        {error && <div className="sm:col-span-2"><ErrorState error={error} /></div>}
        {result && (
          <div className="sm:col-span-2" role="status">
            {result.excluded ? (
              <Notice tone="teal" icon={<ShieldCheck className="size-4" />}>
                <span className="font-medium">Excluded by <code className="font-mono text-[12px]">{result.rule}</code></span> — {result.explanation}
                {result.matched_value && <div className="mt-0.5 font-mono text-[11.5px]">{result.matched_value}</div>}
              </Notice>
            ) : (
              <Notice tone="neutral" icon={<ShieldOff className="size-4" />}>{result.explanation}</Notice>
            )}
          </div>
        )}
      </form>
    </Card>
  );
}

export function AssetRegistry({ brandId, version }: { brandId: number; version?: string }) {
  const { data: reg, error, setData, reload } = useApi<Registry>(`/brands/${brandId}/registry`, { v: version });
  if (error) return <ErrorState error={error} onRetry={() => reload()} />;
  if (!reg) return <Skeleton className="h-96" />;
  const ids = reg.exact_identifiers;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <Card className="min-w-0">
          <CardHeader title="Trusted identifiers" description="Exact values that mark an account or app as official. Edit them in the Profile tab." />
          {ids.length === 0 ? (
            <p className="px-4 py-6 text-[12.5px] text-ink-500">No exact identifiers yet. Add your website, official accounts or apps in the Profile tab — until then nothing can be excluded.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] text-left text-[12.5px]">
                <thead className="border-b border-ink-150 bg-ink-50/70 text-[11.5px] text-ink-500">
                  <tr>
                    <th scope="col" className="py-2 pr-3 pl-4 font-medium">Identifier</th>
                    <th scope="col" className="px-3 py-2 font-medium">Where</th>
                    <th scope="col" className="py-2 pr-4 pl-3 font-medium">Used by rule</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-150">
                  {ids.map((i, n) => {
                    const ruleOn = i.rules.some((r) => reg.rules.find((x) => x.id === r)?.enabled);
                    return (
                      <tr key={n} className={cx(!ruleOn && "text-ink-400")}>
                        <td className="py-2 pr-3 pl-4">
                          <div className="font-mono text-[12px] break-all text-ink-900">{i.value}</div>
                          <div className="text-[11px] text-ink-500">{TYPE_LABEL[i.type] ?? i.type}{i.note ? ` · ${i.note}` : ""}</div>
                        </td>
                        <td className="px-3 py-2 whitespace-nowrap">
                          {i.platform ? <span className="inline-flex items-center gap-1.5"><PlatformGlyph platform={i.platform} className="text-ink-500" />{sourceLabel(i.platform)}</span> : "Any"}
                        </td>
                        <td className="py-2 pr-4 pl-3">
                          {i.rules.map((r) => {
                            const on = reg.rules.find((x) => x.id === r)?.enabled;
                            return <div key={r} className="font-mono text-[11px]">{on ? <span className="text-forest-700">{r}</span> : <span className="text-ink-400 line-through" title="Rule disabled">{r}</span>}</div>;
                          })}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
        <Card className="min-w-0">
          <CardHeader title="Similarity references" description={reg.similarity_reference.note} />
          <dl className="divide-y divide-ink-150 text-[12.5px]">
            {[
              ["Names & aliases", reg.similarity_reference.names.join(", ")],
              ["Products & keywords", reg.similarity_reference.keywords.join(", ") || "—"],
              ["Additional identifiers", reg.similarity_reference.additional_identifiers.join(", ") || "—"],
              ["Description", reg.similarity_reference.has_description ? "Provided" : "Not provided — description similarity is limited"],
            ].map(([k, v]) => (
              <div key={k} className="grid grid-cols-[150px_1fr] gap-3 px-4 py-2.5">
                <dt className="text-ink-500">{k}</dt>
                <dd className="min-w-0 break-words text-ink-900">{v}</dd>
              </div>
            ))}
            <div className="grid grid-cols-[150px_1fr] gap-3 px-4 py-2.5">
              <dt className="text-ink-500">Logo hashes</dt>
              <dd className="font-mono text-[11.5px] text-ink-900">
                {reg.similarity_reference.logo ? (
                  <span className="inline-flex items-center gap-1.5"><CheckCircle2 className="size-3.5 text-forest-600" /> pHash {reg.similarity_reference.logo.phash} · dHash {reg.similarity_reference.logo.dhash}</span>
                ) : (
                  <span className="font-sans text-ink-500">No logo — logo matching is not evaluated</span>
                )}
              </dd>
            </div>
          </dl>
        </Card>
      </div>
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <RulesCard reg={reg} brandId={brandId} onSaved={(rules) => setData({ ...reg, rules: rules.map((r) => ({ ...r, stats: reg.rules.find((x) => x.id === r.id)?.stats })) })} />
        <CheckCard brandId={brandId} />
      </div>
    </div>
  );
}
