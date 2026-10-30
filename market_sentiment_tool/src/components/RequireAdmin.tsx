import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { Lock } from "lucide-react";

import { buildApiUrl } from "@/lib/api";
import { supabase } from "@/lib/supabase";

export type AdminStatus = "checking" | "admin" | "anon";

/** The browser's Supabase session token, or null. Missing auth (tests, no keys) reads as signed out. */
export async function sessionToken(): Promise<string | null> {
  try {
    const { data } = await supabase.auth.getSession();
    return data.session?.access_token ?? null;
  } catch {
    return null;
  }
}

/**
 * Is the signed-in user Kevin? The server decides (`/api/admin/me` checks the JWT against
 * TRADEHUB_ADMIN_EMAIL); a session alone is not enough, and an expired one reads as signed out.
 */
export function useAdminSession(): AdminStatus {
  const [status, setStatus] = useState<AdminStatus>("checking");

  useEffect(() => {
    let cancelled = false;
    const check = async () => {
      const token = await sessionToken();
      if (!token) return !cancelled && setStatus("anon");
      try {
        const r = await fetch(buildApiUrl("/api/admin/me"), { headers: { Authorization: `Bearer ${token}` } });
        if (!cancelled) setStatus(r.ok ? "admin" : "anon");
      } catch {
        if (!cancelled) setStatus("anon");
      }
    };
    check();
    let unsubscribe = () => {};
    try {
      unsubscribe = supabase.auth.onAuthStateChange(() => void check()).data.subscription.unsubscribe;
    } catch {
      // no auth client: the one check above stands
    }
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  return status;
}

/** Operator pages and (step 2) the Workshop. Their URLs stay; a visitor gets the login prompt instead. */
export function RequireAdmin({ children }: { children: React.ReactNode }) {
  const status = useAdminSession();
  const { pathname } = useLocation();
  if (status === "admin") return <>{children}</>;
  if (status === "checking") return <div className="px-8 py-10 text-sm text-slate-400">Checking sign-in…</div>;
  return (
    <div className="mx-auto max-w-md px-4 py-16 text-center">
      <Lock className="mx-auto h-6 w-6 text-slate-400" aria-hidden="true" />
      <h1 className="mt-3 text-xl font-semibold text-white">Admin only</h1>
      <p className="mt-1 text-sm text-slate-400">This page is for the account owner.</p>
      <Link
        to={`/login?next=${encodeURIComponent(pathname)}`}
        className="mt-5 inline-block rounded-lg bg-emerald-500/15 px-4 py-2 text-sm font-medium text-emerald-300 hover:bg-emerald-500/25"
      >
        Sign in
      </Link>
    </div>
  );
}
