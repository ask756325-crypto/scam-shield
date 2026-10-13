"use client";

import { Check, ClipboardCopy, ExternalLink, Gavel } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { relTime } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { useToast } from "../toast";
import { Badge, Button, Card, CardHeader, Field, Input, Skeleton, Textarea, cx } from "../ui";

export interface TakedownCase {
  id: number; finding_id: number; platform: string; channel_label: string; channel_url: string | null; instructions: string | null;
  status: "draft" | "reported" | "acknowledged" | "removed" | "rejected" | "withdrawn"; reference: string; report_text: string;
  events: { at: string; status: string; note: string; user: string }[]; verification: "unknown" | "still_observed" | "not_observed" | "reappeared";
  verified_scan_id: number | null; verified_at: string | null; reported_at: string | null; closed_at: string | null; created_at: string;
  allowed_next: string[]; candidate: { name: string; handle: string | null; url: string | null; source_type: string } | null;
  brand_name: string | null; finding_status: string | null; risk_level: string | null;
}

export const TAKEDOWN_STATUS: Record<string, { label: string; tone: "outline" | "teal" | "med" | "forest" | "crit" }> = {
  draft: { label: "Draft", tone: "outline" },
  reported: { label: "Reported", tone: "teal" },
  acknowledged: { label: "Acknowledged", tone: "med" },
  removed: { label: "Removed", tone: "forest" },
  rejected: { label: "Rejected", tone: "crit" },
  withdrawn: { label: "Withdrawn", tone: "outline" },
};
export const VERIFICATION: Record<string, { label: string; className: string }> = {
  unknown: { label: "Not yet re-checked", className: "text-ink-500" },
  still_observed: { label: "Still visible in the latest scan", className: "text-med" },
  not_observed: { label: "No longer observed in consecutive clean scans", className: "text-forest-700" },
  reappeared: { label: "Seen again after being marked removed", className: "text-crit" },
};
const ACTION_LABEL: Record<string, string> = {
  reported: "Mark reported", acknowledged: "Platform acknowledged", removed: "Mark removed", rejected: "Platform rejected", withdrawn: "Withdraw", draft: "Reopen as draft",
};

