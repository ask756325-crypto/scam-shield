"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { Brand } from "@/lib/types";
import { useToast } from "../toast";
import { Button, Dialog } from "../ui";

export function DeleteBrandDialog({ brand, open, onClose, onDeleted }: { brand: Brand; open: boolean; onClose: () => void; onDeleted: () => void }) {
  const toast = useToast();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => setTyped(""), [open]);
  const counts = `${brand.official_accounts.length} official account${brand.official_accounts.length === 1 ? "" : "s"}, ${brand.official_apps.length} app${brand.official_apps.length === 1 ? "" : "s"}`;
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={`Delete ${brand.name}?`}
      description={`Permanently deletes the profile (${counts}), its logo, and every scan, finding, decision and exclusion record for it. This can’t be undone.`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button
            variant="danger"
            loading={busy}
            disabled={typed.trim() !== brand.name}
            onClick={async () => {
              setBusy(true);
              try {
                await api(`/brands/${brand.id}`, { method: "DELETE" });
                toast({ tone: "success", title: `${brand.name} deleted` });
                onDeleted();
              } catch (e) {
                toast({ tone: "error", title: "Could not delete", description: (e as Error).message });
                setBusy(false);
              }
            }}
          >
            Delete brand
          </Button>
        </>
      }
    >
      <label htmlFor="confirm-name" className="text-[12.5px] text-ink-700">
        Type <strong className="font-medium">{brand.name}</strong> to confirm
      </label>
      <input
        id="confirm-name"
        value={typed}
        onChange={(e) => setTyped(e.target.value)}
        autoComplete="off"
        className="mt-1.5 h-9 w-full rounded-md border border-ink-200 bg-white px-3 text-[13px] focus:border-teal-500 focus:ring-3 focus:ring-teal-500/15 focus:outline-none"
      />
    </Dialog>
  );
}
