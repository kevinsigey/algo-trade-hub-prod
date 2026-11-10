import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { adminJson } from "@/lib/workshop";
import { ctDateTimeYear } from "@/lib/format";
import { priceText, zoneInfo } from "@/lib/valuation";
import { chipHeadline, chipJudgeText, type NameDecision as Decision } from "@/lib/decisions";

/**
 * The per-name decision view (Batch 2, charter workstream 5): ONE surface
 * per name answering — what we know (the fact sheet), what the systems
 * say (recorded screens, zone, crossings, print classification), the
 * judgment (debate verdict + the band falsifier's standing), and what is
 * missing (named gaps). It renders inside the name's expansion on the
 * Guidance page, beside the fact sheet it summarizes; Screening rows
 * deep-link here via ?decision=TICKER. Display only.
 */

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</h4>
      <div className="mt-1.5 space-y-1 text-sm text-slate-300">{children}</div>
    </div>
  );
}

export default function NameDecision({ ticker }: { ticker: string }) {
  const [view, setView] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    setView(null); setError(null);
    adminJson<Decision>(`/api/name-decision/${encodeURIComponent(ticker)}`)
      .then((v) => {
        if (!v || !v.systems || !v.judgment) throw new Error("malformed decision payload");
        if (live) setView(v);
      })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : "The decision view could not be loaded"); });
    return () => { live = false; };
  }, [ticker]);

  if (error) {
    return <p data-testid={`decision-${ticker}`} className="text-sm text-rose-300">{error}</p>;
  }
  if (!view) {
    return (
      <p data-testid={`decision-${ticker}`} className="inline-flex items-center gap-2 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading the decision view…
      </p>
    );
  }
  const { know, systems, judgment } = view;
  const zone = zoneInfo(systems.zone);
  return (
    <div data-testid={`decision-${ticker}`} className="mt-4 border-t border-slate-800 pt-4">
      <h3 className="text-sm font-semibold text-white">
        Decision view — {ticker}
        {view.snapshot && (
          <span className="ml-2 text-xs font-normal text-slate-500">
            against snapshot #{view.snapshot.id}
            {view.snapshot.computed_at ? ` · computed ${ctDateTimeYear(view.snapshot.computed_at)}` : ""}
          </span>
        )}
      </h3>
      <div className="mt-3 grid gap-4 md:grid-cols-2">
        <Block title="What we know">
          {know ? (
            <>
              <p>
                {know.status === "banded" ? "Banded fact sheet" : `Fact sheet — ${know.status}`}
                {" · "}price {priceText(know.price)}
                {know.price_as_of ? ` as of ${know.price_as_of}` : ""}
                {know.bands && ` · bands ${priceText(know.bands.bear)} / ${priceText(know.bands.base)} / ${priceText(know.bands.bull)}`}
              </p>
              {know.peer.group && (
                <p className="text-slate-400">
                  Peer group {know.peer.group} · multiple {know.peer.multiple ?? "—"}× · {know.peer.count ?? "—"} peers
                </p>
              )}
              {know.stale && <p className="text-amber-300">This sheet is stale — the zone is held.</p>}
            </>
          ) : (
            <p className="text-slate-400">No guidance fact sheet on record for this name.</p>
          )}
        </Block>
        <Block title="What the systems say">
          <p>Zone: {systems.zone ? zone.label : "—"}</p>
          {systems.screens.length > 0 ? (
            <p>
              Screens: {systems.screens.map((s) => s.member_since
                ? `${s.screen_name} (member since ${s.member_since})`
                : `${s.screen_name} (survived its last recorded run)`).join("; ")}
            </p>
          ) : (
            <p className="text-slate-400">Screens: no recorded screen membership.</p>
          )}
          <p>
            Print classification: {systems.print_classification
              ? `${systems.print_classification.classification}${systems.print_classification.as_of ? ` (as of ${systems.print_classification.as_of})` : ""}`
              : "none on record"}
          </p>
          <p className="text-slate-400">
            Crossings on record: {systems.crossings.length}
            {systems.crossings.length > 0 && systems.crossings[0]
              ? ` · latest ${systems.crossings[0].action} (${systems.crossings[0].book}, ${ctDateTimeYear(systems.crossings[0].created_at)})`
              : ""}
          </p>
        </Block>
        <Block title="The judgment">
          {judgment.verdict ? (
            <>
              <p className="font-medium text-violet-300">{chipHeadline(judgment.verdict)}</p>
              {judgment.verdict.dissent && <p>Dissent: {judgment.verdict.dissent}</p>}
              <p className="text-xs text-slate-500">
                {chipJudgeText(judgment.verdict)} · rendered {ctDateTimeYear(judgment.verdict.rendered_at)}
                {judgment.verdict.snapshot_id != null ? ` · exhibit snapshot #${judgment.verdict.snapshot_id}` : ""}
              </p>
            </>
          ) : judgment.candidate ? (
            <p className="text-slate-400">
              No verdict yet — debate candidate queued ({judgment.candidate.candidate_class},
              {" "}{judgment.candidate.state}).
            </p>
          ) : (
            <p className="text-slate-400">No verdict yet — not currently a debate candidate.</p>
          )}
          {judgment.falsifier && (
            <p className="text-xs leading-relaxed text-slate-400">
              Falsifier ({judgment.falsifier_source}): {judgment.falsifier}
              {" · "}crossings graded for this name: {judgment.crossings_graded}
              {judgment.crossings_mean_score != null ? ` (mean score ${judgment.crossings_mean_score})` : ""}
            </p>
          )}
        </Block>
        <Block title="What is missing">
          {view.missing.length > 0 ? (
            <ul className="list-disc space-y-0.5 pl-4">
              {view.missing.map((m, i) => <li key={i}>{m}</li>)}
            </ul>
          ) : (
            <p className="text-slate-400">Nothing named — sheet, systems, and judgment are all on record.</p>
          )}
        </Block>
      </div>
    </div>
  );
}
