import { AlertTriangle, Loader2 } from "lucide-react";

import { useState } from "react";

import { FullView } from "@/components/Panel";
import { useThesisCards } from "@/hooks/useThesisCards";
import { useThesisScoreboard } from "@/hooks/useThesisScoreboard";
import { PEEK, PeekRows } from "@/pages/portfolio/shared";
import { ScoreboardCards } from "@/pages/ThesisScoreboard";
import type { ForecastCard } from "@/lib/thesisTracker";

const fmtInstant = (iso: string) =>
  new Date(iso).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
    timeZoneName: "short",
  });

const dash = (value: string | number | null | undefined) =>
  value === null || value === undefined || value === "" ? "—" : String(value);

function CardRow({ card }: { card: ForecastCard }) {
  return (
    <tr className="border-b border-slate-900 last:border-0">
      <td className="px-4 py-3 font-mono font-bold text-white">{card.ticker}</td>
      <td className="px-4 py-3 text-slate-300">{fmtInstant(card.print_at)}</td>
      <td className="px-4 py-3 text-slate-300">
        {dash(card.whisper_sign)}
        {card.whisper_esp !== null && (
          <span className="text-slate-500"> ({card.whisper_esp > 0 ? "+" : ""}{card.whisper_esp})</span>
        )}
      </td>
      <td className="px-4 py-3 text-slate-300">{dash(card.money_flow_direction)}</td>
      <td className="px-4 py-3 text-slate-300">{dash(card.guide_position)}</td>
      <td className="px-4 py-3 text-slate-300">{dash(card.predicted_direction)}</td>
      <td className="px-4 py-3 text-slate-300">{dash(card.classification)}</td>
      <td className="px-4 py-3 text-slate-400">{fmtInstant(card.frozen_at)}</td>
      <td className="px-4 py-3">
        {card.superseded ? (
          <span className="rounded-full bg-slate-800 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
            Superseded
          </span>
        ) : (
          <span className="rounded-full bg-emerald-500/15 px-2 py-0.5 text-[11px] font-bold uppercase tracking-wider text-emerald-300">
            Frozen
          </span>
        )}
      </td>
    </tr>
  );
}

function CardsTable({ cards }: { cards: ForecastCard[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-slate-800 text-[11px] uppercase tracking-wider text-slate-500">
            <th className="px-4 py-2">Ticker</th>
            <th className="px-4 py-2">Print</th>
            <th className="px-4 py-2">Whisper</th>
            <th className="px-4 py-2">Money flow</th>
            <th className="px-4 py-2">Guide position</th>
            <th className="px-4 py-2">Predicted</th>
            <th className="px-4 py-2">Classification</th>
            <th className="px-4 py-2">Frozen at</th>
            <th className="px-4 py-2">State</th>
          </tr>
        </thead>
        <tbody>
          {cards.map((card) => (
            <CardRow key={card.id} card={card} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Thesis() {
  const { cards, loading, error } = useThesisCards();
  const sb = useThesisScoreboard();
  const [all, setAll] = useState(false);

  return (
    <div className="min-h-screen bg-slate-950 px-8 py-6 text-slate-100">
      <div className="mx-auto flex max-w-[1600px] flex-col gap-4">
        <div className="space-y-1 border-b border-slate-900 pb-4">
          <h1 className="text-2xl font-bold tracking-tight text-white">Thesis</h1>
          <p className="max-w-3xl text-sm text-slate-400">
            Claims against their frozen windows, and the forecast cards frozen before each print.
          </p>
        </div>

        {sb.loading ? (
          <div className="flex items-center gap-2 py-4 text-slate-400">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading scoreboard…
          </div>
        ) : sb.error ? (
          <div className="flex items-center gap-2 py-4 text-red-300">
            <AlertTriangle className="h-4 w-4" /> {sb.error}
          </div>
        ) : !sb.board ? (
          <p className="py-4 text-sm text-slate-400">
            The tracker is not seeded yet — no theses, claims or regime inputs are recorded.
          </p>
        ) : (
          <ScoreboardCards board={sb.board} />
        )}

        <section aria-label="Forecast cards" className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
          <div className="flex items-baseline justify-between">
            <h2 className="text-xs font-medium text-slate-400">Forecast cards (frozen before each print)</h2>
            {cards.length > 0 && (
              <button type="button" onClick={() => setAll(true)} className="text-xs text-sky-400 hover:text-sky-300">
                Show all ({cards.length})
              </button>
            )}
          </div>
          <div className="mt-2">
            {loading ? (
              <div className="flex items-center gap-2 py-2 text-slate-400">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading cards…
              </div>
            ) : error ? (
              <div className="flex items-center gap-2 py-2 text-red-300">
                <AlertTriangle className="h-4 w-4" /> {error}
              </div>
            ) : cards.length === 0 ? (
              <p className="py-2 text-sm text-slate-400">
                No forecast cards yet. Cards are frozen through the machine API before a covered
                name prints; a print with no card is a coverage failure and is logged as one.
              </p>
            ) : (
              <PeekRows rows={cards.slice(0, PEEK).map((c) => ({
                key: String(c.id), label: c.ticker, aside: fmtInstant(c.print_at),
                value: `${dash(c.predicted_direction)} · ${c.superseded ? "Superseded" : "Frozen"}`,
              }))} />
            )}
          </div>
        </section>
        {all && (
          <FullView title="Forecast cards" onClose={() => setAll(false)}>
            <CardsTable cards={cards} />
          </FullView>
        )}
      </div>
    </div>
  );
}
