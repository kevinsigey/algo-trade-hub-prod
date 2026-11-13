import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDown, ArrowUp, ChevronDown, ChevronRight } from "lucide-react";

import CompositionBox, { sectorColor } from "@/components/CompositionMap";
import { useApi } from "@/hooks/usePaperPortfolio";
import {
  aggregateToRow,
  contractLabel,
  dayMovers,
  fmtPct,
  fmtUsd,
  ideaScorecard,
  tone,
  withOptionsUnderStock,
  type ClosedPayload,
  type PortfolioPayload,
  type PositionRow,
} from "@/lib/paperPortfolio";
import { accountFigures } from "./Header";
import { DashCard, Fig, FilterBox, money, PEEK, PeekRows, price, REFRESH_MS, Segments, signed } from "./shared";

/** Tab 1: Book as a dashboard (Kevin, 2026-11-13). Composition, the
 * account, today's movers, positions and by-idea as cards: each card shows
 * a number and the top rows, and opens to the full sortable list. Positions
 * carry no idea information; By idea is where it lives. */
export default function BookTab({ data, liveIdeas, book }: {
  data: PortfolioPayload;
  liveIdeas: { id: number; title: string; size_pct: number | null }[];
  book: string;
}) {
  const rows = data.positions.filter((p) => p.symbol !== "Cash");
  const aggRows = data.positions_aggregate?.length
    ? data.positions_aggregate.map(aggregateToRow)
    : rows;
  const cashRow = data.positions.find((p) => p.symbol === "Cash");
  return (
    <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
      <CompositionCard data={data} aggRows={aggRows} cashRow={cashRow} />
      <AccountCard data={data} />
      <MoversCard rows={aggRows} />
      <PositionsCard rows={aggRows} cashRow={cashRow} />
      <ByIdeaCard rows={rows} equity={data.scoreboard.equity} liveIdeas={liveIdeas} book={book} />
    </div>
  );
}

type Segment = { label: string; pct: number; color: string };

function useSegments(data: PortfolioPayload, aggRows: PositionRow[], cashRow: PositionRow | undefined,
                     grouping: "sector" | "idea"): Segment[] {
  return useMemo(() => {
    let out: Segment[];
    if (grouping === "idea") {
      out = data.composition
        .filter((c) => (c.pct_of_book ?? 0) > 0)
        .map((c, i) => ({
          label: c.idea, pct: c.pct_of_book ?? 0,
          color: ["#34d399", "#38bdf8", "#a78bfa", "#f472b6", "#fb923c", "#2dd4bf"][i % 6],
        }));
    } else {
      const bySector = new Map<string, number>();
      for (const r of aggRows) {
        const sector = r.sector ?? "Other";
        bySector.set(sector, (bySector.get(sector) ?? 0) + (r.pct_of_book ?? 0));
      }
      out = [...bySector.entries()].map(([label, pct]) => ({ label, pct, color: sectorColor(label) }));
    }
    // The bar is the whole book in both groupings: cash rides along.
    if (cashRow?.pct_of_book) out.push({ label: "Cash", pct: cashRow.pct_of_book, color: sectorColor("Cash") });
    return out.sort((a, b) => b.pct - a.pct);
  }, [grouping, data.composition, aggRows, cashRow]);
}

function SegmentBar({ segments, tall }: { segments: Segment[]; tall?: boolean }) {
  const total = segments.reduce((sum, s) => sum + s.pct, 0) || 1;
  return (
    <div className={`flex w-full overflow-hidden rounded ${tall ? "h-8" : "h-6"}`} role="img"
         aria-label={segments.map((s) => `${s.label} ${s.pct.toFixed(0)}%`).join(", ")}>
      {segments.map((s) => (
        <div key={s.label} className="flex min-w-0 items-center overflow-hidden px-1.5"
             style={{ width: `${(s.pct / total) * 100}%`, background: s.color }} title={`${s.label} ${s.pct.toFixed(1)}%`}>
          {s.pct / total >= 0.08 && (
            <span className="truncate text-[11px] font-medium text-slate-950">{s.label} {s.pct.toFixed(0)}</span>
          )}
        </div>
      ))}
    </div>
  );
}

