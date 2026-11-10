import { Fragment, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDown, ArrowUp, ChevronDown, Loader2, Plus, Trophy, X } from "lucide-react";

import { adminJson, type ScreenRow } from "@/lib/workshop";
import { ctDateTimeYear } from "@/lib/format";
import { VerdictChipLine } from "@/components/VerdictChip";
import type { ChipsPayload, VerdictChip } from "@/lib/decisions";
import {
  OP_LABELS, PRESETS, UNIVERSES, specFromState, trayFromSpec,
  type CardFn, type Catalog, type NearMiss, type QuotePayload, type RunPayload, type ScoreTerm, type ScreenSpec, type TrayItem,
} from "@/lib/screening";

export function survivorText(n: number): string {
  return `${n} survivor${n === 1 ? "" : "s"}`;
}

/** Plain words for a universe the buttons cannot express (a loaded saved
 * spec's union / wrapper chain), so the page says what will actually run. */
export function universeWords(u: ScreenSpec["universe"]): string {
  if (!u) return "the saved universe";
  if (u.type === "common_equity") {
    return `common equities only · ${universeWords(u.base as ScreenSpec["universe"])}`;
  }
  if (u.type === "sector") return universeWords(u.base as ScreenSpec["universe"]);
  if (u.type === "index_union") {
    const names: Record<string, string> = { sp500: "S&P 500", nasdaq100: "Nasdaq-100",
                                            nasdaq_all: "all US listed" };
    return `${(u.indexes ?? []).map((i) => names[i] ?? i).join(" + ")} union`;
  }
  if (u.type === "index") return u.index ?? "an index";
  if (u.type === "list") return `${u.tickers?.length ?? 0} saved tickers`;
  return u.type;
}

