import { useState, type ReactNode } from "react";
import { Bar, BarChart, Cell, Line, LineChart, ResponsiveContainer, YAxis } from "recharts";

import { FullView, Panel } from "@/components/Panel";
import { sessionToken } from "@/components/RequireAdmin";
import { adminJson, ApiError } from "@/lib/workshop";
import { fmtUsd } from "@/lib/paperPortfolio";

/** The page's card shell (the Panel with the Portfolio page's prop names). */
export function Box({ title, right, children, className = "", full }: {
  title: string; right?: ReactNode; children: ReactNode; className?: string; full?: ReactNode;
}) {
  return <Panel title={title} meta={right} full={full} className={className}>{children}</Panel>;
}

/** How many rows a list card shows on the page; the open view has them all. */
export const PEEK = 5;

/**
 * A dashboard card (Kevin, 2026-11-13: show, don't tell; details behind the
 * card). It leads with one number and a two-to-four-word label, an optional
 * short line, and a small chart or the top rows. The whole card is the open
 * control: click it, or Tab to it and press Enter, and `detail` opens in a
 * FullView. `hint` is the definition, shown as the card's tooltip. Controls
 * placed inside the card's body must carry `relative z-10` to sit above the
 * open control.
 */
export function DashCard({ title, value, valueClass = "text-white", sub, meta, hint, detail, detailTitle,
                           detailActions, children, className = "" }: {
  title: string;
  value?: ReactNode;
  valueClass?: string;
  sub?: ReactNode;
  meta?: ReactNode;
  hint?: string;
  detail?: ReactNode;
  detailTitle?: string;
  detailActions?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <section aria-label={title}
             className={`relative flex min-w-0 flex-col rounded-lg border border-slate-800 bg-slate-900/60 p-3 transition-colors ${detail ? "hover:border-slate-600 hover:bg-slate-900" : ""} ${className}`}>
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="truncate text-xs font-medium text-slate-400">{title}</h2>
        {meta && <div className="shrink-0 text-xs tabular-nums text-slate-400">{meta}</div>}
      </div>
      {value != null && (
        <div className={`mt-0.5 font-display text-[1.75rem] font-semibold leading-none tabular-nums tracking-tight ${valueClass}`}>
          {value}
        </div>
      )}
      {sub != null && <div className="mt-1 truncate text-xs tabular-nums text-slate-400">{sub}</div>}
      {children != null && <div className="mt-2 min-h-0 flex-1">{children}</div>}
      {detail && (
        <button type="button" onClick={() => setOpen(true)} aria-label={`Open ${title}`} aria-haspopup="dialog"
                title={hint}
                className="absolute inset-0 rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400" />
      )}
      {open && detail && (
        <FullView title={detailTitle ?? title} onClose={() => setOpen(false)} actions={detailActions}>
          {detail}
        </FullView>
      )}
    </section>
  );
}

/** A labelled figure inside a card or an open view. Unknown reads as a dash (the formatters do that). */
export function Fig({ label, value, className = "text-white", hint }: {
  label: string; value: ReactNode; className?: string; hint?: string;
}) {
  return (
    <div className="min-w-0" title={hint}>
      <dt className="truncate text-[11px] text-slate-500">{label}</dt>
      <dd className={`text-sm font-semibold tabular-nums ${className}`}>{value}</dd>
    </div>
  );
}

/** A sparkline: one or more series, no axes. Decorative inside a card -- the
 * open view carries the readable chart. */
