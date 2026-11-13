import { useEffect, useState } from "react";
import { ChevronDown, ChevronUp, TriangleAlert } from "lucide-react";

import { ctDateTime } from "@/lib/format";
import {
  breakerLabel,
  concentration,
  fmtPct,
  fmtPts,
  fmtUsd,
  stateLabel,
  tone,
  type PortfolioCheckState,
  type PortfolioPayload,
} from "@/lib/paperPortfolio";
import { adminJson, ApiError } from "@/lib/workshop";
import { money, pollWhileVisible, signed } from "./shared";

/** The fixed header (2026-11-12 redesign): net liquidation value, today
 * split at the 4:00 PM ET close, SPY beside both, and how fresh the page
 * is. The account rail's figures ride underneath as a compact strip --
 * the same numbers, one row instead of a column. */
export function PortfolioHeader({ data, lastUpdatedAt, stale }: {
  data: PortfolioPayload;
  lastUpdatedAt: number | null;
  stale: boolean;
}) {
  const s = data.scoreboard;
  const a = data.account;
  const t = data.today;
  const [nowMs, setNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  const ago = lastUpdatedAt == null ? null : Math.max(0, Math.round((nowMs - lastUpdatedAt) / 1000));

  const cashRow = data.positions.find((p) => p.symbol === "Cash");
  const investedPct = cashRow?.pct_of_book == null ? null : 100 - cashRow.pct_of_book;
  const rows = data.positions.filter((p) => p.symbol !== "Cash");
  // A total only when every holding's figure is known -- a partial sum
  // presented as the total would invent a number.
  const unrealized = rows.length > 0 && rows.every((p) => p.unrealized_pl != null)
    ? rows.reduce((sum, p) => sum + (p.unrealized_pl ?? 0), 0) : null;
  const figures: { label: string; value: string; className?: string }[] = [
    { label: "Cash", value: money(a?.cash ?? cashRow?.market_value) },
    { label: "Buying power", value: money(a?.buying_power) },
    { label: "Invested", value: investedPct == null ? "—" : `${investedPct.toFixed(0)}%` },
    { label: "Long value", value: money(a?.long_value) },
    { label: "Short value", value: money(a?.short_value) },
    { label: "Unrealized P&L", value: signed(unrealized), className: tone(unrealized) },
    { label: "Realized P&L", value: signed(a?.realized_pl), className: tone(a?.realized_pl) },
    { label: "Maintenance margin", value: money(a?.maintenance_margin) },
    { label: "Positions", value: String(data.positions_aggregate?.length ?? rows.length) },
    ...(data.breaker ? [{
      label: "Circuit breaker", value: breakerLabel(data.breaker),
      className: data.breaker.tripped ? "text-rose-400" : "text-slate-100",
    }] : []),
  ];

  return (
    <header className="mt-4 rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-2">
        <div>
          <div className="text-xs text-slate-400">Net liquidation value</div>
          <div className="mt-0.5 text-2xl font-semibold tabular-nums tracking-tight text-white">
            {money(s.equity)}
          </div>
          {t && t.state !== "no_prior" && t.regular_pl != null ? (
            <div className="mt-1 text-sm tabular-nums text-slate-200">
              <span className={tone(t.regular_pl)}>
                {t.is_today === false ? (t.day_label ?? "Today") : "Today"} {signed(t.regular_pl)} ({fmtPct(t.regular_pct)})
              </span>
              {t.spy_regular_pct != null && (
                <span className="text-slate-400"> · SPY {fmtPct(t.spy_regular_pct)}</span>
              )}
              {t.qqq_regular_pct != null && (
                <span className="text-slate-400"> · QQQ {fmtPct(t.qqq_regular_pct)}</span>
              )}
              {t.state === "after_hours" && t.after_hours_pl != null && (
                <>
                  <span className={tone(t.after_hours_pl)}>
                    {" "}· After hours {signed(t.after_hours_pl)} since 4:00 PM
                  </span>
                  {t.spy_after_hours_pct != null && (
                    <span className="text-slate-400"> · SPY {fmtPct(t.spy_after_hours_pct)}</span>
                  )}
                  {t.qqq_after_hours_pct != null && (
                    <span className="text-slate-400"> · QQQ {fmtPct(t.qqq_after_hours_pct)}</span>
                  )}
                  <span className="ml-2 rounded border border-sky-500/40 bg-sky-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-sky-300">
                    After hours
                  </span>
                </>
              )}
            </div>
          ) : (
            <div className={`mt-1 text-sm font-medium tabular-nums ${tone(a?.day_pl)}`}>
              {a?.day_pl == null ? "Day P&L unknown" : `${signed(a.day_pl)} (${fmtPct(a.day_pl_pct)}) today`}
            </div>
          )}
          <div className="mt-0.5 text-xs tabular-nums text-slate-400">
            Since start <span className={tone(s.return_pct)}>{fmtPct(s.return_pct)}</span>
            {" "}· SPY {fmtPct(s.spy_return_pct)}
            {" "}· Ahead of SPY <span className={tone(s.ahead_pts)}>{fmtPts(s.ahead_pts)}</span>
            {s.qqq_return_pct != null && (
              <>
                {" "}· QQQ {fmtPct(s.qqq_return_pct)}
                {" "}· Ahead of QQQ <span className={tone(s.ahead_qqq_pts)}>{fmtPts(s.ahead_qqq_pts)}</span>
              </>
            )}
          </div>
        </div>
        <div className="text-right">
          <p className={`text-[11px] ${data.state === "live" ? "text-emerald-300" : "text-amber-300"}`}>
            {stateLabel(data.state, data.as_of)}
          </p>
          {ago != null && (
            <p className={`mt-0.5 text-[11px] ${stale ? "text-amber-300" : "text-slate-500"}`}>
              Updated {ago} s ago{stale ? " · stale" : ""}
            </p>
          )}
        </div>
      </div>
      <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 border-t border-slate-800 pt-2">
        {figures.map((f) => (
          <div key={f.label} className="flex items-baseline gap-1.5 text-xs">
            <dt className="text-slate-400">{f.label}</dt>
            <dd className={`tabular-nums font-medium ${f.className ?? "text-slate-100"}`}>{f.value}</dd>
          </div>
        ))}
      </dl>
    </header>
  );
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

/** What in the check needs attention, as one-line chips (2026-11-12
 * redesign): an over-cap sleeve or member, a member under its floor, the
 * gold cluster over its flag. Quiet sleeves stay out of the strip. */
export function checkChips(state: PortfolioCheckState): string[] {
  const chips: string[] = [];
  for (const s of state.sleeves) {
    if (s.status === "over" && s.sleeve_max_pct != null) {
      chips.push(`${s.label} over cap ${s.weight_pct.toFixed(1)}% / ${s.sleeve_max_pct.toFixed(0)}%`);
    } else if (s.status !== "ok") {
      chips.push(`${s.label} ${s.status} at ${s.weight_pct.toFixed(1)}%`);
    }
    for (const m of s.members) {
      if (m.status === "over" && m.max_pct != null) {
        chips.push(`${m.symbol} over cap ${m.weight_pct.toFixed(1)}% / ${m.max_pct.toFixed(0)}%`);
      } else if (m.status === "under" && m.min_pct != null) {
        chips.push(`${m.symbol} under floor ${m.weight_pct.toFixed(1)}% / ${m.min_pct.toFixed(0)}%`);
      }
    }
  }
  const gold = state.clusters["gold"];
  if (gold && gold.pct > GOLD_FLAG_PCT) {
    chips.push(`Gold cluster ${gold.pct.toFixed(0)}% (flag ${GOLD_FLAG_PCT}%)`);
  }
  // The strip's quiet line claims a complete check, so an unresolved
  // input is itself something to show: a holding in no sleeve over the
  // unassigned cap (5%, the cap the detail table reads against), and
  // any holding the check could not price.
  for (const u of state.unassigned) {
    if (u.weight_pct > 5) {
      chips.push(`${u.symbol} unassigned ${u.weight_pct.toFixed(1)}% / 5%`);
    }
  }
  if (state.unpriced.length > 0) {
    chips.push(`${state.unpriced.join(", ")} unpriced — not checked`);
  }
  return chips;
}

/**
 * The warnings strip, which replaces the Portfolio check card (2026-11-12
 * redesign). It shows only what needs attention, as chips; with nothing to
 * report it reads "All within limits · last check PASS". Clicking it opens
 * the full check -- sleeve bars, the member table and recent outcomes --
 * in a drawer under the strip. The circuit-breaker alert and the
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
      adminJson<PortfolioCheckState>(`/api/portfolio/portfolio-check?book=${book}`)
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
  const chips = state ? checkChips(state) : [];
  const last = state?.recent_checks[0];

  return (
    <div className="mt-2 space-y-2" role="region" aria-label="Warnings">
      {data.breaker?.tripped && (
        <p role="alert" className="flex items-start gap-2 rounded-lg border border-rose-500/50 px-3 py-1.5 text-sm text-rose-200">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          Circuit breaker tripped: {data.breaker.reasons.join("; ")}. New opening orders are refused; closing and protective orders still pass.
        </p>
      )}
      {heavy.map((h) => (
        <p key={h.sector} className="flex items-start gap-2 rounded-lg border border-amber-500/40 px-3 py-1.5 text-xs text-amber-200">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
          {h.sector} is {h.pct.toFixed(0)}% of what&apos;s invested. These positions tend to move together.
        </p>
      ))}
      {!state && failed && (
        <p className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2 text-xs text-slate-400">
          Portfolio check unavailable — the read failed; it retries on the refresh cycle.
        </p>
      )}
      {state && (
        <div className="rounded-lg border border-slate-800 bg-slate-900/60">
          <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}
                  className="flex w-full flex-wrap items-center gap-1.5 px-3 py-2 text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400">
            {chips.length === 0 ? (
              <span className="text-xs text-slate-300">
                All within limits
                {last && (
                  <> · last check{" "}
                    <span className={`font-semibold uppercase ${CHECK_OUTCOME_TONE[last.outcome ?? "unavailable"]}`}>
                      {last.outcome ?? "unavailable"}
                    </span>
                  </>
                )}
              </span>
            ) : (
              chips.map((c) => (
                <span key={c} className="rounded-full border border-amber-500/50 bg-amber-400/10 px-2 py-0.5 text-[11px] font-medium text-amber-200">
                  {c}
                </span>
              ))
            )}
            <span className="ml-auto inline-flex items-center gap-1 text-[11px] text-slate-500">
              Portfolio check
              {open ? <ChevronUp className="h-3.5 w-3.5" aria-hidden="true" /> : <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />}
            </span>
          </button>
          {open && <CheckDetail state={state} />}
        </div>
      )}
    </div>
  );
}

/** The full check, in the strip's drawer: sleeve and member bars, the
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
    <div className="border-t border-slate-800 px-3 py-2">
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
