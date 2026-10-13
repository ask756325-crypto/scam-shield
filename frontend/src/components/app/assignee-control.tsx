"use client";

import { UserRound } from "lucide-react";
import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Finding } from "@/lib/types";
import { useToast } from "../toast";
import { Select } from "../ui";

/** Assign a finding to an organization member (the API rejects anyone outside the organization). */
export function AssigneeControl({ f, onChange }: { f: Finding; onChange: (f: Finding) => void }) {
  const toast = useToast();
  const { data: org } = useApi<{ members: { user_id: number; name: string; email: string }[] }>("/settings/organization");
  const [busy, setBusy] = useState(false);
  const set = async (value: string) => {
    setBusy(true);
    try {
      const updated = await api<Finding>(`/findings/${f.id}/assignee`, { method: "PATCH", body: { user_id: value ? Number(value) : null } });
      onChange(updated);
      toast({ tone: "success", title: updated.assignee ? `Assigned to ${updated.assignee.name}` : "Unassigned" });
    } catch (e) {
      toast({ tone: "error", title: "Could not assign", description: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <label className="inline-flex items-center gap-1.5 text-[12px] text-ink-500">
      <UserRound className="size-3.5" />
      <span className="sr-only">Assignee</span>
      <Select aria-label="Assignee" className="h-7 w-auto min-w-[9rem] text-[12px]" disabled={busy || !org} value={f.assignee?.id ?? ""} onChange={(e) => set(e.target.value)}>
        <option value="">Unassigned</option>
        {org?.members.map((m) => <option key={m.user_id} value={m.user_id}>{m.name}</option>)}
      </Select>
    </label>
  );
}
