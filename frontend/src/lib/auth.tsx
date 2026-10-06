"use client";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, tokenStore } from "./api";
import type { User } from "./types";
import { safeNext } from "./utils";

interface AuthCtx {
  user: User | null;
  loading: boolean;
  signIn: (email: string, password: string) => Promise<void>;
  signUp: (name: string, email: string, password: string, role: "buyer" | "supplier") => Promise<void>;
  signOut: () => void;
  refresh: () => Promise<void>;
}
const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  const refresh = useCallback(async () => {
    if (!tokenStore.get()) {
      setUser(null);
      return;
    }
    try {
      setUser(await api<User>("/api/auth/me"));
    } catch {
      tokenStore.clear();
      setUser(null);
    }
  }, []);

  useEffect(() => {
    refresh().finally(() => setLoading(false));
  }, [refresh]);

  const finish = (res: { access_token: string; user: User }) => {
    tokenStore.set(res.access_token);
    setUser(res.user);
    // a scanned QR code sends people to /login?next=/units/CODE: bring them back to it after signing in
    router.push(safeNext(new URLSearchParams(window.location.search).get("next")));
  };

  const value: AuthCtx = {
    user,
    loading,
    refresh,
    signIn: async (email, password) => finish(await api("/api/auth/login", { body: { email, password } })),
    signUp: async (name, email, password, role) => finish(await api("/api/auth/register", { body: { name, email, password, role } })),
    signOut: () => {
      tokenStore.clear();
      setUser(null);
      router.push("/login");
    },
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}