export function TakedownCard({ findingId, findingStatus, synthetic }: { findingId: number; findingStatus: string; synthetic: boolean }) {
  const toast = useToast();
  const { data, loading, setData } = useApi<{ case: TakedownCase | null; eligible: boolean }>(`/findings/${findingId}/takedown`, { _s: findingStatus });
  const [busy, setBusy] = useState<string | null>(null);
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const [text, setText] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  if (loading && !data) return <Card><div className="p-4"><Skeleton className="h-20" /></div></Card>;
  if (!data) return null;
  const c = data.case;

  const open = async () => {
    setBusy("open");
    try {
      const created = await api<TakedownCase>(`/findings/${findingId}/takedown`, { method: "POST" });
      setData({ case: created, eligible: true });
      toast({ tone: "success", title: "Takedown case opened", description: "Review the generated report, then file it with the platform." });
    } catch (e) {
      toast({ tone: "error", title: "Could not open a case", description: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };
  const patch = async (body: Record<string, unknown>, label: string) => {
    if (!c) return;
    setBusy(label);
    try {
      const updated = await api<TakedownCase>(`/takedowns/${c.id}`, { method: "PATCH", body });
      setData({ case: updated, eligible: true });
      setNote("");
      setText(null);
      toast({ tone: "success", title: "Takedown updated", description: TAKEDOWN_STATUS[updated.status].label });
    } catch (e) {
      toast({ tone: "error", title: "Not updated", description: (e as Error).message });
    } finally {
      setBusy(null);
    }
  };
  const copy = async () => {
    if (!c) return;
    try {
      await navigator.clipboard.writeText(c.report_text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      toast({ tone: "error", title: "Copy failed", description: "Select the text and copy it manually." });
    }
  };

  return (
    <Card>
      <CardHeader title={<span className="inline-flex items-center gap-2"><Gavel className="size-4 text-ink-500" /> Takedown</span>}
        description="Prepare a report for the platform’s own reporting route and track the outcome. ScamShield never files reports for you."
        actions={c && <Badge tone={TAKEDOWN_STATUS[c.status].tone} dot>{TAKEDOWN_STATUS[c.status].label}</Badge>} />
      {!c ? (
        <div className="space-y-2 p-4 text-[12.5px]">
          {data.eligible ? (
            <>
              <p className="text-ink-600">Open a case to generate an evidence-based report for this {synthetic ? "synthetic demo " : ""}finding.</p>
              {synthetic && <p className="text-med">This is a synthetic record — the generated report is for demonstration only and must not be filed.</p>}
              <Button variant="primary" size="sm" loading={busy === "open"} onClick={open}>Open takedown case</Button>
            </>
          ) : (
            <p className="text-ink-500">Available after the finding is confirmed as an impersonation.</p>
          )}
        </div>
      ) : (
        <div className="space-y-3 p-4 text-[12.5px]">
          <div>
            <div className="font-medium text-ink-900">{c.channel_label}</div>
            {c.instructions && <p className="mt-0.5 text-ink-600">{c.instructions}</p>}
            {c.channel_url && (
              <a href={c.channel_url} target="_blank" rel="noopener noreferrer" className="mt-1 inline-flex items-center gap-1 text-teal-700 hover:underline">
                Open reporting page <ExternalLink className="size-3" />
              </a>
            )}
            <p className="mt-1 text-[11px] text-ink-400">Reporting pages change — check that the form still matches before filing.</p>
          </div>
          {c.status !== "draft" && (
            <p className={cx("text-[12px]", VERIFICATION[c.verification].className)}>
              {VERIFICATION[c.verification].label}{c.verified_at && <span className="text-ink-400"> · checked {relTime(c.verified_at)}</span>}
            </p>
          )}
          <div>
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[11px] font-medium tracking-wide text-ink-500 uppercase">Report</span>
              <Button size="sm" variant="ghost" icon={copied ? <Check className="size-3.5" /> : <ClipboardCopy className="size-3.5" />} onClick={copy}>{copied ? "Copied" : "Copy"}</Button>
            </div>
            {c.status === "draft" && text !== null ? (
              <>
                <Textarea aria-label="Report text" rows={10} value={text} onChange={(e) => setText(e.target.value)} />
                <div className="mt-1.5 flex gap-2">
                  <Button size="sm" variant="primary" loading={busy === "text"} onClick={() => patch({ report_text: text }, "text")}>Save text</Button>
                  <Button size="sm" variant="ghost" onClick={() => setText(null)}>Cancel</Button>
                </div>
              </>
            ) : (
              <>
                <pre className="max-h-52 overflow-auto rounded-md border border-ink-150 bg-white p-2.5 font-sans text-[11.5px] leading-relaxed whitespace-pre-wrap text-ink-800">{c.report_text}</pre>
                {c.status === "draft" && <Button size="sm" variant="ghost" className="mt-1" onClick={() => setText(c.report_text)}>Edit text</Button>}
              </>
            )}
          </div>
          {c.allowed_next.length > 0 && (
            <div className="space-y-2 border-t border-ink-150 pt-3">
              <Field label="Platform reference" htmlFor={`ref-${c.id}`} hint={c.reference ? `Current: ${c.reference}` : "Ticket or case number from the platform, if any"}>
                <Input id={`ref-${c.id}`} value={reference} onChange={(e) => setReference(e.target.value)} placeholder={c.reference || "e.g. case 12345"} />
              </Field>
              <Field label="Note" htmlFor={`note-${c.id}`}>
                <Input id={`note-${c.id}`} value={note} onChange={(e) => setNote(e.target.value)} placeholder="What happened?" />
              </Field>
              <div className="flex flex-wrap gap-1.5">
                {c.allowed_next.map((s) => (
                  <Button key={s} size="sm" variant={s === "reported" || s === "removed" ? "primary" : "ghost"} loading={busy === s}
                    onClick={() => patch({ status: s, note, ...(reference ? { reference } : {}) }, s)}>
                    {ACTION_LABEL[s] ?? s}
                  </Button>
                ))}
              </div>
            </div>
          )}
          <ol className="space-y-1 border-t border-ink-150 pt-3">
            {[...c.events].reverse().map((e, i) => (
              <li key={i} className="text-[11.5px]">
                <span className="font-medium text-ink-800">{TAKEDOWN_STATUS[e.status]?.label ?? e.status}</span>
                <span className="text-ink-400"> · {relTime(e.at)} · {e.user}</span>
                {e.note && <div className="text-ink-600">{e.note}</div>}
              </li>
            ))}
          </ol>
        </div>
      )}
    </Card>
  );
}
