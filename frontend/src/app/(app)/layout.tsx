import { AppShell } from "@/components/app-shell";
import { PrefillProvider } from "@/lib/prefill";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <PrefillProvider>
      <AppShell>{children}</AppShell>
    </PrefillProvider>
  );
}