/** Composition: the whole book as one bar, its top slices under it; opens
 * to the sector/idea toggle and the ticker treemap. */
function CompositionCard({ data, aggRows, cashRow }: {
  data: PortfolioPayload; aggRows: PositionRow[]; cashRow: PositionRow | undefined;
}) {
  const sectors = useSegments(data, aggRows, cashRow, "sector");
  const invested = cashRow?.pct_of_book == null ? null : 100 - cashRow.pct_of_book;
  return (
    <DashCard title="Composition" className="md:col-span-2"
              value={invested == null ? "—" : `${invested.toFixed(0)}%`} sub="invested"
              meta={`${sectors.filter((s) => s.label !== "Cash").length} sectors`}
              detail={<CompositionDetail data={data} aggRows={aggRows} cashRow={cashRow} />}>
      <SegmentBar segments={sectors} />
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums text-slate-300">
        {sectors.slice(0, 6).map((s) => (
          <li key={s.label} className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-sm" style={{ background: s.color }} aria-hidden="true" />
            {s.label} <span className="text-slate-500">{s.pct.toFixed(0)}%</span>
          </li>
        ))}
      </ul>
    </DashCard>
  );
}

function CompositionDetail({ data, aggRows, cashRow }: {
  data: PortfolioPayload; aggRows: PositionRow[]; cashRow: PositionRow | undefined;
}) {
  const [grouping, setGrouping] = useState<"sector" | "idea">("sector");
  const segments = useSegments(data, aggRows, cashRow, grouping);
  return (
    <div>
      <div className="mb-2 flex justify-end">
        <Segments<"sector" | "idea"> label="Composition grouping" options={["sector", "idea"] as const} value={grouping}
                  onChange={setGrouping} render={(g) => (g === "sector" ? "Sectors" : "Ideas")} />
      </div>
      <SegmentBar segments={segments} tall />
      <div className="mt-3">
        <CompositionBox positions={data.positions} composition={data.composition}
                        aggregate={cashRow ? [...aggRows, cashRow] : aggRows} />
      </div>
    </div>
  );
}

const ACCOUNT_PEEK = ["Cash", "Buying power", "Unrealized P&L", "Realized P&L", "Short value", "Circuit breaker"];

function AccountCard({ data }: { data: PortfolioPayload }) {
  const figures = accountFigures(data);
  const shown = figures.filter((f) => ACCOUNT_PEEK.includes(f.label));
  return (
    <DashCard title="Account" detail={(
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        {figures.map((f) => <Fig key={f.label} label={f.label} value={f.value} className={f.className ?? "text-white"} />)}
      </dl>
    )} detailTitle="Account figures">
      <dl className="grid grid-cols-2 gap-x-3 gap-y-2">
        {shown.map((f) => (
          <div key={f.label} className={f.label === "Circuit breaker" ? "col-span-2" : ""}>
            <Fig label={f.label} value={f.value} className={f.className ?? "text-white"} />
          </div>
        ))}
      </dl>
    </DashCard>
  );
}