function fmtCell(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") return Math.abs(v) >= 1000 ? v.toLocaleString("en-US", { maximumFractionDigits: 0 })
    : v.toLocaleString("en-US", { maximumFractionDigits: 3 });
  return String(v);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** "2026-11-10" (or an ISO timestamp) -> "Nov 10", by string split — no Date
 * object, so no timezone can shift the day. */
function fmtDay(iso: string): string {
  const [, m, d] = (iso ?? "").slice(0, 10).split("-").map(Number);
  return m >= 1 && m <= 12 && d >= 1 ? `${MONTHS[m - 1]} ${d}` : iso;
}

/** The right-hand side of a near-miss comparison: "< 7", "≥ 20", "between 3–5". */
function cmpText(op: string, thr: unknown): string {
  const v = Array.isArray(thr) ? thr.map((x) => fmtCell(x)).join("–") : fmtCell(thr);
  switch (op) {
    case "lt": return `< ${v}`;
    case "le": return `≤ ${v}`;
    case "gt": return `> ${v}`;
    case "ge": return `≥ ${v}`;
    case "eq": return `= ${v}`;
    case "ne": return `≠ ${v}`;
    case "between": return `between ${v}`;
    case "pct_gte": case "pct_ge": return `top slice ≥ ${v}%`;
    case "pct_lte": case "pct_le": return `bottom slice ≤ ${v}%`;
    case "in": return `one of ${v}`;
    default: return `${op} ${v}`;
  }
}

/** Screening: describe it or build it from filter cards (the prototype's
 * design) -- each card explains itself and starts from a plausible number
 * in the direction people usually mean. The composed spec is shown
 * read-only for the record. Missing data fails a filter, never reads as
 * zero; a saved screen promotes once into a tracked Workshop idea. */
/** One library group behind its own dropdown: the whole library is six
 * closed rows, not a page of cards (Kevin, 2026-11-03). */
function LibraryGroup({ group, count, children }: { group: string; count: number; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-3 rounded-xl border border-slate-800 bg-slate-900/40">
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}
              className="flex w-full items-center gap-2 px-3.5 py-2.5 text-left">
        <span className="text-sm font-medium text-slate-200">{group}</span>
        <span className="text-xs text-slate-500">{count} filters</span>
        <ChevronDown className={`ml-auto h-4 w-4 shrink-0 text-slate-500 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {open && <div className="px-3.5 pb-3.5">{children}</div>}
    </div>
  );
}

/** A year of daily closes as a plain line: green when the year is up. */
function PriceChart({ closes }: { closes: { date: string; close: number }[] }) {
  if (closes.length < 2) return null;
  const vals = closes.map((c) => c.close);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const W = 560, H = 120, P = 6;
  const pts = closes.map((c, i) =>
    `${(P + (i / (closes.length - 1)) * (W - 2 * P)).toFixed(1)},${(H - P - ((c.close - min) / span) * (H - 2 * P)).toFixed(1)}`
  ).join(" ");
  const up = vals[vals.length - 1] >= vals[0];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mt-2 w-full" role="img"
         aria-label="Price chart: daily closes over the past year">
      <polyline fill="none" strokeWidth="1.8" points={pts}
                className={up ? "stroke-emerald-400" : "stroke-rose-400"} />
    </svg>
  );
}

export default function Screening() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [query, setQuery] = useState("");
  const [name, setName] = useState("untitled_screen");
  const [universeId, setUniverseId] = useState("sp500");
  const [customTickers, setCustomTickers] = useState("");
  const [tray, setTray] = useState<TrayItem[]>([]);
  const [score, setScore] = useState<ScoreTerm[]>([]);
  const [derived, setDerived] = useState<{ name: string; expr: string }[]>([]);
  const [limitN, setLimitN] = useState(25);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [result, setResult] = useState<RunPayload | null>(null);
  const [sort, setSort] = useState<{ col: string; dir: 1 | -1 } | null>(null);
  const [openRow, setOpenRow] = useState<string | null>(null);
  const [quote, setQuote] = useState<{ ticker: string; data?: QuotePayload; error?: string } | null>(null);
  const [screens, setScreens] = useState<ScreenRow[] | null>(null);
  /** The parts of a loaded saved spec the card builder cannot express
   * (a union/wrapped universe, max_universe, membership_diff, its sort):
   * carried verbatim into the composed spec until the user picks a
   * universe button, which replaces them. Without this, loading a saved
   * classic screen silently rebuilt it as {index: sp500} under the
   * default cap -- the loaded screen was not the saved screen. Round 3:
   * the saved screen's own result limit rides along too (null = it has
   * none) -- the builder's "show top" default of 25 must never leak into
   * a loaded screen's run, where it masqueraded as the cohort count. */
  const [carried, setCarried] = useState<{
    universe: ScreenSpec["universe"]; max_universe?: number;
    membership_diff?: boolean; sort?: ScreenSpec["sort"]; description?: string;
    limit: number | null;
  } | null>(null);
  const [dName, setDName] = useState("");
  const [dA, setDA] = useState("");
  const [dB, setDB] = useState("");
  const [scorePick, setScorePick] = useState("");

  const cards = useMemo(() => catalog?.cards ?? [], [catalog]);
  const byCardId = useMemo(() => new Map(cards.map((c) => [c.id, c])), [cards]);
  const groups = useMemo(() => {
    const out = new Map<string, CardFn[]>();
    for (const c of cards) out.set(c.group, [...(out.get(c.group) ?? []), c]);
    return [...out.entries()];
  }, [cards]);
  const numericFields = useMemo(
    () => (catalog?.functions ?? []).filter((f) => f.kind === "field" && f.returns !== "str"),
    [catalog]);
  /** Field units from the catalog's own returns vocabulary (pct -> %, x -> ×):
   * results tables carried bare numbers until the classic-screens audit. */
  const unitFor = useMemo(() => {
    const m = new Map<string, string>();
    for (const f of catalog?.functions ?? []) {
      if (f.returns === "pct") m.set(f.name, "%");
      else if (f.returns === "x") m.set(f.name, "×");
    }
    return m;
  }, [catalog]);
  const labelForFn = useMemo(() => new Map(cards.map((c) => [c.fn, c.label])), [cards]);
  const colUnit = useMemo(() => {
    const out: Record<string, string> = {};
    for (const c of result?.columns ?? []) {
      const fn = result?.footer.columns?.[c]?.fn ?? c.split("(")[0];
      const u = unitFor.get(fn);
      if (u) out[c] = u;
    }
    return out;
  }, [result, unitFor]);
  /** The missing-data record, grouped per ticker with its fields — the old
   * render was a wall of repeated field names with no tickers or counts. */
  const missingByTicker = useMemo(() => {
    const map = new Map<string, string[]>();
    for (const m of result?.footer.missing ?? []) {
      const arr = map.get(m.ticker) ?? [];
      if (!arr.includes(m.field)) arr.push(m.field);
      map.set(m.ticker, arr);
    }
    return [...map.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [result]);

  useEffect(() => {
    if (!openRow) { setQuote(null); return; }
    let live = true;
    setQuote({ ticker: openRow });
    adminJson<QuotePayload>(`/api/screening/quote/${openRow}`)
      .then((d) => { if (live) setQuote({ ticker: openRow, data: d }); })
      .catch(() => { if (live) setQuote({ ticker: openRow, error: "No quote data for this ticker." }); });
    return () => { live = false; };
  }, [openRow ]);

  const [chips, setChips] = useState<Record<string, VerdictChip>>({});

  const loadScreens = () => adminJson<ScreenRow[]>("/api/screening/screens").then(setScreens).catch(() => setScreens([]));
  useEffect(() => {
    adminJson<Catalog>("/api/screening/catalog").then(setCatalog).catch(() => setCatalog(null));
    loadScreens();
    // Verdict chips ride beside the results: the debate judgment sits
    // with the name on this page too, not only in a debates corner.
    adminJson<ChipsPayload>("/api/verdict-chips")
      .then((env) => { if (env?.chips) setChips(env.chips); })
      .catch(() => { /* absence renders as "No debate verdict yet" */ });
  }, []);

  const spec = useMemo(() => {
    const base = specFromState({ name, universeId, customTickers, tray, derived, score, limit: limitN });
    if (!carried) return base;
    const out: ScreenSpec = { ...base, universe: carried.universe };
    if (carried.max_universe != null) out.max_universe = carried.max_universe;
    if (carried.membership_diff != null) out.membership_diff = carried.membership_diff;
    if (carried.description != null) out.description = carried.description;
    if (carried.sort && !base.sort) out.sort = carried.sort;
    // The saved screen's own limit governs its card runs -- including
    // "no limit", which deletes the builder's show-top value outright.
    if (carried.limit == null) delete out.limit;
    else out.limit = carried.limit;
    return out;
  }, [name, universeId, customTickers, tray, derived, score, limitN, carried]);

  const act = async (label: string, fn: () => Promise<void>) => {
    setBusy(label); setError(null); setNotice(null);
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : "Something failed"); }
    setBusy("");
  };

  const applySpec = (sp: ScreenSpec, note: string) => {
    const { tray: t, score: s, derived: d } = trayFromSpec(sp, cards);
    setTray(t); setScore(s); setDerived(d);
    if (sp.name) setName(sp.name);
    const u = sp.universe;
    if (u?.type === "index" && u.index && UNIVERSES.some((x) => x.id === u.index)) {
      setUniverseId(u.index);
      setCarried(null);
    } else if (u?.type === "list") {
      setUniverseId("custom"); setCustomTickers((u.tickers ?? []).join(" "));
      setCarried(null);
    } else if (u) {
      // A universe the buttons cannot express (union, common_equity, ...):
      // carry it verbatim -- never fall through to the sp500 default.
      setUniverseId("");
      setCarried({ universe: u, max_universe: sp.max_universe,
        membership_diff: sp.membership_diff, sort: sp.sort,
        description: typeof sp.description === "string" ? sp.description : undefined,
        limit: typeof sp.limit === "number" ? sp.limit : null });
    } else {
      setCarried(null);
    }
    if (typeof sp.limit === "number") setLimitN(sp.limit);
    setResult(null);
    setNotice(note);
  };

  const addCard = (card: CardFn) => {
    if (tray.some((t) => t.key === card.id)) return;
    setTray((prev) => [...prev, { key: card.id, fn: card.fn, params: card.params, label: card.label,
      unit: card.unit, divisor: card.divisor, source: card.source, custom: false,
      op: card.preset.op, value: card.preset.value }]);
  };

  const applyPreset = (presetId: string) => {
    const preset = PRESETS.find((p) => p.id === presetId);
    if (!preset) return;
    const items: TrayItem[] = [];
    for (const item of preset.items) {
      const card = byCardId.get(item.card);
      if (card) items.push({ key: card.id, fn: card.fn, params: card.params, label: card.label,
        unit: card.unit, divisor: card.divisor, source: card.source, custom: false,
        op: item.op, value: item.value });
    }
    setTray(items);
    setCarried(null);
    const sc = preset.scoreCard ? byCardId.get(preset.scoreCard) : undefined;
    setScore(sc ? [{ fn: sc.fn, params: sc.params, label: sc.label, weight: 1,
                     direction: preset.scoreDirection ?? "high" }] : []);
    setDerived([]);
    setName(preset.id.replace(/-/g, "_"));
    setResult(null);
    setNotice(`${preset.name} loaded -- nudge any number, then run it.`);
  };

  const translate = () => act("translate", async () => {
    const d = await adminJson<{ spec: ScreenSpec; model: string }>("/api/screening/translate",
      { method: "POST", body: JSON.stringify({ query }) });
    applySpec(d.spec, d.model.startsWith("rules")
      ? `Built by the built-in rules (${d.model}) -- the cards below are set; nudge any number, then run.`
      : `Translated by ${d.model} -- the cards below are set; nudge any number, then run.`);
  });

  const runSpec = (sp: ScreenSpec) => act("run", async () => {
    const d = await adminJson<RunPayload>("/api/screening/run", { method: "POST", body: JSON.stringify({ spec: sp }) });
    setResult(d); setSort(null); setOpenRow(null);
  });

  const runSaved = (sc: ScreenRow) => act("run", async () => {
    const d = await adminJson<RunPayload>(`/api/screening/screens/${sc.id}/run`, { method: "POST", body: "{}" });
    applySpec(sc.spec as ScreenSpec, `Re-ran saved screen "${sc.name}".`);
    setResult(d); setSort(null); setOpenRow(null);
    loadScreens();
  });

  const save = () => act("save", async () => {
    // Round 3: a save stores the SPEC only. Builder runs are ad-hoc --
    // they never become a screen's recorded run or membership baseline;
    // only the saved-screen run path (Re-run) writes those. Pre-fix, the
    // builder's current (possibly display-truncated) result rode along
    // as the new screen's last_run.
    await adminJson("/api/screening/screens", { method: "POST",
      body: JSON.stringify({ spec, name }) });
    loadScreens();
    setNotice("Screen saved -- use Re-run on the saved screen to record a run; it promotes once into a tracked idea.");
  });

  const promote = (sc: ScreenRow) => act("promote", async () => {
    const d = await adminJson<{ idea_id: number; verdict: string }>(`/api/screening/screens/${sc.id}/promote`,
      { method: "POST", body: "{}" });
    loadScreens();
    setNotice(`Promoted: the basket is now a tracked Workshop idea (first verdict ${d.verdict}).`);
  });

  const remove = (sc: ScreenRow) => act("delete", async () => {
    await adminJson(`/api/screening/screens/${sc.id}`, { method: "DELETE" });
    loadScreens();
  });

  const addDerived = () => {
    const clean = dName.trim().toLowerCase().replace(/[^a-z0-9_]/g, "");
    if (!clean || !dA || !dB) return;
    setDerived((prev) => [...prev.filter((d) => d.name !== clean), { name: clean, expr: `${dA} / ${dB}` }]);
    setDName("");
  };

  const addScore = () => {
    const card = cards.find((c) => c.id === scorePick);
    if (!card || score.some((s) => s.fn === card.fn)) return;
    setScore((prev) => [...prev, { fn: card.fn, params: card.params, label: card.label, weight: 1, direction: "high" }]);
    setScorePick("");
  };

  const rows = useMemo(() => {
    const rs = [...(result?.rows ?? [])];
    if (sort) {
      rs.sort((a, b) => {
        const x = a[sort.col], y = b[sort.col];
        if (x == null && y == null) return 0;
        if (x == null) return 1;
        if (y == null) return -1;
        const c = typeof x === "number" && typeof y === "number" ? x - y : String(x).localeCompare(String(y));
        return c * sort.dir;
      });
    }
    return rs;
  }, [result, sort]);

  const bestFit = useMemo(() => {
    if (!result?.columns.includes("score")) return new Set<string>();
    return new Set([...result.rows].sort((a, b) => Number(b.score ?? -Infinity) - Number(a.score ?? -Infinity))
      .slice(0, 3).map((r) => String(r.ticker)));
  }, [result]);

  const toggleSort = (col: string) =>
    setSort((s) => (s?.col === col ? { col, dir: (s.dir * -1) as 1 | -1 } : { col, dir: col === "ticker" ? 1 : -1 }));

  const inTray = (id: string) => tray.some((t) => t.key === id);

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 md:px-8">
      <h1 className="text-2xl font-bold tracking-tight text-white">Screening</h1>
      <p className="mt-1 text-sm text-slate-400">
        Describe a screen or build one from the filter cards. Every card starts from a plausible number;
        every result carries its source; missing data fails a filter, never reads as zero.
      </p>

      <div className="mt-6 flex gap-2">
        <textarea aria-label="Describe the screen in plain English" value={query} onChange={(e) => setQuery(e.target.value)}
          rows={2} placeholder="stocks with strong momentum and beat earnings with positive guidance"
          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-white placeholder:text-slate-500 focus:border-emerald-400 focus:outline-none" />
        <button type="button" onClick={translate} disabled={!!busy || query.trim().length < 3}
          className="inline-flex shrink-0 items-center gap-2 self-start rounded-lg bg-emerald-500 px-4 py-2 font-medium text-slate-950 hover:bg-emerald-400 disabled:opacity-50">
          {busy === "translate" && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Translate
        </button>
      </div>
      {error && <p role="alert" className="mt-3 text-sm text-rose-300">{error}</p>}
      {notice && <p className="mt-3 text-sm text-emerald-300">{notice}</p>}

      {result && (
        <section aria-label="Results" className="mt-6">
          <p className="text-sm text-slate-400">
            <span className="font-medium text-slate-200">{result.footer.spec_name ?? "screen"}</span>
            {" "}· ran {result.footer.run_at?.replace("T", " ").slice(0, 16)} UTC · universe {result.footer.universe_size ?? "?"}
            {" "}· <span className="text-slate-200">{survivorText(result.footer.survivors ?? result.rows.length)}</span>
            {result.footer.survivor_issuers != null
              && result.footer.survivor_issuers !== (result.footer.survivors ?? result.rows.length) && (
              <span> · {result.footer.survivor_issuers} issuer{result.footer.survivor_issuers === 1 ? "" : "s"}</span>
            )}
            {result.footer.displayed != null && result.footer.survivors != null
              && result.footer.displayed < result.footer.survivors && (
              <span className="text-amber-300"> · showing {result.footer.displayed} of {result.footer.survivors}</span>
            )}
            {result.footer.universe_capped && (
              <span className="text-amber-300"> · enrichment capped at {result.footer.universe_capped.cap} of {result.footer.universe_capped.universe_size_full} names — the first {result.footer.universe_capped.cap} in sorted ticker order</span>
            )}
            {!result.footer.universe_capped && result.footer.universe_selection && (
              <span> · {result.footer.universe_selection}</span>
            )}
            {result.footer.data_as_of && <> · data as of {result.footer.data_as_of.replace("T", " ").slice(0, 16)} UTC</>}
            {" "}· click a column to sort, a row for its quote and provenance
          </p>
          <div className="mt-3 overflow-x-auto rounded-xl border border-slate-800">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
                  {result.columns.map((c) => (
                    <th key={c} className="px-3 py-2">
                      <button type="button" onClick={() => toggleSort(c)} className="inline-flex items-center gap-1 hover:text-slate-200">
                        {c}
                        {colUnit[c] && <span className="normal-case text-slate-500">({colUnit[c]})</span>}
                        {sort?.col === c && (sort.dir === 1
                          ? <ArrowUp className="h-3 w-3" aria-hidden="true" />
                          : <ArrowDown className="h-3 w-3" aria-hidden="true" />)}
                      </button>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const t = String(r.ticker);
                  const fit = bestFit.has(t);
                  return (
                    <Fragment key={t}>
                      <tr onClick={() => setOpenRow(openRow === t ? null : t)}
                          className={`cursor-pointer border-b border-slate-800/70 hover:bg-slate-800/40 ${fit ? "bg-emerald-500/5" : ""}`}>
                        {result.columns.map((c) => (
                          <td key={c} className="px-3 py-2 tabular-nums text-slate-300">
                            {c === "ticker" ? (
                              <span>
                                <span className="flex items-center gap-2 font-mono font-medium text-white">
                                  {t}
                                  {fit && <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-300">
                                    <Trophy className="h-3 w-3" aria-hidden="true" /> Best fit</span>}
                                </span>
                                <VerdictChipLine chip={chips[t]} ticker={t} />
                              </span>
                            ) : fmtCell(r[c])}
                          </td>
                        ))}
                      </tr>
                      {openRow === t && (
                        <tr key={`${t}-prov`} className="border-b border-slate-800 bg-slate-950/60">
                          <td colSpan={result.columns.length} className="px-3 py-3">
                            {quote?.ticker === t && quote.data ? (
                              <div>
                                <p className="text-sm text-slate-200">
                                  Last ${quote.data.price.toFixed(2)}
                                  {quote.data.change_pct != null && (
                                    <span className={quote.data.change_pct >= 0 ? "text-emerald-300" : "text-rose-300"}>
                                      {" "}{quote.data.change_pct >= 0 ? "+" : ""}{quote.data.change_pct.toFixed(2)}% on the day
                                    </span>
                                  )}
                                  {quote.data.volume != null && <span className="text-slate-400"> · volume {quote.data.volume.toLocaleString("en-US")}</span>}
                                  <span className="text-slate-500"> · as of {quote.data.as_of} · Delayed data (Yahoo Finance)</span>
                                </p>
                                <PriceChart closes={quote.data.closes} />
                              </div>
                            ) : quote?.ticker === t && quote.error ? (
                              <p className="text-xs text-slate-500">{quote.error}</p>
                            ) : (
                              <p className="text-xs text-slate-500">Loading quote…</p>
                            )}
                            <div className="mt-2 text-xs text-slate-400">
                            {result.columns.filter((c) => c !== "ticker").map((c) => {
                              const prov = result.footer.columns?.[c];
                              return (
                                <span key={c} className="mr-4 inline-block">
                                  <span className="font-mono text-slate-300">{c}</span>: {prov?.source ?? "derived"}
                                  {prov?.as_of ? ` · as of ${prov.as_of}` : ""}
                                </span>
                              );
                            })}
                            </div>
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          {missingByTicker.length > 0 && (
            <div className="mt-2 text-xs text-slate-500">
              <p>
                Missing data (fails its filter, never zero): {missingByTicker.length} names ·{" "}
                {result.footer.missing?.length ?? 0} field gaps
              </p>
              <details className="mt-1">
                <summary className="cursor-pointer hover:text-slate-300">Per-ticker record</summary>
                <ul className="mt-1 space-y-0.5">
                  {missingByTicker.map(([t, fields]) => (
                    <li key={t}>
                      <span className="font-mono text-slate-400">{t}</span> — {fields.join(", ")}
                    </li>
                  ))}
                </ul>
              </details>
            </div>
          )}
        </section>
      )}


      <section aria-label="Universe" className="mt-6">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Universe</h2>
        <div className="mt-2 flex flex-wrap gap-2">
          {UNIVERSES.map((u) => (
            <button key={u.id} type="button" onClick={() => { setUniverseId(u.id); setCarried(null); }} aria-pressed={universeId === u.id}
              className={`rounded-xl border px-3.5 py-2 text-left ${universeId === u.id
                ? "border-emerald-400/70 bg-emerald-500/10" : "border-slate-700 bg-slate-900/60 hover:border-slate-500"}`}>
              <span className="block text-sm font-medium text-slate-100">{u.label}</span>
              <span className="block text-xs text-slate-500">{u.note}</span>
              {(() => {
                const r = catalog?.universe_refresh?.[u.id];
                return (
                  <span className="block text-xs text-slate-600">
                    {r ? `refreshed ${ctDateTimeYear(r.as_of)} · ${r.source} · ${r.count} names`
                        : "bundled proxy — not yet refreshed"}
                  </span>
                );
              })()}
            </button>
          ))}
          {universeId === "custom" && (
            <input aria-label="Custom tickers" value={customTickers} onChange={(e) => setCustomTickers(e.target.value)}
              placeholder="AAPL MSFT NVDA ..." className="min-w-56 flex-1 rounded-xl border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-sm text-white placeholder:text-slate-500" />
          )}
        </div>
        {carried && (
          <p className="mt-2 text-xs text-amber-200/90">
            Loaded universe: {universeWords(carried.universe)} — carried from the saved screen, so
            running or re-saving keeps it. Pick a universe above to replace it.
            {carried.limit == null
              ? " The saved screen has no result limit of its own, so a run returns its full cohort — the builder's show-top does not apply."
              : ` The saved screen's own result limit (${carried.limit}) applies to its runs.`}
          </p>
        )}
      </section>

      <section aria-label="Your screen" className="mt-6 rounded-2xl border border-slate-700/80 bg-slate-900/50 p-4">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-sm font-semibold text-slate-100">Your screen</h2>
          <input aria-label="Screen name" value={name} onChange={(e) => setName(e.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-white" />
          <label className="text-xs text-slate-400">show top
            <input aria-label="Result limit" type="number" min={1} max={100} value={limitN}
              onChange={(e) => setLimitN(Math.max(1, Number(e.target.value) || 1))}
              className="ml-1.5 w-16 rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-white" />
          </label>
          <span className="ml-auto flex gap-2">
            <button type="button" onClick={() => runSpec(spec)} disabled={!!busy || tray.length === 0}
              className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 font-medium text-slate-950 hover:bg-emerald-400 disabled:opacity-50">
              {busy === "run" && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Run the screen
            </button>
            <button type="button" onClick={save} disabled={!!busy || tray.length === 0}
              className="rounded-lg border border-slate-600 px-4 py-2 text-sm font-medium text-slate-200 hover:border-slate-400 disabled:opacity-50">
              Save screen
            </button>
          </span>
        </div>

        {tray.length === 0 && score.length === 0 && derived.length === 0 ? (
          <p className="mt-3 text-sm text-slate-500">
            No filters yet. Describe the screen above, start from a preset, or add cards from the library below.
          </p>
        ) : (
          <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {tray.map((t) => (
              <div key={t.key} className="rounded-xl border border-slate-700 bg-slate-950/60 px-3 py-2.5">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-medium text-slate-100">{t.label}</span>
                  <button type="button" aria-label={`Remove ${t.label}`}
                    onClick={() => setTray((prev) => prev.filter((x) => x.key !== t.key))}
                    className="text-slate-500 hover:text-rose-300"><X className="h-4 w-4" aria-hidden="true" /></button>
                </div>
                <div className="mt-1.5 flex items-center gap-1.5 text-sm">
                  <select aria-label={`${t.label} comparison`} value={t.op}
                    onChange={(e) => setTray((prev) => prev.map((x) => x.key === t.key ? { ...x, op: e.target.value } : x))}
                    className="rounded-md border border-slate-700 bg-slate-900 px-1.5 py-1 text-xs text-slate-200">
                    {(t.custom ? ["ge", "gt", "le", "lt", "pct_gte", "pct_lte"] : byCardId.get(t.key)?.ops ?? ["ge", "gt", "le", "lt"])
                      .map((op) => <option key={op} value={op}>{OP_LABELS[op] ?? op}</option>)}
                  </select>
                  <input aria-label={`${t.label} value`} type="number" value={t.value / t.divisor}
                    onChange={(e) => setTray((prev) => prev.map((x) => x.key === t.key
                      ? { ...x, value: (Number(e.target.value) || 0) * x.divisor } : x))}
                    className="w-24 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-xs text-white" />
                  <span className="text-xs text-slate-500">{t.unit}</span>
                </div>
                <p className="mt-1 text-[11px] text-slate-500">{t.source}</p>
              </div>
            ))}
            {derived.map((d) => (
              <div key={d.name} className="rounded-xl border border-violet-500/40 bg-violet-500/5 px-3 py-2.5">
                <div className="flex items-start justify-between gap-2">
                  <span className="font-mono text-sm text-violet-200">{d.name}</span>
                  <button type="button" aria-label={`Remove ${d.name}`}
                    onClick={() => setDerived((prev) => prev.filter((x) => x.name !== d.name))}
                    className="text-slate-500 hover:text-rose-300"><X className="h-4 w-4" aria-hidden="true" /></button>
                </div>
                <p className="mt-1 font-mono text-xs text-slate-400">= {d.expr}</p>
                <p className="mt-1 text-[11px] text-slate-500">derived ratio, composed from catalog fields</p>
              </div>
            ))}
            {score.map((s) => (
              <div key={s.fn} className="rounded-xl border border-emerald-500/30 bg-emerald-500/5 px-3 py-2.5">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-medium text-emerald-200">Rank by {s.label}</span>
                  <button type="button" aria-label={`Remove ranking by ${s.label}`}
                    onClick={() => setScore((prev) => prev.filter((x) => x.fn !== s.fn))}
                    className="text-slate-500 hover:text-rose-300"><X className="h-4 w-4" aria-hidden="true" /></button>
                </div>
                <div className="mt-1.5 flex items-center gap-1.5 text-xs text-slate-300">
                  <span>weight</span>
                  <input aria-label={`Weight for ${s.label}`} type="number" min={1} max={5} value={s.weight}
                    onChange={(e) => setScore((prev) => prev.map((x) => x.fn === s.fn
                      ? { ...x, weight: Math.max(1, Number(e.target.value) || 1) } : x))}
                    className="w-14 rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-white" />
                  <button type="button" onClick={() => setScore((prev) => prev.map((x) => x.fn === s.fn
                      ? { ...x, direction: x.direction === "high" ? "low" : "high" } : x))}
                    className="rounded-md border border-slate-700 px-2 py-1 hover:border-slate-500">
                    {s.direction === "high" ? "higher is better" : "lower is better"}
                  </button>
                </div>
                <p className="mt-1 text-[11px] text-slate-500">percentile blend; the top scores get the Best fit badge</p>
              </div>
            ))}
          </div>
        )}
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-300">
            The spec this composes (read-only, for the record)
          </summary>
          <pre className="mt-2 overflow-x-auto rounded-lg bg-slate-950 p-3 font-mono text-[11px] leading-relaxed text-slate-400">
            {JSON.stringify(spec, null, 2)}
          </pre>
        </details>
      </section>

      <section aria-label="Presets" className="mt-8">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Start from a preset</h2>
        <div className="mt-2 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          {PRESETS.map((p) => (
            <button key={p.id} type="button" onClick={() => applyPreset(p.id)}
              className="rounded-xl border border-slate-800 bg-slate-900/60 px-3.5 py-3 text-left hover:border-slate-500">
              <span className="flex items-center gap-2 text-sm font-medium text-slate-100">
                {p.name}
                <span className="rounded bg-slate-700/60 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-300">Preset</span>
              </span>
              <span className="mt-0.5 block text-xs leading-relaxed text-slate-400">{p.blurb}</span>
            </button>
          ))}
        </div>
      </section>

      <section aria-label="Filter library" className="mt-8">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Filter library -- pick cards, nudge numbers</h2>
        {/* The library lives behind dropdowns (Kevin, 2026-11-03): one closed
            row per group instead of 36 cards of scroll. */}
        {groups.map(([group, gcards]) => (
          <LibraryGroup key={group} group={group} count={gcards.length}>
            <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
              {gcards.map((c) => (
                <div key={c.id} className={`rounded-xl border px-3.5 py-3 ${inTray(c.id)
                  ? "border-emerald-500/50 bg-emerald-500/5" : "border-slate-800 bg-slate-900/60"}`}>
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-sm font-medium text-slate-100">{c.label}</span>
                    <button type="button" onClick={() => addCard(c)} disabled={inTray(c.id)}
                      className="inline-flex shrink-0 items-center gap-1 rounded-md border border-slate-600 px-2 py-1 text-xs text-slate-200 hover:border-emerald-400 hover:text-emerald-300 disabled:border-emerald-600/50 disabled:text-emerald-300">
                      {inTray(c.id) ? "Added" : <><Plus className="h-3 w-3" aria-hidden="true" /> Add</>}
                    </button>
                  </div>
                  <p className="mt-1 text-xs leading-relaxed text-slate-400">{c.blurb}</p>
                  <p className="mt-1.5 text-[11px] text-slate-500">
                    starts at {OP_LABELS[c.preset.op] ?? c.preset.op} {c.preset.value / c.divisor}{c.unit ? ` ${c.unit}` : ""} · {c.source}
                  </p>
                </div>
              ))}
            </div>
          </LibraryGroup>
        ))}

        <div className="mt-4 rounded-xl border border-violet-500/30 bg-slate-900/60 px-3.5 py-3">
          <h3 className="text-sm font-medium text-violet-200">Derived ratio -- compose a field from two others</h3>
          <p className="mt-1 text-xs text-slate-400">
            Name it, pick numerator and denominator; it becomes a column you can filter and rank on, and the formula is stored in the spec.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
            <input aria-label="Derived ratio name" value={dName} onChange={(e) => setDName(e.target.value)}
              placeholder="name (e.g. cash_per_debt)" className="rounded-lg border border-slate-700 bg-slate-900 px-2.5 py-1.5 font-mono text-xs text-white placeholder:text-slate-500" />
            <select aria-label="Derived numerator" value={dA} onChange={(e) => setDA(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-slate-200">
              <option value="">numerator field</option>
              {numericFields.map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
            </select>
            <span className="text-slate-500">/</span>
            <select aria-label="Derived denominator" value={dB} onChange={(e) => setDB(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-slate-200">
              <option value="">denominator field</option>
              {numericFields.map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
            </select>
            <button type="button" onClick={addDerived} disabled={!dName.trim() || !dA || !dB}
              className="rounded-lg border border-violet-500/50 px-3 py-1.5 text-xs text-violet-200 hover:border-violet-300 disabled:opacity-50">Add ratio</button>
          </div>
        </div>

        <div className="mt-4 rounded-xl border border-slate-800 bg-slate-900/60 px-3.5 py-3">
          <h3 className="text-sm font-medium text-slate-200">Ranking (optional)</h3>
          <p className="mt-1 text-xs text-slate-400">Add a score term; results carry a score column and the top 3 matches get the Best fit badge.</p>
          <div className="mt-2 flex items-center gap-2">
            <select aria-label="Score field" value={scorePick} onChange={(e) => setScorePick(e.target.value)}
              className="rounded-lg border border-slate-700 bg-slate-900 px-2 py-1.5 text-xs text-slate-200">
              <option value="">pick a card field</option>
              {cards.map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
            </select>
            <button type="button" onClick={addScore} disabled={!scorePick}
              className="rounded-lg border border-slate-600 px-3 py-1.5 text-xs text-slate-200 hover:border-slate-400 disabled:opacity-50">Add ranking</button>
          </div>
        </div>
      </section>

      <section aria-label="Saved screens" className="mt-8 rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Saved screens</h2>
        {screens?.length === 0 && <p className="mt-2 text-sm text-slate-500">None saved yet.</p>}
        <ul className="mt-2 space-y-2">
          {(screens ?? []).map((sc) => (
            <li key={sc.id} className="rounded-lg border border-slate-800 px-3 py-2.5 text-sm">
              <div className="flex items-baseline justify-between gap-2">
                <span className="flex items-center gap-2 font-medium text-slate-200">
                  {sc.name}
                  <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-emerald-300">Saved</span>
                </span>
                {sc.promoted_idea_id
                  ? <Link to={`/workshop/${sc.promoted_idea_id}`} className="text-xs text-emerald-300 hover:underline">tracked idea →</Link>
                  : <span className="text-xs text-slate-500">not promoted</span>}
              </div>
              <div className="mt-1 text-xs text-slate-500">
                {sc.last_run
                  ? `last run ${sc.last_run.run_at ? ctDateTimeYear(sc.last_run.run_at) : "—"}`
                    + ` · ${survivorText(sc.last_run.survivors ?? 0)}`
                    + (sc.last_run.survivor_issuers != null && sc.last_run.survivors != null
                        && sc.last_run.survivor_issuers !== sc.last_run.survivors
                        ? ` · ${sc.last_run.survivor_issuers} issuer${sc.last_run.survivor_issuers === 1 ? "" : "s"}` : "")
                    + (sc.last_run.data_as_of ? ` · data as of ${sc.last_run.data_as_of}` : "")
                    + (sc.last_run.column_sources && Object.keys(sc.last_run.column_sources).length
                        ? ` · sources: ${Object.entries(sc.last_run.column_sources)
                            .map(([c, s]) => `${c} (${s})`).join(", ")}`
                        : sc.last_run.sources?.length ? ` · sources: ${sc.last_run.sources.join(", ")}` : "")
                  : "not run yet"}
              </div>
              {sc.membership?.tracked_since && (
                <div className="mt-1 text-xs text-slate-500">
                  membership tracked since {fmtDay(sc.membership.tracked_since)}
                  {(!sc.membership_events || sc.membership_events.length === 0) && " · no entrances or exits yet"}
                </div>
              )}
              {(sc.membership_events ?? []).length > 0 && (
                <ul className="mt-1 space-y-0.5 text-xs">
                  {[...(sc.membership_events ?? [])].slice(-6).reverse().map((e, i) => (
                    <li key={`${e.ticker}-${e.date}-${e.kind}-${i}`}
                        className={e.kind === "entered" ? "text-emerald-300/90" : "text-rose-300/90"}>
                      <span className="font-mono font-medium">{e.tickers && e.tickers.length > 1 ? e.tickers.join(" + ") : e.ticker}</span>
                      {e.kind === "entered"
                        ? ` entered · ${fmtDay(e.date)}`
                        : ` exited · was member since ${fmtDay(e.since ?? e.date)}`}
                    </li>
                  ))}
                </ul>
              )}
              {(sc.last_run?.near_misses ?? []).length > 0 && (
                <div className="mt-1 text-xs text-slate-500">
                  Near misses — one filter away ({(sc.last_run?.near_miss_count ?? 0) > (sc.last_run?.near_misses?.length ?? 0)
                    ? `${sc.last_run?.near_misses?.length} closest of ${sc.last_run?.near_miss_count}`
                    : (sc.last_run?.near_miss_count ?? sc.last_run?.near_misses?.length)}):
                  <ul className="mt-0.5 space-y-0.5">
                    {(sc.last_run?.near_misses ?? []).slice(0, 6).map((n: NearMiss) => (
                      <li key={`${n.ticker}-${n.column}`}>
                        <span className="font-mono text-slate-300">{n.ticker}</span>
                        {" — "}{labelForFn.get(n.fn) ?? n.column} {fmtCell(n.value)}
                        {unitFor.get(n.fn) ? ` ${unitFor.get(n.fn)}` : ""} vs {cmpText(n.op, n.threshold)}
                      </li>
                    ))}
                  </ul>
                  {(sc.last_run?.near_misses?.length ?? 0) > 6 && (
                    <details>
                      <summary className="cursor-pointer hover:text-slate-300">
                        {(sc.last_run?.near_miss_count ?? 0) > (sc.last_run?.near_misses?.length ?? 0)
                          ? `all ${sc.last_run?.near_misses?.length} stored near misses`
                          : `all ${sc.last_run?.near_miss_count ?? sc.last_run?.near_misses?.length} near misses`}
                      </summary>
                      <ul className="mt-0.5 space-y-0.5">
                        {(sc.last_run?.near_misses ?? []).slice(6).map((n: NearMiss) => (
                          <li key={`${n.ticker}-${n.column}`}>
                            <span className="font-mono text-slate-300">{n.ticker}</span>
                            {" — "}{labelForFn.get(n.fn) ?? n.column} {fmtCell(n.value)}
                            {unitFor.get(n.fn) ? ` ${unitFor.get(n.fn)}` : ""} vs {cmpText(n.op, n.threshold)}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </div>
              )}
              <div className="mt-2 flex flex-wrap gap-2 text-xs">
                <button type="button" onClick={() => applySpec(sc.spec as ScreenSpec, `Loaded saved screen "${sc.name}" into the cards.`)}
                  className="rounded-md border border-slate-700 px-2 py-1 text-slate-300 hover:border-slate-500">Load into cards</button>
                <button type="button" onClick={() => runSaved(sc)} disabled={!!busy}
                  className="rounded-md border border-slate-700 px-2 py-1 text-slate-300 hover:border-slate-500 disabled:opacity-50">Re-run</button>
                {!sc.promoted_idea_id && sc.last_run && (
                  <button type="button" onClick={() => promote(sc)} disabled={!!busy}
                    className="rounded-md border border-emerald-600/60 px-2 py-1 text-emerald-300 hover:border-emerald-400 disabled:opacity-50">Promote to tracked idea</button>
                )}
                <button type="button" onClick={() => remove(sc)} disabled={!!busy}
                  className="rounded-md border border-slate-700 px-2 py-1 text-slate-400 hover:border-rose-400 hover:text-rose-300 disabled:opacity-50">Delete</button>
              </div>
            </li>
          ))}
        </ul>
        <details className="mt-4">
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-400">
            Full catalog ({catalog?.functions.length ?? 0} functions, reference)
            {catalog?.computed_at ? ` · computed ${catalog.computed_at.replace("T", " ").slice(0, 16)} UTC` : ""}
          </summary>
          <ul className="mt-3 space-y-2 text-sm">
            {(catalog?.functions ?? []).map((f) => (
              <li key={f.name} className="rounded-lg border border-slate-800 px-3 py-2">
                <span className="font-mono text-slate-200">{f.name}</span>
                <span className="text-slate-400"> — {f.doc}</span>
                <span className="block text-xs text-slate-500">{f.source}</span>
              </li>
            ))}
          </ul>
        </details>
      </section>

    </div>
  );
}
