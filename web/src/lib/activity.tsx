"use client";

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { streamActivity, type ActivityEvent } from "@/lib/api";

export type StreamStatus = "idle" | "connecting" | "live" | "error";

type ActivityContextValue = {
  events: ActivityEvent[];
  status: StreamStatus;
  error: string | null;
};

const ActivityContext = createContext<ActivityContextValue | null>(null);

const MAX_EVENTS = 2000;

/**
 * One authenticated SSE connection per signed-in session. It replays
 * persisted history from the start, then follows new events; reconnecting
 * resumes from the last sequence and never starts a run.
 */
export function ActivityProvider({ children }: { children: ReactNode }) {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [status, setStatus] = useState<StreamStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const seen = useRef(new Set<string>());

  useEffect(() => {
    seen.current = new Set();
    const stop = streamActivity({
      after: 0,
      onStatus: (next) => {
        setStatus(next);
        if (next === "live") setError(null);
      },
      onEvent: (event) => {
        if (seen.current.has(event.event_id)) return;
        seen.current.add(event.event_id);
        setEvents((prev) => {
          // Strict Mode may replay the effect while retaining state. Also defend
          // against duplicate delivery across reconnects and stream restarts.
          if (prev.some((old) => old.event_id === event.event_id || old.sequence === event.sequence)) return prev;
          const next = prev.length && prev[prev.length - 1].sequence < event.sequence
            ? [...prev, event]
            : [...prev, event].sort((a, b) => a.sequence - b.sequence);
          return next.length > MAX_EVENTS ? next.slice(-MAX_EVENTS) : next;
        });
      },
      onError: (err) => setError(err.message),
    });
    return stop;
  }, []);

  const value = useMemo(() => ({ events, status, error }), [events, status, error]);
  return <ActivityContext.Provider value={value}>{children}</ActivityContext.Provider>;
}

export function useActivity() {
  const ctx = useContext(ActivityContext);
  if (!ctx) throw new Error("useActivity must be used within ActivityProvider");
  return ctx;
}
