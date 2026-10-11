"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { NaturalMandate } from "@/components/natural-mandate";
import { PageHeader } from "@/components/page";

export default function NewMandatePage() {
  const router = useRouter();
  return <>
    <Link className="text-sm text-muted-foreground" href="/mandates">← Mandates</Link>
    <PageHeader title="New mandate" description="Describe your purchase, review the generated terms, then explicitly confirm." />
    <div className="max-w-3xl"><NaturalMandate onDraft={(draft) => router.push(`/mandates/${encodeURIComponent(draft.id)}`)} /></div>
  </>;
}
