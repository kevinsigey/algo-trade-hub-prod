import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { NextRelease } from "@/components/NextRelease";
import { useApi } from "@/hooks/usePaperPortfolio";
import { getJson } from "@/lib/getJson";
import type { JournalResponse, SeriesEntry, SeriesResponse } from "@/lib/journal";
import { beatingCount, edgeText, league } from "@/lib/league";
import { biggestMovers } from "@/lib/overview";
import { viewRows } from "@/lib/journalView";
import { fmtUsd, type PortfolioPayload } from "@/lib/paperPortfolio";
import { adminJson } from "@/lib/workshop";

/**
 * The home page (Kevin's 2026-11-01 redesign: "Overview as home"). Three questions, in order:
 * what is live right now, which models moved, and what happens next. It replaces both the old
 * portfolio-at-/ (the portfolio keeps its own page at /portfolio) and the retired /predictions
 * overview, which duplicated the journal's standings. Every number is the server's, read from
 * the same endpoints the Tracker and Portfolio pages use, so the home page can never disagree
 * with the page it links to.
 */

function Tile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="border border-border bg-card px-4 py-3">
      <div className="font-display text-4xl leading-none tracking-wide text-foreground tabular-nums">{value}</div>
      <div className="mt-1 text-sm text-foreground">{label}</div>
      {sub && <p className="mt-0.5 text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

function LiveBook() {
  const { data, error } = useApi<PortfolioPayload>("/api/portfolio");
  const [staged, setStaged] = useState<number | null>(null);
  useEffect(() => {
    adminJson<{ email: string }>("/api/admin/me")
      .then(() => adminJson<{ orders: unknown[] }>("/api/portfolio/open-orders"))
      .then((r) => setStaged(r.orders.length))
      .catch(() => setStaged(null));
  }, []);
  if (error) return <p className="text-sm text-muted-foreground">Portfolio unavailable right now.</p>;
  if (!data) return <p className="text-sm text-muted-foreground">{error ? "Portfolio unavailable right now." : "Loading the book…"}</p>;
  const s = data.scoreboard;
  if (data.state !== "live" || s.equity === null) {
    return (
      <p className="text-sm text-muted-foreground">
        The paper book is {data.state === "pre_start" ? "not started yet" : data.state.replace("_", " ")}.{" "}
        <Link to="/portfolio" className="font-semibold text-foreground underline">Open the portfolio</Link>
      </p>
    );
  }
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Tile label="account equity" value={fmtUsd(s.equity, { whole: true })} />
      <Tile
        label="return vs SPY"
        value={s.ahead_pts === null ? "—" : `${s.ahead_pts > 0 ? "+" : s.ahead_pts < 0 ? "−" : ""}${Math.abs(s.ahead_pts).toFixed(2)} pts`}
        sub={s.return_pct === null ? undefined : `${s.return_pct > 0 ? "+" : ""}${s.return_pct.toFixed(2)}% all-in`}
      />
      <Tile label="open positions" value={String(data.positions.length)} />
      {staged !== null ? (
        <Tile label="staged orders waiting" value={String(staged)} sub="Signed-in view" />
      ) : (
        <Tile label="open positions value" value={fmtUsd(data.positions.reduce((a, p) => a + Math.abs(p.market_value), 0), { whole: true })} />
      )}
    </div>
  );
}

export default function Overview() {
  const [journal, setJournal] = useState<JournalResponse | null>(null);
  const [series, setSeries] = useState<SeriesEntry[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getJson<JournalResponse>("/api/journal"), getJson<SeriesResponse>("/api/journal/series")])
      .then(([j, s]) => {
        // A stubbed or error body must read as "no board", never crash the home page.
        if (j && Array.isArray(j.forecasters)) setJournal(j);
        setSeries(Array.isArray(s?.series) ? s.series : []);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  const movers = biggestMovers(series);
  const table = journal ? league(viewRows(journal.forecasters)) : [];
  const { beating, measured } = beatingCount(table);
  const h = journal?.headline;

  return (
    <div className="mx-auto max-w-5xl space-y-10 p-4 md:p-8">
      <header>
        <h1 className="font-display text-5xl uppercase tracking-wide text-foreground">Overview</h1>
        <p className="mt-2 max-w-2xl text-muted-foreground">What is live, which models moved, and what happens next.</p>
      </header>

      <section aria-label="What's live" className="space-y-3">
        <h2 className="font-display text-2xl uppercase tracking-wide text-foreground">What&rsquo;s live</h2>
        <LiveBook />
      </section>

      <section aria-label="Biggest movers" className="space-y-3">
        <h2 className="font-display text-2xl uppercase tracking-wide text-foreground">Biggest movers</h2>
        {error ? (
          <p className="text-sm text-muted-foreground">Model record unavailable: {error}</p>
        ) : movers.length === 0 ? (
          <p className="text-sm text-muted-foreground">Not enough settled history yet to rank movers.</p>
        ) : (
          <ul className="space-y-2">
            {movers.map((m) => (
              <li key={m.key} className="flex flex-wrap items-baseline justify-between gap-2 rounded-lg border border-border bg-card px-4 py-3">
                <span className="font-semibold text-foreground">{m.label}</span>
                <span className="text-sm tabular-nums text-muted-foreground">
                  edge {edgeText(m.delta, null)} since {m.since} — {m.delta > 0 ? "improving" : "slipping"}
                </span>
              </li>
            ))}
          </ul>
        )}
        {h && (
          <p className="text-sm text-muted-foreground">
            {h.frozen_calibrated.toLocaleString()} forecasts locked in · {h.settled_calibrated.toLocaleString()} scored ·{" "}
            {measured === 0 ? "none beating their baseline yet" : `${beating} of ${measured} beating their baseline`}.{" "}
            <Link to="/journal" className="font-semibold text-foreground underline">
              Open the Model Tracker
            </Link>
          </p>
        )}
      </section>

      <section aria-label="Coming up" className="space-y-3">
        <h2 className="font-display text-2xl uppercase tracking-wide text-foreground">Coming up</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <NextRelease family="labor" title="Next jobs report" />
          <NextRelease family="oil" title="Next oil settlement" />
        </div>
      </section>
    </div>
  );
}
