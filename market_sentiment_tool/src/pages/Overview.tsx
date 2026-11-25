import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";

import { FullView } from "@/components/Panel";
import { useApi } from "@/hooks/usePaperPortfolio";
import {
  cents, count, dayRange, gasRecord, gasTrend, metalsPerTrade, modelsBeating, oilPerTrade, testedVsManual, tone,
  type FifteenLite, type JournalLite,
} from "@/lib/overview";
import { fmtPct, fmtPts, fmtUsd, type PortfolioPayload, type ResultsSplit } from "@/lib/paperPortfolio";
import { useKalshiPilot, REAL_MONEY_BADGE } from "@/pages/KalshiLiveBook";
import { DashCard, Fig, MiniBars, PeekRows, Spark } from "@/pages/portfolio/shared";

/**
 * The home page as a dashboard (2026-11-25 rework, Kevin approved): one card per record, each leading with
 * one number or a small chart and linking to its page. Public reads only; a card whose read failed prints
 * a dash and never blanks its neighbours. Real-money dollars are admin-only, so the Kalshi card shows
 * them only when the (admin) payload carries them.
 */

const DASH = "—";
const TONE_TEXT = { up: "text-emerald-300", down: "text-rose-300", flat: "text-white", unknown: "text-slate-400" } as const;
const toneOf = (v: number | null | undefined) => TONE_TEXT[tone(v ?? null)];

/** A read's headline text: "…" while loading, a dash when it failed or the figure is missing. */
const pick = (loading: boolean, v: string | null | undefined) => (loading ? "…" : v ?? DASH);

function More({ to, children }: { to: string; children: string }) {
  return (
    <Link to={to} className="relative z-10 mt-auto inline-flex items-center gap-1 pt-2 text-xs text-emerald-300 hover:text-emerald-200">
      {children} <ArrowRight className="h-3 w-3" aria-hidden="true" />
    </Link>
  );
}

// --- Stock books -----------------------------------------------------------------------------

function BooksCard() {
  const main = useApi<PortfolioPayload>("/api/portfolio?book=main", 30_000);
  const big = useApi<PortfolioPayload>("/api/portfolio?book=big", 30_000);
  const row = (key: string, label: string, r: typeof main) => {
    const s = r.data?.scoreboard;
    return {
      key, label,
      aside: <span className="hidden sm:inline">{pick(r.loading, s ? fmtUsd(s.equity, { whole: true }) : null)}</span>,
      value: pick(r.loading, s ? `${fmtPct(s.return_pct)} · ${fmtPts(s.ahead_pts)}` : null),
      valueClass: toneOf(s?.ahead_pts),
    };
  };
  const eq = main.data?.scoreboard?.equity;
  return (
    <DashCard title="Stock books" meta="paper" value={pick(main.loading, eq == null ? null : fmtUsd(eq, { whole: true }))}
              sub="Main book value" hint="Two paper accounts. Each row: return since start, then points ahead of SPY.">
      <Spark data={main.data?.curve ?? []} height={36}
             lines={[{ key: "spy_pct", color: "#64748b" }, { key: "portfolio_pct", color: "#34d399" }]} />
      <PeekRows rows={[row("main", "Main", main), row("big", "$1M", big)]} />
      <More to="/portfolio">Both books</More>
    </DashCard>
  );
}

// --- Kalshi live pilot -----------------------------------------------------------------------

export function KalshiCard() {
  const k = useKalshiPilot();
  const p = k.pilot;
  const meta = <span className={REAL_MONEY_BADGE}>REAL MONEY</span>;
  if (!p) {
    return (
      <DashCard title="Kalshi live" meta={meta} className="border-rose-500/30"
                value={pick(k.loading, k.adminOnly ? "Admin only" : null)} valueClass="text-slate-400"
                sub={k.error ? "Unavailable" : "WTI & Brent"}>
        <p className="text-xs text-slate-500">Figures are admin-only.</p>
        <More to="/portfolio?book=kalshi">Live book</More>
      </DashCard>
    );
  }
  const edge = p.gates.edge;
  return (
    <DashCard title="Kalshi live" meta={meta} className="border-rose-500/30"
              value={`${p.fills} fills`} sub={p.halted ? `Halted — ${p.halt_reason ?? "halted"}` : p.state === "live" ? "Running" : "Not enabled"}>
      <dl className="grid grid-cols-3 gap-2">
        <Fig label="Settled" value={p.settled} />
        <Fig label="Net / contract" value={cents(p.live_net_per_contract)} className={toneOf(p.live_net_per_contract)} />
        <Fig label="Edge gate" value={`${edge.settled}/${edge.bar}`} />
      </dl>
      {p.balance != null && <p className="mt-1 text-xs tabular-nums text-slate-400">Balance {fmtUsd(p.balance)}</p>}
      <More to="/portfolio?book=kalshi">Live book</More>
    </DashCard>
  );
}

