"use client";

import { Download, KeyRound, ScrollText, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { dateTime, relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useToast } from "../toast";
import { Badge, Button, Card, CardHeader, ErrorState, Field, Input, Notice, Select, Skeleton } from "../ui";

interface Status { enabled: boolean; enabled_at: string | null; recovery_codes_left: number; setup_pending: boolean }

function RecoveryCodes({ codes, onDone }: { codes: string[]; onDone: () => void }) {
  const download = () => {
    const blob = new Blob([`ScamShield AI recovery codes\nEach code works once.\n\n${codes.join("\n")}\n`], { type: "text/plain" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "scamshield-recovery-codes.txt";
    a.click();
    URL.revokeObjectURL(a.href);
  };
  return (
    <div className="space-y-3">
      <Notice tone="warn">Save these recovery codes somewhere safe now. They are shown only once and let you sign in if you lose your authenticator.</Notice>
      <ul className="grid grid-cols-2 gap-1.5 rounded-md border border-ink-150 bg-white p-3 font-mono text-[13px] text-ink-900 sm:grid-cols-5" aria-label="Recovery codes">
        {codes.map((c) => <li key={c}>{c}</li>)}
      </ul>
      <div className="flex gap-2">
        <Button size="sm" icon={<Download className="size-3.5" />} onClick={download}>Download .txt</Button>
        <Button size="sm" variant="primary" onClick={onDone}>I’ve saved them</Button>
      </div>
    </div>
  );
}

export function TwoFactorCard() {
  const toast = useToast();
  const { data, error, reload } = useApi<Status>("/auth/2fa");
  const [step, setStep] = useState<"idle" | "password" | "scan" | "codes" | "disable" | "regen">("idle");
  const [password, setPassword] = useState("");
  const [code, setCode] = useState("");
  const [setup, setSetup] = useState<{ secret: string; otpauth_uri: string } | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const reset = () => { setStep("idle"); setPassword(""); setCode(""); setErr(null); setSetup(null); };

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setErr(null);
    try {
      await fn();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  if (error) return <ErrorState error={error} />;
  if (!data) return <Skeleton className="h-28" />;

  return (
    <Card>
      <CardHeader title={<span className="inline-flex items-center gap-2"><ShieldCheck className="size-4 text-ink-500" /> Two-factor authentication</span>}
        description="Require a 6-digit code from an authenticator app (Google Authenticator, 1Password, Authy…) in addition to your password."
        actions={<Badge tone={data.enabled ? "forest" : "outline"} dot>{data.enabled ? "On" : "Off"}</Badge>} />
      <div className="space-y-3 p-4 text-[12.5px]">
        {err && <p role="alert" className="text-crit">{err}</p>}
        {step === "codes" ? (
          <RecoveryCodes codes={codes} onDone={() => { reset(); reload(true); }} />
        ) : data.enabled ? (
          <>
            <p className="text-ink-600">Turned on {data.enabled_at ? relTime(data.enabled_at) : ""}. {data.recovery_codes_left} recovery code{data.recovery_codes_left === 1 ? "" : "s"} left.</p>
            {step === "idle" && (
              <div className="flex flex-wrap gap-2">
                <Button size="sm" onClick={() => setStep("regen")}>New recovery codes</Button>
                <Button size="sm" variant="ghost" onClick={() => setStep("disable")}>Turn off</Button>
              </div>
            )}
            {step === "regen" && (
              <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); run(async () => { const r = await api<{ recovery_codes: string[] }>("/auth/2fa/recovery-codes", { method: "POST", body: { code } }); setCodes(r.recovery_codes); setStep("codes"); }); }}>
                <Field label="Current code" htmlFor="regen-code"><Input id="regen-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} className="w-32" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} /></Field>
                <Button size="sm" type="submit" variant="primary" loading={busy}>Generate</Button>
                <Button size="sm" variant="ghost" onClick={reset}>Cancel</Button>
              </form>
            )}
            {step === "disable" && (
              <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); run(async () => { await api("/auth/2fa/disable", { method: "POST", body: { password, code } }); toast({ tone: "success", title: "Two-factor authentication turned off" }); reset(); reload(true); }); }}>
                <Field label="Password" htmlFor="dis-pw"><Input id="dis-pw" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
                <Field label="Code or recovery code" htmlFor="dis-code"><Input id="dis-code" autoComplete="one-time-code" className="w-40" value={code} onChange={(e) => setCode(e.target.value)} /></Field>
                <Button size="sm" type="submit" variant="danger" loading={busy}>Turn off</Button>
                <Button size="sm" variant="ghost" onClick={reset}>Cancel</Button>
              </form>
            )}
          </>
        ) : step === "idle" ? (
          <Button size="sm" variant="primary" icon={<KeyRound className="size-3.5" />} onClick={() => setStep("password")}>Set up two-factor authentication</Button>
        ) : step === "password" ? (
          <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); run(async () => { setSetup(await api("/auth/2fa/setup", { method: "POST", body: { password } })); setPassword(""); setStep("scan"); }); }}>
            <Field label="Confirm your password" htmlFor="tfa-pw"><Input id="tfa-pw" type="password" autoComplete="current-password" autoFocus value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
            <Button size="sm" type="submit" variant="primary" loading={busy}>Continue</Button>
            <Button size="sm" variant="ghost" onClick={reset}>Cancel</Button>
          </form>
        ) : setup && (
          <div className="space-y-3">
            <ol className="list-decimal space-y-1 pl-5 text-ink-700">
              <li>In your authenticator app, add an account and enter this setup key (or open the link on a device that has the app):</li>
            </ol>
            <code className="block rounded-md border border-ink-150 bg-white px-3 py-2 font-mono text-[14px] tracking-wider break-all text-ink-950" aria-label="Setup key">
              {setup.secret.match(/.{1,4}/g)?.join(" ")}
            </code>
            <a href={setup.otpauth_uri} className="inline-block text-teal-700 hover:underline">Open in authenticator app</a>
            <form className="flex flex-wrap items-end gap-2" onSubmit={(e) => { e.preventDefault(); run(async () => { const r = await api<{ recovery_codes: string[] }>("/auth/2fa/enable", { method: "POST", body: { code } }); setCodes(r.recovery_codes); setStep("codes"); toast({ tone: "success", title: "Two-factor authentication is on", description: "Other sessions were signed out." }); }); }}>
              <Field label="2. Enter the 6-digit code it shows" htmlFor="tfa-code"><Input id="tfa-code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} className="w-32" autoFocus value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} /></Field>
              <Button size="sm" type="submit" variant="primary" loading={busy} disabled={code.length !== 6}>Turn on</Button>
              <Button size="sm" variant="ghost" onClick={reset}>Cancel</Button>
            </form>
          </div>
        )}
      </div>
    </Card>
  );
}