/** Today's biggest dollar moves, so a bad day reads as "which names", not just a total. */
function MoversCard({ rows }: { rows: PositionRow[] }) {
  const { up, down, known } = useMemo(() => dayMovers(rows), [rows]);
  const all = useMemo(() => dayMovers(rows, rows.length), [rows]);
  const total = known && rows.every((r) => r.day_pl != null) ? rows.reduce((a, r) => a + (r.day_pl ?? 0), 0) : null;
  const line = (r: PositionRow) => ({
    key: r.symbol, label: r.symbol, aside: fmtPct(r.change_pct), value: signed(r.day_pl), valueClass: tone(r.day_pl),
  });
  const byDay = [...all.up, ...all.down.slice().reverse()];
  const maxAbs = Math.max(1, ...byDay.map((r) => Math.abs(r.day_pl ?? 0)));
  return (
    <DashCard title="Today's movers" meta={<span className={tone(total)}>{signed(total)}</span>}
              detail={byDay.length ? (
                <ul className="space-y-1 text-xs tabular-nums">
                  {byDay.map((r) => {
                    const v = r.day_pl ?? 0;
                    return (
                      <li key={r.symbol} className="grid grid-cols-[5rem_4rem_1fr_5.5rem] items-center gap-2">
                        <span className="font-semibold text-white">{r.symbol}</span>
                        <span className="text-slate-400">{fmtPct(r.change_pct)}</span>
                        <span className="relative h-2 rounded bg-slate-800">
                          <span className={`absolute inset-y-0 rounded ${v >= 0 ? "left-1/2 bg-emerald-400" : "right-1/2 bg-rose-400"}`}
                                style={{ width: `${(Math.abs(v) / maxAbs) * 50}%` }} />
                        </span>
                        <span className={`text-right ${tone(v)}`}>{signed(r.day_pl)}</span>
                      </li>
                    );
                  })}
                </ul>
              ) : <p className="text-sm text-slate-400">No moves yet today.</p>}
              detailTitle="Today's moves, every position">
      {!known && rows.length > 0 ? (
        <p className="text-xs text-slate-500">Day P&amp;L —</p>
      ) : up.length + down.length === 0 ? (
        <p className="text-xs text-slate-500">No moves yet</p>
      ) : (
        <div className="space-y-1">
          <PeekRows rows={up.map(line)} empty="No gainers" />
          <PeekRows rows={down.map(line)} empty="No losers" />
        </div>
      )}
    </DashCard>
  );
}

type SortKey = "symbol" | "qty" | "avg" | "last" | "change" | "day" | "ah" | "cost" | "value" | "weight" | "unrealized";
const SIGNED_SORT: ReadonlySet<SortKey> = new Set(["change", "day", "ah", "unrealized"]);

const COLUMNS: { key: SortKey; label: string; read: (r: PositionRow) => number | string | null | undefined }[] = [
  { key: "qty", label: "Shares", read: (r) => r.qty },
  { key: "avg", label: "Avg price", read: (r) => r.avg_price },
  { key: "last", label: "Last", read: (r) => r.last_price },
  { key: "change", label: "Chg %", read: (r) => r.change_pct },
  { key: "day", label: "Day P&L", read: (r) => r.day_pl },
  { key: "ah", label: "AH %", read: (r) => r.ah_change_pct },
  { key: "cost", label: "Cost basis", read: (r) => r.cost_basis },
  { key: "value", label: "Market value", read: (r) => r.market_value },
  { key: "weight", label: "% book", read: (r) => r.pct_of_book },
  { key: "unrealized", label: "Unrealized", read: (r) => r.unrealized_pl },
];

/** Positions: the count, open P&L and the five largest holdings; opens to
 * the account as the broker holds it -- one row per ticker, every column
 * sortable, a filter and a heatmap view. */
function PositionsCard({ rows, cashRow }: { rows: PositionRow[]; cashRow: PositionRow | undefined }) {
  const unrealized = rows.length && rows.every((r) => r.unrealized_pl != null)
    ? rows.reduce((a, r) => a + (r.unrealized_pl ?? 0), 0) : null;
  const top = useMemo(() => [...rows].sort((a, b) => Math.abs(b.market_value) - Math.abs(a.market_value)).slice(0, PEEK), [rows]);
  return (
    <DashCard title="Positions" className="md:col-span-2" value={rows.length}
              meta={<>Open <span className={tone(unrealized)}>{signed(unrealized)}</span></>}
              detail={<PositionsTable rows={rows} cashRow={cashRow} />} detailTitle={`Positions · ${rows.length}`}>
      <PeekRows empty="No open positions. Cash only." rows={top.map((r) => ({
        key: `${r.symbol}-${r.idea ?? ""}`, label: contractLabel(r.symbol) ?? r.symbol,
        aside: `${money(r.market_value)} · ${r.pct_of_book == null ? "—" : `${r.pct_of_book.toFixed(1)}%`}`,
        value: signed(r.unrealized_pl), valueClass: tone(r.unrealized_pl),
      }))} />
    </DashCard>
  );
}

