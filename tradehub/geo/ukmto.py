"""UKMTO incident layer for the chokepoints monitor (Kevin's Hormuz
build, 2026-11-14): the reported-incident feed the AIS picture cannot
see -- mines, projectiles and boardings make no heat signature and the
free AIS feed is dark in the strait, so the monitor's incident record
comes from the official reporting channel instead.

Source, verified 2026-11-14: the same JSON API UKMTO's own Recent
Incidents map consumes, served from the Royal Navy's Sitecore host --
GET https://sccd.royalnavy.mod.uk/api/ukmto/all (no key; the public
ukmto.org pages are a JS shell and their direct PDF media URLs are not
enumerable, so this API is the machine-readable official route). Two
honest limits ride with the data wherever it shows: the API is a
rolling window (about six weeks when verified: 61 incidents, 43 of
them in the Strait of Hormuz), not an archive; and UKMTO only lists
incidents reported to it and verified -- a floor, not a total, the
same caveat as PortWatch. JMIC advisory PDFs (the threat assessments)
sit behind a product-folder API whose parameters are not public, so
this layer carries UKMTO incident reports only; no JMIC threat level
is shown rather than an invented one.

Storage follows the PortWatch pattern: a pull job
(scripts/ukmto_pull.py) writes /cache/chokepoints/ukmto.json; this
module reads it fail-soft and keeps the Hormuz-relevant incidents --
place 'Strait of Hormuz' or coordinates inside the region box.
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime
from pathlib import Path

API_URL = "https://sccd.royalnavy.mod.uk/api/ukmto/all"
SOURCE_URL = "https://www.ukmto.org/recent-incidents"
DEFAULT_PATH = "/cache/chokepoints/ukmto.json"
MAX_INCIDENTS = 20          # the panel shows the newest few weeks, not a ledger
DESCRIPTION_CHARS = 300


class UkmtoError(RuntimeError):
    """The API never answered cleanly -- the caller keeps the last good pull."""


def _description(text) -> str:
    """The narrative, whitespace-collapsed and trimmed to a panel-sized
    excerpt at a word boundary."""
    clean = " ".join(str(text or "").split())
    if len(clean) <= DESCRIPTION_CHARS:
        return clean
    return clean[:DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…"


def _ref(row: dict) -> str | None:
    number = row.get("incidentNumber")
    stamp = str(row.get("utcDateOfIncident") or "")
    if number is None or len(stamp) < 4:
        return None
    return f"{row.get('incidentIssuer') or 'UKMTO'} {number}-{stamp[2:4]}"


def parse_incidents(body) -> list[dict]:
    """The API's rows -> normalized incidents, newest first. A non-list
    body parses as no rows; a row without a usable reference or incident
    date is skipped, never repaired."""
    if not isinstance(body, list):
        return []
    out = []
    for row in body:
        if not isinstance(row, dict):
            continue
        ref = _ref(row)
        occurred = str(row.get("utcDateOfIncident") or "")
        if ref is None or len(occurred) < 10:
            continue
        out.append({
            "ref": ref,
            "date": occurred[:10],
            "occurred_at": occurred,
            "type": row.get("incidentTypeName"),
            "place": row.get("place"),
            "lat": row.get("locationLatitude"),
            "lon": row.get("locationLongitude"),
            "vessel_type": (str(row.get("vesselType") or "").strip() or None),
            "description": _description(row.get("otherDetails")),
            "url": SOURCE_URL,
        })
    out.sort(key=lambda r: r["occurred_at"], reverse=True)
    return out


def _default_get(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "tradehub-geo-pull"})
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.loads(response.read())


def fetch_incidents(*, get=None, tries: int = 3, sleep=time.sleep) -> list[dict]:
    """The API's current rolling window, parsed. Transport and shape
    failures retry, then raise -- the pull keeps its last good file. A
    valid EMPTY list is an answer, not a failure: the window really is
    empty, the pull writes it, and the panel clears instead of showing
    stale incidents forever. A non-list body, or a non-empty list whose
    rows all fail parsing, is a shape failure and retries like the rest."""
    get = get or _default_get
    for attempt in range(tries):
        try:
            body = get(API_URL)
            if isinstance(body, list) and not body:
                return []
            rows = parse_incidents(body)
            if rows:
                return rows
        except Exception:  # noqa: BLE001 -- any failure retries the same way
            pass
        sleep(min(10.0, 2.0 ** attempt))
    raise UkmtoError("UKMTO incident API never answered cleanly")


def store_path() -> Path:
    return Path(os.environ.get("GEO_UKMTO", DEFAULT_PATH))


def _relevant(row: dict, region) -> bool:
    if row.get("place") == "Strait of Hormuz":
        return True
    lat, lon = row.get("lat"), row.get("lon")
    if lat is None or lon is None:
        return False
    from tradehub.geo.regions import inside

    return inside(region.bbox, float(lat), float(lon))


def load_incidents(slug: str, *, now: datetime | None = None) -> dict | None:
    """The region's incidents from the last good pull: newest first,
    capped, with the pull stamp and the newest incident's date as the
    as-of. Fail-soft: a missing or corrupt file, or an unmapped region,
    reads as no incidents -- the panel is additive, never an error."""
    from tradehub.geo.regions import REGIONS

    region = REGIONS.get(slug)
    if region is None:
        return None
    try:
        payload = json.loads(store_path().read_text(encoding="utf-8"))
        rows = [r for r in payload.get("incidents") or [] if _relevant(r, region)]
        if not rows:
            return None
        rows.sort(key=lambda r: r["occurred_at"], reverse=True)
        return {"source": "UKMTO", "source_url": SOURCE_URL,
                "pulled_at": payload.get("pulled_at"),
                "as_of": rows[0]["date"], "count": len(rows),
                "incidents": rows[:MAX_INCIDENTS]}
    except Exception:  # noqa: BLE001
        return None
