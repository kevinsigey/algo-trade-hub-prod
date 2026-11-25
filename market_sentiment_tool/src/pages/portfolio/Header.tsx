import { useEffect, useState } from "react";
import { ChevronRight, TriangleAlert } from "lucide-react";

import { FullView } from "@/components/Panel";

import { ctDateTime } from "@/lib/format";
import {
  breakerLabel,
  concentration,
  tone,
  type PortfolioCheckState,
  type PortfolioPayload,
} from "@/lib/paperPortfolio";
import { ApiError } from "@/lib/workshop";
import { adminCall, money, pollWhileVisible, signed } from "./shared";

/** The account's figures (cash, buying power, exposure, P&L, margin,
 * breaker) -- the Book tab's Account card shows them; the header stays one row. */
export function accountFigures(data: PortfolioPayload): { label: string; value: string; className?: string; hint: string }[] {
  const a = data.account;
  const cashRow = data.positions.find((p) => p.symbol === "Cash");
  const investedPct = cashRow?.pct_of_book == null ? null : 100 - cashRow.pct_of_book;
  const rows = data.positions.filter((p) => p.symbol !== "Cash");
  // A total only when every holding's figure is known -- a partial sum
  // presented as the total would invent a number.
  const unrealized = rows.length > 0 && rows.every((p) => p.unrealized_pl != null)
    ? rows.reduce((sum, p) => sum + (p.unrealized_pl ?? 0), 0) : null;
  return [
    { label: "Cash", value: money(a?.cash ?? cashRow?.market_value), hint: "Uninvested cash in the account." },
    { label: "Buying power", value: money(a?.buying_power), hint: "How much the broker would let this account buy right now, margin included." },
    { label: "Invested", value: investedPct == null ? "—" : `${investedPct.toFixed(0)}%`, hint: "Share of the book held in positions rather than cash." },
    { label: "Long value", value: money(a?.long_value), hint: "Market value of everything held long." },
    { label: "Short value", value: money(a?.short_value), hint: "Market value of everything sold short." },
    { label: "Unrealized P&L", value: signed(unrealized), className: tone(unrealized), hint: "Open profit or loss on positions still held; locked in only when sold." },
    { label: "Realized P&L", value: signed(a?.realized_pl), className: tone(a?.realized_pl), hint: "Profit or loss locked in by closed trades." },
    { label: "Maintenance margin", value: money(a?.maintenance_margin), hint: "The equity the broker requires to keep the positions open; falling below it triggers a margin call." },
    { label: "Positions", value: String(data.positions_aggregate?.length ?? rows.length), hint: "Tickers held right now, one line per ticker." },
    ...(data.breaker ? [{
      label: "Circuit breaker", value: breakerLabel(data.breaker), hint: "Safety stop: when tripped, new opening orders are refused; closing and protective orders still pass.",
      className: data.breaker.tripped ? "text-rose-400" : "text-slate-100",
    }] : []),
  ];
}

const CHECK_STATUS_TONE: Record<string, string> = {
  ok: "text-slate-100", over: "text-rose-300", under: "text-amber-300",
};
const CHECK_BAR_FILL: Record<string, string> = {
  ok: "bg-slate-400", over: "bg-rose-400", under: "bg-amber-400",
};
const CHECK_CLUSTER_GLYPH: Record<string, string> = {
  rates: "◐", ai_complex: "●", gold: "■",
};
// Gold's hard flag, from the check's own seed config (tradehub/portfolio/
// portfolio_check.py): over 12% of invested warns. The card payload carries no
// per-cluster cap, so the gold chip tints on this documented number.
const GOLD_FLAG_PCT = 12;
const CHECK_OUTCOME_TONE: Record<string, string> = {
  pass: "text-emerald-300", warn: "text-amber-300", block: "text-rose-300", unavailable: "text-slate-400",
};

export type CheckIssue = { key: string; who: string; issue: string; size: string; over: boolean };

/** What in the check needs attention, one short row each: an over-cap sleeve or
 * member, a member under its floor, the gold cluster over its flag, a holding
 * in no sleeve over the unassigned cap, and anything the check could not
 * price. Quiet sleeves stay out. An empty list is a complete, clean check. */
