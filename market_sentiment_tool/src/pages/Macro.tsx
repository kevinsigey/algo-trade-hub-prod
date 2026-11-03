import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { Landmark } from "lucide-react";
import { getJson } from "@/lib/getJson";
import { Badge } from "@/components/ui/badge";
import { recordVerdict, type MacroCard, type MacroResponse } from "@/lib/macro";

/**
 * Macro predictions (phase-3 §1). One card per macro engine: the call, the
 * record, the trail -- the main idea first, the full page one click away.
 * Jobs trails are values; CPI/gas trails are probabilities; the card says
 * which and renders accordingly. A section the server could not fill arrives
 * null and renders "unavailable" -- never a zero dressed as a reading.
 */
const fmtVal = (v: number | null, kind: "value" | "probability") =>
  v == null ? "—" : kind === "probability" ? `${Math.round(v * 100)}%` : v.toLocaleString();

const OURS = "#34d399";
const MARKET = "#94a3b8";
const ACTUAL = "#f8fafc";

/** Ours-vs-market as paired horizontal bars (a probability call, e.g. the U3 strike). */
function SplitBar({ ours, market }: { ours: number | null; market: number | null }) {
  if (ours === null && market === null) return null;
  const row = (label: string, v: number | null, color: string) => (
    <div className="flex items-center gap-2 text-xs tabular-nums">
      <span className="w-12 shrink-0 text-muted-foreground">{label}</span>
      <div className="h-2.5 flex-1 rounded bg-muted/40">
        {v !== null && <div className="h-2.5 rounded" style={{ width: `${Math.max(2, v * 100)}%`, background: color }} />}
      </div>
      <span className="w-10 shrink-0 text-right">{v === null ? "—" : `${Math.round(v * 100)}%`}</span>
    </div>
  );
  return (
    <div className="mt-2 space-y-1" role="img" aria-label={`Ours ${ours === null ? "—" : `${Math.round(ours * 100)}%`} versus Kalshi ${market === null ? "—" : `${Math.round(market * 100)}%`}`}>
      {row("Ours", ours, OURS)}
      {row("Kalshi", market, MARKET)}
    </div>
  );
}

/** The trail as a chart (redesign, 2026-11-02): values get grouped bars per print
 * (ours / Kalshi / actual); probabilities get two lines plus the outcome dots. */
function TrailChart({ card }: { card: MacroCard }) {
  const pts = card.trail.filter((p) => p.ours !== null || p.market !== null || p.actual !== null);
  if (pts.length === 0) return null;
  const W = 320;
  const H = 96;
  if (card.trail_kind === "probability") {
    const X = (i: number) => (pts.length === 1 ? W / 2 : (i / (pts.length - 1)) * (W - 16) + 8);
    const Y = (v: number) => H - 8 - v * (H - 20);
    const line = (key: "ours" | "market") =>
      pts.map((p, i) => (p[key] === null ? "" : `${i === 0 ? "M" : "L"}${X(i)},${Y(p[key] as number)}`)).join(" ");
    return (
      <figure>
        <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Recent calls: our probability against the market's, with outcomes">
          <line x1="8" x2={W - 8} y1={Y(0.5)} y2={Y(0.5)} stroke="#475569" strokeDasharray="3 3" strokeWidth="0.75" />
          <path d={line("market")} fill="none" stroke={MARKET} strokeWidth="1.75" />
          <path d={line("ours")} fill="none" stroke={OURS} strokeWidth="1.75" />
          {pts.map((p, i) => p.actual !== null && (
            <circle key={p.label} cx={X(i)} cy={Y(p.actual)} r="3" fill="#fbbf24" />
          ))}
        </svg>
        <figcaption className="mt-1 flex justify-between text-[11px] text-muted-foreground">
          <span>{pts[0].label}</span>
          <span className="flex gap-3">
            <span style={{ color: OURS }}>— ours</span>
            <span style={{ color: MARKET }}>— Kalshi</span>
            <span className="text-amber-400">● outcome</span>
          </span>
          <span>{pts[pts.length - 1].label}</span>
        </figcaption>
      </figure>
    );
  }
  const vals = pts.flatMap((p) => [p.ours, p.market, p.actual]).filter((v): v is number => v !== null);
  const lo = Math.min(0, ...vals);
  const hi = Math.max(...vals, 1);
  const groupW = (W - 16) / pts.length;
  const barW = Math.min(14, groupW / 4);
  const Y = (v: number) => H - 14 - ((v - lo) / (hi - lo)) * (H - 26);
  const bars = (p: MacroCard["trail"][number], gi: number) =>
    ([["ours", OURS], ["market", MARKET], ["actual", ACTUAL]] as const).map(([key, color], bi) => {
      const v = p[key];
      if (v === null) return null;
      const x = 8 + gi * groupW + groupW / 2 + (bi - 1) * (barW + 1.5) - barW / 2;
      const y0 = Y(Math.max(lo, 0));
      const y = Y(v);
      return <rect key={key} x={x} y={Math.min(y, y0)} width={barW} height={Math.max(1.5, Math.abs(y0 - y))} fill={color} rx="1" />;
    });
  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Recent prints: our nowcast against the market mean and the first print">
        <line x1="8" x2={W - 8} y1={Y(0)} y2={Y(0)} stroke="#475569" strokeWidth="0.75" />
        {pts.map((p, i) => bars(p, i))}
        {pts.map((p, i) => (
          <text key={p.label} x={8 + i * groupW + groupW / 2} y={H - 2} textAnchor="middle" fontSize="8.5" fill="#94a3b8">
            {p.label}
          </text>
        ))}
      </svg>
      <figcaption className="mt-1 flex gap-3 text-[11px] text-muted-foreground">
        <span style={{ color: OURS }}>■ ours</span>
        <span style={{ color: MARKET }}>■ Kalshi</span>
        <span style={{ color: ACTUAL }}>■ actual print</span>
      </figcaption>
    </figure>
  );
}

