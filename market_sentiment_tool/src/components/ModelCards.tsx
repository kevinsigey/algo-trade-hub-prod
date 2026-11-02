import { useState } from "react";

import { GateBadge } from "@/components/GateBadge";
import type { SeriesEntry } from "@/lib/journal";
import { STATUS_WORDS, skillText } from "@/lib/journalView";
import { STATUS_LABEL, byGroup, edgeText, type LeagueRow, type LeagueStatus } from "@/lib/league";

/**
 * The Model Tracker's first page (Kevin's redesign, 2026-11-01): every predictor as a card --
 * headline edge first, the record behind a click -- instead of a league-table row. The league
 * table itself stays one tab over, unchanged; these cards read the same server-computed rows
 * (`lib/league`) and the same over-time series the Over time tab charts, so the two views can
 * never disagree. Waiting predictors are cards too, muted, saying what they are waiting for.
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
            {p.score.brier !== null && (
              <span>
                Brier {p.score.brier.toFixed(3)}
                {p.score.brier_baseline !== null ? ` vs ${p.score.brier_baseline.toFixed(3)}` : ""}
              </span>
            )}
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

export function ModelCards({ rows, series }: { rows: LeagueRow[]; series: SeriesEntry[] }) {
  const groups = byGroup(rows);
  if (rows.length === 0) {
    return <p className="py-8 text-center text-muted-foreground">No predictors tracked yet.</p>;
  }
  return (
    <div className="space-y-10">
      {groups.map(({ group: g, rows: groupRows }) => {
        if (groupRows.length === 0) return null;
        const sorted = [...groupRows].sort((a, b) => {
          const aw = a.status === "waiting" ? 1 : 0;
          const bw = b.status === "waiting" ? 1 : 0;
          return aw - bw || b.scored - a.scored;
        });
        return (
          <section key={g.id} aria-label={`${g.label} cards`}>
            <h2 className="font-display text-2xl uppercase tracking-wide text-foreground">{g.label}</h2>
            <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {sorted.map((row) => (
                <Card key={row.id} row={row} series={series} />
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
