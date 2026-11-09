import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, ChevronDown } from "lucide-react";

import { FifteenRuleRecord } from "@/components/FifteenRuleRecord";
import { FifteenSettlements } from "@/components/FifteenSettlements";
import GapDesk from "@/components/GapDesk";
import { SniperRecord } from "@/components/SniperRecord";
import { StrikeRecordLine } from "@/components/StrikeRecordLine";
import { getJson } from "@/lib/getJson";

/** One read per endpoint; a failed read stays null and its tile says the record is unavailable. */
function useJson<T>(url: string): T | null {
  const [data, setData] = useState<T | null>(null);
  useEffect(() => {
    let stop = false;
    getJson<T>(url).then((d) => { if (!stop) setData(d); }).catch(() => undefined);
    return () => { stop = true; };
  }, [url]);
  return data;
}

type Stage = "Live paper account" | "Paper record" | "Picks only" | "Retired";
const STAGE_TONE: Record<Stage, string> = {
  "Live paper account": "border-emerald-500/50 text-emerald-300",
  "Paper record": "border-sky-500/50 text-sky-300",
  "Picks only": "border-slate-600 text-slate-300",
  Retired: "border-slate-700 text-slate-500",
};

const signed = (v: number, digits = 1) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(digits)}`;
const cents = (v: number) => `${signed(v * 100)}¢ a contract`;
const usd = (v: number) => `${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}`;
const toneOf = (v: number | null | undefined) => (v == null ? undefined : v >= 0 ? "text-emerald-300" : "text-rose-300");

interface GapCategoryLedger { closed: number; realized: number; win_rate: number | null; median_pnl: number | null }
interface SeriesStats { n: number; net_per_contract: number | null; win_rate: number | null }
interface FifteenPayload {
  forward?: SeriesStats; replay?: SeriesStats; ready_trades?: number;
  by_series?: Record<string, SeriesStats>;
  gate?: { forward?: SeriesStats; by_series?: Record<string, SeriesStats> };
  // The metals family (2026-11-09 preregistration): its own record block in
  // the same shape, counted entirely apart from the oil family's above.
  metals?: { prereg_at?: string; ready_trades?: number;
             by_series?: Record<string, SeriesStats>;
             gate?: { forward?: SeriesStats; by_series?: Record<string, SeriesStats> } };
}

/** A diverging bar for a signed value: fills right of centre when positive, left when negative. */
function SignedBar({ value, maxAbs, thin = false }: { value: number | null; maxAbs: number; thin?: boolean }) {
  const w = value == null ? 0 : Math.min(50, (Math.abs(value) / Math.max(maxAbs, 1e-9)) * 50);
  return (
    <div className={`relative ${thin ? "h-1.5" : "h-2.5"} min-w-0 flex-1 overflow-hidden rounded-sm bg-slate-800`} aria-hidden="true">
      <div className="absolute inset-y-0 left-1/2 w-px bg-slate-600" />
      {value != null && w > 0 && (
        <div
          className={`absolute inset-y-0 ${value >= 0 ? "bg-emerald-400/80" : "bg-rose-400/80"}`}
          style={value >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }}
        />
      )}
    </div>
  );
}

/** A 0–1 share as a filled proportion bar (hit rates, hits of settled). */
function ShareBar({ share, tone = "bg-sky-400/80" }: { share: number | null; tone?: string }) {
  return (
    <div className="h-2.5 min-w-0 flex-1 overflow-hidden rounded-sm bg-slate-800" aria-hidden="true">
      {share != null && <div className={`h-full ${tone}`} style={{ width: `${Math.max(0, Math.min(100, share * 100))}%` }} />}
    </div>
  );
}

/** Book vs SPY since inception, from the portfolio payload's own curve. No axis words — the legend is two chips. */
function CurveSpark({ curve }: { curve: { portfolio_pct: number; spy_pct: number }[] }) {
  if (curve.length < 2) return null;
  const vals = curve.flatMap((p) => [p.portfolio_pct, p.spy_pct]);
  const min = Math.min(...vals, 0), max = Math.max(...vals, 0);
  const span = max - min || 1;
  const line = (key: "portfolio_pct" | "spy_pct") =>
    curve.map((p, i) => `${((i / (curve.length - 1)) * 100).toFixed(1)},${(30 - ((p[key] - min) / span) * 28 - 1).toFixed(1)}`).join(" ");
  const zeroY = 30 - ((0 - min) / span) * 28 - 1;
  return (
    <div>
      <svg viewBox="0 0 100 32" preserveAspectRatio="none" className="h-16 w-full" role="img" aria-label="Portfolio curve against SPY">
        <line x1="0" x2="100" y1={zeroY} y2={zeroY} stroke="#334155" strokeWidth="0.5" />
        <polyline points={line("spy_pct")} fill="none" stroke="#64748b" strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
        <polyline points={line("portfolio_pct")} fill="none" stroke="#34d399" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="mt-1 flex gap-3 text-[11px] text-slate-400">
        <span className="inline-flex items-center gap-1"><span className="h-1.5 w-3 rounded bg-emerald-400" /> Book</span>
        <span className="inline-flex items-center gap-1"><span className="h-1.5 w-3 rounded bg-slate-500" /> SPY</span>
      </div>
    </div>
  );
}

/** One market's gated-vs-raw bars for a fifteen tile: gated leads (it is the live rule), raw is the control. */
function SeriesBars({ labels, fifteen, lines }: {
  labels: string[]; fifteen: FifteenPayload | null;
  lines: Record<string, { record: string | null; tone?: string }>;
}) {
  const present = labels.filter((l) => fifteen?.gate?.by_series?.[l] || fifteen?.by_series?.[l]);
  if (!fifteen || present.length === 0) return null;
  const maxAbs = Math.max(0.01, ...present.flatMap((l) => [
    Math.abs(fifteen.gate?.by_series?.[l]?.net_per_contract ?? 0),
    Math.abs(fifteen.by_series?.[l]?.net_per_contract ?? 0),
  ]));
  return (
    <div className="space-y-3">
      {present.map((label) => {
        const g = fifteen.gate?.by_series?.[label];
        const r = fifteen.by_series?.[label];
        return (
          <div key={label}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-xs font-semibold text-slate-200">{label}</span>
              <span className="text-[11px] tabular-nums text-slate-400">
                {g && g.n > 0 ? `${g.n} gated` : "0 gated"}{r ? ` · ${r.n} raw` : ""}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2">
              <span className="w-9 shrink-0 text-[10px] uppercase tracking-wide text-slate-500">Gated</span>
              <SignedBar value={g?.net_per_contract ?? null} maxAbs={maxAbs} />
              <span className={`w-16 shrink-0 text-right text-xs tabular-nums ${toneOf(g?.net_per_contract) ?? "text-slate-400"}`}>
                {g?.net_per_contract == null ? "—" : `${signed(g.net_per_contract * 100)}¢`}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2">
              <span className="w-9 shrink-0 text-[10px] uppercase tracking-wide text-slate-500">Raw</span>
              <SignedBar value={r?.net_per_contract ?? null} maxAbs={maxAbs} thin />
              <span className={`w-16 shrink-0 text-right text-xs tabular-nums ${toneOf(r?.net_per_contract) ?? "text-slate-400"}`}>
                {r?.net_per_contract == null ? "—" : `${signed(r.net_per_contract * 100)}¢`}
              </span>
            </div>
            <p className={`mt-1 text-xs font-medium tabular-nums ${lines[label]?.tone ?? "text-slate-300"}`}>
              {lines[label]?.record ?? <span className="text-slate-500">Record unavailable</span>}
            </p>
          </div>
        );
      })}
    </div>
  );
}

interface TileSpec {
  id: string; name: string; stage: Stage; muted?: boolean; defaultOpen?: boolean;
  visual: ReactNode; stats: ReactNode; children: ReactNode;
}

/** One strategy tile: visual + headline numbers at rest; every word of explanation lives in the expansion. */
function Tile({ spec }: { spec: TileSpec }) {
  return (
    <li id={spec.id} className={`scroll-mt-6 rounded-xl border border-slate-800 bg-slate-900/50 ${spec.muted ? "opacity-70" : ""}`}>
      <details className="group" open={spec.defaultOpen || undefined}>
        <summary className="cursor-pointer list-none p-4 [&::-webkit-details-marker]:hidden">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-white">{spec.name}</span>
            <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${STAGE_TONE[spec.stage]}`}>{spec.stage}</span>
            <span className="ml-auto inline-flex items-center gap-1 text-[11px] font-medium text-slate-400">
              Details <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" aria-hidden="true" />
            </span>
          </div>
          <div className="mt-3">{spec.visual}</div>
          <div className="mt-3">{spec.stats}</div>
        </summary>
        <div className="border-t border-slate-800 px-4 py-4">{spec.children}</div>
      </details>
    </li>
  );
}

