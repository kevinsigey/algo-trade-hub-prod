import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import type { Scoreboard } from "@/lib/thesisTracker";

export function useThesisScoreboard() {
  const [board, setBoard] = useState<Scoreboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    (async () => {
      // The scoreboard route is admin-gated (Claude's #552 blocker):
      // the page only renders for the admin, and its read carries the
      // session token the way useHealth's full report does.
      const token = await (await import("@/components/RequireAdmin")).sessionToken();
      return fetch(buildApiUrl("/api/thesis/scoreboard"),
                   { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    })()
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        if (!cancelled) {
          setBoard((payload.scoreboard ?? null) as Scoreboard | null);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Unknown scoreboard error");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { board, loading, error };
}
