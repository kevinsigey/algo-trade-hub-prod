import { useEffect, useState } from "react";
import { ChevronDown } from "lucide-react";

import { adminJson, adminText, type AgentDebateCard, type AgentDebateFeed } from "@/lib/workshop";
import MdDoc from "@/components/MdDoc";
import {
  extractSummary,
  formatPrice,
  hasText,
  parsePriceLevels,
  parseTraderAction,
  type PriceLevels,
  type TraderAction,
} from "@/lib/debateSummary";

/**
 * The TradingAgents debate cards + record line. Moved out of the Workshop page
 * (2026-11-02) when the debates got their own tab: a debate is an opinion panel
 * with a graded record, not a step in the idea pipeline, and the two sharing a
 * page invited exactly the confusion the chip exists to prevent.
 *
 * Summary pass (Kevin, 2026-11-02): the card opens with the verdict, a short
 * extracted summary, and a price ladder when the debate stated levels -- then
 * every section (bull, bear, the four analysts, trader, risk) sits in a
 * dropdown closed by default, one-line preview on the header, full text in a
 * scrollable region. Nothing is generated: the summary and the ladder are
 * extracted from the stored text only (lib/debateSummary), and a piece the
 * text does not state is simply not drawn. No strength score either: the
 * panels present the two cases, they do not measure them.
 */

function decisionClass(decision: string): string {
  const d = decision.toLowerCase();
  if (d.includes("buy") || d.includes("overweight")) return "border-emerald-400/50 bg-emerald-950/40 text-emerald-300";
  if (d.includes("sell") || d.includes("underweight")) return "border-rose-400/50 bg-rose-950/40 text-rose-300";
  return "border-slate-500/50 bg-slate-800/60 text-slate-200";
}

function gradeChip(label: string, g: AgentDebateCard["grades"][string]): { text: string; cls: string } {
  if (g === "pending") return { text: `${label} pending`, cls: "border-slate-700 text-slate-400" };
  const cls = g.outcome === "hit" ? "border-emerald-400/40 text-emerald-300" : g.outcome === "miss" ? "border-rose-400/40 text-rose-300" : "border-slate-600 text-slate-300";
  return { text: `${label} ${g.outcome} (${g.ret_pct >= 0 ? "+" : ""}${g.ret_pct.toFixed(1)}%)`, cls };
}

function actionChipClass(action: TraderAction): string {
  if (action === "BUY") return "border-emerald-400/50 bg-emerald-950/40 text-emerald-300";
  if (action === "SELL") return "border-rose-400/50 bg-rose-950/40 text-rose-300";
  return "border-slate-500/50 bg-slate-800/60 text-slate-200";
}

/**
 * The stated levels as a horizontal ladder: stop, entry, target(s) placed by
 * value on one track. Drawn only when the text stated at least two of them --
 * an unstated level is never invented to complete the picture.
 */
function PriceLadder({ levels, anchorPrice }: { levels: PriceLevels; anchorPrice?: number | null }) {
  const points: { label: string; value: number; dot: string; text: string }[] = [];
  if (levels.stop !== null) points.push({ label: "Stop", value: levels.stop, dot: "bg-rose-400", text: "text-rose-300" });
  if (levels.entry !== null) points.push({ label: "Entry", value: levels.entry, dot: "bg-sky-400", text: "text-sky-300" });
  levels.targets.forEach((t, i) =>
    points.push({ label: levels.targets.length > 1 ? `Target ${i + 1}` : "Target", value: t, dot: "bg-emerald-400", text: "text-emerald-300" }));
  if (points.length < 2) return null;
  // The price the stock actually traded at when debated, drawn on the same
  // track: a ladder floating far from it exposes itself at a glance.
  if (anchorPrice !== null && anchorPrice !== undefined) {
    points.push({ label: "Traded", value: anchorPrice, dot: "bg-white", text: "text-slate-100" });
  }
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const pad = (max - min) * 0.1 || max * 0.02 || 1;
  const lo = min - pad;
  const span = max + pad - lo;
  return (
    <figure className="mt-3 rounded-lg border border-slate-800 bg-slate-950/40 px-3 pb-2 pt-3" aria-label="Price levels stated in the debate">
      <figcaption className="text-[11px] font-bold uppercase tracking-wider text-slate-500">Stated levels</figcaption>
      <div className="relative mx-10 mb-1 mt-5 h-6">
        <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-slate-700" />
        {points.map((p) => {
          const pos = ((p.value - lo) / span) * 100;
          return (
            <div key={p.label} className="absolute top-1/2" style={{ left: `${pos}%`, transform: `translate(-${pos}%, -50%)` }}>
              <span className={`absolute bottom-full left-1/2 mb-1 -translate-x-1/2 whitespace-nowrap text-[11px] font-semibold ${p.text}`}>
                {p.label} {formatPrice(p.value)}
              </span>
              <span className={`block h-2.5 w-2.5 rounded-full ${p.dot}`} />
            </div>
          );
        })}
      </div>
    </figure>
  );
}

