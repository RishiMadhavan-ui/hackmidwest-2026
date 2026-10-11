"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { OctagonX } from "lucide-react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  engageKillSwitch,
  getKillSwitch,
  type KillSwitchResult,
  type KillSwitchState,
} from "@/lib/api";

type KillSwitchContextValue = {
  state: KillSwitchState | null;
  loadError: boolean;
  lastResult: KillSwitchResult | null;
  engage: () => Promise<KillSwitchResult>;
  refresh: () => Promise<void>;
};

const KillSwitchContext = createContext<KillSwitchContextValue | null>(null);

export function KillSwitchProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<KillSwitchState | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [lastResult, setLastResult] = useState<KillSwitchResult | null>(null);

  const refresh = useCallback(async () => {
    try {
      setState(await getKillSwitch());
      setLoadError(false);
    } catch {
      setLoadError(true);
    }
  }, []);

  useEffect(() => {
    let active = true;
    getKillSwitch()
      .then((value) => {
        if (active) setState(value);
      })
      .catch(() => {
        if (active) setLoadError(true);
      });
    return () => {
      active = false;
    };
  }, []);

  const engage = useCallback(async () => {
    const result = await engageKillSwitch();
    setLastResult(result);
    setState({
      on: true,
      rail_enforced: result.rail.status === "enforced",
      provider_controls_enforced: result.provider_card_controls.status !== "pending",
    });
    return result;
  }, []);

  const value = useMemo(
    () => ({ state, loadError, lastResult, engage, refresh }),
    [state, loadError, lastResult, engage, refresh],
  );
  return <KillSwitchContext.Provider value={value}>{children}</KillSwitchContext.Provider>;
}

export function useKillSwitch() {
  const ctx = useContext(KillSwitchContext);
  if (!ctx) throw new Error("useKillSwitch must be used within KillSwitchProvider");
  return ctx;
}

export function isFullyEnforced(state: KillSwitchState | null) {
  return !!state?.on && state.rail_enforced && state.provider_controls_enforced;
}

export function describeResult(result: KillSwitchResult): string {
  const cards = result.provider_card_controls;
  const cardText = cards.total
    ? `${cards.confirmed} of ${cards.total} sandbox card closures confirmed.`
    : "No sandbox cards needed closing.";
  if (result.status === "financially_stopped") {
    const grants = result.rail.unused_grants_revoked;
    const grantText = typeof grants === "number"
      ? `${grants} unused rail grant${grants === 1 ? "" : "s"} invalidated.`
      : "Unused rail grants invalidated.";
    return `${result.mandates_revoked} mandate${result.mandates_revoked === 1 ? "" : "s"} revoked. ${grantText} ${cardText} Agent cancellation has not been acknowledged yet.`;
  }
  return `Stop recorded and mandates revoked, but rail enforcement or card closure is still pending. Press the Kill Switch again to retry. ${cardText}`;
}

/** Human-only, account-wide stop. Agents have no route to this control. */
export function KillSwitchButton({ compact = false }: { compact?: boolean }) {
  const { state, engage } = useKillSwitch();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const enforced = isFullyEnforced(state);

  async function confirm() {
    setBusy(true);
    setFailed(false);
    try {
      const result = await engage();
      setMessage(describeResult(result));
    } catch {
      setFailed(true);
      setMessage("The stop outcome could not be confirmed. Retry the Kill Switch.");
    } finally {
      setBusy(false);
    }
  }

  const label = enforced
    ? "Stopped"
    : state?.on
      ? "Retry stop"
      : "Kill switch";

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (!next) {
          setMessage(null);
          setFailed(false);
        }
      }}
    >
      <Button
        variant={enforced ? "outline" : "danger"}
        size={compact ? "sm" : "default"}
        onClick={() => setOpen(true)}
        aria-label={enforced ? "Shopping stopped" : "Open Kill Switch"}
      >
        <OctagonX aria-hidden />
        {label}
      </Button>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {enforced ? "Shopping is stopped" : "Stop all shopping on this account?"}
          </DialogTitle>
          <DialogDescription>
            {enforced
              ? "Your mandates are revoked and unused rail grants are invalidated. Stopped authority can't be resumed."
              : "This revokes every mandate and invalidates unused spending grants on the payment rail. It can't be undone. Payments that were already authorized are not reversed."}
          </DialogDescription>
        </DialogHeader>
        {message ? (
          <p
            className={
              failed
                ? "rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger"
                : "rounded-lg bg-muted px-3 py-2 text-sm"
            }
            role="status"
          >
            {message}
          </p>
        ) : null}
        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>
            {message && !failed ? "Done" : "Cancel"}
          </DialogClose>
          {!enforced ? (
            <Button variant="danger" onClick={() => void confirm()} disabled={busy}>
              {busy ? "Stopping…" : state?.on ? "Retry enforcement" : "Stop everything"}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export function StoppedBanner() {
  const { state } = useKillSwitch();
  if (!state?.on) return null;
  const enforced = isFullyEnforced(state);
  return (
    <div className="border-b border-border bg-danger-soft">
      <div className="mx-auto flex max-w-6xl flex-col gap-1 px-4 py-2.5 text-sm text-danger sm:flex-row sm:items-center sm:gap-3 sm:px-6">
        <span className="font-semibold">Shopping is stopped on this account.</span>
        <span className="text-danger/90">
          {enforced
            ? "Mandates are revoked and unused grants are invalidated."
            : "Enforcement is still pending. Open the Kill Switch to retry."}
        </span>
      </div>
    </div>
  );
}
