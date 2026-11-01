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

      {card.trail.length > 0 && (
        <div className="mt-4">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            {card.trail_kind === "value" ? "Recent prints" : "Recent calls"}
          </p>
          <ul className="mt-1 space-y-0.5 text-xs tabular-nums text-muted-foreground">
            {card.trail.map((p) => (
              <li key={p.label} className="flex justify-between gap-2">
                <span>{p.label}</span>
                <span>
                  ours {fmtVal(p.ours, card.trail_kind)} · mkt {fmtVal(p.market, card.trail_kind)} ·{" "}
                  {card.trail_kind === "value" ? `actual ${fmtVal(p.actual, "value")}` : p.actual === 1 ? "resolved YES" : p.actual === 0 ? "resolved NO" : "—"}
                </span>
              </li>
            ))}
          </ul>
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
      <p className="mt-1 text-sm text-muted-foreground">Each engine's call and record on one screen. Click a card for the full page.</p>
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
