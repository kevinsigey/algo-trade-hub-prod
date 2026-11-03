import { useMemo, useState } from "react";
import { Maximize2, X } from "lucide-react";
import { ResponsiveContainer, Treemap } from "recharts";

import { fmtUsd, tone, type PortfolioPayload, type PositionRow } from "@/lib/paperPortfolio";

/** The Composition box, rebuilt (Kevin, 2026-11-02): the treemap tiles are
 * colored BY SECTOR with a labeled legend (sector + total weight), the tiles
 * group By sector (sector super-tiles) or By idea (attribution bands, sector
 * colors kept), hovering a tile reads out its full line -- ticker, sector,
 * value, weight, shares, idea -- and the box pops out into the site's
 * overlay sheet (the PlayCheck pattern) at reading size. Sectors come from
 * the backend's curated map (tradehub/portfolio/sectors.py); a position
 * without one reads "Other". */

export const SECTOR_COLORS: Record<string, string> = {
  Technology: "#38bdf8",
  Energy: "#fb923c",
  Financials: "#a78bfa",
  "Health Care": "#34d399",
  "Consumer Staples": "#f472b6",
  Utilities: "#2dd4bf",
  "Communication Services": "#f43f5e",
  "Consumer Discretionary": "#e879f9",
  Industrials: "#94a3b8",
  Materials: "#a3e635",
  "Real Estate": "#fda4af",
  "Broad Market": "#818cf8",
  "Commodities (Gold)": "#eab308",
  "Commodities (Oil)": "#d97706",
  "Commodities (Silver)": "#cbd5e1",
  Commodities: "#a16207",
  Bonds: "#60a5fa",
  Cash: "#475569",
  Other: "#64748b",
};

export function sectorColor(sector: string): string {
  return SECTOR_COLORS[sector] ?? "#64748b";
}

type Grouping = "sector" | "idea";

interface Tile {
  symbol: string;
  sector: string;
  qty: number | null;
  side: string | null;
  market_value: number;
  pct: number | null;
  idea: string | null;
}

function toTile(p: PositionRow): Tile {
  return {
    symbol: p.symbol,
    sector: p.sector ?? (p.symbol === "Cash" ? "Cash" : "Other"),
    qty: p.qty,
    side: p.side,
    market_value: p.market_value,
    pct: p.pct_of_book,
    idea: p.idea,
  };
}

function groupName(tile: Tile, grouping: Grouping): string {
  if (grouping === "sector") return tile.sector;
  return tile.idea ?? (tile.symbol === "Cash" ? "Cash" : "No idea yet (manual)");
}

interface Group {
  name: string;
  sector: string | null;
  pct: number;
  children: ({ name: string; size: number } & Tile)[];
}

function buildGroups(tiles: Tile[], grouping: Grouping): Group[] {
  const byName = new Map<string, Group>();
  for (const tile of tiles) {
    const name = groupName(tile, grouping);
    const group = byName.get(name) ?? {
      name,
      sector: grouping === "sector" ? tile.sector : null,
      pct: 0,
      children: [],
    };
    group.pct += tile.pct ?? 0;
    group.children.push({ ...tile, name: tile.symbol, size: Math.abs(tile.market_value) });
    byName.set(name, group);
  }
  const groups = [...byName.values()];
  for (const g of groups) g.children.sort((a, b) => b.size - a.size);
  return groups.sort((a, b) =>
    b.children.reduce((s, c) => s + c.size, 0) - a.children.reduce((s, c) => s + c.size, 0));
}

function sectorTotals(tiles: Tile[]): { sector: string; pct: number }[] {
  const totals = new Map<string, number>();
  for (const t of tiles) totals.set(t.sector, (totals.get(t.sector) ?? 0) + (t.pct ?? 0));
  return [...totals.entries()].map(([sector, pct]) => ({ sector, pct })).sort((a, b) => b.pct - a.pct);
}

type NodeProps = {
  x?: number; y?: number; width?: number; height?: number; depth?: number;
  name?: string; pct?: number; sector?: string | null;
  symbol?: string; qty?: number | null; side?: string | null;
  market_value?: number; idea?: string | null;
  onHover?: (tile: Tile | null) => void;
};

/** One treemap node: depth 1 is a group band (sector super-tile or idea
 * band) with its label; depth 2 is a holding tile, colored by sector. */
