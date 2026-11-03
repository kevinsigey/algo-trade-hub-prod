// Slippy-map math for the Chokepoints map (pure, so it tests without a
// DOM): world-pixel projection at a zoom, the zoom that fits a bbox into
// a width, and the tile range covering the projected bbox. Boxes in the
// geo API are (lat_min, lon_min, lat_max, lon_max).
export type GeoBox = [number, number, number, number];

const TILE = 256;

export function worldPx(lon: number, lat: number, zoom: number): { x: number; y: number } {
  const scale = TILE * 2 ** zoom;
  const x = ((lon + 180) / 360) * scale;
  const rad = (lat * Math.PI) / 180;
  const y = ((1 - Math.log(Math.tan(rad) + 1 / Math.cos(rad)) / Math.PI) / 2) * scale;
  return { x, y };
}

export function zoomForWidth(bbox: GeoBox, widthPx: number): number {
  for (let z = 12; z >= 3; z--) {
    const nw = worldPx(bbox[1], bbox[2], z);
    const se = worldPx(bbox[3], bbox[0], z);
    if (se.x - nw.x <= widthPx) return z;
  }
  return 3;
}

export interface MapFrame {
  zoom: number;
  width: number;
  height: number;
  tiles: { x: number; y: number; left: number; top: number }[];
  project: (lon: number, lat: number) => { x: number; y: number };
  boxRect: (box: GeoBox) => { left: number; top: number; width: number; height: number };
}

export function frameFor(bbox: GeoBox, widthPx: number): MapFrame {
  const zoom = zoomForWidth(bbox, widthPx);
  const nw = worldPx(bbox[1], bbox[2], zoom);
  const se = worldPx(bbox[3], bbox[0], zoom);
  const width = Math.round(se.x - nw.x);
  const height = Math.round(se.y - nw.y);
  const tiles: MapFrame["tiles"] = [];
  const x0 = Math.floor(nw.x / TILE), x1 = Math.floor(se.x / TILE);
  const y0 = Math.floor(nw.y / TILE), y1 = Math.floor(se.y / TILE);
  for (let x = x0; x <= x1; x++) {
    for (let y = y0; y <= y1; y++) {
      tiles.push({ x, y, left: x * TILE - nw.x, top: y * TILE - nw.y });
    }
  }
  const project = (lon: number, lat: number) => {
    const p = worldPx(lon, lat, zoom);
    return { x: p.x - nw.x, y: p.y - nw.y };
  };
  const boxRect = (box: GeoBox) => {
    const a = project(box[1], box[2]);
    const b = project(box[3], box[0]);
    return { left: a.x, top: a.y, width: b.x - a.x, height: b.y - a.y };
  };
  return { zoom, width, height, tiles, project, boxRect };
}

export function tileUrl(x: number, y: number, zoom: number): string {
  // CARTO dark basemap (free with attribution): matches the hub's dark UI.
  return `https://basemaps.cartocdn.com/dark_all/${zoom}/${x}/${y}.png`;
}
