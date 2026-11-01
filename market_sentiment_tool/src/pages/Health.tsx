import { Fragment, useEffect, useState } from "react";
import { Activity, AlertTriangle, Loader2 } from "lucide-react";

import { useHealth } from "@/hooks/useHealth";
import { adminJson } from "@/lib/workshop";
import { ct } from "@/lib/paperPortfolio";
import {
  HEALTH_INTRO,
  familyRows,
  formatAge,
  healthSummary,
  statusChip,
  timerRows,
  type Chip as ChipTone,
} from "@/lib/health";

const toneClass: Record<ChipTone["tone"], string> = {
  ok: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  warn: "border-amber-500/40 bg-amber-500/10 text-amber-300",
  bad: "border-rose-500/40 bg-rose-500/10 text-rose-300",
};

function ChipBadge({ chip }: { chip: ChipTone }) {
  return (
    <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${toneClass[chip.tone]}`}>
      {chip.label}
    </span>
  );
}

function Stat({ label, value, sub }: { label: string; value: string | number; sub?: string }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
      <div className="text-[11px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-1 text-3xl font-black tracking-tight text-white">{value}</div>
      {sub ? <div className="mt-1 text-xs text-slate-500">{sub}</div> : null}
    </div>
  );
}

export default function Health() {
  const { report, loading, error } = useHealth();

  return (
    <div className="min-h-screen bg-slate-950 px-4 py-8 text-slate-100 sm:px-8">
      <div className="mx-auto flex max-w-5xl flex-col gap-6">
        <header className="border-b border-slate-900 pb-6">
          <div className="flex items-center gap-2 text-emerald-400">
            <Activity className="h-5 w-5" aria-hidden="true" />
            <span className="text-xs font-bold uppercase tracking-widest">System</span>
          </div>
          <h1 className="mt-2 text-3xl font-black uppercase italic tracking-tight text-white sm:text-4xl">
            Health
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-slate-400">{HEALTH_INTRO}</p>
        </header>

        {loading ? (
          <div className="flex items-center gap-2 text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading…
          </div>
        ) : error ? (
          <div className="flex items-start gap-2 rounded-xl border border-rose-500/40 bg-rose-500/10 p-4 text-sm text-rose-200">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        ) : report ? (
          <HealthBody report={report} />
        ) : null}
      </div>
    </div>
  );
}

interface RerunRequest { requested_by?: string; requested_at?: string }
const RERUNNABLE = new Set(["scan", "settle"]);

/**
 * The last 14 days as a heatmap (phase-3 §2): rows are timers, forecaster
 * families, and the diagnostics annotations; colour is the verdict, intensity
 * is the frozen count. "Silent" is only ever a gap inside an active stretch
 * (the backend's rule), never an inference from a quiet day. The orderbooks
 * timer has no history source and is not drawn -- absence over invention.
 */
function Heatmap({ history }: { history: import("@/lib/health").HealthHistory | null | undefined }) {
  const [detail, setDetail] = useState<string | null>(null);
  if (history === undefined) return null;
  if (history === null) {
    return (
      <section>
        <h2 className="mb-2 text-sm font-bold uppercase tracking-wider text-slate-400">Last 14 days</h2>
        <p className="text-sm text-slate-500">Heatmap unavailable — its reads failed; the sections below still report now.</p>
      </section>
    );
  }
  const rows: { label: string; cells: import("@/lib/health").HistoryCell[] }[] = [
    ...Object.entries(history.timers).map(([label, cells]) => ({ label, cells })),
    ...Object.entries(history.families).map(([label, cells]) => ({ label, cells })),
    { label: "diagnostics", cells: history.diagnostics },
  ];
  const cellClass = (c: import("@/lib/health").HistoryCell, isFamily: boolean) => {
    if (c.status === "silent") return "bg-rose-500/80";
    if (c.status === "flags") return "bg-amber-400/80";
    if (c.status === "ok") {
      if (!isFamily) return "bg-emerald-500/70";
      const n = c.count ?? 0;
      return n >= 21 ? "bg-emerald-500/90" : n >= 6 ? "bg-emerald-500/65" : n >= 2 ? "bg-emerald-500/45" : "bg-emerald-500/30";
    }
    return "bg-slate-800";
  };
  const describe = (label: string, c: import("@/lib/health").HistoryCell) =>
    c.status === "flags"
      ? `${label} · ${c.date} · ${(c.flags ?? []).join("; ") || "flags recorded"} (annotations, not a verdict)`
      : c.status === "ok"
        ? `${label} · ${c.date} · ran${c.count != null ? ` · ${c.count} frozen` : ""}`
        : c.status === "silent"
          ? `${label} · ${c.date} · silent — a gap inside an active stretch`
          : `${label} · ${c.date} · no claim`;
  return (
    <section>
      <h2 className="mb-2 text-sm font-bold uppercase tracking-wider text-slate-400">Last 14 days</h2>
      <div className="overflow-x-auto rounded-xl border border-slate-800 bg-slate-900/40 p-3">
        <div className="grid min-w-[560px] gap-1" style={{ gridTemplateColumns: `7rem repeat(${history.days.length}, minmax(0,1fr))` }}>
          <div />
          {history.days.map((d) => (
            <div key={d} className="text-center text-[10px] tabular-nums text-slate-500">{d.slice(5)}</div>
          ))}
          {rows.map((row) => (
            <Fragment key={row.label}>
              <div className="truncate pr-2 text-xs leading-6 text-slate-300">{row.label}</div>
              {row.cells.map((c) => (
                <button key={`${row.label}-${c.date}`} type="button" title={describe(row.label, c)}
                  aria-label={describe(row.label, c)}
                  onClick={() => setDetail(describe(row.label, c))}
                  className={`h-6 rounded ${cellClass(c, row.label in history.families)}`} />
              ))}
            </Fragment>
          ))}
        </div>
      </div>
      <p className="mt-1 text-xs text-slate-500">
        {detail ?? "Green ran (darker = more frozen) · red = silent inside an active stretch · amber = diagnostics flags that day · dark = no claim. The orderbooks timer has no history source and is not drawn."}
      </p>
    </section>
  );
}

function HealthBody({ report }: { report: import("@/lib/health").HealthReport }) {
  const s = healthSummary(report);
  const timers = timerRows(report);
  const families = familyRows(report);
  const ob = report.orderbook;
  // Re-run asks (phase-2 section 4.3): the API drops a trigger file the host watcher
  // claims within a minute. Pending state is the file's own record, read back here.
  const [rerunPending, setRerunPending] = useState<Record<string, RerunRequest>>({});
  const [rerunBusy, setRerunBusy] = useState<string | null>(null);
  const [rerunNote, setRerunNote] = useState<string | null>(null);
  useEffect(() => {
    adminJson<{ pending: Record<string, RerunRequest> }>("/api/health/rerun")
      .then((r) => setRerunPending(r.pending ?? {}))
      .catch(() => undefined);
  }, []);
  const askRerun = (job: string) => {
    setRerunBusy(job);
    setRerunNote(null);
    adminJson<{ status: string; requested_by?: string; requested_at?: string }>("/api/health/rerun", {
      method: "POST", body: JSON.stringify({ job }),
    })
      .then((r) => {
        setRerunPending((prev) => ({ ...prev, [job]: { requested_by: r.requested_by, requested_at: r.requested_at } }));
        setRerunNote(r.status === "already_pending"
          ? `A ${job} re-run is already waiting for the host.`
          : `${job} re-run requested -- the host picks it up within a minute.`);
      })
      .catch(() => setRerunNote(`The ${job} re-run request could not be written.`))
      .finally(() => setRerunBusy(null));
  };

  return (
    <>
      <div className="flex items-center gap-3">
        <span className="text-lg font-bold text-white">Overall</span>
        <ChipBadge chip={statusChip(report.status)} />
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label="Timers fresh"
          value={`${s.okTimers}/${s.totalTimers}`}
          sub={s.untrackedTimers > 0 ? `${s.untrackedTimers} not tracked` : undefined}
        />
        <Stat label="Quiet families" value={s.silentFamilies} sub="daily, froze nothing" />
        <Stat label="Problems" value={s.problemCount} />
        <div className="rounded-xl border border-slate-800 bg-slate-900/40 p-4">
          <div className="text-[11px] uppercase tracking-wider text-slate-500">Order books</div>
          <div className="mt-1 flex items-center gap-2">
            <span className="text-3xl font-black tracking-tight text-white">
              {formatAge(ob.newest_file_age_seconds)}
            </span>
            <ChipBadge chip={statusChip(ob.status)} />
          </div>
        </div>
      </div>

      {s.untrackedTimers > 0 ? (
        <p className="text-xs text-slate-500">
          {report.untracked_timers.join(" and ")} write no record of each run, so their last success
          cannot be read. They are not counted above and are not faults.
        </p>
      ) : null}

      <Heatmap history={report.history} />

      <details>
        <summary className="mb-2 cursor-pointer text-sm font-bold uppercase tracking-wider text-slate-400">Timers</summary>
        <div className="flex flex-col gap-2">
          {timers.map((t) => (
            <div
              key={t.name}
              className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3"
            >
              <div className="min-w-0">
                <div className="text-sm font-semibold text-slate-200">
                  {t.label} <span className="font-mono text-[11px] text-slate-500">({t.name})</span>
                </div>
                <div className="text-xs text-slate-500">{t.lastSuccess ? ct(t.lastSuccess) : "never"}</div>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                <span className="text-sm tabular-nums text-slate-300">{t.age}</span>
                <ChipBadge chip={t.chip} />
                {RERUNNABLE.has(t.name) && (rerunPending[t.name] ? (
                  <span className="rounded-full border border-sky-500/40 bg-sky-500/10 px-2 py-0.5 text-[11px] font-semibold text-sky-300">
                    Re-run pending{rerunPending[t.name].requested_at ? ` · ${ct(rerunPending[t.name].requested_at!)}` : ""}
                  </span>
                ) : (
                  <button type="button" disabled={rerunBusy !== null} onClick={() => askRerun(t.name)}
                    className="rounded-lg border border-slate-700 px-2.5 py-1 text-xs font-medium text-slate-200 hover:border-slate-500 disabled:opacity-50">
                    {rerunBusy === t.name ? "Asking..." : "Re-run"}
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
        {rerunNote && <p className="mt-2 text-sm text-slate-400">{rerunNote}</p>}
      </details>

      <details>
        <summary className="mb-2 cursor-pointer text-sm font-bold uppercase tracking-wider text-slate-400">
          Forecasts frozen (last {report.frozen_window_hours}h)
        </summary>
        <div className="flex flex-col gap-2">
          {families.length === 0 ? (
            <p className="text-sm text-slate-500">No families reported.</p>
          ) : (
            families.map((f) => (
              <div
                key={f.name}
                className="flex items-center justify-between gap-3 rounded-xl border border-slate-800 bg-slate-900/40 px-4 py-3"
              >
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-slate-200">{f.name}</div>
                  <div className="text-xs text-slate-500">{f.cadence}</div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <span className="text-sm tabular-nums text-slate-300">{f.frozen}</span>
                  {f.silent ? <ChipBadge chip={{ label: "Quiet", tone: "bad" }} /> : null}
                </div>
              </div>
            ))
          )}
        </div>
      </details>

      {report.problems.length > 0 ? (
        <section>
          <h2 className="mb-2 text-sm font-bold uppercase tracking-wider text-slate-400">Problems</h2>
          <ul className="flex list-disc flex-col gap-1 pl-5 text-sm text-amber-200">
            {report.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {report.diagnostics ? (
        <section>
          <h2 className="mb-2 text-sm font-bold uppercase tracking-wider text-slate-400">
            Model diagnostics
          </h2>
          <p className="text-xs text-slate-500">
            From the newest measured backtest run ({report.diagnostics.engine} · {report.diagnostics.mode}).
            Flags are reasons to look at a model, not health failures.
          </p>
          {report.diagnostics.feature_flags.length + report.diagnostics.residual_flags.length > 0 ? (
            <ul className="mt-2 flex list-disc flex-col gap-1 pl-5 text-sm text-amber-200">
              {[...report.diagnostics.feature_flags, ...report.diagnostics.residual_flags].map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-slate-400">No diagnostic flags on that run.</p>
          )}
        </section>
      ) : null}

      <p className="pb-6 text-xs text-slate-600">Generated {ct(report.generated_at)}</p>
    </>
  );
}
