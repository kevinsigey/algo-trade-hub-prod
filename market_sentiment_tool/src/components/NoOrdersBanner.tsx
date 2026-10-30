/**
 * The site-wide line (Trading HQ spec §3): the hub may place PAPER orders for ideas Kevin switches on, never real ones.
 * A banner, not a footnote: it sits above every page so no screenshot of a number can lose it.
 */
export const NO_ORDERS_TEXT = "Paper orders only — never real money.";

export function NoOrdersBanner() {
  return (
    <div
      role="note"
      className="border-b border-slate-800 bg-slate-900/70 px-4 py-1.5 text-center text-[11px] uppercase tracking-wider text-slate-400"
    >
      {NO_ORDERS_TEXT}
    </div>
  );
}
