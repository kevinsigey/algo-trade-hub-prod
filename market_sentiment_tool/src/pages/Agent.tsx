import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Bot, ChevronDown } from "lucide-react";

import {
  createAgentSpec,
  interpretText,
  listAgentSpecs,
  patchAgentSpec,
  runAgentGate,
  setAgentState,
  type AgentSpecRow,
  type AgentState,
  type StrategySpec,
} from "@/lib/agent";

/**
 * The in-site agent, phases 1-2 (Kevin, 2026-11-03).
 *
 * Phase 1: paste strategy text; the interpreter returns a validated
 * StrategySpec plus the questions it would not guess at; Kevin confirms or
 * edits, and the spec is saved as a draft. Phase 2: the accuracy gate runs
 * an expressible spec through the Workshop's verdict machinery; states move
 * draft -> shadow -> paper-eligible one step at a time, each promotion
 * Kevin's and gated on a PASS; a failed gate or Kevin's no blocks it.
 * Nothing here stages an order -- the compiler is phase 3.
 */

const STATE_STYLES: Record<AgentState, string> = {
  draft: "border-slate-500/50 text-slate-300",
  shadow: "border-sky-400/50 text-sky-300",
  "paper-eligible": "border-emerald-400/50 text-emerald-300",
  blocked: "border-rose-400/50 text-rose-300",
};

