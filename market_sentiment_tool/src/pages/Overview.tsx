import { Link } from "react-router-dom";

import { useApi } from "@/hooks/usePaperPortfolio";
import {
  cents, count, dayRange, gasRecord, gasTrend, metalsPerTrade, modelsBeating, oilPerTrade, testedVsManual, tone,
  type FifteenLite, type Interval, type JournalLite,
} from "@/lib/overview";
import { fmtUsd, type ResultsSplit } from "@/lib/paperPortfolio";

/**
 * The landing page (2026-11-12 rework, backlog product item 1). It answers a first-time visitor in
 * order: what the hub is, three numbers that grade it, what works and what failed, and how it is
 * built. Public reads only (no admin call), so a signed-out visitor sees the whole page; any number
 * a read could not supply prints as a dash.
 */

const DASH = "—";
const TONE_TEXT = { up: "text-profit", down: "text-loss", flat: "text-foreground", unknown: "text-muted-foreground" } as const;

function Figure({ value, className = "text-5xl md:text-6xl" }: { value: string; className?: string }) {
  return <div className={`whitespace-nowrap font-display font-semibold leading-none tabular-nums ${className}`}>{value}</div>;
}

/** The 95% range on one axis with zero marked: whether the range clears zero is the whole question. */
function RangeBar({ r }: { r: Interval }) {
  if (r.low == null || r.high == null) return null;
  const reach = Math.max(Math.abs(r.low), Math.abs(r.high), 0.01) * 1.15;
  const at = (v: number) => `${50 + (v / reach) * 50}%`;
  const clears = r.low > 0;
  return (
    <div className="mt-4" aria-hidden="true">
      <div className="relative h-5">
        <div className="absolute inset-x-0 top-1/2 h-px bg-border" />
        <div className="absolute top-0 h-5 w-px bg-muted-foreground/60" style={{ left: "50%" }} />
        <div className={`absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full ${clears ? "bg-profit/70" : "bg-warn/60"}`}
             style={{ left: at(r.low), width: `calc(${at(r.high)} - ${at(r.low)})` }} />
        <div className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground"
             style={{ left: at(r.perTrade) }} />
      </div>
      <div className="mt-1 flex justify-between text-xs tabular-nums text-muted-foreground">
        <span>{cents(r.low)}</span>
        <span>0</span>
        <span>{cents(r.high)}</span>
      </div>
    </div>
  );
}

function ModelsNumber({ j }: { j: JournalLite | null }) {
  const m = modelsBeating(j);
  return (
    <div>
      <Figure value={m ? `${m.beating} of ${m.measured}` : DASH} />
      <p className="mt-3 text-sm text-foreground">live models beating their market price</p>
      <p className="mt-1 text-xs text-muted-foreground">
        The Model Tracker&rsquo;s rule: ahead with 95% confidence, on settled forecasts only.
      </p>
    </div>
  );
}

function GasNumber({ f }: { f: FifteenLite | null }) {
  const g = gasRecord(f);
  return (
    <div>
      <Figure value={g ? cents(g.perTrade) : DASH} className={`text-5xl md:text-6xl ${TONE_TEXT[tone(g?.perTrade ?? null)]}`} />
      <p className="mt-3 text-sm text-foreground">
        per trade, 15-minute gas rule{g ? `, ${count(g.n)} settled paper trades` : ""}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">
        After Kalshi&rsquo;s fee. 95% range {g ? `${cents(g.low)} to ${cents(g.high)}` : DASH}
        {g?.low != null ? (g.low > 0 ? ", clear of zero." : ", still touching zero.") : "."}
      </p>
      {g && <RangeBar r={g} />}
    </div>
  );
}

function SplitNumber({ s }: { s: ResultsSplit | null }) {
  const side = (label: string, v: ResultsSplit["tested"] | undefined) => (
    <div className="min-w-0">
      <Figure value={v ? fmtUsd(v.pnl, { signed: true, whole: true }) : DASH}
              className={`text-4xl xl:text-5xl ${TONE_TEXT[tone(v ? v.pnl : null)]}`} />
      <p className="mt-3 text-sm text-foreground">{label}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        {v ? `${count(v.wins)} wins in ${count(v.trades)} closed trades` : DASH}
      </p>
    </div>
  );
  return (
    <div className="grid grid-cols-2 gap-4">
      {side("tested ideas", s?.tested)}
      {side("manual trades", s?.discretionary)}
    </div>
  );
}

