import { useState } from "react";
import { Loader2, PlayCircle, X } from "lucide-react";

import { buildApiUrl } from "@/lib/api";
import { adminJson, legText, type PlayCheckResult } from "@/lib/workshop";

/** "Can I run this?" (Kevin, 2026-11-02): a read-only check of the idea's
 * target book at a chosen size against the live paper portfolio, verdict
 * first, in an overlay sheet (bottom sheet on a phone). It never stages or
 * places an order. Used on Workshop ideas and published Ideas cards alike. */
export function PlayCheckButton({ ideaId, source, title }: {
  ideaId: number; source: "workshop" | "public"; title: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={(e) => { e.preventDefault(); e.stopPropagation(); setOpen(true); }}
              className="inline-flex items-center gap-1.5 rounded-lg border border-slate-700 px-2.5 py-1.5 text-xs font-medium text-slate-200 hover:border-slate-500">
        <PlayCircle className="h-3.5 w-3.5" /> Can I run this?
      </button>
      {open && <PlayCheckSheet ideaId={ideaId} source={source} title={title} onClose={() => setOpen(false)} />}
    </>
  );
}

const money = (n: number) => `${n < 0 ? "−" : ""}$${Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
const shares = (n: number | null) => (n === null ? "—" : `${n < 0 ? "−" : ""}${Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 2 })}`);

function PlayCheckSheet({ ideaId, source, title, onClose }: {
  ideaId: number; source: "workshop" | "public"; title: string; onClose: () => void;
}) {
  const [size, setSize] = useState("10");
  const [book, setBook] = useState<"main" | "big">("main");
  const [result, setResult] = useState<PlayCheckResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    const pct = Number(size);
    if (!Number.isFinite(pct) || pct <= 0 || pct > 100) { setError("Size must be between 0 and 100%."); return; }
    setBusy(true); setError(null);
    try {
      const path = source === "workshop"
        ? `/api/workshop/ideas/${ideaId}/play-check?size_pct=${pct}&book=${book}`
        : `/api/ideas/${ideaId}/play-check?size_pct=${pct}&book=${book}`;
      if (source === "workshop") {
        setResult(await adminJson<PlayCheckResult>(path));
      } else {
        const res = await fetch(buildApiUrl(path));
        if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `Check failed (${res.status})`);
        setResult(await res.json());
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "The check failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60 sm:items-center" role="dialog" aria-modal="true" aria-label={`Play check for ${title}`}>
      <div className="max-h-[88vh] w-full max-w-2xl overflow-y-auto rounded-t-2xl border border-slate-700 bg-slate-900 p-5 sm:rounded-2xl">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-white">Can I run this?</h2>
            <p className="mt-0.5 text-sm text-slate-400">{title}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-md border border-slate-700 p-1.5 text-slate-300 hover:border-slate-500">
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="mt-4 flex flex-wrap items-end gap-2">
          <label className="text-sm text-slate-300">
            Size (% of account equity)
            <input value={size} onChange={(e) => setSize(e.target.value)} inputMode="decimal"
                   className="mt-1 block w-28 rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-white" />
          </label>
          <div className="text-sm text-slate-300">
            Book
            <div className="mt-1 flex overflow-hidden rounded-lg border border-slate-700">
              {(["main", "big"] as const).map((b) => (
                <button key={b} type="button" onClick={() => { setBook(b); setResult(null); }}
                        className={`px-3 py-2 ${book === b ? "bg-slate-700 text-white" : "text-slate-400"}`}>
                  {b === "main" ? "Main book" : "$1M book"}
                </button>
              ))}
            </div>
          </div>
          <button type="button" onClick={run} disabled={busy}
                  className="inline-flex items-center gap-2 rounded-lg bg-white px-4 py-2 text-sm font-semibold text-slate-900 disabled:opacity-60">
            {busy && <Loader2 className="h-4 w-4 animate-spin" />} Check
          </button>
          <p className="text-xs text-slate-500">Read-only — nothing is staged or placed.</p>
        </div>

        {error && <p role="alert" className="mt-4 text-sm text-rose-300">{error}</p>}

        {result && !result.available && <p className="mt-4 text-sm text-slate-300">{result.note}</p>}
        {result?.available && (
          <div className="mt-4">
            <p className={`text-lg font-semibold ${result.verdict === "not_affordable" ? "text-rose-300" : "text-emerald-300"}`}>
              {result.verdict_line}
            </p>
            <p className="mt-1 text-sm text-slate-300">
              {result.state === "in"
                ? "The rule is IN today — the target below is the play's own book."
                : `The rule is OUT today — the target is ${result.otherwise === "CASH" ? "cash" : `its otherwise asset (${result.otherwise})`}.`}
              {result.exit_reason ? ` Exit on record: ${result.exit_reason}` : ""}
            </p>
            <p className="mt-1 text-xs text-slate-500">
              {result.book_label ?? "Main book"} as of {result.as_of ? new Date(result.as_of).toLocaleString() : "—"} · equity {money(result.equity ?? 0)} · cash {money(result.cash ?? 0)} · buys {money(result.buys ?? 0)} · trims {money(result.sells ?? 0)}
            </p>
            {result.sleeve_usd != null && (
              <p className="mt-1 text-sm text-slate-300">
                {money(result.already_in_place_usd ?? 0)} of the {money(result.sleeve_usd)} sleeve is already in place ({result.in_place_pct ?? 0}%).
              </p>
            )}

            <div className="mt-3 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="py-1 pr-2">Ticker</th><th className="py-1 pr-2">Held</th>
                    <th className="py-1 pr-2">Target</th><th className="py-1 pr-2">In place</th><th className="py-1">Change</th>
                  </tr>
                </thead>
                <tbody>
                  {(result.rows ?? []).map((r) => (
                    <tr key={r.ticker} className="border-t border-slate-800">
                      <td className="py-1.5 pr-2 font-medium text-white">
                        {r.ticker}
                        {r.cap_breach && <span className="ml-2 rounded bg-rose-500/15 px-1.5 py-0.5 text-xs text-rose-300">over the 25% cap</span>}
                        {r.overlap_ideas.length > 0 && (
                          <span className="ml-2 rounded bg-amber-500/15 px-1.5 py-0.5 text-xs text-amber-300">also held by {r.overlap_ideas.join(", ")}</span>
                        )}
                      </td>
                      <td className="py-1.5 pr-2 text-slate-300">{shares(r.held_shares)} · {money(r.held_value)}</td>
                      <td className="py-1.5 pr-2 text-slate-300">{r.target_shares === null ? "—" : `${shares(r.target_shares)} · ${money(r.target_value)}`}</td>
                      <td className="py-1.5 pr-2 text-slate-300">{r.coverage_pct === null || r.coverage_pct === undefined ? "—" : r.coverage_pct > 100 ? `${r.coverage_pct}% · over` : `${r.coverage_pct}%`}</td>
                      <td className={`py-1.5 ${r.delta_value > 0 ? "text-emerald-300" : r.delta_value < 0 ? "text-rose-300" : "text-slate-400"}`}>{money(r.delta_value)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {(result.options_legs ?? []).length > 0 && (
              <p className="mt-3 text-sm text-slate-300">
                Option legs (model-priced, placed manually): {(result.options_legs ?? []).map(legText).join(" · ")}
              </p>
            )}
            {(result.notes ?? []).map((n) => <p key={n} className="mt-1 text-xs text-slate-500">{n}</p>)}
          </div>
        )}
      </div>
    </div>
  );
}
