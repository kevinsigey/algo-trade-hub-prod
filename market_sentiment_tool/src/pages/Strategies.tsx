import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, ChevronDown } from "lucide-react";

import { FullView } from "@/components/Panel";
import { DashCard, MiniBars, PEEK, PeekRows, Spark } from "@/pages/portfolio/shared";

import { FifteenDeclineMonitor, type DeclineRow } from "@/components/FifteenDeclineMonitor";
import { FifteenSettlements } from "@/components/FifteenSettlements";
import { SniperRecord } from "@/components/SniperRecord";
import { StrikeRecordLine } from "@/components/StrikeRecordLine";
import { sessionToken } from "@/components/RequireAdmin";
import { TradesView } from "@/pages/KalshiLiveBook";
import { GET_JSON_TIMEOUT_MS, getJson } from "@/lib/getJson";
import type { KalshiDemoPayload } from "@/lib/kalshiDemo";

/** One read per endpoint; a failed read stays null and its tile says the record is unavailable. */
function useJson<T>(url: string): T | null {
  const [data, setData] = useState<T | null>(null);
  useEffect(() => {
    let stop = false;
    getJson<T>(url).then((d) => { if (!stop) setData(d); }).catch(() => undefined);
    return () => { stop = true; };
  }, [url]);
  return data;
}

type Stage = "Live paper account" | "Paper record" | "Picks only" | "Retired" | "Paused";
const STAGE_TONE: Record<Stage, string> = {
  "Live paper account": "border-emerald-500/50 text-emerald-300",
  "Paper record": "border-sky-500/50 text-sky-300",
  "Picks only": "border-slate-600 text-slate-300",
  Retired: "border-slate-700 text-slate-500",
  Paused: "border-amber-500/50 text-amber-300",
};