export function checkIssues(state: PortfolioCheckState): CheckIssue[] {
  const out: CheckIssue[] = [];
  const add = (who: string, issue: string, size: string, over = false) =>
    out.push({ key: `${who}-${issue}`, who, issue, size, over });
  for (const s of state.sleeves) {
    if (s.status === "over" && s.sleeve_max_pct != null) {
      add(s.label, "over cap", `${s.weight_pct.toFixed(1)}% / ${s.sleeve_max_pct.toFixed(0)}%`, true);
    } else if (s.status !== "ok") {
      add(s.label, s.status, `${s.weight_pct.toFixed(1)}%`, s.status === "over");
    }
    for (const m of s.members) {
      if (m.status === "over" && m.max_pct != null) {
        add(m.symbol, "over cap", `${m.weight_pct.toFixed(1)}% / ${m.max_pct.toFixed(0)}%`, true);
      } else if (m.status === "under" && m.min_pct != null) {
        add(m.symbol, "under floor", `${m.weight_pct.toFixed(1)}% / ${m.min_pct.toFixed(0)}%`);
      }
    }
  }
  const gold = state.clusters["gold"];
  if (gold && gold.pct > GOLD_FLAG_PCT) add("Gold cluster", "over flag", `${gold.pct.toFixed(0)}% / ${GOLD_FLAG_PCT}%`);
  // A complete-looking check needs its inputs resolved: a holding in no sleeve
  // over the unassigned cap (5%), and any holding the check could not price.
  for (const u of state.unassigned) {
    if (u.weight_pct > 5) add(u.symbol, "unassigned", `${u.weight_pct.toFixed(1)}% / 5%`);
  }
  if (state.unpriced.length > 0) add(state.unpriced.join(", "), "unpriced", "not checked");
  return out;
}

/** The card's headline: "6 unassigned" when the rows share one issue, else "6 issues". */
export function checkHeadline(issues: CheckIssue[]): string {
  const kinds = new Set(issues.map((i) => i.issue));
  return `${issues.length} ${kinds.size === 1 ? [...kinds][0] : issues.length === 1 ? "issue" : "issues"}`;
}

/**
 * The Portfolio check pill, in the page header beside the title: "Portfolio
 * check · 6 unassigned ›" in the status colour, or "all clear" in emerald. It
 * opens one view with the warnings (circuit breaker, sector concentration), the
 * issue rows, and the full check: sleeve bars, member table, recent outcomes.
 * A second pill shows only when a warning is present. The circuit-breaker alert and the
 * concentration warning ride above it, as before. One engine with the
 * preflight and activation gates, so the strip can never disagree with
 * them. Signed-in only for the check itself: signed out, it renders
 * nothing beyond the payload's own alerts.
 */
export function WarningsStrip({ book, data }: { book: string; data: PortfolioPayload }) {
  const [state, setState] = useState<PortfolioCheckState | null>(null);
  const [failed, setFailed] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let cancelled = false;
    const load = () => {
      adminCall<PortfolioCheckState>(`/api/portfolio/portfolio-check?book=${book}`)
        .then((body) => {
          if (!cancelled && body && Array.isArray(body.sleeves) && Array.isArray(body.recent_checks)) {
            setState(body);
            setFailed(false);
          }
        })
        .catch((err) => {
          // A 401/403 is the signed-out view (stay silent); any other
          // failure is a check that could not be read, which must not
          // look like a quiet book. A failed refresh keeps the last
          // good state on screen.
          if (!cancelled && !(err instanceof ApiError && (err.status === 401 || err.status === 403))) {
            setFailed(true);
          }
        });
    };
    load();
    const stop = pollWhileVisible(load);
    return () => { cancelled = true; stop(); };
  }, [book]);

  const rows = data.positions.filter((p) => p.symbol !== "Cash");
  const heavy = concentration(rows);
  const issues = state ? checkIssues(state) : [];
  const last = state?.recent_checks[0];

  const tripped = !!data.breaker?.tripped;
  const warnCount = (tripped ? 1 : 0) + heavy.length;
  const checkTone = !state ? "" : issues.length === 0 ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
    : issues.some((i) => i.over) ? "border-rose-500/40 bg-rose-500/10 text-rose-300" : "border-amber-500/40 bg-amber-500/10 text-amber-300";
  const pill = "inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-medium focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400";

  return (
    <div className="flex flex-wrap items-center gap-2 empty:hidden" role="region" aria-label="Warnings">
      {state && (
        <button type="button" aria-haspopup="dialog" aria-label="Open Portfolio check" onClick={() => setOpen(true)}
                title="Open for the issues, sleeve bars, the member table and recent outcomes" className={`${pill} ${checkTone}`}>
          Portfolio check · {issues.length === 0 ? "all clear" : checkHeadline(issues)}
          {issues.length === 0 && last && <span className={`uppercase ${CHECK_OUTCOME_TONE[last.outcome ?? "unavailable"]}`} title="The last check's outcome">· {last.outcome ?? "unavailable"}</span>}
          <ChevronRight className="h-3 w-3" aria-hidden="true" />
        </button>
      )}
      {warnCount > 0 && (
        <button type="button" aria-haspopup="dialog" aria-label="Open Warnings" onClick={() => setOpen(true)}
                className={`${pill} ${tripped ? "border-rose-500/50 bg-rose-500/10 text-rose-300" : "border-amber-500/40 bg-amber-500/10 text-amber-300"}`}>
          <TriangleAlert className="h-3 w-3" aria-hidden="true" />
          {tripped ? "Circuit breaker tripped" : `${warnCount} warning${warnCount === 1 ? "" : "s"}`}
          <ChevronRight className="h-3 w-3" aria-hidden="true" />
        </button>
      )}
      {!state && failed && <span className="text-xs text-slate-400">Portfolio check unavailable — retrying.</span>}
      {open && (
        <FullView title="Portfolio check" onClose={() => setOpen(false)}>
          <div className="space-y-2">
            {tripped && (
              <p role="alert" className="flex items-start gap-2 rounded-lg border border-rose-500/50 px-3 py-1.5 text-sm text-rose-200">
                <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                <span title="New opening orders are refused; closing and protective orders still pass">Circuit breaker tripped: {data.breaker?.reasons.join("; ")}. Opening orders refused.</span>
              </p>
            )}
            {heavy.map((h) => (
              <p key={h.sector} className="flex items-start gap-2 rounded-lg border border-amber-500/40 px-3 py-1.5 text-xs text-amber-200">
                <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
                <span title="Positions in one sector tend to move together">{h.sector} {h.pct.toFixed(0)}% of invested</span>
              </p>
            ))}
            {issues.length > 0 && (
              <ul className="divide-y divide-slate-800/70 text-xs tabular-nums">
                {issues.map((i) => (
                  <li key={i.key} className="flex items-baseline gap-2 py-1">
                    <span className="min-w-0 truncate font-medium text-slate-200">{i.who}</span>
                    <span className="shrink-0 text-slate-500">{i.issue}</span>
                    <span className={`ml-auto shrink-0 ${i.over ? "text-rose-300" : "text-amber-300"}`}>{i.size}</span>
                  </li>
                ))}
              </ul>
            )}
            {state && <CheckDetail state={state} />}
          </div>
        </FullView>
      )}
    </div>
  );
}

