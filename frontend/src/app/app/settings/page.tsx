"use client";

import { useEffect, useState } from "react";
import { useSession } from "@/components/app/providers";
import { useToast } from "@/components/toast";
import { Badge, Button, Card, CardHeader, ErrorState, Field, Input, Notice, PageHeader, Segmented, Select, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { dateTime, GROUP_LABELS, relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { DataTab, MonitoringTab, SessionsCard } from "@/components/app/settings-sections";

type Tab = "account" | "organization" | "monitoring" | "data" | "detection";
const TABS: Tab[] = ["account", "organization", "monitoring", "data", "detection"];

interface DetectionCfg {
  groups: Record<string, { signals: string[]; weight: number; threshold: number; label: string; kinds?: string[] }>;
  relevance: { identity_min: number; visual_min: number };
  levels: Record<string, { min_score: number; min_corroboration: number; requires?: string[] }>;
}

function AccountTab() {
  const { session, refresh } = useSession();
  const toast = useToast();
  const [name, setName] = useState(session?.user.name ?? "");
  const [pw, setPw] = useState({ current_password: "", new_password: "" });
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<Error | null>(null);
  const [emailForm, setEmailForm] = useState({ new_email: "", password: "" });
  const [emailErr, setEmailErr] = useState<Error | null>(null);
  useEffect(() => setName(session?.user.name ?? ""), [session?.user.name]);
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Profile" />
        <form
          className="grid gap-4 p-4 md:grid-cols-2"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy("profile");
            try {
              await api("/auth/me", { method: "PATCH", body: { name } });
              await refresh();
              toast({ tone: "success", title: "Profile updated" });
            } catch (e) {
              toast({ tone: "error", title: "Could not update", description: (e as Error).message });
            } finally {
              setBusy(null);
            }
          }}
        >
          <Field label="Name" htmlFor="nm"><Input id="nm" value={name} maxLength={120} required onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Email" htmlFor="em" hint="Change it in the section below."><Input id="em" value={session?.user.email ?? ""} disabled /></Field>
          <div className="flex items-center justify-between md:col-span-2">
            <span className="text-[12px] text-ink-500">Last sign-in {dateTime(session?.user.last_login_at)}</span>
            <Button type="submit" variant="primary" loading={busy === "profile"}>Save</Button>
          </div>
        </form>
      </Card>
      <Card>
        <CardHeader title="Change email" description="Confirm with your password. Other sessions are signed out and the new address must be verified." />
        <form
          className="grid gap-4 p-4 md:grid-cols-2"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy("email");
            setEmailErr(null);
            try {
              await api("/auth/change-email", { method: "POST", body: emailForm });
              setEmailForm({ new_email: "", password: "" });
              await refresh();
              toast({ tone: "success", title: "Email updated" });
            } catch (e) {
              setEmailErr(e as Error);
            } finally {
              setBusy(null);
            }
          }}
        >
          <Field label="New email" htmlFor="ne"><Input id="ne" type="email" required autoComplete="email" value={emailForm.new_email} onChange={(e) => setEmailForm({ ...emailForm, new_email: e.target.value })} /></Field>
          <Field label="Current password" htmlFor="ep"><Input id="ep" type="password" required autoComplete="current-password" value={emailForm.password} onChange={(e) => setEmailForm({ ...emailForm, password: e.target.value })} /></Field>
          {emailErr && <div className="md:col-span-2"><ErrorState error={emailErr} /></div>}
          <div className="flex justify-end md:col-span-2"><Button type="submit" variant="primary" loading={busy === "email"}>Update email</Button></div>
        </form>
      </Card>
      <Card>
        <CardHeader title="Change password" description="Other signed-in sessions will be signed out." />
        <form
          className="grid gap-4 p-4 md:grid-cols-2"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy("pw");
            setErr(null);
            try {
              await api("/auth/change-password", { method: "POST", body: pw });
              setPw({ current_password: "", new_password: "" });
              toast({ tone: "success", title: "Password changed" });
            } catch (e) {
              setErr(e as Error);
            } finally {
              setBusy(null);
            }
          }}
        >
          <Field label="Current password" htmlFor="cp"><Input id="cp" type="password" autoComplete="current-password" required value={pw.current_password} onChange={(e) => setPw({ ...pw, current_password: e.target.value })} /></Field>
          <Field label="New password" htmlFor="np" hint="At least 10 characters."><Input id="np" type="password" autoComplete="new-password" required minLength={10} value={pw.new_password} onChange={(e) => setPw({ ...pw, new_password: e.target.value })} /></Field>
          {err && <div className="md:col-span-2"><ErrorState error={err} /></div>}
          <div className="flex justify-end md:col-span-2"><Button type="submit" variant="primary" loading={busy === "pw"}>Update password</Button></div>
        </form>
      </Card>
    </div>
  );
}