function PositionsTable({ rows, cashRow }: { rows: PositionRow[]; cashRow: PositionRow | undefined }) {
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "value", desc: true });
  const [heatmap, setHeatmap] = useState(false);
  const [q, setQ] = useState("");
  const ordered = useMemo(() => {
    const read = sort.key === "symbol" ? (r: PositionRow) => r.symbol : COLUMNS.find((c) => c.key === sort.key)!.read;
    const needle = q.trim().toUpperCase();
    const sorted = rows.filter((r) => !needle || r.symbol.toUpperCase().includes(needle) || (r.sector ?? "").toUpperCase().includes(needle))
      .sort((a, b) => {
        const x = read(a), y = read(b);
        if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
        const order = typeof x === "string" ? x.localeCompare(String(y))
          : SIGNED_SORT.has(sort.key) ? x - Number(y) : Math.abs(x) - Math.abs(Number(y));
        return sort.desc ? -order : order;
      });
    return withOptionsUnderStock(sorted);
  }, [rows, sort, q]);
  const maxPl = Math.max(1, ...rows.map((r) => Math.abs(r.unrealized_pl ?? 0)));
  const head = (key: SortKey, label: string, align = "text-right") => (
    <th key={key} scope="col" aria-sort={sort.key === key ? (sort.desc ? "descending" : "ascending") : "none"}
        className={`whitespace-nowrap px-2 py-1.5 font-medium ${align}`}>
      <button type="button" onClick={() => setSort({ key, desc: sort.key === key ? !sort.desc : key !== "symbol" })}
              className="inline-flex items-center gap-0.5 rounded hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400">
        {label}
        {sort.key === key && (sort.desc ? <ArrowDown className="h-3 w-3" aria-hidden="true" /> : <ArrowUp className="h-3 w-3" aria-hidden="true" />)}
      </button>
    </th>
  );
  if (rows.length === 0) return <p className="text-sm text-slate-400">No open positions. Cash only.</p>;
  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-3">
        <FilterBox value={q} onChange={setQ} label="Filter positions" />
        <label className="flex items-center gap-1.5 text-xs text-slate-400">
          <input type="checkbox" checked={heatmap} onChange={(e) => setHeatmap(e.target.checked)} className="h-3.5 w-3.5 accent-emerald-400" />
          Heatmap
        </label>
      </div>
      {heatmap ? (
        <div className="flex flex-wrap gap-1" role="img" aria-label={ordered.map((r) => `${r.symbol} ${fmtPct(r.change_pct)}`).join(", ")}>
          {ordered.map((r) => {
            const chg = r.change_pct ?? 0;
            const intensity = Math.min(1, Math.abs(chg) / 5) * 0.5 + 0.07;
            const bg = r.change_pct == null ? "rgba(100,116,139,0.25)"
              : chg >= 0 ? `rgba(52,211,153,${intensity})` : `rgba(251,113,133,${intensity})`;
            return (
              <div key={`${r.symbol}-${r.idea ?? ""}`} className="flex h-16 min-w-[5.5rem] flex-col justify-between rounded p-1.5"
                   style={{ background: bg, flexGrow: Math.max(1, Math.abs(r.market_value) / 1000) }}>
                <span className="text-xs font-semibold text-white">{r.symbol}</span>
                <span className="text-[11px] tabular-nums text-slate-100">{fmtPct(r.change_pct)} · {fmtUsd(r.day_pl, { signed: true, whole: true })}</span>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[60rem] text-[13px] tabular-nums">
            <thead className="text-left text-xs text-slate-400">
              <tr>{head("symbol", "Instrument", "text-left")}{COLUMNS.map((c) => head(c.key, c.label))}</tr>
            </thead>
            <tbody>
              {ordered.map((r) => {
                const pl = r.unrealized_pl ?? 0;
                return (
                  <tr key={`${r.symbol}-${r.idea ?? ""}`} className="border-t border-slate-800/80 text-slate-200">
                    <td className="whitespace-nowrap px-2 py-1.5"><span className="font-semibold text-white">{contractLabel(r.symbol) ?? r.symbol}</span></td>
                    <td className="px-2 py-1.5 text-right">{r.qty == null ? "—" : r.qty}</td>
                    <td className="px-2 py-1.5 text-right">{price(r.avg_price)}</td>
                    <td className="px-2 py-1.5 text-right">{price(r.last_price)}</td>
                    <td className={`px-2 py-1.5 text-right ${tone(r.change_pct)}`}>{fmtPct(r.change_pct)}</td>
                    <td className={`px-2 py-1.5 text-right ${tone(r.day_pl)}`}>{signed(r.day_pl)}</td>
                    <td className={`px-2 py-1.5 text-right ${tone(r.ah_change_pct)}`}>{r.ah_change_pct == null ? "—" : fmtPct(r.ah_change_pct)}</td>
                    <td className="px-2 py-1.5 text-right">{money(r.cost_basis)}</td>
                    <td className="px-2 py-1.5 text-right">{money(r.market_value)}</td>
                    <td className="px-2 py-1.5 text-right">
                      {r.pct_of_book == null ? "—" : `${r.pct_of_book.toFixed(1)}%`}
                      <span className="ml-auto mt-0.5 block h-1 w-16 rounded bg-slate-800">
                        <span className="block h-full rounded bg-slate-400" style={{ width: `${Math.min(100, r.pct_of_book ?? 0)}%` }} />
                      </span>
                    </td>
                    <td className="px-2 py-1.5 text-right">
                      <span className={tone(r.unrealized_pl)}>{signed(r.unrealized_pl)}</span>
                      <span className="relative ml-auto mt-0.5 block h-1 w-16 rounded bg-slate-800">
                        <span className="absolute inset-y-0 left-1/2 w-px bg-slate-600" />
                        <span className={`absolute inset-y-0 rounded ${pl >= 0 ? "bg-emerald-400" : "bg-rose-400"}`}
                              style={pl >= 0
                                ? { left: "50%", width: `${(Math.abs(pl) / maxPl) * 50}%` }
                                : { right: "50%", width: `${(Math.abs(pl) / maxPl) * 50}%` }} />
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {cashRow && <p className="pt-2 text-[11px] text-slate-500">Cash {money(cashRow.market_value)}, outside the table.</p>}
    </div>
  );
}

type IdeaSort = "value" | "today" | "open" | "realized" | "return";

/** The scorecard's key for a row or a closed trade: a manual holding is
 * carded per symbol ("GLD (manual)") while its rows and trades still
 * carry the backend's manual label. Lookups must use the card's key. */
const MANUAL_IDEA = "No idea yet (manual)";
export const cardKeyFor = (idea: string | null | undefined, symbol: string): string =>
  idea && idea !== MANUAL_IDEA ? idea : `${symbol} (manual)`;

type Card = ReturnType<typeof ideaScorecard>[number];

const IdeaName = ({ c, raised }: { c: Card; raised?: boolean }) => (c.id != null ? (
  <Link to={`/workshop/${c.id}`} className={`line-clamp-1 hover:text-white hover:underline underline-offset-2 ${raised ? "relative z-10" : ""}`}>{c.idea}</Link>
) : <span className="line-clamp-1">{c.idea}</span>);

/** By idea: the count, tested-vs-discretionary realized and the five
 * largest ideas; opens to one expandable row per idea -- value, weight
 * against its set size, today, open and realized P&L, return -- each
 * expanding to the idea's own slice of each ticker. */
function ByIdeaCard({ rows, equity, liveIdeas, book }: {
  rows: PositionRow[];
  equity: number | null;
  liveIdeas: { id: number; title: string; size_pct: number | null }[];
  book: string;
}) {
  const { data: closed } = useApi<ClosedPayload>(`/api/portfolio/closed?book=${book}`, REFRESH_MS);
  const cards = useMemo(() => ideaScorecard(rows, equity, liveIdeas), [rows, equity, liveIdeas]);
  const realizedByIdea = useMemo(() => {
    const out = new Map<string, number>();
    for (const t of closed?.trades ?? []) {
      const key = cardKeyFor(t.idea, t.symbol);
      out.set(key, (out.get(key) ?? 0) + t.pnl);
    }
    return out;
  }, [closed]);
  const split = closed?.results_split;
  return (
    <DashCard title="By idea" className="md:col-span-2" value={cards.length}
              meta={split ? <>Tested <span className={tone(split.tested.pnl)}>{signed(split.tested.pnl)}</span> · Discretionary <span className={tone(split.discretionary.pnl)}>{signed(split.discretionary.pnl)}</span></> : undefined}
              detail={<ByIdeaTable cards={cards} rows={rows} realizedByIdea={realizedByIdea} closed={closed} />}
              detailTitle={`By idea · ${cards.length} ideas`}>
      <ul className="divide-y divide-slate-800/70 text-xs tabular-nums" data-peek="">
        {cards.slice(0, PEEK).map((c) => (
          <li key={c.idea} className={`flex items-baseline gap-2 py-1 ${c.id == null && c.idea.endsWith("(manual)") ? "text-slate-400" : "text-slate-200"}`}>
            <span className="min-w-0 font-medium"><IdeaName c={c} raised /></span>
            <span className="shrink-0 text-slate-500">{c.pct != null ? `${c.pct.toFixed(1)}%` : "—"}</span>
            <span className={`ml-auto shrink-0 ${tone(c.unrealized)}`}>{c.positions && c.unrealized != null ? signed(c.unrealized) : "—"}</span>
          </li>
        ))}
        {cards.length === 0 && <li className="py-1 text-slate-500">No ideas holding anything</li>}
      </ul>
    </DashCard>
  );
}

function ByIdeaTable({ cards, rows, realizedByIdea, closed }: {
  cards: Card[]; rows: PositionRow[]; realizedByIdea: Map<string, number>; closed: ClosedPayload | null;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: IdeaSort; desc: boolean }>({ key: "value", desc: true });
  const read = (c: Card): number | null => {
    switch (sort.key) {
      case "value": return c.value;
      case "today": return c.day_pl;
      case "open": return c.unrealized;
      case "realized": return realizedByIdea.get(c.idea) ?? null;
      case "return": return c.return_pct;
    }
  };
  const ordered = useMemo(() => [...cards].sort((a, b) => {
    const x = read(a), y = read(b);
    if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
    return sort.desc ? y - x : x - y;
  }), [cards, sort, realizedByIdea]);  // eslint-disable-line react-hooks/exhaustive-deps
  const scale = Math.max(10, ...cards.map((c) => Math.max(c.pct ?? 0, c.target_pct ?? 0)));
  const known = cards.some((c) => c.target_pct != null);
  const headBtn = (key: IdeaSort, label: string) => (
    <button type="button" onClick={() => setSort({ key, desc: sort.key === key ? !sort.desc : true })}
            className="inline-flex items-center gap-0.5 rounded hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400">
      {label}
      {sort.key === key && (sort.desc ? <ArrowDown className="h-3 w-3" aria-hidden="true" /> : <ArrowUp className="h-3 w-3" aria-hidden="true" />)}
    </button>
  );
  return (
    <div>
      <p className="mb-2 text-xs text-slate-500">{known ? "Bar: held · tick: set size" : "Bar: % of book"}</p>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[40rem] text-xs tabular-nums">
          <thead>
            <tr className="text-left text-xs text-slate-500">
              <th className="pb-1 pr-3 font-medium">Idea</th>
              <th className="pb-1 pr-3 font-medium">Size</th>
              <th className="pb-1 pr-3 text-right font-medium">{headBtn("value", "Value")}</th>
              <th className="pb-1 pr-3 text-right font-medium">{headBtn("today", "Today")}</th>
              <th className="pb-1 pr-3 text-right font-medium">{headBtn("open", "Open P&L")}</th>
              <th className="pb-1 text-right font-medium">{headBtn("realized", "Realized")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/70">
            {ordered.map((c) => {
              const manual = c.id == null && c.idea.endsWith("(manual)");
              const off = c.target_pct != null && c.pct != null ? c.pct - c.target_pct : null;
              const realized = realizedByIdea.get(c.idea);
              const slices = rows.filter((r) => cardKeyFor(r.idea, r.symbol) === c.idea);
              const isOpen = expanded === c.idea;
              return [
                <tr key={c.idea} className={manual ? "text-slate-400" : "text-slate-200"}>
                  <td className="max-w-[22rem] py-1 pr-3">
                    <span className="inline-flex items-center gap-1">
                      <button type="button" aria-expanded={isOpen} aria-label={`Slices of ${c.idea}`}
                              onClick={() => setExpanded(isOpen ? null : c.idea)}
                              className="rounded hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400">
                        {isOpen ? <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" /> : <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />}
                      </button>
                      <IdeaName c={c} />
                    </span>
                    <div className="text-[11px] text-slate-500">
                      {c.positions === 0 ? "nothing held yet" : `${c.positions} position${c.positions === 1 ? "" : "s"}`}
                    </div>
                  </td>
                  <td className="w-44 py-1 pr-3">
                    <div className="relative h-1.5 rounded-full bg-slate-800" role="img"
                         aria-label={`${c.pct != null ? `${c.pct.toFixed(1)}% of the book` : "share of the book unknown"}${c.target_pct != null ? `, set size ${c.target_pct}%` : ""}`}>
                      <div className={`absolute inset-y-0 left-0 rounded-full ${manual ? "bg-slate-500" : "bg-emerald-400/80"}`}
                           style={{ width: `${Math.min(100, ((c.pct ?? 0) / scale) * 100)}%` }} />
                      {c.target_pct != null && (
                        <div className="absolute -top-1 h-3.5 w-px bg-slate-200" style={{ left: `${Math.min(100, (c.target_pct / scale) * 100)}%` }} />
                      )}
                    </div>
                    <div className="mt-1 text-[11px] text-slate-400">
                      {c.pct != null ? `${c.pct.toFixed(1)}%` : "—"}
                      {off != null && Math.abs(off) >= 1 && (
                        <span className="text-amber-300"> · {off > 0 ? `${off.toFixed(1)} pts over` : `${(-off).toFixed(1)} pts under`}</span>
                      )}
                    </div>
                  </td>
                  <td className="py-1 pr-3 text-right">{fmtUsd(c.value, { whole: true })}</td>
                  <td className={`py-1 pr-3 text-right ${tone(c.day_pl)}`}>{c.positions && c.day_pl != null ? signed(c.day_pl) : "—"}</td>
                  <td className={`py-1 pr-3 text-right ${tone(c.unrealized)}`}>
                    {c.positions && c.unrealized != null ? signed(c.unrealized) : "—"}
                    {c.return_pct != null && <div className="text-[11px]">{fmtPct(c.return_pct)}</div>}
                  </td>
                  <td className={`py-1 text-right ${tone(realized)}`}>{realized != null ? signed(realized) : "—"}</td>
                </tr>,
                ...(isOpen ? [
                  <tr key={`${c.idea}-slices`} className="bg-slate-900/40 text-slate-400">
                    <td colSpan={6} className="py-1 pl-8 pr-3">
                      {slices.length === 0 ? "Nothing held under this idea right now." : (
                        <ul className="space-y-0.5">
                          {slices.map((r) => (
                            <li key={`${r.symbol}-${r.idea ?? ""}`}>
                              <span className="font-medium text-slate-200">{r.symbol}</span>{" "}
                              {r.qty ?? "—"} sh · {money(r.market_value)} · today {signed(r.day_pl)} · open {signed(r.unrealized_pl)}
                            </li>
                          ))}
                        </ul>
                      )}
                    </td>
                  </tr>,
                ] : []),
              ];
            })}
          </tbody>
        </table>
      </div>
      {closed?.results_split && (
        <p className="mt-2 border-t border-slate-800/70 pt-1.5 text-xs tabular-nums text-slate-400">
          Tested ideas <span className={tone(closed.results_split.tested.pnl)}>{fmtUsd(closed.results_split.tested.pnl, { signed: true })}</span>
          {" · "}Discretionary <span className={tone(closed.results_split.discretionary.pnl)}>{fmtUsd(closed.results_split.discretionary.pnl, { signed: true })}</span>
        </p>
      )}
    </div>
  );
}