function Drop({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/30">
      <button type="button" aria-expanded={open} onClick={() => setOpen((v) => !v)}
              className="flex w-full items-center gap-2 px-3 py-2 text-left">
        <span className="text-xs font-bold uppercase tracking-wider text-slate-300">{title}</span>
        <ChevronDown className={`ml-auto h-4 w-4 shrink-0 text-slate-500 transition-transform ${open ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {open && <div className="px-3 pb-3">{children}</div>}
    </div>
  );
}

function SpecSummary({ spec }: { spec: StrategySpec }) {
  const bits: [string, string][] = [
    ["Universe", spec.universe?.join(", ") || "—"],
    ["Entry", `${spec.entry?.rule ?? "—"}${spec.entry?.band_pct ? ` · band ${spec.entry.band_pct}%` : ""}`],
    ["Sizing", `${spec.sizing?.value ?? "—"}% of equity · cap ${spec.sizing?.per_name_cap_pct ?? 25}%/name`],
    ["Stops", spec.stops?.kind === "none" ? "none" : `${spec.stops?.kind} ${spec.stops?.value ?? ""}`.trim()],
    ["Exits", [
      spec.exits?.take_profit_pct ? `take profit ${spec.exits.take_profit_pct}%` : null,
      spec.exits?.time_stop_days ? `time stop ${spec.exits.time_stop_days}d` : null,
    ].filter(Boolean).join(" · ") || "—"],
    ["Horizon", spec.horizon?.terminal_date ?? "open"],
    ["Benchmark", spec.scoring?.benchmark ?? "SPY"],
  ];
  return (
    <div>
      <p className="text-sm leading-relaxed text-slate-200">{spec.thesis}</p>
      <dl className="mt-3 grid gap-x-6 gap-y-1.5 sm:grid-cols-2">
        {bits.map(([k, v]) => (
          <div key={k} className="flex gap-2 text-[13px]">
            <dt className="w-20 shrink-0 font-semibold uppercase tracking-wide text-slate-500">{k}</dt>
            <dd className="text-slate-200">{v}</dd>
          </div>
        ))}
      </dl>
      {(spec.catalysts?.length || spec.invalidation?.length) ? (
        <div className="mt-2 space-y-1 text-[13px] text-slate-400">
          {spec.catalysts?.length ? <div>Catalysts: {spec.catalysts.join(" · ")}</div> : null}
          {spec.invalidation?.length ? <div>Invalidation: {spec.invalidation.join(" · ")}</div> : null}
        </div>
      ) : null}
    </div>
  );
}

function SpecEditor({ initial, onSave, saveLabel }: {
  initial: StrategySpec;
  onSave: (spec: StrategySpec) => Promise<void>;
  saveLabel: string;
}) {
  const [text, setText] = useState(() => JSON.stringify(initial, null, 2));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    let parsed: StrategySpec;
    try {
      parsed = JSON.parse(text) as StrategySpec;
    } catch {
      setError("That is not valid JSON.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onSave(parsed);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The save failed.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <textarea aria-label="The spec (editable JSON)" value={text} onChange={(e) => setText(e.target.value)} rows={14}
                className="w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 font-mono text-xs text-slate-100" />
      {error && <p className="mt-1 text-xs text-rose-300">{error}</p>}
      <button type="button" onClick={save} disabled={busy}
              className="mt-2 rounded-lg border border-slate-600 px-3 py-1.5 text-xs font-semibold text-slate-100 hover:border-slate-400 disabled:opacity-50">
        {busy ? "Saving…" : saveLabel}
      </button>
    </div>
  );
}

function SpecCard({ row, onChange }: { row: AgentSpecRow; onChange: (row: AgentSpecRow) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const gate = row.gate;
  const passed = gate?.verdict === "PASS";

  const act = async (label: string, fn: () => Promise<AgentSpecRow>) => {
    setBusy(label);
    setError(null);
    try {
      onChange(await fn());
    } catch (e) {
      setError(e instanceof Error ? e.message : "That failed.");
    } finally {
      setBusy(null);
    }
  };

  const btn = "rounded-lg border border-slate-600 px-3 py-1.5 text-xs font-semibold text-slate-100 hover:border-slate-400 disabled:opacity-50";
  return (
    <article className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex flex-wrap items-center gap-2.5">
        <h3 className="text-base font-semibold text-white">{row.title}</h3>
        <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${STATE_STYLES[row.state]}`}>{row.state}</span>
        {gate && (gate.expressible
          ? <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${passed ? "border-emerald-400/50 text-emerald-300" : "border-amber-400/50 text-amber-300"}`}>gate: {gate.verdict ?? "run"}</span>
          : <span className="rounded-full border border-slate-600 px-2 py-0.5 text-xs font-semibold text-slate-400">research-only</span>)}
      </div>

      <div className="mt-3">
        <SpecSummary spec={row.spec} />
      </div>

      {row.questions.length > 0 && (
        <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2">
          <div className="text-xs font-bold uppercase tracking-wider text-amber-300">Open questions from the interpreter</div>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[13px] text-amber-100/90">
            {row.questions.map((q) => <li key={q}>{q}</li>)}
          </ul>
        </div>
      )}

      {gate && (
        <p className="mt-3 text-[13px] text-slate-400">
          {gate.expressible ? (
            <>
              <span className="font-semibold text-slate-200">{gate.headline ?? gate.verdict}</span>
              {gate.split_date && <> · unseen split {gate.split_date}</>}
              {typeof gate.shuffle_p === "number" && <> · shuffle p {gate.shuffle_p.toFixed(3)}</>}
              {gate.data_start && <> · {gate.data_start} → {gate.data_end}</>}
            </>
          ) : (
            <>{gate.note}</>
          )}
        </p>
      )}
      {error && <p className="mt-2 text-xs text-rose-300">{error}</p>}

      <div className="mt-3 flex flex-wrap gap-2">
        {(row.state === "draft" || row.state === "blocked") && (
          <button type="button" className={btn} disabled={busy !== null}
                  onClick={() => act("gate", () => runAgentGate(row.id))}>
            {busy === "gate" ? "Running the gate…" : gate ? "Re-run the accuracy gate" : "Run the accuracy gate"}
          </button>
        )}
        {row.state === "draft" && passed && (
          <button type="button" className={btn} disabled={busy !== null}
                  onClick={() => act("shadow", () => setAgentState(row.id, "shadow"))}>
            Move to shadow
          </button>
        )}
        {row.state === "shadow" && passed && (
          <button type="button" className={btn} disabled={busy !== null}
                  onClick={() => act("paper", () => setAgentState(row.id, "paper-eligible"))}>
            Approve as paper-eligible
          </button>
        )}
        {row.state === "blocked" && (
          <button type="button" className={btn} disabled={busy !== null}
                  onClick={() => act("draft", () => setAgentState(row.id, "draft"))}>
            Back to draft
          </button>
        )}
        {row.state !== "blocked" && (
          <button type="button" className={btn} disabled={busy !== null}
                  onClick={() => act("block", () => setAgentState(row.id, "blocked"))}>
            Block
          </button>
        )}
      </div>

      <div className="mt-3 space-y-1.5">
        <Drop title="The spec (JSON)">
          <SpecEditor key={row.updated_at} initial={row.spec} saveLabel="Save edits (returns the spec to draft)"
                      onSave={async (spec) => { onChange(await patchAgentSpec(row.id, { spec })); }} />
        </Drop>
        {gate?.expressible && (
          <Drop title="Gate detail">
            <div className="space-y-1 text-[13px] text-slate-300">
              <div>Verdict: <span className="font-semibold text-white">{gate.verdict}</span></div>
              {gate.reason && <div>Reason: {gate.reason}</div>}
              <div>Claim on unseen years: {gate.claim_holds_unseen === null || gate.claim_holds_unseen === undefined ? "—" : gate.claim_holds_unseen ? "holds" : "does not hold"}</div>
              {gate.note && <div className="text-slate-400">{gate.note}</div>}
              {(gate.notes ?? []).map((n) => <div key={n} className="text-slate-400">{n}</div>)}
            </div>
          </Drop>
        )}
      </div>
    </article>
  );
}

export default function Agent() {
  const [rows, setRows] = useState<AgentSpecRow[] | null>(null);
  const [text, setText] = useState("");
  const [draft, setDraft] = useState<{ spec: StrategySpec; questions: string[]; model: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    listAgentSpecs().then((d) => setRows(d.specs)).catch(() => setRows([]));
  }, []);
  useEffect(load, [load]);

  const replace = (row: AgentSpecRow) =>
    setRows((cur) => (cur ?? []).map((r) => (r.id === row.id ? row : r)));

  const interpret = async () => {
    setBusy(true);
    setError(null);
    try {
      setDraft(await interpretText(text));
    } catch (e) {
      setError(e instanceof Error ? e.message : "The interpreter is unavailable.");
    } finally {
      setBusy(false);
    }
  };

  const confirmDraft = async (spec: StrategySpec) => {
    const row = await createAgentSpec(spec, draft?.questions ?? []);
    setRows((cur) => [row, ...(cur ?? [])]);
    setDraft(null);
    setText("");
  };

  return (
    <div className="mx-auto max-w-5xl space-y-6 p-6 md:p-8">
      <header>
        <h1 className="flex items-center gap-2.5 text-3xl font-bold text-white">
          <Bot className="h-7 w-7 text-slate-300" aria-hidden="true" /> Strategy agent
        </h1>
        <p className="mt-2 text-slate-400">
          Paste a strategy; the interpreter turns it into a spec you confirm, and the accuracy
          gate judges it like a Workshop idea. States move draft → shadow → paper-eligible,
          one step at a time. Nothing here stages an order — that is phase 3.
        </p>
      </header>

      <section aria-label="New strategy" className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        <h2 className="text-base font-semibold text-white">New strategy</h2>
        <textarea aria-label="Strategy text" value={text} onChange={(e) => setText(e.target.value)} rows={6}
                  placeholder="A memo, a thesis, a playbook entry — in your words. Ambiguities come back as questions, never guesses."
                  className="mt-3 w-full rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500" />
        {error && <p className="mt-2 text-sm text-rose-300">{error}</p>}
        <button type="button" onClick={interpret} disabled={busy || text.trim().length < 20}
                className="mt-3 rounded-lg border border-slate-500 px-4 py-2 text-sm font-semibold text-white hover:border-slate-300 disabled:opacity-50">
          {busy ? "Interpreting…" : "Interpret"}
        </button>

        {draft && (
          <div className="mt-4 border-t border-slate-800 pt-4">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold text-white">The spec it read</h3>
              <span className="text-xs text-slate-500">via {draft.model} — confirm it, or edit the JSON first</span>
            </div>
            <div className="mt-3">
              <SpecSummary spec={draft.spec} />
            </div>
            {draft.questions.length > 0 && (
              <div className="mt-3 rounded-lg border border-amber-500/30 bg-amber-500/5 px-3 py-2">
                <div className="text-xs font-bold uppercase tracking-wider text-amber-300">Questions, not guesses</div>
                <ul className="mt-1 list-disc space-y-0.5 pl-4 text-[13px] text-amber-100/90">
                  {draft.questions.map((q) => <li key={q}>{q}</li>)}
                </ul>
              </div>
            )}
            <div className="mt-3 space-y-1.5">
              <Drop title="Edit the spec (JSON)">
                <SpecEditor key={JSON.stringify(draft.spec)} initial={draft.spec} saveLabel="Use the edited spec"
                            onSave={async (spec) => { setDraft({ ...draft, spec }); }} />
              </Drop>
            </div>
            <button type="button" onClick={() => confirmDraft(draft.spec)}
                    className="mt-3 rounded-lg border border-emerald-500/60 px-4 py-2 text-sm font-semibold text-emerald-200 hover:border-emerald-300">
              Confirm — save as a draft
            </button>
          </div>
        )}
      </section>

      <section aria-label="Specs">
        <h2 className="text-lg font-semibold text-white">Specs</h2>
        {rows === null && <p className="mt-2 text-sm text-slate-400">Loading…</p>}
        {rows !== null && rows.length === 0 && (
          <p className="mt-2 text-sm text-slate-400">No specs yet. Interpret a strategy above and confirm it.</p>
        )}
        <div className="mt-3 space-y-4">
          {(rows ?? []).map((row) => <SpecCard key={row.id} row={row} onChange={replace} />)}
        </div>
      </section>
    </div>
  );
}
