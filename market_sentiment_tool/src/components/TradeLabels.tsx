import { useEffect, useState } from "react";

import { adminJson, type FillRow, type IdeaRow } from "@/lib/workshop";

/** A fill needs a label only when nothing has decided it yet (Kevin,
 * 2026-11-02): no relabel row, its order tag names no idea, and the client id
 * is not one of the hub's self-describing prefixes (ext- machine orders and
 * manual- hand orders are already what they claim to be). What remains --
 * fills placed outside the hub -- is the real labeling queue. */
export function needsLabel(f: FillRow): boolean {
  if ((f.history?.length ?? 0) > 0) return false;
  const tag = f.tag ?? "";
  if (/^idea-\d+-/.test(tag)) return false;
  return !tag.startsWith("ext-") && !tag.startsWith("manual-");
}

/** The labeling queue: ONLY the fills that need one (Kevin, 2026-11-02),
 * as boxed rows. Attributed fills are counted, not listed. */
export function TradeLabels({ ideas }: { ideas: IdeaRow[] }) {
  const [fills, setFills] = useState<FillRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () =>
    adminJson<{ state: string; fills?: FillRow[] }>("/api/workshop/fills")
      .then((d) => setFills(d.fills ?? []))
      .catch((e: Error) => setError(e.message));
  useEffect(() => {
    load();
  }, []);
  const relabel = (order_id: string, value: string) =>
    adminJson("/api/workshop/labels", { method: "POST", body: JSON.stringify({ order_id, idea_id: value ? Number(value) : null }) })
      .then(load)
      .catch((e: Error) => setError(e.message));
  const title = (n: number | null) => (n == null ? "manual" : ideas.find((i) => i.id === n)?.title ?? `idea ${n}`);
  const queue = (fills ?? []).filter(needsLabel);
  const decided = (fills ?? []).length - queue.length;

  return (
    <>
      <p className="mt-1 text-sm text-slate-400">
        Fills placed outside the hub, with no tag and no label yet. Everything else already counts toward what it is.
      </p>
      {error && <p role="alert" className="mt-3 text-sm text-rose-300">{error}</p>}
      {fills && decided > 0 && (
        <p className="mt-3 text-xs text-slate-500">{decided} fills already attributed by their tags or labels — not shown.</p>
      )}
      {fills && queue.length === 0 && <p className="mt-3 text-sm text-emerald-300">Nothing needs labeling.</p>}
      <ul className="mt-3 space-y-2">
        {queue.map((f) => {
          const name = `${f.symbol} ${f.side} ${f.qty} on ${f.at.slice(0, 10)}`;
          return (
            <li key={f.order_id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2.5 text-sm">
              <span className="font-mono text-slate-200">{name}</span>
              <span className="flex flex-wrap items-center gap-2">
                {f.history.length > 0 && <span className="text-xs text-slate-500">was {title(f.history[f.history.length - 1].from)}</span>}
                <select aria-label={`Idea for ${name}`} value={f.idea_id ?? ""} onChange={(e) => relabel(f.order_id, e.target.value)}
                  className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-white">
                  <option value="">No idea yet (manual)</option>
                  {ideas.map((i) => <option key={i.id} value={i.id}>{i.title}</option>)}
                </select>
              </span>
            </li>
          );
        })}
      </ul>
    </>
  );
}
