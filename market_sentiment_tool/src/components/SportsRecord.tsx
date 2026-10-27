import { useEffect, useState } from "react";

import { gapText, verdict } from "@/components/LiveSkill";
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

function pct(x: number | null): string {
  if (x === null) return "";
  return `${Math.round(x * 100)}%`;
}

function TooEarly({ n }: { n: number }) {
  if (n >= 100) return null;
  return <span className="ml-2 rounded bg-slate-700 px-1.5 py-0.5 text-[10px] text-slate-300">too early</span>;
}

function Row({ row }: { row: SportsRecordRow }) {
  const early = row.n < 100;
  const hitNull = row.hit_rate === null;
  return (
    <div className="space-y-1 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="text-slate-200">{row.label}</span>
        <span className="flex items-center gap-2 tabular-nums">
          {hitNull ? (
            <span className="text-slate-400">n {row.n}</span>
          ) : (
            <>
              <span className="text-lg font-semibold text-white">{pct(row.hit_rate)}</span>
              <span className="h-1.5 w-16 overflow-hidden rounded bg-slate-700">
                <span className="block h-full bg-emerald-500" style={{ width: `${(row.hit_rate as number) * 100}%` }} />
              </span>
              <span className="text-slate-400">n {row.n}</span>
            </>
          )}
          <TooEarly n={row.n} />
        </span>
      </div>
      {row.n_pre !== null && (
        <div className="text-xs text-slate-500">
          before kickoff:{" "}
          {row.hit_rate_pre === null ? `n ${row.n_pre}` : `${pct(row.hit_rate_pre)} of ${row.n_pre}`}
        </div>
      )}
      {row.note && <div className="text-xs text-slate-500">{row.note}</div>}
    </div>
  );
}

function kalshiLine(sport: string, scores: JournalScore[] | null): string | null {
  if (sport !== "nfl" && sport !== "cfb") return "No market comparison yet";
  const forecaster = sport === "nfl" ? "sports_nfl" : "sports_cfb";
  const sc = (scores ?? []).find((s) => s.forecaster === forecaster && s.baseline === "market" && s.gap != null);
  if (!sc) return null;
  const g = sc.gap as number;
  const se = sc.gap_se ?? null;
  const v = verdict(g, se);
  const word = v === "ahead" ? "Ahead" : v === "behind" ? "Behind" : "No signal";
  return `vs Kalshi price: ${gapText(g, se)} (${word})`;
}

function Card({ sport, data, scores }: { sport: SportsRecordSport; data: SportsRecordResponse | null; scores: JournalScore[] | null }) {
  const title = SPORT_TITLES[sport.sport] ?? sport.sport.toUpperCase();
  if (sport.status === "unavailable") {
    return (
      <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
        <h3 className="text-sm font-semibold text-white">{title}</h3>
        <p className="mt-2 text-sm text-slate-500">Unavailable right now</p>
      </div>
    );
  }
  const line = kalshiLine(sport.sport, scores);
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <h3 className="text-sm font-semibold text-white">{title}</h3>
      <div className="mt-3 space-y-3">
        {sport.rows.map((r, i) => <Row key={i} row={r} />)}
      </div>
      <div className="mt-3 text-xs text-slate-400">
        {line === null ? null : line === "No market comparison yet" ? "No market comparison yet" : line}
      </div>
    </div>
  );
}

export default function SportsRecord() {
  const [data, setData] = useState<SportsRecordResponse | null>(null);
  const [scores, setScores] = useState<JournalScore[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([
      loadSportsRecord(),
      getJson<JournalResponse>("/api/journal").then((j) => j.forecasters ?? []).catch(() => [] as JournalScore[]),
    ])
      .then(([d, s]) => { setData(d); setScores(s as JournalScore[]); })
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) {
    return (
      <section aria-label="Sports predictors" className="space-y-3">
        <h2 className="text-xl font-semibold text-white">Sports predictors</h2>
        <p className="text-sm text-rose-300/80">{error}</p>
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
        {ordered.map((s) => <Card key={s.sport} sport={s} data={data} scores={scores} />)}
      </div>
    </section>
  );
}
