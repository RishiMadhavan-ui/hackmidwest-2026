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
    if (!window.confirm("Emergency Kill Switch: stop ALL your purchases and revoke your account's unused spending permissions? Already authorized payments will not be reversed.")) return;
    setBusy(true);
    try {
      const result = await apiFetch<StopResult>("/killswitch", {
        method: "POST", body: JSON.stringify({ on: true }),
      });
      setState({ on: true, rail_enforced: result.rail.status === "enforced", provider_controls_enforced: result.provider_card_controls.status !== "pending" });
      const cards = result.provider_card_controls;
      setMessage(result.status === "financially_stopped"
        ? `Account mandates revoked and unused rail grants stopped. Graph cancellation has not been acknowledged. ${cards.total ? `${cards.confirmed} sandbox card closure(s) confirmed.` : "No provider cards were recorded."}`
        : "Emergency stop requested and mandates revoked. Spending enforcement or sandbox card closure is pending; retry to confirm. Graph cancellation has not been acknowledged.");
    } catch {
      setMessage("Stop outcome could not be confirmed. Retry this stop request.");
    } finally { setBusy(false); }
  }
  return (
    <section className="flex flex-col gap-2 border-t border-border pt-4">
      <h3 className="text-sm font-medium">Emergency Kill Switch</h3>
      <Button variant="destructive" onClick={stop} disabled={busy || !!(state?.rail_enforced && state.provider_controls_enforced)}>
        {busy ? "Requesting emergency stop…" : state?.rail_enforced && state.provider_controls_enforced ? "Account financial stop confirmed" : state?.on ? "Retry emergency enforcement" : "Emergency Kill Switch"}
      </Button>
      <p className="text-xs text-muted-foreground">Account-wide: all your runs and mandates. Graph cancellation remains unacknowledged. Already authorized purchases are not reversed.</p>
      {message ? <p className="text-xs" role="status">{message}</p> : null}
    </section>
  );
}
