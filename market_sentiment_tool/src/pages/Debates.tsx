import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { adminJson } from "@/lib/workshop";
import { DebateFeed } from "@/components/AgentDebates";
import ValuationDebates from "@/components/ValuationDebates";

/**
 * Agent debates (TradingAgents) -- a section of the Guidance page since
 * step 14 folded the standalone page in (it began as its own tab next to
 * the Workshop, Kevin, 2026-11-02). One intro sentence carries the fence;
 * the run form, the feed and the valuation-debate panel follow.
 * Admin only (the Guidance route is wrapped in RequireAdmin).
 */
export function DebatesSection() {
  const [ticker, setTicker] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [lastTicker, setLastTicker] = useState("");
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const polls = useRef(0);

  // While a debate runs, refresh the feed every 20s (a run takes minutes); give up
  // after ~10 minutes -- the stored record, success or failure, stays either way.
  useEffect(() => {
    if (!running) return;
    polls.current = 0;
    const t = setInterval(() => {
      polls.current += 1;
      setRefreshKey((k) => k + 1);
      if (polls.current >= 30) {
        setRunning(null);
        clearInterval(t);
      }
    }, 20_000);
    return () => clearInterval(t);
  }, [running]);

  const start = async (force = false) => {
    const t = force ? lastTicker : ticker.trim().toUpperCase();
    if (!t) return;
    setError(null);
    try {
      const res = await adminJson<{ started?: string; reused?: string; age_hours?: number }>(
        "/api/agent-debates/run",
        { method: "POST", body: JSON.stringify({ ticker: t, force }) },
      );
      if (res.reused) {
        // Inside the reuse window the existing debate stands (Kevin,
        // 2026-11-03: replaced, not duplicated) -- say so, and offer the
        // explicit fresh run instead of silently spending a panel.
        setNotice(`${t} was debated ${res.age_hours}h ago — showing that debate instead of spending another run.`);
        setLastTicker(t);
        setRefreshKey((k) => k + 1);
        return;
      }
      setNotice(null);
      setRunning(t);
      setTicker("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "The debate could not be started");
    }
  };

  return (
    <section aria-label="Agent debates" className="mt-12 border-t border-slate-800 pt-8">
      <h2 className="text-lg font-semibold text-white">Agent debates</h2>
      <p className="mt-1 max-w-3xl text-sm text-slate-400">
        TradingAgents, an open-source panel of AI agents, debates <strong className="text-slate-200">one stock at a time</strong> — and <strong className="text-slate-200">it is not a model</strong>: no debate feeds any score, gate, or order on this site, and every call is graded against the market at +5 and +20 trading days in a record kept separate from every model statistic.
      </p>

      <div className="mt-8">
        <label htmlFor="ticker" className="block text-sm font-medium text-slate-300">
          Run a debate on a ticker
        </label>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            id="ticker"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && start()}
            placeholder="NVDA"
            maxLength={12}
            className="w-36 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 uppercase text-white placeholder:text-slate-500 focus:border-violet-400 focus:outline-none"
          />
          <button
            type="button"
            onClick={() => start()}
            disabled={!ticker.trim() || running !== null}
            className="inline-flex items-center gap-2 rounded-lg bg-violet-500 px-4 py-2 font-medium text-violet-950 hover:bg-violet-400 disabled:opacity-50"
          >
            {running && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Start the debate
          </button>
        </div>
        {running && (
          <p className="mt-2 text-sm text-slate-300">
            Debating {running} — the panel takes a few minutes. You can leave this page; the result lands in the record below either way.
          </p>
        )}
        {notice && (
          <p className="mt-2 text-sm text-slate-300">
            {notice}{" "}
            <button type="button" onClick={() => start(true)}
                    className="font-semibold text-violet-300 underline underline-offset-2">
              Run a fresh debate anyway
            </button>
          </p>
        )}
        {error && <p role="alert" className="mt-2 text-sm text-rose-300">{error}</p>}
        <p className="mt-2 text-xs text-slate-500">
          A debate takes a few minutes (about 20 model calls); the hub caps debates at 10 a day, and the Gemini free tier's roughly 20 calls a day are shared with the Workshop drafter — so in practice expect about one full debate a day unless billing is on.
        </p>
      </div>

      <DebateFeed refreshKey={refreshKey} />

      <div className="mt-12 space-y-2 text-sm text-slate-400">
        <p>
          A second panel debates only <strong className="text-slate-200">the guidance file</strong> — the fact sheet behind the bands above is Exhibit A, fixed for every side — and every verdict is graded at +20 and +60 trading days against both the plain band rule and the proposer's own pick; it is display-only until roughly 40 graded verdicts pass that bar.
        </p>
      </div>

      <ValuationDebates />
    </section>
  );
}
