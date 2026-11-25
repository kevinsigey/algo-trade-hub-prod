import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  fmtPct, fmtPts, fmtUsd, stateLabel, tone,
  type BookHeadline, type PortfolioPayload, type TodaySplit,
} from "@/lib/paperPortfolio";
import { REAL_MONEY_BADGE, type KalshiRead } from "@/pages/KalshiLiveBook";
import { accountFigures, WarningsStrip } from "./Header";
import { money, signed } from "./shared";

/** The left column (Kevin, 2026-11-25): a book selector whose cards ARE the
 * three-book summary, and under it the selected book's account box, vertical. */

export type PaperRead = { data: PortfolioPayload | null; lastUpdatedAt: number | null; stale: boolean };

/** Today's % for a summary card: the regular session's, else the account's day figure. */
function todayPct(d: PortfolioPayload | null): number | null {
  if (!d) return null;
  const t = d.today;
  if (t && t.state !== "no_prior" && (t.regular_pl != null || t.premarket_pl != null)) {
    return t.state === "premarket" ? t.premarket_pct ?? null : t.regular_pct ?? null;
  }
  return d.account?.day_pl_pct ?? null;
}

const diff = (a: number | null | undefined, b: number | null | undefined) =>
  a == null || b == null ? null : a - b;

function Line({ label, value, cls, wide }: { label: string; value: string; cls?: string; wide?: boolean }) {
  return (
    <div className={`${wide ? "hidden md:flex" : "flex"} items-baseline justify-between gap-1 md:justify-start`}>
      <span className="truncate text-slate-500">{label}</span>
      <span className={`tabular-nums ${cls ?? "text-slate-300"}`}>{value}</span>
    </div>
  );
}

