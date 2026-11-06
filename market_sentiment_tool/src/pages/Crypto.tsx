import { useEffect, useState, useCallback } from "react";

import CryptoDesk from "@/components/CryptoDesk";
import { Panel } from "@/components/Panel";
import { getJson } from "@/lib/getJson";
import { ctTime, pct, usd, type CryptoBoard } from "@/lib/crypto";
import type { JournalResponse } from "@/lib/journal";
import { STATUS_WORDS, skillText, viewRows } from "@/lib/journalView";

/**
 * Crypto (Kevin, 2026-11-06: "a wall of text that says nothing" -- redesign around what we can realistically
 * do). The page reads like the Hormuz watcher: what is happening in BTC and ETH market structure right now,
 * each signal with a plain sentence and an explainer, a stress read from the signals that can speak, then how
 * our hourly models do against Kalshi. Every number comes from the server; nothing here computes a score.
 */

interface Signal {
  key: string; label: string; value: number | null; unit: string; percentile: number | null; normal: string | null;
  stress: number | null; weight: number; reading: string; why: string;
}
interface CoinWatch { price: number | null; change_24h_pct: number | null; signals: Signal[] }
interface Watch {
  as_of?: string; state?: string;
  stress?: { stress: number | null; label: string | null; speaking: number; of: number };
  coins?: { BTC: CoinWatch; ETH: CoinWatch };
  market?: Signal[];
}

const LABEL_TONE: Record<string, string> = {
  Calm: "text-emerald-300 border-emerald-500/50", Watch: "text-amber-300 border-amber-500/50",
  Stressed: "text-rose-300 border-rose-500/50",
};

const stressTone = (s: number | null) =>
  s == null ? "bg-slate-700" : s < 0.25 ? "bg-emerald-400" : s < 0.5 ? "bg-amber-400" : "bg-rose-400";

function valueText(s: Signal | undefined): string {
  if (!s || s.value == null) return "—";
  const v = Math.abs(s.value) >= 100 ? s.value.toFixed(0) : s.value.toFixed(s.unit === "bps" ? 1 : 2);
  return s.unit === "$bn" ? `$${v}bn` : `${v}${s.unit === "% a year" ? "%" : ` ${s.unit}`}`;
}

function StressBar({ stress }: { stress: number | null }) {
  return (
    <div className="h-1 w-full rounded-full bg-slate-800" aria-hidden="true">
      <div className={`h-full rounded-full ${stressTone(stress)}`} style={{ width: `${Math.round((stress ?? 0) * 100)}%` }} />
    </div>
  );
}

/** One signal, both coins side by side; the sentence is the coin under the most stress. */
function SignalTile({ label, rows, why }: { label: string; rows: { coin: string; signal: Signal | undefined }[]; why: string }) {
  const lead = [...rows]
    .filter((r) => r.signal)
    .sort((a, b) => {
      const stressA = a.signal!.stress ?? -1;
      const stressB = b.signal!.stress ?? -1;
      if (stressB !== stressA) return stressB - stressA;
      // Tie-break: prefer coin with a value (non-null)
      const hasValueA = a.signal!.value != null;
      const hasValueB = b.signal!.value != null;
      if (hasValueA !== hasValueB) return hasValueB ? 1 : -1;
      return 0;
    })[0];
  return (
    <section aria-label={label} className="flex flex-col rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</h3>
      <div className={`mt-2 grid gap-3 ${rows.length > 1 ? "grid-cols-2" : "grid-cols-1"}`}>
        {rows.map(({ coin, signal }) => (
          <div key={coin} className="min-w-0">
            {rows.length > 1 && <div className="text-[11px] font-medium text-slate-500">{coin}</div>}
            <div className="text-xl font-semibold tabular-nums text-white">{valueText(signal)}</div>
            <div className="mt-1"><StressBar stress={signal?.stress ?? null} /></div>
            {signal?.normal && <div className="mt-1 truncate text-[11px] text-slate-500">{signal.normal}</div>}
          </div>
        ))}
      </div>
      {lead?.signal && (
        <p className="mt-2 text-sm text-slate-300">
          {rows.length > 1 && <span className="font-semibold text-slate-400">{lead.coin} · </span>}
          <span>{lead.signal.reading}</span>
        </p>
      )}
      <details className="mt-auto pt-2 text-sm">
        <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-300">Why it matters</summary>
        <p className="mt-1 text-slate-400">{why}</p>
      </details>
    </section>
  );
}

