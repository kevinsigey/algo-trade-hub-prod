import { Link } from "react-router-dom";
import { useEffect, useState } from "react";

import { adminJson } from "@/lib/workshop";
import { ArrowRight, Loader2 } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, Treemap, XAxis, YAxis } from "recharts";

import StrategyHqStrip from "@/components/StrategyHqStrip";
import { useApi } from "@/hooks/usePaperPortfolio";
import {
  fmtPct,
  fmtPts,
  fmtUsd,
  stateLabel,
  tone,
  type PortfolioPayload,
  type PositionRow,
} from "@/lib/paperPortfolio";

function Big({ label, value, className = "text-white" }: { label: string; value: string; className?: string }) {
  return (
    <div className="min-w-[9rem]">
      <div className="text-sm text-slate-400">{label}</div>
      <div className={`mt-1 text-4xl font-semibold tabular-nums tracking-tight ${className}`}>{value}</div>
    </div>
  );
}

function Small({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex-1 rounded-lg border border-slate-800 px-4 py-3">
      <div className="text-xs text-slate-400">{label}</div>
      <div className="mt-0.5 text-xl font-semibold tabular-nums text-white">{value}</div>
    </div>
  );
}

const BLOCK_COLORS = ["#10b981", "#38bdf8", "#f59e0b", "#a78bfa", "#f43f5e", "#14b8a6", "#eab308"];

function Block(props: { x?: number; y?: number; width?: number; height?: number; index?: number; name?: string; pct?: number }) {
  const { x = 0, y = 0, width = 0, height = 0, index = 0, name, pct } = props;
  const color = name === "Cash" ? "#475569" : BLOCK_COLORS[index % BLOCK_COLORS.length];
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={color} fillOpacity={0.35} stroke="#020617" strokeWidth={2} />
      {width > 56 && height > 28 && (
        <text x={x + 8} y={y + 20} fill="#f8fafc" fontSize={13} fontWeight={600}>
          {name} {pct != null ? `${pct.toFixed(0)}%` : ""}
        </text>
      )}
    </g>
  );
}

