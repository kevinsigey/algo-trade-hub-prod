import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { adminJson } from "@/lib/workshop";
import { DebateFeed } from "@/components/AgentDebates";

/**
 * Agent debates (TradingAgents), its own tab next to the Workshop (Kevin, 2026-11-02).
 * The page explains itself: what the panel is, the fence around it, how its record is
 * graded, and what a run costs -- then lets Kevin start one from here instead of a CLI.
 * Admin only (wrapped in RequireAdmin).
 */
export default function Debates() {
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
    <div className="mx-auto max-w-4xl px-4 py-8 md:px-8">
      <h1 className="text-2xl font-bold tracking-tight text-white">Agent debates</h1>
      <div className="mt-3 space-y-2 text-sm text-slate-400">
        <p>
          TradingAgents is an open-source panel of AI agents that debates <strong className="text-slate-200">one stock at a time</strong>:
          four analysts (technicals, sentiment, news, fundamentals) write reports, a bull and a bear researcher argue over them,
          a trader proposes a plan, and a risk panel rules. The hub runs it on your Gemini key and stores the whole debate.
        </p>
        <p>
          <strong className="text-slate-200">It is not a model.</strong> No debate feeds any score, gate, or order on this site — the
          violet chip on every card says so. It is a second opinion with a memory: every call is graded against the market
          at +5 and +20 trading days, in a record kept separate from every model statistic, and if the graded hit rate ever
          says the panel is a coin flip, a banner here says that too.
        </p>
        <p>
          A debate takes a few minutes (about 20 model calls). The hub caps debates at 10 a day; the Gemini free tier allows
          roughly 20 calls a day in total, shared with the Workshop drafter — so in practice expect about one full debate a
          day unless billing is on. A failed run is shown once with its reason, then cleared.
        </p>
      </div>

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
      </div>

      <DebateFeed refreshKey={refreshKey} />
    </div>
  );
}
