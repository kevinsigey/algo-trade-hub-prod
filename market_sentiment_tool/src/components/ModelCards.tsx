import { useState } from "react";
import { ChevronDown } from "lucide-react";

import { GateBadge } from "@/components/GateBadge";
import { matchedBrier, type SeriesEntry } from "@/lib/journal";
import { STATUS_WORDS, skillText } from "@/lib/journalView";
import { STATUS_LABEL, byGroup, edgeText, type LeagueRow, type LeagueStatus } from "@/lib/league";

/**
 * The Model Tracker's first page (Kevin's redesign, 2026-11-01): every predictor as a card --
 * headline edge first, the record behind a click -- instead of a league-table row. The league
 * table itself stays one tab over, unchanged; these cards read the same server-computed rows
 * (`lib/league`) and the same over-time series the Over time tab charts, so the two views can
 * never disagree. Waiting predictors are cards too, muted, saying what they are waiting for.
 * Since 2026-11-02 the cards sit under their group headers, closed: the header carries the
 * group's quick summary (behind of measured, beating, best edge, scored), so the tab reads
 * as three standings until a group is opened.
 */

const STATUS_TONE: Record<LeagueStatus, string> = {
  beating: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  level: "border-slate-500/40 bg-slate-500/10 text-slate-300",
  behind: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  early: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  waiting: "border-slate-600/60 bg-slate-700/20 text-slate-400",
};

const AHEAD = "#3ddc84";
const BEHIND = "#ff6b6b";
const FLAT = "#909aa8";

