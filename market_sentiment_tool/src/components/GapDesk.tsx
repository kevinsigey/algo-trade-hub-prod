import { useApi } from "@/hooks/usePaperPortfolio";
import { ctDateTime } from "@/lib/format";
import { fmtPct, fmtUsd, tone } from "@/lib/paperPortfolio";

interface GapRow {
  ticker: string; category: string; side: string | null; model_prob: number | null; yes_ask: number | null;
  no_ask: number | null; gap_pts: number | null; failed: string[]; settles_at: string;
}
interface Position {
  ticker: string; category: string; side: string; model_at_entry: number; entry_price: number; gap_pts: number;
  contracts: number; exit_state: string | null; exit_reason?: string | null; pnl?: number | null;
}
interface Score { n: number; model_brier: number | null; market_brier: number | null; brier_delta: number | null;
  model_log_loss: number | null; market_log_loss: number | null;
  calibration: { bucket: string; n: number; mean_model: number; hit_rate: number }[] }
export interface GapCategoryLedger { closed: number; realized: number; win_rate: number | null; median_pnl: number | null }
export interface GapDeskPayload {
  as_of: string | null; started_at: string | null;
  evidence: { status: string; days: number; pairs: number; min_days: number; min_pairs: number };
  grade: { all: Score; crypto: Score; oil: Score };
  ledger: { bankroll: number; return_pct: number; max_drawdown_pct: number; resolved: number; open: number;
            win_rate: number | null; avg_entry_gap_pts: number | null };
  ledger_by_category?: Record<string, GapCategoryLedger>;
  fee_basis: "net" | "gross" | "mixed";
  open_positions: Position[]; closed_positions: Position[]; top_gaps: GapRow[]; near_misses: GapRow[];
  funnel: Record<string, Record<string, number>>;
}

const REASON: Record<string, string> = {
  gap: "gap under 8 points", too_close_to_settlement: "2 hours or less to settlement",
  resolution_source_unknown: "no named resolution source", liquidity_unknown: "order book unread",
  not_enough_depth: "book too thin for the position", exit_slippage: "exit would slip over 3%",
  model_or_market_unknown: "model or market unknown",
};

const num = (v: number | null | undefined, digits = 3) => (v == null ? "—" : v.toFixed(digits));
const cents = (v: number | null | undefined) => (v == null ? "—" : `${Math.round(v * 100)}c`);
const pts = (v: number | null | undefined) => (v == null ? "—" : `${v.toFixed(1)} pts`);

function Stat({ label, value, className = "text-white" }: { label: string; value: string; className?: string }) {
  return (
    <div>
      <dt className="text-xs text-slate-400">{label}</dt>
      <dd className={`mt-0.5 text-base font-semibold tabular-nums ${className}`}>{value}</dd>
    </div>
  );
}

