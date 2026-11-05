/** Kalshi's taker fee rate — mirrors `TAKER_FEE_RATE` in tradehub/oil_live.py. */
const TAKER_FEE_RATE = 0.07;

/**
 * The highest price (in dollars) at which a contract with model probability
 * `prob` still breaks even after the quadratic taker fee: solves
 * prob − p − rate·p·(1−p) = 0. This is the "buy below" limit — pay more
 * than this and the fee eats the whole edge.
 */
export function buyBelowLimit(prob: number): number {
  const r = TAKER_FEE_RATE;
  const disc = Math.max(0, (1 + r) * (1 + r) - 4 * r * prob);
  return ((1 + r) - Math.sqrt(disc)) / (2 * r);
}

export const cents = (v: number) => `${(v * 100).toFixed(1).replace(/\.0$/, "")}c`;
