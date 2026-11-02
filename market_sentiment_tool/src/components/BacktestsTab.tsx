import { Fragment, useEffect, useState } from "react";

import { Chip, type Tone } from "@/components/Chip";
import { GateBadge } from "@/components/GateBadge";
import { SettledBars } from "@/components/SettledBars";
import { Stat } from "@/components/Stat";
import SportsRecord from "@/components/SportsRecord";
import { buildApiUrl } from "@/lib/api";
import {
  brierPair,
  claimText,
  displayOnlyNote,
  retirementText,
  type CatalogueEntry,
  type EngineStatus,
  type ModelsResponse,
} from "@/lib/models";
import {
  backtestGateLabel,
  brierVerdict,
  diagnosticFlags,
  formatBrier,
  formatCount,
  formatSimulatedMoney,
  summarise,
  type ScoreboardRow,
} from "@/lib/scoreboard";

/**
 * The backtest record, merged into the Model Tracker (Kevin's call, 2026-11-02):
 * the Engine Scoreboard and the Models catalogue were two tabs presenting one
 * dataset (both read /api/scoreboard) next to a third tab presenting the forward
 * record, and the overlap confused more than it informed. One tab now holds the
 * whole backtest side: the scoreboard's summary and headline cards first (the
 * verdicts), then the catalogue of every engine -- measured, unmeasured and
 * retired -- then the sports record. The forward record stays the Tracker's
 * other tabs. Both source pages' honesty rules ride along unchanged: every
 * engine renders, in order, with no filter or sort; the headline never renders
 * without the counts that qualify it; the two gates are never merged.
 */

const SUMMARY_TONES = {
  behind: "border-amber-900/60 bg-amber-950/20 text-amber-100",
  ahead: "border-emerald-900/60 bg-emerald-950/20 text-emerald-100",
  unknown: "border-slate-800 bg-slate-900/40 text-slate-300",
} as const;

/**
 * One engine as a headline card (Kevin's redesign, 2026-11-02): the verdict, both
 * Briers, the simulated result and the promotion badge are always on the card --
 * nothing about an engine's standing is ever behind the click. The click opens the
 * backtest detail: the settled bars and both gates in full. Every engine the API
 * returns gets a card, in the API's order; there is still no filter, no sort, and
 * no summary that names only the best engine.
 */
