import type { ReactNode } from "react";

import { PublicHeader } from "@/components/public-header";

export default function PublicLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <PublicHeader />
      <main className="flex flex-1 flex-col">{children}</main>
      <footer className="border-t border-border">
        <div className="mx-auto flex max-w-6xl flex-col gap-1 px-4 py-6 text-xs text-muted-foreground sm:flex-row sm:justify-between sm:px-6">
          <span>Leash · Hack Midwest 2026</span>
          <span>Sandbox only: Local Payment Rail Simulator or Lithic sandbox. No live funds.</span>
        </div>
      </footer>
    </>
  );
}
