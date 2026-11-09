import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { adminJson, ApiError } from "@/lib/workshop";
import { priceText } from "@/lib/valuation";

/**
 * Valuation debates (Phase 1): a second debate panel on the Debates page, under
 * the classic TradingAgents feed. Where the classic panel argues from its own
 * vendor reports, this one debates one fixed exhibit -- the deterministic
 * guidance-band fact sheet for the ticker -- and a judge seat renders a typed
 * verdict against the bands on that sheet.
 *
 * Display-only by spec: verdicts render, log, and grade; they never feed
 * Workshop ideas, orders, or sizing. Every verdict is graded at +20/+60
 * trading days on a peer-relative basis against TWO controls stored on the
 * same row -- the plain band rule (the sheet's zone) and the proposer's own
 * pick -- and the authority gate below counts how many graded verdicts pass
 * that relative bar. Until the gate is met, nothing here carries authority.
 */

export interface ValuationBands {
  bear: number;
  base: number;
  bull: number;
}

export interface ValuationChoice {
  choice_id: string;
  direction: string;
  probability: number | null;
}

export interface ValuationGrade {
  peer_excess_pct: number;
  relative_pass: boolean;
  brier: number | null;
}

export interface ValuationVerdict {
  id: number;
  ticker: string;
  rendered_at: string;
  trigger: string;
  judge: string;
  fact_sheet_id: number;
  price: number | null;
  price_as_of: string | null;
  bands: ValuationBands | null;
  band_basis: string | null;
  zone: string;
  verdict: ValuationChoice & { rationale: string };
  baseline_verdict: string;
  proposer_pick: ValuationChoice;
  options_inputs: {
    implied_move_pct: number | null;
    expression: string;
    long_strike: number | null;
    short_strike: number | null;
    distance_to_target_pct: number | null;
    underpriced: boolean | null;
  } | null;
  falsifier: string | null;
  grades: Record<string, "pending" | ValuationGrade>;
}

export interface ValuationWatchFlag {
  book: string;
  symbol: string;
  underlying: string;
  flag: string; // potential_sell | comfortable_hold
  detail: string; // above_bull | inside_bands | below_bear
  price: number | null;
  bands: ValuationBands | null;
}

export interface ValuationPendingTrigger {
  ticker: string;
  kind: string;
  priority: string;
  created_at: string;
}

export interface ValuationVerdictFeed {
  authority: { gate: number; graded_verdicts: number; relative_passes: number; status: string };
  verdicts: ValuationVerdict[];
  watch: { flags: ValuationWatchFlag[]; pending_triggers: ValuationPendingTrigger[] };
}

const ZONE_LABELS: Record<string, string> = {
  buy_zone_strong: "Strong buy zone",
  buy_zone: "Buy zone",
  neutral: "Neutral",
  short_zone: "Short zone",
  short_zone_strong: "Strong short zone",
  no_chase_long: "No-chase (rich price, cheap guide)",
  stale: "Stale",
  no_bands: "No bands",
  no_price: "No price",
};

export function zoneLabel(zone: string | null | undefined): string {
  if (!zone) return "—";
  return ZONE_LABELS[zone] ?? zone;
}

function zoneBadgeClass(zone: string): string {
  if (zone.startsWith("buy_zone")) return "border-emerald-400/50 bg-emerald-950/40 text-emerald-300";
  if (zone.startsWith("short_zone")) return "border-rose-400/50 bg-rose-950/40 text-rose-300";
  return "border-slate-500/50 bg-slate-800/60 text-slate-200";
}

const CHOICE_LABELS: Record<string, string> = {
  act_at_band_low: "Act at the low band",
  act_at_band_mid: "Act at the mid band",
  watch: "Watch",
  pass: "Pass",
};

export function choiceLabel(choiceId: string | null | undefined): string {
  if (!choiceId) return "—";
  return CHOICE_LABELS[choiceId] ?? choiceId;
}

export function judgeLine(judge: string): string {
  return judge === "free-ai-proposer"
    ? "Judge: free AI (proposer) — Jev seat pending credits"
    : `Judge: ${judge}`;
}

function pctText(v: number | null | undefined): string | null {
  return v == null ? null : `${v.toFixed(1)}%`;
}

