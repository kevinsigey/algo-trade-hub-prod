import { Link } from "react-router-dom";

import { chipHeadline, chipJudgeText, type VerdictChip as Chip } from "@/lib/decisions";

/**
 * The per-name verdict element (Batch 2): verdict, confidence, one-line
 * dissent, judge identity, and a link to the full decision view on the
 * Guidance page. Rendered on BOTH pages wherever a name appears — the
 * Guidance band tables and the Screening results — so the judgment sits
 * with the name, not in a debates corner. A name with no rendered
 * verdict gets the honest absence line, never a placeholder verdict.
 */
export function VerdictChipLine({ chip, ticker }: { chip: Chip | undefined; ticker: string }) {
  if (!chip) {
    return (
      <span data-testid={`verdict-chip-${ticker}`} className="block text-xs text-slate-500">
        No debate verdict yet
      </span>
    );
  }
  return (
    <span data-testid={`verdict-chip-${ticker}`} className="block text-xs">
      <span className="font-medium text-violet-300">Debate: {chipHeadline(chip)}</span>
      {chip.dissent && (
        <span className="block text-slate-400">Dissent: {chip.dissent}</span>
      )}
      <span className="block text-slate-500">
        {chipJudgeText(chip)} ·{" "}
        <Link to={`/valuation?decision=${encodeURIComponent(ticker)}`}
              className="text-slate-300 underline decoration-slate-600 hover:text-white">
          full decision view
        </Link>
      </span>
    </span>
  );
}
