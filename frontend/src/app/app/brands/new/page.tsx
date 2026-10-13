"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { BrandForm, EMPTY_BRAND } from "@/components/app/brand-form";
import { useBrands } from "@/components/app/providers";
import { useToast } from "@/components/toast";
import { PageHeader } from "@/components/ui";
import { api } from "@/lib/api";
import type { Brand } from "@/lib/types";

export default function NewBrandPage() {
  const router = useRouter();
  const toast = useToast();
  const { reloadBrands, select } = useBrands();
  const [logo, setLogo] = useState<File | null>(null);
  return (
    <div className="animate-fade-in space-y-4">
      <Link href="/app/brands" className="inline-flex items-center gap-1.5 text-[12.5px] text-ink-500 hover:text-ink-900">
        <ArrowLeft className="size-3.5" /> Brand profiles
      </Link>
      <PageHeader
        eyebrow="New brand profile"
        title="Describe the brand you protect"
        description="Only the name is required — start partial and add official assets later. The more official assets you list, the fewer of your own accounts and apps you’ll review."
      />
      <BrandForm
        initial={EMPTY_BRAND}
        submitLabel="Create brand"
        pendingLogo={logo}
        onPendingLogo={setLogo}
        onSubmit={async (p) => {
          const b = await api<Brand>("/brands", { method: "POST", body: p });
          let logoNote = "Add a logo to enable logo matching, then run a scan.";
          if (logo) {
            const fd = new FormData();
            fd.append("file", logo);
            try {
              await api(`/brands/${b.id}/logo`, { method: "POST", body: fd });
              logoNote = "Logo saved and hashed. Run a scan when you’re ready.";
            } catch (e) {
              // The profile exists either way; report the logo problem instead of pretending it worked.
              toast({ tone: "error", title: "Brand created, but the logo was rejected", description: (e as Error).message });
              logoNote = "Upload a different logo from the profile page.";
            }
          }
          setLogo(null);
          await reloadBrands();
          select(b.id);
          toast({ tone: "success", title: `${b.name} created`, description: logoNote });
          router.push(`/app/brands/${b.id}`);
        }}
      />
    </div>
  );
}
