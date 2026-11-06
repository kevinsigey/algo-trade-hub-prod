import { useEffect, useState } from "react";

import { Panel } from "@/components/Panel";
import { Chip } from "@/components/Chip";
import { Stat } from "@/components/Stat";
import { buildApiUrl } from "@/lib/api";
import type { SportsEdge, SportsEdgesResponse } from "@/lib/sportsEdges";
import { board, gapText, type SportsPick } from "@/lib/sportsPicks";
import { ctDateTime } from "@/lib/format";

/**
 * /sports: where the NFL and college-football predictors and the Kalshi market disagree, one pick per game.
 *
 * The reviewer decides what is featured, not the size of the gap: a pick is a "top pick" only if the
 * reviewer passed it, and a huge gap (model far from market) is listed under "flagged" with the gap
 * shown, never promoted. When nothing passes, the page says so instead of filling the screen.
 */

const PAGE = 200;
const FETCH_TIMEOUT_MS = 15000;

async function fetchPage(sport: string, offset: number): Promise<{ rows: SportsEdge[]; total: number | null }> {
  const params = new URLSearchParams({ limit: String(PAGE), offset: String(offset) });
  if (sport) params.set("sport", sport);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(buildApiUrl(`/api/sports-edges?${params}`), { signal: controller.signal });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new Error("Request timed out after 15 seconds");
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
  const page = payload as SportsEdgesResponse;
  return { rows: page.edges ?? [], total: typeof page.total === "number" ? page.total : null };
}

/**
 * Every pick. The first page says how many there are, so the rest load side by side (2026-11-06: seven pages
 * one after another took about 8 seconds). Without a total it falls back to reading page after page.
 */
async function fetchAll(sport: string): Promise<SportsEdge[]> {
  const first = await fetchPage(sport, 0);
  const edges = [...first.rows];
  if (first.total != null && first.rows.length > 0) {
    // Step by the page the server actually served: it may cap pages below what was asked.
    const step = first.rows.length;
    const offsets: number[] = [];
    for (let o = step; o < first.total; o += step) offsets.push(o);
    const pages = await Promise.all(offsets.map((o) => fetchPage(sport, o)));
    for (const p of pages) edges.push(...p.rows);
    return edges;
  }
  let last = first.rows.length;
  while (last > 0 && (first.total == null ? last === PAGE : edges.length < first.total)) {
    const next = await fetchPage(sport, edges.length);
    edges.push(...next.rows);
    last = next.rows.length;
  }
  return edges;
}

/** Game starts in the house style (§6): Chicago time, CT suffix. */
const WHEN = { format: (d: Date) => ctDateTime(d.toISOString()) };

const SPORT_SITE = (sport: string) => `https://sports.40-160-91-131.sslip.io/?sport=${sport}`;

/**
 * Predictions tab (phase-3 §4): the board as predictor-style cards -- the
 * model's probability big, a model-vs-market meter, the whole card linking
 * straight to the sport's own site. The grading desk's judgements travel
 * with the card: a flagged pick is featured nowhere and carries its flag
 * when listed; only reviewer-passed picks headline.
 */
function PickCard({ pick }: { pick: SportsPick }) {
  return (
    <a href={SPORT_SITE(pick.sport)} target="_blank" rel="noreferrer"
      className="block rounded-lg border border-slate-800 bg-slate-900/40 p-3 transition hover:border-emerald-500/40">
      <div className="flex items-center justify-between gap-2 text-xs text-slate-400">
        <span className="font-semibold uppercase tracking-wider">{pick.sport} · {WHEN.format(new Date(pick.startUtc))}</span>
        {pick.tier === "flagged" || pick.largeGap ? <Chip tone="bad">Flagged by the reviewer</Chip> : null}
      </div>
      <p className="mt-2 text-sm text-slate-300">{pick.matchup}</p>
      <p className="mt-1 font-semibold text-white">{pick.call}</p>
      <div className="mt-3 flex items-end justify-between">
        <span className="text-3xl font-black tabular-nums text-white">{Math.round(pick.model)}%</span>
        <span className="text-xs tabular-nums text-slate-400">Kalshi {Math.round(pick.market)}% · gap {gapText(pick.gap)} pts</span>
      </div>
      <div className="relative mt-2 h-1.5 rounded bg-slate-800" aria-hidden="true">
        <div className="absolute inset-y-0 rounded bg-emerald-500/70" style={{ left: 0, width: `${Math.min(100, Math.max(0, pick.model))}%` }} />
        <div className="absolute inset-y-[-2px] w-0.5 bg-slate-200" style={{ left: `${Math.min(100, Math.max(0, pick.market))}%` }} />
      </div>
    </a>
  );
}

