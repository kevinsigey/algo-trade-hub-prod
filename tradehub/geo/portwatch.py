"""IMF PortWatch daily chokepoint transits: the real ship-flow series
behind the chokepoints monitor (handover item 5, 2026-11-03).

PortWatch (IMF / UN Global Platform) publishes daily transit calls for
28 chokepoints back to 2019 -- tanker and total counts plus tonnage --
from the same AIS the hub watches live, aggregated by people who count
properly. Our own gate counter sits at a zero median and cannot signal;
this series can. Three honest caveats ride with the numbers wherever
they show: the data updates WEEKLY with roughly a week to ten days of
lag (the lag is printed, never hidden); counts are AIS-visible transits,
a floor rather than a total (dark vessels are invisible to it); and the
ArcGIS endpoint is flaky -- intermittent 400 'Invalid URL' responses --
so fetching retries with backoff and the reader serves the last good
pull, stamped with its as-of date.

Storage follows the geo pattern: a daily job (scripts/portwatch_pull.py)
writes /cache/chokepoints/portwatch.json; this module reads it fail-soft.
"""
from __future__ import annotations

import json
import os
import statistics
import time
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

BASE = ("https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/"
        "Daily_Chokepoints_Data/FeatureServer/0")
FIELDS = ("date,n_total,n_tanker,n_cargo,n_container,n_dry_bulk,n_general_cargo,"
          "n_roro,capacity,capacity_tanker")
KEEP_DAYS = 400
PORTID_BY_SLUG = {"hormuz": "chokepoint6"}
DEFAULT_PATH = "/cache/chokepoints/portwatch.json"


class PortWatchError(RuntimeError):
    """The endpoint never answered cleanly -- the caller keeps the last good pull."""


