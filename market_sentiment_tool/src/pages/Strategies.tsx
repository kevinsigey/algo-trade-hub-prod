import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";

import { FifteenRuleRecord } from "@/components/FifteenRuleRecord";
import { FifteenSettlements } from "@/components/FifteenSettlements";
import GapDesk from "@/components/GapDesk";
import { SniperRecord } from "@/components/SniperRecord";
import { StrikeRecordLine } from "@/components/StrikeRecordLine";
import { getJson } from "@/lib/getJson";

/** One read per endpoint; a failed read stays null and its row says the record is unavailable. */
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

interface Row { id: string; name: string; rule: string; stage: Stage; record: string | null; tone?: string; detail: string }

const signed = (v: number, digits = 1) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(digits)}`;
const cents = (v: number) => `${signed(v * 100)}¢ a contract`;
const usd = (v: number) => `${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}`;
const toneOf = (v: number | null | undefined) => (v == null ? undefined : v >= 0 ? "text-emerald-300" : "text-rose-300");

interface SeriesStats { n: number; net_per_contract: number | null; win_rate: number | null }
interface FifteenPayload {
  forward?: SeriesStats; replay?: SeriesStats; ready_trades?: number;
  by_series?: Record<string, SeriesStats>;
  gate?: { forward?: SeriesStats; by_series?: Record<string, SeriesStats> };
}

/**
 * Strategies (Kevin, 2026-11-05; split per market 2026-11-09): every rule that trades or
 * paper-trades, one market per line — what it does in one sentence, where it stands, and its
 * record, readable on first sight. Composite entries hid which market was carrying them, so
 * the 15-minute rule lists per market and the gap tracker lists per desk. The market pages
 * keep the live reads; the Track record keeps whether the reads are right; this page keeps
 * whether trading on them pays.
 */
export default function Strategies() {
  const portfolio = useJson<{ scoreboard?: { return_pct: number | null; ahead_pts: number | null } }>("/api/portfolio");
  const ideas = useJson<{ live_books?: string[] }[]>("/api/ideas");
  const fifteen = useJson<FifteenPayload>("/api/oil/fifteen-rule");
  const strike = useJson<{ settled?: number; hits?: number; net_per_contract?: number | null }>("/api/oil/itm-record");
  const gaps = useJson<{ closed_positions?: { category: string; pnl: number | null }[] }>("/api/gaps/desk");
  const sniper = useJson<{ overall?: { count: number; hit_rate: number } }>("/api/crypto/sniper-verdict");

  // Trading on at least one book; `live` on this payload is the shadow record's state, not trading.
  const live = Array.isArray(ideas) ? ideas.filter((i) => (i.live_books ?? []).length > 0).length : null;
  const ahead = portfolio?.scoreboard?.ahead_pts;

  // One market's line for the 15-minute rule: the gated record leads (it is the live rule);
  // a market with no gated trades yet falls back to its raw record and says so.
  const fifteenRecord = (label: string): Pick<Row, "record" | "tone"> => {
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

  // One desk's line for the gap tracker: its own closed trades (the $10k pot is shared and
  // stays combined in the desk below; the trades carry their market and split exactly).
  const gapRecord = (category: string): Pick<Row, "record" | "tone"> => {
    const mine = (gaps?.closed_positions ?? []).filter((p) => p.category === category && p.pnl != null);
    if (!gaps || mine.length === 0) return { record: null };
    const sum = mine.reduce((a, p) => a + (p.pnl ?? 0), 0);
    const won = mine.filter((p) => (p.pnl ?? 0) > 0).length;
    return { record: `${mine.length} closed · ${usd(sum)} realized · ${Math.round((won / mine.length) * 100)}% won`,
             tone: toneOf(sum) };
  };

  const rows: Row[] = [
    {
      id: "stock-ideas", name: "Stock ideas", stage: "Live paper account", detail: "/portfolio",
      rule: "Workshop ideas that cleared their gates hold their stock baskets on the paper account at their set sizes; a morning job rebalances them.",
      record: ahead == null ? null : `${signed(ahead)} pts vs SPY since start${live != null ? ` · ${live} idea${live === 1 ? "" : "s"} trading` : ""}`,
      tone: toneOf(ahead),
    },
    {
      id: "fifteen-wti", name: "WTI 15-minute rule", stage: "Paper record", detail: "#fifteen-rule",
      rule: fifteenRule("WTI"), ...fifteenRecord("WTI"),
    },
    {
      id: "fifteen-brent", name: "Brent 15-minute rule", stage: "Paper record", detail: "#fifteen-rule",
      rule: fifteenRule("Brent"), ...fifteenRecord("Brent"),
    },
    {
      id: "fifteen-natgas", name: "Natural gas 15-minute rule", stage: "Paper record", detail: "#fifteen-rule",
      rule: fifteenRule("natural gas"), ...fifteenRecord("Natural gas"),
    },
    {
      id: "hourly-picks", name: "WTI hourly best strike", stage: "Paper record", detail: "#hourly-picks",
      rule: "Thirty minutes before each hourly WTI settlement on Kalshi, buy the single strike the model beats by the most after fees; hold to the settle.",
      record: strike?.settled == null ? null
        : `${strike.hits} of ${strike.settled} hit${strike.net_per_contract == null ? "" : ` · ${cents(strike.net_per_contract)}`}`,
      tone: toneOf(strike?.net_per_contract),
    },
    {
      id: "gap-oil", name: "Oil gap tracker", stage: "Paper record", detail: "#gap-oil",
      rule: "Brent and WTI hourly and daily contracts on Kalshi: buy when the model's chance beats the price you can actually pay by 8+ points after the fee — one trade per event — and exit when the gap narrows to 2 points, the model moves 5+ points against the trade, or 2 hours before settlement.",
      ...gapRecord("oil"),
    },
    {
      id: "gap-crypto", name: "Crypto gap tracker", stage: "Paper record", detail: "#gap-crypto",
      rule: "Bitcoin and Ethereum hourly and daily contracts on Kalshi: the same gap rule as the oil desk — buy an 8+ point gap after fees, one trade per event; exit at a 2-point gap, a 5+ point model move against the trade, or 2 hours before settlement.",
      ...gapRecord("crypto"),
    },
    {
      id: "sports-picks", name: "Sports picks", stage: "Picks only", detail: "/sports",
      rule: "Games where the model and the market disagree, after the grading desk's review. No paper ledger yet.",
      record: "Graded in the Track record",
    },
    {
      id: "sniper", name: "Crypto sniper", stage: "Retired", detail: "#sniper",
      rule: "Next-hour BTC and ETH calls on the Kalshi demo account; the worker stopped June 2, 2026.",
      record: sniper?.overall ? `${sniper.overall.count.toLocaleString()} graded · ${Math.round(sniper.overall.hit_rate * 100)}% hit` : null,
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

      <ul aria-label="Strategies at a glance" className="mt-5 divide-y divide-slate-800 rounded-xl border border-slate-800 bg-slate-900/50">
        {rows.map((r) => {
          const inPage = r.detail.startsWith("#");
          const name = <span className="font-semibold text-white group-hover:underline underline-offset-2">{r.name}</span>;
          return (
            <li key={r.id} className="grid gap-x-6 gap-y-1 px-4 py-3 md:grid-cols-[minmax(0,15rem)_minmax(0,1fr)_minmax(0,16rem)] md:items-center">
              <div className="flex flex-wrap items-center gap-2">
                {inPage ? <a href={r.detail} className="group">{name}</a> : <Link to={r.detail} className="group">{name}</Link>}
                <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${STAGE_TONE[r.stage]}`}>{r.stage}</span>
              </div>
              <p className="text-sm text-slate-400">{r.rule}</p>
              <p className={`text-sm font-medium tabular-nums md:text-right ${r.tone ?? "text-slate-200"}`}>
                {r.record ?? <span className="text-slate-500">Record unavailable</span>}
              </p>
            </li>
          );
        })}
      </ul>

      {/* The detail, two across (2026-11-06: one screen and a bit). */}
      <div className="mt-4 grid items-start gap-3 xl:grid-cols-2">
        <section id="stock-ideas" aria-label="Stock ideas" className="scroll-mt-6 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h2 className="text-lg font-semibold text-white">Stock ideas</h2>
          <p className="mt-1 text-sm text-slate-400">
            The live ideas trade the paper stock accounts; their holdings, sizes and P&amp;L are on the Portfolio, and
            every idea's backtest and shadow record is on Ideas.
          </p>
          <div className="mt-2 flex gap-4 text-sm">
            <Link to="/portfolio" className="inline-flex items-center gap-1 text-emerald-300 hover:text-emerald-200">Portfolio <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></Link>
            <Link to="/ideas" className="inline-flex items-center gap-1 text-emerald-300 hover:text-emerald-200">Ideas <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></Link>
          </div>
        </section>

        <section id="fifteen-rule" aria-label="15-minute rules by market" className="scroll-mt-6 rounded-xl border border-slate-800 bg-slate-900/60 p-4 xl:row-span-2">
          <h2 className="text-lg font-semibold text-white">15-minute rules — WTI, Brent, natural gas</h2>
          <p className="mt-1 text-sm text-slate-400">
            One rule, three separate markets — each market has its own line above and its own column in the
            record below, so a market that pays is never hidden inside one that doesn't. First, whether the
            forecasts themselves are right; then, whether trading them pays.
          </p>
          <h3 className="mt-4 text-sm font-semibold text-slate-200">Settlements scoring — the forecasts vs Kalshi's price</h3>
          <FifteenSettlements />
          <h3 className="mt-5 text-sm font-semibold text-slate-200">The trade record</h3>
          <FifteenRuleRecord />
        </section>

        <section id="hourly-picks" aria-label="WTI hourly best strike" className="scroll-mt-6 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h2 className="text-lg font-semibold text-white">WTI hourly best strike</h2>
          <p className="mt-1 text-sm text-slate-400">
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

        <div id="gap-oil" className="scroll-mt-6">
          <GapDesk category="oil" />
        </div>

        <div id="gap-crypto" className="scroll-mt-6">
          <GapDesk category="crypto" />
        </div>

        <section id="sniper" aria-label="Crypto sniper" className="scroll-mt-6 space-y-2">
          <h2 className="text-lg font-semibold text-white">Crypto sniper, retired</h2>
          <SniperRecord />
        </section>
      </div>
    </div>
  );
}
