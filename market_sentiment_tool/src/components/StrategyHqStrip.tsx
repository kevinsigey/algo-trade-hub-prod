import { Link } from "react-router-dom";

import { useHealth } from "@/hooks/useHealth";
import { useApi } from "@/hooks/usePaperPortfolio";
import { healthSummary } from "@/lib/health";
import { summarise, type ScoreboardResponse } from "@/lib/scoreboard";

export interface IdeasSummary {
  tested: number;
  passed: number;
  failed: number;
  not_enough_data: number;
  published: number;
}

const SUMMARY_COUNTS: (keyof IdeasSummary)[] = ["tested", "passed", "failed", "not_enough_data", "published"];
const SCOREBOARD_COUNTS = [
  "runs_read",
  "rows_total",
  "rows_behind_market",
  "rows_ahead_of_market",
  "rows_level_with_market",
  "rows_not_comparable",
  "engines",
] as const;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isIdeasSummary(value: unknown): value is IdeasSummary {
  return isRecord(value) && SUMMARY_COUNTS.every((key) => typeof value[key] === "number" && Number.isFinite(value[key]));
}

function isScoreboardResponse(value: unknown): value is ScoreboardResponse {
  return (
    isRecord(value) &&
    typeof value.headline === "string" &&
    typeof value.headline_kind === "string" &&
    Array.isArray(value.rows) &&
    SCOREBOARD_COUNTS.every((key) => typeof value[key] === "number" && Number.isFinite(value[key]))
  );
}

function CellLabel({ children }: { children: string }) {
  return <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{children}</div>;
}

/**
 * The Strategy HQ summary on the Portfolio page (phase-2 section 4.1).
 *
 * It is a pass-through, not a second record: idea counts come from /api/ideas/summary, the engine
 * headline and its qualifying counts come from /api/scoreboard's own summary, and Health's verdict
 * comes from the Health report. A failed or malformed read is shown as unavailable in its own cell;
 * it is never replaced with a zero, a healthy label, or a verdict composed here.
 */
export default function StrategyHqStrip() {
  const ideasRead = useApi<unknown>("/api/ideas/summary");
  const scoreboardRead = useApi<unknown>("/api/scoreboard");
  const { report: healthReport, error: healthError, loading: healthLoading } = useHealth();

  if (ideasRead.loading || scoreboardRead.loading || healthLoading) return null;

  const ideas = isIdeasSummary(ideasRead.data) ? ideasRead.data : null;
  const scoreboard = isScoreboardResponse(scoreboardRead.data) ? scoreboardRead.data : null;
  const scoreboardSummary = scoreboard ? summarise(scoreboard) : null;
  const health = healthReport ? healthSummary(healthReport) : null;
  const degraded = healthReport?.status === "degraded";

  return (
    <section
      aria-label="Strategy HQ summary"
      className={`mt-8 rounded-xl border p-4 md:p-5 ${degraded ? "border-amber-500/50 bg-amber-950/10" : "border-slate-800 bg-slate-900/40"}`}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold text-white">Strategy HQ</h2>
          <p className="mt-0.5 text-sm text-slate-400">Ideas, engines and system health, in one place.</p>
        </div>
        {health && (
          <span
            className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${
              degraded ? "border-amber-400/50 bg-amber-400/10 text-amber-300" : "border-emerald-400/40 bg-emerald-400/10 text-emerald-300"
            }`}
          >
            Health: {health.verdict}
          </span>
        )}
      </div>

      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <div className="rounded-lg border border-slate-800 bg-slate-950/40 px-4 py-3">
          <CellLabel>Ideas record</CellLabel>
          {ideas ? (
            <>
              <p className="mt-1.5 text-sm font-medium leading-6 text-slate-100">
                {ideas.tested} tested · {ideas.passed} passed · {ideas.failed} failed · {ideas.not_enough_data} not enough data
              </p>
              <p className="mt-1 text-sm text-slate-400">{ideas.published} published on the public record</p>
            </>
          ) : (
            <p className="mt-1.5 text-sm text-amber-300">Ideas summary unavailable</p>
          )}
          <Link to="/ideas" className="mt-3 inline-block text-sm text-emerald-300 hover:text-emerald-200">
            Open the Ideas record →
          </Link>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-950/40 px-4 py-3">
          <CellLabel>Engine scoreboard</CellLabel>
          {scoreboard && scoreboardSummary ? (
            <>
              <p className="mt-1.5 text-sm font-medium leading-6 text-slate-100">{scoreboardSummary.headline}</p>
              <p className="mt-1 text-xs leading-5 text-slate-400">{scoreboardSummary.counts}</p>
              {scoreboardSummary.caveat && <p className="mt-1 text-xs leading-5 text-amber-300">{scoreboardSummary.caveat}</p>}
              <p className="mt-1 text-xs text-slate-500">As of {scoreboard.as_of.slice(0, 10)}</p>
            </>
          ) : (
            <p className="mt-1.5 text-sm text-amber-300">Engine scoreboard unavailable</p>
          )}
          <Link to="/scoreboard" className="mt-3 inline-block text-sm text-emerald-300 hover:text-emerald-200">
            Open the scoreboard →
          </Link>
        </div>

        <div className={`rounded-lg border px-4 py-3 ${degraded ? "border-amber-500/40 bg-amber-950/30" : "border-slate-800 bg-slate-950/40"}`}>
          <CellLabel>System health</CellLabel>
          {health ? (
            <>
              <p className={`mt-1.5 text-xl font-semibold ${degraded ? "text-amber-300" : "text-emerald-300"}`}>{health.verdict}</p>
              <p className="mt-1 text-sm leading-6 text-slate-400">
                {health.okTimers} of {health.totalTimers} tracked timers fresh · {health.problemCount}{" "}
                {health.problemCount === 1 ? "problem" : "problems"} · {health.silentFamilies} silent{" "}
                {health.silentFamilies === 1 ? "family" : "families"}
              </p>
              {health.untrackedTimers > 0 && (
                <p className="mt-1 text-xs text-slate-500">{health.untrackedTimers} timers are not tracked</p>
              )}
            </>
          ) : (
            <>
              <p className="mt-1.5 text-sm font-medium text-amber-300">Health unavailable</p>
              {healthError && <p className="mt-1 text-xs leading-5 text-slate-500">{healthError}</p>}
            </>
          )}
          <Link to="/health" className="mt-3 inline-block text-sm text-emerald-300 hover:text-emerald-200">
            Open Health →
          </Link>
        </div>
      </div>
    </section>
  );
}