const signed = (v: number, digits = 1) => `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(digits)}`;
const cent1 = (v: number) => `${signed(v * 100)}¢`;
const cents = (v: number) => `${cent1(v)} a contract`;
const pts1 = (v: number) => `${signed(v * 100)} pts`;
const usd = (v: number) => `${v >= 0 ? "+" : "−"}$${Math.abs(v).toFixed(2)}`;
const usdPlain = (v: number) => `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const toneOf = (v: number | null | undefined) => (v == null ? undefined : v >= 0 ? "text-emerald-300" : "text-rose-300");

interface GapCategoryLedger { closed: number; realized: number; win_rate: number | null; median_pnl: number | null }
interface GapPosition { ticker: string; category: string; side: string; model_at_entry: number;
                        entry_price: number; gap_pts: number; contracts: number;
                        exit_state: string | null; exit_reason?: string | null; pnl?: number | null;
                        settles_at?: string }
/** How a gap position ended, in the order the post-mortem reads them. */
const GAP_EXIT_LABELS: [string, string][] = [
  ["gap_closed", "Gap closed"], ["model_moved", "Model moved"],
  ["near_settlement", "Under an hour left"], ["settlement", "Held to settlement"],
];
const gapExitLabel = (reason: string | null | undefined): string =>
  GAP_EXIT_LABELS.find(([k]) => k === reason)?.[1] ?? (reason ? reason.replace(/_/g, " ") : "—");
interface SeriesStats { n: number; net_per_contract: number | null; win_rate: number | null;
                        total?: number; low95?: number | null; windows?: number }
interface FifteenTrade { series: string; target: string; frozen_at: string; side: "yes" | "no";
                         cost: number; model: number; outcome: number; pnl: number }
interface OffsetStat { offset_min: number; windows: number; priced: number; mean_edge_net: number | null;
                       n: number; net_per_contract: number | null; win_rate: number | null }
interface FifteenPayload {
  prereg_at?: string; ready_trades?: number;
  forward?: SeriesStats; replay?: SeriesStats; pending?: number; recent?: FifteenTrade[];
  by_series?: Record<string, SeriesStats>;
  by_session?: { open: SeriesStats; closed: SeriesStats };
  gate?: { forward?: SeriesStats; by_series?: Record<string, SeriesStats> };
  bar?: { basis: string; trades: number; ready_trades: number; ready: boolean; low95: number | null; windows?: number; pending?: number };
  decisions?: { recorded: number; buy: number; skip: number; by_reason: Record<string, number> };
  offsets?: { by_offset: OffsetStat[] };
  // Per ET day and market, all six series: live rule, blend, vol-regime challenger.
  decline?: DeclineRow[];
  volregime?: { fresh?: { trades: number; net_per_contract: number | null; low95: number | null; clustered_low95: number | null };
                paired?: { windows: number; delta_per_window: number | null; low95: number | null; clustered_low95: number | null } };
  // The metals family (2026-11-09 preregistration): its own record block in
  // the same shape, counted entirely apart from the oil family's above.
  metals?: { prereg_at?: string; ready_trades?: number;
             by_series?: Record<string, SeriesStats>;
             gate?: { forward?: SeriesStats; by_series?: Record<string, SeriesStats> } };
  // The redesign board (2026-11-19): the fifteen family grouped by
  // commodity, every model ranked, a simulated account under each.
  board?: { commodities: BoardCard[]; account_start: number };
}

interface BoardAccount { start: number; balance: number; drawdown: number; bust: boolean;
                         curve: number[]; trades_taken: number }
interface BoardModel { version: string; label: string; series: string; trades: number;
                       net_cents: number | null; low95: number | null; paired_low95: number | null;
                       fill_short: number; too_few: boolean; weight?: number;
                       progress: { n: number; needed: number;
                                   legs: { n: boolean; low95: boolean; paired: boolean } };
                       account: BoardAccount }
interface BoardCard { series: string; commodity: string; models: BoardModel[] }

const REASON_LABELS: [string, string][] = [
  ["no_edge", "no edge"], ["no_quote", "no quote"], ["no_prediction", "no prediction"],
  ["stale_tape", "stale tape"], ["halt", "halt"],
];

function etShort(iso: string): string {
  return new Date(iso).toLocaleString("en-US", { timeZone: "America/New_York", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/** A diverging bar for a signed value: fills right of centre when positive, left when negative. */
function SignedBar({ value, maxAbs, thin = false }: { value: number | null; maxAbs: number; thin?: boolean }) {
  const w = value == null ? 0 : Math.min(50, (Math.abs(value) / Math.max(maxAbs, 1e-9)) * 50);
  return (
    <div className={`relative ${thin ? "h-1.5" : "h-2.5"} min-w-0 flex-1 overflow-hidden rounded-sm bg-slate-800`} aria-hidden="true">
      <div className="absolute inset-y-0 left-1/2 w-px bg-slate-600" />
      {value != null && w > 0 && (
        <div
          className={`absolute inset-y-0 ${value >= 0 ? "bg-emerald-400/80" : "bg-rose-400/80"}`}
          style={value >= 0 ? { left: "50%", width: `${w}%` } : { right: "50%", width: `${w}%` }}
        />
      )}
    </div>
  );
}

/** A 0–1 share as a filled proportion bar (hit rates, hits of settled). */
function ShareBar({ share, tone = "bg-sky-400/80" }: { share: number | null; tone?: string }) {
  return (
    <div className="h-2.5 min-w-0 flex-1 overflow-hidden rounded-sm bg-slate-800" aria-hidden="true">
      {share != null && <div className={`h-full ${tone}`} style={{ width: `${Math.max(0, Math.min(100, share * 100))}%` }} />}
    </div>
  );
}

/** Book vs SPY since inception, from the portfolio payload's own curve. No axis words — the legend is two chips. */
function CurveSpark({ curve, height = "h-16" }: { curve: { portfolio_pct: number; spy_pct: number }[]; height?: string }) {
  if (curve.length < 2) return null;
  const vals = curve.flatMap((p) => [p.portfolio_pct, p.spy_pct]);
  const min = Math.min(...vals, 0), max = Math.max(...vals, 0);
  const span = max - min || 1;
  const line = (key: "portfolio_pct" | "spy_pct") =>
    curve.map((p, i) => `${((i / (curve.length - 1)) * 100).toFixed(1)},${(30 - ((p[key] - min) / span) * 28 - 1).toFixed(1)}`).join(" ");
  const zeroY = 30 - ((0 - min) / span) * 28 - 1;
  return (
    <div>
      <svg viewBox="0 0 100 32" preserveAspectRatio="none" className={`${height} w-full`} role="img" aria-label="Portfolio curve against SPY">
        <line x1="0" x2="100" y1={zeroY} y2={zeroY} stroke="#334155" strokeWidth="0.5" />
        <polyline points={line("spy_pct")} fill="none" stroke="#64748b" strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
        <polyline points={line("portfolio_pct")} fill="none" stroke="#34d399" strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="mt-1 flex gap-3 text-[11px] text-slate-400">
        <span className="inline-flex items-center gap-1"><span className="h-1.5 w-3 rounded bg-emerald-400" /> Book</span>
        <span className="inline-flex items-center gap-1"><span className="h-1.5 w-3 rounded bg-slate-500" /> SPY</span>
      </div>
    </div>
  );
}

type WhereCell = { n: number; cents: number; low95: number | null } | null;
type WherePayload = {
  label?: string; generated_at?: string; sample_note?: string;
  data_so_far?: { source: string; series: string; settled_windows: number; days: number; trades: number }[];
  views?: { all?: {
    features?: { minute?: { bucket: string; cells: Record<string, Record<string, WhereCell>> }[] };
    paired_vs_5?: { minute: number; series: string; source: string; n_windows: number; cents: number; low95: number | null }[];
  } };
};

/** Step A study block: where the 15-minute models work, forward and
 * replay side by side (never pooled together). Renders nothing until
 * the study runner has written its report. */
function FifteenWhereBlock() {
  const where = useJson<WherePayload>("/api/oil/fifteen-where");
  const all = where?.views?.all;
  if (!where || !all || !(where.data_so_far ?? []).length) return null;
  const minutes = (all.features?.minute ?? []).map((r) => ({
    bucket: r.bucket, forward: r.cells?.POOLED?.forward ?? null, replay: r.cells?.POOLED?.replay ?? null,
  }));
  const paired = (all.paired_vs_5 ?? []).filter((p) => p.series === "POOLED");
  const cellText = (c: WhereCell) => (c ? `${c.cents.toFixed(1)}¢ (${c.n})` : "—");
  return (
    <SubDetails title="Where the models work — Step A study (in-sample)">
      <p className="text-xs text-slate-400">
        Net cents per trade after the fee, forward record and history replay side by side, cells under
        30 trades blanked. {where.sample_note ?? ""}
      </p>
      <p className="mt-1 text-xs tabular-nums text-slate-500">
        {(where.data_so_far ?? []).map((d) =>
          `${d.source} ${d.series.replace("KX", "").replace("15M", "")}: ${d.settled_windows} windows / ${d.days} days / ${d.trades} trades`).join(" · ")}
      </p>
      {paired.length > 0 && (
        <table aria-label="Paired entry minute versus minute 5" className="mt-3 w-full max-w-xl text-xs tabular-nums">
          <thead><tr className="text-left text-slate-500">
            <th className="pb-1 pr-3 font-medium">Minute vs 5</th>
            <th className="pb-1 pr-3 font-medium text-right">Forward ¢/window</th>
            <th className="pb-1 pr-3 font-medium text-right">low95</th>
            <th className="pb-1 pr-3 font-medium text-right">Replay ¢/window</th>
            <th className="pb-1 font-medium text-right">low95</th>
          </tr></thead>
          <tbody className="divide-y divide-slate-800/70 text-slate-300">
            {paired.filter((p) => p.source === "forward").map((f) => {
              const r = paired.find((p) => p.source === "replay" && p.minute === f.minute);
              return (
                <tr key={f.minute}>
                  <td className="py-1 pr-3">{f.minute}</td>
                  <td className="py-1 pr-3 text-right">{f.cents.toFixed(1)} ({f.n_windows})</td>
                  <td className="py-1 pr-3 text-right">{f.low95 == null ? "—" : f.low95.toFixed(1)}</td>
                  <td className="py-1 pr-3 text-right">{r ? `${r.cents.toFixed(1)} (${r.n_windows})` : "—"}</td>
                  <td className="py-1 text-right">{r?.low95 == null ? "—" : r.low95.toFixed(1)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {minutes.length > 0 && (
        <table aria-label="Per-minute record by source" className="mt-3 w-full max-w-xl text-xs tabular-nums">
          <thead><tr className="text-left text-slate-500">
            <th className="pb-1 pr-3 font-medium">Entry minute</th>
            <th className="pb-1 pr-3 font-medium text-right">Forward ¢/trade (n)</th>
            <th className="pb-1 font-medium text-right">Replay ¢/trade (n)</th>
          </tr></thead>
          <tbody className="divide-y divide-slate-800/70 text-slate-300">
            {minutes.map((m) => (
              <tr key={m.bucket}>
                <td className="py-1 pr-3">{m.bucket}</td>
                <td className="py-1 pr-3 text-right">{cellText(m.forward)}</td>
                <td className="py-1 text-right">{cellText(m.replay)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </SubDetails>
  );
}

/** The simulated account's balance curve as a small sparkline. */
function Sparkline({ curve }: { curve: number[] }) {
  if (curve.length < 2) return null;
  const min = Math.min(...curve), max = Math.max(...curve), span = Math.max(max - min, 1e-9);
  const pts = curve.map((v, i) => `${(i / (curve.length - 1)) * 118 + 1},${26 - ((v - min) / span) * 24}`).join(" ");
  const up = curve[curve.length - 1] >= curve[0];
  return (
    <svg width="120" height="28" className="shrink-0" aria-hidden="true">
      <polyline points={pts} fill="none" strokeWidth="1.5"
                className={up ? "stroke-emerald-400/80" : "stroke-rose-400/80"} />
    </svg>
  );
}

/** One model on a commodity card: its record, its promotion progress,
 * and the simulated account below. */
function BoardModelRow({ m }: { m: BoardModel }) {
  const leg = (ok: boolean, name: string) => (
    <span className={ok ? "text-emerald-300" : "text-slate-500"}>{name} {ok ? "✓" : "✗"}</span>
  );
  const pct = Math.min(100, (m.progress.n / Math.max(m.progress.needed, 1)) * 100);
  return (
    <div className={`border-t border-slate-800/70 py-2 ${m.too_few ? "opacity-70" : ""}`}>
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-0.5 text-xs tabular-nums">
        <span className="text-sm font-medium text-slate-100">{m.label === m.version ? m.version : m.label}</span>
        {m.label !== m.version && <span className="text-slate-500">{m.version}</span>}
        {m.weight != null && <span className="text-slate-400">weight {m.weight.toFixed(2)}</span>}
        {m.too_few && <span className="rounded border border-slate-700 px-1 text-slate-400">too few trades</span>}
        <span className="text-slate-300">{m.trades} trades</span>
        <span className={toneOf(m.net_cents)}>{m.net_cents == null ? "—" : `${signed(m.net_cents)}¢`} a contract</span>
        <span className="text-slate-400">low95 {m.low95 == null ? "—" : `${signed(m.low95)}¢`}</span>
        <span className="text-slate-400">paired vs live {m.paired_low95 == null ? "—" : `${signed(m.paired_low95)}¢`}</span>
        <span className="text-slate-400">fill-short {m.fill_short}</span>
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-slate-400">
        <div className="h-1.5 w-36 rounded-full bg-slate-800" role="img"
             aria-label={`${m.progress.n} of ${m.progress.needed} trades toward the promotion bar`}>
          <div className="h-full rounded-full bg-sky-400/70" style={{ width: `${pct}%` }} />
        </div>
        <span>{m.progress.n}/{m.progress.needed}</span>
        {leg(m.progress.legs.n, "trades")}
        {leg(m.progress.legs.low95, "low95")}
        {leg(m.progress.legs.paired, "paired (display only)")}
      </div>
      <div className="mt-1 flex flex-wrap items-center gap-x-4 text-xs tabular-nums text-slate-400">
        <span>Simulated account: <span className={toneOf(m.account.balance - m.account.start)}>{usdPlain(m.account.balance)}</span>
          {" "}from {usdPlain(m.account.start)} · drawdown {usdPlain(m.account.drawdown)}
          {m.account.bust && <span className="ml-1 rounded border border-rose-500/50 px-1 text-rose-300">bust</span>}
        </span>
        <Sparkline curve={m.account.curve} />
      </div>
    </div>
  );
}

/** The redesign board: one wide card per commodity, its models ranked
 * best to worst, cards ordered by their best proven model. */
function FifteenBoard({ board }: { board: NonNullable<FifteenPayload["board"]> }) {
  if (!board.commodities?.length) return null;
  return (
    <div className="space-y-4">
      <p className="text-xs text-slate-400">
        Every model scored on each market, ranked by fresh net cents a contract; models under 10 trades
        sit last. The simulated account starts at $20 and stakes 10% of its balance a trade, capped at
        the depth on offer where the tape measured it; it stops when it cannot buy one contract.
        Fees on multi-contract trades are approximate. The board's paired check is display-only —
        the promotion leg pairs on the offset-5 row.
      </p>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {board.commodities.map((card) => (
          <section key={card.series} aria-label={`${card.commodity} models`}
                   className="rounded-md border border-slate-800 px-3 py-2">
            <h4 className="text-sm font-semibold text-slate-100">{card.commodity}</h4>
            {card.models.map((m) => <BoardModelRow key={m.version} m={m} />)}
          </section>
        ))}
      </div>
    </div>
  );
}

/** One market's gated-vs-raw bars for a fifteen tile: gated leads (it is the live rule), raw is the control. */
function SeriesBars({ labels, fifteen, lines }: {
  labels: string[]; fifteen: FifteenPayload | null;
  lines: Record<string, { record: string | null; tone?: string }>;
}) {
  const present = labels.filter((l) => fifteen?.gate?.by_series?.[l] || fifteen?.by_series?.[l]);
  if (!fifteen || present.length === 0) return null;
  const maxAbs = Math.max(0.01, ...present.flatMap((l) => [
    Math.abs(fifteen.gate?.by_series?.[l]?.net_per_contract ?? 0),
    Math.abs(fifteen.by_series?.[l]?.net_per_contract ?? 0),
  ]));
  return (
    <div className="space-y-3">
      {present.map((label) => {
        const g = fifteen.gate?.by_series?.[label];
        const r = fifteen.by_series?.[label];
        return (
          <div key={label}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="text-xs font-semibold text-slate-200">{label}</span>
              <span className="text-[11px] tabular-nums text-slate-400">
                {g && g.n > 0 ? `${g.n} gated` : "0 gated"}{r ? ` · ${r.n} raw` : ""}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2">
              <span className="w-9 shrink-0 text-[10px] uppercase tracking-wide text-slate-500">Gated</span>
              <SignedBar value={g?.net_per_contract ?? null} maxAbs={maxAbs} />
              <span className={`w-16 shrink-0 text-right text-xs tabular-nums ${toneOf(g?.net_per_contract) ?? "text-slate-400"}`}>
                {g?.net_per_contract == null ? "—" : `${signed(g.net_per_contract * 100)}¢`}
              </span>
            </div>
            <div className="mt-1 flex items-center gap-2">
              <span className="w-9 shrink-0 text-[10px] uppercase tracking-wide text-slate-500">Raw</span>
              <SignedBar value={r?.net_per_contract ?? null} maxAbs={maxAbs} thin />
              <span className={`w-16 shrink-0 text-right text-xs tabular-nums ${toneOf(r?.net_per_contract) ?? "text-slate-400"}`}>
                {r?.net_per_contract == null ? "—" : `${signed(r.net_per_contract * 100)}¢`}
              </span>
            </div>
            <p className={`mt-1 text-xs font-medium tabular-nums ${lines[label]?.tone ?? "text-slate-300"}`}>
              {lines[label]?.record ?? <span className="text-slate-500">Record unavailable</span>}
            </p>
          </div>
        );
      })}
    </div>
  );
}

interface TileSpec {
  id: string; name: string; stage: Stage; chipLabel?: string; muted?: boolean; defaultOpen?: boolean;
  /** The plain read where the strategy has a gate: true proven, false not yet; omitted when it has none. */
  proven?: boolean;
  visual: ReactNode; stats: ReactNode; children: ReactNode;
  /** A live model's dashboard card: headline, quick stats, its always-open graph. Its detail is visual + stats + children. */
  card?: { value: ReactNode; valueClass?: string; sub: ReactNode; graph: ReactNode; hint?: string };
}

/** The tile's one chip: the proven read where it has a gate, else its stage. */
function TileChip({ spec }: { spec: TileSpec }) {
  if (spec.proven != null) {
    return <span className={`hidden rounded-full border px-1.5 py-0.5 text-[10px] font-medium sm:inline ${spec.proven ? "border-emerald-500/50 text-emerald-300" : "border-slate-600 text-slate-400"}`}>{spec.proven ? "Proven" : "Not proven yet"}</span>;
  }
  return <span className={`hidden rounded-full border px-1.5 py-0.5 text-[10px] font-medium sm:inline ${STAGE_TONE[spec.stage]}`}>{spec.chipLabel ?? spec.stage}</span>;
}

/** A live model as a dashboard card; the click opens every word the old tile held. */
function LiveCard({ spec }: { spec: TileSpec & { card: NonNullable<TileSpec["card"]> } }) {
  return (
    <DashCard title={spec.name} meta={<TileChip spec={spec} />} value={spec.card.value} valueClass={spec.card.valueClass}
              sub={<span className="hidden sm:inline">{spec.card.sub}</span>} hint={spec.card.hint}
              detail={<div id={spec.id} className="space-y-4"><p className="text-xs tabular-nums text-slate-400 sm:hidden">{spec.card.sub}</p>{spec.visual}{spec.stats}{spec.children}</div>}>
      {spec.card.graph}
    </DashCard>
  );
}

/** One strategy tile: visual + headline numbers at rest; every word of explanation lives in the expansion. */
function Tile({ spec }: { spec: TileSpec }) {
  return (
    <li id={spec.id} className={`scroll-mt-6 rounded-xl border border-slate-800 bg-slate-900/50 ${spec.muted ? "opacity-70" : ""}`}>
      <details className="group" open={spec.defaultOpen || undefined}>
        <summary className="cursor-pointer list-none p-4 [&::-webkit-details-marker]:hidden">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-semibold text-white">{spec.name}</span>
            <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${STAGE_TONE[spec.stage]}`}>{spec.chipLabel ?? spec.stage}</span>
            {spec.proven != null && (
              <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${spec.proven ? "border-emerald-500/50 text-emerald-300" : "border-slate-600 text-slate-400"}`}>
                {spec.proven ? "Proven" : "Not proven yet"}
              </span>
            )}
            <span className="ml-auto inline-flex items-center gap-1 text-[11px] font-medium text-slate-400">
              Details <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" aria-hidden="true" />
            </span>
          </div>
          <div className="mt-3">{spec.visual}</div>
          <div className="mt-3">{spec.stats}</div>
        </summary>
        <div className="border-t border-slate-800 px-4 py-4">{spec.children}</div>
      </details>
    </li>
  );
}

/** One small titled expansion inside a tile — the split that replaced the single mega-dropdown. */
function SubDetails({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="group/sub border-t border-slate-800 py-3 first:border-t-0 first:pt-0 last:pb-0">
      <summary className="cursor-pointer list-none text-sm font-semibold text-slate-200 hover:text-white [&::-webkit-details-marker]:hidden">
        {title}
        <ChevronDown className="ml-1 inline h-3.5 w-3.5 text-slate-500 transition-transform group-open/sub:rotate-180" aria-hidden="true" />
      </summary>
      <div className="mt-2">{children}</div>
    </details>
  );
}

/** The gap tracker's positions as a closed book reads them: how each trade ended, or that it is still open. */
function GapPositionsTable({ rows, open = false }: { rows: GapPosition[]; open?: boolean }) {
  return (
    <div className="-mx-4 overflow-x-auto px-4">
      <table className="w-full min-w-[34rem] text-left text-xs tabular-nums">
        <thead className="text-slate-500">
          <tr>
            <th scope="col" className="py-1 pr-3 font-medium">Contract</th>
            <th scope="col" className="py-1 pr-3 font-medium">Desk</th>
            <th scope="col" className="py-1 pr-3 font-medium">Side</th>
            <th scope="col" className="py-1 pr-3 text-right font-medium">Contracts</th>
            <th scope="col" className="py-1 pr-3 text-right font-medium">Entry</th>
            <th scope="col" className="py-1 pr-3 text-right font-medium">Entry gap</th>
            <th scope="col" className="py-1 font-medium">{open ? "State" : "Result"}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((p) => (
            <tr key={p.ticker} className="border-t border-slate-800/80 text-slate-300">
              <td className="whitespace-nowrap py-1.5 pr-3 font-medium text-slate-100">{p.ticker}</td>
              <td className="py-1.5 pr-3 capitalize">{p.category}</td>
              <td className="py-1.5 pr-3">{p.side}</td>
              <td className="py-1.5 pr-3 text-right">{p.contracts}</td>
              <td className="py-1.5 pr-3 text-right">{Math.round(p.entry_price * 100)}¢</td>
              <td className="py-1.5 pr-3 text-right">{p.gap_pts.toFixed(1)} pts</td>
              <td className={`py-1.5 ${open ? "text-amber-300" : toneOf(p.pnl) ?? ""}`}>
                {open ? "open · resolving" : p.pnl == null ? "—" : `${usd(p.pnl)} · ${gapExitLabel(p.exit_reason).toLowerCase()}`}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A headline record line: the same composed string the glance list used to carry, kept whole. */
function RecordLine({ text, tone }: { text: string | null; tone?: string }) {
  return (
    <p className={`text-sm font-medium tabular-nums ${tone ?? "text-slate-200"}`}>
      {text ?? <span className="text-slate-500">Record unavailable</span>}
    </p>
  );
}

/** What we learned, newest first. Append a row here when a finding lands. */
const LEARNED: { date: string; text: string }[] = [
  { date: "2026-11-24", text: "Natural gas paused on the live pilot: the gas model reads the Hyperliquid perp while Kalshi settles on Pyth. Since Nov 10, 22 gas trades lost while the perp said they won, and 1 went the other way." },
  { date: "2026-11-24", text: "Oil trades that agreed with the last 15-minute move did better on held-out data (+10.8¢ vs +0.4¢ a contract). Now on trial as oil-trend-agree-v1." },
  { date: "2026-11-20", text: "The v2-oil shadow was killed." },
  { date: "2026-11-20", text: "Sports were removed from the hub." },
];

/** One line per 15-minute shadow version on the board; the rest come from /api/strategies/trials. */
const TRIAL_TESTS: Record<string, string> = {
  "v2-blend-shadow": "A self-weighting blend of the 15-minute models",
  "v3-volregime-shadow": "Trades only in the volatility regime that has paid",
  "v4-edge20-shadow": "The live rule with a 20¢ edge bar instead of 10¢",
  "v4-no-gold-shadow": "The live rule with gold left out",
  "v4-late-window-shadow": "Entering at minutes 11–13 instead of minute 5",
  "v4-per-commodity-shadow": "Each market at its own best minute and bar",
  "v4-side50-shadow": "Oil buys only on sides the model gives 50%+",
  "v4-spread3-shadow": "Oil buys only when the quote is 3¢+ wide",
  "oil-trend-agree-v1": "Oil trades only when they agree with the last 15-minute move",
  "oil-big-gap-v1": "Oil buys only when the model's gap is 15+ points",
  "v5-binance-gold-shadow": "Gold read off the Binance tape",
};

type TrialStatus = "recording" | "eligible" | "killed" | "no_read";
interface TrialRow { id: string; name: string; tests: string; n: number | null; needed: number; unit: string;
                     net: string | null; netTone?: string; low95: string | null; status: TrialStatus; note?: string | null;
                     /** 15-minute shadows: the version's model on each commodity card, and its lead market's simulated account. */
                     models?: { commodity: string; m: BoardModel }[]; curve?: number[] }
interface ServedTrial { id: string; name: string; tests: string; n: number | null; needed: number; unit: string;
                        score: number | null; score_label: string | null; status: TrialStatus; note: string | null }

const STATUS_TONE: Record<TrialStatus, string> = {
  recording: "border-sky-500/50 text-sky-300", eligible: "border-emerald-500/50 text-emerald-300",
  killed: "border-rose-500/50 text-rose-300", no_read: "border-slate-700 text-slate-500",
};

/** The board's per-market models folded to one row per shadow version: trades pooled,
 * progress and low95 from the market closest to its bar (the bar is per market). */
function boardTrials(board: FifteenPayload["board"]): TrialRow[] {
  const byVersion = new Map<string, { commodity: string; m: BoardModel }[]>();
  for (const card of board?.commodities ?? []) {
    for (const m of card.models) {
      if (m.version === "live") continue;
      byVersion.set(m.version, [...(byVersion.get(m.version) ?? []), { commodity: card.commodity, m }]);
    }
  }
  return [...byVersion.entries()].map(([version, models]) => {
    const ms = models.map((x) => x.m);
    const lead = [...ms].sort((a, b) => b.progress.n / b.progress.needed - a.progress.n / a.progress.needed)[0];
    const trades = ms.reduce((a, m) => a + m.trades, 0);
    const priced = ms.filter((m) => m.net_cents != null && m.trades > 0);
    const pn = priced.reduce((a, m) => a + m.trades, 0);
    const net = pn > 0 ? priced.reduce((a, m) => a + (m.net_cents ?? 0) * m.trades, 0) / pn : null;
    return {
      id: version, name: lead.label === version ? version : `${lead.label} · ${version}`,
      tests: TRIAL_TESTS[version] ?? "15-minute shadow", n: lead.progress.n, needed: lead.progress.needed,
      unit: ms.length > 1 ? `trades (best market; ${trades} across ${ms.length})` : "trades",
      net: net == null ? null : `${signed(net)}¢`, netTone: toneOf(net),
      low95: lead.low95 == null ? null : `${signed(lead.low95)}¢`,
      // The board carries no promotion verdict, so eligible needs every leg (n, low95, paired) on one market.
      status: ms.some((m) => m.progress.legs.n && m.progress.legs.low95 && m.progress.legs.paired) ? "eligible" : "recording",
      models, curve: lead.account.curve,
    };
  });
}

function servedTrial(t: ServedTrial): TrialRow {
  const score = t.score == null ? null
    : t.score_label === "pass rate" ? `${Math.round(t.score * 100)}%` : t.score.toFixed(2);
  return { id: t.id, name: t.name, tests: t.tests, n: t.n, needed: t.needed, unit: t.unit,
           net: score == null ? null : `${score} ${t.score_label ?? ""}`.trim(), low95: null,
           status: t.status, note: t.status === "no_read" ? "recording, no public read yet" : t.note };
}

/** True under Tailwind's `sm` (640px): phones get the compact page. */
function usePhone(): boolean {
  const q = typeof window !== "undefined" && window.matchMedia ? window.matchMedia("(max-width: 639px)") : null;
  const [phone, setPhone] = useState(!!q?.matches);
  useEffect(() => {
    if (!q) return;
    const on = () => setPhone(q.matches);
    q.addEventListener("change", on);
    return () => q.removeEventListener("change", on);
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  return phone;
}

const trialProgress = (r: TrialRow) => (r.n == null ? -1 : r.n / Math.max(r.needed, 1));

/** One shadow: the row (name, status, progress, net, low95) opens its full record in a box. */
function TrialItem({ r }: { r: TrialRow }) {
  const [open, setOpen] = useState(false);
  const pct = r.n == null ? 0 : Math.min(100, (r.n / Math.max(r.needed, 1)) * 100);
  const stats = (
    <>
      <span className="h-1.5 w-28 shrink-0 rounded-full bg-slate-800" role="img"
            aria-label={r.n == null ? "progress unknown" : `${r.n} of ${r.needed} toward the pass bar`}>
        <span className="block h-full rounded-full bg-sky-400/70" style={{ width: `${pct}%` }} />
      </span>
      <span className="text-slate-300">{r.n == null ? "—" : r.n} / {r.needed} <span className="hidden sm:inline">{r.unit}</span></span>
      {r.net && <span className={r.netTone ?? "text-slate-300"}>{r.net}</span>}
      {r.low95 && <span>low95 {r.low95}</span>}
      {r.note && <span className="text-slate-500">{r.note}</span>}
    </>
  );
  return (
    <li>
      <button type="button" onClick={() => setOpen(true)} aria-haspopup="dialog"
              className="block w-full px-3 py-1.5 text-left sm:px-4 sm:py-2 hover:bg-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400">
        <span className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs tabular-nums text-slate-400">
          <span className="text-sm font-semibold text-white">{r.name}</span>
          <span className={`rounded-full border px-2 py-0.5 text-[11px] font-medium ${STATUS_TONE[r.status]}`}>
            {r.status === "no_read" ? "recording" : r.status}
          </span>
          {stats}
          {r.curve && r.curve.length > 1 && <span className="ml-auto hidden sm:block"><Sparkline curve={r.curve} /></span>}
        </span>
        <span className="mt-0.5 hidden truncate text-xs text-slate-500 sm:block">{r.tests}</span>
      </button>
      {open && (
        <FullView title={r.name} onClose={() => setOpen(false)}>
          <p className="text-sm text-slate-300">{r.tests}</p>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs tabular-nums text-slate-400">{stats}</div>
          {(r.models ?? []).length > 0 && (
            <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
              {r.models!.map(({ commodity, m }) => (
                <section key={commodity} aria-label={`${commodity} record`} className="rounded-md border border-slate-800 px-3 py-2">
                  <h4 className="text-sm font-semibold text-slate-100">{commodity}</h4>
                  <BoardModelRow m={m} />
                </section>
              ))}
            </div>
          )}
        </FullView>
      )}
    </li>
  );
}

/** Every preregistered shadow, one row each. */
function TrialList({ rows, label = "Shadows on trial" }: { rows: TrialRow[]; label?: string }) {
  if (rows.length === 0) return <p className="text-sm text-slate-500">Trial records unavailable.</p>;
  return (
    <ul aria-label={label} className="divide-y divide-slate-800 overflow-hidden rounded-lg border border-slate-800 bg-slate-900/60">
      {rows.map((r) => <TrialItem key={r.id} r={r} />)}
    </ul>
  );
}

/** On trial: the PEEK shadows closest to their bar on the page; every one behind Show all. */
function OnTrial({ rows }: { rows: TrialRow[] }) {
  const [all, setAll] = useState(false);
  const peek = usePhone() ? 3 : PEEK;
  const ranked = [...rows].sort((a, b) => trialProgress(b) - trialProgress(a));
  return (
    <section aria-label="On trial" className="min-w-0 lg:col-span-2">
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h2 className="text-sm font-semibold text-white" title="Preregistered shadows: recorded, never traded, until they clear their bar.">On trial (shadows)</h2>
        {ranked.length > peek && (
          <button type="button" onClick={() => setAll(true)} aria-haspopup="dialog"
                  className="text-xs text-emerald-300 hover:text-emerald-200">Show all {ranked.length}</button>
        )}
      </div>
      <TrialList rows={ranked.slice(0, peek)} />
      {all && (
        <FullView title="On trial — every shadow" onClose={() => setAll(false)}>
          <TrialList rows={ranked} label="All shadows on trial" />
        </FullView>
      )}
    </section>
  );
}

const REAL_MONEY = <span className="rounded border border-rose-500/40 bg-rose-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-rose-300">REAL MONEY</span>;

/** The real-money pilot: admin sees the figures (the same admin read the Kalshi live book makes),
 * everyone else one line. */
function PilotCard() {
  const [pilot, setPilot] = useState<KalshiDemoPayload["live_pilot"]>(null);
  useEffect(() => {
    let stop = false;
    sessionToken()
      .then((token) => getJson<KalshiDemoPayload>("/api/kalshi-demo", GET_JSON_TIMEOUT_MS,
        token ? { Authorization: `Bearer ${token}` } : undefined))
      .then((d) => { if (!stop) setPilot(d.live_pilot ?? null); })
      .catch(() => undefined);
    return () => { stop = true; };
  }, []);
  const full = pilot && !("admin_only" in pilot) && pilot.state !== "unavailable" ? pilot : null;
  const cell = (label: string, value: string, cls = "text-white") => (
    <div><dt className="text-[11px] text-slate-500">{label}</dt><dd className={`text-sm font-semibold tabular-nums ${cls}`}>{value}</dd></div>
  );
  const money = (v: number | null | undefined) => (v == null ? "—" : usd(v));
  const status = full ? (full.halted ? `Halted — ${full.halt_reason ?? "halted"}` : full.state === "live" ? "Running" : "Not enabled") : null;
  // The settled orders' P&L, oldest first, summed: the pilot's cumulative record (admin only).
  let run = 0;
  const cum = (full?.orders ?? []).filter((o) => o.pnl != null)
    .sort((a, b) => String(a.window_close ?? a.created_at).localeCompare(String(b.window_close ?? b.created_at)))
    .map((o) => ({ pnl: (run += o.pnl ?? 0) }));
  const wins = (full?.orders ?? []).filter((o) => o.pnl != null && o.pnl > 0).length;
  const blurb = "A $10 live pilot runs the 15-minute oil rule on WTI & Brent with real money. Figures are admin-only.";
  const link = (
    <Link to="/portfolio?book=kalshi" className="relative z-10 inline-flex items-center gap-1 text-xs text-emerald-300 hover:text-emerald-200">
      Kalshi live book <ArrowRight className="h-3 w-3" aria-hidden="true" />
    </Link>
  );
  return (
    <DashCard title="Kalshi live" meta={REAL_MONEY} className="border-rose-500/30"
              value={full ? (full.balance == null ? "—" : usdPlain(full.balance)) : "Admin only"}
              valueClass={full ? "text-white" : "text-slate-400"}
              sub={full ? <><span className={toneOf(full.pnl_since_start)}>{money(full.pnl_since_start)}</span> since start · <span className={full.halted ? "text-rose-300" : undefined}>{status}</span></> : <span className="hidden sm:inline">{blurb}</span>}
              hint="The 15-minute oil rule on WTI & Brent, live on a real Kalshi account. Open for every trade and its P&L."
              detail={
                <div className="space-y-3">
                  {full ? (
                    <>
                      <p className={`text-sm font-medium ${full.halted ? "text-rose-300" : "text-slate-400"}`}>{status}</p>
                      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                        {cell("Balance", full.balance == null ? "—" : usdPlain(full.balance))}
                        {cell("P&L since start", money(full.pnl_since_start), toneOf(full.pnl_since_start))}
                        {cell("Fills", `${full.fills} of ${full.decisions}`)}
                        {cell("Live vs paper / contract", `${money(full.live_net_per_contract)} vs ${money(full.paper_net_per_contract)}`)}
                      </dl>
                      {cum.length > 1 && <Spark data={cum} lines={[{ key: "pnl", color: run >= 0 ? "#34d399" : "#fb7185" }]} height={120} />}
                      <TradesView orders={full.orders} />
                    </>
                  ) : <p className="text-sm text-slate-400">{blurb}</p>}
                  {link}
                </div>
              }>
      {full ? (
        <>
          <Spark data={cum} lines={[{ key: "pnl", color: run >= 0 ? "#34d399" : "#fb7185" }]} height={40} />
          <p className="mt-1 hidden text-xs tabular-nums text-slate-400 sm:block">{full.fills} trades · {wins} won · <span className={toneOf(run)}>{money(run)}</span> settled</p>
        </>
      ) : null}
      <div className="mt-1 hidden sm:block">{link}</div>
    </DashCard>
  );
}

/** Small labelled bar groups for a card (one group per market; dimmed bars are the control). */
function LabeledBars({ groups, height = 36 }: { groups: { label: string; bars: { v: number | null; dim?: boolean }[] }[]; height?: number }) {
  if (groups.length === 0) return <div style={{ height }} className="flex items-center text-xs text-slate-500">—</div>;
  const data = groups.flatMap((g) => g.bars.map((b) => ({ v: b.v ?? 0, dim: !!b.dim })));
  return (
    <div>
      <MiniBars data={data} valueKey="v" height={height} dim={(d) => d.dim} />
      <div className="mt-0.5 grid text-center text-[10px] text-slate-500" style={{ gridTemplateColumns: `repeat(${groups.length}, minmax(0, 1fr))` }}>
        {groups.map((g) => <span key={g.label} className="truncate">{g.label}</span>)}
      </div>
    </div>
  );
}

const x100 = (v: number | null | undefined) => (v == null ? null : v * 100);

/** Per market, gated net cents then raw (dimmed): the 15-minute card's always-open graph. */
const seriesGroups = (labels: string[], block?: { gate?: { by_series?: Record<string, SeriesStats> }; by_series?: Record<string, SeriesStats> } | null) =>
  labels.filter((l) => block?.gate?.by_series?.[l] || block?.by_series?.[l]).map((l) => ({
    label: l === "Natural gas" ? "Gas" : l,
    bars: [{ v: x100(block?.gate?.by_series?.[l]?.net_per_contract) },
           { v: x100(block?.by_series?.[l]?.net_per_contract), dim: true }],
  }));

/**
 * Strategies (Kevin, 2026-11-05; split per market 2026-11-09; visual tiles 2026-11-09): every rule
 * that trades or paper-trades as a tile — its record drawn (bars, curves) with a few headline
 * numbers, and every sentence of explanation under the tile's expansion. The 15-minute oil & gas
 * expansion is itself split into small titled blocks (rule, settlements, record, decisions,
 * timing, sessions, shadow), each fact stated once — the single mega-dropdown repeated itself
 * (Kevin, 2026-11-09). The gap tracker, paused 2026-11-09, sits with the muted entries at the
 * bottom as a closed book: the final record on the tile, the post-mortem in its one expansion.
 * The market pages keep the live reads; the Track record keeps whether the reads are right;
 * this page keeps whether trading on them pays.
 * Organised by stage (Kevin, 2026-11-24); compact dashboard the same day (DESIGN-RULES): live models as
 * DashCards with an always-open graph, shadows below as a five-row list, everything else behind a click.
 */
export default function Strategies() {
  const portfolio = useJson<{ scoreboard?: { return_pct: number | null; ahead_pts: number | null };
                              curve?: { t: string; portfolio_pct: number; spy_pct: number }[] }>("/api/portfolio");
  const ideas = useJson<{ live_books?: string[] }[]>("/api/ideas");
  const fifteen = useJson<FifteenPayload>("/api/oil/fifteen-rule");
  const strike = useJson<{ settled?: number; hits?: number; hit_rate?: number | null; net_per_contract?: number | null;
                           by_segment?: Record<string, { settled: number; hits: number; net_per_contract: number | null }> }>("/api/oil/itm-record");
  const gaps = useJson<{ as_of?: string | null; entries_paused?: boolean;
                         grade?: { oil?: { n: number; brier_delta: number | null };
                                   crypto?: { n: number; brier_delta: number | null } };
                         ledger?: { bankroll: number; resolved: number; open: number };
                         open_positions?: GapPosition[];
                         closed_positions?: GapPosition[];
                         ledger_by_category?: Record<string, GapCategoryLedger> }>("/api/gaps/desk");
  const sniper = useJson<{ overall?: { count: number; hit_rate: number } }>("/api/crypto/sniper-verdict");
  const served = useJson<{ trials?: ServedTrial[] }>("/api/strategies/trials");
  const trials = [...boardTrials(fifteen?.board), ...(served?.trials ?? []).map(servedTrial)];

  // Trading on at least one book; `live` on this payload is the shadow record's state, not trading.
  const live = Array.isArray(ideas) ? ideas.filter((i) => (i.live_books ?? []).length > 0).length : null;
  const ahead = portfolio?.scoreboard?.ahead_pts;

  // One market's line for the 15-minute rule: the gated record leads (it is the live rule);
  // a market with no gated trades yet falls back to its raw record and says so.
  const fifteenRecord = (label: string): { record: string | null; tone?: string } => {
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

  // The metals family's line: same shape as fifteenRecord, read from the
  // metals block — and before its first settled gated trade the line says
  // so, instead of borrowing a number from anywhere else.
  const metalsRecord = (label: string): { record: string | null; tone?: string } => {
    const m = fifteen?.metals;
    if (!m) return { record: null };
    const g = m.gate?.by_series?.[label];
    const r = m.by_series?.[label];
    if (g && g.n > 0) {
      return { record: `${g.n} gated trades · ${g.net_per_contract == null ? "—" : cents(g.net_per_contract)} · ${g.win_rate == null ? "—" : `${Math.round(g.win_rate * 100)}% win`}`,
               tone: toneOf(g.net_per_contract) };
    }
    if (r && r.n > 0) {
      return { record: `${g ? "0 gated trades · " : ""}raw ${r.n} trade${r.n === 1 ? "" : "s"} · ${r.net_per_contract == null ? "—" : cents(r.net_per_contract)}`,
               tone: toneOf(r.net_per_contract) };
    }
    return { record: "Accruing — no settled gated trades yet" };
  };

  // The family headline for a fifteen tile: the gated record across its markets, raw kept beside it as the control.
  const familyStats = (labels: string[], block?: { gate?: { by_series?: Record<string, SeriesStats> }; by_series?: Record<string, SeriesStats> } | null): { gated: SeriesStats | null; raw: SeriesStats | null } => {
    const fold = (src?: Record<string, SeriesStats>): SeriesStats | null => {
      const parts = labels.map((l) => src?.[l]).filter((s): s is SeriesStats => !!s);
      if (parts.length === 0) return null;
      const n = parts.reduce((a, s) => a + s.n, 0);
      const wsum = parts.reduce((a, s) => a + (s.net_per_contract != null ? s.n * s.net_per_contract : 0), 0);
      const wn = parts.reduce((a, s) => a + (s.net_per_contract != null ? s.n : 0), 0);
      const wr = parts.reduce((a, s) => a + (s.win_rate != null ? s.n * s.win_rate : 0), 0);
      const wrn = parts.reduce((a, s) => a + (s.win_rate != null ? s.n : 0), 0);
      return { n, net_per_contract: wn > 0 ? wsum / wn : null, win_rate: wrn > 0 ? wr / wrn : null };
    };
    return { gated: fold(block?.gate?.by_series), raw: fold(block?.by_series) };
  };
  const familyLine = (labels: string[], block?: { gate?: { by_series?: Record<string, SeriesStats> }; by_series?: Record<string, SeriesStats> } | null): { record: string | null; tone?: string } => {
    const { gated, raw } = familyStats(labels, block);
    if (!block || (!gated && !raw)) return { record: null };
    if (gated && gated.n > 0) {
      return { record: `${gated.n} gated trades · ${gated.net_per_contract == null ? "—" : cents(gated.net_per_contract)} · ${gated.win_rate == null ? "—" : `${Math.round(gated.win_rate * 100)}% win`}${raw && raw.n > 0 ? ` · raw control ${raw.n} · ${raw.net_per_contract == null ? "—" : cents(raw.net_per_contract)}` : ""}`,
               tone: toneOf(gated.net_per_contract) };
    }
    if (raw) return { record: `${gated ? "0 gated trades · " : ""}raw ${raw.n} trade${raw.n === 1 ? "" : "s"} · ${raw.net_per_contract == null ? "—" : cents(raw.net_per_contract)}`, tone: toneOf(raw.net_per_contract) };
    return { record: null };
  };

  // One desk's line for the gap tracker: the server's per-desk ledger leads — it is computed
  // over every closed position, while the payload's closed-positions page is capped, so the
  // page is only a fallback for a payload that predates the ledger. (The $10k pot is shared
  // and stays combined in the desk below; the trades carry their market and split exactly.)
  const gapStats = (category: string): GapCategoryLedger | null => {
    if (!gaps) return null;
    const led = gaps.ledger_by_category?.[category];
    if (led && led.closed > 0) return led;
    const pnls = (gaps.closed_positions ?? []).filter((p) => p.category === category && p.pnl != null)
      .map((p) => p.pnl ?? 0).sort((a, b) => a - b);
    if (pnls.length === 0) return null;
    const sum = pnls.reduce((a, v) => a + v, 0);
    const won = pnls.filter((v) => v > 0).length;
    const median = pnls.length % 2 === 1 ? pnls[(pnls.length - 1) / 2]
      : (pnls[pnls.length / 2 - 1] + pnls[pnls.length / 2]) / 2;
    return { closed: pnls.length, realized: sum, win_rate: won / pnls.length, median_pnl: median };
  };
  const gapRecord = (category: string): { record: string | null; tone?: string } => {
    const led = gapStats(category);
    if (!led) return { record: null };
    if (led.win_rate == null || led.median_pnl == null) return { record: null };
    return { record: `${led.closed} closed · ${usd(led.realized)} realized · ${Math.round(led.win_rate * 100)}% won · typical trade ${usd(led.median_pnl)}`,
             tone: toneOf(led.realized) };
  };

  // How one desk's closed trades ended, grouped by exit reason. The payload's closed page
  // holds the whole book here: the tracker is paused, so only the still-open positions can
  // still join it, and they cannot push it past the page.
  const exitBreakdown = (category: string): { key: string; label: string; n: number; pnl: number }[] => {
    const byReason = new Map<string, { n: number; pnl: number }>();
    for (const p of gaps?.closed_positions ?? []) {
      if (p.category !== category || p.pnl == null) continue;
      const key = p.exit_reason ?? "unknown";
      const cur = byReason.get(key) ?? { n: 0, pnl: 0 };
      cur.n += 1;
      cur.pnl += p.pnl;
      byReason.set(key, cur);
    }
    const known = GAP_EXIT_LABELS.filter(([k]) => byReason.has(k))
      .map(([k, label]) => ({ key: k, label, ...byReason.get(k)! }));
    const rest = [...byReason.entries()].filter(([k]) => !GAP_EXIT_LABELS.some(([kk]) => kk === k))
      .map(([k, v]) => ({ key: k, label: gapExitLabel(k), ...v }));
    return [...known, ...rest];
  };

  const OIL_LABELS = ["WTI", "Brent", "Natural gas"];
  const METAL_LABELS = ["Gold", "Silver", "Copper"];
  const hasMetals = !!fifteen?.metals;
  // The oil family's headline is the endpoint's own aggregate (gate.forward, with forward as the
  // raw control) — never a client fold that could disagree with the server's record. Metals have
  // no served family aggregate yet, so theirs folds the per-series stats the endpoint does serve.
  const oilAgg = fifteen?.gate?.forward ?? null;
  const oilRaw = fifteen?.forward ?? null;
  const oilLine: { record: string | null; tone?: string } = !fifteen || (!oilAgg && !oilRaw)
    ? { record: null }
    : oilAgg && oilAgg.n > 0
      ? { record: `${oilAgg.n} gated trades · ${oilAgg.net_per_contract == null ? "—" : cents(oilAgg.net_per_contract)} · ${oilAgg.win_rate == null ? "—" : `${Math.round(oilAgg.win_rate * 100)}% win`}${oilRaw && oilRaw.n > 0 ? ` · raw control ${oilRaw.n} · ${oilRaw.net_per_contract == null ? "—" : cents(oilRaw.net_per_contract)}` : ""}`,
          tone: toneOf(oilAgg.net_per_contract) }
      : { record: `${oilAgg ? "0 gated trades · " : ""}raw ${oilRaw?.n ?? 0} trade${oilRaw?.n === 1 ? "" : "s"} · ${oilRaw?.net_per_contract == null ? "—" : cents(oilRaw.net_per_contract)}`, tone: toneOf(oilRaw?.net_per_contract) };
  // The oil tile's detail blocks, all read from the same payload: the gated record leads,
  // the raw record is its control.
  const gateFwd = fifteen?.gate?.forward ?? null;
  const rawFwd = fifteen?.forward ?? null;
  const liveBar = fifteen?.bar ?? null;
  const readyN = fifteen?.ready_trades ?? 300;
  const barPct = liveBar ? Math.min(100, (liveBar.trades / readyN) * 100) : 0;
  const pricedOffsets = (fifteen?.offsets?.by_offset ?? []).filter((o) => o.priced > 0);
  const bestOffset = pricedOffsets
    .filter((o) => o.n >= 10 && o.net_per_contract != null)
    .sort((a, b) => (b.net_per_contract ?? 0) - (a.net_per_contract ?? 0))[0];
  // The metals headline prefers the block's own served aggregate (gate.forward);
  // the fold over its per-series stats is only the fallback for a payload without one.
  // Before the first settled trade the headline says accruing, like its per-market lines.
  const metalAgg = fifteen?.metals?.gate?.forward ?? null;
  const metalFold = familyStats(METAL_LABELS, fifteen?.metals);
  const metalLine: { record: string | null; tone?: string } = metalAgg && metalAgg.n > 0
    ? { record: `${metalAgg.n} gated trades · ${metalAgg.net_per_contract == null ? "—" : cents(metalAgg.net_per_contract)} · ${metalAgg.win_rate == null ? "—" : `${Math.round(metalAgg.win_rate * 100)}% win`}`,
        tone: toneOf(metalAgg.net_per_contract) }
    : (metalFold.gated || metalFold.raw) && (metalFold.gated?.n ?? 0) === 0 && (metalFold.raw?.n ?? 0) === 0
      ? { record: "Accruing — no settled gated trades yet" }
      : familyLine(METAL_LABELS, fifteen?.metals);
  const gapOil = gapStats("oil"), gapCrypto = gapStats("crypto");
  const gapMaxAbs = Math.max(0.01, Math.abs(gapOil?.realized ?? 0), Math.abs(gapCrypto?.realized ?? 0));
  const gapTotalRealized = (gapOil || gapCrypto) ? (gapOil?.realized ?? 0) + (gapCrypto?.realized ?? 0) : null;
  const gapClosedTotal = (gapOil || gapCrypto) ? (gapOil?.closed ?? 0) + (gapCrypto?.closed ?? 0) : null;
  // The pause lane's switch, read off the desk payload: entries are paused unless the payload
  // says otherwise (Kevin paused the desk 2026-11-09; the flag confirms it once that lane lands).
  const gapPaused = gaps?.entries_paused !== false;
  const gapOpen = gaps?.open_positions ?? [];
  const gapOilExits = exitBreakdown("oil"), gapCryptoExits = exitBreakdown("crypto");
  const gapDelta = (d: number | null | undefined) => (d == null ? null : `${d >= 0 ? "+" : "−"}${Math.abs(d).toFixed(3)}`);
  const cryptoMoved = gapCryptoExits.find((r) => r.key === "model_moved") ?? null;
  const oilGapClosed = gapOilExits.find((r) => r.key === "gap_closed") ?? null;
  const oilSettled = gapOilExits.find((r) => r.key === "settlement") ?? null;
  const strikeShare = strike?.settled ? (strike.hits ?? 0) / strike.settled : null;

  const tiles: TileSpec[] = [
    {
      id: "stock-ideas", name: "Stock ideas", stage: "Live paper account",
      card: {
        value: ahead == null ? "—" : `${signed(ahead)} pts`, valueClass: toneOf(ahead) ?? "text-slate-200",
        sub: `vs SPY since start · ${live == null ? "—" : `${live} idea${live === 1 ? "" : "s"} trading`}`,
        graph: (
          <div>
            {portfolio?.curve && portfolio.curve.length > 1 ? <CurveSpark curve={portfolio.curve} height="h-8 sm:h-10" />
              : <div className="flex h-8 items-center text-xs text-slate-500 sm:h-10">—</div>}
            <Link to="/portfolio" className="relative z-10 mt-1 hidden items-center sm:inline-flex gap-1 text-xs text-emerald-300 hover:text-emerald-200">
              Portfolio <ArrowRight className="h-3 w-3" aria-hidden="true" />
            </Link>
          </div>
        ),
      },
      visual: portfolio?.curve ? <CurveSpark curve={portfolio.curve} /> : null,
      stats: (
        <div>
          <p className="text-sm tabular-nums text-slate-300">
            <span className={`text-xl font-semibold ${toneOf(ahead) ?? "text-slate-200"}`}>{ahead == null ? "—" : signed(ahead)}</span>
            {" pts vs SPY since start"}
          </p>
          <RecordLine text={live == null ? null : `${live} idea${live === 1 ? "" : "s"} trading`} />
        </div>
      ),
      children: (
        <section aria-label="Stock ideas">
          <p className="text-sm text-slate-400">
            Workshop ideas that cleared their gates hold their stock baskets on the paper account at their set sizes; a morning job rebalances them.
          </p>
          <p className="mt-2 text-sm text-slate-400">
            The live ideas trade the paper stock accounts; their holdings, sizes and P&amp;L are on the Portfolio, and
            every idea's backtest and shadow record is on Ideas.
          </p>
          <div className="mt-2 flex gap-4 text-sm">
            <Link to="/portfolio" className="inline-flex items-center gap-1 text-emerald-300 hover:text-emerald-200">Portfolio <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></Link>
            <Link to="/ideas" className="inline-flex items-center gap-1 text-emerald-300 hover:text-emerald-200">Ideas <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" /></Link>
          </div>
        </section>
      ),
    },
    {
      id: "fifteen-rule", name: "15-min oil & gas", stage: "Paper record",
      card: {
        value: oilAgg && oilAgg.n > 0 && oilAgg.net_per_contract != null ? cent1(oilAgg.net_per_contract) : "—",
        valueClass: toneOf(oilAgg?.net_per_contract) ?? "text-slate-200",
        sub: `${oilAgg?.n ?? "—"} of ${readyN} gated · ${oilAgg?.win_rate == null ? "—" : `${Math.round(oilAgg.win_rate * 100)}%`} win · raw ${oilRaw?.net_per_contract == null ? "—" : cent1(oilRaw.net_per_contract)}`,
        graph: <LabeledBars groups={seriesGroups(OIL_LABELS, fifteen)} />,
        hint: "Net cents a contract per market after the fee: solid bars gated, faded bars raw",
      },
      proven: liveBar ? liveBar.ready : undefined,
      visual: <SeriesBars labels={OIL_LABELS} fifteen={fifteen} lines={Object.fromEntries(OIL_LABELS.map((l) => [l, fifteenRecord(l)]))} />,
      stats: <RecordLine text={oilLine.record} tone={oilLine.tone} />,
      children: (
        <section aria-label="15-minute rules by market">
          <SubDetails title="The rule">
            <p className="text-sm text-slate-400">
              Five minutes into each 15-minute window, buy the side the model beats by 10+ points after
              Kalshi's fee; hold to the close. Nothing trades around the 4:45–6:30 PM ET futures halt.
            </p>
          </SubDetails>
          <SubDetails title="Settlements scoring — the forecasts vs Kalshi's price">
            <FifteenSettlements />
          </SubDetails>
          {fifteen && (
            <SubDetails title="The trade record">
              {gateFwd && gateFwd.n > 0 ? (
                <div className="flex flex-wrap items-baseline gap-x-6 gap-y-1 tabular-nums">
                  <span className={`text-lg font-semibold ${toneOf(gateFwd.net_per_contract) ?? "text-slate-200"}`}>
                    {gateFwd.net_per_contract == null ? "—" : cents(gateFwd.net_per_contract)}
                  </span>
                  <span className="text-sm text-slate-400">
                    win rate {gateFwd.win_rate == null ? "—" : `${Math.round(gateFwd.win_rate * 100)}%`}
                    {gateFwd.total != null && <> · {gateFwd.total >= 0 ? "+" : "−"}${Math.abs(gateFwd.total).toFixed(2)} on one contract each</>}
                  </span>
                </div>
              ) : (
                <p className="text-sm text-slate-400">
                  No forward trades yet{fifteen.prereg_at ? <>. The record starts {etShort(fifteen.prereg_at)} ET</> : ""}.
                </p>
              )}
              {liveBar && (
                <div className="mt-2">
                  <div className="h-1.5 max-w-sm rounded-full bg-slate-800" role="img" aria-label={`${liveBar.trades} of ${readyN} settled gated trades`}>
                    <div className="h-full rounded-full bg-emerald-400/80" style={{ width: `${barPct}%` }} />
                  </div>
                  <p className="mt-1 text-xs text-slate-400">
                    {liveBar.trades} of {readyN} settled gated trades{liveBar.windows != null ? ` in ${liveBar.windows} separate 15-minute windows` : ""}. Copyable once the gated record has {readyN} and is still ahead at the
                    low end of its 95% range{liveBar.low95 != null ? ` (now ${cent1(liveBar.low95)})` : ""}.{liveBar.ready ? " It has cleared that bar." : ""}
                    {(liveBar.pending ?? 0) > 0 ? ` ${liveBar.pending} waiting to settle.` : ""}
                  </p>
                </div>
              )}
              {rawFwd && rawFwd.n > 0 && (
                <p className="mt-2 text-xs text-slate-400">
                  On the original gross-edge record, kept as a control: {rawFwd.n} trades, {rawFwd.net_per_contract == null ? "—" : cents(rawFwd.net_per_contract)}, win rate {rawFwd.win_rate == null ? "—" : `${Math.round(rawFwd.win_rate * 100)}%`}.
                </p>
              )}
              {(fifteen.recent ?? []).length > 0 && (
                <table className="mt-3 w-full max-w-xl text-xs tabular-nums">
                  <thead><tr className="text-left text-slate-500">
                    <th className="pb-1 pr-3 font-medium">Window</th><th className="pb-1 pr-3 font-medium">Market</th>
                    <th className="pb-1 pr-3 font-medium">Bought</th><th className="pb-1 text-right font-medium">Result</th>
                  </tr></thead>
                  <tbody className="divide-y divide-slate-800/70 text-slate-300">
                    {(fifteen.recent ?? []).slice(0, 6).map((t) => (
                      <tr key={`${t.series}-${t.target}`}>
                        <td className="py-1 pr-3">{etShort(t.frozen_at)}</td>
                        <td className="py-1 pr-3">{t.series}</td>
                        <td className="py-1 pr-3">{t.side.toUpperCase()} at {Math.round(t.cost * 100)}¢ (model {Math.round((t.side === "yes" ? t.model : 1 - t.model) * 100)}%)</td>
                        <td className={`py-1 text-right ${t.pnl >= 0 ? "text-emerald-300" : "text-rose-300"}`}>{cent1(t.pnl)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {fifteen.replay && (
                <p className="mt-2 text-xs text-slate-500">
                  Replay before the rule was fixed: {fifteen.replay.n} trades, {fifteen.replay.net_per_contract == null ? "—" : cents(fifteen.replay.net_per_contract)}. Fills at the quoted price are assumed; paper only.
                </p>
              )}
            </SubDetails>
          )}
          <FifteenWhereBlock />
          {fifteen?.decline && (
            <SubDetails title="Day by day — v1 rule, blend and vol-regime challenger">
              <FifteenDeclineMonitor rows={fifteen.decline} />
              <p className="mt-1 text-xs text-slate-400">
                All six 15-minute markets, the last two weeks of whole ET days: settled trades and P&amp;L per trade after
                fees. The v1 rule is the live gate for oil and gas and a record only for metals; the blend and the
                vol-regime challenger are paper shadows. Each model's own record now sits on its commodity
                card above.
              </p>
            </SubDetails>
          )}
          {fifteen?.decisions && fifteen.decisions.recorded > 0 && (
            <SubDetails title="Decisions — every window gets one">
              <p className="text-xs text-slate-400">
                {fifteen.decisions.recorded} windows on record: {fifteen.decisions.buy} buys, {fifteen.decisions.skip} skipped
                {REASON_LABELS.some(([k]) => fifteen.decisions!.by_reason[k]) &&
                  ` (${REASON_LABELS.filter(([k]) => fifteen.decisions!.by_reason[k]).map(([k, label]) => `${label} ${fifteen.decisions!.by_reason[k]}`).join(", ")})`}
                .
              </p>
            </SubDetails>
          )}
          {pricedOffsets.length > 0 && (
            <SubDetails title="Entry timing — what entering at each minute has paid">
              <table aria-label="Entry timing by minute" className="w-full max-w-xl text-xs tabular-nums">
                <thead><tr className="text-left text-slate-500">
                  <th className="pb-1 pr-3 font-medium">Minute</th>
                  <th className="pb-1 pr-3 font-medium text-right">Windows priced</th>
                  <th className="pb-1 pr-3 font-medium text-right">Entries</th>
                  <th className="pb-1 pr-3 font-medium text-right">Per contract</th>
                  <th className="pb-1 pr-3 font-medium text-right">Win rate</th>
                  <th className="pb-1 font-medium text-right">Edge on offer</th>
                </tr></thead>
                <tbody className="divide-y divide-slate-800/70 text-slate-300">
                  {pricedOffsets.map((o) => (
                    <tr key={o.offset_min} className={bestOffset && o.offset_min === bestOffset.offset_min ? "text-slate-100" : undefined}>
                      <td className="py-1 pr-3 text-slate-200">
                        {o.offset_min}
                        {bestOffset && o.offset_min === bestOffset.offset_min ? <span className="text-emerald-300"> · best so far</span> : null}
                      </td>
                      <td className="py-1 pr-3 text-right">{o.priced}</td>
                      <td className="py-1 pr-3 text-right">{o.n}</td>
                      <td className="py-1 pr-3 text-right">{o.net_per_contract == null ? "—" : cent1(o.net_per_contract)}</td>
                      <td className="py-1 pr-3 text-right">{o.win_rate == null ? "—" : `${Math.round(o.win_rate * 100)}%`}</td>
                      <td className="py-1 text-right">{o.mean_edge_net == null ? "—" : pts1(o.mean_edge_net)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-1 text-xs text-slate-400">
                Each row replays the gate at that minute of the window on settled windows — the same window can
                appear in several rows, so read it as "what this minute has paid", not as separate trades.
                Minutes 0 and 15 have almost no priced rows: the tape recorder starts and stops at the window's edges.
              </p>
              {bestOffset && (
                <p className="mt-1 text-xs text-slate-400">
                  Best entry minute so far: minute {bestOffset.offset_min} of the window ({bestOffset.n} priced entries, {cent1(bestOffset.net_per_contract ?? 0)} a contract after fees).
                </p>
              )}
            </SubDetails>
          )}
          {fifteen?.by_session && (
            <SubDetails title="Trading hours vs closed hours">
              <table className="w-full max-w-md text-xs tabular-nums">
                <thead><tr className="text-left text-slate-500">
                  <th className="pb-1 pr-3 font-medium"></th>
                  <th className="pb-1 pr-3 font-medium text-right">Trades</th>
                  <th className="pb-1 pr-3 font-medium text-right">Per contract</th>
                  <th className="pb-1 text-right font-medium">Win rate</th>
                </tr></thead>
                <tbody className="divide-y divide-slate-800/70 text-slate-300">
                  <tr>
                    <td className="py-1 pr-3 text-slate-200">When futures were trading</td>
                    <td className="py-1 text-right">{fifteen.by_session.open.n}</td>
                    <td className="py-1 text-right">{fifteen.by_session.open.net_per_contract == null ? "—" : cent1(fifteen.by_session.open.net_per_contract)}</td>
                    <td className="py-1 text-right">{fifteen.by_session.open.win_rate == null ? "—" : `${Math.round(fifteen.by_session.open.win_rate * 100)}%`}</td>
                  </tr>
                  <tr>
                    <td className="py-1 pr-3 text-slate-200">When futures were closed</td>
                    <td className="py-1 text-right">{fifteen.by_session.closed.n}</td>
                    <td className="py-1 text-right">{fifteen.by_session.closed.net_per_contract == null ? "—" : cent1(fifteen.by_session.closed.net_per_contract)}</td>
                    <td className="py-1 text-right">{fifteen.by_session.closed.win_rate == null ? "—" : `${Math.round(fifteen.by_session.closed.win_rate * 100)}%`}</td>
                  </tr>
                </tbody>
              </table>
              <p className="mt-1 text-xs text-slate-400">A real edge should hold while futures trade; wins only in closed hours can come from stale prices.</p>
            </SubDetails>
          )}
        </section>
      ),
    },
    ...(hasMetals ? [{
      id: "fifteen-metals", name: "15-min metals", stage: "Paper record" as Stage,
      card: {
        value: metalAgg && metalAgg.n > 0 && metalAgg.net_per_contract != null ? cent1(metalAgg.net_per_contract) : "Accruing",
        valueClass: toneOf(metalAgg && metalAgg.n > 0 ? metalAgg.net_per_contract : null) ?? "text-slate-400",
        sub: `${metalAgg?.n ?? metalFold.gated?.n ?? "—"} of ${fifteen?.metals?.ready_trades ?? 300} gated · ${metalAgg?.win_rate == null ? "—" : `${Math.round(metalAgg.win_rate * 100)}%`} win · raw ${metalFold.raw?.net_per_contract == null ? "—" : cent1(metalFold.raw.net_per_contract)}`,
        graph: <LabeledBars groups={seriesGroups(METAL_LABELS, fifteen?.metals)} />,
        hint: "Net cents a contract per market after the fee: solid bars gated, faded bars raw",
      },
      // Same bar as oil: ready_trades settled gated trades with low95 above zero.
      proven: (metalAgg?.n ?? 0) >= (fifteen?.metals?.ready_trades ?? 300) && (metalAgg?.low95 ?? 0) > 0,
      visual: <SeriesBars labels={METAL_LABELS} fifteen={fifteen?.metals ?? null} lines={Object.fromEntries(METAL_LABELS.map((l) => [l, metalsRecord(l)]))} />,
      stats: <RecordLine text={metalLine.record} tone={metalLine.tone} />,
      children: (
        <section aria-label="15-minute metals rule">
          <div className="space-y-2">
            {(["gold", "silver", "copper"] as const).map((m) => (
              <p key={m} className="text-sm text-slate-400">{fifteenRule(m)}</p>
            ))}
          </div>
        </section>
      ),
    }] : []),
    {
      id: "hourly-picks", name: "WTI hourly strike", stage: "Paper record",
      card: {
        value: strike?.settled ? `${Math.round(((strike.hits ?? 0) / strike.settled) * 100)}%` : "—",
        valueClass: toneOf(strike?.net_per_contract) ?? "text-slate-200",
        sub: strike?.settled == null ? "—" : `${strike.hits} of ${strike.settled} hit${strike.net_per_contract == null ? "" : ` · ${cent1(strike.net_per_contract)} a contract`}`,
        graph: <LabeledBars groups={Object.entries(strike?.by_segment ?? {}).map(([k, v]) => ({ label: k.replace("v2_", ""), bars: [{ v: x100(v.net_per_contract) }] }))} />,
        hint: "Hit rate of the graded picks; bars are net cents a contract by picker segment",
      },
      visual: (
        <div className="flex items-center gap-2">
          <span className="w-14 shrink-0 text-[11px] text-slate-400">Hit rate</span>
          <ShareBar share={strikeShare} tone={(strike?.net_per_contract ?? 0) >= 0 ? "bg-emerald-400/80" : "bg-rose-400/80"} />
          <span className="w-12 shrink-0 text-right text-xs tabular-nums text-slate-200">
            {strike?.settled ? `${Math.round(((strike.hits ?? 0) / strike.settled) * 100)}%` : "—"}
          </span>
        </div>
      ),
      stats: (
        <RecordLine
          text={strike?.settled == null ? null
            : `${strike.hits} of ${strike.settled} hit${strike.net_per_contract == null ? "" : ` · ${cents(strike.net_per_contract)}`}`}
          tone={toneOf(strike?.net_per_contract)}
        />
      ),
      children: (
        <section aria-label="WTI hourly best strike">
          <p className="text-sm text-slate-400">
            Before each hourly WTI settlement on Kalshi, record the strike the model beats by the most, but only when its calibrated chance clears the price you can actually pay by 15 or more points; snapshots land thirty and ten minutes out. The model's raw chances have run about 13 points hot, so they are corrected against its own settled history first. Recorded, never traded.
          </p>
          <p className="mt-2 text-sm text-slate-400">
            The live pick is on the <Link to="/oil" className="text-emerald-300 hover:text-emerald-200">Commodities page</Link>; this is how the picks have done.
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
      ),
    },
    {
      id: "sniper", name: "Crypto sniper", stage: "Retired", muted: true,
      visual: (
        <div className="flex items-center gap-2">
          <span className="w-14 shrink-0 text-[11px] text-slate-400">Hit rate</span>
          <ShareBar share={sniper?.overall?.hit_rate ?? null} tone="bg-slate-400/80" />
          <span className="w-12 shrink-0 text-right text-xs tabular-nums text-slate-200">
            {sniper?.overall ? `${Math.round(sniper.overall.hit_rate * 100)}%` : "—"}
          </span>
        </div>
      ),
      stats: (
        <RecordLine text={sniper?.overall ? `${sniper.overall.count.toLocaleString()} graded · ${Math.round(sniper.overall.hit_rate * 100)}% hit` : null} />
      ),
      children: (
        <section aria-label="Crypto sniper">
          <p className="text-sm text-slate-400">
            Next-hour BTC and ETH calls on the Kalshi demo account; the worker stopped June 2, 2026.
          </p>
          <h2 className="mt-4 text-lg font-semibold text-white">Crypto sniper, retired</h2>
          <SniperRecord />
        </section>
      ),
    },
    {
      // Paused 2026-11-09 and demoted out of the live grid: the tile is the final
      // record, and its one expansion is the post-mortem, not a desk.
      id: "gap-tracker", name: "Kalshi gap tracker", stage: gapPaused ? "Paused" : "Paper record",
      chipLabel: gapPaused ? "Paused · Nov 9, 2026" : undefined, muted: gapPaused,
      visual: (
        <div className="space-y-3">
          {([["Oil", gapOil], ["Crypto", gapCrypto]] as const).map(([label, led]) => (
            <div key={label} className="flex items-center gap-2">
              <span className="w-14 shrink-0 text-[11px] text-slate-400">{label}</span>
              <SignedBar value={led?.realized ?? null} maxAbs={gapMaxAbs} />
              <span className={`w-24 shrink-0 text-right text-xs tabular-nums ${toneOf(led?.realized) ?? "text-slate-400"}`}>
                {led ? usd(led.realized) : "—"}
              </span>
            </div>
          ))}
        </div>
      ),
      stats: (
        <div>
          <p className="text-sm tabular-nums text-slate-300">
            <span className={`text-xl font-semibold ${toneOf(gapTotalRealized) ?? "text-slate-200"}`}>
              {gapTotalRealized == null ? "—" : usd(gapTotalRealized)}
            </span>
            {" realized · the final record"}
          </p>
          <p className="mt-1 text-xs tabular-nums text-slate-400">
            {gapClosedTotal == null
              ? "Record unavailable"
              : `${gapClosedTotal} closed${gaps?.ledger ? ` · pot ${usdPlain(gaps.ledger.bankroll)} of $10,000` : ""}${gapOpen.length > 0 ? ` · ${gapOpen.length} open, resolving` : ""}`}
          </p>
          {gaps?.as_of && <p className="mt-0.5 text-xs text-slate-500">As of {etShort(gaps.as_of)} ET</p>}
        </div>
      ),
      children: (
        <section aria-label="Kalshi gap tracker — the record">
          <p className="text-sm text-slate-400">
            Paused on Kevin's call, Nov 9, 2026. It takes no new trades;{" "}
            {gapOpen.length > 0
              ? <>the {gapOpen.length} position{gapOpen.length === 1 ? "" : "s"} still open run{gapOpen.length === 1 ? "s" : ""} to the old exits, and then the book is final.</>
              : "every position has resolved, and the book is final."}
          </p>
          {gaps?.grade && (gaps.grade.oil?.brier_delta != null || gaps.grade.crypto?.brier_delta != null) && (
            <p className="mt-2 text-sm text-slate-400">
              Why it was paused: on the paired forecasts, each desk's fair values graded worse than Kalshi's
              own price — Brier worse by {gapDelta(gaps.grade.oil?.brier_delta)} on oil and {gapDelta(gaps.grade.crypto?.brier_delta)} on
              crypto (model minus market; positive is worse). A gap measured against a price that forecasts
              better than the model is mostly the model's own error, and the record below is what that cost.
            </p>
          )}
          {cryptoMoved && gapCrypto && (
            <p className="mt-2 text-sm text-slate-400">
              Crypto's exits churned: {cryptoMoved.n} of its {gapCrypto.closed} trade{gapCrypto.closed === 1 ? "" : "s"} ended because the model
              moved, not because the gap closed ({usd(cryptoMoved.pnl)}) — it kept repricing its own fair value
              and paying to leave.
            </p>
          )}
          {oilGapClosed && (
            <p className="mt-2 text-sm text-slate-400">
              Oil's gap-closed exits were the one working piece: {oilGapClosed.n} trade{oilGapClosed.n === 1 ? "" : "s"}, {usd(oilGapClosed.pnl)}
              {oilSettled ? <>. Against them, {oilSettled.n} position{oilSettled.n === 1 ? "" : "s"} held to settlement cost {usd(oilSettled.pnl)} — more than the working piece made</> : ""}.
            </p>
          )}
          <p className="mt-2 text-sm text-slate-400">
            The WTI hourly lane never fired: by the pause it had read 2,013 snapshots of the hourly series and
            flagged none — the entry gate demanded 2+ hours to settlement, which an hourly contract's tradable
            life never offers.
          </p>
          <p className="mt-2 text-sm text-slate-400">
            What it was: it bought Brent and WTI, Bitcoin and Ethereum hourly and daily contracts when the
            model's chance beat the price it could actually pay by 8+ points, with the fee outside the entry
            test — fees came out of the trade's P&L, not the test — only with 2+ hours to settlement and a book
            deep enough to exit in full, one trade per event. It exited when the gap narrowed to 2 points, the
            model moved more than 5 points from entry, or under an hour was left.
          </p>
          <div className="mt-3 space-y-1">
            {([["Oil", gapRecord("oil")], ["Crypto", gapRecord("crypto")]] as const).map(([label, line]) => (
              <div key={label} className="flex items-baseline gap-2">
                <span className="w-14 shrink-0 text-sm text-slate-400">{label}</span>
                <RecordLine text={line.record} tone={line.tone} />
              </div>
            ))}
          </div>
          {(gapOilExits.length > 0 || gapCryptoExits.length > 0) && (
            <div className="mt-4">
              <h3 className="mb-1 text-xs font-medium text-slate-300">How the trades ended</h3>
              <div className="-mx-4 overflow-x-auto px-4">
                <table className="w-full min-w-[26rem] text-left text-xs tabular-nums">
                  <thead className="text-slate-500">
                    <tr>
                      <th scope="col" className="py-1 pr-3 font-medium">Desk</th>
                      <th scope="col" className="py-1 pr-3 font-medium">Exit</th>
                      <th scope="col" className="py-1 pr-3 text-right font-medium">Trades</th>
                      <th scope="col" className="py-1 text-right font-medium">P&amp;L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {([["Oil", gapOilExits], ["Crypto", gapCryptoExits]] as const).flatMap(([label, rows]) =>
                      rows.map((r) => (
                        <tr key={`${label}-${r.key}`} className="border-t border-slate-800/80 text-slate-300">
                          <td className="py-1.5 pr-3">{label}</td>
                          <td className="py-1.5 pr-3">{r.label}</td>
                          <td className="py-1.5 pr-3 text-right">{r.n}</td>
                          <td className={`py-1.5 text-right ${toneOf(r.pnl) ?? ""}`}>{usd(r.pnl)}</td>
                        </tr>
                      )))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
          {gapOpen.length > 0 && (
            <div className="mt-4">
              <h3 className="mb-1 text-xs font-medium text-slate-300">Still open — resolving under the old exits</h3>
              <GapPositionsTable rows={gapOpen} open />
            </div>
          )}
          {(gaps?.closed_positions ?? []).length > 0 && (
            <div className="mt-4">
              <h3 className="mb-1 text-xs font-medium text-slate-300">Closed trades</h3>
              <GapPositionsTable rows={gaps?.closed_positions ?? []} />
            </div>
          )}
        </section>
      ),
    },
  ];

  const RETIRED = new Set(["sniper", "gap-tracker"]);
  const board = fifteen?.board;
  return (
    <div className="mx-auto max-w-7xl px-4 py-3 sm:py-5 md:px-6">
      <h1 className="text-xl font-bold sm:text-2xl tracking-tight text-white">Strategies</h1>
      <p className="mt-1 hidden text-sm text-slate-400 sm:block">Live models first, shadows on trial below. Click any card or row for its full record.</p>

      <section aria-label="Live models" className="mt-3 sm:mt-4">
        <h2 className="mb-2 text-sm font-semibold text-white">Live models</h2>
        <div className="grid grid-cols-2 gap-2 sm:gap-3 lg:grid-cols-3 xl:grid-cols-5">
          <PilotCard />
          {tiles.filter((t): t is TileSpec & { card: NonNullable<TileSpec["card"]> } => !!t.card)
            .map((spec) => <LiveCard key={spec.id} spec={spec} />)}
        </div>
      </section>

      <div className="mt-3 grid gap-2 sm:mt-5 sm:gap-3 lg:grid-cols-3">
        <OnTrial rows={trials} />
        <div className="grid min-w-0 grid-cols-2 content-start gap-2 sm:gap-3 lg:mt-7 lg:grid-cols-1">
          {board?.commodities?.length ? (
            <DashCard title="By commodity" className="sm:col-span-2 lg:col-span-1"
                      sub={<span className="sm:hidden">{board.commodities.length} markets</span>}
                      meta={`${board.commodities.reduce((a, c) => a + c.models.length, 0)} models`}
                      hint="Every 15-minute model on each market, ranked, a simulated account under each"
                      detailTitle="15-minute models by commodity"
                      detail={<section aria-label="15-minute models by commodity"><FifteenBoard board={board} /></section>}>
              <div className="hidden sm:block"><PeekRows rows={board.commodities.slice(0, PEEK).map((c) => {
                const top = c.models[0];
                return { key: c.series, label: c.commodity, aside: top ? (top.label === top.version ? top.version : top.label) : undefined,
                         value: top?.net_cents == null ? "—" : `${signed(top.net_cents)}¢`, valueClass: toneOf(top?.net_cents) };
              })} /></div>
            </DashCard>
          ) : null}
          <DashCard title="What we learned" meta={`${LEARNED.length}`} sub={`${LEARNED[0].date} · ${LEARNED[0].text}`}
                    detail={
                      <ul className="space-y-2">
                        {LEARNED.map((f) => (
                          <li key={`${f.date}-${f.text.slice(0, 20)}`} className="flex gap-3 text-sm">
                            <span className="shrink-0 tabular-nums text-slate-500">{f.date}</span>
                            <span className="text-slate-300">{f.text}</span>
                          </li>
                        ))}
                      </ul>
                    } />
          <DashCard title="Retired & paused" meta={`${RETIRED.size}`}
                    sub={tiles.filter((t) => RETIRED.has(t.id)).map((t) => t.name).join(" · ")}
                    detail={
                      <ul aria-label="Retired strategies" className="grid items-start gap-3 sm:grid-cols-2">
                        {tiles.filter((t) => RETIRED.has(t.id)).map((spec) => <Tile key={spec.id} spec={spec} />)}
                      </ul>
                    } />
        </div>
      </div>
    </div>
  );
}