// --- 15-minute rules -------------------------------------------------------------------------

function FifteenCard({ f }: { f: ReturnType<typeof useApi<FifteenLite>> }) {
  const d = f.data;
  const rows = [
    { key: "oil", label: "Oil", v: oilPerTrade(d) },
    { key: "gas", label: "Gas", v: gasRecord(d)?.perTrade ?? null },
    { key: "metals", label: "Metals", v: metalsPerTrade(d) },
  ];
  const range = (low: number | null | undefined, high?: number | null) => (low == null ? DASH : high == null ? `low ${cents(low)}` : `${cents(low)} to ${cents(high)}`);
  const g = gasRecord(d);
  const by = d?.gate?.by_series;
  const hint = `Paper ¢ per trade after fees. 95% range: gas ${range(g?.low, g?.high)}; WTI low ${range(by?.WTI?.low95)}; Brent low ${range(by?.Brent?.low95)}; metals low ${range(d?.metals?.gate?.forward?.low95)}.`;
  const bars = rows.filter((r) => r.v != null).map((r) => ({ label: r.label, c: (r.v as number) * 100 }));
  return (
    <DashCard title="15-minute rules" meta={<span className="hidden sm:inline">¢ / paper trade</span>} hint={hint}>
      {f.loading ? <p className="text-xs text-slate-500">…</p> : <MiniBars data={bars} valueKey="c" height={40} />}
      <PeekRows rows={rows.map((r) => ({ key: r.key, label: r.label, value: f.loading ? "…" : cents(r.v), valueClass: toneOf(r.v) }))} />
      <More to="/oil">Oil &amp; 15-minute</More>
    </DashCard>
  );
}

// --- Model Tracker, Ideas, Tested vs manual --------------------------------------------------

function ModelsCard({ j }: { j: ReturnType<typeof useApi<JournalLite>> }) {
  const m = modelsBeating(j.data);
  return (
    <DashCard title="Model Tracker" value={pick(j.loading, m ? `${m.beating} of ${m.measured}` : null)}
              sub="beating their benchmark" hint="Ahead of the market price (or climatology) with 95% confidence, settled forecasts only.">
      <p className="text-xs tabular-nums text-slate-400">{m ? `${count(m.scored)} forecasts scored · ${count(m.retired)} retired` : DASH}</p>
      <More to="/journal">Track record</More>
    </DashCard>
  );
}

function IdeasCard() {
  const ideas = useApi<{ live_books?: string[] }[]>("/api/ideas");
  const sum = useApi<{ tested: number; passed: number }>("/api/ideas/summary");
  const live = Array.isArray(ideas.data) ? ideas.data.filter((i) => (i.live_books ?? []).length > 0).length : null;
  const s = sum.data && typeof sum.data.tested === "number" && typeof sum.data.passed === "number" ? sum.data : null;
  return (
    <DashCard title="Ideas" value={pick(ideas.loading, live == null ? null : String(live))} sub="live on a book"
              hint="Ideas trading on a paper book now, and how many tested ideas passed the hub's standard.">
      <p className="text-xs tabular-nums text-slate-400">{pick(sum.loading, s ? `${s.passed} of ${s.tested} tests passing` : null)}</p>
      <More to="/ideas">Ideas</More>
    </DashCard>
  );
}

