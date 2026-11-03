import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { frameFor, tileLabelUrl, tileUrl, type GeoBox } from "@/lib/geoMap";
import { GEO_EXPLAIN, GEO_GROUPS, geoCoverage, geoReading, IN_OIL_MODEL } from "@/lib/geoExplain";
import { getJson } from "@/lib/getJson";

// The Chokepoints monitor on the Oil page (approved plan, Nov 2 2026):
// a 2D map over Esri satellite tiles with the region's gate, anchorages and
// terminals drawn from the read API's own geometry -- and, since Kevin's
// Nov 3 2026 ask, the actual ships and military aircraft plotted big and
// clear from their stored positions, with visual counters (baseline bars,
// not just text) under the map. Ships come from the AIS consumer's state
// file: when that feed's health is stale the markers render dimmed and
// dashed -- last-known, never dressed as live.

interface GeoMetric {
  feed: string; metric: string; value: number | null; health: string | null;
  baseline: number | null; delta_pct: number | null; baseline_n: number;
}

interface GeoVessel {
  mmsi: string; name: string | null; ship_type: number | null; tanker: boolean;
  lat: number; lon: number; sog: number | null; in_gate: boolean; last_seen: string | null;
}

interface GeoAircraft {
  callsign: string; type: string | null; kind: string; lat: number; lon: number;
}

interface GeoView {
  region: string; name: string; at: string | null;
  feeds: Record<string, string>;
  metrics: GeoMetric[];
  geometry: { bbox: GeoBox; gate: GeoBox; anchorages: Record<string, GeoBox>; terminals: Record<string, GeoBox> };
  vessels?: GeoVessel[];
  vessels_as_of?: string | null;
  aircraft?: GeoAircraft[];
}

const FEED_LABEL: Record<string, string> = {
  ais: "Ships (AIS)", adsb: "Military flights", adsb_jamming: "GPS jamming (live)",
  gpsjam: "GPS jamming (daily)", usgs: "Earthquakes", firms: "Terminal fires (FIRMS)",
};

const METRIC_LABEL: Record<string, string> = {
  tankers_in_gate: "Tankers in the gate", tankers_gate_entries_1h: "Gate entries (1h)",
  anchored_tankers: "Anchored tankers", tankers_in_region: "Tankers in region",
  vessels_in_region: "Vessels tracked", mil_total: "Military aircraft",
  jamming_intraday: "Jamming share (live)", frp_region_other: "Fire power (other)",
  quakes_24h: "Quakes 24h", frp_terminals: "Fire power at terminals", jamming_daily: "Jamming share (daily)",
};

// The counters lead with these, in this order; anything else the API grows
// still renders after them. mil_tanker / mil_isr fold into the mil tile.
const COUNTER_ORDER = [
  "vessels_in_region", "tankers_in_region", "anchored_tankers", "tankers_in_gate",
  "tankers_gate_entries_1h", "mil_total", "quakes_24h", "jamming_intraday",
];
const FOLDED = new Set(["mil_tanker", "mil_isr"]);

const HEALTH_DOT: Record<string, string> = {
  live: "bg-emerald-400", stale: "bg-amber-400", unknown: "bg-slate-500",
};

type Layer = "gate" | "anchorages" | "terminals" | "ships" | "aircraft";

function ShipGlyph() {
  return (
    <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="none" stroke="currentColor"
         strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M4 15.5 5.6 20h12.8L20 15.5" />
      <path d="M6.5 15.5v-3h11v3" />
      <path d="M12 12.5v-6" />
      <path d="M9 6.5h6" />
    </svg>
  );
}

function PlaneGlyph() {
  return (
    <svg viewBox="0 0 24 24" className="h-[16px] w-[16px]" fill="currentColor" aria-hidden="true">
      <path d="M21.5 15.5v-2l-8.5-5V3.2a1.2 1.2 0 0 0-2.4 0v5.3l-8.5 5v2l8.5-2.6v5l-2.3 1.7v1.5l3.5-1 3.5 1V19l-2.3-1.7v-5l8.5 2.6z" />
    </svg>
  );
}

