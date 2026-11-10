import { useEffect, useState } from "react";
import { Loader2 } from "lucide-react";

import { adminJson } from "@/lib/workshop";
import { ctDateTime } from "@/lib/format";
import { num } from "@/lib/valuation";

/**
 * Level watcher (Spec D, STAGE 1 — Rung 1 alerts only): a deterministic
 * service watches price levels with conditions (cross, touch-and-hold,
 * zone entry, VWAP side, volume, time window, file state, FOMC blackout)
 * and alerts. Stage 1 has no order path: a fired watch writes the
 * trigger log and the alert outbox, nothing else. Band-crossing watches
 * do not detect anything themselves — they drive Spec C's own crossing
 * state machine at intraday prices (one detector, ever), and the alert
 * fires from the crossing Spec C logs. This section is additive display;
 * if the endpoint is unavailable the page renders without it.
 */

export interface WatchRow {
  id: number;
  name: string;
  family: string;
  kind: string;
  instrument: string;
  trigger_type: string | null;
  level: number | string | null;
  level_hi: number | string | null;
  hold_minutes: number | null;
  intent: string;
  rung: number;
  enabled: boolean;
  disabled_reason: string | null;
  governor_group: string | null;
}

export interface FireRow {
  id: number;
  watch_id: number | null;
  family: string | null;
  instrument: string;
  session_date: string;
  fired_at: string;
  rung_effective: number;
  trigger_price: number | string | null;
  intent: string | null;
  score_1: number | string | null;
  score_5: number | string | null;
  crossing_ids: number[] | null;
}

export interface AlertRow {
  id: number;
  kind: string;
  title: string;
  body: string;
  status: string;
  created_at: string;
}

interface GovernorRow {
  name: string;
  numbers_set: boolean;
  disarmed: boolean;
  note: string;
}

interface FamilyRow {
  family: string;
  graded_count: number;
  mean_score_5: number | string | null;
  demoted_at: string | null;
}

interface WatcherPayload {
  stage: number;
  rung_cap: number;
  mode: string;
  cpi_blackout_gap: boolean;
  status: { state: string; last_heartbeat: string | null };
  watches: WatchRow[];
  fires: FireRow[];
  alerts_pending: AlertRow[];
  families: FamilyRow[];
  governors: GovernorRow[];
}

function price(v: number | string | null): string {
  const n = num(v);
  return n == null ? "—" : n.toFixed(2);
}

function score(v: number | string | null): string {
  const n = num(v);
  return n == null ? "—" : `${n >= 0 ? "+" : ""}${(n * 100).toFixed(1)}%`;
}

function triggerText(w: WatchRow): string {
  const level = price(w.level);
  if (w.trigger_type === "cross_up") return `cross up through ${level}`;
  if (w.trigger_type === "cross_down") return `cross down through ${level}`;
  if (w.trigger_type === "touch_and_hold") return `touch & hold ${level} · ${w.hold_minutes ?? "—"}m`;
  if (w.trigger_type === "zone_entry") {
    return `zone entry ${level}–${price(w.level_hi)}${w.hold_minutes ? ` · hold ${w.hold_minutes}m` : ""}`;
  }
  return w.trigger_type ?? "—";
}

const STATE_STYLES: Record<string, string> = {
  up: "bg-emerald-500/15 text-emerald-300",
  down: "bg-rose-500/15 text-rose-300",
  idle: "bg-slate-500/15 text-slate-300",
};

