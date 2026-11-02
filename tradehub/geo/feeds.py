"""Chokepoint feed fetchers + parsers (all free; endpoints verified against the
providers' own docs in the 2026-11-02 inventory). Parsers are pure functions
over payloads so they test without the network; fetchers are thin.

Health discipline (the plan's hard rule): a feed that fails, 404s, or returns
nothing parseable raises FeedDown, and the snapshot writer records the metric
as UNKNOWN -- never as zero. An empty result from a WORKING feed (zero quakes
in 24h) is a real zero and parses fine.
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta

import httpx

from tradehub.geo.regions import Region, inside

UA = {"User-Agent": "algo-trade-hub chokepoints (personal research)"}


class FeedDown(Exception):
    """The feed did not answer usefully; the metric is unknown, not zero."""


def _get(url: str, *, timeout: float = 20.0) -> httpx.Response:
    try:
        r = httpx.get(url, headers=UA, timeout=timeout, follow_redirects=True)
    except httpx.HTTPError as exc:
        raise FeedDown(f"{url.split('/')[2]}: {exc.__class__.__name__}") from exc
    if r.status_code != 200:
        raise FeedDown(f"{url.split('/')[2]}: HTTP {r.status_code}")
    return r


def _get_json(url: str) -> dict:
    r = _get(url)
    try:
        return r.json()
    except ValueError as exc:
        raise FeedDown(f"{url.split('/')[2]}: not JSON") from exc


# ── adsb.lol: military aircraft + the DIY intraday jamming share ─────────────

# ADS-B type codes (the `t` field). Small, explicit tables -- a type we do not
# recognise is "other", never guessed into a bucket.
TANKER_TYPES = {"K35R", "K35E", "KC10", "K46", "KC46", "KC30", "KC76", "KC97", "K135"}
ISR_TYPES = {"R135", "RC35", "U2", "E3TF", "E3CF", "E8", "P8", "P3", "EP3", "RQ4", "RQ1",
             "MQ9", "MQ1", "E6", "RC12", "MC12", "WC135"}


def classify_mil(ac_type: str | None) -> str:
    t = (ac_type or "").upper()
    if t in TANKER_TYPES:
        return "tanker"
    if t in ISR_TYPES:
        return "isr"
    return "other"


def parse_mil(payload: dict, region: Region) -> dict:
    rows = payload.get("ac")
    if rows is None:
        raise FeedDown("adsb.lol /v2/mil: no 'ac' list")
    counts = {"tanker": 0, "isr": 0, "other": 0}
    detail = []
    for a in rows:
        lat, lon = a.get("lat"), a.get("lon")
        if lat is None or lon is None or not inside(region.bbox, float(lat), float(lon)):
            continue
        kind = classify_mil(a.get("t"))
        counts[kind] += 1
        detail.append({"callsign": (a.get("flight") or "").strip(), "type": a.get("t"),
                       "kind": kind, "lat": float(lat), "lon": float(lon)})
    return {"mil_total": sum(counts.values()), "mil_tanker": counts["tanker"],
            "mil_isr": counts["isr"], "mil_other": counts["other"], "aircraft": detail}


def mil_air(region: Region) -> dict:
    return parse_mil(_get_json("https://api.adsb.lol/v2/mil"), region)


def parse_jamming_point(payload: dict) -> dict:
    """DIY intraday jamming index: the share of aircraft in the point query
    reporting NACp < 8 (GPSJam's 'bad' band), over those reporting any NACp."""
    rows = payload.get("ac")
    if rows is None:
        raise FeedDown("adsb.lol point: no 'ac' list")
    good = bad = 0
    for a in rows:
        nac = a.get("nac_p")
        if nac is None:
            continue
        if int(nac) < 8:
            bad += 1
        else:
            good += 1
    if good + bad == 0:
        raise FeedDown("adsb.lol point: no NACp reports in range")
    return {"jamming_intraday": bad / (good + bad), "nac_good": good, "nac_bad": bad}


def jamming_intraday(region: Region) -> dict:
    lat = (region.bbox[0] + region.bbox[2]) / 2
    lon = (region.bbox[1] + region.bbox[3]) / 2
    return parse_jamming_point(_get_json(f"https://api.adsb.lol/v2/point/{lat}/{lon}/250"))


# ── GPSJam: the daily index over the region's H3 cells ───────────────────────

def parse_gpsjam(csv_text: str, region: Region) -> dict:
    good = bad = seen = 0
    for row in csv.DictReader(io.StringIO(csv_text)):
        if row.get("hex") not in region.gpsjam_hexes:
            continue
        seen += 1
        good += int(row.get("count_good_aircraft") or 0)
        bad += int(row.get("count_bad_aircraft") or 0)
    if seen == 0 or good + bad == 0:
        raise FeedDown("gpsjam: no region hexes in the daily file")
    return {"jamming_daily": bad / (good + bad), "hexes": seen, "nac_good": good, "nac_bad": bad}


def gpsjam(region: Region, *, today: date) -> dict:
    # Published ~04:00 UTC for the prior day; fall back one more day before
    # calling it down.
    for back in (1, 2):
        day = today - timedelta(days=back)
        try:
            return {**parse_gpsjam(_get(f"https://gpsjam.org/data/{day.isoformat()}-h3_4.csv").text, region),
                    "for_date": day.isoformat()}
        except FeedDown:
            continue
    raise FeedDown("gpsjam: no daily file for the last two days")


# ── USGS: earthquakes in the region box ──────────────────────────────────────

def parse_quakes(payload: dict) -> list[dict]:
    feats = payload.get("features")
    if feats is None:
        raise FeedDown("usgs: no 'features' list")
    out = []
    for f in feats:
        p, g = f.get("properties") or {}, (f.get("geometry") or {}).get("coordinates") or []
        if len(g) < 2:
            continue
        out.append({"id": f.get("id"), "mag": p.get("mag"), "place": p.get("place"),
                    "time": p.get("time"), "lon": g[0], "lat": g[1]})
    return out


def quakes(region: Region, *, since_iso: str) -> list[dict]:
    la0, lo0, la1, lo1 = region.quake_bbox
    url = ("https://earthquake.usgs.gov/fdsnws/event/1/query?format=geojson"
           f"&starttime={since_iso}&minmagnitude=4.5"
           f"&minlatitude={la0}&maxlatitude={la1}&minlongitude={lo0}&maxlongitude={lo1}")
    return parse_quakes(_get_json(url))


# ── NASA FIRMS: fire radiative power in the terminal footprints ──────────────

def parse_firms(csv_text: str, region: Region) -> dict:
    frp_terminals = frp_other = 0.0
    detections = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        try:
            lat, lon, frp = float(row["latitude"]), float(row["longitude"]), float(row.get("frp") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        terminal = next((name for name, box in region.terminals.items() if inside(box, lat, lon)), None)
        if terminal:
            frp_terminals += frp
            detections.append({"lat": lat, "lon": lon, "frp": frp, "terminal": terminal,
                               "acq_date": row.get("acq_date"), "acq_time": row.get("acq_time"),
                               "satellite": row.get("satellite")})
        else:
            frp_other += frp
    return {"frp_terminals": round(frp_terminals, 2), "frp_other": round(frp_other, 2),
            "terminal_detections": detections}


def firms(region: Region, *, key: str | None) -> dict:
    if not key:
        raise FeedDown("firms: no MAP_KEY configured yet")
    la0, lo0, la1, lo1 = region.bbox
    area = f"{lo0},{la0},{lo1},{la1}"
    merged = {"frp_terminals": 0.0, "frp_other": 0.0, "terminal_detections": []}
    for source in ("VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT"):  # SNPP ceased 2026-11-02
        url = f"https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{area}/1"
        part = parse_firms(_get(url).text, region)
        merged["frp_terminals"] += part["frp_terminals"]
        merged["frp_other"] += part["frp_other"]
        merged["terminal_detections"] += part["terminal_detections"]
    merged["frp_terminals"] = round(merged["frp_terminals"], 2)
    merged["frp_other"] = round(merged["frp_other"], 2)
    return merged
