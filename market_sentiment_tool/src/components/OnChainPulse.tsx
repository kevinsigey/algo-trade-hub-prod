import { useEffect, useState } from "react";

import { getJson } from "@/lib/getJson";

/** Live BTC and ETH chain state from free public data (`/api/onchain`). Display only; every number is the server's. */
type Chain = { chain: "btc" | "eth"; status: "ok" | "unavailable"; stale?: boolean } & Record<string, number | string | null | boolean | undefined>;

const n = (v: unknown, digits = 0, unit = "") =>
  typeof v === "number" ? `${v.toLocaleString("en-US", { maximumFractionDigits: digits })}${unit}` : "—";

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-2xl font-semibold tabular-nums text-white">{value}</div>
      <div className="mt-1 text-sm text-slate-300">{label}</div>
      {hint && <div className="text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

export default function OnChainPulse() {
  const [chains, setChains] = useState<Chain[] | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    getJson<{ chains: Chain[] }>("/api/onchain").then((r) => setChains(r.chains ?? [])).catch(() => setFailed(true));
  }, []);

  if (failed) return <p className="text-sm text-slate-500">Live chain data could not be reached just now.</p>;
  if (!chains) return null;
  const btc = chains.find((c) => c.chain === "btc");
  const eth = chains.find((c) => c.chain === "eth");

  return (
    <section aria-label="On-chain right now" className="space-y-3" data-onchain="">
      <div>
        <h2 className="text-lg font-semibold text-slate-200">On-chain right now</h2>
        <p className="text-xs text-slate-500">Free public data (mempool.space, a public Ethereum node). Refreshes every minute.</p>
      </div>
      {btc?.status === "ok" ? (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-slate-400">Bitcoin{btc.stale ? " (last good reading)" : ""}</h3>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Tile label="Fastest fee" value={n(btc.fee_fastest, 0, " sat/vB")} hint={`1-hour fee ${n(btc.fee_hour, 0, " sat/vB")}`} />
            <Tile label="Waiting to confirm" value={n(btc.mempool_txs)} hint={`${n(btc.mempool_mb, 1, " MB")} backlog`} />
            <Tile label="Next difficulty change" value={typeof btc.retarget_pct === "number" ? `${btc.retarget_pct > 0 ? "+" : ""}${btc.retarget_pct.toFixed(2)}%` : "—"} hint={`in ${n(btc.blocks_to_retarget)} blocks`} />
            <Tile label="Hashrate" value={n(btc.hashrate_eh, 0, " EH/s")} hint={`block ${n(btc.height)}`} />
          </div>
        </div>
      ) : <p className="text-sm text-slate-500">Bitcoin chain data could not be reached just now.</p>}
      {eth?.status === "ok" ? (
        <div className="space-y-2">
          <h3 className="text-sm font-medium text-slate-400">Ethereum{eth.stale ? " (last good reading)" : ""}</h3>
          <div className="grid gap-3 sm:grid-cols-3">
            <Tile label="Base fee" value={n(eth.base_fee_gwei, 3, " gwei")} hint={`20-block average ${n(eth.base_fee_20_block_avg_gwei, 3, " gwei")}`} />
            <Tile label="Blocks full" value={typeof eth.block_fullness === "number" ? `${Math.round(eth.block_fullness * 100)}%` : "—"} hint="50% is the target; above it fees rise" />
            <Tile label="Latest block" value={n(eth.block)} />
          </div>
        </div>
      ) : <p className="text-sm text-slate-500">Ethereum chain data could not be reached just now.</p>}
    </section>
  );
}