function SplitCard({ c }: { c: ReturnType<typeof useApi<{ results_split?: ResultsSplit }>> }) {
  const s = testedVsManual(c.data);
  const side = (label: string, v: ResultsSplit["tested"] | undefined) => (
    <Fig label={label} value={pick(c.loading, v ? fmtUsd(v.pnl, { signed: true, whole: true }) : null)} className={toneOf(v?.pnl)} />
  );
  return (
    <DashCard title="Tested vs manual" meta={<span className="hidden sm:inline">closed P&L</span>} hint="Closed-trade P&L on the paper books: tested ideas against manual trades.">
      <dl className="grid grid-cols-2 gap-2 [&_dd]:whitespace-nowrap [&_dd]:text-lg sm:[&_dd]:text-xl">
        {side("Tested ideas", s?.tested)}
        {side("Manual trades", s?.discretionary)}
      </dl>
      <p className="mt-1 text-xs tabular-nums text-slate-400">
        {pick(c.loading, s ? `${s.tested.wins}/${s.tested.trades} vs ${s.discretionary.wins}/${s.discretionary.trades} wins` : null)}
      </p>
      <More to="/portfolio?tab=trade">Closed trades</More>
    </DashCard>
  );
}

// --- Verdict ---------------------------------------------------------------------------------

/** What works / too early / what failed: a one-liner for the card, the full text for its open view. */
function verdict(j: JournalLite | null, f: FifteenLite | null) {
  const m = modelsBeating(j);
  const g = gasRecord(f);
  const trend = gasTrend(f);
  const oil = oilPerTrade(f);
  const metals = metalsPerTrade(f);
  const word = (v: number | null) => ({ up: "positive", down: "negative", flat: "flat", unknown: "unknown" })[tone(v)];
  const clears = g != null && g.low != null && g.low > 0;
  const span = (s: { from: string; to: string; n: number }) => `${dayRange(s.from, s.to)}, ${count(s.n)} trades`;
  const gas = g
    ? `Gas so far: ${cents(g.perTrade)} a paper trade over ${count(g.n)} settled paper trades, 95% range ${cents(g.low)} to ${cents(g.high)}${clears ? ", clear of zero." : ", still touching zero."}`
    : "";
  const holding = trend?.verdict === "holding"
    ? ` It is holding: ${cents(trend.recent.perTrade)} a trade over the last 3 days with trades (${span(trend.recent)}) against ${cents(trend.earlier.perTrade)} before (${span(trend.earlier)}).`
    : "";
  const fading = trend?.verdict === "fading"
    ? `The 15-minute gas edge is fading: ${cents(trend.recent.perTrade)} a paper trade over the last 3 days with trades (${span(trend.recent)}), down from ${cents(trend.earlier.perTrade)} before (${span(trend.earlier)}). `
    : "";
  return [
    { mark: "bg-emerald-400", label: "What works",
      short: `${count(m?.scored)} forecasts graded in public${clears ? `; gas ${cents(g!.perTrade)}` : ""}`,
      long: `The grading: ${count(m?.scored)} calibrated forecasts frozen before the outcome and scored, against the market price where there is one and climatology where there isn't, losses included.${clears ? ` ${gas}${holding}` : ""}` },
    { mark: "bg-amber-400", label: "Too early",
      short: g ? (clears ? "Nothing waiting" : `Gas ${cents(g.perTrade)}, range touches zero`) : DASH,
      long: g ? (clears ? "No rule is waiting on its 95% range." : `${gas}${holding}`) : DASH },
    { mark: "bg-rose-400", label: "What failed",
      short: `${count(m?.retired)} models retired; oil ${cents(oil)}, metals ${cents(metals)}`,
      long: `${count(m?.retired)} models retired from freezing; their records stay public. ${fading}Oil is ${word(oil)} at ${cents(oil)} a paper trade and metals ${word(metals)} at ${cents(metals)}.` },
  ];
}

