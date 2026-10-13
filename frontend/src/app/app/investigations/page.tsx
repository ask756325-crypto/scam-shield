"use client";

import { Suspense } from "react";
import { FindingsExplorer } from "@/components/app/findings-explorer";
import { PageHeader, Skeleton } from "@/components/ui";

export default function InvestigationsPage() {
  return (
    <div className="animate-fade-in">
      <PageHeader
        eyebrow="Investigate"
        title="Investigations"
        description="Every retained candidate for the selected brand, across social and app-store sources. Open a finding to see the evidence, signal breakdown and decision history."
      />
      <Suspense fallback={<Skeleton className="h-64" />}>
        <FindingsExplorer
          sourceOptions={[
            { value: "bluesky", label: "Bluesky" },
            { value: "mastodon", label: "Mastodon" },
            { value: "apple_app_store", label: "App Store" },
            { value: "google_play", label: "Google Play" },
            { value: "import", label: "CSV import" },
          ]}
        />
      </Suspense>
    </div>
  );
}
