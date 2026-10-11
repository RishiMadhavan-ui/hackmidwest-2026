"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError, startShopping, type StartShoppingResult } from "@/lib/api";
import type { PurchaseMandate } from "@/lib/mandates";
import { cn } from "@/lib/utils";

type Mode = "live" | "scripted_charger" | "scripted_attack";

const MODES: {
  id: Mode;
  label: string;
  hint: string;
}[] = [
  {
    id: "live",
    label: "Live Strands shopper",
    hint: "Real model + MCP tools under this mandate.",
  },
  {
    id: "scripted_charger",
    label: "Scripted charger",
    hint: "Labeled fixture: checks out CHG-65W through real tools.",
  },
  {
    id: "scripted_attack",
    label: "Scripted compromised agent",
    hint: "Labeled fixture: attempts SUB-CARE-MO while claiming a charger.",
  },
];

function requestFor(mode: Mode, mandateId: string) {
  if (mode === "scripted_attack") {
    return {
      mandate_id: mandateId,
      agent_mode: "scripted" as const,
      scenario: "subscription_attack" as const,
    };
  }
  if (mode === "scripted_charger") {
    return {
      mandate_id: mandateId,
      agent_mode: "scripted" as const,
      scenario: "charger" as const,
    };
  }
  return {
    mandate_id: mandateId,
    agent_mode: "live" as const,
    scenario: "charger" as const,
  };
}

export function StartShopping({
  mandate,
}: {
  mandate: PurchaseMandate | null;
}) {
  const [mode, setMode] = useState<Mode>("live");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [last, setLast] = useState<StartShoppingResult | null>(null);

  const canStart = !!mandate && mandate.status === "active";

  async function onStart() {
    if (!mandate) return;
    setBusy(true);
    setError(null);
    try {
      const result = await startShopping(requestFor(mode, mandate.id));
      setLast(result);
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Could not start shopping";
      setError(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div>
        <h2 className="text-base font-semibold tracking-tight">Start shopping</h2>
        <p className="text-xs text-muted-foreground">
          Human-only. The API starts the agents service with a server credential —
          nothing secret is sent to the browser.
        </p>
      </div>

      <fieldset className="grid gap-2" disabled={!canStart || busy}>
        <legend className="sr-only">Shopper mode</legend>
        {MODES.map((item) => (
          <label
            key={item.id}
            className={cn(
              "flex cursor-pointer gap-3 rounded-lg border border-border px-3 py-2 text-sm",
              mode === item.id && "border-ring bg-muted/30",
              !canStart && "opacity-60",
            )}
          >
            <input
              type="radio"
              name="shopper-mode"
              className="mt-1"
              checked={mode === item.id}
              onChange={() => setMode(item.id)}
            />
            <span>
              <span className="font-medium">{item.label}</span>
              <span className="mt-0.5 block text-xs text-muted-foreground">
                {item.hint}
              </span>
            </span>
          </label>
        ))}
      </fieldset>

      <Button type="button" onClick={() => void onStart()} disabled={!canStart || busy}>
        {busy ? "Starting…" : "Start shopping"}
      </Button>

      {!canStart ? (
        <p className="text-xs text-muted-foreground">
          Confirm an active mandate above before starting a shopper.
        </p>
      ) : null}

      {last ? (
        <p className="text-xs text-success" role="status">
          Started {last.label}: <span className="font-mono">{last.run_id}</span>.
          Watch Live activity for tool and payment events.
        </p>
      ) : null}
      {error ? (
        <p className="text-xs text-destructive" role="alert">
          {error}
        </p>
      ) : null}
    </div>
  );
}
