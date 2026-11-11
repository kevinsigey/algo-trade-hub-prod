import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Loader2 } from "lucide-react";

import { adminJson, verdictTone, type FillRow, type Idea, type IdeaRow, type ScreenRow, type WorkshopDashboard } from "@/lib/workshop";
import { fmtUsd } from "@/lib/paperPortfolio";
import NewIdeaBox from "@/components/NewIdeaBox";
import { SectorTonePanel } from "@/components/SectorTonePanel";

export const toneClass = {
  ok: "border-emerald-500/40 bg-emerald-500/10 text-emerald-300",
  bad: "border-rose-500/40 bg-rose-500/10 text-rose-300",
  flat: "border-slate-600/60 bg-slate-700/20 text-slate-300",
} as const;

/** A fill needs a label only when nothing has decided it yet (Kevin,
 * 2026-11-02): no relabel row, its order tag names no idea, and the client id
 * is not one of the hub's self-describing prefixes (ext- machine orders and
 * manual- hand orders are already what they claim to be). What remains --
 * fills placed outside the hub -- is the real labeling queue. */
export function needsLabel(f: FillRow): boolean {
  if ((f.history?.length ?? 0) > 0) return false;
  const tag = f.tag ?? "";
  if (/^idea-\d+-/.test(tag)) return false;
  return !tag.startsWith("ext-") && !tag.startsWith("manual-");
}

/** The labeling queue: ONLY the fills that need one (Kevin, 2026-11-02),
 * as boxed rows. Attributed fills are counted, not listed. */
export function TradeLabels({ ideas }: { ideas: IdeaRow[] }) {
  const [fills, setFills] = useState<FillRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = () =>
    adminJson<{ state: string; fills?: FillRow[] }>("/api/workshop/fills")
      .then((d) => setFills(d.fills ?? []))
      .catch((e: Error) => setError(e.message));
  useEffect(() => {
    load();
  }, []);
  const relabel = (order_id: string, value: string) =>
    adminJson("/api/workshop/labels", { method: "POST", body: JSON.stringify({ order_id, idea_id: value ? Number(value) : null }) })
      .then(load)
      .catch((e: Error) => setError(e.message));
  const title = (n: number | null) => (n == null ? "manual" : ideas.find((i) => i.id === n)?.title ?? `idea ${n}`);
  const queue = (fills ?? []).filter(needsLabel);
  const decided = (fills ?? []).length - queue.length;

  return (
    <>
      <p className="mt-1 text-sm text-slate-400">
        Fills placed outside the hub, with no tag and no label yet. Everything else already counts toward what it is.
      </p>
      {error && <p role="alert" className="mt-3 text-sm text-rose-300">{error}</p>}
      {fills && decided > 0 && (
        <p className="mt-3 text-xs text-slate-500">{decided} fills already attributed by their tags or labels — not shown.</p>
      )}
      {fills && queue.length === 0 && <p className="mt-3 text-sm text-emerald-300">Nothing needs labeling.</p>}
      <ul className="mt-3 space-y-2">
        {queue.map((f) => {
          const name = `${f.symbol} ${f.side} ${f.qty} on ${f.at.slice(0, 10)}`;
          return (
            <li key={f.order_id} className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2.5 text-sm">
              <span className="font-mono text-slate-200">{name}</span>
              <span className="flex flex-wrap items-center gap-2">
                {f.history.length > 0 && <span className="text-xs text-slate-500">was {title(f.history[f.history.length - 1].from)}</span>}
                <select aria-label={`Idea for ${name}`} value={f.idea_id ?? ""} onChange={(e) => relabel(f.order_id, e.target.value)}
                  className="rounded-md border border-slate-700 bg-slate-900 px-2 py-1 text-sm text-white">
                  <option value="">No idea yet (manual)</option>
                  {ideas.map((i) => <option key={i.id} value={i.id}>{i.title}</option>)}
                </select>
              </span>
            </li>
          );
        })}
      </ul>
    </>
  );
}