export default function LevelWatcher() {
  const [payload, setPayload] = useState<WatcherPayload | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    adminJson<WatcherPayload>("/api/level-watcher")
      .then((rows) => { if (live) setPayload(rows); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, []);

  if (failed) return null;
  if (!payload) {
    return (
      <section data-testid="level-watcher" aria-label="Level watcher" className="mt-10">
        <p className="inline-flex items-center gap-2 text-sm text-slate-400">
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> Loading watcher…
        </p>
      </section>
    );
  }
  const watches = Array.isArray(payload.watches) ? payload.watches : [];
  const fires = Array.isArray(payload.fires) ? payload.fires : [];
  const pending = Array.isArray(payload.alerts_pending) ? payload.alerts_pending : [];
  const governors = Array.isArray(payload.governors) ? payload.governors : [];
  const families = Array.isArray(payload.families) ? payload.families : [];
  const state = payload.status?.state ?? "idle";

  return (
    <section data-testid="level-watcher" aria-label="Level watcher" className="mt-10">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-lg font-semibold text-white">Level watcher</h2>
        <span className="rounded-full bg-amber-500/15 px-2.5 py-0.5 text-xs font-medium text-amber-300">
          STAGE 1 — RUNG 1 ALERTS ONLY
        </span>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATE_STYLES[state] ?? STATE_STYLES.idle}`}>
          watcher {state}
          {payload.status?.last_heartbeat && ` · last heartbeat ${ctDateTime(payload.status.last_heartbeat)}`}
        </span>
      </div>
      <p className="mt-0.5 max-w-3xl text-sm text-slate-400">
        Price levels with conditions a resting order cannot express — touch and hold, VWAP
        side, time windows, event blackouts. A fired watch writes the trigger log and an
        alert; Stage 1 places nothing and stages nothing. Band-crossing watches drive
        Spec C&apos;s own crossing machine at intraday prices — one detector, ever.
        Alerts wait in the outbox until the agent-side poller carries them to the
        Trading Thesis Testing chat.
      </p>
      {payload.cpi_blackout_gap && (
        <p className="mt-1 max-w-3xl text-xs text-slate-500">
          Blackout covers FOMC statements only — the hub has no stored CPI release
          calendar yet, so CPI blackouts are a known gap, not a silent one.
        </p>
      )}

      {governors.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm text-slate-300">
          {governors.map((g) => (
            <li key={g.name}>
              Governor · <span className="font-medium text-white">{g.name}</span>
              {`: ${g.note}`}
            </li>
          ))}
        </ul>
      )}

      <h3 className="mt-5 text-sm font-semibold text-white">
        Alerts pending delivery{pending.length > 0 && ` (${pending.length})`}
      </h3>
      {pending.length === 0 ? (
        <p className="mt-1 text-sm text-slate-500">No alerts pending. Fires land here first.</p>
      ) : (
        <ul className="mt-2 space-y-2">
          {pending.map((a) => (
            <li key={a.id} className="rounded-xl border border-slate-800 px-3 py-2 text-sm text-slate-300">
              <span className="font-medium text-white">{a.title}</span>
              {` · ${ctDateTime(a.created_at)}`}
              <br />
              <span className="text-slate-400">{a.body}</span>
            </li>
          ))}
        </ul>
      )}

      <h3 className="mt-5 text-sm font-semibold text-white">Watches</h3>
      {watches.length === 0 ? (
        <p className="mt-1 text-sm text-slate-500">
          No watches armed. The first watches (CEG zone, band crossings, SPY 770) arm
          only on Kevin&apos;s go — the service is running, the store is empty.
        </p>
      ) : (
        <div className="mt-2 overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full min-w-[680px] text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2 font-medium">Watch</th>
                <th className="px-3 py-2 font-medium">Trigger</th>
                <th className="px-3 py-2 font-medium">Family</th>
                <th className="px-3 py-2 font-medium">Rung</th>
                <th className="px-3 py-2 font-medium">State</th>
              </tr>
            </thead>
            <tbody>
              {watches.map((w) => (
                <tr key={w.id} className="border-b border-slate-800/60 text-slate-300">
                  <td className="px-3 py-2">
                    <span className="font-medium text-white">{w.instrument}</span>
                    {` · ${w.name}`}
                  </td>
                  <td className="px-3 py-2">{w.kind === "band_crossing" ? "Spec C band transitions" : triggerText(w)}</td>
                  <td className="px-3 py-2">{w.family}</td>
                  <td className="px-3 py-2">{w.rung > 1 ? `${w.rung} → 1 in Stage 1` : "1"}</td>
                  <td className="px-3 py-2">
                    {w.enabled ? "armed" : `off${w.disabled_reason ? ` — ${w.disabled_reason}` : ""}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h3 className="mt-5 text-sm font-semibold text-white">Trigger log</h3>
      {fires.length === 0 ? (
        <p className="mt-1 text-sm text-slate-500">
          No triggers yet. Every fire records its evidence here and grades at +1 and
          +5 sessions against doing nothing; a rule family that grades negative over
          20 triggers demotes itself.
        </p>
      ) : (
        <div className="mt-2 overflow-x-auto rounded-xl border border-slate-800">
          <table className="w-full min-w-[680px] text-left text-sm">
            <thead>
              <tr className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
                <th className="px-3 py-2 font-medium">When</th>
                <th className="px-3 py-2 font-medium">Name</th>
                <th className="px-3 py-2 font-medium">Family</th>
                <th className="px-3 py-2 font-medium">Trigger price</th>
                <th className="px-3 py-2 font-medium">+1 score</th>
                <th className="px-3 py-2 font-medium">+5 score</th>
              </tr>
            </thead>
            <tbody>
              {fires.map((f) => (
                <tr key={f.id} className="border-b border-slate-800/60 text-slate-300">
                  <td className="whitespace-nowrap px-3 py-2">{ctDateTime(f.fired_at)}</td>
                  <td className="px-3 py-2 font-medium text-white">{f.instrument}</td>
                  <td className="px-3 py-2">{f.family ?? "—"}</td>
                  <td className="px-3 py-2">{price(f.trigger_price)}</td>
                  <td className="px-3 py-2">{score(f.score_1)}</td>
                  <td className="px-3 py-2">{score(f.score_5)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {families.length > 0 && (
        <ul className="mt-3 space-y-1 text-sm text-slate-300">
          {families.map((f) => (
            <li key={f.family}>
              Family <span className="font-medium text-white">{f.family}</span>
              {`: ${f.graded_count}/20 graded`}
              {num(f.mean_score_5) != null && ` · mean +5 score ${score(f.mean_score_5)}`}
              {f.demoted_at && " · DEMOTED (auto-disabled)"}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
