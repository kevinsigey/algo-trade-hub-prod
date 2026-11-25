import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import {
  fmtPct, fmtPts, fmtUsd, stateLabel, tone,
  type BookHeadline, type PortfolioPayload, type TodaySplit,
} from "@/lib/paperPortfolio";
import { REAL_MONEY_BADGE, type KalshiRead } from "@/pages/KalshiLiveBook";
import { accountFigures } from "./Header";
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

/** One labelled figure on a selector card: a small label over a `text-base` value. */
function Stat({ label, value, cls, wide }: { label: string; value: string; cls?: string; wide?: boolean }) {
  return (
    <div className={`${wide ? "hidden md:block" : ""} min-w-0`}>
      <div className="truncate text-[11px] text-slate-500">{label}</div>
      <div className={`truncate text-base font-semibold tabular-nums ${cls ?? "text-white"}`}>{value}</div>
    </div>
  );
}

function SelectorCard({ to, active, title, badge, value, children }: {
  to: string; active: boolean; title: string; badge?: boolean; value?: React.ReactNode; children: React.ReactNode;
}) {
  return (
    <Link to={to} aria-current={active ? "page" : undefined}
          className={`block min-w-0 rounded-lg border p-2 transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-emerald-400 md:px-2.5 md:py-2 ${active ? "border-emerald-500/50 bg-emerald-500/10" : "border-slate-800 bg-slate-900/60 hover:border-slate-600"}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-2">
        <span className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
          <span className={`text-xs md:text-sm ${active ? "font-semibold text-white" : "text-slate-200"}`}>{badge ? <><span className="md:hidden">Kalshi</span><span className="hidden md:inline">{title}</span></> : title}</span>
          {badge && <span className={`${REAL_MONEY_BADGE} max-md:px-1 max-md:text-[8px]`}>REAL MONEY</span>}
        </span>
        {value != null && <span className="font-display text-base font-semibold tabular-nums text-white md:text-xl">{value}</span>}
      </div>
      <div className="mt-1 grid gap-x-2 md:mt-1.5 md:grid-cols-3 md:border-t md:border-slate-800/70 md:pt-1.5">{children}</div>
    </Link>
  );
}

/** The selector: one big card per book -- name, value, then Since start, Today
 * and vs SPY as labelled figures (a phone keeps Since start). The selected one
 * is `aria-current`; `?book=` is the link. */
export function BookSelector({ book, books, paper, kalshi }: {
  book: string;
  books: BookHeadline[];
  paper: Record<string, PaperRead>;
  kalshi: KalshiRead;
}) {
  const kp = kalshi.pilot;
  return (
    <nav aria-label="Books" className="grid grid-cols-3 items-start gap-1.5 md:grid-cols-1 md:gap-2">
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
              <div className="text-sm text-slate-400 md:col-span-3">not connected</div>
            ) : (
              <>
                <Stat label="Since start" value={fmtPct(ret)} cls={tone(ret)} />
                <Stat wide label="Today" value={fmtPct(today)} cls={tone(today)} />
                <Stat wide label="vs SPY" value={fmtPts(d?.scoreboard?.ahead_pts)} cls={tone(d?.scoreboard?.ahead_pts)} />
              </>
            )}
          </SelectorCard>
        );
      })}
      <SelectorCard to="/portfolio?book=kalshi" active={book === "kalshi"} title="Kalshi live" badge
                    value={kp ? fmtUsd(kp.balance) : undefined}>
        {kp ? (
          <Stat label="P&L" value={fmtUsd(kp.pnl_since_start, { signed: true })} cls={tone(kp.pnl_since_start)} />
        ) : (
          <div className="text-sm text-slate-400 md:col-span-3">{kalshi.loading ? "Reading…" : kalshi.adminOnly ? "admin only" : "—"}</div>
        )}
      </SelectorCard>
    </nav>
  );
}

type Num = number | null | undefined;

/** One move against the indexes: a big figure (the dollar change and its % beside
 * it, or just the % when the account has no dollar figure), then one compact line
 * -- SPY, QQQ and the tinted gap to SPY in points. The QQQ gap is in a tooltip. */
function Move({ label, tag, tagClass, pl, pct, spy, qqq, vsSpy, vsQqq, big }: {
  label: string; tag?: string; tagClass?: string;
  /** Pass `null` for "no dollar figure"; `undefined` hides the dollar slot (since start). */
  pl?: Num; pct: Num; spy: Num; qqq: Num;
  /** The backend's own gaps, when it has them; otherwise book minus the index. */
  vsSpy?: Num; vsQqq?: Num; big?: boolean;
}) {
  const gapSpy = vsSpy !== undefined ? vsSpy : diff(pct, spy);
  const gapQqq = vsQqq !== undefined ? vsQqq : diff(pct, qqq);
  return (
    <div>
      {tag ? <span className={`rounded border px-1.5 py-0.5 text-[10px] ${tagClass}`}>{tag}</span>
        : <div className="text-[11px] text-slate-500">{label}</div>}
      <div className="flex items-baseline gap-2 tabular-nums">
        {pl !== undefined && (
          <span className={`font-display text-2xl font-semibold leading-tight ${tone(pl ?? pct)}`}>{signed(pl)}</span>
        )}
        <span className={`${pl === undefined ? "font-display text-xl" : "text-base"} font-semibold ${tone(pct)}`}>{fmtPct(pct)}</span>
      </div>
      {(spy != null || qqq != null) && (
        <div className="text-[11px] tabular-nums text-slate-400">
          {spy != null && <>SPY {fmtPct(spy)}</>}
          {qqq != null && <span title={gapQqq == null ? undefined : `${fmtPts(gapQqq)} vs QQQ`}>{spy != null && " · "}QQQ {fmtPct(qqq)}</span>}
          {gapSpy != null && spy != null && <> · <span className={`font-semibold ${tone(gapSpy)}`} title="Gap: book minus SPY, in percentage points">{fmtPts(gapSpy)} vs SPY</span></>}
        </div>
      )}
    </div>
  );
}

/** Today, split at the 4:00 PM ET close with SPY/QQQ beside it. Premarket and
 * after-hours moves are one small line each. */
function TodayBlocks({ data }: { data: PortfolioPayload }) {
  const t: TodaySplit | null | undefined = data.today;
  const a = data.account;
  if (t && t.state !== "no_prior" && (t.regular_pl != null || (t.state === "premarket" && t.premarket_pl != null))) {
    if (t.state === "premarket" && t.premarket_pl != null) {
      return <Move label="Premarket" tag="Premarket" tagClass="border-amber-500/40 bg-amber-500/15 text-amber-300" big
                   pl={t.premarket_pl} pct={t.premarket_pct} spy={t.spy_premarket_pct} qqq={t.qqq_premarket_pct} />;
    }
    return (
      <>
        <Move label={t.is_today === false ? (t.day_label ?? "Today") : "Today"} big
              pl={t.regular_pl} pct={t.regular_pct} spy={t.spy_regular_pct} qqq={t.qqq_regular_pct} />
        {t.state === "after_hours" && t.after_hours_pl != null && (
          <div className="mt-1 flex flex-wrap items-baseline gap-x-1.5 text-[11px] tabular-nums">
            <span className="rounded border border-sky-500/40 bg-sky-500/15 px-1.5 py-0.5 text-[10px] text-sky-300">After hours</span>
            <span className={tone(t.after_hours_pl)}>{signed(t.after_hours_pl)} ({fmtPct(t.after_hours_pct)}) since 4:00 PM</span>
            {t.spy_after_hours_pct != null && <span className="text-slate-400">· SPY {fmtPct(t.spy_after_hours_pct)}</span>}
            {t.qqq_after_hours_pct != null && <span className="text-slate-400">· QQQ {fmtPct(t.qqq_after_hours_pct)}</span>}
          </div>
        )}
      </>
    );
  }
  return <Move label="Today" big pl={a?.day_pl ?? null} pct={a?.day_pl_pct} spy={null} qqq={null} />;
}

/** The selected paper book's account box, vertical: net liquidation value,
 * today and since start as big figures with SPY and QQQ beside them, freshness, the account's figures
 * as labelled figures with a hover definition each. */
export function AccountBox({ read }: { read: PaperRead }) {
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
      <div className="flex items-baseline justify-between gap-2">
        <h2 className="text-xs font-medium text-slate-400">Net liquidation value</h2>
        {ago != null && (
          <span className={`text-[11px] ${stale ? "text-amber-300" : "text-slate-500"}`}>Updated {ago} s ago{stale ? " · stale" : ""}</span>
        )}
      </div>
      <div className="mt-0.5 font-display text-[1.75rem] font-semibold leading-none tabular-nums tracking-tight text-white">{money(s.equity)}</div>
      <div className={`mt-1 text-[11px] ${data.state === "live" ? "text-emerald-300" : "text-amber-300"}`}>{stateLabel(data.state, data.as_of)}</div>
      <div className="mt-2 space-y-1.5 border-t border-slate-800 pt-2">
        <TodayBlocks data={data} />
        <Move label="Since start" pct={s.return_pct} spy={s.spy_return_pct} qqq={s.qqq_return_pct}
              vsSpy={s.ahead_pts} vsQqq={s.qqq_return_pct != null ? s.ahead_qqq_pts ?? null : undefined} />
      </div>
      {/* Open on desktop; a closed "Details" expander on a phone. */}
      <details open={detailsOpen} onToggle={(e) => setDetailsOpen(e.currentTarget.open)}
               className="mt-2 border-t border-slate-800 pt-1">
        <summary className="cursor-pointer py-1 text-xs text-slate-400 md:hidden">Details</summary>
        <dl className="grid grid-cols-3 gap-x-2 gap-y-1 text-xs">
          {accountFigures(data).map((f) => (
            <div key={f.label} className="min-w-0" title={f.hint}>
              <dt className="cursor-help truncate text-[11px] text-slate-500 underline decoration-dotted decoration-slate-700 underline-offset-2">{f.label}</dt>
              <dd className={`truncate font-semibold tabular-nums ${f.className ?? "text-slate-100"}`}>{f.value}</dd>
            </div>
          ))}
        </dl>
      </details>
    </section>
  );
}
