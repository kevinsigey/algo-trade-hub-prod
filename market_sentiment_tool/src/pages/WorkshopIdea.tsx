import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, Loader2 } from "lucide-react";
import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { PaperLine } from "@/pages/Ideas";
import { toneClass } from "@/pages/Workshop";
import {
  ApiError,
  CLAIM_OPTIONS,
  DEFAULT_EXECUTION,
  NO_EXITS,
  ORDER_OPTIONS,
  EVENT_LABELS,
  WINDOW_LABELS,
  adminDownload,
  adminJson,
  isEvent,
  parseEventTable,
  claimLabel,
  MEASURES,
  rulesText,
  specRules,
  verdictTone,
  type Claim,
  type Condition,
  type Execution,
  type Exits,
  type GateResult,
  type Group,
  type DraftResponse,
  type EventSpec,
  type PlayMatch,
  type Rules,
  type RunAnalysis,
  type TickerNames,
  type IdeaDetail,
  type IdeaSpec,
  type Run,
} from "@/lib/workshop";

const field = "mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-sm text-white focus:border-emerald-400 focus:outline-none";
const DEFAULT_CONDITION: Condition = { source: "fred", series: "DGS10", measure: "change", lookback_days: 63, slow_days: null, op: ">", threshold: 0.25 };
const pct = (v: number | null | undefined, digits = 1) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(digits)}%`);

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-xs text-slate-400">
      {label}
      {children}
    </label>
  );
}

function ConditionRow({ c, label, onChange, onRemove }: { c: Condition; label: string; onChange: (c: Condition) => void; onRemove?: () => void }) {
  const options = MEASURES.filter((m) => m.sources.includes(c.source));
  const hint = MEASURES.find((m) => m.value === c.measure)?.hint;
  const put = <K extends keyof Condition>(key: K, value: Condition[K]) => {
    const next = { ...c, [key]: value };
    if (key === "source" && !MEASURES.some((m) => m.value === next.measure && m.sources.includes(next.source)))
      next.measure = MEASURES.find((m) => m.sources.includes(next.source))!.value;
    // A default slow average only when the measure becomes a cross; the server checks slow > fast.
    if (key === "measure") {
      next.slow_days = next.measure === "sma_cross" ? Math.max(200, next.lookback_days + 1) : null;
      if (next.measure === "macd") next.lookback_days = Math.max(1, Number(next.lookback_days) || 1);
    }
    onChange(next);
  };
  return (
    <div className="mt-3 rounded-lg border border-slate-800 p-3">
      <div className="grid gap-3 sm:grid-cols-7">
        <Field label="Source">
          <select className={field} value={c.source} onChange={(e) => put("source", e.target.value as Condition["source"])}>
            <option value="fred">FRED series</option>
            <option value="price">Price</option>
            <option value="analyst">Analyst (stocks)</option>
            <option value="spread">Spread (A+B/C+D)</option>
          </select>
        </Field>
        <Field label="Series / ticker">
          <input className={field} value={c.series} onChange={(e) => put("series", e.target.value)} />
        </Field>
        <Field label="Measure">
          <select className={field} value={c.measure} onChange={(e) => put("measure", e.target.value as Condition["measure"])}>
            {options.map((m) => (
              <option key={m.value} value={m.value}>{m.label}</option>
            ))}
          </select>
        </Field>
        {c.measure === "macd" ? (
          <div className="flex items-end text-xs text-slate-400">MACD uses fixed 12/26/9</div>
        ) : (
          <Field label={c.measure === "sma_cross" ? "Fast average (days)" : "Over (trading days)"}>
            <input type="number" className={field} value={c.lookback_days} onChange={(e) => put("lookback_days", Number(e.target.value))} />
          </Field>
        )}
        {c.measure === "sma_cross" && (
          <Field label="Slow average (days)">
            <input type="number" className={field} value={c.slow_days ?? ""} onChange={(e) => put("slow_days", Number(e.target.value))} />
          </Field>
        )}
        <Field label="Is">
          <select className={field} value={c.op} onChange={(e) => put("op", e.target.value as Condition["op"])}>
            <option value=">">above</option>
            <option value="<">below</option>
          </select>
        </Field>
        <Field label="Threshold">
          <input type="number" step="any" className={field} value={c.threshold} onChange={(e) => put("threshold", Number(e.target.value))} />
        </Field>
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
        {c.source === "analyst" ? (
          <span className="text-amber-300">Data from ~2019, stocks only (no ETFs).</span>
        ) : c.measure === "sma_cross" && (c.slow_days ?? 0) <= c.lookback_days ? (
          <span className="text-amber-300">The slow average needs more days than the fast one.</span>
        ) : (
          <span>{hint}</span>
        )}
        {onRemove && (
          <button type="button" aria-label={`Remove ${label}`} className="text-slate-400 hover:text-red-300" onClick={onRemove}>Remove</button>
        )}
      </div>
    </div>
  );
}

function GroupEditor({ side, group, onChange }: { side: "buy" | "sell"; group: Group; onChange: (g: Group) => void }) {
  const title = side === "buy" ? "Buy when" : "Sell when";
  return (
    <div className="mt-3">
      <label className="flex items-center gap-2 text-sm text-slate-300">
        {title}
        <select aria-label={title} className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-white" value={group.mode}
          onChange={(e) => onChange({ ...group, mode: e.target.value as Group["mode"] })}>
          <option value="all">all of these hold</option>
          <option value="any">any of these holds</option>
        </select>
      </label>
      {group.conditions.map((c, i) => (
        <ConditionRow key={i} c={c} label={`${side} condition ${i + 1}`}
          onChange={(next) => onChange({ ...group, conditions: group.conditions.map((x, j) => (j === i ? next : x)) })}
          onRemove={group.conditions.length > 1 ? () => onChange({ ...group, conditions: group.conditions.filter((_, j) => j !== i) }) : undefined} />
      ))}
      {group.conditions.length < 5 && (
        <button type="button" className="mt-2 text-sm text-emerald-300 hover:text-emerald-200"
          onClick={() => onChange({ ...group, conditions: [...group.conditions, group.conditions[group.conditions.length - 1]] })}>
          Add a {side} condition
        </button>
      )}
    </div>
  );
}

/** Step 6: buy-when and sell-when rules. Each side is all-of or any-of up to 5 conditions. */
function RulesEditor({ rules, onChange }: { rules: Rules | null; onChange: (r: Rules | null) => void }) {
  const fresh: Group = { mode: "all", conditions: [DEFAULT_CONDITION] };
  return (
    <div className="mt-4">
      <label className="flex items-center gap-2 text-sm text-slate-300">
        <input type="checkbox" checked={rules !== null} onChange={(e) => onChange(e.target.checked ? { enter: fresh, exit: null } : null)} />
        Buy only when a rule holds
      </label>
      {rules && (
        <>
          <GroupEditor side="buy" group={rules.enter} onChange={(enter) => onChange({ ...rules, enter })} />
          <label className="mt-4 flex items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={rules.exit !== null} onChange={(e) => onChange({ ...rules, exit: e.target.checked ? { ...fresh, conditions: [{ ...DEFAULT_CONDITION, op: "<" }] } : null })} />
            Sell when its own rule holds
          </label>
          {rules.exit ? (
            <GroupEditor side="sell" group={rules.exit} onChange={(exit) => onChange({ ...rules, exit })} />
          ) : (
            <p className="mt-1 text-xs text-slate-500">Sells when the buy rule stops holding.</p>
          )}
        </>
      )}
    </div>
  );
}

/** What each ticker really is ("GOLD" is a stock, not gold), looked up as Kevin types. Fails quietly. */
const knownTickers: TickerNames = {}; // answers kept for the page's life, so retyping doesn't ask again

function TickerNamesLine({ symbols }: { symbols: string[] }) {
  const [names, setNames] = useState<TickerNames>(() => ({ ...knownTickers }));
  const key = [...new Set(symbols.map((s) => s.trim().toUpperCase()).filter((s) => s && s !== "CASH"))].slice(0, 20).join(",");
  useEffect(() => {
    const missing = key.split(",").filter((s) => s && !(s in knownTickers));
    if (!missing.length) return;
    let live = true;
    const t = setTimeout(() => {
      adminJson<TickerNames>(`/api/workshop/tickers?symbols=${encodeURIComponent(missing.join(","))}`)
        .then((got) => {
          for (const [s, n] of Object.entries(got)) if (n) knownTickers[s] = n; // a miss may be Yahoo throttling: ask again later
          if (live) setNames((old) => ({ ...old, ...got }));
        })
        .catch(() => undefined); // a failed lookup just shows nothing new
    }, 400);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [key]);
  const shown = key.split(",").filter((s) => s && s in names);
  if (!shown.length) return null;
  return (
    <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400" aria-label="What each ticker is">
      {shown.map((s) => {
        const n = names[s];
        return <li key={s} className={n ? "" : "text-amber-300"}>{n ? `${s}: ${n.name} (${n.kind})` : `${s}: not found`}</li>;
      })}
    </ul>
  );
}

/** The draft, as a form. Nothing runs until Kevin presses Run it. An event study gets its own form. */
export function DraftEditor(props: { initial: IdeaSpec; onRun: (s: IdeaSpec) => void; busy: boolean; note?: string; storageKey?: string }) {
  return isEvent(props.initial) ? <EventEditor {...props} /> : <RuleEditor {...props} />;
}

function EventEditor({ initial, onRun, busy, note, storageKey }: { initial: IdeaSpec; onRun: (s: IdeaSpec) => void; busy: boolean; note?: string; storageKey?: string }) {
  const [spec, setSpec] = useState<EventSpec>(initial as unknown as EventSpec);
  const [pasted, setPasted] = useState(() => ((initial as unknown as EventSpec).custom ?? []).map((e) => [e.ticker, e.date, e.surprise ?? ""].join(",")).join("\n"));
  useEffect(() => {
    if (!storageKey) return;
    try { localStorage.setItem(storageKey, JSON.stringify(spec)); } catch { void 0; }
  }, [spec, storageKey]);
  const set = <K extends keyof EventSpec>(key: K, value: EventSpec[K]) => setSpec((s) => ({ ...s, [key]: value }));
  const setEvent = (event: EventSpec["event"]) => setSpec((s) => ({
    ...s, event, when: event === "gap" ? "down" : "all", window: event === "gap" && s.window === "reaction" ? "drift_1_5" : s.window,
    tickers: event === "custom" ? [] : s.tickers, // the server takes the pasted rows' tickers only when this is empty
  }));
  return (
    <section className="mt-6 rounded-xl border border-slate-800 p-5">
      <h2 className="text-base font-semibold text-white">Event study</h2>
      <p className="mt-1 text-xs text-slate-400">Each event: the move vs {spec.benchmark} on the reaction day, then days +1 to +10. Judged on the newest events, against random dates.</p>
      {note && <p className="mt-1 text-sm text-amber-300">{note}</p>}
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Field label="Name">
          <input className={field} value={spec.title} onChange={(e) => set("title", e.target.value)} />
        </Field>
        <Field label={spec.event === "custom" ? "Tickers (from your table)" : "Tickers (comma separated)"}>
          <input className={field} disabled={spec.event === "custom"} value={spec.event === "custom" ? [...new Set((spec.custom ?? []).map((e) => e.ticker))].join(", ") : spec.tickers.join(", ")} onChange={(e) => set("tickers", e.target.value.split(",").map((t) => t.trim()).filter(Boolean))} />
        </Field>
        <Field label="Event">
          <select className={field} value={spec.event} onChange={(e) => setEvent(e.target.value as EventSpec["event"])}>
            {(Object.keys(EVENT_LABELS) as EventSpec["event"][]).map((k) => <option key={k} value={k}>{EVENT_LABELS[k]}</option>)}
          </select>
        </Field>
        {spec.event === "custom" && (
          <div className="sm:col-span-2">
            <Field label="Paste your events (ticker,date[,surprise] per line, or a notebook CSV with a header)">
              <textarea className={`${field} h-28 font-mono text-xs`} value={pasted}
                onChange={(e) => { setPasted(e.target.value); const rows = parseEventTable(e.target.value); setSpec((s) => ({ ...s, custom: rows, tickers: [] })); }} />
            </Field>
            <p className="mt-1 text-xs text-slate-400"><span>{(spec.custom ?? []).length} events read</span> · each date is taken as the reaction day (the first close that reflects it)</p>
          </div>
        )}
        {(spec.event === "earnings" || spec.event === "custom") && (
          <Field label="Which prints">
            <select className={field} value={spec.when} onChange={(e) => set("when", e.target.value as EventSpec["when"])}>
              <option value="all">all prints</option>
              <option value="beat">beats (EPS above estimate)</option>
              <option value="miss">misses</option>
            </select>
          </Field>
        )}
        {spec.event === "gap" && (
          <>
            <Field label="Gap direction">
              <select className={field} value={spec.when} onChange={(e) => set("when", e.target.value as EventSpec["when"])}>
                <option value="down">down days</option>
                <option value="up">up days</option>
              </select>
            </Field>
            <Field label="Gap size vs SPY (%)">
              <input type="number" className={field} value={spec.gap_pct} onChange={(e) => set("gap_pct", Number(e.target.value))} />
            </Field>
          </>
        )}
        <Field label="Which days count">
          <select className={field} value={spec.window} onChange={(e) => set("window", e.target.value as EventSpec["window"])}>
            {(Object.keys(WINDOW_LABELS) as EventSpec["window"][]).filter((w) => spec.event !== "gap" || w !== "reaction").map((w) => <option key={w} value={w}>{WINDOW_LABELS[w]}</option>)}
          </select>
        </Field>
        <Field label="Claimed move">
          <select className={field} value={spec.direction} onChange={(e) => set("direction", e.target.value as EventSpec["direction"])}>
            <option value="up">up vs the benchmark</option>
            <option value="down">down vs the benchmark</option>
          </select>
        </Field>
        <Field label="Compared with">
          <input className={field} value={spec.benchmark} onChange={(e) => set("benchmark", e.target.value)} />
        </Field>
        <Field label="Data from">
          <input type="date" className={field} value={spec.start} onChange={(e) => set("start", e.target.value)} />
        </Field>
      </div>
      {spec.event === "earnings" && <p className="mt-2 text-xs text-slate-500">Stocks only: ETFs have no earnings prints. Yahoo's dated prints go back about 12 years.</p>}
      <button type="button" onClick={() => onRun(spec as unknown as IdeaSpec)} disabled={busy}
        className="mt-4 inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 font-medium text-emerald-950 hover:bg-emerald-400 disabled:opacity-50">
        {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} {busy ? "Testing…" : "Run it"}
      </button>
    </section>
  );
}

function RuleEditor({ initial, onRun, busy, note, storageKey }: { initial: IdeaSpec; onRun: (s: IdeaSpec) => void; busy: boolean; note?: string; storageKey?: string }) {
  const [spec, setSpec] = useState<IdeaSpec>(() => {
    const { when: _legacy, ...rest } = initial; // a stored steps 2-5 spec: its one condition becomes the buy rule
    return { ...rest, rules: specRules(initial) };
  });
  useEffect(() => {
    if (!storageKey) return;
    try { localStorage.setItem(storageKey, JSON.stringify(spec)); } catch { void 0; }
  }, [spec, storageKey]);
  const set = <K extends keyof IdeaSpec>(key: K, value: IdeaSpec[K]) => setSpec((s) => ({ ...s, [key]: value }));
  const exec = spec.execution ?? DEFAULT_EXECUTION;
  const exits = spec.exits ?? NO_EXITS;
  const legs = spec.hold.length + (spec.short ?? []).length;
  const setExit = <K extends keyof Exits>(key: K, value: Exits[K]) => set("exits", { ...exits, [key]: value });
  const num = (v: string) => (v.trim() === "" ? null : Number(v));
  const setLegs = (key: "hold" | "short", value: string[]) =>
    setSpec((s) => {
      const next = { ...s, [key]: value };
      const n = next.hold.length + (next.short ?? []).length;
      const ex = next.exits ?? NO_EXITS;
      return n !== 1 && ex.mode === "intraday" ? { ...next, exits: { ...ex, mode: "close" } } : next;
    });

  return (
    <section className="mt-6 rounded-xl border border-slate-800 p-5">
      <h2 className="text-base font-semibold text-white">The test, as drafted</h2>
      {note && <p className="mt-1 text-sm text-amber-300">{note}</p>}
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <Field label="Name">
          <input className={field} value={spec.title} onChange={(e) => set("title", e.target.value)} />
        </Field>
        <Field label="What success means (the claim)">
          <select className={field} value={spec.claim} onChange={(e) => set("claim", e.target.value as Claim)}>
            {CLAIM_OPTIONS.map((c) => (
              <option key={c} value={c}>{claimLabel(c)}</option>
            ))}
          </select>
        </Field>
        <Field label="Hold (tickers, comma separated, equal weight)">
          <input className={field} value={spec.hold.join(", ")} onChange={(e) => setLegs("hold", e.target.value.split(",").map((t) => t.trim()).filter(Boolean))} />
        </Field>
        <Field label="Short (tickers, comma separated)">
          <input className={field} value={(spec.short ?? []).join(", ")} onChange={(e) => setLegs("short", e.target.value.split(",").map((t) => t.trim()).filter(Boolean))} />
        </Field>
        <Field label="Otherwise hold (ticker or CASH)">
          <input className={field} value={spec.otherwise} onChange={(e) => set("otherwise", e.target.value)} />
        </Field>
      </div>
      <TickerNamesLine symbols={[...spec.hold, ...(spec.short ?? []), spec.otherwise, spec.benchmark]} />

      <RulesEditor rules={spec.rules} onChange={(rules) => set("rules", rules)} />

      <label className="mt-4 flex items-center gap-2 text-sm text-slate-300">
        <input type="checkbox" checked={!!spec.portfolio}
          onChange={(e) => setSpec((s) => ({ ...s, portfolio: e.target.checked ? { core: ["SPY"], idea_share: 0.5 } : null,
            exits: e.target.checked && s.exits?.mode === "intraday" ? { ...s.exits, mode: "close" } : s.exits }))} />
        Test it inside a portfolio
      </label>
      {spec.portfolio && (
        <div className="mt-2 grid gap-3 sm:grid-cols-3">
          <Field label="Core (tickers, equal weight)">
            <input className={field} value={spec.portfolio.core.join(", ")}
              onChange={(e) => set("portfolio", { ...spec.portfolio!, core: e.target.value.split(",").map((t) => t.trim()).filter(Boolean) })} />
          </Field>
          <Field label="Idea's share (%)">
            <input type="number" min={10} max={90} className={field} value={Math.round(spec.portfolio.idea_share * 100)}
              onChange={(e) => set("portfolio", { ...spec.portfolio!, idea_share: Number(e.target.value) / 100 })} />
          </Field>
          <p className="self-end text-xs text-slate-500">Each day the idea gets this share and the core the rest; judged against the benchmark below.</p>
        </div>
      )}

      <div className="mt-4 grid gap-4 sm:grid-cols-4">
        <Field label="Compared with">
          <input className={field} value={spec.benchmark} onChange={(e) => set("benchmark", e.target.value)} />
        </Field>
        <Field label="Cost per switch (bps)">
          <input type="number" className={field} value={spec.cost_bps} onChange={(e) => set("cost_bps", Number(e.target.value))} />
        </Field>
        <Field label="Slippage per switch (bps)">
          <input type="number" className={field} value={spec.slippage_bps ?? 0} onChange={(e) => set("slippage_bps", Number(e.target.value))} />
        </Field>
        {(spec.short ?? []).length > 0 && (
          <Field label="Short borrow (bps a year)">
            <input type="number" className={field} value={spec.borrow_bps_yr ?? 25} onChange={(e) => set("borrow_bps_yr", Number(e.target.value))} />
          </Field>
        )}
        <Field label="Data from">
          <input type="date" className={field} value={spec.start} onChange={(e) => set("start", e.target.value)} />
        </Field>
        <Field label="Unseen years (share of the data)">
          <input type="number" step="0.05" min="0.1" max="0.5" className={field} value={spec.unseen_fraction} onChange={(e) => set("unseen_fraction", Number(e.target.value))} />
        </Field>
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-4">
        <Field label="Orders">
          <select className={field} value={`${exec.order_type}:${exec.timing}`}
            onChange={(e) => { const [order_type, timing] = e.target.value.split(":") as [Execution["order_type"], Execution["timing"]]; set("execution", { ...exec, order_type, timing }); }}>
            {ORDER_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </Field>
        {exec.order_type === "limit" && (
          <Field label="Limit offset (bps)">
            <input type="number" min={0} max={500} className={field} value={exec.limit_offset_bps} onChange={(e) => set("execution", { ...exec, limit_offset_bps: Number(e.target.value) })} />
          </Field>
        )}
      </div>

      <div className="mt-4 grid gap-4 sm:grid-cols-5">
        <Field label="Stop-loss %">
          <input type="number" min={0.01} max={90} step="any" className={field} value={exits.stop_loss_pct ?? ""} onChange={(e) => setExit("stop_loss_pct", num(e.target.value))} />
        </Field>
        <Field label="Trailing stop %">
          <input type="number" min={0.01} max={90} step="any" className={field} value={exits.trailing_pct ?? ""} onChange={(e) => setExit("trailing_pct", num(e.target.value))} />
        </Field>
        <Field label="Take-profit %">
          <input type="number" min={0.01} max={1000} step="any" className={field} value={exits.take_profit_pct ?? ""} onChange={(e) => setExit("take_profit_pct", num(e.target.value))} />
        </Field>
        <Field label="Max days held">
          <input type="number" min={1} max={756} className={field} value={exits.max_days ?? ""} onChange={(e) => setExit("max_days", num(e.target.value))} />
        </Field>
        <Field label="Exits checked">
          <select className={field} value={exits.mode} onChange={(e) => setExit("mode", e.target.value as Exits["mode"])}>
            <option value="close">At each close</option>
            <option value="intraday" disabled={legs !== 1}>During the day: real stop orders (one ticker)</option>
          </select>
        </Field>
      </div>

      {exits.mode === "intraday" && (
        <p className="mt-2 text-xs text-slate-400">
          During the day, Alpaca holds one resting exit per position: a stop, a take-profit, both together, or a trailing stop on its own.
          The stop goes on after the morning order fills (about 9:45 to 10:45am New York).
        </p>
      )}

      <Field label="Assumptions (one per line; edit any you disagree with)">
        <textarea rows={3} className={field} value={spec.assumptions.join("\n")} onChange={(e) => set("assumptions", e.target.value.split("\n").filter((l) => l.trim()))} />
      </Field>

      <button
        type="button"
        onClick={() => onRun(spec)}
        disabled={busy}
        className="mt-4 inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 font-medium text-emerald-950 hover:bg-emerald-400 disabled:opacity-50"
      >
        {busy && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} {busy ? "Testing…" : "Run it"}
      </button>
    </section>
  );
}

function Mark({ ok }: { ok: boolean | null }) {
  if (ok === null) return <span className="text-slate-400">~</span>;
  return ok ? <span className="text-emerald-400">✓</span> : <span className="text-rose-400">✗</span>;
}

/** Year by year, the rolling 12-month excess, and the raw daily data: why a run passed or failed, and when. */
function DeeperLook({ ideaId, run }: { ideaId: string; run: Run }) {
  const [data, setData] = useState<RunAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const base = `/api/workshop/ideas/${ideaId}/runs/${run.id}`;
  useEffect(() => {
    setData(null);
    setError(null);
  }, [run.id]);
  const load = async () => {
    setBusy(true);
    setError(null);
    try {
      setData(await adminJson<RunAnalysis>(`${base}/analysis`));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't load it.");
    } finally {
      setBusy(false);
    }
  };
  const download = async () => {
    setDownloading(true);
    setError(null);
    try {
      await adminDownload(`${base}/daily.csv`, `idea-${ideaId}-run-${run.id}-daily.csv`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed");
    } finally {
      setDownloading(false);
    }
  };
  const split = run.result.split_date;
  return (
    <div className="mt-4">
      <div className="flex flex-wrap gap-2">
        {!data && <button type="button" className={button} disabled={busy} onClick={load}>{busy ? "Loading…" : "Year by year"}</button>}
        <button type="button" className={button} disabled={downloading} onClick={download}>{downloading ? "Downloading…" : "Download daily data (CSV)"}</button>
      </div>
      {error && <p className="mt-2 text-sm text-rose-300">{error}</p>}
      {data && (
        <>
          {data.rolling.length > 1 && (
            <div className="mt-4 h-40" aria-label="Rolling 12-month excess return">
              <div className="text-xs text-slate-400">Rolling 12 months: idea minus {run.spec.benchmark}, pts</div>
              <ResponsiveContainer width="100%" height="90%">
                <LineChart data={data.rolling} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                  <XAxis dataKey="t" tickFormatter={(t: string) => t.slice(0, 4)} stroke="#64748b" fontSize={11} minTickGap={40} />
                  <YAxis tickFormatter={(v: number) => v.toFixed(0)} stroke="#64748b" fontSize={11} width={40} />
                  <Tooltip contentStyle={{ background: "#0f172a", border: "1px solid #1e293b" }} formatter={(v: number) => [`${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(1)} pts`, "excess"]} />
                  <ReferenceLine y={0} stroke="#475569" />
                  {split && data.rolling.length > 0 && split >= data.rolling[0].t && split <= data.rolling[data.rolling.length - 1].t && <ReferenceLine x={data.rolling.find((p) => p.t >= split)?.t} stroke="#94a3b8" strokeDasharray="3 3" />}
                  <Line type="monotone" dataKey="excess" stroke="#fbbf24" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[30rem] text-xs tabular-nums">
              <thead className="text-left text-slate-400">
                <tr>
                  <th className="py-1 font-medium">Year</th><th className="py-1 text-right font-medium">Idea</th>
                  <th className="py-1 text-right font-medium">{run.spec.benchmark}</th><th className="py-1 text-right font-medium">Excess, pts</th>
                  <th className="py-1 text-right font-medium">Days in</th><th className="py-1 text-right font-medium">Idea while in</th>
                </tr>
              </thead>
              <tbody>
                {data.years.map((y) => (
                  <tr key={y.year} className={`border-t border-slate-800/80 ${split && String(y.year) > split.slice(0, 4) ? "bg-slate-900/60" : ""}`}>
                    <td className="py-1 text-slate-300">{y.year}{split && String(y.year) === split.slice(0, 4) ? <span className="ml-1 text-xs text-slate-500">split</span> : null}</td>
                    <td className="py-1 text-right text-slate-200">{pct(y.idea)}</td>
                    <td className="py-1 text-right text-slate-400">{pct(y.bench)}</td>
                    <td className={`py-1 text-right ${y.excess >= 0 ? "text-emerald-300" : "text-rose-300"}`}>{`${y.excess >= 0 ? "+" : "−"}${Math.abs(y.excess).toFixed(1)}`}</td>
                    <td className="py-1 text-right text-slate-400">{y.days_in.toFixed(0)}%</td>
                    <td className="py-1 text-right text-slate-400">{pct(y.idea_in)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-1 text-xs text-slate-500">Shaded rows: unseen years. Recomputed from the run's spec, up to {data.data_end}.</p>
            {data.drift_pts != null && Math.abs(data.drift_pts) >= 1 && (
              <p className="mt-1 text-xs text-amber-300">
                Today's data differs from the verdict by {data.drift_pts >= 0 ? "+" : "−"}{Math.abs(data.drift_pts).toFixed(1)} pts of total return (revised prices or series), so these rows may not match the card exactly.
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export function VerdictCard(props: { ideaId: string; run: Run; onVary: (s: IdeaSpec) => void }) {
  return isEvent(props.run.spec) ? <EventVerdictCard {...props} /> : <RuleVerdictCard {...props} />;
}

const sgn = (v: number | null | undefined, d = 2) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(d)}`);