function CoinPrice({ coin, c }: { coin: string; c: CoinWatch }) {
  const ch = c.change_24h_pct;
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">{coin}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums text-white">
        {c.price == null ? "—" : `$${c.price.toLocaleString("en-US", { maximumFractionDigits: c.price >= 1000 ? 0 : 2 })}`}
      </div>
      <div className={`text-sm tabular-nums ${ch == null ? "text-slate-500" : ch >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
        {ch == null ? "—" : `${ch >= 0 ? "+" : "−"}${Math.abs(ch).toFixed(1)}%`} <span className="text-slate-500">24h</span>
      </div>
    </div>
  );
}

function WatchView({ watch }: { watch: Watch }) {
  const coins = watch.coins!;
  const keys = coins.BTC.signals.map((s) => s.key);
  const st = watch.stress!;
  return (
    <>
      <div className="grid gap-2 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)]">
        <div className={`rounded-lg border bg-slate-900/60 p-3 ${LABEL_TONE[st.label ?? ""] ?? "border-slate-800 text-slate-300"}`}>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">Market stress</div>
          <div className="mt-1 flex items-baseline gap-3">
            <span className="text-2xl font-bold">{st.label ?? "Not enough signals"}</span>
            {st.stress != null && <span className="text-sm tabular-nums text-slate-400">{st.stress.toFixed(2)} of 1</span>}
          </div>
          <p className="mt-1 text-xs text-slate-400">
            From the {st.speaking} of {st.of} signals that can speak. A signal with no history or no live value is left
            out, never read as calm.
          </p>
        </div>
        <CoinPrice coin="BTC" c={coins.BTC} />
        <CoinPrice coin="ETH" c={coins.ETH} />
      </div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {keys.map((k) => {
          const btc = coins.BTC.signals.find((s) => s.key === k);
          const eth = coins.ETH.signals.find((s) => s.key === k);
          return <SignalTile key={k} label={btc?.label ?? k} why={btc?.why ?? eth?.why ?? ""}
                             rows={[{ coin: "BTC", signal: btc }, { coin: "ETH", signal: eth }]} />;
        })}
        {(watch.market ?? []).map((m) => <SignalTile key={m.key} label={m.label} why={m.why} rows={[{ coin: "", signal: m }]} />)}
      </div>
    </>
  );
}

/** How our hourly models do against Kalshi's own price, from the journal; the server grades. */
function ModelsVsMarket({ board }: { board: CryptoBoard | null }) {
  const [journal, setJournal] = useState<JournalResponse | null>(null);
  useEffect(() => {
    getJson<JournalResponse>("/api/journal").then(setJournal).catch(() => undefined);
  }, []);
  const rows = journal?.forecasters
    ? viewRows(journal.forecasters.filter((f) => f.forecaster === "crypto_btc_hourly" || f.forecaster === "crypto_eth_hourly"))
    : [];
  return (
    <Panel title="Our hourly models vs Kalshi"
           full={board ? (
             <div className="grid gap-3 md:grid-cols-2">
               <CoinCard asset="BTC" board={board} />
               <CoinCard asset="ETH" board={board} />
               <p className="text-xs text-slate-400 md:col-span-2">{board.note}</p>
             </div>
           ) : undefined}
           fullTitle="Kalshi's crypto markets right now">
      {rows.length === 0 ? (
        <p className="text-sm text-slate-400">The model record is loading or unavailable.</p>
      ) : (
        <ul className="space-y-1 text-sm">
          {rows.map((r) => (
            <li key={r.key} className="flex items-baseline justify-between gap-3">
              <span className="text-slate-200">{r.label}</span>
              <span className="tabular-nums text-slate-400">
                {r.scored.toLocaleString()} scored · skill {skillText(r.skill)} · {STATUS_WORDS[r.status]}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-2 text-xs text-slate-500">
        Skill is accuracy against Kalshi's own price: above zero means we read the hour better than the market.
        Next: test whether the stress read above sharpens these models, as the Hormuz read did for oil.
      </p>
    </Panel>
  );
}

/** Kalshi market data for one coin: not a prediction. */
function CoinCard({ asset, board }: { asset: "BTC" | "ETH"; board: CryptoBoard }) {
  const spot = board.spots[asset];
  const hourly = board.hourly[asset];
  const quarter = board.quarter[asset];
  return (
    <div className="rounded-2xl border border-border/70 bg-card p-5 shadow-sm">
      <div className="flex items-baseline justify-between">
        <h3 className="text-lg font-semibold">{asset}</h3>
        <p className="text-sm tabular-nums text-muted-foreground">Spot {usd(spot)} (Kraken)</p>
      </div>

      <div className="mt-4">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">Hourly ladder · Kalshi</p>
        {hourly == null ? (
          <p className="mt-1 text-sm text-muted-foreground">Unavailable just now.</p>
        ) : hourly.shape === "coin_flip" ? (
          <p className="mt-1 text-sm">
            Coin-flip strike <strong className="tabular-nums">{usd(hourly.coin_flip_strike)}</strong> — implied{" "}
            <strong className="tabular-nums">{hourly.implied_pct}%</strong> at/above it · closes {ctTime(hourly.closes_at)}
            {hourly.one_sided ? " · one-sided quote" : ""}
          </p>
        ) : (
          <p className="mt-1 text-sm">
            The book quotes a step, not a curve: near-certain at/above{" "}
            <strong className="tabular-nums">{usd(hourly.bracket?.[0])}</strong>, near-impossible at/above{" "}
            <strong className="tabular-nums">{usd(hourly.bracket?.[1])}</strong> · closes {ctTime(hourly.closes_at)}
            {spot != null && hourly.bracket && spot >= hourly.bracket[0] && spot < hourly.bracket[1]
              ? " · spot sits inside the step"
              : ""}
          </p>
        )}
      </div>

      <div className="mt-4">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">15-minute · Kalshi</p>
        {quarter == null ? (
          <p className="mt-1 text-sm text-muted-foreground">Unavailable just now.</p>
        ) : (
          <p className="mt-1 text-sm">
            <strong className="tabular-nums">{quarter.implied_pct}%</strong> implied at/above{" "}
            <strong className="tabular-nums">{usd(quarter.floor)}</strong> · closes {ctTime(quarter.closes_at)}
            {quarter.one_sided ? " · one-sided quote" : ""}
          </p>
        )}
      </div>
    </div>
  );
}

export default function Crypto() {
  const [watch, setWatch] = useState<Watch | null>(null);
  const [failed, setFailed] = useState(false);
  const [board, setBoard] = useState<CryptoBoard | null>(null);

  const fetchWatch = useCallback(async () => {
    try {
      const data = await getJson<Watch>("/api/crypto/watch");
      // Only update if we got valid data (not unavailable)
      if (data && data.coins && data.stress) {
        setWatch(data);
        setFailed(false);
      } else if (!watch) {
        // Initial load failed with unavailable
        setFailed(true);
      }
      // If unavailable on refetch, keep the last good watch
    } catch {
      // On network error, keep last good watch if we have one
      if (!watch) setFailed(true);
    }
  }, [watch]);

  useEffect(() => {
    fetchWatch();
    getJson<CryptoBoard>("/api/crypto/board").then(setBoard).catch(() => undefined);
    
    // Refetch every 5 minutes
    const interval = setInterval(fetchWatch, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, [fetchWatch]);

  const live = watch?.coins && watch.stress;
  return (
    <div className="mx-auto max-w-7xl space-y-3 px-4 py-5 md:px-6">
      <header>
        <h1 className="text-2xl font-bold text-white">Crypto</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-400">
          What is moving BTC and ETH right now, from free market data: who is paying to hold leverage, how hard
          the price is moving, what options charge for protection, and whether money is arriving or leaving.
          {watch?.as_of && <span className="text-slate-500"> Read {ctTime(watch.as_of)}, refreshed every 5 minutes.</span>}
        </p>
      </header>

      {failed || (watch && !live) ? (
        <p className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-sm text-slate-400">
          The market signals are unavailable right now. The sources are free public feeds; the next read retries.
        </p>
      ) : !watch ? (
        <p className="text-sm text-slate-400">Reading the market…</p>
      ) : (
        <WatchView watch={watch} />
      )}

      <div className="grid gap-2 lg:grid-cols-2">
        <ModelsVsMarket board={board} />
        <Panel title="Protocols as companies" full={<CryptoDesk />} fullTitle="The crypto desk">
          <p className="text-sm text-slate-400">
            Networks and protocols read like stocks: price, market cap, fees and revenue, and what the price pays
            for a year of fees. Open it for the full desk.
          </p>
        </Panel>
      </div>
    </div>
  );
}
