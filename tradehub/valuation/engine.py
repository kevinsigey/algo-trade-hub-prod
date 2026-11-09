"""Deterministic fact-sheet + bands engine (valuation Spec v1, sections 1-2).

Pure functions, no I/O: the compute job (run.py) gathers inputs (guidance
records, peer multiple, price, EDGAR fundamentals) and this module turns them
into the fact sheet. Frozen method (implementation plan, Phase 0):

- Band metric is EPS. Anchor guide: eps_adjusted preferred, eps_gaap fallback;
  full-year periods only; latest recorded guide for the latest guided FY wins.
- Sanity guards reject recorder noise (recorded on the sheet, never silent).
- Bands: bull = guide high x M, base = guide mid x M, bear = guide low x
  0.90 (the frozen 10% haircut) x M, M = industry peer-group median forward P/E.
- Gap = (implied EPS - guide mid) / guide range width, in range widths.
- Baseline verdict = the zone the price sits in vs the bands (mirrored for
  shorts). Staleness suppresses the verdict, never the record.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

HAIRCUT = 0.90          # bear band: low-end guide x 0.90 (Kevin, frozen)
MIN_PEERS = 3           # peer multiple needs >= 3 valid members
PRICE_STALE_DAYS = 5
GUIDE_STALE_DAYS = 135
FUND_STALE_DAYS = 550

_QUARTER = re.compile(r"\bq[1-4]\b|[1-4]q\d{2}|quarter", re.IGNORECASE)
_YEAR = re.compile(r"(20\d{2})")
_FY_SIGNAL = re.compile(r"\bfy\d|\bfy\b|full year|fiscal|year ending|year ended",
                        re.IGNORECASE)


def _year_of(period: str) -> int | None:
    m = _YEAR.search(period or "")
    return int(m.group(1)) if m else None


def is_full_year_period(period: str, *, now: datetime | None = None) -> bool:
    """A period counts as a full-year guide only if it names a fiscal year
    (FY / full year / fiscal / year ending / bare year), carries no quarter
    token, and the year is in [now-1, now+2] — a bare far-future year (the
    DUK '2030' growth-range row) is not an annual EPS guide."""
    if not period or _QUARTER.search(period):
        return False
    year = _year_of(period)
    if year is None:
        return False
    now = now or datetime.now(timezone.utc)
    if not (now.year - 1 <= year <= now.year + 2):
        return False
    bare = period.strip() == str(year)
    return bool(bare or _FY_SIGNAL.search(period))


def period_key(period: str) -> str:
    """Normalized comparison key: FY<year> for year periods, else the raw
    string lowercased (quarterly periods keep their own keys)."""
    year = _year_of(period)
    if year is not None and not _QUARTER.search(period or ""):
        return f"FY{year}"
    return (period or "").strip().lower()


def _mid(low: float | None, high: float | None) -> float | None:
    if low is None:
        return None
    return low if high is None else (low + high) / 2.0


def _created(rec: dict) -> datetime:
    raw = rec.get("created_at") or ""
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _guards(rec: dict, fundamentals: dict) -> list[str]:
    """Sanity guards on one candidate anchor record. Returns rejection
    reasons (empty = passes). The recorder's noise is real (segment rows,
    zero ranges, growth ranges stored as EPS), so no silent drops."""
    reasons: list[str] = []
    low, high = rec.get("low"), rec.get("high")
    mid = _mid(low, high)
    if rec.get("unit") != "usd_per_share":
        reasons.append(f"unit {rec.get('unit')!r} is not usd_per_share")
    if low is None or low <= 0:
        reasons.append(f"low end {low!r} is not positive")
    if high is not None and low is not None and high < low:
        reasons.append(f"high {high} below low {low}")
    cons = rec.get("consensus")
    # consensus_period in the recorder is often a relative tag ('0y', '+1y'),
    # not a fiscal-year label: apply the check unless both sides parse to
    # fiscal years that provably differ.
    cons_year = _year_of(rec.get("consensus_period") or "")
    guide_year = _year_of(rec.get("period") or "")
    periods_compatible = (cons_year is None or guide_year is None
                          or cons_year == guide_year)
    if (cons and mid is not None and periods_compatible):
        ratio = mid / cons if cons > 0 else None
        if ratio is None or not (0.4 <= ratio <= 2.5):
            reasons.append(
                f"guide mid {mid:.2f} vs consensus {cons:.2f} outside "
                f"[0.4x, 2.5x] consensus band")
    trailing = (fundamentals.get("eps_diluted") or {}).get("value")
    if trailing and mid is not None:
        if not (0.3 * trailing <= mid <= 2.0 * trailing):
            reasons.append(
                f"guide mid {mid:.2f} vs trailing diluted EPS {trailing:.2f} "
                f"outside [0.3x, 2.0x] trailing band")
    return reasons


def _select_anchor(records: list[dict], fundamentals: dict,
                   now: datetime) -> tuple[dict | None, list[str], bool]:
    """Returns (anchor_record, guard_rejections, had_fy_candidates)."""
    rejections: list[str] = []
    for metric in ("eps_adjusted", "eps_gaap"):
        fy = [r for r in records
              if r.get("metric") == metric
              and is_full_year_period(r.get("period") or "", now=now)]
        if not fy:
            continue
        years = sorted({_year_of(r["period"]) for r in fy}, reverse=True)
        for year in years:
            cands = [r for r in fy if _year_of(r["period"]) == year]
            cands.sort(key=_created, reverse=True)
            for cand in cands:
                bad = _guards(cand, fundamentals)
                if not bad:
                    return cand, rejections, True
                rejections.extend(
                    f"{metric} {cand.get('period')}: {b}" for b in bad)
        return None, rejections, True
    return None, rejections, False


def _directions(records: list[dict]) -> dict:
    """Per metric: latest guide for its period vs the previous guide for the
    SAME period — raised / cut / held (midpoint move beyond +/-0.5%), or
    'first'. Note: segment-level rows share ticker+metric+period in the
    recorder and cannot be told apart; direction reads the recorded sequence
    as-is."""
    out: dict = {}
    by_metric: dict[str, list[dict]] = {}
    for r in records:
        by_metric.setdefault(r.get("metric"), []).append(r)
    for metric, rows in by_metric.items():
        groups: dict[str, list[dict]] = {}
        for r in rows:
            groups.setdefault(period_key(r.get("period") or ""), []).append(r)
        # the live period = the one holding the most recently recorded guide
        live_key = max(groups, key=lambda k: max(_created(r) for r in groups[k]))
        seq = sorted(groups[live_key], key=_created)
        latest = seq[-1]
        mid = _mid(latest.get("low"), latest.get("high"))
        entry = {"period": latest.get("period"), "mid": mid,
                 "recorded_at": latest.get("created_at")}
        if len(seq) < 2 or mid is None:
            entry["direction"] = "first"
        else:
            prev_mid = _mid(seq[-2].get("low"), seq[-2].get("high"))
            entry["prev_mid"] = prev_mid
            if prev_mid:
                chg = (mid - prev_mid) / abs(prev_mid)
                entry["direction"] = ("raised" if chg > 0.005
                                      else "cut" if chg < -0.005 else "held")
            else:
                entry["direction"] = "first"
        out[metric] = entry
    return out


def classify_zone(*, price: float, bands: dict, implied_eps: float,
                  guide_low: float, guide_high: float,
                  guide_mid: float) -> str:
    """The band-rule baseline verdict (mirrored for shorts): at/below bear the
    market prices in less than the haircut low end (strong buy zone); at/below
    base it prices in less than the guide mid; inside the bull band with the
    implied EPS still inside the guide it is neutral; above bull with the
    implied EPS above the guide it is short zone; above bull while the implied
    EPS still trails the guide mid is no-chase (rich price, cheap guide — do
    not chase either way)."""
    if price <= bands["bear"]:
        return "buy_zone_strong"
    if price <= bands["base"]:
        return "buy_zone"
    if price <= bands["bull"]:
        return "neutral" if guide_low <= implied_eps <= guide_high \
            else "short_zone"
    return "short_zone_strong" if implied_eps > guide_mid else "no_chase_long"


def _percentile(ticker: str, guided_peers: list[dict]) -> float | None:
    """Percentile of this name's guide-vs-consensus surprise among guided
    peers (self included in the passed list). Null below 3 peers."""
    if len(guided_peers) < MIN_PEERS:
        return None
    mine = [p["surprise"] for p in guided_peers if p.get("ticker") == ticker]
    if not mine:
        return None
    below = sum(1 for p in guided_peers if p["surprise"] < mine[0])
    return round(100.0 * below / (len(guided_peers) - 1), 1)


def build_fact_sheet(*, ticker: str, records: list[dict], price: float | None,
                     price_date: date | None, peer_multiple: float | None,
                     peer_median_fwd_eps: float | None,
                     peer_count: int, peer_basis: str,
                     guided_peers: list[dict],
                     fundamentals: dict, now: datetime,
                     tier: str = "open") -> dict:
    sheet: dict = {
        "ticker": ticker,
        "tier": tier,
        "computed_at": now.isoformat(),
        "status": None,
        "price": price,
        "price_as_of": price_date.isoformat() if price_date else None,
        "peer_group": None,
        "peer_multiple": peer_multiple,
        "peer_count": peer_count,
        "peer_basis": peer_basis,
        "peer_median_fwd_eps": peer_median_fwd_eps,
        "anchor": None,
        "bands": None,
        "implied": None,
        "gap_range_widths": None,
        "guidance_percentile": None,
        "directions": _directions(records),
        "fundamentals": fundamentals,
        "fundamentals_stale": False,
        "guard_rejections": [],
        "stale": False,
        "stale_reasons": [],
        "baseline_verdict": None,
        "falsifier": None,
        "inputs": {"guidance_records": records},
    }

    eps_as_of = (fundamentals.get("eps_diluted") or {}).get("as_of")
    if eps_as_of:
        try:
            age = (now.date() - date.fromisoformat(eps_as_of)).days
            sheet["fundamentals_stale"] = age > FUND_STALE_DAYS
        except ValueError:
            pass

    anchor, rejections, had_fy = _select_anchor(records, fundamentals, now)
    sheet["guard_rejections"] = rejections
    if anchor is None:
        sheet["status"] = "guide_rejected" if (had_fy or rejections) \
            else "no_full_year_guide"
        sheet["baseline_verdict"] = "no_bands"
        sheet["falsifier"] = (
            f"No band to falsify: {ticker} has no usable full-year EPS guide "
            "on record. The next recorded full-year EPS guide creates the "
            "bands; until then the name is tracked for direction only.")
        return sheet

    low = float(anchor["low"])
    high = float(anchor["high"]) if anchor.get("high") is not None else low
    mid = (low + high) / 2.0
    sheet["anchor"] = {
        "metric": anchor["metric"], "period": anchor.get("period"),
        "period_key": period_key(anchor.get("period") or ""),
        "low": low, "high": high, "mid": mid,
        "point_guide": high == low,
        "consensus": anchor.get("consensus"),
        "recorded_at": anchor.get("created_at"),
        "accession": anchor.get("accession"),
    }

    if peer_multiple is None or peer_count < MIN_PEERS:
        sheet["status"] = "no_peer_multiple"
        sheet["baseline_verdict"] = "no_bands"
        sheet["falsifier"] = (
            f"No band to falsify: the peer group for {ticker} has fewer than "
            f"{MIN_PEERS} members with a usable forward P/E.")
        return sheet

    m = float(peer_multiple)
    sheet["bands"] = {"bear": round(low * HAIRCUT * m, 2),
                      "base": round(mid * m, 2),
                      "bull": round(high * m, 2)}
    sheet["status"] = "banded"
    sheet["guidance_percentile"] = _percentile(ticker, guided_peers)

    # Staleness: the record stands, the verdict is suppressed.
    if price_date is None or (now.date() - price_date).days > PRICE_STALE_DAYS:
        sheet["stale"] = True
        sheet["stale_reasons"].append("price")
    if (now - _created(anchor)).days > GUIDE_STALE_DAYS:
        sheet["stale"] = True
        sheet["stale_reasons"].append("guide")

    if price is None:
        sheet["baseline_verdict"] = "no_price"
        return sheet

    implied_eps = price / m
    sheet["implied"] = {"eps": round(implied_eps, 4),
                        "vs_guide": ("above" if implied_eps > high else
                                     "below" if implied_eps < low else
                                     "inside")}
    width = high - low
    sheet["gap_range_widths"] = (round((implied_eps - mid) / width, 4)
                                 if width > 0 else None)

    if sheet["stale"]:
        sheet["baseline_verdict"] = "stale"
    else:
        sheet["baseline_verdict"] = classify_zone(
            price=price, bands=sheet["bands"], implied_eps=implied_eps,
            guide_low=low, guide_high=high, guide_mid=mid)

    sheet["falsifier"] = (
        f"Falsified if {ticker} guides {sheet['anchor']['period_key']} EPS "
        f"below {low:.2f} (the recorded low end of the current guide) at the "
        f"next print, or the guide is withdrawn — the bear band "
        f"({sheet['bands']['bear']:.2f}) then has no recorded anchor. "
        f"Re-underwrite on any new recorded guide for "
        f"{sheet['anchor']['period_key']}.")
    return sheet
