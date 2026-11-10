import { useEffect, useState } from "react";
import { ChevronDown, Loader2 } from "lucide-react";

import { adminJson } from "@/lib/workshop";
import { ctDateTime } from "@/lib/format";
import { num } from "@/lib/valuation";

/**
 * Band crossings (Spec C, LOG-ONLY): the engine watches the Guidance
 * bands for transitions — a name entering a buy zone with its guide
 * intact, a held name pushing above its bull band — and records the
 * would-be action with its Portfolio Check outcome. It places no orders:
 * the log is the product, graded at +5/+20 sessions against the frozen
 * falsifier. This section is additive display; if the endpoint is
 * unavailable the page renders without it rather than failing.
 */

export interface Crossing {
  id: number;
  created_at: string;
  scan_kind: string | null;
  book: string;
  ticker: string;
  industry: string | null;
  band_basis: string | null;
  bear: number | string | null;
  base: number | string | null;
  bull: number | string | null;
  price: number | string | null;
  price_as_of: string | null;
  zone: string | null;
  prev_action: string | null;
  action: string;
  target_pct: number | string | null;
  delta_usd: number | string | null;
  held_mv: number | string | null;
  guide_status: string | null;
  guide_direction: string | null;
  t1_classification: string | null;
  suppress_reason: string | null;
  pc_outcome: string | null;
  pc_detail: string | null;
  snapshot_id: number | null;
  source: string | null;
  mode: string;
  outcome_20: { score?: number; excess_pct?: number } | null;
  score_20: number | string | null;
}

interface ScanRow {
  id: number;
  kind: string;
  started_at: string;
  banded_names: number | null;
  crossings_written: number | null;
  snapshot_id: number | null;
}

interface CrossingsPayload {
  mode: string;
  orders_enabled: boolean;
  falsifier: { gate: number; graded: number; mean_score: number | null; status: string };
  scans: ScanRow[];
  crossings: Crossing[];
}

const ACTION_LABELS: Record<string, string> = {
  starter: "Starter",
  add: "Add",
  trim_half: "Trim half",
  short_put_spread: "Put spread (short)",
  review_full_exit: "Full-exit review",
  none: "No action",
};

const REASON_LABELS: Record<string, string> = {
  guide_cut: "guide cut",
  guide_status_unknown: "guide status unknown",
  no_t1_classification: "no T1 classification on file",
  target_reached: "already at target",
  zone_exit: "left the zone",
};

const PC_LABELS: Record<string, string> = {
  would_pass: "would pass",
  would_warn: "would warn",
  would_block: "WOULD BLOCK",
  unavailable: "check unavailable",
  not_run: "—",
};

