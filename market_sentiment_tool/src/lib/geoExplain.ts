/** What each chokepoint metric means for oil and commodities. Direct effects are well understood;
 * none of these is a proven trading signal, and the tag says which ones the oil model is testing. */

export type GeoGroup = "flow" | "risk" | "background";

export const GEO_GROUPS: { key: GeoGroup; title: string; note: string }[] = [
  { key: "risk", title: "Chance of trouble", note: "Risk is up but supply hasn't changed: expect bigger swings with no clear direction." },
  { key: "background", title: "Background", note: "Weak link to prices. Useful as context." },
  // Barrels moving LAST (Kevin, 2026-11-16): the flow read is the one the
  // dark Gulf feed most often leaves empty, so it no longer leads the page.
  { key: "flow", title: "Barrels moving", note: "A direct read on supply, when the feed can see the ships." },
];

export const IN_OIL_MODEL = new Set(["tankers_gate_entries_1h", "jamming_intraday", "mil_total"]);

const FLOW_DOWN = "Fewer tankers through means less supply getting out: Brent up more than WTI, plus diesel and Asian and European LNG.";

export const GEO_EXPLAIN: Record<string, { group: GeoGroup; effect: string }> = {
  tankers_gate_entries_1h: { group: "flow", effect: FLOW_DOWN },
  tankers_in_gate: { group: "flow", effect: FLOW_DOWN },
  tankers_in_region: { group: "flow", effect: "A falling count can mean ships are avoiding the Gulf, which tightens supply and raises freight costs." },
  anchored_tankers: { group: "flow", effect: "More ships waiting means later deliveries and higher freight and insurance costs." },
  mil_total: { group: "risk", effect: "A surge raises the odds of an incident. Oil's range widens; gold may catch a bid." },
  jamming_intraday: { group: "risk", effect: "Heavy jamming often accompanies military activity and makes shipping riskier and costlier to insure." },
  jamming_daily: { group: "risk", effect: "The slower daily view of jamming: a sustained rise matters more than one spike." },
  frp_terminals: { group: "risk", effect: "Heat at an export terminal could be a direct hit on supply, the strongest signal here if confirmed." },
  vessels_in_region: { group: "background", effect: "All ships the feed can see. It shows coverage more than oil traffic." },
  vessels_in_gate: { group: "background", effect: "All ships the feed can see inside the transit gate. Zero here is why the gate tanker counts read as not visible: the feed cannot see the gate at all." },
  vessels_typed: { group: "background", effect: "Ships whose type the feed knows. Tanker counts are only trusted when at least half the ships seen are typed." },
  frp_region_other: { group: "background", effect: "Heat away from terminals, often flaring or farm burning." },
  quakes_24h: { group: "background", effect: "Almost no link to prices unless one is close to a terminal." },
};

/** Today's reading against the metric's own median, in words. */
export function geoReading(deltaPct: number | null | undefined): string {
  if (deltaPct == null) return "No baseline yet.";
  if (deltaPct >= 25) return "Above normal.";
  if (deltaPct <= -25) return "Below normal.";
  return "Near normal.";
}

export interface GeoCoverage {
  seen: number;
  typed: number;
  inGate: number;
  /** Any coverage gap at all (the banner's verdict). */
  gap: boolean;
  /** The gate zone is blind: no vessel observed inside the gate, or typing too
   * thin to trust tanker counts. Gate counts then mean "can't see", not 0. */
  gateGap: boolean;
  /** The region picture is blind: nothing seen at all, or typing too thin.
   * Region-wide counts (tankers in region, anchored) are only masked then --
   * a region the feed demonstrably sees reports its real zeros. */
  regionGap: boolean;
}

export function geoCoverage(
  vessels: { ship_type: number | null; in_gate: boolean }[],
  metrics?: { metric: string; value: number | null }[],
): GeoCoverage {
  let seen = vessels.length;
  let typed = vessels.filter((v) => v.ship_type != null).length;
  let inGate = vessels.filter((v) => v.in_gate).length;
  // The snapshot's exact coverage counts, when the view carries them: the
  // vessel list the API serves is capped (250, tankers first), so counts
  // taken from it can be biased enough to hide a gap. The stored metrics
  // are the whole picture. All three ride together in a batch, so the
  // fallback is all-or-nothing, mirroring the backend's ais_coverage.
  const exact = new Map((metrics ?? []).map((m) => [m.metric, m.value]));
  const seenExact = exact.get("vessels_in_region");
  const typedExact = exact.get("vessels_typed");
  const inGateExact = exact.get("vessels_in_gate");
  if (seenExact != null && typedExact != null && inGateExact != null) {
    seen = seenExact;
    typed = typedExact;
    inGate = inGateExact;
  }
  const thin = typed < seen / 2;
  const gateGap = inGate === 0 || thin;
  const regionGap = seen === 0 || thin;
  return { seen, typed, inGate, gateGap, regionGap, gap: gateGap || regionGap };
}
