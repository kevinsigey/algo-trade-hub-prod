import { Fragment, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowDown, ArrowUp, Loader2, Trophy } from "lucide-react";

import { adminJson, type ScreenRow } from "@/lib/workshop";
import type { Catalog, RunPayload, ScreenSpec } from "@/lib/screening";

const EXAMPLES: Record<string, ScreenSpec> = {
  "finviz_value_clean": {
    "context": [
      {
        "fn": "fred_latest",
        "params": {
          "series_id": "DGS10"
        }
      },
      {
        "fn": "fred_latest",
        "params": {
          "series_id": "UNRATE"
        }
      }
    ],
    "description": "The house Finviz value screen, CLEANED version (audit of Nov 1, 2026): the reel's four legs (P/S < 2, LT debt/equity < 0.5, net margin > 0, P/B < 5) with the sign bug fixed (0 < P/B, so negative-equity names are excluded) plus the audit's listed + tradable legs (major exchange, price >= $3, market cap >= $25M, 3m avg volume >= 25k). Run here on a large-cap liquid universe, where few names are expected to pass \u2014 the original screen's habitat was small caps.",
    "filters": [
      {
        "fn": "price_to_sales",
        "op": "lt",
        "value": 2
      },
      {
        "fn": "lt_debt_to_equity",
        "op": "lt",
        "value": 0.5
      },
      {
        "fn": "net_margin",
        "op": "gt",
        "value": 0
      },
      {
        "fn": "price_to_book",
        "op": "gt",
        "value": 0
      },
      {
        "fn": "price_to_book",
        "op": "lt",
        "value": 5
      },
      {
        "fn": "is_major_exchange",
        "op": "eq",
        "value": 1
      },
      {
        "fn": "price",
        "op": "ge",
        "value": 3
      },
      {
        "fn": "market_cap",
        "op": "ge",
        "value": 25000000
      },
      {
        "fn": "avg_volume_3m",
        "op": "ge",
        "value": 25000
      }
    ],
    "name": "finviz_value_clean",
    "sort": {
      "ascending": false,
      "by": "market_cap"
    },
    "universe": {
      "tickers": [
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "GOOGL",
        "META",
        "AVGO",
        "TSLA",
        "JPM",
        "XOM",
        "CVX",
        "UNH",
        "LLY",
        "HD",
        "COST",
        "WMT",
        "PG",
        "JNJ",
        "MA",
        "V",
        "NFLX",
        "CRM",
        "ORCL",
        "AMD",
        "QCOM",
        "CSCO",
        "ABBV",
        "MRK",
        "PEP",
        "KO",
        "MCD",
        "NKE",
        "DIS",
        "CAT",
        "GE",
        "CRWV",
        "PLTR",
        "HOOD",
        "MSTR",
        "SOFI",
        "INTC",
        "MU",
        "AMGN",
        "BKNG"
      ],
      "type": "list"
    }
  },
  "funding_flag_fcc": {
    "description": "Funding-flag screen in the spirit of the house Funded Conversion Coverage (book-to-bill study, Oct 2026: FCC = guided next-12m revenue / (capex guide + debt due <=12m + interest run-rate); CRWV 0.27x vs ORCL 1.6x, MSFT 2.9x; checklist convention: FCC < 0.5x = funding flag). APPROXIMATION: guidance is not in any free source, so fcc_proxy uses TTM actuals (revenue / (capex + current debt + interest expense)) from statements. It preserves the order-of-magnitude gap the metric exists to catch; it is not the guide-based FCC.",
    "filters": [
      {
        "fn": "fcc_proxy",
        "op": "lt",
        "value": 0.5
      }
    ],
    "name": "funding_flag_fcc",
    "score": [
      {
        "direction": "low",
        "fn": "fcc_proxy",
        "weight": 1
      },
      {
        "direction": "high",
        "fn": "capex_intensity",
        "weight": 1
      }
    ],
    "sort": {
      "ascending": true,
      "by": "fcc_proxy"
    },
    "universe": {
      "tickers": [
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "GOOGL",
        "META",
        "AVGO",
        "TSLA",
        "JPM",
        "XOM",
        "CVX",
        "UNH",
        "LLY",
        "HD",
        "COST",
        "WMT",
        "PG",
        "JNJ",
        "MA",
        "V",
        "NFLX",
        "CRM",
        "ORCL",
        "AMD",
        "QCOM",
        "CSCO",
        "ABBV",
        "MRK",
        "PEP",
        "KO",
        "MCD",
        "NKE",
        "DIS",
        "CAT",
        "GE",
        "CRWV",
        "PLTR",
        "HOOD",
        "MSTR",
        "SOFI",
        "INTC",
        "MU",
        "AMGN",
        "BKNG"
      ],
      "type": "list"
    }
  },
  "momentum_quality": {
    "context": [
      {
        "fn": "fred_latest",
        "params": {
          "series_id": "T10Y2Y"
        }
      }
    ],
    "description": "Momentum + quality: top-quartile 6-month momentum, positive year-over-year earnings growth, and leverage at or below the universe median; scored on momentum (2x), revenue growth (1x), and FCF yield (1x) percentile blends.",
    "filters": [
      {
        "fn": "momentum",
        "op": "pct_gte",
        "params": {
          "months": 6
        },
        "value": 75
      },
      {
        "fn": "earnings_growth_yoy",
        "op": "gt",
        "value": 0
      },
      {
        "fn": "debt_to_equity",
        "op": "pct_lte",
        "value": 50
      }
    ],
    "limit": 10,
    "name": "momentum_quality",
    "score": [
      {
        "direction": "high",
        "fn": "momentum",
        "params": {
          "months": 6
        },
        "weight": 2
      },
      {
        "direction": "high",
        "fn": "revenue_growth_yoy",
        "weight": 1
      },
      {
        "direction": "high",
        "fn": "fcf_yield",
        "weight": 1
      }
    ],
    "sort": {
      "ascending": false,
      "by": "score"
    },
    "universe": {
      "tickers": [
        "AAPL",
        "MSFT",
        "NVDA",
        "AMZN",
        "GOOGL",
        "META",
        "AVGO",
        "TSLA",
        "JPM",
        "XOM",
        "CVX",
        "UNH",
        "LLY",
        "HD",
        "COST",
        "WMT",
        "PG",
        "JNJ",
        "MA",
        "V",
        "NFLX",
        "CRM",
        "ORCL",
        "AMD",
        "QCOM",
        "CSCO",
        "ABBV",
        "MRK",
        "PEP",
        "KO",
        "MCD",
        "NKE",
        "DIS",
        "CAT",
        "GE",
        "CRWV",
        "PLTR",
        "HOOD",
        "MSTR",
        "SOFI",
        "INTC",
        "MU",
        "AMGN",
        "BKNG"
      ],
      "type": "list"
    }
  }
};

