import { AppProviders } from "@/components/app/providers";
import { AppShell } from "@/components/app/shell";
import { ToastProvider } from "@/components/toast";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <ToastProvider>
      <AppProviders>
        <AppShell>{children}</AppShell>
      </AppProviders>
    </ToastProvider>
  );
}