function CardView({ card }: { card: MacroCard }) {
  const rec = card.record;
  return (
    <Link to={card.detail_href} className="block rounded-2xl border border-border/70 bg-card p-5 shadow-sm transition hover:border-foreground/30">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{card.title}</h2>
          <p className="text-sm text-muted-foreground">{card.predicts}</p>
          {card.display_only && (
            <p className="mt-1 text-xs text-muted-foreground">
              Display — the nowcast and its record, not a board of opportunities.
            </p>
          )}
        </div>
        {rec?.gate_status ? (
          <Badge variant={rec.gate_status === "PROMOTED" ? "default" : "secondary"}>{rec.gate_status}</Badge>
        ) : (
          <Badge variant="outline">journal-graded</Badge>
        )}
      </div>

      {card.next_release && (
        <p className="mt-3 text-xs text-muted-foreground">Next release: {card.next_release}</p>
      )}

      <div className="mt-4">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">The call</p>
        {card.call ? (
          <div className="mt-1">
            <p className="text-sm font-medium">{card.call.label}</p>
            <p className="mt-1 text-sm tabular-nums">
              Ours <strong>{fmtVal(card.call.ours, card.trail_kind)}</strong>
              {" · "}Kalshi <strong>{fmtVal(card.call.market, card.trail_kind)}</strong>
              {card.call.last_actual != null && (
                <>{" · "}Last print <strong>{fmtVal(card.call.last_actual, card.trail_kind)}</strong></>
              )}
            </p>
          </div>
        ) : (
          <p className="mt-1 text-sm text-muted-foreground">No live call — unavailable.</p>
        )}
      </div>

      <div className="mt-4">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">The record</p>
        {rec ? (
          <>
            <p className="mt-1 text-sm">{recordVerdict(rec)}</p>
            <p className="text-xs tabular-nums text-muted-foreground">
              {rec.n_settled ?? 0} settled · Brier ours {rec.brier_ours?.toFixed(3) ?? "—"} vs market{" "}
              {rec.brier_market?.toFixed(3) ?? "—"}
              {rec.gap != null && ` · paired gap ${rec.gap >= 0 ? "+" : ""}${rec.gap.toFixed(3)}`}
            </p>
            {rec.diagnostics_flags.length > 0 && (
              <p className="mt-1 text-xs text-muted-foreground">
                Diagnostics: {rec.diagnostics_flags.join("; ")} — annotations, not a verdict.
              </p>
            )}
          </>
        ) : (
          <p className="mt-1 text-sm text-muted-foreground">Record unavailable.</p>
        )}
      </div>

      {card.u3 && (
        <div className="mt-4 border-t border-border pt-3">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            Unemployment (KXU3)
          </p>
          {card.u3.call ? (
            <>
              <p className="mt-1 text-sm tabular-nums">
                {card.u3.call.label} — Ours <strong>{fmtVal(card.u3.call.ours, "probability")}</strong>
                {" · "}Kalshi <strong>{fmtVal(card.u3.call.market, "probability")}</strong>
              </p>
              <SplitBar ours={card.u3.call.ours} market={card.u3.call.market} />
            </>
          ) : (
            <p className="mt-1 text-sm text-muted-foreground">No live call.</p>
          )}
          {card.u3.record && (
            <p className="text-xs tabular-nums text-muted-foreground">
              {card.u3.record.n_settled ?? 0} settled · Brier ours{" "}
              {card.u3.record.brier_ours?.toFixed(3) ?? "—"} vs market{" "}
              {card.u3.record.brier_market?.toFixed(3) ?? "—"}
            </p>
          )}
        </div>
      )}

      {card.trail.length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            {card.trail_kind === "value" ? "Recent prints" : "Recent calls"}
          </p>
          <div className="mt-1">
            <TrailChart card={card} />
          </div>
        </div>
      )}
      <p className="mt-4 text-xs font-medium text-primary">Open the full page →</p>
    </Link>
  );
}

export default function Macro() {
  const [data, setData] = useState<MacroResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJson<MacroResponse>("/api/macro").then(setData).catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div className="mx-auto w-full max-w-6xl">
      <div className="flex items-center gap-2">
        <Landmark className="h-6 w-6 text-muted-foreground" />
        <h1 className="text-3xl font-bold tracking-tight">Macro predictions</h1>
      </div>
      <p className="mt-1 text-sm text-muted-foreground">Jobs, CPI and PPI — each engine's call and record on one screen. Click a card for the full page.</p>
      {error && <p role="alert" className="mt-4 text-sm text-rose-300">Macro dashboard unavailable: {error}</p>}
      {!data && !error && <p className="mt-4 text-sm text-muted-foreground">Loading the macro board…</p>}
      {data && (
        <>
          <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {data.cards.map((c) => <CardView key={c.key} card={c} />)}
          </div>
          <p className="mt-4 text-xs text-muted-foreground">As of {data.as_of}. Records pair each engine against the market on the same prints.</p>
        </>
      )}
    </div>
  );
}