const ESTATE = [
  { name: "Premier League", href: "https://pl.40-160-91-131.sslip.io", blurb: "Match predictions for every Premier League fixture." },
  { name: "NBA", href: "https://nba.40-160-91-131.sslip.io", blurb: "Game predictions across the NBA slate." },
  { name: "Formula 1", href: "https://f1.40-160-91-131.sslip.io", blurb: "Race predictions for the F1 calendar." },
];

function EstateCards() {
  return (
    <section aria-label="More predictors" className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
      <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">More predictors</span>
      {ESTATE.map((s) => (
        <a key={s.name} href={s.href} target="_blank" rel="noreferrer" title={s.blurb}
          className="font-medium text-emerald-300 hover:text-emerald-200">{s.name} →</a>
      ))}
    </section>
  );
}

function PickRow({ pick }: { pick: SportsPick }) {
  return (
    <li className="grid grid-cols-[1fr_auto] items-center gap-x-4 gap-y-1 border-t border-slate-800 py-3 lg:grid-cols-[1.4fr_1fr_auto]">
      <div>
        <div className="font-medium text-slate-100">{pick.call}</div>
        <div className="text-xs text-slate-500">
          {pick.matchup} · {WHEN.format(new Date(pick.startUtc))}
          {pick.kind !== "winner" && <span> · {pick.kind}</span>}
        </div>
      </div>
      <div className="hidden text-sm tabular-nums text-slate-300 lg:block">
        Model <b className="text-slate-100">{pick.model}%</b> <span className="text-slate-600">·</span> Market{" "}
        <b className="text-slate-100">{pick.market}%</b>
      </div>
      <div className="flex items-center gap-3 justify-self-end">
        <Chip tone={pick.largeGap ? "warn" : "good"} title={pick.largeGap ? "Model and market are unusually far apart" : "Model minus market, in points"}>
          {gapText(pick.gap)} pts
        </Chip>
        <a className="text-xs text-sky-400 hover:underline" href={pick.marketUrl} target="_blank" rel="noreferrer">Kalshi</a>
      </div>
      <div className="text-xs tabular-nums text-slate-400 lg:hidden">
        Model {pick.model}% · Market {pick.market}%
      </div>
    </li>
  );
}

/** A list of picks: the first few lines, all of them one click away (2026-11-06: one screen per page). */
function Section({ title, picks, initial = 6 }: { title: string; picks: SportsPick[]; initial?: number }) {
  if (picks.length === 0) return null;
  const list = (items: SportsPick[]) => <ul>{items.map((p) => <PickRow key={p.key} pick={p} />)}</ul>;
  return (
    <Panel title={`${title} (${picks.length})`} full={picks.length > initial ? list(picks) : undefined}>
      {list(picks.slice(0, initial))}
    </Panel>
  );
}