/** Edge sparkline from the over-time series: the server's gap flipped to edge (positive beats it). */
function Sparkline({ entry }: { entry: SeriesEntry | undefined }) {
  const pts = (entry?.points ?? [])
    .filter((p) => p.gap !== null)
    .slice(-40)
    .map((p) => -(p.gap as number));
  if (pts.length < 2) return null;
  const min = Math.min(0, ...pts);
  const max = Math.max(0, ...pts);
  const span = max - min || 1;
  const x = (i: number) => (i / (pts.length - 1)) * 100;
  const y = (v: number) => 26 - ((v - min) / span) * 24;
  const last = pts[pts.length - 1];
  const color = last > 0 ? AHEAD : last < 0 ? BEHIND : FLAT;
  return (
    <svg viewBox="0 0 100 28" className="h-7 w-full" role="img" aria-label={`Edge trend, latest ${edgeText(last, null)}`}>
      <line x1="0" x2="100" y1={y(0)} y2={y(0)} stroke="#475569" strokeDasharray="2 2" strokeWidth="0.5" />
      <polyline
        fill="none"
        stroke={color}
        strokeWidth="1.4"
        points={pts.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ")}
      />
    </svg>
  );
}

function fmtCents(cents: number): string {
  const dollars = cents / 100;
  return `${dollars < 0 ? "−" : ""}$${Math.abs(dollars).toFixed(2)}`;
}

function Card({ row, series }: { row: LeagueRow; series: SeriesEntry[] }) {
  const [open, setOpen] = useState(false);
  const p = row.primary;
  const entry = series.find((s) => `${s.forecaster}@${s.version}` === p.key);
  const waiting = row.status === "waiting";
  return (
    <article className={`flex flex-col gap-3 border bg-card p-4 ${waiting ? "border-dashed border-border/70" : "border-border"}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h3 className="truncate font-semibold text-foreground">{row.label}</h3>
          {p.experimental && <div className="text-xs text-muted-foreground">Experimental</div>}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          <GateBadge edge={{ gate_status: p.score.gate_status }} />
          <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${STATUS_TONE[row.status]}`}>
            {STATUS_LABEL[row.status]}
          </span>
        </div>
      </div>

      {waiting ? (
        <p className="text-sm text-muted-foreground">
          {p.frozen > 0
            ? `${p.frozen.toLocaleString()} forecasts locked in. Scoring starts with the first settlement.`
            : "No forecasts locked in yet. This card fills in when the first one freezes."}
        </p>
      ) : (
        <>
          <div>
            <div className="font-display text-4xl leading-none tracking-wide text-foreground tabular-nums">
              {row.edge === null ? "—" : edgeText(row.edge, null)}
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              edge vs {row.against}
              {row.se !== null && row.edge !== null ? ` (${edgeText(row.edge, row.se)})` : ""}
            </div>
          </div>
          <Sparkline entry={entry} />
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-muted-foreground">
            <span>
              Scored {row.scored.toLocaleString()} / {row.needed.toLocaleString()} needed
            </span>
            {(() => {
              const matched = matchedBrier(p.score);
              if (matched) {
                return (
                  <span>
                    Brier {matched.ours.toFixed(3)} vs {matched.baseline.toFixed(3)}
                    {matched.n != null ? ` on ${matched.n.toLocaleString()} matched contracts` : ""}
                  </span>
                );
              }
              return p.score.brier !== null ? <span>Brier {p.score.brier.toFixed(3)}, no baseline to compare</span> : null;
            })()}
          </div>
        </>
      )}

      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="mt-auto self-start text-xs font-semibold text-muted-foreground hover:text-foreground"
      >
        {open ? "Hide details" : "Details"}
      </button>
      {open && (
        <div className="space-y-3 border-t border-border pt-3 text-sm">
          {row.variants.length > 0 && (
            <ul className="space-y-1">
              {row.variants.map((v) => (
                <li key={v.key} className="flex flex-wrap items-baseline justify-between gap-2 text-xs">
                  <span className="text-foreground">{v.label}</span>
                  <span className="tabular-nums text-muted-foreground">
                    {STATUS_WORDS[v.status]} · scored {v.scored.toLocaleString()} · skill {skillText(v.skill)}
                  </span>
                </li>
              ))}
            </ul>
          )}
          {p.score.costs?.net_pnl_cents !== undefined && (
            <p className="text-xs text-muted-foreground">
              Simulated taker P&amp;L after fees:{" "}
              <span className="tabular-nums text-foreground">{fmtCents(p.score.costs.net_pnl_cents)}</span>
            </p>
          )}
          {p.score.gate_reasons.length > 0 && (
            <div>
              <div className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Gate</div>
              <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-muted-foreground">
                {p.score.gate_reasons.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-xs text-muted-foreground">Scores updated {new Date(p.score.computed_at).toLocaleString()}</p>
        </div>
      )}
    </article>
  );
}

/**
 * The group header's quick summary (Kevin, 2026-11-02): how the group stands
 * without opening it -- behind of measured first (his words), then beating and
 * level, the unmeasured tail, the best edge in the group, and the total scored.
 */
function groupSummary(rows: LeagueRow[]): string {
  const count = (s: LeagueStatus) => rows.filter((r) => r.status === s).length;
  const measured = count("beating") + count("level") + count("behind");
  const parts = [`${count("behind")} behind of ${measured} measured`, `${count("beating")} beating`];
  if (count("level") > 0) parts.push(`${count("level")} level`);
  if (count("early") > 0) parts.push(`${count("early")} too early`);
  if (count("waiting") > 0) parts.push(`${count("waiting")} waiting`);
  const best = rows.filter((r) => r.edge !== null).sort((a, b) => (b.edge ?? 0) - (a.edge ?? 0))[0];
  if (best) parts.push(`best edge ${edgeText(best.edge, null)} (${best.label})`);
  const scored = rows.reduce((n, r) => n + r.scored, 0);
  if (scored > 0) parts.push(`${scored.toLocaleString()} scored`);
  return parts.join(" · ");
}

function GroupSection({ label, blurb, rows, series }: { label: string; blurb: string; rows: LeagueRow[]; series: SeriesEntry[] }) {
  // Closed by default (Kevin, 2026-11-02): the Tracker leads with the group
  // standings; the cards are one press away, not a scroll away.
  const [open, setOpen] = useState(false);
  const sorted = [...rows].sort((a, b) => {
    const aw = a.status === "waiting" ? 1 : 0;
    const bw = b.status === "waiting" ? 1 : 0;
    return aw - bw || b.scored - a.scored;
  });
  return (
    <section aria-label={`${label} cards`} className="border border-border bg-card/40">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-left hover:bg-card"
      >
        <span className="font-display text-2xl uppercase tracking-wide text-foreground">{label}</span>
        <span className="text-xs tabular-nums text-muted-foreground">
          {rows.length} models · {groupSummary(rows)}
        </span>
        <ChevronDown className={`ml-auto h-5 w-5 shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      <p className="px-4 pb-3 text-xs text-muted-foreground">{blurb}</p>
      {open && (
        <div className="grid gap-4 px-4 pb-4 sm:grid-cols-2 lg:grid-cols-3">
          {sorted.map((row) => (
            <Card key={row.id} row={row} series={series} />
          ))}
        </div>
      )}
    </section>
  );
}

export function ModelCards({ rows, series }: { rows: LeagueRow[]; series: SeriesEntry[] }) {
  const groups = byGroup(rows);
  if (rows.length === 0) {
    return <p className="py-8 text-center text-muted-foreground">No predictors tracked yet.</p>;
  }
  return (
    <div className="space-y-4">
      {groups.map(({ group: g, rows: groupRows }) =>
        groupRows.length === 0 ? null : (
          <GroupSection key={g.id} label={g.label} blurb={g.blurb} rows={groupRows} series={series} />
        ),
      )}
    </div>
  );
}