export function Spark<T extends object>({ data, lines, height = 48 }: {
  data: T[];
  lines: { key: keyof T & string; color: string; dashed?: boolean; width?: number }[];
  height?: number;
}) {
  if (data.length < 2) return <div style={{ height }} className="flex items-center text-xs text-slate-500">—</div>;
  return (
    <div style={{ height }} aria-hidden="true">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
          <YAxis hide domain={["auto", "auto"]} />
          {lines.map((l) => (
            <Line key={l.key} type="monotone" dataKey={l.key} stroke={l.color} strokeWidth={l.width ?? 1.5}
                  strokeDasharray={l.dashed ? "3 2" : undefined} dot={false} isAnimationActive={false} connectNulls={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

/** Mini signed bars, green up and rose down. */
export function MiniBars<T extends object>({ data, valueKey, height = 48, dim }: {
  data: T[]; valueKey: keyof T & string; height?: number; dim?: (row: T) => boolean;
}) {
  if (data.length === 0) return <div style={{ height }} className="flex items-center text-xs text-slate-500">—</div>;
  return (
    <div style={{ height }} aria-hidden="true">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 2, right: 0, bottom: 0, left: 0 }}>
          <YAxis hide domain={[(m: number) => Math.min(0, m), (m: number) => Math.max(0, m)]} />
          <Bar dataKey={valueKey} isAnimationActive={false}>
            {data.map((d, i) => {
              const v = Number(d[valueKey]);
              return <Cell key={i} fill={v >= 0 ? "#34d399" : "#fb7185"} fillOpacity={dim?.(d) ? 0.45 : 0.9} />;
            })}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/** A card's top rows: label left, figure right, one line each. */
export function PeekRows({ rows, empty }: {
  rows: { key: string; label: ReactNode; aside?: ReactNode; value: ReactNode; valueClass?: string }[];
  empty?: string;
}) {
  if (rows.length === 0) return <p className="text-xs text-slate-500">{empty ?? "None"}</p>;
  return (
    <ul className="divide-y divide-slate-800/70 text-xs tabular-nums" data-peek="">
      {rows.map((r) => (
        <li key={r.key} className="flex items-baseline gap-2 py-1">
          <span className="min-w-0 truncate font-medium text-slate-200">{r.label}</span>
          {r.aside != null && <span className="shrink-0 truncate text-slate-500">{r.aside}</span>}
          <span className={`ml-auto shrink-0 ${r.valueClass ?? "text-slate-200"}`}>{r.value}</span>
        </li>
      ))}
    </ul>
  );
}

/** A segmented control (range, grouping, filters). */
export function Segments<T extends string>({ label, options, value, onChange, render }: {
  label: string; options: readonly T[]; value: T; onChange: (v: T) => void; render?: (v: T) => string;
}) {
  return (
    <div role="group" aria-label={label} className="flex gap-1">
      {options.map((o) => (
        <button key={o} type="button" aria-pressed={o === value} onClick={() => onChange(o)}
                className={`rounded px-2 py-0.5 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 ${o === value ? "bg-slate-700 font-semibold text-white" : "text-slate-400 hover:text-white"}`}>
          {render ? render(o) : o}
        </button>
      ))}
    </div>
  );
}

/** A text filter for an open view's table. */
export function FilterBox({ value, onChange, label }: { value: string; onChange: (v: string) => void; label: string }) {
  return (
    <input type="search" aria-label={label} placeholder="Filter" value={value} onChange={(e) => onChange(e.target.value)}
           className="w-40 rounded-md border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-white placeholder:text-slate-500" />
  );
}

/** An admin read or write that a signed-out visitor never sends: with no
 * session it fails as a 401 locally, so the callers' signed-out branch runs
 * and no admin endpoint is hit (Kevin, 2026-11-13: the visitor path makes
 * no admin calls). The server still decides who is admin. */
export async function adminCall<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (!(await sessionToken())) throw new ApiError("Signed out", 401, null);
  return adminJson<T>(path, init);
}

export const money = (v: number | null | undefined) => fmtUsd(v, { whole: true });
export const signed = (v: number | null | undefined) => fmtUsd(v, { signed: true, whole: true });
export const price = (v: number | null | undefined) => fmtUsd(v);

export const dayLabel = (d: string) =>
  new Date(`${d}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

export const tooltipStyle = { background: "#0f172a", border: "1px solid #1e293b" };

/** The Portfolio page's 30-second live refresh cycle (2026-11-12 redesign). */
export const REFRESH_MS = 30_000;

/** Run `fn` on the live cycle while the browser tab is visible (a hidden
 * tab skips its turns rather than polling in the background). Returns the
 * stop function for effect cleanup. */
export function pollWhileVisible(fn: () => void, ms: number = REFRESH_MS): () => void {
  const timer = setInterval(() => {
    if (typeof document === "undefined" || document.visibilityState !== "hidden") fn();
  }, ms);
  return () => clearInterval(timer);
}