function OrgTab() {
  const toast = useToast();
  const { refresh, session } = useSession();
  const { data, error, reload } = useApi<{ id: number; name: string; role: string; created_at: string; members: { user_id: number; name: string; email: string; role: string; joined_at: string }[] }>("/settings/organization");
  const { data: invites, reload: reloadInvites } = useApi<{ id: number; email: string; role: string; expires_at: string }[]>(session?.role === "owner" ? "/settings/invites" : null);
  const [invite, setInvite] = useState({ email: "", role: "analyst" });
  const [newLink, setNewLink] = useState<{ email: string; link: string; emailed: boolean } | null>(null);
  const [name, setName] = useState("");
  useEffect(() => data && setName(data.name), [data]);
  if (error) return <ErrorState error={error} />;
  if (!data) return <Skeleton className="h-48" />;
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Organization" description="All brands, scans and findings are scoped to this organization and never visible to others." />
        <form
          className="flex flex-wrap items-end gap-3 p-4"
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              await api("/settings/organization", { method: "PATCH", body: { name } });
              toast({ tone: "success", title: "Organization renamed" });
              reload(true);
              refresh();
            } catch (e) {
              toast({ tone: "error", title: "Could not save", description: (e as Error).message });
            }
          }}
        >
          <div className="w-72"><Field label="Name" htmlFor="on"><Input id="on" value={name} required maxLength={120} disabled={data.role !== "owner"} onChange={(e) => setName(e.target.value)} /></Field></div>
          <Button type="submit" variant="primary" disabled={data.role !== "owner"}>Save</Button>
        </form>
      </Card>
      <Card>
        <CardHeader title="Members" description="Owners manage sources, detection settings and the team. Analysts triage findings and run scans." />
        <ul className="divide-y divide-ink-150">
          {data.members.map((m) => (
            <li key={m.email} className="flex items-center justify-between gap-3 px-4 py-2.5 text-[12.5px]">
              <div className="min-w-0"><div className="truncate font-medium text-ink-900">{m.name}{m.email === session?.user.email && <span className="font-normal text-ink-400"> (you)</span>}</div><div className="truncate text-ink-500">{m.email}</div></div>
              {data.role === "owner" && m.email !== session?.user.email ? (
                <div className="flex items-center gap-2">
                  <Select aria-label={`Role for ${m.name}`} value={m.role} className="h-8 w-28 text-[12.5px]" onChange={async (e) => {
                    try { await api(`/settings/members/${m.user_id}`, { method: "PATCH", body: { role: e.target.value } }); reload(true); }
                    catch (err) { toast({ tone: "error", title: "Could not change role", description: (err as Error).message }); }
                  }}>
                    <option value="analyst">Analyst</option>
                    <option value="owner">Owner</option>
                  </Select>
                  <Button size="sm" variant="ghost" onClick={async () => {
                    if (!confirm(`Remove ${m.name}? Their account will be deleted.`)) return;
                    try { await api(`/settings/members/${m.user_id}`, { method: "DELETE" }); toast({ tone: "success", title: "Member removed" }); reload(true); }
                    catch (err) { toast({ tone: "error", title: "Could not remove", description: (err as Error).message }); }
                  }}>Remove</Button>
                </div>
              ) : (
                <Badge tone="outline" className="capitalize">{m.role}</Badge>
              )}
            </li>
          ))}
        </ul>
      </Card>
      {data.role === "owner" && (
        <Card>
          <CardHeader title="Invite a teammate" description="Creates a single-use link valid for 7 days. If SMTP is configured it is also emailed; otherwise share it yourself." />
          <form
            className="flex flex-wrap items-end gap-3 p-4"
            onSubmit={async (e) => {
              e.preventDefault();
              try {
                const r = await api<{ link: string; emailed: boolean }>("/settings/invites", { method: "POST", body: invite });
                setNewLink({ email: invite.email, link: r.link, emailed: r.emailed });
                setInvite({ ...invite, email: "" });
                reloadInvites(true);
              } catch (err) {
                toast({ tone: "error", title: "Could not create invite", description: (err as Error).message });
              }
            }}
          >
            <div className="w-72"><Field label="Email" htmlFor="ie"><Input id="ie" type="email" required value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} /></Field></div>
            <div className="w-36"><Field label="Role" htmlFor="ir"><Select id="ir" value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}><option value="analyst">Analyst</option><option value="owner">Owner</option></Select></Field></div>
            <Button type="submit" variant="primary">Create invite</Button>
          </form>
          {newLink && (
            <div className="px-4 pb-4">
              <Notice tone="teal">
                <div className="font-medium">Invite for {newLink.email} {newLink.emailed ? "(also emailed)" : "(not emailed — copy and send it)"}</div>
                <div className="mt-1.5 flex items-center gap-2">
                  <code className="min-w-0 flex-1 truncate rounded border border-ink-150 bg-white px-2 py-1 font-mono text-[11px] text-ink-800">{newLink.link}</code>
                  <Button size="sm" onClick={() => { navigator.clipboard?.writeText(newLink.link); toast({ tone: "success", title: "Link copied" }); }}>Copy</Button>
                </div>
                <div className="mt-1 text-[11.5px]">Shown once. Anyone with the link can create the account.</div>
              </Notice>
            </div>
          )}
          {invites && invites.length > 0 && (
            <ul className="divide-y divide-ink-150 border-t border-ink-150">
              {invites.map((i) => (
                <li key={i.id} className="flex items-center justify-between px-4 py-2.5 text-[12.5px]">
                  <div><div className="text-ink-900">{i.email}</div><div className="text-[11.5px] text-ink-500"><span className="capitalize">{i.role}</span> · expires {relTime(i.expires_at)}</div></div>
                  <Button size="sm" variant="ghost" onClick={async () => { await api(`/settings/invites/${i.id}`, { method: "DELETE" }); reloadInvites(true); }}>Revoke</Button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  );
}

function DetectionTab() {
  const toast = useToast();
  const { session } = useSession();
  const { data, error, setData } = useApi<{ effective: DetectionCfg; defaults: DetectionCfg; overrides: Record<string, unknown> }>("/settings/detection");
  const [cfg, setCfg] = useState<DetectionCfg | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => data && setCfg(structuredClone(data.effective)), [data]);
  if (error) return <ErrorState error={error} />;
  if (!data || !cfg) return <Skeleton className="h-64" />;
  const owner = session?.role === "owner";
  const totalWeight = Object.values(cfg.groups).reduce((s, g) => s + g.weight, 0);
  const num = (v: string) => (v === "" ? 0 : Number(v));

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="Evidence groups"
          description="Signals in the same group are correlated and combined with max(). Score = Σ weight × group score ÷ Σ weights applicable to the candidate type. A group corroborates when its score ≥ its threshold."
        />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-left text-[12.5px]">
            <thead className="border-b border-ink-150 bg-ink-50/70 text-[11.5px] text-ink-500">
              <tr><th className="py-2 pr-3 pl-4 font-medium">Group</th><th className="px-3 py-2 font-medium">Signals</th><th className="px-3 py-2 font-medium">Weight</th><th className="px-3 py-2 font-medium">Corroboration threshold</th></tr>
            </thead>
            <tbody className="divide-y divide-ink-150">
              {Object.entries(cfg.groups).map(([g, v]) => (
                <tr key={g}>
                  <td className="py-2 pr-3 pl-4 font-medium text-ink-900">{GROUP_LABELS[g] ?? g}{v.kinds && <span className="ml-1.5 text-[11px] font-normal text-ink-500">(apps only)</span>}</td>
                  <td className="px-3 py-2 font-mono text-[11px] text-ink-500">{v.signals.join(", ")}</td>
                  <td className="px-3 py-2"><Input aria-label={`${g} weight`} type="number" step="0.01" min={0} max={1} className="h-8 w-24" disabled={!owner} value={v.weight} onChange={(e) => setCfg({ ...cfg, groups: { ...cfg.groups, [g]: { ...v, weight: num(e.target.value) } } })} /></td>
                  <td className="px-3 py-2">{g === "identity" ? <span className="text-[11.5px] text-ink-400">Relevance gate below</span> : <Input aria-label={`${g} threshold`} type="number" step="0.05" min={0} max={1} className="h-8 w-24" disabled={!owner} value={v.threshold} onChange={(e) => setCfg({ ...cfg, groups: { ...cfg.groups, [g]: { ...v, threshold: num(e.target.value) } } })} />}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="border-t border-ink-150 px-4 py-2 text-[11.5px] text-ink-500 tabular">Weights sum to {totalWeight.toFixed(2)} (scores are normalised by applicable weight, so the sum need not be 1).</div>
      </Card>
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader title="Relevance gate" description="Below both thresholds a candidate is treated as unrelated and not retained." />
          <div className="grid grid-cols-2 gap-3 p-4">
            <Field label="Min identity similarity" htmlFor="rid"><Input id="rid" type="number" step="0.05" min={0} max={1} disabled={!owner} value={cfg.relevance.identity_min} onChange={(e) => setCfg({ ...cfg, relevance: { ...cfg.relevance, identity_min: num(e.target.value) } })} /></Field>
            <Field label="…or min logo similarity" htmlFor="rvm"><Input id="rvm" type="number" step="0.05" min={0} max={1} disabled={!owner} value={cfg.relevance.visual_min} onChange={(e) => setCfg({ ...cfg, relevance: { ...cfg.relevance, visual_min: num(e.target.value) } })} /></Field>
          </div>
        </Card>
        <Card>
          <CardHeader title="Risk levels" description="Name similarity alone always stays “low”." />
          <div className="space-y-2 p-4">
            {(["critical", "high", "medium"] as const).map((l) => (
              <div key={l} className="grid grid-cols-[70px_1fr_1fr] items-center gap-2 text-[12.5px]">
                <span className="capitalize text-ink-800">{l}</span>
                <Input aria-label={`${l} min score`} type="number" min={0} max={100} className="h-8" disabled={!owner} value={cfg.levels[l].min_score} onChange={(e) => setCfg({ ...cfg, levels: { ...cfg.levels, [l]: { ...cfg.levels[l], min_score: num(e.target.value) } } })} />
                <Input aria-label={`${l} min corroboration`} type="number" min={0} max={5} className="h-8" disabled={!owner} value={cfg.levels[l].min_corroboration} onChange={(e) => setCfg({ ...cfg, levels: { ...cfg.levels, [l]: { ...cfg.levels[l], min_corroboration: Math.round(num(e.target.value)) } } })} />
              </div>
            ))}
            <p className="pt-1 text-[11.5px] text-ink-500">Columns: minimum score, minimum corroborating groups. Critical additionally requires scam indicators.</p>
          </div>
        </Card>
      </div>
      <div className="flex justify-end gap-2">
        <Button
          variant="ghost"
          disabled={!owner}
          onClick={async () => {
            const r = await api<typeof data>("/settings/detection", { method: "DELETE" });
            setData(r);
            toast({ tone: "success", title: "Detection settings reset to defaults" });
          }}
        >
          Reset to defaults
        </Button>
        <Button
          variant="primary"
          disabled={!owner}
          loading={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const r = await api<typeof data>("/settings/detection", { method: "PUT", body: { overrides: cfg } });
              setData(r);
              toast({ tone: "success", title: "Detection settings saved", description: "Applied from the next scan. Existing findings keep their stored scores until rescanned." });
            } catch (e) {
              toast({ tone: "error", title: "Could not save", description: (e as Error).message });
            } finally {
              setBusy(false);
            }
          }}
        >
          Save detection settings
        </Button>
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const { session } = useSession();
  const owner = session?.role === "owner";
  const [tab, setTabState] = useState<Tab>("account");
  // Deep-linkable tabs (?tab=monitoring) without a Suspense boundary for useSearchParams.
  useEffect(() => {
    const t = new URLSearchParams(window.location.search).get("tab") as Tab | null;
    if (t && TABS.includes(t)) setTabState(t);
  }, []);
  const setTab = (t: Tab) => {
    setTabState(t);
    window.history.replaceState(null, "", `?tab=${t}`);
  };
  return (
    <div className="animate-fade-in">
      <PageHeader
        eyebrow="Configure"
        title="Settings"
        actions={
          <Segmented
            label="Settings section"
            value={tab}
            onChange={setTab}
            options={[
              { value: "account", label: "Account" },
              { value: "organization", label: "Organization" },
              { value: "monitoring", label: "Monitoring" },
              { value: "data", label: "Data" },
              { value: "detection", label: "Detection" },
            ]}
          />
        }
      />
      {tab === "account" ? (
        <div className="space-y-4"><AccountTab /><SessionsCard /></div>
      ) : tab === "organization" ? <OrgTab /> : tab === "monitoring" ? <MonitoringTab owner={owner} /> : tab === "data" ? <DataTab owner={owner} /> : <DetectionTab />}
    </div>
  );
}