function Node(props: NodeProps) {
  const { x = 0, y = 0, width = 0, height = 0, depth = 0, name } = props;
  if (depth === 1) {
    const color = props.sector ? sectorColor(props.sector) : "#94a3b8";
    return (
      <g>
        <rect x={x} y={y} width={width} height={height}
              fill={props.sector ? color : "#1e293b"} fillOpacity={props.sector ? 0.16 : 0.5}
              stroke="#020617" strokeWidth={2} />
        {width > 70 && height > 30 && (
          <text x={x + 8} y={y + 16} fill={color} fontSize={11} fontWeight={700}
                style={{ textTransform: "uppercase", letterSpacing: "0.04em" }}>
            {name}{props.pct != null ? ` · ${props.pct.toFixed(0)}%` : ""}
          </text>
        )}
      </g>
    );
  }
  if (depth !== 2 || !props.symbol) return <g />;
  const tile: Tile = {
    symbol: props.symbol, sector: props.sector ?? "Other", qty: props.qty ?? null,
    side: props.side ?? null, market_value: props.market_value ?? 0,
    pct: props.pct ?? null, idea: props.idea ?? null,
  };
  const color = sectorColor(tile.sector);
  return (
    <g data-testid={`tile-${tile.symbol}`}
       onMouseEnter={() => props.onHover?.(tile)} onMouseLeave={() => props.onHover?.(null)}>
      <rect x={x} y={y} width={width} height={height} fill={color} fillOpacity={0.38} stroke="#020617" strokeWidth={2} />
      {width > 56 && height > 28 && (
        <text x={x + 8} y={y + 20} fill="#f8fafc" fontSize={13} fontWeight={600}>
          {tile.symbol}{tile.pct != null ? ` ${tile.pct.toFixed(0)}%` : ""}
        </text>
      )}
      {width > 76 && height > 46 && (
        <text x={x + 8} y={y + 38} fill="#e2e8f0" fontSize={11}>
          {fmtUsd(tile.market_value, { whole: true })}
        </text>
      )}
    </g>
  );
}

function GroupingToggle({ grouping, setGrouping }: { grouping: Grouping; setGrouping: (g: Grouping) => void }) {
  return (
    <div className="inline-flex rounded-md border border-slate-700 p-0.5" role="group" aria-label="Group composition by">
      {(["sector", "idea"] as const).map((g) => (
        <button key={g} type="button" aria-pressed={grouping === g} onClick={() => setGrouping(g)}
                className={`rounded px-2 py-0.5 text-[11px] font-medium ${
                  grouping === g ? "bg-slate-700 text-white" : "text-slate-400 hover:text-slate-200"}`}>
          {g === "sector" ? "By sector" : "By idea"}
        </button>
      ))}
    </div>
  );
}

function Legend({ tiles }: { tiles: Tile[] }) {
  const totals = sectorTotals(tiles);
  if (totals.length === 0) return null;
  return (
    <ul aria-label="Sector legend" className="mt-2 flex flex-wrap gap-x-3 gap-y-1">
      {totals.map(({ sector, pct }) => (
        <li key={sector} className="flex items-center gap-1.5 text-[11px] text-slate-300">
          <span aria-hidden="true" className="h-2.5 w-2.5 rounded-[3px]" style={{ background: sectorColor(sector) }} />
          {sector} <span className="tabular-nums text-slate-500">{pct.toFixed(0)}%</span>
        </li>
      ))}
    </ul>
  );
}

