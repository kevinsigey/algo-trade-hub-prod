/** What each chokepoint metric means for oil and commodities. Direct effects are well understood;
 * none of these is a proven trading signal, and the tag says which ones the oil model is testing. */

export type GeoGroup = "flow" | "risk" | "background";

export const GEO_GROUPS: { key: GeoGroup; title: string; note: string }[] = [
  { key: "flow", title: "Barrels moving", note: "A direct read on supply, when the feed can see the ships." },
  { key: "risk", title: "Chance of trouble", note: "Risk is up but supply hasn't changed: expect bigger swings with no clear direction." },
  { key: "background", title: "Background", note: "Weak link to prices. Useful as context." },
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
  /** The tanker counts can't be trusted: a 0 means the feed can't see, not that traffic stopped. */
  gap: boolean;
}

export function geoCoverage(vessels: { ship_type: number | null; in_gate: boolean }[]): GeoCoverage {
  const seen = vessels.length;
  const typed = vessels.filter((v) => v.ship_type != null).length;
  const inGate = vessels.filter((v) => v.in_gate).length;
  return { seen, typed, inGate, gap: inGate === 0 || typed < seen / 2 };
}
