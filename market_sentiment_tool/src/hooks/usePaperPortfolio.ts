import { useEffect, useRef, useState } from "react";

import { getJson } from "@/lib/getJson";

/** One GET of a portfolio payload. A failed read is an error string, never an empty book.
 *
 * With `refreshMs` set, the read repeats on that cycle while the browser tab
 * is visible (a hidden tab skips its turns rather than polling in the
 * background). A failed refresh keeps the last good data and marks it
 * `stale` instead of blanking the page; `lastUpdatedAt` says when the data
 * on screen actually landed. */
export function useApi<T>(path: string, refreshMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null);
  const [stale, setStale] = useState(false);
  const hasData = useRef(false);

  useEffect(() => {
    let cancelled = false;
    hasData.current = false;
    setData(null);
    setError(null);
    setLastUpdatedAt(null);
    setStale(false);
    const load = () => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      getJson<T>(path)
        .then((body) => {
          if (cancelled) return;
          hasData.current = true;
          setData(body);
          setError(null);
          setStale(false);
          setLastUpdatedAt(Date.now());
        })
        .catch((err) => {
          if (cancelled) return;
          if (hasData.current) {
            setStale(true);
          } else {
            setError(err instanceof Error ? err.message : "Unknown error");
          }
        });
    };
    load();
    if (!refreshMs) return () => { cancelled = true; };
    const timer = setInterval(load, refreshMs);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [path, refreshMs]);

  return { data, error, loading: data === null && error === null, lastUpdatedAt, stale };
}