function EngineCard({ row }: { row: ScoreboardRow }) {
  const [open, setOpen] = useState(false);
  return (
    <article className="rounded-2xl border border-slate-800 bg-slate-900/40 p-4">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="block w-full text-left"
      >
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-base font-semibold text-slate-50">{row.engine}</h3>
          <span className="text-xs text-slate-500">
            {row.mode}
            {row.engine_version ? ` · ${row.engine_version}` : ""}
            {row.date_from && row.date_to ? ` · ${row.date_from.slice(0, 10)} → ${row.date_to.slice(0, 10)}` : ""}
          </span>
        </div>
        <div className="mt-2 flex flex-wrap items-baseline gap-x-6 gap-y-1">
          <span className="font-mono text-lg text-slate-100">
            {formatBrier(row.brier_ours)}
            <span className="ml-1 text-xs text-slate-500">ours</span>
          </span>
          <span className="font-mono text-lg text-slate-400">
            {formatBrier(row.brier_market)}
            <span className="ml-1 text-xs text-slate-500">market</span>
          </span>
          <span className="text-sm text-slate-200">{brierVerdict(row)}</span>
          {/* Labelled as simulated: this product places no orders, so a currency figure with no such
              label would read as money available to someone. */}
          <span className="font-mono text-sm text-slate-300">
            {formatSimulatedMoney(row.pnl_after_fees)}
            <span className="ml-1 text-[11px] text-slate-500">
              simulated · drawdown {formatSimulatedMoney(row.max_drawdown)}
            </span>
          </span>
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <GateBadge edge={{ gate_status: row.promotion_status }} />
          <span className="text-[11px] text-slate-500">
            {formatCount(row.n_decisions)} decisions · {formatCount(row.n_fills)} filled
          </span>
          <span className="ml-auto text-xs font-medium text-slate-400">{open ? "Hide the backtest detail" : "Backtest detail"}</span>
        </div>
      </button>
      {open && (
        <div className="mt-4 border-t border-slate-800 pt-4">
          <SettledBars row={row} />
          <div className="mt-4">
            <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
              Backtest gate
            </div>
            <div className="text-[11px] text-slate-300">{backtestGateLabel(row.gate_status)}</div>
            <div className="mt-2 text-[10px] font-bold uppercase tracking-wider text-slate-500">
              Promotion
            </div>
        {/* The scope, in the cell and in VISIBLE TEXT, naming the pair rather than "this".

            Two reasons it is not prose in a comment, which is what it was before the review found it:
            a reader who has not opened the code has no other way to know the verdict is about this
            engine AND this version, and two versions of one engine carry the same verdict, so a
            bare "Promotion" reads as the engine's. It is not in the badge's `title=` either: that is
            a native tooltip on a <div> with no tabindex, no role and no aria-describedby, so it
            cannot be reached by keyboard and is never announced. The scope is the one claim in this
            cell that a mouse-only affordance would take away from everyone else.

            10px is deliberate and is the size this cell's own headers already use, not a leftover:
            there is no 12px floor in this repo, and 10px is this file's convention -- the two
            micro-headers in this cell, each bar's own label, and the shared `GateBadge` below. (No
            count is quoted here, because a comment that quoted the class name would inflate it.)
            The claim is carried by sentence case, not by size -- `uppercase` would have case-folded
            `gas-v1` into a different string than the one the lookup is keyed on.

            `—` rather than a guess: the API's `is_experiment_version` fails toward EXCLUSION, so a
            run with an absent or empty version never reaches this board and the dash is a guard for
            the type, not a state a reader will see. */}
        <div className="text-[10px] text-slate-500">
          for {row.engine} · {row.engine_version ?? "—"}
        </div>
        {/* The shared lookup's verdict -- the badge itself rides on the card's headline,
            beside this scope line's pair; it is not repeated here. */}
        {row.gate_reasons.length > 0 && (
          <ul className="mt-2 list-disc pl-4 text-[11px] text-slate-500">
            {row.gate_reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
        {diagnosticFlags(row).length > 0 && (
          <div className="mt-2 text-[11px] text-amber-300/90">
            Diagnostics: {diagnosticFlags(row).join(" · ")}
          </div>
        )}
          </div>
        </div>
      )}
    </article>
  );
}

const WORDS: Record<EngineStatus, string> = {
  ahead: "Beating it",
  behind: "Behind",
  level: "Level",
  not_comparable: "Unclear",
  not_measured: "Not tested",
  retired: "Retired",
};

const TONES: Record<EngineStatus, Tone> = {
  ahead: "good", behind: "bad", level: "quiet", not_comparable: "quiet", not_measured: "quiet", retired: "quiet",
};

/** The engine's worst error multiple, or an em dash: never 0.0x for an engine nobody measured. */
function ratio(entry: CatalogueEntry): string {
  return entry.worst_brier_ratio === null ? "—" : `${entry.worst_brier_ratio.toFixed(1)}x`;
}

function decisions(entry: CatalogueEntry): string {
  const n = Math.max(0, ...entry.rows.map((r) => r.n_decisions ?? 0));
  return n > 0 ? n.toLocaleString() : "—";
}

function Detail({ entry }: { entry: CatalogueEntry }) {
  const displayOnly = displayOnlyNote(entry);
  const retired = retirementText(entry);
  return (
    <div className="grid gap-6 py-4 md:grid-cols-2">
      <div className="space-y-2 text-sm text-slate-300">
        <div className="font-mono text-xs text-slate-500">{entry.engine}</div>
        <div>{claimText(entry)}</div>
        {displayOnly && <div className="text-amber-300">{displayOnly}</div>}
        {retired && <div className="text-slate-400">{retired}</div>}
      </div>
      <div className="space-y-4">
        {entry.rows.length === 0 && <div className="text-sm text-slate-500">No backtest run yet.</div>}
        {entry.rows.map((row) => (
          <div key={`${row.mode}-${row.engine_version}`} className="text-sm">
            <div className="text-slate-200">{brierVerdict(row)}</div>
            <div className="font-mono text-xs text-slate-400">{brierPair(row)}</div>
            <div className="text-xs text-slate-500">
              {row.engine_version ?? "—"} · {row.mode}
              {row.date_from && row.date_to ? ` · ${row.date_from.slice(0, 10)} → ${row.date_to.slice(0, 10)}` : ""}
            </div>
            <SettledBars row={row} />
            <div className="mt-2 flex items-center gap-2 text-xs text-slate-400">
              {backtestGateLabel(row.gate_status)} <GateBadge edge={{ gate_status: row.promotion_status }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const FETCH_TIMEOUT_MS = 15000;

export default function BacktestsTab() {
  const [data, setData] = useState<ModelsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    setData(null);
    setError(null);
    let cancelled = false;
    let done = false;
    const controller = new AbortController();
    const timer = setTimeout(() => {
      if (!cancelled && !done) {
        done = true;
        controller.abort();
        setError("Request timed out after 15 seconds");
      }
    }, FETCH_TIMEOUT_MS);
    fetch(buildApiUrl("/api/scoreboard"), { signal: controller.signal })
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        if (cancelled || done) return;
        done = true;
        clearTimeout(timer);
        setData(payload as ModelsResponse);
      })
      .catch((err) => {
        if (cancelled || done) return;
        done = true;
        clearTimeout(timer);
        if (err instanceof DOMException && err.name === "AbortError") {
          setError("Request timed out after 15 seconds");
        } else {
          setError(err instanceof Error ? err.message : "Unknown error");
        }
      });
    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller.abort();
    };
  }, [attempt]);

  // The sports records come from their own endpoint, so they stay up when the scoreboard is slow or down.
  if (error) {
    return (
      <div className="space-y-10">
        <div className="rounded-lg border border-rose-900 bg-rose-950/30 p-4 text-sm text-rose-200">
          <p className="font-semibold">Backtests unavailable</p>
          <p className="mt-1 text-rose-300/80">{error}</p>
          <button
            type="button"
            onClick={() => setAttempt((n) => n + 1)}
            className="mt-3 rounded-full border border-slate-700 px-3 py-1 text-sm text-slate-300 hover:text-white"
          >
            Retry
          </button>
        </div>
        <SportsRecord />
      </div>
    );
  }
  if (!data) {
    return (
      <div className="space-y-10">
        <div className="text-slate-400">Loading backtests…</div>
        <SportsRecord />
      </div>
    );
  }

  const summary = summarise(data);
  const rows = data.rows ?? [];
  const entries = data.catalogue?.entries ?? [];
  const count = (status: EngineStatus) => entries.filter((e) => e.status === status).length;

  return (
    <div className="space-y-10">
      <section aria-label="Backtest scoreboard">
        {/* The headline, the count that qualifies it, and the count of the reduction, in one block.
            Rendered together or not at all: a sentence about engines next to an unstated count of
            unmeasured rows is a claim the board has not earned -- and `runs_read` beside `rows_total`
            is the only thing that distinguishes a complete board from one an engine has silently
            vanished from. The excluded versions are NOT listed; only the size of the reduction is. */}
        <div className={`rounded-lg border p-4 text-sm ${SUMMARY_TONES[summary.tone]}`}>
          <p className="font-semibold">{summary.headline}</p>
          <p className="mt-1 text-xs opacity-90">{summary.counts}</p>
          {summary.caveat && <p className="mt-1 text-xs opacity-90">{summary.caveat}</p>}
          {data.promotion_lookup_failed && (
            <p className="mt-2 text-xs text-amber-300">
              The promotion gate could not be read, so every engine below reads SHADOW. That is the
              fail-closed default, not a measurement.
            </p>
          )}
        </div>

        {rows.length === 0 ? (
          <p className="mt-4 text-slate-400">
            No recorded backtest runs yet. Run{" "}
            <code>python -m tradehub.scripts.backtest_engines --engine &lt;engine&gt; --record</code> to
            produce one.
          </p>
        ) : (
          <div className="mt-4 flex flex-col gap-3">
            {/* Every engine the API returned, in the API's order. No filter, no sort, no tail
                collapsed: this board exists to show the losing tail. A card's headline always
                carries the engine's standing; the click only opens its backtest detail. */}
            {rows.map((row) => (
              <EngineCard key={`${row.engine}-${row.mode}-${row.engine_version}`} row={row} />
            ))}
          </div>
        )}
      </section>

      <section aria-label="Every engine">
        <h2 className="text-lg font-semibold text-white">Every engine</h2>
        <p className="mt-1 text-sm text-slate-400">Each model&apos;s error next to the market&apos;s. Lower is better.</p>
        <div aria-label="Totals" className="mt-4 grid gap-3 sm:grid-cols-3">
          <Stat value={count("ahead")} label="beating the market" />
          <Stat value={count("behind")} label="behind the market" />
          <Stat value={data.catalogue?.engines_not_measured ?? "—"} label="not tested yet" />
        </div>

        {data.promotion_lookup_failed && <p className="mt-3 text-sm text-amber-300">Gates could not be read; all show SHADOW.</p>}

        {entries.length === 0 ? (
          <p className="mt-4 text-slate-400">The model list did not arrive.</p>
        ) : (
          <table className="mt-4 w-full text-sm">
            <caption className="sr-only">Every model: its verdict, its error compared with the market, and how many decisions it was tested on.</caption>
            <thead className="text-xs uppercase tracking-wider text-slate-500">
              <tr>
                <th scope="col" className="py-2 text-left font-normal">Model</th>
                <th scope="col" className="py-2 text-left font-normal">Verdict</th>
                <th scope="col" className="py-2 text-right font-normal" title="Our error divided by the market's. Above 1x is worse.">Error vs market</th>
                <th scope="col" className="py-2 text-right font-normal">Tested on</th>
              </tr>
            </thead>
            {/* Every engine, in the catalogue's order: no filter, no sort, no collapsed tail. */}
            <tbody>
              {entries.map((entry) => (
                <Fragment key={entry.engine}>
                  <tr className="border-t border-slate-800">
                    <th scope="row" className="py-3 text-left font-normal">
                      <button
                        type="button"
                        aria-expanded={open === entry.engine}
                        onClick={() => setOpen(open === entry.engine ? null : entry.engine)}
                        className="text-left text-slate-100 hover:text-white"
                      >
                        {entry.label}
                      </button>
                      {entry.cadence && <div className="text-xs text-slate-500">{entry.cadence}</div>}
                    </th>
                    <td className="py-3"><Chip tone={TONES[entry.status]}>{WORDS[entry.status]}</Chip></td>
                    <td className="py-3 text-right text-xl tabular-nums text-slate-100">{ratio(entry)}</td>
                    <td className="py-3 text-right tabular-nums text-slate-300">{decisions(entry)}</td>
                  </tr>
                  {open === entry.engine && (
                    <tr><td colSpan={4} className="border-t border-slate-800/60"><Detail entry={entry} /></td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <SportsRecord />
    </div>
  );
}
