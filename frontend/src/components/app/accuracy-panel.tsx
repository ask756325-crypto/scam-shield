"use client";

import { ChevronDown, FlaskConical, Target } from "lucide-react";
import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { sourceLabel } from "@/lib/format";
import { useApi } from "@/lib/hooks";
import { Badge, Card, CardHeader, ErrorState, Notice, Skeleton, cx } from "../ui";
import { RiskBadge } from "./bits";

interface M { tp: number; fp: number; fn: number; tn: number; precision: number | null; recall: number | null; f1: number | null }
interface Summary {
  labelled: number; positives: number; negatives: number; enough_labels: boolean;
  by_threshold: Record<"critical" | "high" | "medium" | "low", M>;
  score_sweep: (M & { min_score: number })[];
  best_f1_threshold: (M & { min_score: number }) | null;
  note: string;
}
interface Analyst extends Summary { excluded_simulated: number; by_source_at_medium: Record<string, M & { labelled: number }> }
interface Bench extends Summary {
  official_assets_flagged: string[];
  cases: { id: string; category: string; label: string; excluded: boolean; risk_level: string | null; risk_score: number | null; name: string; predicted_at_medium?: boolean }[];
}

const pct = (v: number | null) => (v === null ? "—" : `${Math.round(v * 100)}%`);