function fmtCell(v: unknown): string {
  if (v == null) return "—";
  if (typeof v === "number") return Math.abs(v) >= 1000 ? v.toLocaleString("en-US", { maximumFractionDigits: 0 })
    : v.toLocaleString("en-US", { maximumFractionDigits: 3 });
  return String(v);
}

/** Screening (Part A3): plain English -> a visible, editable spec -> run ->
 * sortable results with per-value provenance. Missing data fails a filter and
 * renders as a dash, never a zero. A saved screen promotes once into a
 * tracked Workshop basket idea. */
export default function Screening() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [query, setQuery] = useState("");
  const [specText, setSpecText] = useState(() => JSON.stringify(EXAMPLES.momentum_quality, null, 2));
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [result, setResult] = useState<RunPayload | null>(null);
  const [sort, setSort] = useState<{ col: string; dir: 1 | -1 } | null>(null);
  const [openRow, setOpenRow] = useState<string | null>(null);
  const [screens, setScreens] = useState<ScreenRow[] | null>(null);
  const [saveName, setSaveName] = useState("");

  const loadScreens = () => adminJson<ScreenRow[]>("/api/screening/screens").then(setScreens).catch(() => setScreens([]));
  useEffect(() => {
    adminJson<Catalog>("/api/screening/catalog").then(setCatalog).catch(() => setCatalog(null));
    loadScreens();
  }, []);

  const spec = useMemo<ScreenSpec | null>(() => {
    try { return JSON.parse(specText) as ScreenSpec; } catch { return null; }
  }, [specText]);
  const specError = specText.trim() && !spec ? "The spec is not valid JSON yet." : null;

  const byName = useMemo(() => new Map((catalog?.functions ?? []).map((f) => [f.name, f])), [catalog]);
  const filters = (spec?.filters as { fn: string; op: string; value?: unknown; params?: unknown }[] | undefined) ?? [];
  const derived = (spec?.derived as { name: string; expr: string }[] | undefined) ?? [];

  const act = async (label: string, fn: () => Promise<void>) => {
    setBusy(label); setError(null); setNotice(null);
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : "Something failed"); }
    setBusy("");
  };

  const translate = () => act("translate", async () => {
    const d = await adminJson<{ spec: ScreenSpec; model: string }>("/api/screening/translate",
      { method: "POST", body: JSON.stringify({ query }) });
    setSpecText(JSON.stringify(d.spec, null, 2));
    setResult(null);
    setNotice(`Translated by ${d.model} -- review the spec, then run it.`);
  });

  const runSpec = (sp: ScreenSpec) => act("run", async () => {
    const d = await adminJson<RunPayload>("/api/screening/run", { method: "POST", body: JSON.stringify({ spec: sp }) });
    setResult(d); setSort(null); setOpenRow(null);
  });

  const runSaved = (sc: ScreenRow) => act("run", async () => {
    const d = await adminJson<RunPayload>(`/api/screening/screens/${sc.id}/run`, { method: "POST", body: "{}" });
    setSpecText(JSON.stringify(sc.spec, null, 2));
    setResult(d); setSort(null); setOpenRow(null);
    loadScreens();
  });

  const save = () => act("save", async () => {
    if (!spec) return;
    const last = result ? { footer: result.footer, columns: result.columns,
                            survivors: result.rows.map((r) => String(r.ticker)) } : undefined;
    await adminJson("/api/screening/screens", { method: "POST",
      body: JSON.stringify({ spec, name: saveName || String(spec.name ?? "Untitled screen"), last_run: last }) });
    setSaveName("");
    loadScreens();
    setNotice("Screen saved.");
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

  return (
    <div className="mx-auto max-w-6xl px-4 py-8 md:px-8">
      <h1 className="text-2xl font-bold tracking-tight text-white">Screening</h1>
      <p className="mt-1 text-sm text-slate-400">
        Describe a screen, check the spec it becomes, run it. Every value carries its source; missing data fails a filter, never reads as zero.
      </p>

      <div className="mt-6 flex gap-2">
        <textarea aria-label="Describe the screen in plain English" value={query} onChange={(e) => setQuery(e.target.value)}
          rows={2} placeholder="S&P 500 stocks with top-quartile 6-month momentum, positive earnings growth, and low debt"
          className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-white placeholder:text-slate-500 focus:border-emerald-400 focus:outline-none" />
        <button type="button" onClick={translate} disabled={!!busy || query.trim().length < 3}
          className="inline-flex shrink-0 items-center gap-2 self-start rounded-lg bg-emerald-500 px-4 py-2 font-medium text-slate-950 hover:bg-emerald-400 disabled:opacity-50">
          {busy === "translate" && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Translate
        </button>
      </div>
      {error && <p role="alert" className="mt-3 text-sm text-rose-300">{error}</p>}
      {notice && <p className="mt-3 text-sm text-emerald-300">{notice}</p>}

      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs">
        <span className="text-slate-500">Starters:</span>
        {Object.entries(EXAMPLES).map(([name, sp]) => (
          <button key={name} type="button" onClick={() => { setSpecText(JSON.stringify(sp, null, 2)); setResult(null); }}
            className="rounded-full border border-slate-700 px-2.5 py-1 text-slate-300 hover:border-slate-500">{name}</button>
        ))}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_360px]">
        <div>
          <label htmlFor="spec" className="text-sm font-medium text-slate-300">The spec (editable JSON)</label>
          <textarea id="spec" value={specText} onChange={(e) => setSpecText(e.target.value)} rows={14} spellCheck={false}
            className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 font-mono text-xs leading-relaxed text-slate-200 focus:border-emerald-400 focus:outline-none" />
          {specError && <p className="mt-2 text-sm text-rose-300">{specError}</p>}
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" onClick={() => spec && runSpec(spec)} disabled={!!busy || !spec}
              className="inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 font-medium text-slate-950 hover:bg-emerald-400 disabled:opacity-50">
              {busy === "run" && <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" />} Run the screen
            </button>
            <input aria-label="Name for the saved screen" value={saveName} onChange={(e) => setSaveName(e.target.value)}
              placeholder={String(spec?.name ?? "Screen name")} className="rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-white placeholder:text-slate-500" />
            <button type="button" onClick={save} disabled={!!busy || !spec}
              className="rounded-lg border border-slate-600 px-4 py-2 text-sm font-medium text-slate-200 hover:border-slate-400 disabled:opacity-50">
              Save screen
            </button>
          </div>
        </div>

        <div className="space-y-4">
          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">What it asks, in order</h2>
            {filters.length === 0 && derived.length === 0 && <p className="mt-2 text-sm text-slate-500">No filters in this spec.</p>}
            <ul className="mt-2 space-y-2">
              {filters.map((f, i) => (
                <li key={i} className="rounded-lg border border-slate-800 px-3 py-2 text-sm">
                  <span className="font-mono text-slate-200">{f.fn}</span>{" "}
                  <span className="text-slate-400">{f.op} {f.value != null ? String(f.value) : ""}</span>
                  <span className="block text-xs text-slate-500">{byName.get(f.fn)?.source ?? "derived / catalog"}</span>
                </li>
              ))}
              {derived.map((d) => (
                <li key={d.name} className="rounded-lg border border-violet-500/30 px-3 py-2 text-sm">
                  <span className="font-mono text-violet-200">{d.name}</span>{" "}
                  <span className="font-mono text-slate-400">= {d.expr}</span>
                  <span className="block text-xs text-slate-500">derived ratio, composed from catalog fields</span>
                </li>
              ))}
            </ul>
          </section>

          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Saved screens</h2>
            {screens?.length === 0 && <p className="mt-2 text-sm text-slate-500">None saved yet.</p>}
            <ul className="mt-2 space-y-2">
              {(screens ?? []).map((sc) => (
                <li key={sc.id} className="rounded-lg border border-slate-800 px-3 py-2.5 text-sm">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-medium text-slate-200">{sc.name}</span>
                    {sc.promoted_idea_id
                      ? <Link to={`/workshop/${sc.promoted_idea_id}`} className="text-xs text-emerald-300 hover:underline">tracked idea →</Link>
                      : <span className="text-xs text-slate-500">not promoted</span>}
                  </div>
                  <div className="mt-1 text-xs text-slate-500">
                    {sc.last_run ? `last run ${sc.last_run.run_at?.slice(0, 10) ?? ""} · ${sc.last_run.survivors ?? 0} survivors` : "not run yet"}
                  </div>
                  <div className="mt-2 flex flex-wrap gap-2 text-xs">
                    <button type="button" onClick={() => setSpecText(JSON.stringify(sc.spec, null, 2))}
                      className="rounded-md border border-slate-700 px-2 py-1 text-slate-300 hover:border-slate-500">Load</button>
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
          </section>

          <details className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-400">
              Catalog ({catalog?.functions.length ?? 0} functions)
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
        </div>
      </div>

      {result && (
        <section className="mt-8">
          <p className="text-sm text-slate-400">
            <span className="font-medium text-slate-200">{result.footer.spec_name ?? "screen"}</span>
            {" "}· ran {result.footer.run_at?.replace("T", " ").slice(0, 16)} UTC · universe {result.footer.universe_size ?? "?"}
            {" "}· <span className="text-slate-200">{result.footer.survivors ?? result.rows.length} survivors</span>
            {result.footer.universe_capped && (
              <span className="text-amber-300"> · enrichment capped at {result.footer.universe_capped.cap} of {result.footer.universe_capped.universe_size_full} names</span>
            )}
            {" "}· click a column to sort, a row for its provenance
          </p>
          <div className="mt-3 overflow-x-auto rounded-xl border border-slate-800">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
                  {result.columns.map((c) => (
                    <th key={c} className="px-3 py-2">
                      <button type="button" onClick={() => toggleSort(c)} className="inline-flex items-center gap-1 hover:text-slate-200">
                        {c}
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
                              <span className="flex items-center gap-2 font-mono font-medium text-white">
                                {t}
                                {fit && <span className="inline-flex items-center gap-1 rounded-full border border-emerald-500/40 bg-emerald-500/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-300">
                                  <Trophy className="h-3 w-3" aria-hidden="true" /> Best fit</span>}
                              </span>
                            ) : fmtCell(r[c])}
                          </td>
                        ))}
                      </tr>
                      {openRow === t && (
                        <tr key={`${t}-prov`} className="border-b border-slate-800 bg-slate-950/60">
                          <td colSpan={result.columns.length} className="px-3 py-2 text-xs text-slate-400">
                            {result.columns.filter((c) => c !== "ticker").map((c) => {
                              const prov = result.footer.columns?.[c];
                              return (
                                <span key={c} className="mr-4 inline-block">
                                  <span className="font-mono text-slate-300">{c}</span>: {prov?.source ?? "derived"}
                                  {prov?.as_of ? ` · as of ${prov.as_of}` : ""}
                                </span>
                              );
                            })}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
              </tbody>
            </table>
          </div>
          {result.footer.missing && result.footer.missing.length > 0 && (
            <p className="mt-2 text-xs text-slate-500">
              Missing data (fails its filter, never zero): {result.footer.missing.map((m) => m.field).join(", ")}
            </p>
          )}
        </section>
      )}
    </div>
  );
}