/** The full check, in the card's open view: sleeve and member bars, the
 * member table, cluster chips and recent outcomes. */
function CheckDetail({ state }: { state: PortfolioCheckState }) {
  const pct = (v: number, dp = 1) => `${v.toFixed(dp)}%`;
  type CheckBar = {
    key: string; label: string; nested?: boolean; weight: number;
    floor: number | null; target: number | null; cap: number | null;
    status: string; note?: string; neutral?: boolean;
  };
  const bars: CheckBar[] = [];
  for (const s of state.sleeves) {
    bars.push({
      key: s.id, label: s.label, weight: s.weight_pct, floor: null, target: null,
      cap: s.exit_only ? null : s.sleeve_max_pct, status: s.status,
      note: s.exit_only ? "exit-only" : undefined,
    });
    for (const m of s.members) {
      if (m.max_pct == null && m.status === "ok") continue;
      bars.push({
        key: `${s.id}-${m.symbol}`, label: m.symbol, nested: true, weight: m.weight_pct,
        floor: m.min_pct, target: m.target_pct, cap: m.max_pct, status: m.status,
      });
    }
  }
  if (state.cash_pct != null) {
    bars.push({
      key: "cash", label: "Cash", weight: state.cash_pct, floor: null, target: null,
      cap: null, status: "ok", neutral: true,
    });
  }
  const scale = Math.max(20, ...bars.flatMap((b) => [b.weight, b.cap ?? 0, b.target ?? 0]));
  const at = (v: number) => `${Math.min(100, (v / scale) * 100)}%`;
  const tick = (v: number | null, cls: string, name: string) =>
    v == null ? null : (
      <span key={name} title={`${name} ${v}%`} aria-hidden="true"
        className={`absolute -top-[2px] h-[14px] w-[2px] ${cls}`} style={{ left: at(v) }} />
    );

  return (
    <div>
      <div className="space-y-1">
        {bars.map((b) => (
          <div key={b.key} className="flex items-center gap-2 text-xs">
            <span className={`w-40 shrink-0 truncate ${b.nested ? "pl-4 text-slate-400" : "text-slate-300"}`}>
              {b.label}
              {b.note ? <span className="text-slate-500"> · {b.note}</span> : null}
            </span>
            <div className="relative h-2.5 min-w-0 flex-1 rounded bg-slate-800">
              <div className={`h-full rounded ${b.neutral ? "bg-slate-500" : CHECK_BAR_FILL[b.status]}`}
                style={{ width: at(b.weight) }} />
              {tick(b.floor, "bg-slate-500", "floor")}
              {tick(b.target, "bg-sky-300", "target")}
              {tick(b.cap, "bg-white", "cap")}
            </div>
            <span className={`w-14 shrink-0 text-right tabular-nums font-medium ${CHECK_STATUS_TONE[b.status]}`}>
              {pct(b.weight)}
            </span>
          </div>
        ))}
      </div>
      <p className="mt-1.5 text-[11px] text-slate-500">
        Bars: % of invested (cash: % of equity). Ticks on a bar:{" "}
        <span className="text-slate-400">floor</span> · <span className="text-sky-300">target</span> ·{" "}
        <span className="text-slate-100">cap</span> — a fill past the white tick is over its cap.
      </p>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {Object.entries(state.clusters).map(([id, c]) => {
          const flagged = id === "gold" && c.pct > GOLD_FLAG_PCT;
          return (
            <span key={id}
              className={`inline-flex items-baseline gap-1.5 rounded-full border px-2 py-0.5 text-[11px] ${
                flagged ? "border-amber-500/60 bg-amber-400/10 text-amber-200" : "border-slate-700 text-slate-300"
              }`}>
              <span aria-hidden="true">{CHECK_CLUSTER_GLYPH[id] ?? "●"}</span>
              {c.label}
              <span className="font-semibold tabular-nums">{pct(c.pct)}</span>
              {c.with_flagged_pct != null && c.with_flagged_pct !== c.pct
                ? <span className={flagged ? "text-amber-200/70" : "text-slate-500"}>{pct(c.with_flagged_pct)} incl. GLD</span>
                : null}
            </span>
          );
        })}
      </div>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-left text-xs">
          <thead>
            <tr className="text-[11px] uppercase tracking-wide text-slate-500">
              <th className="py-1 pr-3">Name</th><th className="py-1 pr-3">Weight</th>
              <th className="py-1 pr-3">Target</th><th className="py-1 pr-3">Floor</th>
              <th className="py-1 pr-3">Cap</th><th className="py-1 pr-3">Corr to book</th>
              <th className="py-1">Status</th>
            </tr>
          </thead>
          <tbody>
            {state.sleeves.flatMap((s) => [
              <tr key={s.id} className="border-t border-slate-800 font-medium text-slate-200">
                <td className="py-1 pr-3">{s.label}</td>
                <td className="py-1 pr-3 tabular-nums">{pct(s.weight_pct, 2)}</td>
                <td className="py-1 pr-3">—</td><td className="py-1 pr-3">—</td>
                <td className="py-1 pr-3">{s.exit_only ? "exit-only" : s.sleeve_max_pct != null ? pct(s.sleeve_max_pct, 0) : "—"}</td>
                <td className="py-1 pr-3 tabular-nums">{s.correlation_to_book != null ? s.correlation_to_book.toFixed(2) : "—"}</td>
                <td className={`py-1 ${CHECK_STATUS_TONE[s.status]}`}>{s.status}</td>
              </tr>,
              ...s.members.map((m) => (
                <tr key={`${s.id}-${m.symbol}`} className="text-slate-400">
                  <td className="py-1 pr-3 pl-4">{m.symbol}</td>
                  <td className="py-1 pr-3 tabular-nums">{pct(m.weight_pct, 2)}</td>
                  <td className="py-1 pr-3">{m.target_pct != null ? pct(m.target_pct) : "—"}</td>
                  <td className="py-1 pr-3">{m.min_pct != null ? pct(m.min_pct) : "—"}</td>
                  <td className="py-1 pr-3">{m.max_pct != null ? pct(m.max_pct) : "—"}</td>
                  <td className="py-1 pr-3">—</td>
                  <td className={`py-1 ${CHECK_STATUS_TONE[m.status]}`}>{m.status}</td>
                </tr>
              )),
            ])}
            {state.unassigned.map((u) => (
              <tr key={u.symbol} className="text-slate-400">
                <td className="py-1 pr-3 pl-4">{u.symbol} (unassigned)</td>
                <td className="py-1 pr-3 tabular-nums">{pct(u.weight_pct, 2)}</td>
                <td className="py-1 pr-3">—</td><td className="py-1 pr-3">—</td>
                <td className="py-1 pr-3">5%</td><td className="py-1 pr-3">—</td>
                <td className="py-1 text-slate-100">ok</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {state.recent_checks.length > 0 && (
        <ul className="mt-3 space-y-1.5 border-t border-slate-800 pt-2">
          {state.recent_checks.map((e, i) => (
            <li key={i} className="text-xs text-slate-300">
              <span className={`font-semibold uppercase ${CHECK_OUTCOME_TONE[e.outcome ?? "unavailable"]}`}>
                {e.outcome ?? "unavailable"}
              </span>{" "}
              {e.symbol ? <span className="text-slate-400">{e.symbol} · </span> : null}
              {e.detail}
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-[11px] text-slate-500">
        Targets updated {state.targets_updated_at ? ctDateTime(state.targets_updated_at) : "never (seed values)"};
        return series refreshed {state.series_refreshed_at ? ctDateTime(state.series_refreshed_at) : "not yet"}.
      </p>
    </div>
  );
}
