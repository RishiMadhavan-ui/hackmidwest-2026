import { Suspense } from "react";

import { MandateDetail } from "./mandate-detail";

export default function MandatePage() {
  return (
    <Suspense fallback={<p className="py-8 text-sm text-muted-foreground">Loading mandate…</p>}>
      <MandateDetail />
    </Suspense>
  );
}
