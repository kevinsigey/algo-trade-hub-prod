import { useEffect, useState } from "react";

import { edgeOf, edgeText, statusOf } from "@/lib/league";
import { getJson } from "@/lib/getJson";
import type { JournalResponse, JournalScore } from "@/lib/journal";
import { loadSportsRecord, type SportsRecordResponse, type SportsRecordSport, type SportsRecordRow } from "@/lib/sportsRecord";

const SPORT_TITLES: Record<string, string> = {
  nfl: "NFL",
  cfb: "College football",
  nba: "NBA",
  pl: "Premier League",
  f1: "F1",
};

const ORDER = ["nfl", "cfb", "nba", "pl", "f1"] as const;

/** What the predictor calls the moment its pre-event subset is frozen. */
const PRE_LABEL: Record<string, string> = {
  nfl: "before kickoff",
  cfb: "before kickoff",
  nba: "before tip-off",
  pl: "before kickoff",
  f1: "before the session",
};

function pct(x: number | null): string {
  if (x === null) return "";
  return `${Math.round(x * 100)}%`;
}

function TooEarly({ n }: { n: number | null }) {
  if (n === null || n >= 100) return null;
  return <span className="ml-2 rounded bg-slate-700 px-1.5 py-0.5 text-[10px] text-slate-300">too early</span>;
}

function Row({ row, vs }: { row: SportsRecordRow; vs: string | null }) {
  const hitNull = row.hit_rate === null;
  return (
    <div className="space-y-1 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="text-slate-200">{row.label}</span>
        <span className="flex items-center gap-2 tabular-nums">
          {hitNull ? (
            <span className="text-slate-400">n {row.n ?? "—"}</span>
          ) : (
            <>
              <span className="text-lg font-semibold text-white">{pct(row.hit_rate)}</span>
              <span aria-hidden className="h-1.5 w-16 overflow-hidden rounded bg-slate-700">
                <span className="block h-full bg-emerald-500" style={{ width: `${(row.hit_rate as number) * 100}%` }} />
              </span>
              <span className="text-slate-400">n {row.n ?? "—"}</span>
            </>
          )}
          <TooEarly n={row.n} />
        </span>
      </div>
      {row.n_pre !== null && (
        <div className="text-xs text-slate-500">
          {PRE_LABEL[row.sport] ?? "before the event"}:{" "}
          {row.hit_rate_pre === null ? `n ${row.n_pre}` : `${pct(row.hit_rate_pre)} of ${row.n_pre}`}
        </div>
      )}
      {row.note && <div className="text-xs text-slate-500">{row.note}</div>}
      {vs && <div className="text-xs text-slate-400">{vs}</div>}
    </div>
  );
}

/** The journal scorecard that grades this row against the Kalshi price on the same contracts, by market. */
const JOURNAL_SUFFIX: Record<string, string> = { moneyline: "", spread: "_spread", total: "_total" };

/** NFL and college football only: the other three have no Kalshi feed yet. Numbers come from the server. */
function vsLine(sport: string, market: string, scores: JournalScore[] | null): string | null {
  // null = the journal is still loading or failed: say nothing rather than claim the market is unscored.
  if (scores === null) return null;
  if (sport !== "nfl" && sport !== "cfb") return null;
  const suffix = JOURNAL_SUFFIX[market];
  if (suffix === undefined) return null;
  const sc = scores.find((x) => x.forecaster === `sports_${sport}${suffix}` && x.baseline === "market" && x.gap != null);
  if (!sc) return "vs Kalshi price: not scored yet";
  // League convention (PR #184): edge is the flipped gap, so positive reads ahead here
  // exactly as it does in the journal league table. "early" (too few scored, or no
  // standard error) keeps the old "No signal" wording rather than claiming a verdict.
  const edge = edgeOf(sc);
  const se = sc.gap_se ?? null;
  const st = statusOf(edge, se, sc.n_settled);
  return `vs Kalshi price: ${edgeText(edge, se)} (${st === "beating" ? "Ahead" : st === "behind" ? "Behind" : "No signal"})`;
}

function Card({ sport, scores }: { sport: SportsRecordSport; scores: JournalScore[] | null }) {
  const title = SPORT_TITLES[sport.sport] ?? sport.sport.toUpperCase();
  const compared = sport.sport === "nfl" || sport.sport === "cfb";
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <h3 className="text-sm font-semibold text-white">{title}</h3>
      {sport.status === "unavailable" ? (
        <p className="mt-2 text-sm text-slate-500">Unavailable right now</p>
      ) : (
        <>
          <div className="mt-3 space-y-3">
            {sport.rows.map((r) => <Row key={r.market} row={r} vs={vsLine(sport.sport, r.market, scores)} />)}
          </div>
          {!compared && <div className="mt-3 text-xs text-slate-400">No market comparison yet</div>}
        </>
      )}
    </div>
  );
}

const FETCH_TIMEOUT_MS = 15000;

export default function SportsRecord() {
  const [data, setData] = useState<SportsRecordResponse | null>(null);
  const [scores, setScores] = useState<JournalScore[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setData(null);
    setError(null);
    setScores(null);
    let cancelled = false;
    let done = false;
    const timer = setTimeout(() => {
      if (!cancelled && !done) {
        done = true;
        setError("Request timed out after 15 seconds");
      }
    }, FETCH_TIMEOUT_MS);
    loadSportsRecord()
      .then((d) => {
        if (cancelled || done) return;
        done = true;
        clearTimeout(timer);
        setData(d);
      })
      .catch((e: Error) => {
        if (cancelled || done) return;
        done = true;
        clearTimeout(timer);
        setError(e.message);
      });
    // Two requests, two states: the journal only adds the Kalshi line, so a slow or failed journal must not
    // hold the five records back.
    const jTimer = setTimeout(() => undefined, FETCH_TIMEOUT_MS);
    getJson<JournalResponse>("/api/journal")
      .then((j) => {
        if (cancelled) return;
        clearTimeout(jTimer);
        setScores(j.forecasters ?? []);
      })
      .catch(() => {
        if (cancelled) return;
        clearTimeout(jTimer);
      }); // stays null: no Kalshi line, never a false "not scored yet"
    return () => {
      cancelled = true;
      clearTimeout(timer);
      clearTimeout(jTimer);
    };
  }, [attempt]);

  if (error) {
    return (
      <section aria-label="Sports predictors" className="space-y-3">
        <h2 className="text-xl font-semibold text-white">Sports predictors</h2>
        <p className="text-sm text-slate-500" title={error}>Sports records unavailable right now</p>
        <button
          type="button"
          onClick={() => setAttempt((n) => n + 1)}
          className="mt-2 rounded-full border border-slate-700 px-3 py-1 text-sm text-slate-300 hover:text-white"
        >
          Retry
        </button>
      </section>
    );
  }
  if (!data) return <div className="text-slate-400">Loading sports…</div>;

  const sports = data.sports ?? [];
  const ordered = ORDER.map((s) => sports.find((x) => x.sport === s)).filter(Boolean) as SportsRecordSport[];

  return (
    <section aria-label="Sports predictors" className="space-y-3">
      <h2 className="text-xl font-semibold text-white">Sports predictors</h2>
      <div className="grid gap-4 md:grid-cols-2">
        {ordered.map((s) => <Card key={s.sport} sport={s} scores={scores} />)}
      </div>
    </section>
  );
}