function PositionsTable({ rows }: { rows: PositionRow[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[36rem] text-sm tabular-nums">
        <thead className="text-left text-slate-400">
          <tr>
            <th className="py-2 pr-4 font-medium">Holding</th>
            <th className="py-2 pr-4 text-right font-medium">Shares</th>
            <th className="py-2 pr-4 text-right font-medium">Value</th>
            <th className="py-2 pr-4 text-right font-medium">% of book</th>
            <th className="py-2 pr-4 text-right font-medium">P&amp;L</th>
            <th className="py-2 font-medium">From idea</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.symbol} className="border-t border-slate-800/80">
              <td className="py-2 pr-4 font-semibold text-white">{r.symbol}</td>
              <td className="py-2 pr-4 text-right text-slate-300">{r.qty ?? ""}</td>
              <td className="py-2 pr-4 text-right text-slate-200">{fmtUsd(r.market_value, { whole: true })}</td>
              <td className="py-2 pr-4 text-right text-slate-300">{r.pct_of_book == null ? "—" : `${r.pct_of_book.toFixed(0)}%`}</td>
              <td className={`py-2 pr-4 text-right ${tone(r.unrealized_pl)}`}>
                {r.unrealized_pl == null ? "" : fmtUsd(r.unrealized_pl, { signed: true })}
              </td>
              <td className="py-2 text-slate-300">{r.idea ?? ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Portfolio() {
  const { data, error, loading } = useApi<PortfolioPayload>("/api/portfolio");
  const [liveIdeas, setLiveIdeas] = useState<{ id: number; title: string; size_pct: number | null }[]>([]);
  useEffect(() => {
    let cancelled = false;
    // Admin only: a signed-out visitor gets a 401 and simply sees no list.
    adminJson<{ id: number; title: string; size_pct: number | null; live_at: string | null; killed_at: string | null; auto_orders: boolean }[]>("/api/workshop/ideas")
      .then((rows) => {
        if (!cancelled) setLiveIdeas(rows.filter((r) => r.live_at && !r.killed_at && r.auto_orders));
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 md:px-8">
      <h1 className="text-2xl font-bold tracking-tight text-white">Portfolio</h1>
      <p className="mt-1 text-sm text-slate-400">A paper account, in full. Are we beating SPY?</p>

      <StrategyHqStrip />

      {loading && (
        <div className="mt-8 flex items-center gap-2 text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Reading the account…
        </div>
      )}
      {error && <p className="mt-8 text-rose-300">Could not read the portfolio: {error}</p>}

      {data && data.state === "not_connected" && (
        <div className="mt-8 rounded-xl border border-slate-800 p-6">
          <div className="text-xl font-semibold text-white">Paper account not connected</div>
          <p className="mt-1 max-w-prose text-sm text-slate-400">
            The paper trading account is not linked yet. Numbers appear here from its first snapshot, never before.
          </p>
        </div>
      )}

      {data && data.state !== "not_connected" && data.scoreboard && <Body data={data} liveIdeas={liveIdeas} />}
    </div>
  );
}

function Body({ data, liveIdeas }: { data: PortfolioPayload; liveIdeas: { id: number; title: string; size_pct: number | null }[] }) {
  const s = data.scoreboard;
  const holdings = data.positions.map((p) => ({ name: p.symbol, size: Math.abs(p.market_value), pct: p.pct_of_book }));
  const count = data.positions.filter((p) => p.symbol !== "Cash").length;

  return (
    <>
      <section className="mt-8">
        <div className="flex flex-wrap gap-x-10 gap-y-4">
          <Big label="Account" value={fmtUsd(s.equity, { whole: true })} />
          <Big label="Since start" value={fmtPct(s.return_pct)} className={tone(s.return_pct)} />
          <Big label="SPY same period" value={fmtPct(s.spy_return_pct)} />
          <Big label="Ahead of SPY" value={fmtPts(s.ahead_pts)} className={tone(s.ahead_pts)} />
        </div>
        <p className={`mt-3 text-xs ${data.state === "live" ? "text-emerald-300" : "text-amber-300"}`}>
          {stateLabel(data.state, data.as_of)}
        </p>

        {data.curve.length > 1 ? (
          <div className="mt-6 h-56" aria-label="Portfolio vs SPY since start">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data.curve} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <XAxis dataKey="t" hide />
                <YAxis tickFormatter={(v: number) => `${v.toFixed(0)}%`} stroke="#64748b" fontSize={11} width={40} />
                <Tooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #1e293b" }}
                  formatter={(v: number, name: string) => [fmtPct(v), name === "portfolio_pct" ? "Portfolio" : "SPY"]}
                  labelFormatter={(t: string) => new Date(t).toLocaleString()}
                />
                <Line type="monotone" dataKey="portfolio_pct" stroke="#34d399" strokeWidth={2.5} dot={false} />
                <Line type="monotone" dataKey="spy_pct" stroke="#94a3b8" strokeWidth={2} strokeDasharray="4 3" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="mt-6 text-sm text-slate-400">The curve starts after the second snapshot.</p>
        )}

        <div className="mt-4 flex flex-wrap gap-3">
          <Small label="Max drawdown" value={fmtPct(s.max_drawdown_pct)} />
          <Small label="Sharpe" value={s.sharpe == null ? "—" : s.sharpe.toFixed(2)} />
          <Small label="Win rate" value={s.win_rate == null ? "—" : `${s.win_rate.toFixed(0)}%`} />
        </div>
      </section>

      <section className="mt-12">
        <h2 className="text-lg font-semibold text-white">What we own, and which idea put it there</h2>
        <div className="mt-4 flex flex-col gap-6 md:flex-row">
          <div className="h-48 md:flex-[1.4]">
            <ResponsiveContainer width="100%" height="100%">
              <Treemap data={holdings} dataKey="size" isAnimationActive={false} content={<Block />} />
            </ResponsiveContainer>
          </div>
          <ul className="space-y-2 md:flex-1">
            {data.composition.map((c) => (
              <li key={c.idea} className="flex items-baseline justify-between gap-3 rounded-lg border border-slate-800 px-4 py-2.5 text-sm">
                <span className="text-slate-200">{c.idea}</span>
                <span className="tabular-nums text-slate-400">
                  {c.pct_of_book.toFixed(0)}% · <span className={tone(c.unrealized_pl)}>{fmtUsd(c.unrealized_pl, { signed: true })}</span>
                </span>
              </li>
            ))}
            {data.composition.length === 0 && <li className="text-sm text-slate-400">All cash.</li>}
          </ul>
        </div>
      </section>

      {liveIdeas.length > 0 && (
        <section className="mt-12">
          <div className="flex items-baseline justify-between gap-2">
            <h2 className="text-lg font-semibold text-white">Ideas trading on this account</h2>
            <Link to="/workshop" className="text-sm text-emerald-300 hover:text-emerald-200">Workshop →</Link>
          </div>
          <ul className="mt-3 space-y-2">
            {liveIdeas.map((idea) => (
              <li key={idea.id} className="flex items-baseline justify-between gap-3 rounded-lg border border-slate-800 px-4 py-2.5 text-sm">
                <Link to={`/workshop/${idea.id}`} className="text-slate-200 hover:text-emerald-300">{idea.title}</Link>
                <span className="tabular-nums text-slate-400">{idea.size_pct ?? "—"}%</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="mt-12">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-lg font-semibold text-white">Every position · {count}</h2>
          <Link to="/portfolio/closed" className="inline-flex items-center gap-1 text-sm text-emerald-300 hover:text-emerald-200">
            Closed trades <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Link>
        </div>
        <div className="mt-3">
          <PositionsTable rows={data.positions} />
        </div>
      </section>

      <OrderForm />
    </>
  );
}

const inputCls = "rounded-md border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-white";
const labelCls = "flex flex-col gap-1 text-xs text-slate-400";

function OrderForm() {
  const [signedIn, setSignedIn] = useState(false);
  const [ideas, setIdeas] = useState<{ id: number; title: string }[]>([]);
  const [symbol, setSymbol] = useState("");
  const [qty, setQty] = useState("1");
  const [side, setSide] = useState("buy");
  const [orderType, setOrderType] = useState("market");
  const [limitPrice, setLimitPrice] = useState("");
  const [tif, setTif] = useState("day");
  const [ideaId, setIdeaId] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Signed-in only: /api/admin/me 401s for a visitor, and the form simply never appears.
    adminJson<{ email: string }>("/api/admin/me")
      .then(() => {
        if (cancelled) return;
        setSignedIn(true);
        adminJson<{ id: number; title: string }[]>("/api/workshop/ideas")
          .then((rows) => { if (!cancelled) setIdeas(rows); })
          .catch(() => undefined);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  if (!signedIn) return null;

  async function place() {
    setBusy(true);
    setNote(null);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        symbol: symbol.trim().toUpperCase(), qty: Number(qty), side, order_type: orderType, time_in_force: tif,
      };
      if (orderType === "limit") body.limit_price = Number(limitPrice);
      if (ideaId) body.idea_id = Number(ideaId);
      const placed = await adminJson<{ client_order_id: string }>("/api/portfolio/orders", {
        method: "POST", body: JSON.stringify(body),
      });
      setNote(`Order sent: ${side} ${qty} ${body.symbol as string} (${placed.client_order_id})`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Order failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-12">
      <h2 className="text-lg font-semibold text-white">Place an order by hand</h2>
      <p className="mt-1 text-sm text-slate-400">
        Paper account, market or limit. Tag it with an idea and it lands in that idea&apos;s order log.
      </p>
      <div className="mt-4 flex flex-wrap items-end gap-3">
        <label className={labelCls}>Symbol
          <input aria-label="Symbol" className={inputCls} value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="XLE" />
        </label>
        <label className={labelCls}>Shares
          <input aria-label="Shares" className={`${inputCls} w-24`} type="number" min={1} value={qty} onChange={(e) => setQty(e.target.value)} />
        </label>
        <label className={labelCls}>Side
          <select aria-label="Side" className={inputCls} value={side} onChange={(e) => setSide(e.target.value)}>
            <option value="buy">Buy</option>
            <option value="sell">Sell</option>
          </select>
        </label>
        <label className={labelCls}>Type
          <select aria-label="Type" className={inputCls} value={orderType} onChange={(e) => setOrderType(e.target.value)}>
            <option value="market">Market</option>
            <option value="limit">Limit</option>
          </select>
        </label>
        {orderType === "limit" && (
          <label className={labelCls}>Limit price
            <input aria-label="Limit price" className={`${inputCls} w-28`} type="number" min={0} step="0.01" value={limitPrice} onChange={(e) => setLimitPrice(e.target.value)} />
          </label>
        )}
        <label className={labelCls}>Time in force
          <select aria-label="Time in force" className={inputCls} value={tif} onChange={(e) => setTif(e.target.value)}>
            <option value="day">Day</option>
            <option value="opg">At the open</option>
            <option value="cls">At the close</option>
          </select>
        </label>
        <label className={labelCls}>Idea (optional)
          <select aria-label="Idea" className={inputCls} value={ideaId} onChange={(e) => setIdeaId(e.target.value)}>
            <option value="">No idea</option>
            {ideas.map((i) => <option key={i.id} value={i.id}>{i.title}</option>)}
          </select>
        </label>
        <button type="button" disabled={busy || !symbol.trim()} onClick={place}
          className="rounded-md bg-emerald-600 px-4 py-1.5 text-sm font-semibold text-white disabled:opacity-40">
          {busy ? "Sending…" : "Place order"}
        </button>
      </div>
      {note && <p className="mt-3 text-sm text-emerald-300">{note}</p>}
      {error && <p className="mt-3 text-sm text-rose-300">{error}</p>}
    </section>
  );
}
