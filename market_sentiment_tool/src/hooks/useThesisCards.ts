import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import type { ForecastCard } from "@/lib/thesisTracker";

export function useThesisCards() {
  const [cards, setCards] = useState<ForecastCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    fetch(buildApiUrl("/api/thesis/cards"))
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        if (!cancelled) {
          setCards((payload.cards ?? []) as ForecastCard[]);
          setError(null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Unknown thesis tracker error");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { cards, loading, error };
}
