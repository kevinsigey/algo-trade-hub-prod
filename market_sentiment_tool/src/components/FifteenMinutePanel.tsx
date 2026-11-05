import { useEffect, useState } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";

import { FifteenRuleRecord } from "@/components/FifteenRuleRecord";
import { LiveChip } from "@/components/LiveChip";
import { getJson } from "@/lib/getJson";
import { buyBelowLimit, cents } from "@/lib/oilFees";

interface Pick { side: "yes" | "no"; prob: number; cost: number; net_pts: number }
interface FifteenMarket {
  series: string; label: string; state: string; reason?: string;
  close_time?: string; minutes_left?: number; open_price?: number; price?: number;
  official_open?: number | null; prob_up?: number; market?: number | null;
  yes_bid?: number | null; yes_ask?: number | null; best?: Pick | null;
}
interface FifteenLive { state: string; as_of?: string; markets?: FifteenMarket[] }

const REFRESH_MS = 15 * 1000;
const GRID = "sm:grid sm:grid-cols-[7rem_8.5rem_6.5rem_minmax(0,1fr)] sm:items-center sm:gap-x-4";

function money(series: string, v: number): string {
  return `$${v.toFixed(series === "KXNATGAS15M" ? 3 : 2)}`;
}

function etTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
}

function Trade({ m }: { m: FifteenMarket }) {
  if (!m.best) return <span className="text-sm text-slate-400">No trade</span>;
  const yes = m.best.side === "yes";
  return (
    <span className={`inline-block text-sm font-semibold tabular-nums ${yes ? "text-emerald-300" : "text-rose-300"}`}>
      Buy {yes ? "YES" : "NO"} below {cents(buyBelowLimit(m.best.prob))}
      <span className="ml-2 whitespace-nowrap font-normal text-slate-300">now {cents(m.best.cost)}</span>
    </span>
  );
}

function MarketRow({ m }: { m: FifteenMarket }) {
  if (m.state !== "live" || m.prob_up == null || m.price == null || m.open_price == null) {
    return (
      <li className={`border-t border-slate-800 py-3 ${GRID}`}>
        <div className="font-semibold text-white">{m.label}</div>
        <div className="mt-1 text-sm text-slate-400 sm:col-span-3 sm:mt-0">{m.reason ?? "Unavailable right now."}</div>
      </li>
    );
  }
  const up = m.prob_up >= 0.5;
  const move = m.price - m.open_price;
  return (
    <li className="border-t border-slate-800 py-3">
      <div className={GRID}>
        <div className="font-semibold text-white">{m.label}</div>
        <div className={`mt-1 flex items-center gap-1 text-2xl font-bold tabular-nums sm:mt-0 ${up ? "text-emerald-300" : "text-rose-300"}`}>
          {up ? <ArrowUp className="h-5 w-5" aria-hidden="true" /> : <ArrowDown className="h-5 w-5" aria-hidden="true" />}
          {Math.round((up ? m.prob_up : 1 - m.prob_up) * 100)}% {up ? "up" : "down"}
        </div>
        <div className="mt-1 text-sm tabular-nums text-slate-300 sm:mt-0">
          {m.market == null ? "Not quoted" : `Kalshi ${Math.round(m.market * 100)}% up`}
        </div>
        <div className="mt-1 sm:mt-0"><Trade m={m} /></div>
      </div>
      <p className="mt-1 text-xs tabular-nums text-slate-400">
        {move >= 0 ? "+" : "−"}{money(m.series, Math.abs(move))} since the open · now {money(m.series, m.price)}
        {m.official_open != null && <> · Kalshi's strike {money(m.series, m.official_open)}</>}
      </p>
    </li>
  );
}

/**
 * The 15-minute half of the Oil page: one direction contract per window, so unlike the hourly ladder this one does
 * state a direction. It's the move so far against the volatility left, the same math the journal freezes.
 */
export function FifteenMinutePanel() {
  const [live, setLive] = useState<FifteenLive | null>(null);
  const [failed, setFailed] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), REFRESH_MS);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    let stop = false;
    getJson<FifteenLive>("/api/oil/fifteen-live")
      .then((r) => { if (!stop) { setLive(r); setFailed(false); } })
      .catch(() => { if (!stop) setFailed(true); });
    return () => { stop = true; };
  }, [tick]);

  const markets = live?.markets ?? [];
  const open = markets.find((m) => m.close_time);
  return (
    <section aria-label="Next 15 minutes" className="rounded-xl border border-slate-700 bg-slate-900/70 p-5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {markets.length > 0 && !failed && <LiveChip />}
        <h2 className="text-xl font-semibold text-white">Next 15 minutes</h2>
        {open?.close_time && (
          <span className="text-xs tabular-nums text-slate-400">
            window closes {etTime(open.close_time)} ET · {Math.max(0, Math.round(open.minutes_left ?? 0))} min left
          </span>
        )}
      </div>
      {markets.length === 0 ? (
        <p className="mt-2 text-sm text-slate-400">
          {failed ? "The 15-minute read is unavailable right now." : "Reading the live market…"}
        </p>
      ) : (
        <>
          <ul className="mt-3">{markets.map((m) => <MarketRow key={m.series} m={m} />)}</ul>
          <p className="mt-2 text-xs leading-relaxed text-slate-400">
            Each contract pays if the price closes the window at or above its open. Our read is the move so far
            against the volatility left, so it starts at 50% and firms up as the window runs. A trade needs 5+ points
            over the cost. The graded record freezes at minute 5, and it's under Track record below.
          </p>
        </>
      )}
      <FifteenRuleRecord />
    </section>
  );
}
