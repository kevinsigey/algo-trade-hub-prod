import { useEffect, useState } from "react";
import { ArrowDown, ArrowUp, Info } from "lucide-react";

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
function money(series: string, v: number): string {
  return `$${v.toFixed(series === "KXNATGAS15M" ? 3 : 2)}`;
}

function etTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", { timeZone: "America/New_York", hour: "numeric", minute: "2-digit" });
}

function ctTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-US", { timeZone: "America/Chicago", hour: "2-digit", minute: "2-digit", hour12: false });
}

function Trade({ m }: { m: FifteenMarket }) {
  if (!m.best) return <span className="text-xs text-slate-400">No trade</span>;
  const yes = m.best.side === "yes";
  return (
    <span className={`text-xs font-semibold tabular-nums ${yes ? "text-emerald-300" : "text-rose-300"}`}>
      Buy {yes ? "YES" : "NO"} below {cents(buyBelowLimit(m.best.prob))}
      <span className="ml-1.5 hidden whitespace-nowrap font-normal text-slate-300 sm:inline">now {cents(m.best.cost)}</span>
    </span>
  );
}

/** One series as a tile: the live read, or a single muted line while its window is shut. */
function SeriesTile({ m }: { m: FifteenMarket }) {
  if (m.state !== "live" || m.prob_up == null || m.price == null || m.open_price == null) {
    const next = m.close_time && Date.parse(m.close_time) > Date.now() ? `next window ${ctTime(m.close_time)} CT` : "closed";
    return (
      <li title={m.reason} className="flex items-baseline justify-between gap-2 rounded-md border border-slate-800 bg-slate-950/30 px-2.5 py-2 text-xs text-slate-500">
        <span className="font-medium text-slate-400">{m.label}</span><span className="truncate">{next}</span>
      </li>
    );
  }
  const up = m.prob_up >= 0.5;
  const move = m.price - m.open_price;
  return (
    <li title={m.official_open != null ? `Kalshi's strike ${money(m.series, m.official_open)}` : undefined}
        className="rounded-md border border-slate-700 bg-slate-950/40 px-2 py-1.5 sm:px-2.5 sm:py-2">
      <div className="flex items-baseline justify-between gap-2 text-xs">
        <span className="font-semibold text-white">{m.label}</span>
        <span className="tabular-nums text-slate-400">{Math.max(0, Math.round(m.minutes_left ?? 0))} min left</span>
      </div>
      <div className={`flex items-center gap-1 text-base font-bold tabular-nums sm:text-xl ${up ? "text-emerald-300" : "text-rose-300"}`}>
        {up ? <ArrowUp className="h-4 w-4" aria-hidden="true" /> : <ArrowDown className="h-4 w-4" aria-hidden="true" />}
        {Math.round((up ? m.prob_up : 1 - m.prob_up) * 100)}% {up ? "up" : "down"}
      </div>
      <div className="flex justify-between gap-x-1 text-[11px] tabular-nums text-slate-300 sm:text-xs">
        <span>{m.market == null ? "Not quoted" : `Kalshi ${Math.round(m.market * 100)}% up`}</span>
        <span>{m.best ? `edge +${m.best.net_pts.toFixed(1)} pts` : "edge —"}</span>
      </div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <Trade m={m} />
        <span className="hidden text-[11px] tabular-nums text-slate-400 sm:inline">
          {move >= 0 ? "+" : "−"}{money(m.series, Math.abs(move))} since the open
        </span>
      </div>
    </li>
  );
}

const HINT = "Each contract pays if the price closes the window at or above its open. Our read is the move so far against the volatility left, so it starts at 50% and firms up as the window runs. A trade needs 5+ points over the cost. The graded record freezes at minute 5 (Track record below); the trade rule built on it is on Strategies.";

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
    <section aria-label="Next 15 minutes" className="rounded-lg border border-slate-700 bg-slate-900/70 p-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {markets.length > 0 && !failed && <LiveChip />}
        <h2 title={HINT} className="inline-flex cursor-help items-center gap-1 text-sm font-semibold text-white">
          Next 15 minutes <Info className="h-3.5 w-3.5 text-slate-500" aria-hidden="true" />
        </h2>
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
        <ul className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">{markets.map((m) => <SeriesTile key={m.series} m={m} />)}</ul>
      )}
    </section>
  );
}
