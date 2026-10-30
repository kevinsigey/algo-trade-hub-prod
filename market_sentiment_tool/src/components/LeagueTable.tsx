import { Fragment, useState } from "react";

import { JournalDetail } from "@/components/JournalDetail";
import { EARLY_N, type ViewRow } from "@/lib/journalView";
import { axisSpan, byGroup, edgeText, NOT_YET, STATUS_LABEL, Z95, type LeagueRow, type LeagueStatus } from "@/lib/league";
import { tileNote } from "@/lib/forecasterLabels";

/**
 * The journal's core: one row per predictor, grouped, each scored against the market or baseline it
 * is measured against. Positive edge always means "beats it". Nothing is computed here: edge, interval
 * and status come from `lib/league.ts`, which only changes the sign of the server's gap.
 */

const TONE: Record<LeagueStatus, string> = {
  beating: "text-pr-win",
  behind: "text-pr-loss",
  level: "text-foreground",
  early: "text-muted-foreground",
  waiting: "text-muted-foreground",
};
const DOT: Record<LeagueStatus, string> = {
  beating: "var(--pr-win)",
  behind: "var(--pr-loss)",
  level: "var(--pr-faint)",
  early: "var(--pr-faint)",
  waiting: "var(--pr-faint)",
};

function statusWord(row: LeagueRow): string {
  const text = STATUS_LABEL[row.status];
  return row.primary.baseline === "market" ? text.replace("baseline", "market") : text;
}

function Forest({ row, span }: { row: LeagueRow; span: number }) {
  if (row.scored === 0) return <span className="text-xs text-muted-foreground">no results yet</span>;
  if (row.edge === null) return <span className="text-xs text-muted-foreground">not measured</span>;
  const pos = (v: number) => `${((v + span) / (2 * span)) * 100}%`;
  const half = row.se === null ? 0 : Z95 * row.se;
  const hollow = row.scored < EARLY_N;
  const color = DOT[row.status];
  return (
    <div className="relative h-5 w-full min-w-[9rem]" role="img" aria-label={`Edge ${edgeText(row.edge, row.se)}`}>
      <div className="absolute inset-y-0 w-px bg-border" style={{ left: "50%" }} />
      {half > 0 && (
        <div className="absolute top-1/2 h-0.5 -translate-y-1/2" style={{ left: pos(row.edge - half), width: `${(half / span) * 100}%`, background: color, opacity: 0.6 }} />
      )}
      <div
        data-testid="dot"
        data-hollow={hollow}
        className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full"
        style={{ left: pos(row.edge), background: hollow ? "transparent" : color, border: `2px solid ${color}` }}
      />
    </div>
  );
}

function Progress({ scored, needed }: { scored: number; needed: number }) {
  return (
    <div aria-hidden className="mt-1 h-1 w-full max-w-[6rem] bg-border">
      <div className="h-full bg-muted-foreground" style={{ width: `${Math.min(scored / needed, 1) * 100}%` }} />
    </div>
  );
}

