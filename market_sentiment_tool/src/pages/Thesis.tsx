import { AlertTriangle, Loader2 } from "lucide-react";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useThesisCards } from "@/hooks/useThesisCards";
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

export default function Thesis() {
  const { cards, loading, error } = useThesisCards();

  return (
    <div className="min-h-screen bg-slate-950 px-8 py-10 text-slate-100">
      <div className="mx-auto flex max-w-[1600px] flex-col gap-8">
        <div className="space-y-2 border-b border-slate-900 pb-8">
          <h1 className="text-4xl font-black uppercase italic tracking-tight text-white">Thesis Tracker</h1>
          <p className="max-w-3xl text-sm text-slate-400">
            Forecast cards frozen before each print — the whisper and the money flow recorded as
            separate signals, graded separately once the print lands. A card can never be edited
            after it freezes; a correction is a new card that supersedes it.
          </p>
        </div>

        <Card className="border-slate-800 bg-slate-900/40">
          <CardHeader>
            <CardTitle className="text-lg text-white">Forecast cards</CardTitle>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="flex items-center gap-2 py-8 text-slate-400">
                <Loader2 className="h-4 w-4 animate-spin" /> Loading cards…
              </div>
            ) : error ? (
              <div className="flex items-center gap-2 py-8 text-red-300">
                <AlertTriangle className="h-4 w-4" /> {error}
              </div>
            ) : cards.length === 0 ? (
              <p className="py-8 text-sm text-slate-400">
                No forecast cards yet. Cards are frozen through the machine API before a covered
                name prints; a print with no card is a coverage failure and is logged as one.
              </p>
            ) : (
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
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