/** A headline record line: the same composed string the glance list used to carry, kept whole. */
function RecordLine({ text, tone }: { text: string | null; tone?: string }) {
  return (
    <p className={`text-sm font-medium tabular-nums ${tone ?? "text-slate-200"}`}>
      {text ?? <span className="text-slate-500">Record unavailable</span>}
    </p>
  );
}

/**
 * Strategies (Kevin, 2026-11-05; split per market 2026-11-09; visual tiles 2026-11-09): every rule
 * that trades or paper-trades as a tile — its record drawn (bars, curves) with a few headline
 * numbers, and every sentence of explanation under the tile's expansion, moved verbatim, never
 * deleted. The market pages keep the live reads; the Track record keeps whether the reads are
 * right; this page keeps whether trading on them pays.
 */
export default function Strategies() {
  const portfolio = useJson<{ scoreboard?: { return_pct: number | null; ahead_pts: number | null };
                              curve?: { t: string; portfolio_pct: number; spy_pct: number }[] }>("/api/portfolio");
  const ideas = useJson<{ live_books?: string[] }[]>("/api/ideas");
  const fifteen = useJson<FifteenPayload>("/api/oil/fifteen-rule");
  const strike = useJson<{ settled?: number; hits?: number; hit_rate?: number | null; net_per_contract?: number | null }>("/api/oil/itm-record");
  const gaps = useJson<{ closed_positions?: { category: string; pnl: number | null }[];
                         ledger_by_category?: Record<string, GapCategoryLedger> }>("/api/gaps/desk");
  const sniper = useJson<{ overall?: { count: number; hit_rate: number } }>("/api/crypto/sniper-verdict");

  // Trading on at least one book; `live` on this payload is the shadow record's state, not trading.
  const live = Array.isArray(ideas) ? ideas.filter((i) => (i.live_books ?? []).length > 0).length : null;
  const ahead = portfolio?.scoreboard?.ahead_pts;

  // One market's line for the 15-minute rule: the gated record leads (it is the live rule);
  // a market with no gated trades yet falls back to its raw record and says so.
  const fifteenRecord = (label: string): { record: string | null; tone?: string } => {
    const g = fifteen?.gate?.by_series?.[label];
    const r = fifteen?.by_series?.[label];
    if (!fifteen || (!g && !r)) return { record: null };
    if (g && g.n > 0) {
      return { record: `${g.n} gated trades · ${g.net_per_contract == null ? "—" : cents(g.net_per_contract)} · ${g.win_rate == null ? "—" : `${Math.round(g.win_rate * 100)}% win`}`,
               tone: toneOf(g.net_per_contract) };
    }
    if (r) {
      return { record: `${g ? "0 gated trades · " : ""}raw ${r.n} trade${r.n === 1 ? "" : "s"} · ${r.net_per_contract == null ? "—" : cents(r.net_per_contract)}`,
               tone: toneOf(r.net_per_contract) };
    }
    return { record: null };
  };
  const fifteenRule = (market: string) =>
    `Five minutes into each 15-minute ${market} window, buy the side the model beats by 10+ points after Kalshi's fee; hold to the close. Nothing trades around the 4:45–6:30 PM ET futures halt.`;

  // The metals family's line: same shape as fifteenRecord, read from the
  // metals block — and before its first settled gated trade the line says
  // so, instead of borrowing a number from anywhere else.
  const metalsRecord = (label: string): { record: string | null; tone?: string } => {
    const m = fifteen?.metals;
    if (!m) return { record: null };
    const g = m.gate?.by_series?.[label];
    const r = m.by_series?.[label];
    if (g && g.n > 0) {
      return { record: `${g.n} gated trades · ${g.net_per_contract == null ? "—" : cents(g.net_per_contract)} · ${g.win_rate == null ? "—" : `${Math.round(g.win_rate * 100)}% win`}`,
               tone: toneOf(g.net_per_contract) };
    }
    if (r && r.n > 0) {
      return { record: `${g ? "0 gated trades · " : ""}raw ${r.n} trade${r.n === 1 ? "" : "s"} · ${r.net_per_contract == null ? "—" : cents(r.net_per_contract)}`,
               tone: toneOf(r.net_per_contract) };
    }
    return { record: "Accruing — no settled gated trades yet" };
  };

  // The family headline for a fifteen tile: the gated record across its markets, raw kept beside it as the control.
  const familyStats = (labels: string[], block?: { gate?: { by_series?: Record<string, SeriesStats> }; by_series?: Record<string, SeriesStats> } | null): { gated: SeriesStats | null; raw: SeriesStats | null } => {
    const fold = (src?: Record<string, SeriesStats>): SeriesStats | null => {
      const parts = labels.map((l) => src?.[l]).filter((s): s is SeriesStats => !!s);
      if (parts.length === 0) return null;
      const n = parts.reduce((a, s) => a + s.n, 0);
      const wsum = parts.reduce((a, s) => a + (s.net_per_contract != null ? s.n * s.net_per_contract : 0), 0);
      const wn = parts.reduce((a, s) => a + (s.net_per_contract != null ? s.n : 0), 0);
      const wr = parts.reduce((a, s) => a + (s.win_rate != null ? s.n * s.win_rate : 0), 0);
      const wrn = parts.reduce((a, s) => a + (s.win_rate != null ? s.n : 0), 0);
      return { n, net_per_contract: wn > 0 ? wsum / wn : null, win_rate: wrn > 0 ? wr / wrn : null };
    };
    return { gated: fold(block?.gate?.by_series), raw: fold(block?.by_series) };
  };
  const familyLine = (labels: string[], block?: { gate?: { by_series?: Record<string, SeriesStats> }; by_series?: Record<string, SeriesStats> } | null): { record: string | null; tone?: string } => {
    const { gated, raw } = familyStats(labels, block);
    if (!block || (!gated && !raw)) return { record: null };
    if (gated && gated.n > 0) {
      return { record: `${gated.n} gated trades · ${gated.net_per_contract == null ? "—" : cents(gated.net_per_contract)} · ${gated.win_rate == null ? "—" : `${Math.round(gated.win_rate * 100)}% win`}${raw && raw.n > 0 ? ` · raw control ${raw.n} · ${raw.net_per_contract == null ? "—" : cents(raw.net_per_contract)}` : ""}`,
               tone: toneOf(gated.net_per_contract) };
    }
    if (raw) return { record: `${gated ? "0 gated trades · " : ""}raw ${raw.n} trade${raw.n === 1 ? "" : "s"} · ${raw.net_per_contract == null ? "—" : cents(raw.net_per_contract)}`, tone: toneOf(raw.net_per_contract) };
    return { record: null };
  };

  // One desk's line for the gap tracker: the server's per-desk ledger leads — it is computed
  // over every closed position, while the payload's closed-positions page is capped, so the
  // page is only a fallback for a payload that predates the ledger. (The $10k pot is shared
  // and stays combined in the desk below; the trades carry their market and split exactly.)
  const gapStats = (category: string): GapCategoryLedger | null => {
    if (!gaps) return null;
    const led = gaps.ledger_by_category?.[category];
    if (led && led.closed > 0) return led;
    const pnls = (gaps.closed_positions ?? []).filter((p) => p.category === category && p.pnl != null)
      .map((p) => p.pnl ?? 0).sort((a, b) => a - b);
    if (pnls.length === 0) return null;
    const sum = pnls.reduce((a, v) => a + v, 0);
    const won = pnls.filter((v) => v > 0).length;
    const median = pnls.length % 2 === 1 ? pnls[(pnls.length - 1) / 2]
      : (pnls[pnls.length / 2 - 1] + pnls[pnls.length / 2]) / 2;
    return { closed: pnls.length, realized: sum, win_rate: won / pnls.length, median_pnl: median };
  };
  const gapRecord = (category: string): { record: string | null; tone?: string } => {
    const led = gapStats(category);
    if (!led) return { record: null };
    if (led.win_rate == null || led.median_pnl == null) return { record: null };
    return { record: `${led.closed} closed · ${usd(led.realized)} realized · ${Math.round(led.win_rate * 100)}% won · typical trade ${usd(led.median_pnl)}`,
             tone: toneOf(led.realized) };
  };

  const OIL_LABELS = ["WTI", "Brent", "Natural gas"];
  const METAL_LABELS = ["Gold", "Silver", "Copper"];
  const hasMetals = !!fifteen?.metals;
  // The oil family's headline is the endpoint's own aggregate (gate.forward, with forward as the
  // raw control) — never a client fold that could disagree with the server's record. Metals have
  // no served family aggregate yet, so theirs folds the per-series stats the endpoint does serve.
  const oilAgg = fifteen?.gate?.forward ?? null;
  const oilRaw = fifteen?.forward ?? null;
  const oilLine: { record: string | null; tone?: string } = !fifteen || (!oilAgg && !oilRaw)
    ? { record: null }
    : oilAgg && oilAgg.n > 0
      ? { record: `${oilAgg.n} gated trades · ${oilAgg.net_per_contract == null ? "—" : cents(oilAgg.net_per_contract)} · ${oilAgg.win_rate == null ? "—" : `${Math.round(oilAgg.win_rate * 100)}% win`}${oilRaw && oilRaw.n > 0 ? ` · raw control ${oilRaw.n} · ${oilRaw.net_per_contract == null ? "—" : cents(oilRaw.net_per_contract)}` : ""}`,
          tone: toneOf(oilAgg.net_per_contract) }
      : { record: `${oilAgg ? "0 gated trades · " : ""}raw ${oilRaw?.n ?? 0} trade${oilRaw?.n === 1 ? "" : "s"} · ${oilRaw?.net_per_contract == null ? "—" : cents(oilRaw.net_per_contract)}`, tone: toneOf(oilRaw?.net_per_contract) };
  // The metals headline prefers the block's own served aggregate (gate.forward);
  // the fold over its per-series stats is only the fallback for a payload without one.
  // Before the first settled trade the headline says accruing, like its per-market lines.
  const metalAgg = fifteen?.metals?.gate?.forward ?? null;
  const metalFold = familyStats(METAL_LABELS, fifteen?.metals);
  const metalLine: { record: string | null; tone?: string } = metalAgg && metalAgg.n > 0
    ? { record: `${metalAgg.n} gated trades · ${metalAgg.net_per_contract == null ? "—" : cents(metalAgg.net_per_contract)} · ${metalAgg.win_rate == null ? "—" : `${Math.round(metalAgg.win_rate * 100)}% win`}`,
        tone: toneOf(metalAgg.net_per_contract) }
    : (metalFold.gated || metalFold.raw) && (metalFold.gated?.n ?? 0) === 0 && (metalFold.raw?.n ?? 0) === 0
      ? { record: "Accruing — no settled gated trades yet" }
      : familyLine(METAL_LABELS, fifteen?.metals);
  const gapOil = gapStats("oil"), gapCrypto = gapStats("crypto");
  const gapMaxAbs = Math.max(0.01, Math.abs(gapOil?.realized ?? 0), Math.abs(gapCrypto?.realized ?? 0));
  const gapTotalRealized = (gapOil || gapCrypto) ? (gapOil?.realized ?? 0) + (gapCrypto?.realized ?? 0) : null;
  const strikeShare = strike?.settled ? (strike.hits ?? 0) / strike.settled : null;

  const tiles: TileSpec[] = [
    {
      id: "stock-ideas", name: "Stock ideas", stage: "Live paper account", defaultOpen: true,
      visual: portfolio?.curve ? <CurveSpark curve={portfolio.curve} /> : null,
      stats: (
        <div>
          <p className="text-sm tabular-nums text-slate-300">
            <span className={`text-xl font-semibold ${toneOf(ahead) ?? "text-slate-200"}`}>{ahead == null ? "—" : signed(ahead)}</span>
            {" pts vs SPY since start"}
          </p>
          <RecordLine text={live == null ? null : `${live} idea${live === 1 ? "" : "s"} trading`} />
        </div>
      ),
      children: (
        <section aria-label="Stock ideas">
          <p className="text-sm text-slate-400">
            Workshop ideas that cleared their gates hold their stock baskets on the paper account at their set sizes; a morning job rebalances them.
          </p>
          <p className="mt-2 text-sm text-slate-400">
            The live ideas trade the paper stock accounts; their holdings, sizes and P&amp;L are on the Portfolio, and
            every idea's backtest and shadow record is on Ideas.
          </p>
          <div className="mt-2 flex gap-4 text-sm">
            <Link to="/portfolio" className="inline-flex items-center gap-1 text-emerald-300 hover:text-emerald-200">Portfolio <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></Link>
            <Link to="/ideas" className="inline-flex items-center gap-1 text-emerald-300 hover:text-emerald-200">Ideas <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></Link>
          </div>
        </section>
      ),
    },
    {
      id: "fifteen-rule", name: "15-minute rules — oil & gas", stage: "Paper record",
      visual: <SeriesBars labels={OIL_LABELS} fifteen={fifteen} lines={Object.fromEntries(OIL_LABELS.map((l) => [l, fifteenRecord(l)]))} />,
      stats: <RecordLine text={oilLine.record} tone={oilLine.tone} />,
      children: (
        <section aria-label="15-minute rules by market">
          <div className="space-y-2">
            {(["WTI", "Brent", "natural gas"] as const).map((m) => (
              <p key={m} className="text-sm text-slate-400">{fifteenRule(m)}</p>
            ))}
          </div>
          <p className="mt-3 text-sm text-slate-400">
            One rule, three separate markets — each market has its own line above and its own column in the
            record below, so a market that pays is never hidden inside one that doesn't. First, whether the
            forecasts themselves are right; then, whether trading them pays.
          </p>
          <h3 className="mt-4 text-sm font-semibold text-slate-200">Settlements scoring — the forecasts vs Kalshi's price</h3>
          <FifteenSettlements />
          <h3 className="mt-5 text-sm font-semibold text-slate-200">The trade record</h3>
          <FifteenRuleRecord />
        </section>
      ),
    },
    ...(hasMetals ? [{
      id: "fifteen-metals", name: "15-minute metals rule", stage: "Paper record" as Stage,
      visual: <SeriesBars labels={METAL_LABELS} fifteen={fifteen?.metals ?? null} lines={Object.fromEntries(METAL_LABELS.map((l) => [l, metalsRecord(l)]))} />,
      stats: <RecordLine text={metalLine.record} tone={metalLine.tone} />,
      children: (
        <section aria-label="15-minute metals rule">
          <div className="space-y-2">
            {(["gold", "silver", "copper"] as const).map((m) => (
              <p key={m} className="text-sm text-slate-400">{fifteenRule(m)}</p>
            ))}
          </div>
        </section>
      ),
    }] : []),
    {
      id: "hourly-picks", name: "WTI hourly best strike", stage: "Paper record",
      visual: (
        <div className="flex items-center gap-2">
          <span className="w-14 shrink-0 text-[11px] text-slate-400">Hit rate</span>
          <ShareBar share={strikeShare} tone={(strike?.net_per_contract ?? 0) >= 0 ? "bg-emerald-400/80" : "bg-rose-400/80"} />
          <span className="w-12 shrink-0 text-right text-xs tabular-nums text-slate-200">
            {strike?.settled ? `${Math.round(((strike.hits ?? 0) / strike.settled) * 100)}%` : "—"}
          </span>
        </div>
      ),
      stats: (
        <RecordLine
          text={strike?.settled == null ? null
            : `${strike.hits} of ${strike.settled} hit${strike.net_per_contract == null ? "" : ` · ${cents(strike.net_per_contract)}`}`}
          tone={toneOf(strike?.net_per_contract)}
        />
      ),
      children: (
        <section aria-label="WTI hourly best strike">
          <p className="text-sm text-slate-400">
            Before each hourly WTI settlement on Kalshi, record the strike the model beats by the most, but only when its calibrated chance clears the price you can actually pay by 15 or more points; snapshots land thirty and ten minutes out. The model's raw chances have run about 13 points hot, so they are corrected against its own settled history first. Recorded, never traded.
          </p>
          <p className="mt-2 text-sm text-slate-400">
            The live pick is on the <Link to="/oil" className="text-emerald-300 hover:text-emerald-200">Oil page</Link>; this is how the picks have done.
          </p>
          {strike?.settled != null && strike.settled > 0 && strike.net_per_contract != null && (
            <p className="mt-1 text-sm text-slate-400">
              {strike.net_per_contract < 0
                ? "The graded picks are behind: on the picks so far, the model's stated chances run hotter than its hits — it claims more edge than it has."
                : "The graded picks are ahead so far."}
            </p>
          )}
          <StrikeRecordLine />
        </section>
      ),
    },
    {
      id: "gap-tracker", name: "Kalshi gap tracker", stage: "Paper record",
      visual: (
        <div className="space-y-3">
          {([["Oil", gapOil], ["Crypto", gapCrypto]] as const).map(([label, led]) => (
            <div key={label} className="flex items-center gap-2">
              <span className="w-14 shrink-0 text-[11px] text-slate-400">{label}</span>
              <SignedBar value={led?.realized ?? null} maxAbs={gapMaxAbs} />
              <span className={`w-24 shrink-0 text-right text-xs tabular-nums ${toneOf(led?.realized) ?? "text-slate-400"}`}>
                {led ? usd(led.realized) : "—"}
              </span>
            </div>
          ))}
        </div>
      ),
      stats: (
        <p className="text-sm tabular-nums text-slate-300">
          <span className={`text-xl font-semibold ${toneOf(gapTotalRealized) ?? "text-slate-200"}`}>
            {gapTotalRealized == null ? "—" : usd(gapTotalRealized)}
          </span>
          {" realized · both desks"}
        </p>
      ),
      children: (
        <div>
          <section id="gap-oil" aria-label="Oil gap tracker" className="scroll-mt-6">
            <p className="text-sm text-slate-400">
              Brent and WTI hourly and daily contracts on Kalshi: buy when the model's chance beats the price you can actually pay by 8+ points (fees come out of the trade's P&L, not the test) — only with 2+ hours to settlement and a book deep enough to exit — one trade per event; exit when the gap narrows to 2 points, the model moves more than 5 points from entry, or under an hour is left.
            </p>
            <RecordLine text={gapRecord("oil").record} tone={gapRecord("oil").tone} />
            <div className="mt-3"><GapDesk category="oil" /></div>
          </section>
          <section id="gap-crypto" aria-label="Crypto gap tracker" className="mt-6 scroll-mt-6">
            <p className="text-sm text-slate-400">
              Bitcoin and Ethereum hourly and daily contracts on Kalshi: buy when the model's chance beats the price you can actually pay by 8+ points (fees come out of the trade's P&L, not the test) — only with 2+ hours to settlement and a book deep enough to exit — one trade per event; exit when the gap narrows to 2 points, the model moves more than 5 points from entry, or under an hour is left.
            </p>
            <RecordLine text={gapRecord("crypto").record} tone={gapRecord("crypto").tone} />
            <div className="mt-3"><GapDesk category="crypto" /></div>
          </section>
        </div>
      ),
    },
    {
      id: "sports-picks", name: "Sports picks", stage: "Picks only", muted: true,
      visual: null,
      stats: <RecordLine text="Graded in the Track record" />,
      children: (
        <section aria-label="Sports picks">
          <p className="text-sm text-slate-400">
            Games where the model and the market disagree, after the grading desk's review. No paper ledger yet.
          </p>
          <div className="mt-2 text-sm">
            <Link to="/sports" className="inline-flex items-center gap-1 text-emerald-300 hover:text-emerald-200">Sports <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></Link>
          </div>
        </section>
      ),
    },
    {
      id: "sniper", name: "Crypto sniper", stage: "Retired", muted: true,
      visual: (
        <div className="flex items-center gap-2">
          <span className="w-14 shrink-0 text-[11px] text-slate-400">Hit rate</span>
          <ShareBar share={sniper?.overall?.hit_rate ?? null} tone="bg-slate-400/80" />
          <span className="w-12 shrink-0 text-right text-xs tabular-nums text-slate-200">
            {sniper?.overall ? `${Math.round(sniper.overall.hit_rate * 100)}%` : "—"}
          </span>
        </div>
      ),
      stats: (
        <RecordLine text={sniper?.overall ? `${sniper.overall.count.toLocaleString()} graded · ${Math.round(sniper.overall.hit_rate * 100)}% hit` : null} />
      ),
      children: (
        <section aria-label="Crypto sniper">
          <p className="text-sm text-slate-400">
            Next-hour BTC and ETH calls on the Kalshi demo account; the worker stopped June 2, 2026.
          </p>
          <h2 className="mt-4 text-lg font-semibold text-white">Crypto sniper, retired</h2>
          <SniperRecord />
        </section>
      ),
    },
  ];

  return (
    <div className="mx-auto max-w-7xl px-4 py-5 md:px-6">
      <h1 className="text-2xl font-bold tracking-tight text-white">Strategies</h1>
      <p className="mt-1 max-w-[70ch] text-sm text-slate-400">
        Every rule that trades or paper-trades, one market per line: what it does in one sentence, where it
        stands, and its record. The market pages keep the live reads; the Track record says whether the reads
        are right; this page says whether trading on them pays.
      </p>

      <ul aria-label="Strategies at a glance" className="mt-5 grid items-start gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {tiles.map((spec) => <Tile key={spec.id} spec={spec} />)}
      </ul>
    </div>
  );
}
