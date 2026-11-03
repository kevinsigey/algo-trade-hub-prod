import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { frameFor, tileUrl, type GeoBox } from "@/lib/geoMap";
import { getJson } from "@/lib/getJson";

// The Chokepoints monitor on the Oil page (approved plan, Nov 2 2026):
// a 2D map over free CARTO tiles with the region's gate, anchorages and
// terminals drawn from the read API's own geometry; filter chips per
// layer; feed-health chips; and the headline measures as deltas against
// their trailing medians. Values are deltas, not absolutes, per the plan.

interface GeoMetric {
  feed: string; metric: string; value: number | null; health: string | null;
  baseline: number | null; delta_pct: number | null; baseline_n: number;
}

interface GeoView {
  region: string; name: string; at: string | null;
  feeds: Record<string, string>;
  metrics: GeoMetric[];
  geometry: { bbox: GeoBox; gate: GeoBox; anchorages: Record<string, GeoBox>; terminals: Record<string, GeoBox> };
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
  quakes_24h: "Quakes 24h",
};

const HEALTH_DOT: Record<string, string> = {
  live: "bg-emerald-400", stale: "bg-amber-400", unknown: "bg-slate-500",
};

type Layer = "gate" | "anchorages" | "terminals";

export default function ChokepointsMap() {
  const [view, setView] = useState<GeoView | null>(null);
  const [layers, setLayers] = useState<Record<Layer, boolean>>({ gate: true, anchorages: true, terminals: false });

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

  const toggle = (layer: Layer) => setLayers((s) => ({ ...s, [layer]: !s[layer] }));
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
  const headline = view.metrics.filter((m) => m.value != null).slice(0, 8);

  return (
    <section aria-label="Chokepoints monitor" className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-xl font-semibold text-white">Strait of Hormuz — chokepoints monitor</h2>
        <span className="text-[12px] text-slate-500">
          Snapshot {view.at ? new Date(view.at).toLocaleString() : "—"} · values vs their trailing median
        </span>
      </div>

      <div className="flex flex-wrap gap-2" role="group" aria-label="Map layers">
        {(Object.keys(layers) as Layer[]).map((layer) => (
          <button key={layer} type="button" onClick={() => toggle(layer)} aria-pressed={layers[layer]}
                  className={`rounded-full border px-3 py-1 text-[13px] capitalize ${layers[layer] ? "border-slate-400 text-white" : "border-slate-700 text-slate-500"}`}>
            {layer}
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
            {boxes.map((b) => {
              const r = frame.boxRect(b.box);
              return (
                <div key={b.label} className={`absolute border ${b.cls}`} title={b.label}
                     style={{ left: r.left, top: r.top, width: Math.max(r.width, 6), height: Math.max(r.height, 6) }}>
                  <span className="absolute left-0 top-full whitespace-nowrap text-[10px] text-slate-300">{b.label}</span>
                </div>
              );
            })}
          </div>
        </div>
        <span className="absolute bottom-1 right-2 text-[10px] text-slate-400">© OpenStreetMap contributors © CARTO</span>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {headline.map((m) => (
          <div key={`${m.feed}-${m.metric}`} className="rounded-lg border border-slate-700 bg-slate-900/60 px-3 py-2">
            <div className="text-[12px] uppercase tracking-wide text-slate-400">{METRIC_LABEL[m.metric] ?? m.metric}</div>
            <div className="mt-0.5 flex items-baseline gap-2">
              <span className="text-xl font-semibold text-white">{m.value}</span>
              {m.delta_pct != null ? (
                <span className={m.delta_pct >= 0 ? "text-[13px] text-amber-300" : "text-[13px] text-sky-300"}>
                  {m.delta_pct >= 0 ? "+" : ""}{m.delta_pct}% vs median {m.baseline}
                </span>
              ) : (
                <span className="text-[13px] text-slate-500">no baseline yet</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