function VerdictCard({ j, f }: { j: JournalLite | null; f: FifteenLite | null }) {
  const rows = verdict(j, f);
  return (
    <DashCard title="Verdict" className="col-span-2 lg:col-span-3" meta="open for detail" detailTitle="The record so far"
              detail={
                <dl className="grid gap-x-6 gap-y-3 text-sm md:grid-cols-[7rem_1fr]">
                  {rows.map((r) => (
                    <div key={r.label} className="contents">
                      <dt className="flex items-center gap-2 font-semibold text-white">
                        <span className={`h-2.5 w-2.5 rounded-sm ${r.mark}`} aria-hidden="true" />{r.label}
                      </dt>
                      <dd className="text-slate-400">{r.long}</dd>
                    </div>
                  ))}
                </dl>
              }>
      <ul className="divide-y divide-slate-800/70 text-xs">
        {rows.map((r) => (
          <li key={r.label} className="flex items-center gap-2 py-1">
            <span className={`h-2 w-2 shrink-0 rounded-full ${r.mark}`} aria-hidden="true" />
            <span className="w-24 shrink-0 font-semibold text-slate-200">{r.label}</span>
            <span className="min-w-0 truncate text-slate-400">{r.short}</span>
          </li>
        ))}
      </ul>
    </DashCard>
  );
}

// --- How it's built --------------------------------------------------------------------------

const STEPS = [
  { title: "Freeze", body: "Each forecast is stored with a timestamp before the outcome is known, and never edited." },
  { title: "Settle", body: "When the market resolves, the official result is attached: Kalshi settlements, official data releases." },
  { title: "Score", body: "Every forecast is scored against the market price it could have traded at, fees included." },
  { title: "Shadow, then paper", body: "A change runs as a shadow version beside the current one, preregistered, before it can trade. All trading is paper, except one small real-money Kalshi pilot." },
];

function HowBuilt({ onClose }: { onClose: () => void }) {
  return (
    <FullView title="How it's built" onClose={onClose}>
      <p className="text-sm text-slate-400">
        Prices and settlements from Kalshi, paper fills from Alpaca, live ticks from Pyth, and public data from FRED
        and the National Weather Service. Every result moves through the same four steps.
      </p>
      <ol className="mt-4 space-y-3">
        {STEPS.map((s, i) => (
          <li key={s.title} className="grid grid-cols-[1.75rem_1fr] text-sm">
            <span className="font-display text-lg font-semibold leading-5 tabular-nums text-slate-500">{i + 1}</span>
            <span><span className="font-semibold text-white">{s.title}.</span> <span className="text-slate-400">{s.body}</span></span>
          </li>
        ))}
      </ol>
    </FullView>
  );
}

// --- Page ------------------------------------------------------------------------------------

const ET = new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export default function Overview() {
  const journal = useApi<JournalLite>("/api/journal");
  const fifteen = useApi<FifteenLite>("/api/oil/fifteen-rule");
  const closed = useApi<{ results_split?: ResultsSplit }>("/api/portfolio/closed");
  const asOf = useApi<PortfolioPayload>("/api/portfolio?book=main", 30_000).data?.as_of;
  const [how, setHow] = useState(false);

  return (
    <div className="mx-auto max-w-6xl px-4 py-4 md:px-6">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div className="min-w-0">
          <h1 className="font-display text-2xl font-semibold text-white md:text-3xl">Algo Trade Hub</h1>
          <p className="text-sm text-slate-400">A solo research desk that grades every forecast and trade in public.</p>
        </div>
        <div className="flex items-center gap-3 text-xs text-slate-400">
          <span className="tabular-nums">{asOf ? `As of ${ET.format(new Date(asOf))} ET` : "As of —"}</span>
          <button type="button" onClick={() => setHow(true)} aria-haspopup="dialog"
                  className="rounded-md border border-slate-700 px-2 py-1 font-semibold text-slate-200 hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400">
            How it&rsquo;s built
          </button>
        </div>
      </header>
      {how && <HowBuilt onClose={() => setHow(false)} />}

      <section aria-label="Headline numbers" className="mt-3 grid grid-cols-2 gap-2 md:gap-3 lg:grid-cols-3">
        <BooksCard />
        <KalshiCard />
        <FifteenCard f={fifteen} />
        <ModelsCard j={journal} />
        <IdeasCard />
        <SplitCard c={closed} />
        <VerdictCard j={journal.data} f={fifteen.data} />
      </section>
    </div>
  );
}