function money(v: number | string | null): string {
  const n = num(v);
  if (n == null) return "—";
  const sign = n < 0 ? "−" : "";
  return `${sign}$${Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

function price(v: number | string | null): string {
  const n = num(v);
  return n == null ? "—" : n.toFixed(2);
}

function actionText(c: Crossing): string {
  if (c.action === "none") {
    const reason = c.suppress_reason ? REASON_LABELS[c.suppress_reason] ?? c.suppress_reason : null;
    return reason ? `No action — ${reason}` : "No action";
  }
  const label = ACTION_LABELS[c.action] ?? c.action;
  if ((c.action === "starter" || c.action === "add") && num(c.target_pct) != null) {
    return `${label} to ${num(c.target_pct)}% of book`;
  }
  if (c.action === "short_put_spread") return `${label} · $1,500 unit`;
  return label;
}

export default function BandCrossings() {
  const [payload, setPayload] = useState<CrossingsPayload | null>(null);
  const [failed, setFailed] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);

  useEffect(() => {
    let live = true;
    adminJson<CrossingsPayload>("/api/band-crossings")
      .then((rows) => { if (live) setPayload(rows); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, []);

  if (failed) return null;
  if (!payload) {
    return (
      <section data-testid="band-crossings" aria-label="Band crossings" className="mt-10">
        <p className="inline-flex items-center gap-2 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading crossings…
        </p>
      </section>
    );
  }
  // An unexpected payload shape (e.g. an older deployment) must never
  // take the page down with it.
  const crossings = Array.isArray(payload.crossings) ? payload.crossings : [];
  const scans = Array.isArray(payload.scans) ? payload.scans : [];
  const falsifier = payload.falsifier;
  const lastScan = scans[0];

  return (
    <section data-testid="band-crossings" aria-label="Band crossings" className="mt-10">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold text-white">Band crossings</h2>
        {payload.mode === "log_only" && (
          <span className="rounded-full bg-amber-500/15 px-2.5 py-0.5 text-xs font-medium text-amber-300">
            LOG-ONLY — records would-be actions, places no orders
          </span>
        )}
      </div>
      <p className="mt-0.5 max-w-3xl text-sm text-slate-400">
        Names crossing their Guidance bands, per book: a starter at or below the base band
        with the guide intact or raised (2% of book, 4% at the bear band), a trim above the
        bull band, a short only as a defined-risk put spread when the forward file has
        deteriorated. Every would-be action carries its Portfolio Check outcome; entries
        grade at +5 and +20 sessions.
      </p>
      <p data-testid="crossings-summary" className="mt-3 text-sm text-slate-300">
        {lastScan ? (
          <>Last scan: <span className="font-medium text-white">{lastScan.kind}</span>
            {` · ${ctDateTime(lastScan.started_at)}`}
            {lastScan.banded_names != null && ` · ${lastScan.banded_names} banded names`}
            {lastScan.crossings_written != null && ` · ${lastScan.crossings_written} crossings written`}
            {lastScan.snapshot_id != null && ` · snapshot #${lastScan.snapshot_id}`}
            {" · "}
          </>
        ) : null}
        {falsifier && (
          <>Falsifier: <span className="font-medium text-white">
            {falsifier.graded}/{falsifier.gate} graded entries</span>
            {` — ${falsifier.status}`}
            {falsifier.mean_score != null && ` · mean score ${falsifier.mean_score}`}
          </>
        )}
      </p>

      {crossings.length === 0 ? (
        <p className="mt-3 text-sm text-slate-500">
          No crossings yet. The baseline scan establishes each name's state; a crossing is a
          transition — entering a zone, or the would-be action changing — never a name
          merely sitting in a zone.
        </p>
      ) : (
        <div className="mt-3 overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2 font-medium">When</th>
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Book</th>
                <th className="px-3 py-2 font-medium">Zone</th>
                <th className="px-3 py-2 font-medium">Would-be action</th>
                <th className="px-3 py-2 font-medium">Size</th>
                <th className="px-3 py-2 font-medium">Portfolio check</th>
                <th className="px-3 py-2 font-medium">+20 score</th>
                <th className="px-3 py-2" aria-label="Detail" />
              </tr>
            </thead>
            <tbody>
              {crossings.map((c) => {
                const open = expanded === c.id;
                return [
                  <tr key={c.id} className="border-b border-slate-800/60 text-slate-300">
                    <td className="whitespace-nowrap px-3 py-2">{ctDateTime(c.created_at)}</td>
                    <td className="px-3 py-2 font-medium text-white">{c.ticker}</td>
                    <td className="px-3 py-2">{c.book}</td>
                    <td className="px-3 py-2">{c.zone ?? "—"}</td>
                    <td className="px-3 py-2">{actionText(c)}</td>
                    <td className="whitespace-nowrap px-3 py-2">{money(c.delta_usd)}</td>
                    <td className={`px-3 py-2 ${c.pc_outcome === "would_block" ? "font-medium text-rose-300" : ""}`}>
                      {c.pc_outcome ? PC_LABELS[c.pc_outcome] ?? c.pc_outcome : "—"}
                    </td>
                    <td className="px-3 py-2">{num(c.score_20) != null ? num(c.score_20)!.toFixed(2) : "—"}</td>
                    <td className="px-3 py-2">
                      <button type="button" aria-label={`Detail for ${c.ticker} crossing ${c.id}`}
                              aria-expanded={open}
                              onClick={() => setExpanded(open ? null : c.id)}
                              className="text-slate-400 hover:text-white">
                        <ChevronDown className={`h-4 w-4 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
                      </button>
                    </td>
                  </tr>,
                  open ? (
                    <tr key={`${c.id}-detail`} className="border-b border-slate-800/60 bg-slate-900/40">
                      <td colSpan={9} className="px-3 py-3 text-xs text-slate-400">
                        <span className="text-slate-200">{c.ticker}</span>
                        {` · ${c.industry ?? "unknown industry"} · ${c.band_basis ?? "eps"} basis`}
                        {` · bands bear ${price(c.bear)} / base ${price(c.base)} / bull ${price(c.bull)}`}
                        {` · price ${price(c.price)}${c.price_as_of ? ` (${c.price_as_of})` : ""}`}
                        {` · guide ${c.guide_status ?? "—"}${c.guide_direction ? ` (${c.guide_direction})` : ""}`}
                        {` · T1 ${c.t1_classification ?? "none on file"}`}
                        {num(c.held_mv) != null && ` · held ${money(c.held_mv)}`}
                        {c.prev_action && ` · previously ${ACTION_LABELS[c.prev_action] ?? c.prev_action}`}
                        {c.snapshot_id != null && ` · snapshot #${c.snapshot_id}`}
                        {` · via ${c.source ?? "scan"}`}
                        {c.pc_detail && <><br />{`Portfolio check: ${c.pc_detail}`}</>}
                        {c.outcome_20?.excess_pct != null &&
                          <><br />{`+20 sessions: excess ${c.outcome_20.excess_pct}% vs the unconditional control`}</>}
                      </td>
                    </tr>
                  ) : null,
                ];
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
