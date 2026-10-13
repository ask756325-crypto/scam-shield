"use client";

import { ChevronDown, Eye } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { cx } from "../ui";

interface Preview {
  search_terms: string[];
  examples: { text: string; technique: string; kind: string; similarity: number; flagged: boolean }[];
  note: string;
}

/** Before the first scan: the search terms that will be used and illustrative look-alikes the engine would flag. */
export function LookalikePreview({ name, aliases }: { name: string; aliases: string[] }) {
  const [open, setOpen] = useState(false);
  const [data, setData] = useState<Preview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const key = `${name.trim()}|${aliases.join(",")}`;
  useEffect(() => {
    if (!open || name.trim().length < 2) return;
    const t = setTimeout(() => {
      api<Preview>("/brands/preview-variants", { query: { name: name.trim(), aliases } })
        .then((d) => { setData(d); setError(null); })
        .catch((e) => setError((e as Error).message));
    }, 350);
    return () => clearTimeout(t);
  }, [open, key]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="border-t border-ink-150">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} disabled={name.trim().length < 2}
        className="flex w-full items-center gap-1.5 px-4 py-2.5 text-left text-[12.5px] font-medium text-ink-700 hover:text-ink-950 disabled:text-ink-400">
        <Eye className="size-3.5" /> Preview look-alikes ScamShield will watch for
        <ChevronDown className={cx("ml-auto size-3.5 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div className="space-y-3 px-4 pb-4 text-[12.5px]">
          {error && <p className="text-crit">{error}</p>}
          {!data ? <p className="text-ink-400">Loading…</p> : (
            <>
              <div>
                <div className="text-[11px] font-medium tracking-wide text-ink-500 uppercase">Search terms sent to each source</div>
                <div className="mt-1 flex flex-wrap gap-1.5">{data.search_terms.map((t) => <code key={t} className="rounded border border-ink-150 bg-white px-1.5 py-0.5 font-mono text-[11.5px]">{t}</code>)}</div>
              </div>
              <div>
                <div className="text-[11px] font-medium tracking-wide text-ink-500 uppercase">Example look-alikes</div>
                <ul className="mt-1 grid gap-x-6 gap-y-1 sm:grid-cols-2">
                  {data.examples.map((x) => (
                    <li key={x.text} className="flex items-baseline gap-2">
                      <span className={cx("size-1.5 shrink-0 translate-y-[-1px] rounded-full", x.flagged ? "bg-forest-500" : "bg-ink-300")} title={x.flagged ? "Would be flagged for review" : "Below the name-similarity threshold on its own"} />
                      <code className="font-mono text-[12px] text-ink-900">{x.text}</code>
                      <span className="truncate text-[11.5px] text-ink-500">{x.technique}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <p className="text-[11.5px] text-ink-500">{data.note} Green: the name alone would put it in review; risk still depends on corroborating evidence.</p>
            </>
          )}
        </div>
      )}
    </div>
  );
}
