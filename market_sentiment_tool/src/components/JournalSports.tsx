import { useEffect, useState } from "react";

import { SPORT_TITLES, vsLine } from "@/components/SportsRecord";
import type { JournalScore } from "@/lib/journal";
import {
  loadSportsRecord,
  type SportsRecordResponse,
  type SportsRecordRow,
  type SportsRecordSport,
} from "@/lib/sportsRecord";

/**
 * The sports predictors on the Journal (Kevin's ask, 2026-11-01): every
 * predictor site's own published record, grouped by sport, one card each --
 * the headline market (moneyline, else the deepest record) up front and the
 * rest under "All markets", so the whole estate reads in one screenful
 * instead of a scroll. The same /api/sports-record payload the Models page
 * shows in full; nothing here computes a score.
 */

const ORDER = ["nfl", "cfb", "nba", "pl", "f1"] as const;

function pct(x: number | null): string {
  return x === null ? "—" : `${Math.round(x * 100)}%`;
}

function headlineRow(rows: SportsRecordRow[]): SportsRecordRow {
  return (
    rows.find((r) => r.market === "moneyline") ??
    rows.reduce((a, b) => ((b.n ?? -1) > (a.n ?? -1) ? b : a), rows[0])
  );
}

function CompactRow({ row, vs }: { row: SportsRecordRow; vs: string | null }) {
  return (
    <div className="flex items-baseline justify-between gap-2 text-sm">
      <span className="text-muted-foreground">{row.label}</span>
      <span className="tabular-nums text-foreground">
        {pct(row.hit_rate)} <span className="text-xs text-muted-foreground">n {row.n ?? "—"}</span>
        {vs ? <span className="ml-2 text-xs text-muted-foreground">{vs}</span> : null}
      </span>
    </div>
  );
}

function SportCard({ sport, scores }: { sport: SportsRecordSport; scores: JournalScore[] | null }) {
  const title = SPORT_TITLES[sport.sport] ?? sport.sport.toUpperCase();
  const rows = Array.isArray(sport.rows) ? sport.rows : [];
  if (sport.status === "unavailable" || rows.length === 0) {
    return (
      <div className="border border-border bg-card p-4">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <p className="mt-2 text-sm text-muted-foreground">Unavailable right now</p>
      </div>
    );
  }
  const head = headlineRow(rows);
  const rest = rows.filter((r) => r !== head);
  const headVs = vsLine(sport.sport, head.market, scores);
  const compared = sport.sport === "nfl" || sport.sport === "cfb";
  return (
    <div className="border border-border bg-card p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        <span className="text-xs text-muted-foreground">{head.label}</span>
      </div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="font-display text-4xl leading-none text-foreground tabular-nums">{pct(head.hit_rate)}</span>
        <span className="text-sm text-muted-foreground tabular-nums">hit rate · n {head.n ?? "—"}</span>
      </div>
      {head.n_pre !== null && (
        <p className="mt-1 text-xs text-muted-foreground tabular-nums">
          Before the event: {head.hit_rate_pre === null ? `n ${head.n_pre}` : `${pct(head.hit_rate_pre)} of ${head.n_pre}`}
        </p>
      )}
      {headVs ? (
        <p className="mt-1 text-xs text-muted-foreground">{headVs}</p>
      ) : !compared ? (
        <p className="mt-1 text-xs text-muted-foreground">No market comparison yet</p>
      ) : null}
      {head.note && <p className="mt-1 text-xs text-muted-foreground">{head.note}</p>}
      {rest.length > 0 && (
        <details className="mt-3 border-t border-border pt-2">
          <summary className="cursor-pointer text-xs text-muted-foreground">
            All markets ({rows.length})
          </summary>
          <div className="mt-2 space-y-1.5">
            {rest.map((r) => (
              <CompactRow key={r.market} row={r} vs={vsLine(sport.sport, r.market, scores)} />
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

export default function JournalSports({ scores }: { scores: JournalScore[] | null }) {
  const [data, setData] = useState<SportsRecordResponse | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadSportsRecord()
      .then((d) => {
        // Shape-guard like the weather map: a payload without the sports
        // array is a failed read, never a render crash.
        if (!Array.isArray(d?.sports)) throw new Error("sports payload has no sports");
        if (!cancelled) setData(d);
      })
      .catch(() => { if (!cancelled) setFailed(true); });
    return () => { cancelled = true; };
  }, []);

  if (failed) {
    return <p className="py-8 text-center text-muted-foreground">The sports records are unavailable right now — the league table above still reports.</p>;
  }
  if (!data) return <p className="py-8 text-center text-muted-foreground">Loading sports records…</p>;
  const bySport = new Map(data.sports.map((s) => [s.sport, s]));
  return (
    <section aria-label="Sports predictors">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {ORDER.map((key) => {
          const sport = bySport.get(key);
          return sport ? <SportCard key={key} sport={sport} scores={scores} /> : null;
        })}
      </div>
      <p className="mt-3 text-xs text-muted-foreground">
        Each site's own locked-in record, as of {new Date(data.as_of).toLocaleDateString("en-US")}. The full
        per-market tables live on the Models page.
      </p>
    </section>
  );
}
