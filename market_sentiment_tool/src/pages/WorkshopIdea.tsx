import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, Loader2 } from "lucide-react";
import { Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { PaperLine } from "@/pages/Ideas";
import { toneClass } from "@/pages/Workshop";
import {
  ApiError,
  CLAIM_OPTIONS,
  adminJson,
  claimLabel,
  conditionText,
  verdictTone,
  type Claim,
  type Condition,
  type GateResult,
  type IdeaDetail,
  type IdeaSpec,
  type Run,
} from "@/lib/workshop";

const field = "mt-1 w-full rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1.5 text-sm text-white focus:border-emerald-400 focus:outline-none";
const DEFAULT_CONDITION: Condition = { source: "fred", series: "DGS10", measure: "change", lookback_days: 63, op: ">", threshold: 0.25 };
const pct = (v: number | null | undefined, digits = 1) => (v == null ? "—" : `${v >= 0 ? "+" : "−"}${Math.abs(v).toFixed(digits)}%`);

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-xs text-slate-400">
      {label}
      {children}
    </label>
  );
}

/** The draft, as a form. Nothing runs until Kevin presses Run it. */
export function DraftEditor({ initial, onRun, busy, note }: { initial: IdeaSpec; onRun: (s: IdeaSpec) => void; busy: boolean; note?: string }) {
  const [spec, setSpec] = useState<IdeaSpec>(initial);
  const set = <K extends keyof IdeaSpec>(key: K, value: IdeaSpec[K]) => setSpec((s) => ({ ...s, [key]: value }));
  const setWhen = <K extends keyof Condition>(key: K, value: Condition[K]) =>
    setSpec((s) => ({ ...s, when: { ...(s.when ?? DEFAULT_CONDITION), [key]: value } }));

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
          <input className={field} value={spec.hold.join(", ")} onChange={(e) => set("hold", e.target.value.split(",").map((t) => t.trim()).filter(Boolean))} />
        </Field>
        <Field label="Otherwise hold (ticker or CASH)">
          <input className={field} value={spec.otherwise} onChange={(e) => set("otherwise", e.target.value)} />
        </Field>
      </div>

      <label className="mt-4 flex items-center gap-2 text-sm text-slate-300">
        <input type="checkbox" checked={spec.when !== null} onChange={(e) => set("when", e.target.checked ? spec.when ?? DEFAULT_CONDITION : null)} />
        Only while a condition holds
      </label>
      {spec.when && (
        <div className="mt-3 grid gap-3 sm:grid-cols-6">
          <Field label="Source">
            <select className={field} value={spec.when.source} onChange={(e) => setWhen("source", e.target.value as Condition["source"])}>
              <option value="fred">FRED series</option>
              <option value="price">Price</option>
            </select>
          </Field>
          <Field label="Series / ticker">
            <input className={field} value={spec.when.series} onChange={(e) => setWhen("series", e.target.value)} />
          </Field>
          <Field label="Measure">
            <select className={field} value={spec.when.measure} onChange={(e) => setWhen("measure", e.target.value as Condition["measure"])}>
              <option value="level">level</option>
              <option value="change">change</option>
              <option value="pct_change">% change</option>
            </select>
          </Field>
          <Field label="Over (trading days)">
            <input type="number" className={field} value={spec.when.lookback_days} onChange={(e) => setWhen("lookback_days", Number(e.target.value))} />
          </Field>
          <Field label="Is">
            <select className={field} value={spec.when.op} onChange={(e) => setWhen("op", e.target.value as Condition["op"])}>
              <option value=">">above</option>
              <option value="<">below</option>
            </select>
          </Field>
          <Field label="Threshold">
            <input type="number" step="any" className={field} value={spec.when.threshold} onChange={(e) => setWhen("threshold", Number(e.target.value))} />
          </Field>
        </div>
      )}

      <div className="mt-4 grid gap-4 sm:grid-cols-4">
        <Field label="Compared with">
          <input className={field} value={spec.benchmark} onChange={(e) => set("benchmark", e.target.value)} />
        </Field>
        <Field label="Cost per switch (bps)">
          <input type="number" className={field} value={spec.cost_bps} onChange={(e) => set("cost_bps", Number(e.target.value))} />
        </Field>
        <Field label="Data from">
          <input type="date" className={field} value={spec.start} onChange={(e) => set("start", e.target.value)} />
        </Field>
        <Field label="Unseen share (most recent)">
          <input type="number" step="0.05" min="0.1" max="0.5" className={field} value={spec.unseen_fraction} onChange={(e) => set("unseen_fraction", Number(e.target.value))} />
        </Field>
      </div>

      <Field label="Assumptions (one per line; edit any you disagree with)">
        <textarea rows={3} className={field} value={spec.assumptions.join("\n")} onChange={(e) => set("assumptions", e.target.value.split("\n").filter((l) => l.trim()))} />
      </Field>

      <button
        type="button"
        onClick={() => onRun(spec)}
        disabled={busy}
        className="mt-4 inline-flex items-center gap-2 rounded-lg bg-emerald-500 px-4 py-2 font-medium text-slate-950 hover:bg-emerald-400 disabled:opacity-50"
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

export function VerdictCard({ run, onVary }: { run: Run; onVary: (s: IdeaSpec) => void }) {
  const r = run.result;
  const tone = verdictTone(run.verdict);
  return (
    <article className="mt-6 rounded-xl border border-slate-800 p-5">
      <div className="flex flex-wrap items-center gap-4">
        <div className={`rounded-lg border-2 px-4 py-1 text-2xl font-extrabold ${toneClass[tone]}`}>{run.verdict}</div>
        <div className="min-w-0">
          <div className="text-lg font-semibold text-white">{r.headline}</div>
          <div className="text-xs text-slate-400">
            Variation {run.variation} · {run.spec.hold.join(", ")} {conditionText(run.spec.when) === "always" ? "always" : `while ${conditionText(run.spec.when)}`} · {claimLabel(run.spec.claim)}
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

      {r.claim && r.shuffle && (
        <table className="mt-4 w-full text-sm">
          <tbody className="divide-y divide-slate-800/80">
            <tr><td className="py-1.5 text-slate-300">On the years it was built on</td><td className="py-1.5 text-slate-400">{r.claim.built.label}</td><td><Mark ok={r.claim.built.holds} /></td></tr>
            <tr><td className="py-1.5 text-slate-300">On the years it hadn't seen</td><td className="py-1.5 text-slate-400">{r.claim.unseen.label}</td><td><Mark ok={r.claim.unseen.holds} /></td></tr>
            <tr><td className="py-1.5 text-slate-300">Better than chance ({r.shuffle.method})</td><td className="py-1.5 text-slate-400">beats {r.shuffle.beats_pct.toFixed(0)}% of {r.shuffle.permutations.toLocaleString()} · p = {r.shuffle.p.toFixed(3)}, needs &lt; {r.shuffle.bar.toFixed(4).replace(/0+$/, "")}</td><td><Mark ok={r.shuffle.p < r.shuffle.bar} /></td></tr>
            {r.t_test && <tr><td className="py-1.5 text-slate-300">t-test, daily difference</td><td className="py-1.5 text-slate-400">{pct(r.t_test.mean_daily_diff, 3)}/day · p = {r.t_test.p.toFixed(3)}</td><td><Mark ok={r.t_test.p < 0.05 ? r.t_test.mean_daily_diff > 0 : null} /></td></tr>}
            {r.periods && <tr><td className="py-1.5 text-slate-300">Holds in each market period</td><td className="py-1.5 text-slate-400">{r.periods.held} of {r.periods.of}</td><td><Mark ok={r.periods.held >= 4 ? true : r.periods.held <= 1 ? false : null} /></td></tr>}
            <tr><td className="py-1.5 text-slate-300">Variations tried on this idea</td><td className="py-1.5 text-slate-400">{r.variations} · bar raised accordingly</td><td /></tr>
          </tbody>
        </table>
      )}

      {r.context.length > 0 && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[28rem] text-xs tabular-nums">
            <thead className="text-left text-slate-400">
              <tr><th className="py-1 font-medium">Per year</th><th className="py-1 text-right font-medium">Built years</th><th className="py-1 text-right font-medium">Unseen years</th><th className="py-1 text-right font-medium">Unseen worst drop</th></tr>
            </thead>
            <tbody>
              {r.context.map((c) => (
                <tr key={c.name} className="border-t border-slate-800/80">
                  <td className={`py-1 ${c.name === "Idea" ? "font-semibold text-amber-300" : "text-slate-300"}`}>{c.name}</td>
                  <td className="py-1 text-right text-slate-300">{pct(c.built_cagr)}</td>
                  <td className="py-1 text-right text-slate-300">{pct(c.unseen_cagr)}</td>
                  <td className="py-1 text-right text-slate-300">{pct(c.unseen_max_dd, 0)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

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
  const kill = () => {
    if (!window.confirm("Kill this idea? Its paper record stops today and stays on the record.")) return;
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
              className="rounded-lg bg-emerald-500 px-3 py-1.5 text-sm font-medium text-slate-950 hover:bg-emerald-400 disabled:opacity-50">
              Go live on paper
            </button>
          </div>
          {gate && (
            <ul className="mt-2 space-y-1 text-sm">
              {gate.claim && <li className={gate.claim.holds ? "text-emerald-300" : "text-rose-300"}>New data: {gate.claim.label}</li>}
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
  const [draft, setDraft] = useState<{ spec: IdeaSpec; model: string | null; note?: string } | null>(null);
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

  useEffect(() => {
    if (!data || params.get("draft") !== "1" || draft || drafting) return;
    setDrafting(true);
    adminJson<{ spec: IdeaSpec; model: string }>("/api/workshop/draft", { method: "POST", body: JSON.stringify({ text: data.idea.plain_words }) })
      .then((d) => setDraft({ spec: d.spec, model: d.model }))
      .catch((e: unknown) => {
        const template = e instanceof ApiError ? (e.body?.template as IdeaSpec | undefined) : undefined;
        if (template) setDraft({ spec: { ...template, title: data.idea.title.slice(0, 120) }, model: null, note: "The AI couldn't draft this — fill it in." });
        else setError(e instanceof Error ? e.message : "Draft failed");
      })
      .finally(() => {
        setDrafting(false);
        setParams({}, { replace: true });
      });
  }, [data, params, draft, drafting, setParams]);

  const run = async (spec: IdeaSpec) => {
    if (id === null) return;
    setRunning(true);
    setError(null);
    try {
      await adminJson<Run>(`/api/workshop/ideas/${id}/runs`, { method: "POST", body: JSON.stringify({ spec, draft_model: draft?.model ?? null }) });
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
      {draft && <DraftEditor key={JSON.stringify(draft.spec)} initial={draft.spec} onRun={run} busy={running} note={draft.note} />}
      {data && data.runs.length === 0 && !draft && !drafting && (
        <button type="button" onClick={() => setParams({ draft: "1" })} className="mt-6 rounded-lg border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-900">
          Draft the test
        </button>
      )}
      {data && [...data.runs].reverse().map((r) => (
        <VerdictCard key={r.id} run={r} onVary={(spec) => { setDraft({ spec, model: null }); window.scrollTo({ top: 0, behavior: "smooth" }); }} />
      ))}
    </div>
  );
}
