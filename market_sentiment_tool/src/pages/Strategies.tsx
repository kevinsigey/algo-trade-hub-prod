import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight } from "lucide-react";

import { FifteenRuleRecord } from "@/components/FifteenRuleRecord";
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
const toneOf = (v: number | null | undefined) => (v == null ? undefined : v >= 0 ? "text-emerald-300" : "text-rose-300");

/**
 * Strategies (Kevin, 2026-11-05): every rule that trades or paper-trades, on one page. The market pages keep
 * the live reads, the Track record keeps whether the reads are right, and this page keeps whether trading on
 * them makes money: the rule in a line, where it stands, and its record against the bar it must clear.
 */
export default function Strategies() {
  const portfolio = useJson<{ scoreboard?: { return_pct: number | null; ahead_pts: number | null } }>("/api/portfolio");
  const ideas = useJson<{ live_books?: string[] }[]>("/api/ideas");
  const fifteen = useJson<{ forward?: { n: number; net_per_contract: number | null }; replay?: { n: number; net_per_contract: number | null };
                            ready_trades?: number }>("/api/oil/fifteen-rule");
  const strike = useJson<{ settled?: number; hits?: number; net_per_contract?: number | null }>("/api/oil/itm-record");
  const gaps = useJson<{ ledger?: { return_pct: number; resolved: number }; evidence?: { days: number; min_days: number } }>("/api/gaps/desk");
  const sniper = useJson<{ overall?: { count: number; hit_rate: number } }>("/api/crypto/sniper-verdict");

  // Trading on at least one book; `live` on this payload is the shadow record's state, not trading.
  const live = Array.isArray(ideas) ? ideas.filter((i) => (i.live_books ?? []).length > 0).length : null;
  const ahead = portfolio?.scoreboard?.ahead_pts;
  const f = fifteen?.forward;
  const rows: Row[] = [
    {
      id: "stock-ideas", name: "Stock ideas", stage: "Live paper account", detail: "/portfolio",
      rule: "Each live idea holds its basket at its set size on the paper stock account; the morning job rebalances it.",
      record: ahead == null ? null : `${signed(ahead)} pts vs SPY since start${live != null ? ` · ${live} idea${live === 1 ? "" : "s"} trading` : ""}`,
      tone: toneOf(ahead),
    },
    {
      id: "fifteen-rule", name: "15-minute oil and gas rule", stage: "Paper record", detail: "#fifteen-rule",
      rule: "Five minutes into each window, buy the side the model beats by 10+ points; hold to the close. Never around the 5–6 PM ET futures halt.",
      record: !f ? null : f.n === 0
        ? `0 of ${fifteen?.ready_trades ?? 300} forward trades · replay ${fifteen?.replay?.net_per_contract == null ? "—" : cents(fifteen.replay.net_per_contract)}`
        : `${f.n} of ${fifteen?.ready_trades ?? 300} forward trades · ${f.net_per_contract == null ? "—" : cents(f.net_per_contract)}`,
      tone: toneOf(f?.n ? f.net_per_contract : null),
    },
    {
      id: "hourly-picks", name: "Hourly oil best strike", stage: "Paper record", detail: "#hourly-picks",
      rule: "Half an hour before each hourly WTI settle, the strike with the biggest edge after fees; held to the settle.",
      record: strike?.settled == null ? null
        : `${strike.hits} of ${strike.settled} hit${strike.net_per_contract == null ? "" : ` · ${cents(strike.net_per_contract)}`}`,
      tone: toneOf(strike?.net_per_contract),
    },
    {
      id: "gap-tracker", name: "Kalshi gap tracker, oil and crypto", stage: "Paper record", detail: "#gap-tracker",
      rule: "Buy when the model beats the ask by 8+ points; exit when the gap closes, the model moves 5+ points, or an hour before settling.",
      record: !gaps?.ledger ? null
        : `${signed(gaps.ledger.return_pct)}% on $10k · ${gaps.ledger.resolved} closed${gaps.evidence ? ` · ${gaps.evidence.days.toFixed(0)} of ${gaps.evidence.min_days} days` : ""}`,
      tone: toneOf(gaps?.ledger?.return_pct),
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
        Every rule that trades or paper-trades, in one place: the rule, where it stands, and its record. The market
        pages keep the live reads; the Track record says whether the reads are right; this page says whether trading
        on them pays.
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

        <section id="fifteen-rule" aria-label="15-minute oil and gas rule" className="scroll-mt-6 rounded-xl border border-slate-800 bg-slate-900/60 p-4 xl:row-span-2">
          <h2 className="text-lg font-semibold text-white">15-minute oil and gas rule</h2>
          <FifteenRuleRecord />
        </section>

        <section id="hourly-picks" aria-label="Hourly oil best strike" className="scroll-mt-6 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
          <h2 className="text-lg font-semibold text-white">Hourly oil best strike</h2>
          <p className="mt-1 text-sm text-slate-400">
            The live pick is on the <Link to="/oil" className="text-emerald-300 hover:text-emerald-200">Oil page</Link>; this is how the picks have done.
          </p>
          <StrikeRecordLine />
        </section>

        <div id="gap-tracker" className="scroll-mt-6">
          <GapDesk />
        </div>

        <section id="sniper" aria-label="Crypto sniper" className="scroll-mt-6 space-y-2">
          <h2 className="text-lg font-semibold text-white">Crypto sniper, retired</h2>
          <SniperRecord />
        </section>
      </div>
    </div>
  );
}