function CompositionView({ tiles, grouping, heightClass }: {
  tiles: Tile[]; grouping: Grouping; heightClass: string;
}) {
  const [hover, setHover] = useState<{ tile: Tile; x: number; y: number } | null>(null);
  const groups = useMemo(() => buildGroups(tiles, grouping), [tiles, grouping]);
  return (
    <div className="relative"
         onMouseMove={(e) => {
           const rect = e.currentTarget.getBoundingClientRect();
           const x = e.clientX - rect.left, y = e.clientY - rect.top;
           setHover((h) => (h ? { ...h, x, y } : h));
         }}
         onMouseLeave={() => setHover(null)}>
      <div className={heightClass} aria-label="Holdings by size, colored by sector">
        <ResponsiveContainer width="100%" height="100%">
          <Treemap data={groups} dataKey="size" isAnimationActive={false}
                   content={<Node onHover={(tile) => setHover((h) => (tile ? { tile, x: h?.x ?? 0, y: h?.y ?? 0 } : null))} />} />
        </ResponsiveContainer>
      </div>
      {hover && (
        <div data-testid="tile-tooltip" role="tooltip"
             className="pointer-events-none absolute z-10 w-52 rounded-lg border border-slate-700 bg-slate-900/95 p-2.5 text-xs shadow-xl"
             style={{ left: Math.max(0, hover.x + 14), top: Math.max(0, hover.y + 14) }}>
          <div className="flex items-center gap-1.5 font-semibold text-white">
            <span aria-hidden="true" className="h-2.5 w-2.5 rounded-[3px]" style={{ background: sectorColor(hover.tile.sector) }} />
            {hover.tile.symbol}
            {hover.tile.side === "short" && <span className="font-normal text-slate-400">short</span>}
          </div>
          <dl className="mt-1.5 space-y-0.5 text-slate-300">
            <div className="flex justify-between gap-2"><dt className="text-slate-500">Sector</dt><dd>{hover.tile.sector}</dd></div>
            <div className="flex justify-between gap-2"><dt className="text-slate-500">Value</dt><dd className="tabular-nums">{fmtUsd(hover.tile.market_value, { whole: true })}</dd></div>
            <div className="flex justify-between gap-2"><dt className="text-slate-500">Weight</dt><dd className="tabular-nums">{hover.tile.pct == null ? "—" : `${hover.tile.pct.toFixed(1)}%`}</dd></div>
            {hover.tile.qty != null && (
              <div className="flex justify-between gap-2"><dt className="text-slate-500">Shares</dt><dd className="tabular-nums">{hover.tile.qty}</dd></div>
            )}
            {hover.tile.idea && (
              <div className="flex justify-between gap-2"><dt className="text-slate-500">From idea</dt><dd className="text-right">{hover.tile.idea}</dd></div>
            )}
          </dl>
        </div>
      )}
    </div>
  );
}

export default function CompositionBox({ positions, composition, className = "" }: {
  positions: PositionRow[];
  composition: PortfolioPayload["composition"];
  className?: string;
}) {
  const [grouping, setGrouping] = useState<Grouping>("sector");
  const [open, setOpen] = useState(false);
  const tiles = useMemo(() => positions.map(toTile), [positions]);

  return (
    <section className={`rounded-xl border border-slate-800 bg-slate-900/60 p-4 ${className}`}>
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Composition</h2>
        <div className="flex items-center gap-2">
          <GroupingToggle grouping={grouping} setGrouping={setGrouping} />
          <button type="button" onClick={() => setOpen(true)} aria-label="Expand composition"
                  className="rounded-md border border-slate-700 p-1 text-slate-300 hover:border-slate-500">
            <Maximize2 className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        </div>
      </div>
      <div className="mt-3">
        <CompositionView tiles={tiles} grouping={grouping} heightClass="h-44" />
        <Legend tiles={tiles} />
        <ul className="mt-2 max-h-44 space-y-1 overflow-auto">
          {composition.map((c) => (
            <li key={c.idea} className="flex items-baseline justify-between gap-3 rounded-md border border-slate-800 px-2.5 py-1.5 text-xs">
              <span className="text-slate-200">{c.idea}</span>
              <span className="tabular-nums text-slate-400">
                {c.pct_of_book.toFixed(0)}% · <span className={tone(c.unrealized_pl)}>{fmtUsd(c.unrealized_pl, { signed: true })}</span>
              </span>
            </li>
          ))}
          {composition.length === 0 && <li className="text-xs text-slate-400">All cash.</li>}
        </ul>
      </div>

      {open && (
        <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 sm:items-center"
             role="dialog" aria-modal="true" aria-label="Composition"
             onClick={() => setOpen(false)}
             onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}>
          <div className="max-h-[88vh] w-full max-w-5xl overflow-y-auto rounded-t-2xl border border-slate-700 bg-slate-900 p-5 sm:rounded-2xl"
               onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between gap-3">
              <h2 className="text-base font-semibold text-white">Composition</h2>
              <div className="flex items-center gap-2">
                <GroupingToggle grouping={grouping} setGrouping={setGrouping} />
                <button type="button" onClick={() => setOpen(false)} aria-label="Close"
                        className="rounded-md border border-slate-700 p-1.5 text-slate-300 hover:border-slate-500">
                  <X className="h-4 w-4" />
                </button>
              </div>
            </div>
            <div className="mt-4">
              <CompositionView tiles={tiles} grouping={grouping} heightClass="h-[55vh]" />
              <Legend tiles={tiles} />
            </div>
          </div>
        </div>
      )}
    </section>
  );
}
