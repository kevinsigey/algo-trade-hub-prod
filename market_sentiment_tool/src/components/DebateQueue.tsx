import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { adminJson } from "@/lib/workshop";
import { ctDateTime } from "@/lib/format";
import type { DebateQueuePayload } from "@/lib/decisions";

/**
 * The debate queue in aggregate (Loop Round 4, Item 2). Candidates used
 * to be visible only per-name inside decision views; the "Agent debates"
 * nav destination serves the separate TradingAgents feed, not this
 * queue. The panel lives here because the queue is generated from this
 * page's guidance snapshot and its verdicts render into this page's
 * decision views. It serves the persisted, stamped generation (snapshot
 * id + computed-at, generation time) -- never a live recompute -- and
 * names every exclusion with its reason. Additive display: if the
 * endpoint is unavailable the page renders without it.
 */

const CLASS_LABELS: Record<string, string> = {
  conjunction: "conjunction",
  entrant: "entrant",
  zone: "zone",
};

export default function DebateQueue() {
  const [payload, setPayload] = useState<DebateQueuePayload | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    adminJson<DebateQueuePayload>("/api/debate-candidates")
      .then((p) => { if (live) setPayload(p); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, []);

  if (failed) return null;
  if (!payload) {
    return (
      <section data-testid="debate-queue" aria-label="Debate queue" className="mt-10">
        <p className="inline-flex items-center gap-2 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading debate queue…
        </p>
      </section>
    );
  }

  const snap = payload.snapshot;
  const pending = (payload.candidates ?? []).filter((r) => r.state === "pending");
  const settled = (payload.candidates ?? []).length - pending.length;
  const byClass = payload.pending_by_class ?? { conjunction: 0, entrant: 0, zone: 0 };
  const pendingTotal = byClass.conjunction + byClass.entrant + byClass.zone;
  const excluded = payload.excluded ?? [];

  return (
    <section data-testid="debate-queue" aria-label="Debate queue" className="mt-10">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold text-white">Debate queue</h2>
        {snap && (
          <span className="rounded-full bg-slate-500/20 px-2.5 py-0.5 text-xs font-medium text-slate-300">
            snapshot #{snap.id}
            {snap.computed_at ? ` · computed ${ctDateTime(snap.computed_at)}` : ""}
            {payload.generated_at ? ` · queue generated ${ctDateTime(payload.generated_at)}` : ""}
          </span>
        )}
      </div>
      <p className="mt-0.5 max-w-3xl text-sm text-slate-400">
        Names the nightly generation queues for an agent debate — screen survivors and
        entrants meeting a directional band zone, conjunctions first. The drain renders
        up to the shared daily budget; a name that cannot debate is named below with
        its reason, never silently dropped.
      </p>

      {!snap || pending.length === 0 ? (
        <p className="mt-3 text-sm text-slate-400">
          The debate queue is empty for this snapshot — no pending candidates.
        </p>
      ) : (
        <>
          <p className="mt-3 text-sm text-slate-300">
            {pendingTotal} pending — {byClass.conjunction} conjunction
            {byClass.conjunction === 1 ? "" : "s"} · {byClass.entrant} entrant
            {byClass.entrant === 1 ? "" : "s"} · {byClass.zone} zone
            {settled > 0 && (
              <span className="text-slate-500"> · {settled} already rendered or settled</span>
            )}
          </p>
          <ul className="mt-2 divide-y divide-slate-800 rounded-xl border border-slate-800">
            {pending.map((r) => {
              const held = r.sources?.held;
              return (
                <li key={r.ticker} className="flex flex-wrap items-baseline gap-x-3 px-3 py-2 text-sm">
                  <span className="font-mono font-medium text-white">{r.ticker}</span>
                  <span className="text-slate-400">
                    {CLASS_LABELS[r.candidate_class] ?? r.candidate_class}
                    {r.sources?.zone ? ` · ${r.sources.zone}` : ""}
                  </span>
                  {held && (
                    <span className="rounded bg-amber-500/15 px-1.5 py-0.5 text-xs font-medium text-amber-300">
                      held{(held.sleeves ?? []).length ? ` · ${held.sleeves!.join(", ")}` : ""}
                    </span>
                  )}
                  <span className="ml-auto text-xs text-slate-500">priority {r.priority}</span>
                </li>
              );
            })}
          </ul>
        </>
      )}

      {excluded.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs font-semibold uppercase tracking-wide text-slate-400 hover:text-slate-200">
            {excluded.length} named exclusion{excluded.length === 1 ? "" : "s"} — considered, not queued
          </summary>
          <ul className="mt-2 space-y-0.5 text-xs">
            {excluded.map((e) => (
              <li key={e.ticker}>
                <span className="font-mono text-slate-300">{e.ticker}</span>
                <span className="text-slate-500"> — {e.reason ?? "no reason recorded"}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
