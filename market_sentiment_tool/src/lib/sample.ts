/**
 * The site-wide minimum-sample display rule.
 *
 * Below this many observations, a measured number is labelled "Too early to say" rather than
 * praised, blamed, or read as a verdict. This is a presentation rule only: it never changes a
 * server verdict, a gate, or the underlying measurement.
 */
export const EARLY_N = 30;

export function isEarlySample(count: number | null | undefined): boolean {
  return typeof count !== "number" || !Number.isFinite(count) || count < EARLY_N;
}