function GapTable({ rows, showFailed = false }: { rows: GapRow[]; showFailed?: boolean }) {
  return (
    <div className="-mx-4 overflow-x-auto px-4">
      <table className="w-full min-w-[34rem] text-left text-xs tabular-nums">
        <thead className="text-slate-400">
          <tr>
            <th scope="col" className="py-1 pr-3 font-medium">Contract</th>
            <th scope="col" className="py-1 pr-3 font-medium">Side</th>
            <th scope="col" className="py-1 pr-3 text-right font-medium">Model</th>
            <th scope="col" className="py-1 pr-3 text-right font-medium">Ask</th>
            <th scope="col" className="py-1 pr-3 text-right font-medium">Gap</th>
            {showFailed && <th scope="col" className="py-1 font-medium">Failed on</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.ticker} className="border-t border-slate-800/80 text-slate-200">
              <td className="whitespace-nowrap py-1.5 pr-3 font-medium text-white">{r.ticker}</td>
              <td className="py-1.5 pr-3">{r.side ?? "—"}</td>
              <td className="py-1.5 pr-3 text-right">{r.model_prob == null ? "UNKNOWN" : `${(r.model_prob * 100).toFixed(0)}%`}</td>
              <td className="py-1.5 pr-3 text-right">{cents(r.side === "no" ? r.no_ask : r.yes_ask)}</td>
              <td className="py-1.5 pr-3 text-right">{pts(r.gap_pts)}</td>
              {showFailed && <td className="py-1.5 text-slate-400">{r.failed.map((f) => REASON[f] ?? f).join(", ")}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PositionTable({ rows }: { rows: Position[] }) {
  return (
    <div className="-mx-4 overflow-x-auto px-4">
      <table className="w-full min-w-[34rem] text-left text-xs tabular-nums">
        <thead className="text-slate-400">
          <tr>
            <th scope="col" className="py-1 pr-3 font-medium">Contract</th>
            <th scope="col" className="py-1 pr-3 font-medium">Side</th>
            <th scope="col" className="py-1 pr-3 text-right font-medium">Contracts</th>
            <th scope="col" className="py-1 pr-3 text-right font-medium">Entry</th>
            <th scope="col" className="py-1 pr-3 text-right font-medium">Entry gap</th>
            <th scope="col" className="py-1 font-medium">State</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.ticker} className="border-t border-slate-800/80 text-slate-200">
              <td className="whitespace-nowrap py-1.5 pr-3 font-medium text-white">{p.ticker}</td>
              <td className="py-1.5 pr-3">{p.side}</td>
              <td className="py-1.5 pr-3 text-right">{p.contracts}</td>
              <td className="py-1.5 pr-3 text-right">{cents(p.entry_price)}</td>
              <td className="py-1.5 pr-3 text-right">{pts(p.gap_pts)}</td>
              <td className={`py-1.5 ${p.pnl != null ? tone(p.pnl) : p.exit_state ? "text-amber-300" : "text-slate-400"}`}>
                {p.pnl != null ? `${fmtUsd(p.pnl, { signed: true })} · ${p.exit_reason}` : p.exit_state ?? "open"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The Kalshi gap tracker: do the model's fair values find real mispricings after executable prices?
 * A paper ledger on a $10,000 tracker bankroll. It never places or suggests an order. */
/** One desk; `category` filters its gap lists to one market, none shows both (the ledger is shared either way). */
export default function GapDesk({ category }: { category?: "oil" | "crypto" }) {
  const { data } = useApi<GapDeskPayload>("/api/gaps/desk");
  // Additive: no data or a partial reply, no panel.
  if (!data?.evidence || !data.grade?.all || !data.ledger || !data.top_gaps || !data.near_misses || !data.funnel) return null;
  const { evidence, ledger } = data;
  const score = category ? data.grade[category] : data.grade.all;
  const mine = (rows: { category: string }[]) => (category ? rows.filter((r) => r.category === category) : rows);
  const top = mine(data.top_gaps) as GapRow[];
  const open = mine(data.open_positions) as Position[];
  const closed = mine(data.closed_positions) as Position[];
  // This desk's own settled record: the two desks share one $10k pot (the ledger above is
  // the pot, never split), but every closed trade carries its category and its P&L, so the
  // desks' trade records split exactly. The server's per-desk ledger is computed over every
  // closed position and leads; the closed-positions page below is capped, so it is only a
  // fallback for a payload that predates the ledger.
  const pnls = closed.map((p) => p.pnl).filter((v): v is number => v != null);
  const realized = pnls.reduce((a, b) => a + b, 0);
  const wins = pnls.filter((v) => v > 0).length;
  const byPnl = [...pnls].sort((a, b) => a - b);
  const median = byPnl.length === 0 ? null
    : byPnl.length % 2 === 1 ? byPnl[(byPnl.length - 1) / 2]
    : (byPnl[byPnl.length / 2 - 1] + byPnl[byPnl.length / 2]) / 2;
  const catLedger = category ? data.ledger_by_category?.[category] : undefined;
  const deskRecord = catLedger && catLedger.closed > 0 && catLedger.win_rate != null && catLedger.median_pnl != null
    ? { closed: catLedger.closed, realized: catLedger.realized,
        wins: Math.round(catLedger.win_rate * catLedger.closed), median: catLedger.median_pnl }
    : { closed: pnls.length, realized, wins, median };
  const funnel: Record<string, number> = category ? data.funnel[category] ?? {}
    : Object.values(data.funnel).reduce<Record<string, number>>((acc, f) => {
        for (const [k, v] of Object.entries(f)) acc[k] = (acc[k] ?? 0) + v;
        return acc;
      }, {});
  const enough = evidence.status !== "NOT ENOUGH EVIDENCE";
  return (
    <section aria-label="Kalshi gap tracker" className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-slate-200">
          {category ? `${category === "oil" ? "Oil" : "Crypto"} gap tracker` : "Kalshi gap tracker"}
        </h2>
        <p className="text-xs text-slate-400">
          Paper ledger, no orders · hourly snapshot, delayed{data.as_of ? ` · as of ${ctDateTime(data.as_of)}` : " · no snapshot yet"}
        </p>
      </div>
      <p className={`mt-2 text-sm font-medium ${enough ? "text-emerald-300" : "text-amber-200"}`}>
        {evidence.status}: {evidence.days.toFixed(1)} of {evidence.min_days} days, {evidence.pairs} of {evidence.min_pairs} paired forecasts, {ledger.resolved} resolved paper trades.
      </p>
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-5">
        <Stat label="Brier, model minus market" value={num(score.brier_delta)}
              className={score.brier_delta == null ? "text-white" : score.brier_delta < 0 ? "text-emerald-400" : "text-rose-400"} />
        <Stat label={`Paper return (${data.fee_basis === "mixed" ? "part gross, part net" : data.fee_basis})`} value={fmtPct(ledger.return_pct)} className={tone(ledger.return_pct)} />
        <Stat label="Max drawdown" value={`${ledger.max_drawdown_pct.toFixed(1)}%`} />
        <Stat label="Open positions (max 2 per event)" value={`${ledger.open} of 5`} />
        <Stat label="Win rate" value={ledger.win_rate == null ? "—" : `${(ledger.win_rate * 100).toFixed(0)}%`} />
      </dl>
      {category && (
        <p className="mt-3 text-sm text-slate-300">
          This desk's own record:{" "}
          <span className="font-medium tabular-nums text-white">
            {deskRecord.closed} closed trades · {fmtUsd(deskRecord.realized, { signed: true })} realized · {deskRecord.wins} of {deskRecord.closed} won
            {deskRecord.median != null ? ` · typical trade ${fmtUsd(deskRecord.median, { signed: true })}` : ""}
          </span>
          . The return and drawdown above are the shared $10k pot both desks trade from — the pot is
          not split; the trades are.
        </p>
      )}
      {open.length > 0 && <div className="mt-4"><h3 className="mb-1 text-xs font-medium text-slate-300">Open paper positions</h3><PositionTable rows={open} /></div>}
      {top.length > 0 && <div className="mt-4"><h3 className="mb-1 text-xs font-medium text-slate-300">Largest passing gaps</h3><GapTable rows={top} /></div>}
      <details className="mt-4 text-sm">
        <summary className="cursor-pointer text-xs text-slate-400 hover:text-slate-200">Grading, gate funnel, near misses and the full ledger</summary>
        <div className="mt-3 space-y-4">
          <div>
            <h3 className="mb-1 text-xs font-medium text-slate-300">Model vs Kalshi's price</h3>
            <div className="-mx-4 overflow-x-auto px-4">
              <table className="w-full min-w-[28rem] text-left text-xs tabular-nums">
                <thead className="text-slate-400"><tr>
                  <th scope="col" className="py-1 pr-3 font-medium" />
                  <th scope="col" className="py-1 pr-3 text-right font-medium">Pairs</th>
                  <th scope="col" className="py-1 pr-3 text-right font-medium">Brier, model</th>
                  <th scope="col" className="py-1 pr-3 text-right font-medium">Brier, market</th>
                  <th scope="col" className="py-1 pr-3 text-right font-medium">Log loss, model</th>
                  <th scope="col" className="py-1 text-right font-medium">Log loss, market</th>
                </tr></thead>
                <tbody>
                  {(["all", "crypto", "oil"] as const).map((k) => {
                    const s = data.grade[k];
                    return (
                      <tr key={k} className="border-t border-slate-800/80 text-slate-200">
                        <td className="py-1.5 pr-3 capitalize">{k}</td>
                        <td className="py-1.5 pr-3 text-right">{s.n}</td>
                        <td className="py-1.5 pr-3 text-right">{num(s.model_brier)}</td>
                        <td className="py-1.5 pr-3 text-right">{num(s.market_brier)}</td>
                        <td className="py-1.5 pr-3 text-right">{num(s.model_log_loss)}</td>
                        <td className="py-1.5 text-right">{num(s.market_log_loss)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
          {score.calibration.length > 0 && (
            <p className="text-xs text-slate-400">
              Calibration: {score.calibration.map((b) => `${b.bucket}%: ${(b.hit_rate * 100).toFixed(0)}% hit (${b.n})`).join(" · ")}
            </p>
          )}
          <div>
            <h3 className="mb-1 text-xs font-medium text-slate-300">Gate funnel{category ? `, ${category}` : ", oil and crypto"}</h3>
            <p className="text-xs text-slate-400">
              {funnel.rows ?? 0} snapshots · {funnel.flagged ?? 0} flagged
              {Object.keys(funnel).filter((k) => k in REASON).map((k) => ` · ${funnel[k]} ${REASON[k]}`).join("")}
            </p>
          </div>
          {mine(data.near_misses).length > 0 && (
            <div><h3 className="mb-1 text-xs font-medium text-slate-300">Near misses</h3><GapTable rows={mine(data.near_misses) as GapRow[]} showFailed /></div>
          )}
          {closed.length > 0 && (
            <div><h3 className="mb-1 text-xs font-medium text-slate-300">Closed paper trades</h3><PositionTable rows={closed} /></div>
          )}
        </div>
      </details>
    </section>
  );
}
