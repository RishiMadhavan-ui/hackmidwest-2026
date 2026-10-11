"use client";

import { MandateForm } from "@/components/mandate-form";
import { replaceMandate, type Mandate } from "@/lib/api";

export function EditMandateForm({
  mandate,
  onSaved,
  onCancel,
}: {
  mandate: Mandate;
  onSaved: (next: Mandate) => void;
  onCancel: () => void;
}) {
  return (
    <MandateForm
      initial={mandate}
      title="Edit terms"
      intro={
        <>
          Saving creates version {mandate.version + 1} as a draft.
          {mandate.status === "active"
            ? " The current version stops being usable right away and the new one needs your confirmation."
            : " You'll confirm it next."}
        </>
      }
      submitLabel={`Save as version ${mandate.version + 1}`}
      onSubmit={async (proposal) => onSaved(await replaceMandate(mandate, proposal))}
      onCancel={onCancel}
    />
  );
}