export default function ChokepointsMap() {
  const [view, setView] = useState<GeoView | null>(null);
  const [layers, setLayers] = useState<Record<Layer, boolean>>(
    { gate: true, anchorages: true, terminals: false, ships: true, aircraft: true });

  useEffect(() => {
    // Defensive by design: this panel is additive to the Oil page, so a
    // malformed or missing payload renders nothing, never an exception.
    getJson<GeoView>("/api/geo/regions/hormuz")
      .then((v) => setView(v && v.geometry && Array.isArray(v.geometry.bbox) ? v : null))
      .catch(() => setView(null));
  }, []);

  const frame = useMemo(
    () => (view ? frameFor(view.geometry.bbox, 960) : null),
    [view],
  );
  const wrapRef = useRef<HTMLDivElement>(null);
  const [wrapW, setWrapW] = useState(0);
  useLayoutEffect(() => {
    const el = wrapRef.current;
    if (el) setWrapW(el.clientWidth);
  }, [frame]);

  if (!view || !frame) return null; // the monitor is additive: no data, no panel
  const scale = wrapW > 0 ? wrapW / frame.width : 1;

  const vessels = view.vessels ?? [];
  const aircraft = view.aircraft ?? [];
  const aisStale = view.feeds.ais === "stale";

  const toggle = (layer: Layer) => setLayers((s) => ({ ...s, [layer]: !s[layer] }));
  const layerLabel: Record<Layer, string> = {
    gate: "gate", anchorages: "anchorages", terminals: "terminals",
    ships: `ships (${vessels.length})`, aircraft: `aircraft (${aircraft.length})`,
  };
  const boxes: { label: string; box: GeoBox; cls: string }[] = [];
  if (layers.gate) boxes.push({ label: "Transit gate", box: view.geometry.gate, cls: "border-rose-400/80 bg-rose-400/10" });
  if (layers.anchorages) {
    for (const [name, box] of Object.entries(view.geometry.anchorages)) {
      boxes.push({ label: name, box, cls: "border-amber-300/70 bg-amber-300/10" });
    }
  }
  if (layers.terminals) {
    for (const [name, box] of Object.entries(view.geometry.terminals)) {
      boxes.push({ label: name, box, cls: "border-sky-300/70 bg-sky-300/10" });
    }
  }

  const byMetric = new Map(view.metrics.map((m) => [m.metric, m]));
  const counters = [
    ...COUNTER_ORDER.map((k) => byMetric.get(k)).filter((m): m is GeoMetric => !!m && m.value != null),
    ...view.metrics.filter((m) => m.value != null && !COUNTER_ORDER.includes(m.metric) && !FOLDED.has(m.metric)),
  ];
  const coverage = geoCoverage(vessels);
  const milTanker = byMetric.get("mil_tanker")?.value;
  const milIsr = byMetric.get("mil_isr")?.value;

  return (
    <section aria-label="Chokepoints monitor" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-xl font-semibold text-white">Strait of Hormuz — chokepoints monitor</h2>
        <span className="text-[12px] text-slate-500">
          Snapshot {view.at ? new Date(view.at).toLocaleString() : "—"} · values vs their trailing median
          {aisStale && view.vessels_as_of
            ? ` · ship positions last known as of ${new Date(view.vessels_as_of).toLocaleString()}`
            : ""}
        </span>
      </div>

      <div className="flex flex-wrap gap-2" role="group" aria-label="Map layers">
        {(Object.keys(layers) as Layer[]).map((layer) => (
          <button key={layer} type="button" onClick={() => toggle(layer)} aria-pressed={layers[layer]}
                  className={`rounded-full border px-3 py-1 text-[13px] capitalize ${layers[layer] ? "border-slate-400 text-white" : "border-slate-700 text-slate-500"}`}>
            {layerLabel[layer]}
          </button>
        ))}
        <span className="mx-1 hidden h-6 w-px bg-slate-700 sm:block" />
        {Object.entries(view.feeds).map(([feed, health]) => (
          <span key={feed} className="inline-flex items-center gap-1.5 rounded-full border border-slate-700 px-3 py-1 text-[13px] text-slate-300">
            <span className={`h-2 w-2 rounded-full ${HEALTH_DOT[health] ?? "bg-slate-500"}`} />
            {FEED_LABEL[feed] ?? feed}: {health}
          </span>
        ))}
      </div>

      <div ref={wrapRef} className="relative overflow-hidden rounded-lg border border-slate-700"
           style={{ width: "100%", maxWidth: frame.width, height: frame.height * scale }}>
        <div className="absolute inset-0" style={{ transform: `scale(${scale})`, transformOrigin: "top left" }}>
          <div className="relative" style={{ width: frame.width, height: frame.height }}>
            {frame.tiles.map((t) => (
              <img key={`${t.x}-${t.y}`} src={tileUrl(t.x, t.y, frame.zoom)} alt=""
                   className="absolute" style={{ left: t.left, top: t.top, width: 256, height: 256 }} />
            ))}
            {frame.tiles.map((t) => (
              <img key={`lbl-${t.x}-${t.y}`} src={tileLabelUrl(t.x, t.y, frame.zoom)} alt=""
                   className="absolute" style={{ left: t.left, top: t.top, width: 256, height: 256 }} />
            ))}
            {boxes.map((b) => {
              const r = frame.boxRect(b.box);
              return (
                <div key={b.label} className={`absolute border ${b.cls}`} title={b.label}
                     style={{ left: r.left, top: r.top, width: Math.max(r.width, 6), height: Math.max(r.height, 6) }}>
                  <span className="absolute left-0 top-full whitespace-nowrap text-[10px] text-slate-300">{b.label}</span>
                </div>
              );
            })}
            {layers.ships && vessels.map((v) => {
              const p = frame.project(v.lon, v.lat);
              const slow = v.sog !== null && v.sog < 1;
              const title = `${v.name ?? "Unknown vessel"} · ${v.tanker ? "Tanker" : "Vessel"}`
                + `${v.sog !== null ? ` · ${v.sog} kt` : ""}${v.in_gate ? " · in the gate" : ""}`
                + `${v.last_seen ? ` · seen ${new Date(v.last_seen).toLocaleString()}` : ""}`
                + `${aisStale ? " · last known (feed stale)" : ""}`;
              return (
                <div key={v.mmsi} title={title} aria-label={title}
                     className={`absolute flex h-[30px] w-[30px] items-center justify-center rounded-full border-2 backdrop-blur-[1px] ${
                       v.tanker
                         ? "border-amber-300 bg-amber-400/30 text-amber-100"
                         : "border-sky-300 bg-sky-400/25 text-sky-100"
                     } ${slow ? "ring-2 ring-white/40" : ""} ${aisStale ? "border-dashed opacity-60" : ""}`}
                     style={{ left: p.x - 15, top: p.y - 15 }}>
                  <ShipGlyph />
                </div>
              );
            })}
            {layers.aircraft && aircraft.map((a, i) => {
              const p = frame.project(a.lon, a.lat);
              const title = `${a.callsign || "Unknown aircraft"} · ${a.type ?? "type unknown"} ·${
                a.kind === "tanker" ? " tanker" : a.kind === "isr" ? " ISR" : " military"}`;
              return (
                <div key={`${a.callsign}-${i}`} title={title} aria-label={title}
                     className={`absolute flex h-[26px] w-[26px] items-center justify-center rounded-full border-2 ${
                       a.kind === "tanker"
                         ? "border-violet-300 bg-violet-400/30 text-violet-100"
                         : a.kind === "isr"
                           ? "border-cyan-300 bg-cyan-400/25 text-cyan-100"
                           : "border-slate-300 bg-slate-400/25 text-slate-100"
                     }`}
                     style={{ left: p.x - 13, top: p.y - 13 }}>
                  <PlaneGlyph />
                </div>
              );
            })}
          </div>
        </div>
        <span className="absolute bottom-1 right-2 text-[10px] text-slate-300">Imagery © Esri, Maxar, Earthstar Geographics</span>
      </div>

      {coverage.gap && (
        <p className="rounded-lg border border-amber-500/40 px-3 py-2 text-sm text-amber-200">
          Ship coverage is thin: {coverage.seen} ships seen, {coverage.inGate} in the transit gate, {coverage.typed} with a
          known type. Zero tankers here means the free feed can&apos;t see them, not that traffic stopped.
        </p>
      )}

      {GEO_GROUPS.map((group) => {
        const tiles = counters.filter((m) => (GEO_EXPLAIN[m.metric]?.group ?? "background") === group.key);
        if (tiles.length === 0) return null;
        return (
          <div key={group.key}>
            <h3 className="text-sm font-semibold text-slate-200">{group.title}</h3>
            <p className="text-xs text-slate-400">{group.note}</p>
            <div className="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
              {tiles.map((m) => {
                const isShare = m.metric.startsWith("jamming");
                const blind = coverage.gap && group.key === "flow";
                const display = m.value === null ? "—" : isShare ? `${Math.round(m.value * 100)}%` : `${m.value}`;
                const barPct = m.baseline && m.baseline > 0 && m.value !== null
                  ? Math.min(100, (m.value / m.baseline) * 100) : 0;
                const up = (m.delta_pct ?? 0) >= 0;
                return (
                  <div key={`${m.feed}-${m.metric}`} className="rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2.5">
                    <div className="flex items-center gap-1.5 text-[13px] text-slate-300">
                      {m.feed === "ais" ? <ShipGlyph /> : m.feed === "adsb" ? <PlaneGlyph /> : null}
                      {METRIC_LABEL[m.metric] ?? m.metric}
                    </div>
                    {blind ? (
                      <div className="mt-1 text-xl font-semibold text-amber-200">No coverage</div>
                    ) : (
                      <>
                        <div className="mt-1 flex items-baseline gap-2">
                          <span className="text-3xl font-bold leading-none text-white">{display}</span>
                          {m.delta_pct != null && (
                            <span className={`text-[13px] font-semibold ${up ? "text-amber-300" : "text-sky-300"}`}>
                              {up ? "▲" : "▼"} {`${m.delta_pct >= 0 ? "+" : ""}${m.delta_pct}% vs median ${m.baseline}`}
                            </span>
                          )}
                        </div>
                        <div className="mt-2 h-1.5 overflow-hidden rounded bg-slate-800" aria-hidden="true">
                          <div className={`h-full rounded ${up ? "bg-amber-400/80" : "bg-sky-400/80"}`}
                               style={{ width: `${barPct}%` }} />
                        </div>
                      </>
                    )}
                    {m.metric === "mil_total" && (milTanker != null || milIsr != null) && (
                      <div className="mt-1.5 text-[12px] text-slate-400">
                        Tankers {milTanker ?? "—"} · ISR {milIsr ?? "—"}
                      </div>
                    )}
                    <p className="mt-2 text-xs leading-snug text-slate-300">
                      {!blind && <span className="font-medium text-white">{geoReading(m.delta_pct)} </span>}
                      {GEO_EXPLAIN[m.metric]?.effect}
                    </p>
                    {IN_OIL_MODEL.has(m.metric) && (
                      <p className="mt-1 text-[11px] text-slate-400">In the oil model&apos;s test</p>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </section>
  );
}