function Record({ j, f }: { j: JournalLite | null; f: FifteenLite | null }) {
  const m = modelsBeating(j);
  const g = gasRecord(f);
  const trend = gasTrend(f);
  const oil = oilPerTrade(f);
  const metals = metalsPerTrade(f);
  const word = (v: number | null) => ({ up: "positive", down: "negative", flat: "flat", unknown: "unknown" })[tone(v)];
  return (
    <dl className="grid gap-x-6 gap-y-3 text-sm md:grid-cols-[7rem_1fr]">
      <dt className="flex items-center gap-2 font-semibold text-foreground">
        <span className="h-2.5 w-2.5 rounded-sm bg-profit" aria-hidden="true" />What works
      </dt>
      <dd className="text-muted-foreground">
        The grading: {count(m?.scored)} forecasts frozen before the outcome and scored against the market price, losses
        included. And gas, so far: {cents(g?.perTrade)} a trade over {count(g?.n)} paper trades.
      </dd>
      <dt className="flex items-center gap-2 font-semibold text-foreground">
        <span className="h-2.5 w-2.5 rounded-sm bg-loss" aria-hidden="true" />What failed
      </dt>
      <dd className="text-muted-foreground">
        Retired for trailing their markets: {count(m?.retired)} models.{" "}
        {trend
          ? `The 15-minute edge is fading: gas went from ${cents(trend.earlier.perTrade)} a trade on ${dayRange(trend.earlier.from, trend.earlier.to)} to ${cents(trend.recent.perTrade)} on ${dayRange(trend.recent.from, trend.recent.to)}. `
          : ""}
        Oil is {word(oil)} at {cents(oil)} a trade and metals {word(metals)} at {cents(metals)}.
      </dd>
    </dl>
  );
}

const START = [
  { to: "/strategies", title: "The 15-minute rules", body: "Kalshi oil, gas and metals contracts, each paper trade graded at settlement." },
  { to: "/portfolio", title: "The stock book", body: "A $100k Alpaca paper account against SPY, tested ideas split from manual trades." },
  { to: "/portfolio?book=kalshi", title: "Kalshi demo", body: "The gas rule placing orders on Kalshi’s demo exchange, play money only." },
];

const STEPS = [
  { title: "Freeze", body: "Each forecast is stored with a timestamp before the outcome is known, and never edited." },
  { title: "Settle", body: "When the market resolves, the official result is attached: Kalshi settlements, official data releases." },
  { title: "Score", body: "Every forecast is scored against the market price it could have traded at, fees included." },
  { title: "Shadow, then paper", body: "A change runs as a shadow version beside the current one, preregistered, before it can trade. All trading is paper or demo money." },
];

export default function Overview() {
  const journal = useApi<JournalLite>("/api/journal");
  const fifteen = useApi<FifteenLite>("/api/oil/fifteen-rule");
  const closed = useApi<{ results_split?: ResultsSplit }>("/api/portfolio/closed");
  const split = testedVsManual(closed.data);

  return (
    <div className="mx-auto max-w-6xl px-[16px] py-6 md:px-8 md:py-10">
      <section aria-label="What this is" className="max-w-4xl">
        <h1 className="font-display text-4xl font-semibold leading-[1.05] text-foreground md:text-[3.25rem]">
          A solo research desk that forecasts markets, then grades every forecast and paper trade in public against
          the market price.
        </h1>
        <nav aria-label="Start here" className="mt-5 flex flex-wrap gap-2">
          {START.map((s) => (
            <Link key={s.to} to={s.to}
                  className="rounded-md border border-border px-3 py-1.5 text-sm font-semibold text-foreground hover:bg-secondary focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring">
              {s.title}
            </Link>
          ))}
        </nav>
      </section>

      <section aria-label="Headline numbers"
               className="mt-8 grid border border-border bg-card md:grid-cols-[1fr_1.15fr_1.35fr] md:divide-x md:divide-border max-md:divide-y max-md:divide-border">
        <div className="p-5"><ModelsNumber j={journal.data} /></div>
        <div className="p-5"><GasNumber f={fifteen.data} /></div>
        <div className="p-5"><SplitNumber s={split} /></div>
      </section>

      <section aria-label="The record so far" className="mt-6">
        <Record j={journal.data} f={fifteen.data} />
      </section>

      <div className="mt-14 grid gap-12 lg:grid-cols-2">
        <section aria-labelledby="start-here">
          <h2 id="start-here" className="font-display text-2xl font-semibold text-foreground">Start here</h2>
          <ul className="mt-4 divide-y divide-border border-y border-border">
            {START.map((s) => (
              <li key={s.to}>
                <Link to={s.to} className="block py-3 hover:bg-secondary/50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring">
                  <span className="font-semibold text-foreground underline-offset-4 hover:underline">{s.title}</span>
                  <span className="mt-0.5 block text-sm text-muted-foreground">{s.body}</span>
                </Link>
              </li>
            ))}
          </ul>
        </section>

        <section aria-labelledby="how-built">
          <h2 id="how-built" className="font-display text-2xl font-semibold text-foreground">How it&rsquo;s built</h2>
          <p className="mt-4 text-sm text-muted-foreground">
            Prices and settlements from Kalshi, paper fills from Alpaca, live ticks from Pyth, and public data from FRED
            and the National Weather Service. Every result moves through the same four steps.
          </p>
          <ol className="mt-4 space-y-3">
            {STEPS.map((s, i) => (
              <li key={s.title} className="grid grid-cols-[1.75rem_1fr] text-sm">
                <span className="font-display text-lg font-semibold leading-5 text-muted-foreground tabular-nums">{i + 1}</span>
                <span>
                  <span className="font-semibold text-foreground">{s.title}.</span>{" "}
                  <span className="text-muted-foreground">{s.body}</span>
                </span>
              </li>
            ))}
          </ol>
        </section>
      </div>
    </div>
  );
}