/** Where an idea stands in its lifecycle, as a chip beside the verdict. Drafts show no chip. */
export function LifecycleChip({ row }: { row: IdeaRow }) {
  const chip = row.killed_at
    ? { label: "Killed", cls: toneClass.bad }
    : row.live_at
      ? { label: "Live", cls: toneClass.ok }
      : row.tracked_at
        ? { label: "Tracking", cls: "border-sky-500/40 bg-sky-500/10 text-sky-300" }
        : row.published_at
          ? { label: "Published", cls: toneClass.flat }
          : null;
  if (!chip) return null;
  return <span className={`rounded-full border px-2 py-0.5 font-semibold ${chip.cls}`}>{chip.label}</span>;
}

function ideaGroup(row: IdeaRow): "live" | "tracking" | "published" | "draft" | "killed" {
  if (row.killed_at) return "killed";
  if (row.live_at) return "live";
  if (row.tracked_at) return "tracking";
  if (row.published_at) return "published";
  return "draft";
}

const GROUP_LABEL = { live: "Live", tracking: "Tracking", published: "Published", draft: "Drafts", killed: "Killed" } as const;

function IdeaRows({ rows }: { rows: IdeaRow[] }) {
  return (
    <ul className="mt-3 space-y-2">
      {rows.map((i) => (
        <li key={i.id} className="rounded-lg border border-slate-800 bg-slate-900/60 px-3 hover:border-slate-600">
          <Link to={`/workshop/${i.id}`} className="flex items-center justify-between gap-3 py-2.5 hover:text-white">
            <span className="text-slate-200">{i.title}</span>
            <span className="flex shrink-0 items-center gap-3 text-xs text-slate-400">
              {i.runs} {i.runs === 1 ? "run" : "runs"}
              <LifecycleChip row={i} />
              <span className={`rounded-full border px-2 py-0.5 font-semibold ${toneClass[verdictTone(i.verdict_now ?? i.latest_verdict)]}`}>
                {i.verdict_now ?? i.latest_verdict ?? "Not run"}
              </span>
              {i.verdict_now != null && i.latest_verdict != null && i.verdict_now !== i.latest_verdict && (
                <span className="text-slate-500">as run {i.latest_verdict}</span>
              )}
              {i.batch && (
                <span className="text-slate-500">
                  Trial {i.batch.position} of {i.batch.size} in {i.batch.id}
                  {i.batch.trial != null && i.batch.trial !== i.batch.position ? ` · lab trial ${i.batch.trial}` : ""}
                </span>
              )}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function StatTile({ label, value, sub, warn = false }: { label: string; value: string; sub?: string; warn?: boolean }) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${warn ? "text-amber-300" : "text-white"}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  );
}

type Tab = "overview" | "ideas" | "labels" | "screens" | "tone";

/** Kevin's Workshop (rebuilt, 2026-11-02): a dashboard of totals up front and
 * the detail behind tabs -- ideas grouped by where they stand, the labeling
 * queue showing only what needs a label, runs summarized instead of listed.
 * The full record of any single idea lives on its own page. */
export default function Workshop() {
  const [error, setError] = useState<string | null>(null);
  const [ideas, setIdeas] = useState<IdeaRow[] | null>(null);
  const [dash, setDash] = useState<WorkshopDashboard | null>(null);
  const [screens, setScreens] = useState<ScreenRow[] | null>(null);
  const [tab, setTab] = useState<Tab>("overview");

  useEffect(() => {
    adminJson<IdeaRow[]>("/api/workshop/ideas").then(setIdeas).catch((e: Error) => setError(e.message));
    adminJson<WorkshopDashboard>("/api/workshop/dashboard").then((d) => setDash(d?.ideas ? d : null)).catch(() => setDash(null));
    adminJson<ScreenRow[]>("/api/screening/screens").then((d) => setScreens(Array.isArray(d) ? d : [])).catch(() => setScreens([]));
  }, []);

  const groups = (Object.keys(GROUP_LABEL) as (keyof typeof GROUP_LABEL)[])
    .map((g) => ({ g, rows: (ideas ?? []).filter((i) => ideaGroup(i) === g) }))
    .filter(({ rows }) => rows.length > 0);
  const liveRows = (ideas ?? []).filter((i) => ideaGroup(i) === "live");

  const tabs: { key: Tab; label: string; badge?: number }[] = [
    { key: "overview", label: "Overview" },
    { key: "ideas", label: "Ideas", badge: dash?.ideas.total },
    { key: "labels", label: "Trade labels", badge: dash?.fills.needs_label },
    { key: "screens", label: "Screens", badge: dash?.screens.total },
    { key: "tone", label: "Sector tone" },
  ];

  return (
    <div className="mx-auto max-w-5xl px-4 py-8 md:px-8">
      <h1 className="text-2xl font-bold tracking-tight text-white">Workshop</h1>
      <p className="mt-1 text-sm text-slate-400">An idea in plain words, tested against what it claims. Every verdict is kept, pass or fail.</p>

      <NewIdeaBox />
      {error && <p role="alert" className="mt-3 text-sm text-rose-300">{error}</p>}

      {dash && (
        <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
          <StatTile label="Live ideas" value={String(dash.ideas.live + dash.ideas.live_big)}
                    sub={`${dash.ideas.live} main · ${dash.ideas.live_big} on $1M`} />
          <StatTile label="Tracking" value={String(dash.ideas.tracking)} sub={`${dash.ideas.total} ideas in all`} />
          <StatTile label="Tests kept" value={String(dash.runs.saved)} sub={`${dash.runs.total} runs incl. previews`} />
          <StatTile label="Latest verdicts, current bar" value={`${dash.runs.latest_verdicts.PASS ?? 0} PASS`}
                    sub={`${dash.runs.latest_verdicts.FAIL ?? 0} fail · ${dash.runs.latest_verdicts.NOT_ENOUGH_DATA ?? 0} not enough data${(dash.runs.latest_verdicts_as_run?.PASS ?? 0) !== (dash.runs.latest_verdicts.PASS ?? 0) ? ` · as run ${dash.runs.latest_verdicts_as_run?.PASS ?? 0} PASS` : ""}`} />
          <StatTile label="Fills attributed" value={dash.fills.state === "live" ? `${dash.fills.attributed}/${dash.fills.total}` : "—"}
                    sub={dash.fills.state === "live" ? "the rest are manual / mirror" : "account not connected"} />
          <StatTile label="Needs labeling" value={String(dash.fills.needs_label)} warn={dash.fills.needs_label > 0}
                    sub={dash.manual_actions_open > 0 ? `${dash.manual_actions_open} manual actions open` : "no manual actions open"} />
        </div>
      )}

      <div className="mt-8 flex flex-wrap gap-1 border-b border-slate-800" role="tablist" aria-label="Workshop sections">
        {tabs.map((t) => (
          <button key={t.key} type="button" role="tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}
                  className={`rounded-t-lg px-3 py-2 text-sm font-medium ${
                    tab === t.key ? "bg-slate-800 text-white" : "text-slate-400 hover:text-slate-200"}`}>
            {t.label}
            {t.badge != null && t.badge > 0 && (
              <span className="ml-1.5 rounded-full bg-slate-700 px-1.5 py-0.5 text-[11px] tabular-nums text-slate-200">{t.badge}</span>
            )}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="mt-6 grid gap-4 lg:grid-cols-2">
          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Live now</h2>
            {liveRows.length === 0
              ? <p className="mt-3 text-sm text-slate-400">Nothing is trading live.</p>
              : <IdeaRows rows={liveRows} />}
          </section>
          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Latest test activity</h2>
            {dash && dash.runs.recent.length > 0 ? (
              <ul className="mt-3 space-y-2">
                {dash.runs.recent.map((r, i) => (
                  <li key={i} className="flex items-baseline justify-between gap-3 rounded-lg border border-slate-800 px-3 py-2 text-sm">
                    <Link to={`/workshop/${r.idea_id}`} className="text-slate-200 hover:text-emerald-300">{r.title ?? `Idea ${r.idea_id}`}</Link>
                    <span className="flex shrink-0 items-baseline gap-2 text-xs text-slate-500">
                      {r.at?.slice(0, 10)}
                      <span className={`rounded-full border px-2 py-0.5 font-semibold ${toneClass[verdictTone(r.verdict as IdeaRow["latest_verdict"])]}`}>{r.verdict}</span>
                    </span>
                  </li>
                ))}
              </ul>
            ) : <p className="mt-3 text-sm text-slate-400">No saved runs yet.</p>}
          </section>
          <section className="rounded-xl border border-slate-800 bg-slate-900/60 p-4 lg:col-span-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Closed paper P&L by idea</h2>
            {dash && dash.fills.closed_pnl_by_idea.length > 0 ? (
              <ul className="mt-3 grid gap-2 sm:grid-cols-2">
                {dash.fills.closed_pnl_by_idea.map((row) => (
                  <li key={row.idea} className="flex items-baseline justify-between gap-3 rounded-lg border border-slate-800 px-3 py-2 text-sm">
                    <span className="text-slate-200">{row.idea}</span>
                    <span className="tabular-nums text-slate-400">
                      {row.trades} trades · <span className={row.pnl >= 0 ? "text-emerald-300" : "text-rose-300"}>{fmtUsd(row.pnl, { signed: true })}</span>
                    </span>
                  </li>
                ))}
              </ul>
            ) : <p className="mt-3 text-sm text-slate-400">No closed paper trades yet.</p>}
          </section>
        </div>
      )}

      {tab === "ideas" && (
        <div className="mt-6 space-y-8">
          {ideas === null && !error && <p className="text-sm text-slate-400">Loading…</p>}
          {ideas?.length === 0 && <p className="text-sm text-slate-400">No ideas yet.</p>}
          {groups.map(({ g, rows }) => (
            <details key={g} open={g === "live" || g === "tracking"}>
              <summary className="cursor-pointer text-lg font-semibold text-white">
                {GROUP_LABEL[g]} <span className="text-sm font-normal text-slate-500">· {rows.length}</span>
              </summary>
              <IdeaRows rows={rows} />
            </details>
          ))}
        </div>
      )}

      {tab === "labels" && ideas && (
        <div className="mt-6">
          <h2 className="sr-only">Trade labels</h2>
          <TradeLabels ideas={ideas} />
        </div>
      )}

      {tab === "screens" && (
        <div className="mt-6">
          <p className="text-sm text-slate-400">
            Saved screens from the <Link to="/screening" className="text-emerald-300 hover:underline">Screening tab</Link> — a screen
            promotes once, into a tracked basket idea.
          </p>
          {screens?.length === 0 && <p className="mt-3 text-sm text-slate-400">No saved screens yet.</p>}
          <ul className="mt-3 space-y-2">
            {(screens ?? []).map((sc) => (
              <li key={sc.id} className="flex flex-wrap items-baseline justify-between gap-3 rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2.5 text-sm">
                <span className="text-slate-200">{sc.name}</span>
                <span className="text-xs text-slate-500">
                  {sc.last_run ? `last run ${sc.last_run.run_at?.slice(0, 10) ?? ""} · ${sc.last_run.survivors ?? 0} survivors` : "not run yet"}
                  {sc.promoted_idea_id
                    ? <> · <Link to={`/workshop/${sc.promoted_idea_id}`} className="text-emerald-300 hover:underline">promoted to an idea</Link></>
                    : " · not promoted"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {tab === "tone" && (
        <div className="mt-6">
          <SectorTonePanel />
        </div>
      )}

      <p className="mt-12 text-sm text-slate-400">
        Looking for the TradingAgents panel? It has its own tab now:{" "}
        <Link to="/debates" className="text-violet-300 hover:underline">Agent debates</Link>{" "}
        — an opinion panel with a graded record, kept out of the idea pipeline on purpose.
      </p>
    </div>
  );
}
