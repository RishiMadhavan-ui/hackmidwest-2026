"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";

type StopState = { on: boolean; rail_enforced: boolean; provider_controls_enforced: boolean };
type StopResult = { status: string; rail: { status: string }; provider_card_controls: { status: string; total: number; confirmed: number } };

export function KillSwitch() {
  const [state, setState] = useState<StopState | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    apiFetch<StopState>("/killswitch").then((value) => {
      if (active) setState(value);
    }).catch(() => { if (active) setMessage("Could not load shopping control status."); });
    return () => { active = false; };
  }, []);
  async function stop() {
    if (!window.confirm("Stop shopping and revoke unused spending permissions? Already authorized payments will not be reversed.")) return;
    setBusy(true);
    try {
      const result = await apiFetch<StopResult>("/killswitch", {
        method: "POST", body: JSON.stringify({ on: true }),
      });
      setState({ on: true, rail_enforced: result.rail.status === "enforced", provider_controls_enforced: result.provider_card_controls.status !== "pending" });
      const cards = result.provider_card_controls;
      setMessage(result.status === "stopped"
        ? `Mandates revoked and unused rail grants stopped. Run cancellation requested. ${cards.total ? `${cards.confirmed} sandbox card control(s) confirmed.` : "No provider cards require a pause."}`
        : "Stop requested and mandates revoked. Spending enforcement or sandbox card pause is pending; retry to confirm.");
    } catch {
      setMessage("Stop outcome could not be confirmed. Retry this stop request.");
    } finally { setBusy(false); }
  }
  return (
    <section className="flex flex-col gap-2 border-t border-border pt-4">
      <Button variant="destructive" onClick={stop} disabled={busy || !!(state?.rail_enforced && state.provider_controls_enforced)}>
        {busy ? "Stopping…" : state?.rail_enforced && state.provider_controls_enforced ? "Spending stopped" : state?.on ? "Retry stop enforcement" : "Stop shopping"}
      </Button>
      <p className="text-xs text-muted-foreground">Already authorized purchases are not reversed.</p>
      {message ? <p className="text-xs" role="status">{message}</p> : null}
    </section>
  );
}
