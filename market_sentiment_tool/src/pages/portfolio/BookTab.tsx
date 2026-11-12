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
import { Box, money, price, REFRESH_MS, signed } from "./shared";

/** Tab 1: Book (2026-11-12 redesign). Composition first, readable without
 * scrolling; then the positions the broker holds, one row per ticker with
 * no idea information at all; then By idea, where the idea information
 * lives, as expandable rows. Today's movers come from tickers, not
 * slices. */
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
    <div className="space-y-2">
      <CompositionSection data={data} aggRows={aggRows} cashRow={cashRow} />
      <PositionsSection rows={aggRows} cashRow={cashRow} />
      <ByIdea rows={rows} equity={data.scoreboard.equity} liveIdeas={liveIdeas} book={book} />
      <MoversBox rows={aggRows} />
    </div>
  );
}

/** One full-width stacked bar of sectors, labelled inside, with the
 * ticker treemap under it. The bar is the legend. A toggle reads the
 * same bar by idea instead. */
function CompositionSection({ data, aggRows, cashRow }: {
  data: PortfolioPayload;
  aggRows: PositionRow[];
  cashRow: PositionRow | undefined;
}) {
  const [grouping, setGrouping] = useState<"sector" | "idea">("sector");
  const segments = useMemo(() => {
    if (grouping === "idea") {
      const out = data.composition
        .filter((c) => (c.pct_of_book ?? 0) > 0)
        .map((c, i) => ({
          label: c.idea, pct: c.pct_of_book ?? 0,
          color: ["#34d399", "#38bdf8", "#a78bfa", "#f472b6", "#fb923c", "#2dd4bf"][i % 6],
        }));
      // The bar is the whole book in both groupings: cash rides along
      // (the composition read itself groups holdings by idea only).
      if (cashRow?.pct_of_book) out.push({ label: "Cash", pct: cashRow.pct_of_book, color: sectorColor("Cash") });
      return out.sort((a, b) => b.pct - a.pct);
    }
    const bySector = new Map<string, number>();
    for (const r of aggRows) {
      const sector = r.sector ?? "Other";
      bySector.set(sector, (bySector.get(sector) ?? 0) + (r.pct_of_book ?? 0));
    }
    const out = [...bySector.entries()].map(([label, pct]) => ({
      label, pct, color: sectorColor(label),
    }));
    if (cashRow?.pct_of_book) out.push({ label: "Cash", pct: cashRow.pct_of_book, color: sectorColor("Cash") });
    return out.sort((a, b) => b.pct - a.pct);
  }, [grouping, data.composition, aggRows, cashRow]);
  const total = segments.reduce((sum, s) => sum + s.pct, 0) || 1;
  return (
    <section aria-label="Composition" className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-white">Composition</h2>
        <div role="group" aria-label="Composition grouping" className="flex gap-1">
          {(["sector", "idea"] as const).map((g) => (
            <button key={g} type="button" aria-pressed={g === grouping} onClick={() => setGrouping(g)}
                    className={`rounded px-2 py-0.5 text-xs capitalize focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 ${g === grouping ? "bg-slate-700 font-semibold text-white" : "text-slate-400 hover:text-white"}`}>
              {g === "sector" ? "Sectors" : "Ideas"}
            </button>
          ))}
        </div>
      </div>
      <div className="mt-2 flex h-7 w-full overflow-hidden rounded" role="img"
           aria-label={segments.map((s) => `${s.label} ${s.pct.toFixed(0)}%`).join(", ")}>
        {segments.map((s) => (
          <div key={s.label} className="flex min-w-0 items-center overflow-hidden px-1.5"
               style={{ width: `${(s.pct / total) * 100}%`, background: s.color }} title={`${s.label} ${s.pct.toFixed(1)}%`}>
            {s.pct / total >= 0.06 && (
              <span className="truncate text-[11px] font-medium text-slate-950">
                {s.label} {s.pct.toFixed(0)}
              </span>
            )}
          </div>
        ))}
      </div>
      <div className="mt-2">
        <CompositionBox positions={data.positions} composition={data.composition}
                        aggregate={cashRow ? [...aggRows, cashRow] : aggRows} />
      </div>
    </section>
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

/** The account as the broker holds it: one row per ticker, no idea
 * information at all. Every column sorts; the Heatmap switch turns the
 * table into tiles sized by weight and coloured by today's move. */
function PositionsSection({ rows, cashRow }: {
  rows: PositionRow[];
  cashRow: PositionRow | undefined;
}) {
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "value", desc: true });
  const [heatmap, setHeatmap] = useState(false);
  const ordered = useMemo(() => {
    const read = sort.key === "symbol" ? (r: PositionRow) => r.symbol : COLUMNS.find((c) => c.key === sort.key)!.read;
    const sorted = [...rows].sort((a, b) => {
      const x = read(a), y = read(b);
      if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1;
      const order = typeof x === "string" ? x.localeCompare(String(y))
        : SIGNED_SORT.has(sort.key) ? x - Number(y) : Math.abs(x) - Math.abs(Number(y));
      return sort.desc ? -order : order;
    });
    return withOptionsUnderStock(sorted);
  }, [rows, sort]);
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
  return (
    <section aria-label="Positions" className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <div className="flex items-center justify-between gap-3 px-1">
        <h2 className="text-sm font-semibold text-white">Positions · {rows.length}</h2>
        <label className="flex items-center gap-1.5 text-xs text-slate-400">
          <input type="checkbox" checked={heatmap} onChange={(e) => setHeatmap(e.target.checked)}
                 className="h-3.5 w-3.5 accent-emerald-400" />
          Heatmap
        </label>
      </div>
      {rows.length === 0 ? (
        <p className="px-1 pt-2 text-sm text-slate-400">No open positions. Cash only.</p>
      ) : heatmap ? (
        <div className="flex flex-wrap gap-1 pt-2" role="img"
             aria-label={rows.map((r) => `${r.symbol} ${fmtPct(r.change_pct)}`).join(", ")}>
          {ordered.map((r) => {
            const chg = r.change_pct ?? 0;
            const intensity = Math.min(1, Math.abs(chg) / 5) * 0.5 + 0.07;
            const bg = r.change_pct == null ? "rgba(100,116,139,0.25)"
              : chg >= 0 ? `rgba(52,211,153,${intensity})` : `rgba(251,113,133,${intensity})`;
            return (
              <div key={`${r.symbol}-${r.idea ?? ""}`} className="flex h-16 min-w-[5.5rem] flex-col justify-between rounded p-1.5"
                   style={{ background: bg, flexGrow: Math.max(1, Math.abs(r.market_value) / 1000) }}>
                <span className="text-xs font-semibold text-white">{r.symbol}</span>
                <span className="text-[11px] tabular-nums text-slate-100">
                  {fmtPct(r.change_pct)} · {fmtUsd(r.day_pl, { signed: true, whole: true })}
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="-mx-3 overflow-x-auto px-3 pt-1">
          <table className="w-full min-w-[60rem] text-[13px] tabular-nums">
            <thead className="text-left text-xs text-slate-400">
              <tr>
                {head("symbol", "Instrument", "text-left")}
                {COLUMNS.map((c) => head(c.key, c.label))}
              </tr>
            </thead>
            <tbody>
              {ordered.map((r) => {
                const pl = r.unrealized_pl ?? 0;
                return (
                  <tr key={`${r.symbol}-${r.idea ?? ""}`} className="border-t border-slate-800/80 text-slate-200">
                    <td className="whitespace-nowrap px-2 py-1.5">
                      <span className="font-semibold text-white">
                        {contractLabel(r.symbol) ?? r.symbol}
                      </span>
                    </td>
                    <td className="px-2 py-1.5 text-right">{r.qty == null ? "—" : r.qty}</td>
                    <td className="px-2 py-1.5 text-right">{price(r.avg_price)}</td>
                    <td className="px-2 py-1.5 text-right">{price(r.last_price)}</td>
                    <td className={`px-2 py-1.5 text-right ${tone(r.change_pct)}`}>{fmtPct(r.change_pct)}</td>
                    <td className={`px-2 py-1.5 text-right ${tone(r.day_pl)}`}>{signed(r.day_pl)}</td>
                    <td className={`px-2 py-1.5 text-right ${tone(r.ah_change_pct)}`}>
                      {r.ah_change_pct == null ? "—" : fmtPct(r.ah_change_pct)}
                    </td>
                    <td className="px-2 py-1.5 text-right">{money(r.cost_basis)}</td>
                    <td className="px-2 py-1.5 text-right">{money(r.market_value)}</td>
                    <td className="px-2 py-1.5 text-right">
                      {r.pct_of_book == null ? "—" : `${r.pct_of_book.toFixed(1)}%`}
                      <span className="mt-0.5 block h-1 w-16 ml-auto rounded bg-slate-800">
                        <span className="block h-full rounded bg-slate-400"
                              style={{ width: `${Math.min(100, r.pct_of_book ?? 0)}%` }} />
                      </span>
                    </td>
                    <td className="px-2 py-1.5 text-right">
                      <span className={tone(r.unrealized_pl)}>{signed(r.unrealized_pl)}</span>
                      <span className="relative mt-0.5 block h-1 w-16 ml-auto rounded bg-slate-800">
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
      {cashRow && <p className="px-1 pt-1 text-[11px] text-slate-500">Cash {money(cashRow.market_value)} sits outside the table.</p>}
    </section>
  );
}

type IdeaSort = "value" | "today" | "open" | "realized" | "return";

/** The scorecard's key for a row or a closed trade: a manual holding is
 * carded per symbol ("GLD (manual)") while its rows and trades still
 * carry the backend's manual label. Lookups must use the card's key. */
const MANUAL_IDEA = "No idea yet (manual)";
export const cardKeyFor = (idea: string | null | undefined, symbol: string): string =>
  idea && idea !== MANUAL_IDEA ? idea : `${symbol} (manual)`;

/** By idea: where the idea information lives. One expandable row per
 * idea -- value, weight against its set size, today, open and realized
 * P&L, return -- expanding to the idea's own slice of each ticker, so
 * the slices add up to the Positions row. Tested ideas and discretionary
 * trades are totalled separately at the foot. */
function ByIdea({ rows, equity, liveIdeas, book }: {
  rows: PositionRow[];
  equity: number | null;
  liveIdeas: { id: number; title: string; size_pct: number | null }[];
  book: string;
}) {
  const { data: closed } = useApi<ClosedPayload>(`/api/portfolio/closed?book=${book}`, REFRESH_MS);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [sort, setSort] = useState<{ key: IdeaSort; desc: boolean }>({ key: "value", desc: true });
  const cards = useMemo(() => ideaScorecard(rows, equity, liveIdeas), [rows, equity, liveIdeas]);
  const realizedByIdea = useMemo(() => {
    const out = new Map<string, number>();
    for (const t of closed?.trades ?? []) {
      const key = cardKeyFor(t.idea, t.symbol);
      out.set(key, (out.get(key) ?? 0) + t.pnl);
    }
    return out;
  }, [closed]);
  const read = (c: (typeof cards)[number]): number | null => {
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
    <Box title={`By idea · ${cards.length} ideas`}
         right={<span className="text-xs text-slate-500">{known ? "bar: held · tick: set size" : "bar: % of book"}</span>}>
      <div className="overflow-x-auto">
        <table className="w-full text-xs tabular-nums">
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
                      {c.id != null ? (
                        <Link to={`/workshop/${c.id}`} className="line-clamp-1 hover:text-white hover:underline underline-offset-2">{c.idea}</Link>
                      ) : (
                        <span className="line-clamp-1">{c.idea}</span>
                      )}
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
                  <td className={`py-1 pr-3 text-right ${tone(c.day_pl)}`}>{c.positions && c.day_pl != null ? fmtUsd(c.day_pl, { signed: true, whole: true }) : "—"}</td>
                  <td className={`py-1 pr-3 text-right ${tone(c.unrealized)}`}>
                    {c.positions && c.unrealized != null ? fmtUsd(c.unrealized, { signed: true, whole: true }) : "—"}
                    {c.return_pct != null && <div className="text-[11px]">{fmtPct(c.return_pct)}</div>}
                  </td>
                  <td className={`py-1 text-right ${tone(realized)}`}>
                    {realized != null ? fmtUsd(realized, { signed: true, whole: true }) : "—"}
                  </td>
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
    </Box>
  );
}

/** Today's biggest dollar moves, so a bad day reads as "which names", not just a total. */
function MoversBox({ rows }: { rows: PositionRow[] }) {
  const { up, down, known } = useMemo(() => dayMovers(rows), [rows]);
  const line = (r: PositionRow) => (
    <li key={r.symbol} className="flex items-baseline justify-between gap-2 py-1">
      <span className="font-medium text-slate-200">{r.symbol}</span>
      <span className="text-xs text-slate-500">{fmtPct(r.change_pct)}</span>
      <span className={`ml-auto tabular-nums ${tone(r.day_pl)}`}>{fmtUsd(r.day_pl, { signed: true, whole: true })}</span>
    </li>
  );
  return (
    <Box title="Today's movers">
      {!known && rows.length > 0 ? (
        <p className="text-sm text-slate-400">Today's P&amp;L isn't available right now.</p>
      ) : up.length + down.length === 0 ? (
        <p className="text-sm text-slate-400">No moves yet today.</p>
      ) : (
        <div className="grid grid-cols-2 gap-4 text-sm">
          <div><div className="text-xs text-slate-500">Gaining</div><ul>{up.map(line)}</ul>{!up.length && <p className="py-1 text-slate-500">None</p>}</div>
          <div><div className="text-xs text-slate-500">Losing</div><ul>{down.map(line)}</ul>{!down.length && <p className="py-1 text-slate-500">None</p>}</div>
        </div>
      )}
    </Box>
  );
}
