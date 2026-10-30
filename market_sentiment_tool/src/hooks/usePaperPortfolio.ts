import { useEffect, useState } from "react";

import { getJson } from "@/lib/getJson";

/** One GET of a portfolio payload. A failed read is an error string, never an empty book. */
export function useApi<T>(path: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getJson<T>(path)
      .then((body) => !cancelled && setData(body))
      .catch((err) => !cancelled && setError(err instanceof Error ? err.message : "Unknown error"));
    return () => {
      cancelled = true;
    };
  }, [path]);

  return { data, error, loading: data === null && error === null };
}