/** An event study's verdict: the claim on built vs unseen events, random dates, shrunk per-ticker means, events. */
function EventVerdictCard({ ideaId, run, onVary }: { ideaId: string; run: Run; onVary: (s: IdeaSpec) => void }) {
  const r = run.result;
  const spec = run.spec as unknown as EventSpec;
  const [error, setError] = useState<string | null>(null);
  const events = r.events ?? [];
  return (
    <article className="mt-6 rounded-xl border border-slate-800 p-5">
      <div className="flex flex-wrap items-center gap-4">
        <div className={`rounded-lg border-2 px-4 py-1 text-2xl font-extrabold ${toneClass[verdictTone(run.verdict)]}`}>{run.verdict}</div>
        <div className="min-w-0">
          <div className="text-lg font-semibold text-white">{r.headline}</div>
          <div className="text-xs text-slate-400">
            Variation {run.variation} · Event study · {EVENT_LABELS[spec.event]}{spec.event === "earnings" && spec.when !== "all" ? ` (${spec.when}s)` : ""}{spec.event === "gap" ? ` (${spec.when} ${spec.gap_pct}%+)` : ""} · {spec.tickers.join(", ")} · {WINDOW_LABELS[spec.window]} {spec.direction} vs {spec.benchmark} · {r.n_events ?? "—"} events
          </div>
        </div>
      </div>
      {r.reason && <p className="mt-3 text-sm text-slate-300">{r.reason}</p>}

      {r.claim && r.shuffle && (
        <table className="mt-4 w-full text-sm">
          <tbody className="divide-y divide-slate-800/80">
            <tr><td className="py-1.5 text-slate-300">On the events it was built on</td><td className="py-1.5 text-slate-400">{r.claim.built.label}</td><td><Mark ok={r.claim.built.holds} /></td></tr>
            <tr><td className="py-1.5 text-slate-300">On the newest events (unseen)</td><td className="py-1.5 text-slate-400">{r.claim.unseen.label}</td><td><Mark ok={r.claim.unseen.holds} /></td></tr>
            <tr><td className="py-1.5 text-slate-300">Better than random dates</td><td className="py-1.5 text-slate-400">beats {r.shuffle.beats_pct.toFixed(0)}% of {r.shuffle.permutations.toLocaleString()} random dates · p = {r.shuffle.p.toFixed(3)}, needs &lt; {r.shuffle.bar.toFixed(4).replace(/0+$/, "")}</td><td><Mark ok={r.shuffle.holds ?? null} /></td></tr>
            {r.t_test && <tr><td className="py-1.5 text-slate-300">t-test, unseen events</td><td className="py-1.5 text-slate-400">t = {r.t_test.t.toFixed(2)} · p = {r.t_test.p.toFixed(3)}</td><td><Mark ok={r.t_test.holds ?? null} /></td></tr>}
            {r.periods && <tr><td className="py-1.5 text-slate-300">Holds in each stretch of events</td><td className="py-1.5 text-slate-400">{r.periods.held} of {r.periods.of}</td><td><Mark ok={r.periods.holds ?? null} /></td></tr>}
          </tbody>
        </table>
      )}
      {(r.per_ticker ?? []).length > 0 && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[28rem] text-xs tabular-nums">
            <thead className="text-left text-slate-400">
              <tr><th className="py-1 font-medium">Ticker</th><th className="py-1 text-right font-medium">Events</th><th className="py-1 text-right font-medium">Mean, %</th><th className="py-1 text-right font-medium">Shrunk, %</th><th className="py-1 text-right font-medium">Weight</th></tr>
            </thead>
            <tbody>
              {(r.per_ticker ?? []).map((p) => (
                <tr key={p.ticker} className="border-t border-slate-800/80">
                  <td className="py-1 text-slate-300">{p.ticker}</td><td className="py-1 text-right text-slate-300">{p.n}</td>
                  <td className="py-1 text-right text-slate-300">{sgn(p.mean)}</td><td className="py-1 text-right text-slate-200">{sgn(p.shrunk)}</td>
                  <td className="py-1 text-right text-slate-400">{p.weight.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1 text-xs text-slate-500">Shrunk = each ticker's mean pulled toward the pooled mean by how little evidence it has (Strategy HQ shrinkage).</p>
        </div>
      )}
      {events.length > 0 && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[34rem] text-xs tabular-nums">
            <thead className="text-left text-slate-400">
              <tr><th className="py-1 font-medium">Date</th><th className="py-1 font-medium">Ticker</th><th className="py-1 text-right font-medium">Surprise</th><th className="py-1 text-right font-medium">Reaction</th><th className="py-1 text-right font-medium">+1..+3</th><th className="py-1 text-right font-medium">+1..+5</th><th className="py-1 text-right font-medium">+1..+10</th></tr>
            </thead>
            <tbody>
              {events.slice(-15).reverse().map((e) => (
                <tr key={`${e.date}-${e.ticker}`} className="border-t border-slate-800/80">
                  <td className="py-1 text-slate-300">{e.date}</td><td className="py-1 text-slate-300">{e.ticker}</td>
                  <td className="py-1 text-right text-slate-400">{e.surprise == null ? "—" : `${sgn(e.surprise, 1)}%`}</td>
                  <td className="py-1 text-right text-slate-300">{sgn(e.ar0)}</td><td className="py-1 text-right text-slate-300">{sgn(e.car_1_3)}</td>
                  <td className="py-1 text-right text-slate-300">{sgn(e.car_1_5)}</td><td className="py-1 text-right text-slate-300">{sgn(e.car_1_10)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-1 text-xs text-slate-500">The latest 15 of {events.length} events; % vs {spec.benchmark}. The CSV has them all.</p>
        </div>
      )}
      {error && <p className="mt-2 text-sm text-rose-300">{error}</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <button type="button" className={button} onClick={() => adminDownload(`/api/workshop/ideas/${ideaId}/runs/${run.id}/daily.csv`, `idea-${ideaId}-run-${run.id}-events.csv`).catch((e) => setError(e instanceof Error ? e.message : "Download failed"))}>Download events (CSV)</button>
        <button type="button" onClick={() => onVary(run.spec)} className={button}>Try a variation</button>
      </div>
    </article>
  );
}

function RuleVerdictCard({ ideaId, run, onVary }: { ideaId: string; run: Run; onVary: (s: IdeaSpec) => void }) {
  const r = run.result;
  const tone = verdictTone(run.verdict);
  return (
    <article className="mt-6 rounded-xl border border-slate-800 p-5">
      <div className="flex flex-wrap items-center gap-4">
        <div className={`rounded-lg border-2 px-4 py-1 text-2xl font-extrabold ${toneClass[tone]}`}>{run.verdict}</div>
        <div className="min-w-0">
          <div className="text-lg font-semibold text-white">{r.headline}</div>
          <div className="text-xs text-slate-400">
            Variation {run.variation} · {run.spec.hold.join(", ")} {rulesText(run.spec)} · {claimLabel(run.spec.claim)}
            {run.spec.portfolio && ` · as ${Math.round(run.spec.portfolio.idea_share * 100)}% of a portfolio with ${run.spec.portfolio.core.join(", ")}`}
          </div>
        </div>
      </div>
      {r.reason && <p className="mt-3 text-sm text-slate-300">{r.reason}</p>}

      {r.curve.length > 1 && (
        <div className="mt-4 h-48" aria-label="Idea vs benchmark, cumulative">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={r.curve} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <XAxis dataKey="t" tickFormatter={(t: string) => t.slice(0, 4)} stroke="#64748b" fontSize={11} minTickGap={40} />
              <YAxis tickFormatter={(v: number) => `${v.toFixed(0)}%`} stroke="#64748b" fontSize={11} width={48} />
              <Tooltip
                contentStyle={{ background: "#0f172a", border: "1px solid #1e293b" }}
                formatter={(v: number, name: string) => [pct(v), name === "idea" ? "Idea" : run.spec.benchmark]}
              />
              {r.split_date && <ReferenceLine x={r.curve.find((p) => p.t >= r.split_date!)?.t} stroke="#94a3b8" strokeDasharray="3 3" label={{ value: "unseen years →", position: "insideTopRight", fill: "#94a3b8", fontSize: 11 }} />}
              <Line type="monotone" dataKey="idea" stroke="#fbbf24" strokeWidth={2.5} dot={false} />
              <Line type="monotone" dataKey="benchmark" stroke="#94a3b8" strokeWidth={2} strokeDasharray="4 3" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {r.curve.length > 1 && <p className="mt-1 text-xs text-slate-500">Cumulative return since {r.data_start}, % (not log)</p>}

      {r.claim && r.shuffle && (
        <table className="mt-4 w-full text-sm">
          <tbody className="divide-y divide-slate-800/80">
            <tr><td className="py-1.5 text-slate-300">On the years it was built on</td><td className="py-1.5 text-slate-400">{r.claim.built.label}</td><td><Mark ok={r.claim.built.holds} /></td></tr>
            <tr><td className="py-1.5 text-slate-300">On the unseen years</td><td className="py-1.5 text-slate-400">{r.claim.unseen.label}</td><td><Mark ok={r.claim.unseen.holds} /></td></tr>
            <tr><td className="py-1.5 text-slate-300">Better than chance ({r.shuffle.method})</td><td className="py-1.5 text-slate-400">beats {r.shuffle.beats_pct.toFixed(0)}% of {r.shuffle.permutations.toLocaleString()} · p = {r.shuffle.p.toFixed(3)}, needs &lt; {r.shuffle.bar.toFixed(4).replace(/0+$/, "")}</td><td><Mark ok={r.shuffle.p < r.shuffle.bar} /></td></tr>
            {r.t_test && <tr><td className="py-1.5 text-slate-300">t-test, daily difference</td><td className="py-1.5 text-slate-400">{pct(r.t_test.mean_daily_diff, 3)}/day · p = {r.t_test.p.toFixed(3)}{r.t_test.p < 0.05 && r.t_test.mean_daily_diff < 0 ? " · significant, but the wrong way" : ""}</td><td><Mark ok={r.t_test.p < 0.05 ? r.t_test.mean_daily_diff > 0 : null} /></td></tr>}
            {r.periods && <tr><td className="py-1.5 text-slate-300">Holds in each market period</td><td className="py-1.5 text-slate-400">{r.periods.held} of {r.periods.of}</td><td><Mark ok={r.periods.held >= 4 ? true : r.periods.held <= 1 ? false : null} /></td></tr>}
            <tr><td className="py-1.5 text-slate-300">Variations tried on this idea</td><td className="py-1.5 text-slate-400">{r.variations} · bar raised accordingly</td><td /></tr>
          </tbody>
        </table>
      )}

      <p className="mt-1 text-xs text-slate-500">✓ holds · ✗ fails · ~ mixed or not decisive</p>

      {r.context.length > 0 && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[28rem] text-xs tabular-nums">
            <thead className="text-left text-slate-400">
              <tr><th className="py-1 font-medium">Per year (CAGR)</th><th className="py-1 text-right font-medium">Built years</th><th className="py-1 text-right font-medium">Unseen years</th><th className="py-1 text-right font-medium">Unseen worst drop</th></tr>
            </thead>
            <tbody>
              {r.context.map((c) => (
                <tr key={c.name} className="border-t border-slate-800/80">
                  <td className={`py-1 ${c.name === "Idea" ? "font-semibold text-amber-300" : "text-slate-300"}`}>{c.name}{c.name === run.spec.benchmark ? " (benchmark)" : ""}</td>
                  <td className="py-1 text-right text-slate-300">{pct(c.built_cagr)}</td>
                  <td className="py-1 text-right text-slate-300">{pct(c.unseen_cagr)}</td>
                  <td className="py-1 text-right text-slate-300">{pct(c.unseen_max_dd, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <DeeperLook ideaId={ideaId} run={run} />

      {run.spec.assumptions.length > 0 && (
        <ul className="mt-3 list-disc pl-5 text-xs text-slate-400">
          {run.spec.assumptions.map((a) => <li key={a}>{a}</li>)}
        </ul>
      )}
      <button type="button" onClick={() => onVary(run.spec)} className="mt-4 rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-900">
        Try a variation
      </button>
    </article>
  );
}

const button = "rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-900 disabled:opacity-50";

/** Publish, the live-paper gate, the order tag and the kill button (spec §4.5-4.6). Each step happens once. */
export function LifecyclePanel({ id, detail, onChange }: { id: string; detail: IdeaDetail; onChange: () => void }) {
  const { idea, runs, tag, shadow } = detail;
  const [size, setSize] = useState("");
  const [gate, setGate] = useState<GateResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const passed = runs.length > 0 && runs[runs.length - 1].verdict === "PASS";

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That didn't work");
    } finally {
      setBusy(false);
    }
  };
  const check = () => act(async () => setGate(await adminJson<GateResult>(`/api/workshop/ideas/${id}/gate?size_pct=${encodeURIComponent(size)}`)));
  const goLive = () => act(() => adminJson(`/api/workshop/ideas/${id}/live`, { method: "POST", body: JSON.stringify({ size_pct: Number(size) }) }));
  const toggleAuto = () => {
    const on = !idea.auto_orders;
    if (on && !window.confirm(`Turn on automatic paper orders? Each weekday morning the hub trades this idea's rule in the paper account at ${idea.size_pct}% of the account, skipping any order that would put one stock over 25%.`)) return;
    act(() => adminJson(`/api/workshop/ideas/${id}/auto`, { method: "POST", body: JSON.stringify({ on }) }));
  };
  const kill = () => {
    if (!window.confirm("Kill this idea? Its paper record stops today and stays on the record. If it traded automatically, its paper positions are closed at the next open.")) return;
    act(() => adminJson(`/api/workshop/ideas/${id}/kill`, { method: "POST" }));
  };

  return (
    <section className="mt-6 space-y-4 rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        {idea.published_at ? (
          <span className="text-slate-400">Published {idea.published_at.slice(0, 10)} · <Link to={`/ideas/${id}`} className="text-emerald-300 hover:underline">public record</Link></span>
        ) : (
          <button type="button" className={button} disabled={busy} onClick={() => act(() => adminJson(`/api/workshop/ideas/${id}/publish`, { method: "POST" }))}>
            Publish to the Ideas record
          </button>
        )}
      </div>

      {passed && !idea.live_at && (
        <div>
          <h2 className="text-sm font-semibold text-white">Live-paper gate</h2>
          <p className="mt-1 text-xs text-slate-400">The claim must still hold on at least 63 trading days the backtest never saw, and each position must be 25% of the account or less.</p>
          <div className="mt-3 flex flex-wrap items-end gap-2">
            <label className="text-xs text-slate-300">
              Size (% of account)
              <input type="number" min={1} max={100} value={size} onChange={(e) => { setSize(e.target.value); setGate(null); }} className={`${field} w-28`} />
            </label>
            <button type="button" className={button} disabled={busy || !size} onClick={check}>Check the gate</button>
            <button type="button" disabled={busy || gate?.status !== "ready"} onClick={goLive}
              className="rounded-lg bg-emerald-500 px-3 py-1.5 text-sm font-medium text-emerald-950 hover:bg-emerald-400 disabled:opacity-50">
              Go live on paper
            </button>
          </div>
          {gate && (
            <ul className="mt-2 space-y-1 text-sm">
              {gate.claim && <li className={gate.claim.holds === true ? "text-emerald-300" : gate.claim.holds === false ? "text-rose-300" : "text-slate-300"}>New data: {gate.claim.label}</li>}
              {gate.reasons.map((r) => <li key={r} className="text-slate-300">{r}</li>)}
              {gate.status === "ready" && <li className="text-emerald-300">Clear. Press Go live to start the paper record.</li>}
            </ul>
          )}
        </div>
      )}

      {idea.live_at && (
        <div className="space-y-2">
          <p className="text-sm text-slate-300">
            {idea.killed_at ? `Killed ${idea.killed_at.slice(0, 10)}` : "Live on paper"} · since {idea.live_at.slice(0, 10)} · size {idea.size_pct}%
          </p>
          {shadow && <PaperLine live={shadow} />}
          {!idea.killed_at && tag && (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-slate-400">Order tag (start each client order id with it):</span>
              <code className="rounded bg-slate-800 px-2 py-0.5 text-amber-200">{tag}</code>
              <button type="button" className={button} onClick={() => navigator.clipboard?.writeText(tag)}>Copy tag</button>
            </div>
          )}
          {!idea.killed_at && (
            <div className="space-y-1 border-t border-slate-800 pt-3">
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <span className="text-slate-300">Automatic paper orders: <strong className={idea.auto_orders ? "text-emerald-300" : "text-slate-400"}>{idea.auto_orders ? "on" : "off"}</strong></span>
                <button type="button" className={button} disabled={busy} onClick={toggleAuto}>
                  {idea.auto_orders ? "Turn off automatic paper orders" : "Turn on automatic paper orders"}
                </button>
              </div>
              {!detail.orders_enabled && (
                <p className="text-xs text-amber-300">The server's paper-order switch is off, so nothing is sent until it's turned on.</p>
              )}
            </div>
          )}
          {(detail.orders?.length ?? 0) > 0 && (
            <table className="w-full text-xs">
              <thead className="text-left text-slate-500">
                <tr><th className="py-1 font-normal">Day</th><th className="font-normal">Order</th><th className="font-normal">Status</th></tr>
              </thead>
              <tbody>
                {detail.orders?.map((o) => (
                  <tr key={o.id} className="border-t border-slate-800 align-top">
                    <td className="whitespace-nowrap py-1 pr-2 text-slate-400">{o.day}</td>
                    <td className="py-1 pr-2 font-mono text-slate-200">{o.side} {o.qty} {o.symbol}</td>
                    <td className="py-1"><span className={o.status === "sent" ? "text-emerald-300" : o.status === "rejected" ? "text-rose-300" : "text-slate-400"}>{o.status}</span>{o.reason && <span className="block text-slate-500">{o.reason}</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {!idea.killed_at && (
            <button type="button" className="rounded-lg border border-rose-500/40 px-3 py-1.5 text-sm text-rose-300 hover:bg-rose-500/10" disabled={busy} onClick={kill}>
              Kill this idea
            </button>
          )}
        </div>
      )}
      {error && <p role="alert" className="text-sm text-rose-300">{error}</p>}
    </section>
  );
}

export default function WorkshopIdea() {
  // Only a numeric id ever reaches a URL: the requests below carry Kevin's session token, so a crafted link
  // must not be able to point them at another API path.
  const raw = useParams().id ?? "";
  const id = /^\d+$/.test(raw) ? raw : null;
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<IdeaDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ spec: IdeaSpec; model: string | null; note?: string; play?: PlayMatch | null; alternatives?: DraftResponse["alternatives"]; dropped?: string[] } | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [running, setRunning] = useState(false);

  const load = useCallback(() => {
    if (id === null) {
      setError("No such idea.");
      return Promise.resolve();
    }
    return adminJson<IdeaDetail>(`/api/workshop/ideas/${id}`).then(setData).catch((e: Error) => setError(e.message));
  }, [id]);
  useEffect(() => {
    load();
  }, [load]);

  const requestDraft = useCallback((text: string, title: string, free = false) => {
    setDrafting(true);
    adminJson<DraftResponse>("/api/workshop/draft", { method: "POST", body: JSON.stringify({ text, free }) })
      .then((d) => setDraft({ spec: d.spec, model: d.model, play: d.play, alternatives: d.alternatives, dropped: d.dropped }))
      .catch((e: unknown) => {
        const template = e instanceof ApiError ? (e.body?.template as IdeaSpec | undefined) : undefined;
        if (template) setDraft({ spec: { ...template, title: title.slice(0, 120) }, model: null, note: "The AI couldn't draft this — fill it in." });
        else setError(e instanceof Error ? e.message : "Draft failed");
      })
      .finally(() => {
        setDrafting(false);
        setParams({}, { replace: true });
      });
  }, [setParams]);

  useEffect(() => {
    if (!data || params.get("draft") !== "1" || draft || drafting) return;
    try {
      if (localStorage.getItem(`workshop-draft-${id}`)) return;
    } catch { void 0; }
    requestDraft(data.idea.plain_words, data.idea.title);
  }, [data, params, draft, drafting, requestDraft, id]);

  useEffect(() => {
    if (!data || draft || drafting) return;
    const key = `workshop-draft-${id}`;
    try {
      const raw = localStorage.getItem(key);
      if (raw) {
        const spec = JSON.parse(raw) as IdeaSpec;
        setDraft({ spec, model: null, play: null, alternatives: [], dropped: [] });
      }
    } catch { void 0; }
  }, [data, draft, drafting, id]);

  /** Swap the draft for one of the other plays the words matched. */
  const switchPlay = (alt: DraftResponse["alternatives"][number]) => {
    if (!draft?.play) return;
    const { spec: current } = draft;
    const others = (draft.alternatives ?? []).filter((a) => a.id !== alt.id);
    const { spec, ...play } = alt;
    setDraft({ spec, model: "playbook", play, alternatives: [...others, { ...draft.play, spec: current }] });
  };

  const run = async (spec: IdeaSpec) => {
    if (id === null) return;
    setRunning(true);
    setError(null);
    try {
      const route = isEvent(spec) ? "event-runs" : "runs";
      await adminJson<Run>(`/api/workshop/ideas/${id}/${route}`, { method: "POST", body: JSON.stringify({ spec, draft_model: draft?.model ?? null }) });
      try { localStorage.removeItem(`workshop-draft-${id}`); } catch { void 0; }
      setDraft(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Run failed");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="mx-auto max-w-4xl px-4 py-8 md:px-8">
      <Link to="/workshop" className="inline-flex items-center gap-1 text-sm text-slate-400 hover:text-slate-200">
        <ArrowLeft className="h-4 w-4" aria-hidden="true" /> Workshop
      </Link>
      {data && <h1 className="mt-3 text-xl font-semibold text-white">“{data.idea.plain_words}”</h1>}
      {error && <p role="alert" className="mt-4 text-sm text-rose-300">{error}</p>}
      {data && id && <LifecyclePanel id={id} detail={data} onChange={load} />}
      {drafting && (
        <p className="mt-6 flex items-center gap-2 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> The AI is drafting the test…
        </p>
      )}
      {draft?.play && data && (
        <section className="mt-6 rounded-xl border border-emerald-500/30 bg-emerald-500/5 p-4 text-sm" aria-label="Matched play">
          <div className="text-xs uppercase tracking-wide text-emerald-300">Matched play</div>
          <div className="mt-1 font-semibold text-white">{draft.play.name}</div>
          <p className="mt-0.5 text-slate-300">{draft.play.summary}</p>
          <p className="mt-1 text-xs text-slate-400">
            Matched on: {draft.play.why.map((w) => `“${w}”`).join(", ")} · from {draft.play.source}
            {draft.model && draft.model !== "playbook" ? ` · picked by ${draft.model}` : " · picked by word match"}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {(draft.alternatives ?? []).map((a) => (
              <button key={a.id} type="button" className={button} onClick={() => switchPlay(a)}>Use {a.name} instead</button>
            ))}
            <button type="button" className={button} disabled={drafting} onClick={() => { setDraft(null); requestDraft(data.idea.plain_words, data.idea.title, true); }}>
              Write it from scratch
            </button>
          </div>
        </section>
      )}
      {draft?.dropped && draft.dropped.length > 0 && (
        <p className="mt-4 text-sm text-amber-300">The draft left out: {draft.dropped.join(", ")}. Add them back if you meant them.</p>
      )}
      {draft && (
        <div className="mt-4 flex justify-end">
          <button type="button" className={button} onClick={() => { try { localStorage.removeItem(`workshop-draft-${id}`); } catch { void 0; } setDraft(null); }}>
            Discard saved draft
          </button>
        </div>
      )}
      {draft && <DraftEditor key={JSON.stringify(draft.spec)} initial={draft.spec} onRun={run} busy={running} note={draft.note} storageKey={id ? `workshop-draft-${id}` : undefined} />}
      {data && data.runs.length === 0 && !draft && !drafting && (
        <button type="button" onClick={() => setParams({ draft: "1" })} className="mt-6 rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-900">
          Draft the test
        </button>
      )}
      {data && [...data.runs].reverse().map((r) => (
        <VerdictCard key={r.id} ideaId={id ?? ""} run={r} onVary={(spec) => { setDraft({ spec, model: null }); window.scrollTo({ top: 0, behavior: "smooth" }); }} />
      ))}
    </div>
  );
}
