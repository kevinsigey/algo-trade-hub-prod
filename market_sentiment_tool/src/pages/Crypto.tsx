import { useEffect, useState } from "react";

import OnChainPulse from "@/components/OnChainPulse";
import { getJson } from "@/lib/getJson";
import { ctTime, pct, usd, type CryptoBoard, type SniperVerdict } from "@/lib/crypto";

/**
 * Crypto research (phase-3 §5). The old page graded a dead worker as if it
 * were live: the sniper stopped on 2026-06-02 and its windows have been
 * empty ever since. This desk says what is true instead, in the spec's
 * order -- what is live (chain state, Kalshi market data), the sniper's
 * closed record graded once, and the research queue. Nothing here is a
 * prediction and nothing here refreshes a grade.
 */

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

function ClosedRecord() {
  const [verdict, setVerdict] = useState<SniperVerdict | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  useEffect(() => {
    getJson<SniperVerdict>("/api/crypto/sniper-verdict").then(setVerdict).catch(() => setUnavailable(true));
  }, []);

  if (unavailable) {
    return <p className="text-sm text-muted-foreground">The closed record has not been graded yet.</p>;
  }
  if (!verdict) return null;
  const p = verdict.population;
  return (
    <div className="rounded-2xl border border-border/70 bg-card p-5 shadow-sm">
      <div className="grid gap-4 sm:grid-cols-4">
        <div>
          <p className="text-2xl font-semibold tabular-nums">{p.graded.toLocaleString()}</p>
          <p className="text-sm text-muted-foreground">rows graded (of {p.grading_population.toLocaleString()} archived)</p>
        </div>
        <div>
          <p className="text-2xl font-semibold tabular-nums">{pct(verdict.overall.hit_rate)}</p>
          <p className="text-sm text-muted-foreground">hit rate on the evaluator's next-hour rule</p>
        </div>
        <div>
          <p className="text-2xl font-semibold tabular-nums">{verdict.overall.brier_score?.toFixed(3) ?? "—"}</p>
          <p className="text-sm text-muted-foreground">shadow Brier (0.250 is a coin flip)</p>
        </div>
        <div>
          <p className="text-2xl font-semibold tabular-nums">{pct(p.dead_zone_share)}</p>
          <p className="text-sm text-muted-foreground">of rows sat in the model's dead zone</p>
        </div>
      </div>
      <div className="mt-4 space-y-1 text-sm">
        {(["BTC", "ETH"] as const).map((asset) => {
          const a = verdict.by_asset[asset];
          return a ? (
            <p key={asset} className="tabular-nums">
              {asset}: {a.count.toLocaleString()} graded · hit rate {pct(a.hit_rate)} · Brier{" "}
              {a.brier_score?.toFixed(3) ?? "—"}
            </p>
          ) : null;
        })}
      </div>
      <p className="mt-4 text-xs text-muted-foreground">
        The worker ran Apr 8 – Jun 2, 2026 against the Kalshi demo API; every signal's execution was skipped or
        blocked. Graded once on {verdict.graded_on} with the hub's existing shadow evaluator ({verdict.price_source}{" "}
        hourly closes) — a closed record, never refreshed. {verdict.method}
      </p>
    </div>
  );
}

const RESEARCH = [
  {
    title: "Venue lead-lag: does Kalshi move first?",
    chip: "The gate",
    body: "Measure whether Kalshi's implied probabilities on the hourly and 15-minute markets move before or after spot (BRTI). Everything else in this queue waits on the answer: a forecaster only makes sense on the venue that moves second.",
  },
  {
    title: "BTC daily-direction forecaster",
    chip: "Blocked",
    body: "Deferred on Sep 29, 2026. It may only be proposed after the lead-lag measurement shows which venue leads — proposing it before that is how the sniper got built on the wrong side of the information flow.",
  },
  {
    title: "On-chain state as model features",
    chip: "Idea",
    body: "The OnChainPulse series above (fees, mempool backlog, difficulty, base fee, block fullness) is archived nowhere yet. First step is a data question: start storing it, then test whether any of it leads the Kalshi markets.",
  },
];

export default function Crypto() {
  const [board, setBoard] = useState<CryptoBoard | null>(null);
  const [boardFailed, setBoardFailed] = useState(false);

  useEffect(() => {
    getJson<CryptoBoard>("/api/crypto/board").then(setBoard).catch(() => setBoardFailed(true));
  }, []);

  return (
    <div className="mx-auto max-w-5xl space-y-10 p-6 md:p-8">
      <header>
        <h1 className="text-3xl font-bold">Crypto research</h1>
        <p className="mt-2 text-muted-foreground">
          The sniper worker stopped on June 2, 2026 — nothing here is a live signal. What remains is worth
          keeping in the open: live chain state, the Kalshi markets worth tracking, the sniper's closed
          record, and the research queue.
        </p>
      </header>

      <OnChainPulse />

      <section aria-label="Tracked Kalshi markets" className="space-y-3">
        <div>
          <h2 className="text-lg font-semibold">Tracked Kalshi markets</h2>
          <p className="text-xs text-muted-foreground">Market data, not predictions.</p>
        </div>
        {boardFailed ? (
          <p className="text-sm text-muted-foreground">The Kalshi board could not be reached just now.</p>
        ) : board ? (
          <>
            <div className="grid gap-3 md:grid-cols-2">
              <CoinCard asset="BTC" board={board} />
              <CoinCard asset="ETH" board={board} />
            </div>
            <p className="text-xs text-muted-foreground">{board.note}</p>
          </>
        ) : null}
      </section>

      <section aria-label="The sniper's closed record" className="space-y-3">
        <h2 className="text-lg font-semibold">The sniper's closed record</h2>
        <ClosedRecord />
      </section>

      <section aria-label="Research queue" className="space-y-3">
        <h2 className="text-lg font-semibold">Research queue</h2>
        <div className="grid gap-3 md:grid-cols-3">
          {RESEARCH.map((item) => (
            <div key={item.title} className="rounded-2xl border border-border/70 bg-card p-5 shadow-sm">
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{item.chip}</p>
              <h3 className="mt-1 font-semibold">{item.title}</h3>
              <p className="mt-2 text-sm text-muted-foreground">{item.body}</p>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