export function LeagueTable({ rows }: { rows: LeagueRow[] }) {
  const [open, setOpen] = useState<string | null>(null);
  const [more, setMore] = useState<string | null>(null);
  const span = axisSpan(rows);
  const groups = byGroup(rows);

  return (
    <div className="space-y-8">
      <p className="text-sm text-muted-foreground">
        Edge is how many Brier points a predictor is ahead of what it is measured against. <b className="font-semibold text-foreground">Right of zero beats it.</b> Bars are 95% intervals; a hollow dot means under {EARLY_N} scored.
      </p>
      {groups.map(({ group, rows: gRows }) => (
        <section key={group.id} aria-label={group.label}>
          <h2 className="font-display text-2xl uppercase tracking-wide text-foreground">{group.label}</h2>
          <p className="mb-2 text-sm text-muted-foreground">{group.blurb}</p>
          <div className="overflow-x-auto border border-border bg-card">
            <table className="w-full min-w-[34rem] text-sm">
              <thead className="text-xs uppercase tracking-wider text-muted-foreground">
                <tr>
                  <th className="sticky left-0 z-10 bg-card py-2 pl-3 pr-2 text-left font-normal">Predictor</th>
                  <th className="px-2 py-2 text-right font-normal">Scored</th>
                  <th className="px-3 py-2 text-left font-normal">
                    <span className="flex justify-between"><span>{(-span).toFixed(2)} behind</span><span>ahead {span.toFixed(2)}</span></span>
                  </th>
                  <th className="px-2 py-2 pr-3 text-left font-normal">Status</th>
                </tr>
              </thead>
              <tbody>
                {gRows.map((r) => (
                  <Fragment key={r.id}>
                    <tr className="border-t border-border align-top">
                      <td className="sticky left-0 z-10 bg-card py-3 pl-3 pr-2">
                        <button type="button" aria-expanded={open === r.id} onClick={() => setOpen(open === r.id ? null : r.id)} className="text-left font-semibold text-foreground hover:underline">
                          {r.label}
                        </button>
                        {r.promoted && <span className="ml-2 border border-border px-1.5 py-0.5 text-xs uppercase tracking-wide text-foreground">Promoted</span>}
                        {r.primary.experimental && <span className="ml-2 text-xs text-muted-foreground">Experimental</span>}
                        <div className="text-xs text-muted-foreground">vs {r.against}</div>
                        {tileNote(r.primary.forecaster) && <div className="text-xs text-muted-foreground" data-tile-note="">{tileNote(r.primary.forecaster)}</div>}
                        {r.variants.length > 0 && (
                          <button type="button" onClick={() => setMore(more === r.id ? null : r.id)} aria-expanded={more === r.id} className="mt-0.5 text-xs text-muted-foreground underline">
                            {more === r.id ? "Hide" : "Show"} {r.variants.length} other {r.variants.length === 1 ? "variant" : "variants"}
                          </button>
                        )}
                      </td>
                      <td className="px-2 py-3 text-right tabular-nums">
                        <div className="text-foreground">{r.scored}</div>
                        <div className="text-xs text-muted-foreground">of {r.needed}</div>
                        <Progress scored={r.scored} needed={r.needed} />
                      </td>
                      <td className="px-3 py-3">
                        <Forest row={r} span={span} />
                        {r.scored > 0 && <div className="mt-0.5 text-xs tabular-nums text-muted-foreground">{edgeText(r.edge, r.se)}</div>}
                      </td>
                      <td className={`px-2 py-3 pr-3 font-semibold ${TONE[r.status]}`}>{statusWord(r)}</td>
                    </tr>
                    {more === r.id && r.variants.map((v: ViewRow) => (
                      <tr key={v.key} className="border-t border-border/60 bg-background/40 text-xs text-muted-foreground">
                        <td className="sticky left-0 z-10 bg-card py-2 pl-6 pr-2">{v.label}</td>
                        <td className="px-2 py-2 text-right tabular-nums">{v.scored}</td>
                        <td className="px-3 py-2 tabular-nums">{v.score.gap == null ? "not measured" : edgeText(-v.score.gap, v.score.gap_se ?? null)}</td>
                        <td className="px-2 py-2 pr-3">{v.score.gate_status === "PROMOTED" ? "Promoted" : "Shadow"}</td>
                      </tr>
                    ))}
                    {open === r.id && (
                      <tr><td colSpan={4} className="border-t border-border/60 p-2"><JournalDetail row={r.primary} /></td></tr>
                    )}
                  </Fragment>
                ))}
                {NOT_YET.filter((n) => n.group === group.id).map((n) => (
                  <tr key={n.label} className="border-t border-border text-muted-foreground">
                    <td className="sticky left-0 z-10 bg-card py-3 pl-3 pr-2 font-semibold">{n.label}</td>
                    <td className="px-2 py-3 text-right">-</td>
                    <td className="px-3 py-3 text-xs">Its own site shows its record. Not scored here yet.</td>
                    <td className="px-2 py-3 pr-3">Not tracked here</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}
