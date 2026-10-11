"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/lib/api";

type Resource<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
  refresh: () => Promise<void>;
  setData: (value: T) => void;
};

type State<T> = { key: string; data: T | null; error: string | null; loading: boolean };

export function errorMessage(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

/** Minimal fetch-on-mount state. A new `key` starts a fresh request. */
export function useResource<T>(fetcher: () => Promise<T>, key: string): Resource<T> {
  const [state, setState] = useState<State<T>>({ key, data: null, error: null, loading: true });
  const fetcherRef = useRef(fetcher);

  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const run = useCallback(
    (forKey: string, isActive: () => boolean) =>
      fetcherRef.current().then(
        (data) => {
          if (isActive()) setState({ key: forKey, data, error: null, loading: false });
        },
        (err: unknown) => {
          if (isActive()) {
            setState((s) => ({
              key: forKey,
              data: s.key === forKey ? s.data : null,
              error: errorMessage(err, "Request failed"),
              loading: false,
            }));
          }
        },
      ),
    [],
  );

  useEffect(() => {
    let active = true;
    void run(key, () => active);
    return () => {
      active = false;
    };
  }, [key, run]);

  const refresh = useCallback(async () => {
    setState((s) => ({ ...s, loading: true }));
    await run(key, () => true);
  }, [key, run]);

  const setData = useCallback(
    (value: T) => setState({ key, data: value, error: null, loading: false }),
    [key],
  );

  const current = state.key === key;
  return {
    data: current ? state.data : null,
    error: current ? state.error : null,
    loading: !current || state.loading,
    refresh,
    setData,
  };
}

/** Current time that re-renders periodically; keeps Date.now() out of render. */
export function useNow(intervalMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(timer);
  }, [intervalMs]);
  return now;
}