function SelectorCard({ to, active, title, badge, value, children }: {
  to: string; active: boolean; title: string; badge?: boolean; value?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <Link to={to} aria-current={active ? "page" : undefined}
          className={`block min-w-0 rounded-lg border px-2.5 py-1.5 text-[11px] transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 ${active ? "border-emerald-500/50 bg-emerald-500/10" : "border-slate-800 bg-slate-900/60 hover:border-slate-600"}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <span className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
          <span className={`text-xs ${active ? "font-semibold text-white" : "text-slate-200"}`}>{badge ? <><span className="md:hidden">Kalshi</span><span className="hidden md:inline">{title}</span></> : title}</span>
          {badge && <span className={`${REAL_MONEY_BADGE} max-md:px-1 max-md:text-[8px]`}>REAL MONEY</span>}
        </span>
        {value != null && <span className="font-display text-base font-semibold tabular-nums text-white">{value}</span>}
      </div>
      <div className="grid md:flex md:flex-wrap md:gap-x-3">{children}</div>
    </Link>
  );
}

/** The selector: one compact card per book with value, return since start,
 * today and vs SPY. The selected one is `aria-current`; `?book=` is the link. */
export function BookSelector({ book, books, paper, kalshi }: {
  book: string;
  books: BookHeadline[];
  paper: Record<string, PaperRead>;
  kalshi: KalshiRead;
}) {
  const kp = kalshi.pilot;
  return (
    <nav aria-label="Books" className="grid grid-cols-3 items-start gap-1.5 md:grid-cols-1">
      {books.map((b) => {
        const d = paper[b.book]?.data ?? null;
        // The headline list says "not connected" first; a payload can also say it.
        const connected = b.state !== "not_connected" && d?.state !== "not_connected";
        const ret = d?.scoreboard?.return_pct ?? b.return_pct;
        const eq = d?.scoreboard?.equity ?? b.equity;
        const today = todayPct(d);
        return (
          <SelectorCard key={b.book} to={`/portfolio?book=${b.book}`} active={b.book === book} title={b.label}
                        value={connected ? money(eq) : undefined}>
            {!connected ? (
              <div className="text-slate-400">not connected</div>
            ) : (
              <>
                <Line label="Since start" value={fmtPct(ret)} cls={tone(ret)} />
                <Line wide label="Today" value={fmtPct(today)} cls={tone(today)} />
                <Line wide label="vs SPY" value={fmtPts(d?.scoreboard?.ahead_pts)} cls={tone(d?.scoreboard?.ahead_pts)} />
              </>
            )}
          </SelectorCard>
        );
      })}
      <SelectorCard to="/portfolio?book=kalshi" active={book === "kalshi"} title="Kalshi live" badge
                    value={kp ? fmtUsdBal(kp.balance) : undefined}>
        {kp ? (
          <>
            <Line label="P&L" value={fmtSigned(kp.pnl_since_start)} cls={tone(kp.pnl_since_start)} />
          </>
        ) : (
          <div className="text-slate-400">{kalshi.loading ? "Reading…" : kalshi.adminOnly ? "admin only" : "—"}</div>
        )}
      </SelectorCard>
    </nav>
  );
}
// Kalshi's balance is a few dollars: cents matter, so no whole-dollar rounding.
const fmtUsdBal = (v: number | null) => fmtUsd(v);
const fmtSigned = (v: number | null) => fmtUsd(v, { signed: true });

/** One comparison block: the book's figure against SPY and QQQ as paired bars on a
 * shared scale, and the gap to each, tinted. */
function Compare({ book, spy, qqq, vsSpy: gapSpy, vsQqq: gapQqq }: {
  book: number | null | undefined; spy: number | null | undefined; qqq: number | null | undefined;
  /** The backend's own gaps, when it has them; otherwise book minus the index. */
  vsSpy?: number | null; vsQqq?: number | null;
}) {
  const vals = [book, spy, qqq];
  const scale = Math.max(0.5, ...vals.map((v) => Math.abs(v ?? 0)));
  const bar = (v: number | null | undefined, color: string) => (
    <span className="relative block h-1.5 rounded bg-slate-800" aria-hidden="true">
      <span className="absolute inset-y-0 left-1/2 w-px bg-slate-600" />
      {v != null && (
        <span className={`absolute inset-y-0 rounded ${color}`}
              style={v >= 0 ? { left: "50%", width: `${(v / scale) * 50}%` } : { right: "50%", width: `${(-v / scale) * 50}%` }} />
      )}
    </span>
  );
  const row = (label: string, v: number | null | undefined, color: string, valueCls: string, gap?: number | null, hint?: string) => (
    <div className="grid grid-cols-[1fr_8.5rem] items-center gap-2" title={hint}>
      {bar(v, color)}
      <span className="flex items-baseline justify-between gap-1">
        <span className={valueCls}>{label} {fmtPct(v)}</span>
        {gap !== undefined && <b className={`font-semibold ${tone(gap)}`}>{fmtPts(gap)}</b>}
      </span>
    </div>
  );
  const vsSpy = gapSpy !== undefined ? gapSpy : diff(book, spy);
  const vsQqq = gapQqq !== undefined ? gapQqq : diff(book, qqq);
  return (
    <div className="space-y-0.5 text-[11px] tabular-nums md:space-y-1">
      {row("Book", book, book != null && book < 0 ? "bg-rose-400" : "bg-emerald-400", tone(book))}
      {spy != null && row("SPY", spy, "bg-slate-400", "text-slate-400", vsSpy, "Gap: book minus SPY, in percentage points")}
      {qqq != null && row("QQQ", qqq, "bg-sky-400", "text-slate-400", vsQqq, "Gap: book minus QQQ, in percentage points")}
    </div>
  );
}

/** Today, split at the 4:00 PM ET close with SPY/QQQ beside it. */
function TodayBlocks({ data }: { data: PortfolioPayload }) {
  const t: TodaySplit | null | undefined = data.today;
  const a = data.account;
  const head = (label: string, pl: number | null | undefined, pct: number | null | undefined, suffix = "") => (
    <span className={tone(pl ?? pct)}>{label} {signed(pl)}{suffix} ({fmtPct(pct)})</span>
  );
  if (t && t.state !== "no_prior" && (t.regular_pl != null || (t.state === "premarket" && t.premarket_pl != null))) {
    if (t.state === "premarket" && t.premarket_pl != null) {
      return <BlockWithHead head={head("Premarket", t.premarket_pl, t.premarket_pct)} tag="Premarket"
                            tagClass="border-amber-500/40 bg-amber-500/15 text-amber-300"
                            book={t.premarket_pct} spy={t.spy_premarket_pct} qqq={t.qqq_premarket_pct} />;
    }
    return (
      <>
        <BlockWithHead head={head(t.is_today === false ? (t.day_label ?? "Today") : "Today", t.regular_pl, t.regular_pct)}
                       book={t.regular_pct} spy={t.spy_regular_pct} qqq={t.qqq_regular_pct} />
        {t.state === "after_hours" && t.after_hours_pl != null && (
          <BlockWithHead head={head("After hours", t.after_hours_pl, t.after_hours_pct, " since 4:00 PM")} tag="After hours"
                         tagClass="border-sky-500/40 bg-sky-500/15 text-sky-300"
                         book={t.after_hours_pct} spy={t.spy_after_hours_pct} qqq={t.qqq_after_hours_pct} />
        )}
      </>
    );
  }
  return (
    <div className={`text-xs font-medium tabular-nums ${tone(a?.day_pl)}`}>
      {a?.day_pl == null ? "Today —" : `Today ${signed(a.day_pl)} (${fmtPct(a.day_pl_pct)})`}
    </div>
  );
}

function BlockWithHead({ head, tag, tagClass, book, spy, qqq, vsSpy, vsQqq }: {
  head: React.ReactNode; tag?: string; tagClass?: string;
  book: number | null | undefined; spy: number | null | undefined; qqq: number | null | undefined;
  vsSpy?: number | null; vsQqq?: number | null;
}) {
  // The head line carries the dollar figure; Compare draws the paired bars under it.
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2 text-xs font-semibold tabular-nums">
        {head}
        {tag && <span className={`rounded border px-1.5 py-0.5 text-[10px] ${tagClass}`}>{tag}</span>}
      </div>
      <Compare book={book} spy={spy} qqq={qqq} vsSpy={vsSpy} vsQqq={vsQqq} />
    </div>
  );
}

/** The selected paper book's account box, vertical: net liquidation value,
 * today and since start against SPY and QQQ, freshness, the account's figures
 * as labelled rows with a hover definition each, and the warnings as chips. */
export function AccountBox({ book, read }: { book: string; read: PaperRead }) {
  const { data, lastUpdatedAt, stale } = read;
  const [nowMs, setNowMs] = useState(() => Date.now());
  const [detailsOpen, setDetailsOpen] = useState(
    () => typeof window === "undefined" || !window.matchMedia || window.matchMedia("(min-width: 768px)").matches);
  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  if (!data || data.state === "not_connected" || !data.scoreboard) return null;
  const s = data.scoreboard;
  const ago = lastUpdatedAt == null ? null : Math.max(0, Math.round((nowMs - lastUpdatedAt) / 1000));
  return (
    <section aria-label="Account" className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
      <h2 className="text-xs font-medium text-slate-400">Net liquidation value</h2>
      <div className="mt-0.5 flex items-baseline justify-between gap-2">
        <span className="font-display text-[1.75rem] font-semibold leading-none tabular-nums tracking-tight text-white">{money(s.equity)}</span>
        {ago != null && (
          <span className={`text-[11px] ${stale ? "text-amber-300" : "text-slate-500"}`}>Updated {ago} s ago{stale ? " · stale" : ""}</span>
        )}
      </div>
      <div className={`mt-1 text-[11px] ${data.state === "live" ? "text-emerald-300" : "text-amber-300"}`}>{stateLabel(data.state, data.as_of)}</div>
      <div className="mt-2 space-y-2 border-t border-slate-800 pt-2 md:space-y-2.5">
        <TodayBlocks data={data} />
        <BlockWithHead head={<span className={tone(s.return_pct)}>Since start {fmtPct(s.return_pct)}</span>}
                       book={s.return_pct} spy={s.spy_return_pct} qqq={s.qqq_return_pct}
                       vsSpy={s.ahead_pts} vsQqq={s.qqq_return_pct != null ? s.ahead_qqq_pts ?? null : undefined} />
      </div>
      {/* Open on desktop; a closed "Details" expander on a phone. */}
      <details open={detailsOpen} onToggle={(e) => setDetailsOpen(e.currentTarget.open)}
               className="mt-2 border-t border-slate-800 pt-1">
        <summary className="cursor-pointer py-1 text-xs text-slate-400 md:hidden">Details</summary>
        <dl className="divide-y divide-slate-800/70 text-xs">
          {accountFigures(data).map((f) => (
            <div key={f.label} className="flex items-baseline justify-between gap-2 py-[2px]" title={f.hint}>
              <dt className="cursor-help text-slate-400 underline decoration-dotted decoration-slate-600 underline-offset-2">{f.label}</dt>
              <dd className={`text-right font-semibold tabular-nums ${f.className ?? "text-slate-100"}`}>{f.value}</dd>
            </div>
          ))}
        </dl>
      </details>
      <WarningsStrip book={book} data={data} />
    </section>
  );
}