function ThresholdTable({ s }: { s: Summary }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-left text-[12.5px]">
        <thead className="border-b border-ink-150 bg-ink-50/70 text-[11.5px] text-ink-500">
          <tr>
            <th className="py-2 pr-3 pl-4 font-medium">Flag at</th>
            <th className="px-3 py-2 text-right font-medium" title="Of the findings flagged, how many were real impersonations">Precision</th>
            <th className="px-3 py-2 text-right font-medium" title="Of the real impersonations, how many were flagged">Recall</th>
            <th className="px-3 py-2 text-right font-medium">F1</th>
            <th className="py-2 pr-4 pl-3 text-right font-medium">TP · FP · FN · TN</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-ink-150">
          {(["critical", "high", "medium", "low"] as const).map((l) => {
            const m = s.by_threshold[l];
            return (
              <tr key={l}>
                <td className="py-2 pr-3 pl-4"><RiskBadge level={l} /> <span className="text-[11.5px] text-ink-500">and above</span></td>
                <td className="tabular px-3 py-2 text-right text-ink-900">{pct(m.precision)}</td>
                <td className="tabular px-3 py-2 text-right text-ink-900">{pct(m.recall)}</td>
                <td className="tabular px-3 py-2 text-right text-ink-700">{m.f1 === null ? "—" : m.f1.toFixed(2)}</td>
                <td className="tabular py-2 pr-4 pl-3 text-right text-ink-500">{m.tp} · {m.fp} · {m.fn} · {m.tn}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function Sweep({ s }: { s: Summary }) {
  const data = s.score_sweep.map((x) => ({ score: x.min_score, Precision: x.precision === null ? null : Math.round(x.precision * 100), Recall: x.recall === null ? null : Math.round(x.recall * 100) }));
  return (
    <div className="px-2 pb-2">
      <div className="h-48">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 8, right: 16, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="var(--color-ink-150)" vertical={false} />
            <XAxis dataKey="score" tick={{ fontSize: 11 }} stroke="var(--color-ink-400)" label={{ value: "minimum score", position: "insideBottomRight", offset: -2, fontSize: 10 }} />
            <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} stroke="var(--color-ink-400)" unit="%" />
            <Tooltip formatter={(v) => `${v}%`} labelFormatter={(l) => `Score ≥ ${l}`} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Line type="monotone" dataKey="Precision" stroke="var(--color-teal-600)" dot={false} strokeWidth={2} connectNulls />
            <Line type="monotone" dataKey="Recall" stroke="var(--color-high)" dot={false} strokeWidth={2} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {s.best_f1_threshold && (
        <p className="px-2 text-[11.5px] text-ink-500">
          Best balance (F1) at score ≥ <span className="tabular font-medium text-ink-800">{s.best_f1_threshold.min_score}</span>: precision {pct(s.best_f1_threshold.precision)}, recall {pct(s.best_f1_threshold.recall)}.
          Adjust level thresholds in “Risk levels” below if your team prefers fewer misses or fewer false alarms.
        </p>
      )}
    </div>
  );
}

export function AccuracyPanel() {
  const { data: a, error: ea } = useApi<Analyst>("/evaluation");
  const { data: b, error: eb } = useApi<Bench>("/evaluation/benchmark");
  const [showCases, setShowCases] = useState(false);
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title={<span className="inline-flex items-center gap-2"><Target className="size-4 text-ink-500" /> Accuracy on your analysts’ decisions</span>}
          description="Precision: of the findings flagged at a level, how many your analysts confirmed. Recall: of the confirmed impersonations, how many were flagged at that level." />
        {ea ? <div className="p-3"><ErrorState error={ea} /></div> : !a ? <div className="p-4"><Skeleton className="h-32" /></div> : (
          <>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-[12.5px] text-ink-700">
              <span><span className="tabular font-medium">{a.labelled}</span> labelled findings</span>
              <span className="text-ink-500">{a.positives} confirmed · {a.negatives} marked legitimate</span>
              {a.excluded_simulated > 0 && <span className="text-ink-400">{a.excluded_simulated} synthetic decisions not counted</span>}
            </div>
            {!a.enough_labels && (
              <div className="px-4 pb-3">
                <Notice tone="warn">
                  {a.labelled === 0
                    ? "No live findings have been confirmed or marked legitimate yet. Review findings from real scans to measure accuracy."
                    : `Only ${a.labelled} labelled finding${a.labelled === 1 ? "" : "s"} (need at least 20, with both outcomes) — treat these numbers as anecdotal.`}
                </Notice>
              </div>
            )}
            {a.labelled > 0 && <><ThresholdTable s={a} /><Sweep s={a} /></>}
            {Object.keys(a.by_source_at_medium).length > 0 && (
              <div className="border-t border-ink-150 px-4 py-2.5 text-[12px] text-ink-600">
                At medium and above:{" "}
                {Object.entries(a.by_source_at_medium).map(([src, m]) => (
                  <span key={src} className="mr-3">{sourceLabel(src)} — precision {pct(m.precision)}, recall {pct(m.recall)} <span className="text-ink-400">({m.labelled})</span></span>
                ))}
              </div>
            )}
            <p className="border-t border-ink-150 px-4 py-2 text-[11.5px] text-ink-500">{a.note}</p>
          </>
        )}
      </Card>

      <Card>
        <CardHeader title={<span className="inline-flex items-center gap-2"><FlaskConical className="size-4 text-ink-500" /> Regression benchmark</span>}
          description="A small hand-labelled synthetic set run through the live engine on every test run. It guards against regressions — it is not a measure of real-world accuracy." actions={<Badge tone="med">Synthetic</Badge>} />
        {eb ? <div className="p-3"><ErrorState error={eb} /></div> : !b ? <div className="p-4"><Skeleton className="h-32" /></div> : (
          <>
            <div className="flex flex-wrap gap-x-4 px-4 py-2.5 text-[12.5px] text-ink-700">
              <span>{b.positives} impersonations · {b.negatives} legitimate look-alikes · {b.cases.filter((c) => c.label === "official").length} official assets</span>
              <span className={b.official_assets_flagged.length ? "text-crit" : "text-forest-700"}>{b.official_assets_flagged.length ? `${b.official_assets_flagged.length} official asset(s) not excluded` : "All official assets excluded"}</span>
            </div>
            <ThresholdTable s={b} />
            <button type="button" onClick={() => setShowCases((v) => !v)} aria-expanded={showCases} className="flex w-full items-center gap-1 border-t border-ink-150 px-4 py-2 text-[12px] font-medium text-ink-600 hover:text-ink-900">
              <ChevronDown className={cx("size-3.5 transition-transform", showCases && "rotate-180")} /> {showCases ? "Hide" : "Show"} all {b.cases.length} cases
            </button>
            {showCases && (
              <ul className="divide-y divide-ink-150 border-t border-ink-150">
                {b.cases.map((c) => {
                  const wrong = c.label !== "official" && c.predicted_at_medium !== (c.label === "impersonation");
                  return (
                    <li key={c.id} className={cx("flex flex-wrap items-center gap-x-3 gap-y-0.5 px-4 py-1.5 text-[12px]", wrong && "bg-med/5")}>
                      <code className="w-8 font-mono text-[11px] text-ink-400">{c.id}</code>
                      <span className="min-w-0 flex-1 truncate text-ink-900">{c.name} <span className="text-ink-500">· {c.category}</span></span>
                      <Badge tone={c.label === "impersonation" ? "crit" : c.label === "official" ? "forest" : "outline"}>{c.label}</Badge>
                      {c.excluded ? <span className="text-forest-700">excluded</span> : c.risk_level && <RiskBadge level={c.risk_level as "low"} score={c.risk_score ?? undefined} />}
                      {wrong && <span className="text-med">{c.label === "impersonation" ? "missed at medium" : "false alarm at medium"}</span>}
                    </li>
                  );
                })}
              </ul>
            )}
            <p className="border-t border-ink-150 px-4 py-2 text-[11.5px] text-ink-500">{b.note}</p>
          </>
        )}
      </Card>
    </div>
  );
}
