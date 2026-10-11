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

import {
  login as apiLogin,
  logoutSession as apiLogout,
  me as apiMe,
  signup as apiSignup,
  TOKEN_STORAGE_KEY,
  type SignupInput,
  type User,
} from "@/lib/api";

type AuthContextValue = {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (input: SignupInput) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem(TOKEN_STORAGE_KEY);
    let cancelled = false;
    const restoredUser = token ? apiMe(token) : Promise.resolve(null);
    restoredUser
      .then((u) => {
        if (!cancelled) setUser(u);
      })
      .catch(() => {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
        if (!cancelled) setUser(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const persist = useCallback((accessToken: string, nextUser: User) => {
    localStorage.setItem(TOKEN_STORAGE_KEY, accessToken);
    setUser(nextUser);
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await apiLogin(email, password);
      persist(res.access_token, res.user);
    },
    [persist],
  );

  const signup = useCallback(
    async (input: SignupInput) => {
      const res = await apiSignup(input);
      persist(res.access_token, res.user);
    },
    [persist],
  );

  const logout = useCallback(async () => {
    const token = localStorage.getItem(TOKEN_STORAGE_KEY);
    try {
      if (token) await apiLogout(token);
    } catch {
      // Still clear local session if the activity write fails.
    }
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    // Remove the scoped read-only Lab cookie even if backend logout is unavailable.
    await fetch("/attack-lab/session", { method: "DELETE" }).catch(() => undefined);
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({ user, loading, login, signup, logout }),
    [user, loading, login, signup, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