const SECTION_ACCENTS: Record<string, { box: string; title: string }> = {
  bull: { box: "border-emerald-900/60", title: "text-emerald-300" },
  bear: { box: "border-rose-900/60", title: "text-rose-300" },
  plain: { box: "border-slate-800", title: "text-slate-300" },
};

const ANALYST_SECTIONS: [string, string][] = [
  ["fundamentals", "Fundamentals"],
  ["news", "News"],
  ["sentiment", "Sentiment"],
  ["technicals", "Technicals"],
];

export function DebateCard({ card }: { card: AgentDebateCard }) {
  const [report, setReport] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [caseOpen, setCaseOpen] = useState(false);
  const toggleCase = () => {
    const opening = !caseOpen;
    setCaseOpen(opening);
    if (opening && card.has_report && report === null && !busy) {
      setBusy(true);
      adminText(`/api/agent-debates/${card.run_id}/report`)
        .then(setReport)
        .catch(() => setReport("The report could not be loaded."))
        .finally(() => setBusy(false));
    }
  };
  // A failed run is a compact line, never a full card (Kevin, 2026-11-02):
  // eight "not recorded" panels and a raw report dump bury the record. The
  // reason is the whole content; grades and cases do not exist for it.
  if (card.status !== "complete") {
    return (
      <li>
        <article className="flex flex-wrap items-baseline gap-x-3 gap-y-1 rounded-xl border border-rose-900/50 bg-rose-950/10 px-4 py-2.5">
          <span className="text-base font-bold tracking-tight text-white">{card.ticker}</span>
          <span className="rounded-full border border-rose-400/40 px-2 py-0.5 text-xs font-semibold text-rose-300">failed</span>
          <span className="min-w-0 flex-1 text-xs leading-relaxed text-slate-300">{card.error ?? card.status}</span>
          <span className="text-xs text-slate-500">Run {card.run_at_ct.replace("T", " ").slice(0, 16)} CT · as of {card.as_of_date}</span>
        </article>
      </li>
    );
  }
  const g5 = gradeChip("+5d", card.grades["+5d"]);
  const g20 = gradeChip("+20d", card.grades["+20d"]);
  const action = parseTraderAction(card.trader_rationale);
  const summary = extractSummary(card.risk_verdict, card.trader_rationale);
  const levels = parsePriceLevels(card.trader_rationale, card.risk_verdict);
  const sections: { key: string; title: string; text: string; accent: "bull" | "bear" | "plain" }[] = [
    { key: "bull", title: "Bull case", text: card.bull_case, accent: "bull" as const },
    { key: "bear", title: "Bear case", text: card.bear_case, accent: "bear" as const },
    ...ANALYST_SECTIONS.map(([k, label]) => ({
      key: k,
      title: label,
      text: card.analyst_summaries[k] ?? "",
      accent: "plain" as const,
    })),
    { key: "trader", title: "Trader", text: card.trader_rationale, accent: "plain" as const },
    { key: "risk", title: "Risk panel", text: card.risk_verdict, accent: "plain" as const },
  ].filter((s) => hasText(s.text));
  return (
    <li>
      <article className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
        {/* The verdict first: ticker, the decision as the headline, status flags, grades. */}
        <div className="flex flex-wrap items-center gap-3">
          <span className="text-xl font-bold tracking-tight text-white">{card.ticker}</span>
          <span className={`rounded-lg border px-3 py-1 text-base font-extrabold ${decisionClass(card.decision)}`}>{card.decision}</span>
          <span className="rounded-full border border-violet-400/40 px-2 py-0.5 text-xs font-semibold text-violet-300">{card.chip}</span>
          {action && <span className={`rounded-full border px-2 py-0.5 text-xs font-bold ${actionChipClass(action)}`}>Trader: {action}</span>}
          {card.stale && <span className="text-xs font-semibold text-amber-300">stale</span>}
          {card.historical_label && <span className="text-xs text-slate-400">{card.historical_label}</span>}
          {card.status !== "complete" && <span className="text-xs font-semibold text-rose-300">{card.status}{card.error ? `: ${card.error}` : ""}</span>}
          <span className="ml-auto flex flex-wrap gap-1.5">
            <span className={`rounded-full border px-2 py-0.5 font-mono text-xs ${g5.cls}`}>{g5.text}</span>
            <span className={`rounded-full border px-2 py-0.5 font-mono text-xs ${g20.cls}`}>{g20.text}</span>
          </span>
        </div>

        {/* The summary: extracted from the risk panel / trader text, never written for it. */}
        {summary && <p className="mt-3 text-sm leading-relaxed text-slate-200">{summary}</p>}

        {/* The stated levels, when the debate stated enough of them to draw. */}
        <PriceLadder levels={levels} anchorPrice={card.market_anchor?.price ?? null} />

        {/* The grounding line (Kevin, 2026-11-03): what the stock actually
            traded at when debated, and now -- with a warning when the stated
            levels sit far from that traded price. */}
        {card.market_anchor && (
          <p className="mt-2 text-xs text-slate-400">
            Traded at <span className="font-semibold text-slate-200">{formatPrice(card.market_anchor.price)}</span> when debated
            {card.live && <> · now <span className="font-semibold text-slate-200">{formatPrice(card.live.price)}</span></>}
            {[levels.entry, levels.stop, ...levels.targets].some(
              (v) => v !== null && Math.abs(v / card.market_anchor!.price - 1) > 0.15,
            ) && (
              <span className="ml-2 rounded bg-amber-500/15 px-1.5 py-0.5 font-semibold text-amber-300">
                Stated levels sit far from the traded price — treat them as unreliable
              </span>
            )}
          </p>
        )}

        {/* The full case, on click only (Kevin, 2026-11-03): the list card
            above is the whole summary -- rating, fence, trader action, the
            +5d/+20d state, the action text, the stated levels. The cases
            and the framework report open here, rendered as documents. */}
        {caseOpen && (
          <div className="mt-3 space-y-2">
            {sections.map((sec) => (
              <div key={sec.key} className={`rounded-lg border ${SECTION_ACCENTS[sec.accent].box} bg-slate-950/30 px-3 py-2.5`}>
                <div className={`text-xs font-bold uppercase tracking-wider ${SECTION_ACCENTS[sec.accent].title}`}>{sec.title}</div>
                <div className="mt-1.5"><MdDoc markdown={sec.text} /></div>
              </div>
            ))}
            {busy && <p className="text-xs text-slate-500">Loading the framework report…</p>}
            {report !== null && (
              <div className="rounded-lg border border-slate-800 bg-slate-950/30 px-3 py-2.5">
                <div className="text-xs font-bold uppercase tracking-wider text-slate-300">Framework report</div>
                <div className="mt-1.5"><MdDoc markdown={report} /></div>
              </div>
            )}
          </div>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
          <span>
            Run {card.run_at_ct.replace("T", " ").slice(0, 16)} CT · as of {card.as_of_date} · framework {card.framework_short} · {card.llm_model} · cost {typeof card.cost_usd === "number" ? `$${card.cost_usd.toFixed(2)}` : card.cost_usd}
          </span>
          <span>Inputs: {card.inputs_note}</span>
          <button type="button" aria-expanded={caseOpen} onClick={toggleCase}
                  className="inline-flex items-center gap-1 text-slate-300 underline decoration-dotted underline-offset-4 hover:text-white">
            {caseOpen ? "Hide the full case" : "Read the full case"}
            <ChevronDown className={`h-3.5 w-3.5 transition-transform ${caseOpen ? "rotate-180" : ""}`} aria-hidden="true" />
          </button>
        </div>
      </article>
    </li>
  );
}

export function DebateFeed({ refreshKey = 0 }: { refreshKey?: number }) {
  const [feed, setFeed] = useState<AgentDebateFeed | null>(null);
  useEffect(() => {
    adminJson<AgentDebateFeed>("/api/agent-debates").then(setFeed).catch(() => setFeed(null));
  }, [refreshKey]);
  if (!feed) return <p className="mt-3 text-sm text-slate-400">Loading the debate record…</p>;
  if (!feed.cards?.length) return <p className="mt-3 text-sm text-slate-400">No debates yet. Run the first one above.</p>;
  const { h5, h20 } = feed.record;
  const rate = (r: { graded: number; hit_rate: number | null }) =>
    r.graded === 0 || r.hit_rate === null ? "no graded runs yet" : `${(r.hit_rate * 100).toFixed(0)}% hits`;
  return (
    <section className="mt-10">
      <h2 className="text-lg font-semibold text-white">The record</h2>
      <p className="mt-1 text-xs text-slate-400">Debate record (kept separate from every model statistic):</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
          <div className="font-display text-3xl leading-none text-white tabular-nums">{rate(h5)}</div>
          <div className="mt-1 text-xs text-slate-400">+5d · {h5.graded} graded · {h5.no_calls} no-calls</div>
        </div>
        <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-3">
          <div className="font-display text-3xl leading-none text-white tabular-nums">{rate(h20)}</div>
          <div className="mt-1 text-xs text-slate-400">+20d · {h20.graded} graded · {h20.no_calls} no-calls</div>
        </div>
      </div>
      {feed.banner && <p className="mt-3 rounded-lg border border-amber-400/40 px-3 py-2 text-sm font-semibold text-amber-300">{feed.banner}</p>}
      <ul className="mt-4 space-y-4">
        {feed.cards.map((c) => <DebateCard key={c.run_id} card={c} />)}
      </ul>
    </section>
  );
}