interface AuditItem { id: number; action: string; actor: string; target_type: string; target_id: string; summary: string; details: Record<string, unknown>; ip: string; created_at: string }
const AUDIT_GROUPS = [
  ["", "All activity"], ["sources.", "Sources"], ["schedule.", "Schedules"], ["team.", "Team & roles"], ["security.", "Security"],
  ["brand.", "Brands"], ["takedown.", "Takedowns"], ["data.", "Exports & deletion"], ["monitoring.", "Monitoring settings"], ["detection.", "Detection settings"],
  ["webhook.", "Webhook"], ["organization.", "Organization"],
] as const;

export function AuditLogTab() {
  const [action, setAction] = useState("");
  const [page, setPage] = useState(0);
  const { data, error, loading } = useApi<{ total: number; items: AuditItem[] }>("/settings/audit", { action: action || undefined, limit: 50, offset: page * 50 });
  return (
    <Card>
      <CardHeader title={<span className="inline-flex items-center gap-2"><ScrollText className="size-4 text-ink-500" /> Audit log</span>}
        description="Who changed configuration, access or data in this organization. Secrets are never recorded."
        actions={<a href={`/api/settings/audit.csv${action ? `?action=${action}` : ""}`} download className="inline-flex h-8 items-center gap-1.5 rounded-md border border-ink-200 bg-white px-2.5 text-[12.5px] font-medium text-ink-700 hover:border-ink-300"><Download className="size-3.5" /> CSV</a>} />
      <div className="border-b border-ink-150 px-4 py-2.5">
        <Select aria-label="Activity type" className="h-8 w-auto text-[12.5px]" value={action} onChange={(e) => { setAction(e.target.value); setPage(0); }}>
          {AUDIT_GROUPS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </Select>
      </div>
      {error ? <div className="p-3"><ErrorState error={error} /></div> : loading && !data ? <div className="p-4"><Skeleton className="h-24" /></div> : !data?.items.length ? (
        <p className="px-4 py-3 text-[12.5px] text-ink-500">No activity recorded yet.</p>
      ) : (
        <>
          <ul className="divide-y divide-ink-150">
            {data.items.map((e) => (
              <li key={e.id} className="px-4 py-2 text-[12.5px]">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <code className="font-mono text-[11px] text-ink-500">{e.action}</code>
                  <span className="text-ink-900">{e.summary}</span>
                  <span className="ml-auto text-[11.5px] text-ink-400" title={dateTime(e.created_at)}>{relTime(e.created_at)}</span>
                </div>
                <div className="text-[11.5px] text-ink-500">{e.actor}{e.ip ? ` · ${e.ip}` : ""}</div>
              </li>
            ))}
          </ul>
          {data.total > 50 && (
            <div className="flex items-center justify-between border-t border-ink-150 px-4 py-2 text-[12px] text-ink-500">
              <span className="tabular">{page * 50 + 1}–{Math.min((page + 1) * 50, data.total)} of {data.total}</span>
              <div className="flex gap-1">
                <Button size="sm" variant="ghost" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                <Button size="sm" variant="ghost" disabled={(page + 1) * 50 >= data.total} onClick={() => setPage((p) => p + 1)}>Next</Button>
              </div>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