def _parse_day(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=UTC).date().isoformat()
    text = str(value)[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def parse_features(body: dict) -> list[dict]:
    """ArcGIS query body -> rows sorted by date. An error body (the flaky
    400) parses as no rows; the fetcher treats it as a failed attempt."""
    if not isinstance(body, dict) or "error" in body:
        return []
    out = []
    for feature in body.get("features") or []:
        attrs = feature.get("attributes") or {}
        day = _parse_day(attrs.get("date"))
        if day is None:
            continue
        row = {"date": day}
        for field in FIELDS.split(",")[1:]:
            row[field] = attrs.get(field)
        out.append(row)
    out.sort(key=lambda r: r["date"])
    return out


def _default_get(params: dict) -> dict:
    url = BASE + "/query?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=45) as response:
        return json.loads(response.read())


def fetch_series(portid: str, *, get=None, tries: int = 6, page: int = 2000,
                 sleep=time.sleep) -> list[dict]:
    """The full daily series for one chokepoint, paged, with per-page
    retries -- the endpoint fails intermittently, not permanently."""
    get = get or _default_get
    rows: list[dict] = []
    offset = 0
    while True:
        params = {"where": f"portid='{portid}'", "outFields": FIELDS,
                  "orderByFields": "date ASC", "resultOffset": offset,
                  "resultRecordCount": page, "f": "json"}
        body = None
        for attempt in range(tries):
            try:
                got = get(params)
                if isinstance(got, dict) and "error" not in got:
                    body = got
                    break
            except Exception:  # noqa: BLE001 -- any transport failure retries the same way
                pass
            sleep(min(30.0, 2.0 ** attempt))
        if body is None:
            raise PortWatchError(f"PortWatch never answered for {portid}")
        rows.extend(parse_features(body))
        if not body.get("exceededTransferLimit"):
            return rows
        offset += page


def fetch_inventory(*, get=None, tries: int = 6, sleep=time.sleep) -> dict[str, str]:
    """portid -> portname for every chokepoint in the dataset."""
    get = get or _default_get
    params = {"where": "1=1", "outFields": "portid,portname",
              "groupByFieldsForStatistics": "portid,portname",
              "outStatistics": json.dumps([{"statisticType": "count",
                                            "onStatisticField": "ObjectId",
                                            "outStatisticFieldName": "n"}]),
              "f": "json"}
    for attempt in range(tries):
        try:
            body = get(params)
            if isinstance(body, dict) and "error" not in body:
                out = {}
                for feature in body.get("features") or []:
                    attrs = feature.get("attributes") or {}
                    if attrs.get("portid"):
                        out[attrs["portid"]] = attrs.get("portname") or attrs["portid"]
                if out:
                    return out
        except Exception:  # noqa: BLE001
            pass
        sleep(min(30.0, 2.0 ** attempt))
    raise PortWatchError("PortWatch inventory never answered")


KNOWN_NAMES = {"chokepoint6": "Strait of Hormuz"}


def probe_inventory(*, get=None, tries: int = 3, sleep=time.sleep,
                    candidates=range(1, 41)) -> dict[str, str]:
    """Fallback discovery when the grouped inventory query fails (it is
    the flaky endpoint's most expensive call): a light count probe per
    candidate id, then one row for the name. Ids with no rows are not
    chokepoints in this dataset."""
    get = get or _default_get
    out: dict[str, str] = {}
    for n in candidates:
        pid = f"chokepoint{n}"
        count = None
        for attempt in range(tries):
            try:
                body = get({"where": f"portid='{pid}'", "returnCountOnly": "true", "f": "json"})
                if isinstance(body, dict) and "error" not in body:
                    count = body.get("count")
                    break
            except Exception:  # noqa: BLE001
                pass
            sleep(min(10.0, 2.0 ** attempt))
        if not count:
            continue
        name = KNOWN_NAMES.get(pid, pid)
        try:
            body = get({"where": f"portid='{pid}'", "outFields": "portname",
                        "resultRecordCount": 1, "f": "json"})
            feats = (body or {}).get("features") or []
            if feats:
                name = feats[0]["attributes"].get("portname") or name
        except Exception:  # noqa: BLE001 -- the id alone still pulls fine
            pass
        out[pid] = name
    return out


def flow_summary(rows: list[dict], *, today: date) -> dict | None:
    """The read model: latest transit counts against the series' own
    trailing baseline -- the 30 observations before the latest 7, per the
    plan's baseline rule -- with the publication lag stated. Needs the
    latest 7 plus at least 7 before them for a baseline; with less, the
    baseline is None, named rather than invented."""
    clean = sorted((r for r in rows if r.get("date")), key=lambda r: r["date"])
    if not clean:
        return None
    latest = clean[-1]
    as_of = date.fromisoformat(latest["date"])
    last7 = clean[-7:]

    def mean7(field: str) -> float | None:
        vals = [float(r[field]) for r in last7 if r.get(field) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    prior = clean[:-7][-30:]
    prior_vals = [float(r["n_tanker"]) for r in prior if r.get("n_tanker") is not None]
    baseline = round(statistics.median(prior_vals), 2) if len(prior_vals) >= 7 else None
    tanker_7d = mean7("n_tanker")
    delta = (round((tanker_7d / baseline - 1) * 100, 1)
             if baseline not in (None, 0) and tanker_7d is not None else None)

    # Year-ago baseline: mean of n_tanker over [as_of - 365 - 29, as_of - 365] inclusive
    year_ago_start = (as_of - timedelta(days=365 + 29)).isoformat()
    year_ago_end = (as_of - timedelta(days=365)).isoformat()
    year_ago_rows = [r for r in clean if year_ago_start <= r["date"] <= year_ago_end]
    year_ago_vals = [float(r["n_tanker"]) for r in year_ago_rows if r.get("n_tanker") is not None]
    tanker_year_ago = round(sum(year_ago_vals) / len(year_ago_vals), 1) if len(year_ago_vals) >= 7 else None
    tanker_year_ago_delta_pct = (
        round((tanker_7d / tanker_year_ago - 1) * 100, 1)
        if tanker_year_ago not in (None, 0) and tanker_7d is not None
        else None
    )

    return {"source": "IMF PortWatch", "as_of": latest["date"],
            "lag_days": (today - as_of).days,
            "n_tanker_latest": latest.get("n_tanker"), "n_total_latest": latest.get("n_total"),
            "capacity_tanker_latest": latest.get("capacity_tanker"),
            "n_tanker_7d": tanker_7d, "n_total_7d": mean7("n_total"),
            "capacity_tanker_7d": mean7("capacity_tanker"),
            "tanker_baseline_30d": baseline, "tanker_delta_pct": delta,
            "baseline_n": len(prior_vals),
            "tanker_year_ago": tanker_year_ago,
            "tanker_year_ago_delta_pct": tanker_year_ago_delta_pct,
            "recent": [{"date": r["date"], "n_tanker": r.get("n_tanker"),
                        "n_total": r.get("n_total")} for r in clean[-14:]]}


def store_path() -> Path:
    return Path(os.environ.get("GEO_PORTWATCH", DEFAULT_PATH))


def load_flow(slug: str, *, today: date | None = None) -> dict | None:
    """The region's flow summary from the last good pull. Fail-soft: a
    missing or corrupt file, or an unmapped region, reads as no flow --
    the panel is additive, never an error."""
    portid = PORTID_BY_SLUG.get(slug)
    if portid is None:
        return None
    try:
        payload = json.loads(store_path().read_text(encoding="utf-8"))
        entry = (payload.get("series") or {}).get(portid) or {}
        out = flow_summary(entry.get("rows") or [], today=today or datetime.now(UTC).date())
        if out is None:
            return None
        out["name"] = entry.get("name")
        out["pulled_at"] = payload.get("pulled_at")
        return out
    except Exception:  # noqa: BLE001
        return None


def trim(rows: list[dict], *, keep_days: int = KEEP_DAYS) -> list[dict]:
    if not rows:
        return rows
    last = date.fromisoformat(max(r["date"] for r in rows))
    cutoff = (last - timedelta(days=keep_days)).isoformat()
    return [r for r in rows if r["date"] >= cutoff]
