import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";

declare global {
  interface Window {
    goatcounter?: { count: (vars: { path: string }) => void };
  }
}

/**
 * GoatCounter SPA pageviews (2026-11-01): the count.js snippet in index.html
 * counts the landing view; this counts every later client-side navigation.
 * The first render is skipped so the landing is never double-counted, and
 * the whole thing no-ops wherever count.js is absent (tests, blocked loads).
 */
export function GoatCounterTracker() {
  const location = useLocation();
  const first = useRef(true);

  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    window.goatcounter?.count({ path: location.pathname });
  }, [location.pathname]);

  return null;
}