/** A bare strike figure, as the Valuation page states levels: 310, not $310.00. */
function strikeText(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

export function optionsLine(v: ValuationVerdict): string {
  const o = v.options_inputs;
  if (!o) return "Options: unevaluated";
  const implied = pctText(o.implied_move_pct);
  const distance = pctText(o.distance_to_target_pct);
  if (o.expression === "debit_put_spread" || o.expression === "debit_call_spread") {
    const kind = o.expression === "debit_put_spread" ? "debit put spread" : "debit call spread";
    const strikes = `${strikeText(o.long_strike)} → ${strikeText(o.short_strike)}`;
    if (implied && distance) {
      return o.underpriced
        ? `Options: ${kind} ${strikes} — implied move ${implied} underprices the ${distance} distance`
        : `Options: ${kind} ${strikes} — implied move ${implied} against a ${distance} distance`;
    }
    return `Options: ${kind} ${strikes}`;
  }
  if (o.expression === "stock_only") {
    return implied ? `Options: stock expression only — implied move ${implied}` : "Options: stock expression only";
  }
  if (o.expression === "none") {
    if (o.underpriced === false && implied && distance) {
      return `Options: none — implied move ${implied} does not underprice the ${distance} distance to the next band`;
    }
    if (implied == null) return "Options: none — no implied move available to price a spread against";
    return "Options: none — no spread underprices the distance to the next band";
  }
  return "Options: unevaluated";
}

function gradeChip(label: string, g: "pending" | ValuationGrade | undefined): { text: string; cls: string } {
  if (!g || g === "pending") return { text: `${label}: pending`, cls: "border-slate-700 text-slate-400" };
  const excess = g.peer_excess_pct;
  const text = excess >= 0
    ? `${label}: beat peers by ${excess.toFixed(1)}% ${g.relative_pass ? "✓" : "✗"}`
    : `${label}: trailed peers by ${Math.abs(excess).toFixed(1)}% ${g.relative_pass ? "✓" : "✗"}`;
  return { text, cls: g.relative_pass ? "border-emerald-400/40 text-emerald-300" : "border-rose-400/40 text-rose-300" };
}

/** The price against its bands, drawn the Valuation page's way: one SVG strip
 * (bear–bull range, base tick, amber price marker) with every word in the chip
 * row beneath it, so labels can never collide on the bar itself. */
function BandStrip({ bands, price }: { bands: ValuationBands; price: number | null }) {
  const vals = [bands.bear, bands.bull, bands.base, ...(price != null ? [price] : [])];
  const rawLo = Math.min(...vals), rawHi = Math.max(...vals);
  const span = rawHi - rawLo || 1;
  const x0 = rawLo - span * 0.05, x1 = rawHi + span * 0.05;
  const W = 680;
  const X = (v: number) => 6 + ((v - x0) / (x1 - x0)) * (W - 12);
  const aria = `Band chart: bear ${priceText(bands.bear)}, base ${priceText(bands.base)}, bull ${priceText(bands.bull)}, price ${priceText(price)}`;
  return (
    <div>
      <svg viewBox={`0 0 ${W} 44`} className="w-full" role="img" aria-label={aria}>
        <rect x={X(bands.bear)} y={16} width={Math.max(2, X(bands.bull) - X(bands.bear))} height={12}
              className="fill-slate-600" rx={2} />
        <line x1={X(bands.base)} y1={11} x2={X(bands.base)} y2={33} className="stroke-slate-100" strokeWidth={2} />
        {price != null && (
          <>
            <line x1={X(price)} y1={4} x2={X(price)} y2={40} stroke="#f59e0b" strokeWidth={2} />
            <path d={`M ${X(price) - 5} 0 L ${X(price) + 5} 0 L ${X(price)} 7 Z`} fill="#f59e0b" />
          </>
        )}
      </svg>
      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1">
        <BandChip dot="bg-slate-400">{`Bear ${priceText(bands.bear)}`}</BandChip>
        <BandChip dot="bg-slate-100">{`Base ${priceText(bands.base)}`}</BandChip>
        <BandChip dot="bg-slate-400">{`Bull ${priceText(bands.bull)}`}</BandChip>
        <BandChip dot="bg-amber-500">{`Price ${priceText(price)}`}</BandChip>
      </div>
    </div>
  );
}

function BandChip({ dot, children }: { dot: string; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-slate-300">
      <span className={`h-2 w-2 rounded-full ${dot}`} aria-hidden="true" />{children}
    </span>
  );
}

export function ValuationVerdictCard({ verdict: v }: { verdict: ValuationVerdict }) {
  const g20 = gradeChip("+20d", v.grades?.["20"]);
  const g60 = gradeChip("+60d", v.grades?.["60"]);
  const prob = v.verdict.probability != null ? `${Math.round(v.verdict.probability * 100)}%` : null;
  return (
    <li>
      <article className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xl font-bold tracking-tight text-white">{v.ticker}</span>
          <span className={`rounded-lg border px-2.5 py-1 text-sm font-bold ${zoneBadgeClass(v.zone)}`}>
            {zoneLabel(v.zone)}
          </span>
          <span className="rounded-full border border-violet-400/40 px-2 py-0.5 text-xs font-semibold text-violet-300">
            Display only — verdicts are graded, they do not feed ideas or orders
          </span>
          <span className="ml-auto flex flex-wrap gap-1.5">
            <span className={`rounded-full border px-2 py-0.5 font-mono text-xs ${g20.cls}`}>{g20.text}</span>
            <span className={`rounded-full border px-2 py-0.5 font-mono text-xs ${g60.cls}`}>{g60.text}</span>
          </span>
        </div>

        <div className="mt-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-base font-extrabold text-slate-100">{choiceLabel(v.verdict.choice_id)}</span>
          {v.verdict.direction && v.verdict.direction !== "none" && (
            <span className="text-sm font-semibold text-slate-300">
              {v.verdict.direction}{prob ? ` · ${prob}` : ""}
            </span>
          )}
          {v.verdict.direction === "none" && prob && (
            <span className="text-sm font-semibold text-slate-300">{prob}</span>
          )}
        </div>
        <p className="mt-1 text-xs text-slate-400">{judgeLine(v.judge)}</p>
        {v.verdict.rationale && (
          <p className="mt-2 text-sm leading-relaxed text-slate-200">{v.verdict.rationale}</p>
        )}

        {v.bands && (
          <figure className="mt-3 rounded-lg border border-slate-800 bg-slate-950/40 px-3 pb-2 pt-3" aria-label="Price against the valuation bands">
            <figcaption className="text-[11px] font-bold uppercase tracking-wider text-slate-500">
              Price vs bands{v.band_basis ? ` (${v.band_basis} basis)` : ""}
            </figcaption>
            <div className="mt-2">
              <BandStrip bands={v.bands} price={v.price} />
            </div>
          </figure>
        )}

        {/* The two controls the verdict is graded against, side by side: the
            plain band rule from the sheet, and the proposer's own pick. */}
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <div className="rounded-lg border border-slate-800 bg-slate-950/30 px-3 py-2 text-sm text-slate-300">
            {`Band rule: ${zoneLabel(v.baseline_verdict)}`}
          </div>
          <div className="rounded-lg border border-slate-800 bg-slate-950/30 px-3 py-2 text-sm text-slate-300">
            {`Proposer's own pick: ${choiceLabel(v.proposer_pick?.choice_id)}`}
          </div>
        </div>

        <p className="mt-3 text-sm text-slate-300">{optionsLine(v)}</p>
        {v.falsifier && (
          <p className="mt-2 text-xs leading-relaxed text-slate-400">{`Falsifier: ${v.falsifier}`}</p>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
          <span>
            {`Rendered ${v.rendered_at.replace("T", " ").slice(0, 16)} · price as of ${v.price_as_of ?? "—"} · trigger ${v.trigger} · fact sheet #${v.fact_sheet_id}`}
          </span>
        </div>
      </article>
    </li>
  );
}

const FLAG_DETAIL_LABELS: Record<string, string> = {
  above_bull: "above the top band",
  inside_bands: "inside its bands",
  below_bear: "below the bear band",
};

function BandWatch({ watch }: { watch: ValuationVerdictFeed["watch"] }) {
  const flags = watch?.flags ?? [];
  const triggers = watch?.pending_triggers ?? [];
  if (!flags.length && !triggers.length) return null;
  return (
    <div className="mt-8">
      <h3 className="text-base font-semibold text-white">Band watch — held positions</h3>
      {flags.length > 0 ? (
        <ul className="mt-3 space-y-2">
          {flags.map((f, i) => {
            const sell = f.flag === "potential_sell";
            return (
              <li key={`${f.book}-${f.symbol}-${i}`}>
                <div className={`flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-lg border px-3 py-2 ${
                  sell ? "border-amber-400/50 bg-amber-950/20" : "border-slate-800 bg-slate-900/40"}`}>
                  <span className="font-bold text-white">{f.symbol}</span>
                  <span className={`text-xs font-semibold ${sell ? "text-amber-300" : "text-slate-400"}`}>
                    {f.book} book
                  </span>
                  <span className={`text-sm ${sell ? "font-semibold text-amber-200" : "text-slate-300"}`}>
                    {sell ? "Potential sell — " : "Comfortable hold — "}
                    {FLAG_DETAIL_LABELS[f.detail] ?? f.detail}
                  </span>
                  {f.price != null && (
                    <span className="text-xs text-slate-400">
                      {`Price ${priceText(f.price)}`}
                      {f.bands ? ` · bear ${priceText(f.bands.bear)} / base ${priceText(f.bands.base)} / bull ${priceText(f.bands.bull)}` : ""}
                    </span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="mt-2 text-sm text-slate-400">No held position sits outside its bands.</p>
      )}
      {triggers.length > 0 && (
        <p className="mt-2 text-xs text-slate-500">
          {triggers.length === 1 ? "1 debate trigger queued" : `${triggers.length} debate triggers queued`}
        </p>
      )}
    </div>
  );
}

export default function ValuationDebates() {
  const [feed, setFeed] = useState<ValuationVerdictFeed | null>(null);
  const [ticker, setTicker] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [lastTicker, setLastTicker] = useState("");
  const [running, setRunning] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const polls = useRef(0);

  useEffect(() => {
    let live = true;
    adminJson<ValuationVerdictFeed>("/api/valuation-verdicts")
      .then((f) => { if (live) setFeed(f); })
      .catch(() => { if (live) setFeed(null); });
    return () => { live = false; };
  }, [refreshKey]);

  // While a verdict renders, poll the feed every 20s (same cadence as the
  // classic debates); give up after ~10 minutes -- the verdict, success or
  // failure, stays in the record either way.
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
      const res = await adminJson<{ started?: string; reused?: number; age_hours?: number }>(
        "/api/valuation-verdicts/run",
        { method: "POST", body: JSON.stringify({ ticker: t, force }) },
      );
      if (res.reused != null) {
        // Inside the reuse window the existing verdict stands -- say so, and
        // offer the explicit fresh run instead of silently spending another.
        setNotice(`${t} already has a verdict from ${res.age_hours}h ago — showing that verdict instead of running a fresh one.`);
        setLastTicker(t);
        setRefreshKey((k) => k + 1);
        return;
      }
      setNotice(null);
      setRunning(t);
      setTicker("");
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setNotice(null);
        setRunning(t);
        setError(`A valuation debate for ${t} is already running — this page refreshes while it runs.`);
        return;
      }
      // A 422 carries the server's detail (no fact sheet / stale / not
      // banded) as the error message via adminJson -- show it as-is.
      setError(e instanceof Error ? e.message : "The valuation debate could not be started");
    }
  };

  const authority = feed?.authority;
  const verdicts = feed?.verdicts ?? [];

  return (
    <section className="mt-10" aria-label="Valuation debates">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold text-white">Valuation debates</h2>
        <span className="rounded-full border border-violet-400/40 px-2 py-0.5 text-xs font-semibold text-violet-300">
          Display only — verdicts are graded, they do not feed ideas or orders
        </span>
      </div>
      {authority && (
        <p className="mt-1 text-xs text-slate-400">
          {`Authority gate: ${authority.relative_passes}/${authority.gate} relative passes (${authority.graded_verdicts} graded)`}
        </p>
      )}

      <div className="mt-6">
        <label htmlFor="valuation-ticker" className="block text-sm font-medium text-slate-300">
          Run a valuation debate on a ticker
        </label>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <input
            id="valuation-ticker"
            value={ticker}
            onChange={(e) => setTicker(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && start()}
            placeholder="AMGN"
            maxLength={12}
            className="w-36 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 uppercase text-white placeholder:text-slate-500 focus:border-violet-400 focus:outline-none"
          />
          <button
            type="button"
            onClick={() => start()}
            disabled={!ticker.trim() || running !== null}
            className="inline-flex items-center gap-2 rounded-lg bg-violet-500 px-4 py-2 font-medium text-violet-950 hover:bg-violet-400 disabled:opacity-50"
          >
            {running && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Run the valuation debate
          </button>
        </div>
        {running && (
          <p className="mt-2 text-sm text-slate-300">
            {`Debating ${running} against its bands — the verdict takes a little while. You can leave this page; the result lands in the record below either way.`}
          </p>
        )}
        {notice && (
          <p className="mt-2 text-sm text-slate-300">
            {notice}{" "}
            <button type="button" onClick={() => start(true)}
                    className="font-semibold text-violet-300 underline underline-offset-2">
              Run fresh anyway
            </button>
          </p>
        )}
        {error && <p role="alert" className="mt-2 text-sm text-rose-300">{error}</p>}
      </div>

      {!feed ? (
        <p className="mt-6 text-sm text-slate-400">Loading valuation verdicts…</p>
      ) : verdicts.length === 0 ? (
        <p className="mt-6 text-sm text-slate-400">No valuation verdicts yet — run the first one above.</p>
      ) : (
        <ul className="mt-6 space-y-4">
          {verdicts.map((v) => <ValuationVerdictCard key={v.id} verdict={v} />)}
        </ul>
      )}

      {feed && <BandWatch watch={feed.watch} />}
    </section>
  );
}