export default function SportsEdges() {
  const [edges, setEdges] = useState<SportsEdge[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sport, setSport] = useState<"" | "nfl" | "cfb">("");
  const [tab, setTab] = useState<"predictions" | "desk">("predictions");
  // `attempt` exists only so a retry re-runs the effect. `error` is cleared here rather than on the
  // success path, because a failure used to replace the WHOLE page -- including this button -- leaving
  // the visitor with no way forward but a full reload.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setEdges(null);
    setError(null);
    fetchAll(sport).then(setEdges).catch((e: Error) => setError(e.message));
  }, [sport, attempt]);

  if (error) {
    return (
      <div className="p-8 text-red-400">
        Sports picks unavailable: {error}
        <button
          type="button"
          onClick={() => setAttempt((n) => n + 1)}
          className="mt-3 rounded-full border border-slate-700 px-3 py-1 text-sm text-slate-300 hover:text-white"
        >
          Retry
        </button>
      </div>
    );
  }
  if (!edges) return <div className="p-8 text-slate-400">Loading sports picks…</div>;

  const b = board(edges);
  return (
    <div className="mx-auto max-w-6xl space-y-4 px-4 py-5 md:px-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white">Sports picks</h1>
          <p className="mt-1 text-sm text-slate-400">Where our predictors and the market disagree.</p>
        </div>
        <div role="group" aria-label="Sport" className="flex gap-2">
          {([["", "All"], ["nfl", "NFL"], ["cfb", "College"]] as const).map(([value, label]) => (
            <button
              key={value}
              type="button"
              aria-pressed={sport === value}
              onClick={() => setSport(value)}
              className={`rounded-full border px-3 py-1 text-sm ${
                sport === value ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-300" : "border-slate-700 text-slate-400 hover:text-slate-200"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </header>

      <div role="group" aria-label="View" className="flex gap-2">
        {([["predictions", "Predictions"], ["desk", "Grading desk"]] as const).map(([value, label]) => (
          <button key={value} type="button" aria-pressed={tab === value} onClick={() => setTab(value)}
            className={`rounded-full border px-3 py-1 text-sm ${
              tab === value ? "border-emerald-500/50 bg-emerald-500/10 text-emerald-300" : "border-slate-700 text-slate-400 hover:text-slate-200"
            }`}>
            {label}
          </button>
        ))}
      </div>

      {tab === "predictions" ? (
        <>
          {b.topPicks.length === 0 && (
            <p className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3 text-slate-300">
              No pick passed review today — the grading desk shows what the reviewer held back.
            </p>
          )}
          {b.topPicks.length > 0 && (
            <section aria-label="Featured predictions">
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {b.topPicks.map((p) => <PickCard key={p.key} pick={p} />)}
              </div>
            </section>
          )}
          {(b.unreviewed.length > 0 || b.flagged.length > 0) && (() => {
            const more = [...b.unreviewed, ...b.flagged];
            const grid = (items: SportsPick[]) => (
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{items.map((p) => <PickCard key={p.key} pick={p} />)}</div>
            );
            return (
              <Panel title={`More predictions (${more.length})`} full={more.length > 6 ? grid(more) : undefined}>
                {grid(more.slice(0, 6))}
              </Panel>
            );
          })()}
          {sport === "" && <EstateCards />}
        </>
      ) : (
        <>
          <section aria-label="Totals" className="grid gap-2 sm:grid-cols-3">
            <Stat value={b.topPicks.length} label="top picks" />
            <Stat value={b.flagged.length} label="flagged by the reviewer" />
            <Stat value={b.unreviewed.length} label="not reviewed yet" />
          </section>

          {b.topPicks.length === 0 && (
            <p className="rounded-lg border border-slate-800 bg-slate-900/40 px-4 py-3 text-slate-300">No pick passed review today.</p>
          )}

          <div className="grid gap-2 lg:grid-cols-3">
            <Section title="Top picks" picks={b.topPicks} />
            <Section title="Flagged by the reviewer" picks={b.flagged} />
            <Section title="Not reviewed yet" picks={b.unreviewed} />
          </div>

          {b.noEdge > 0 && <p className="text-sm text-slate-500">{b.noEdge} more games had no usable edge.</p>}
        </>
      )}
    </div>
  );
}
