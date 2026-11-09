"""Valuation fact-sheet compute job (Phase 0).

Universe: every ticker with a guidance record (amended universe, Nov 8
21:15 CT — S&P 500 names are the watch tier, any other recorded name is the
open tier; the index never gates entry). For each name: gather the recorded
guides, the industry peer-group median forward P/E, the last close, and EDGAR
fundamentals via the hub's existing DataStore, build the fact sheet with the
pure engine, and append it to valuation_fact_sheets.

Run: python -m tradehub.valuation.run [--ticker ACME] [--dry-run]
"""
from __future__ import annotations

import argparse
import statistics
from datetime import date, datetime, timezone

from tradehub.core.supabase_client import get_client
from tradehub.screening.sources import DataStore
from tradehub.valuation import engine, peers, store

EDGAR_CONCEPTS = {
    "eps_diluted": "EarningsPerShareDiluted",
    "shares_diluted": "WeightedAverageNumberOfDilutedSharesOutstanding",
    "cash": "CashAndCashEquivalentsAtCarryingValue",
    "debt_long_term": "LongTermDebtNoncurrent",
    "debt_current": "DebtCurrent",
}


def _peer_sales_multiple(ds: DataStore, ticker: str,
                         now: datetime) -> tuple[float | None, int, str,
                                                 str | None]:
    """(median Price/Sales, member count, basis, group) -- Phase B mirror of
    _peer_multiple over the same frozen groups: last close x diluted shares
    / latest FY revenue per member. A member counts only with every input
    present and a revenue as-of inside the fundamentals gate; net debt is
    never involved (EV/Sales is the deferred v2 amendment)."""
    group = peers.peer_group(ticker)
    basis = "industry_group"
    if group is not None:
        members = peers.group_members(group)
    else:
        sec = peers.sector(ticker)
        if sec is None:
            try:
                sec = ds.info(ticker).get("sector") or None
            except Exception:
                sec = None
        members = peers.sector_members(sec) if sec else []
        basis = "sector_fallback"
        group = f"sector:{sec}" if sec else None

    def collect(mems: list[str]) -> list[float]:
        vals: list[float] = []
        if not mems:
            return vals
        try:
            frame = ds.prices(mems, years=1)
        except Exception:
            return vals
        for m in mems:
            try:
                if m not in frame.columns:
                    continue
                series = frame[m].dropna()
                if not len(series):
                    continue
                price = float(series.iloc[-1])
                shares = ds.edgar_concept(
                    m, "WeightedAverageNumberOfDilutedSharesOutstanding")
                rev = None
                for rc in ("RevenueFromContractWithCustomerExcludingAssessedTax",
                           "Revenues"):
                    rev = ds.edgar_concept(m, rc)
                    if rev:
                        break
                if not shares or not rev:
                    continue
                (sv, _s_asof), (rv, r_asof) = shares, rev
                if sv <= 0 or rv <= 0:
                    continue
                try:
                    if (now.date() - date.fromisoformat(r_asof)).days \
                            > engine.FUND_STALE_DAYS:
                        continue
                except (ValueError, TypeError):
                    continue
                vals.append(price * sv / rv)
            except Exception:
                continue
        return vals

    vals = collect(members)
    if len(vals) < engine.MIN_PEERS and basis == "industry_group":
        sec = peers.sector(ticker)
        wider = peers.sector_members(sec) if sec else []
        vals2 = collect([m for m in wider if m not in members])
        if len(vals) + len(vals2) >= engine.MIN_PEERS:
            vals, basis = vals + vals2, "sector_widened"
    if len(vals) < engine.MIN_PEERS:
        return None, len(vals), basis, group
    return round(statistics.median(vals), 4), len(vals), basis, group


def _fundamentals(ds: DataStore, ticker: str) -> dict:
    out: dict = {"missing": []}
    for key, concept in EDGAR_CONCEPTS.items():
        try:
            hit = ds.edgar_concept(ticker, concept)
        except Exception:
            hit = None
        if hit is None:
            out["missing"].append(key)
        else:
            value, as_of = hit
            out[key] = {"value": value, "as_of": as_of}
    for rev_concept in ("RevenueFromContractWithCustomerExcludingAssessedTax",
                        "Revenues"):
        try:
            hit = ds.edgar_concept(ticker, rev_concept)
        except Exception:
            hit = None
        if hit is not None:
            out["revenue"] = {"value": hit[0], "as_of": hit[1]}
            break
    else:
        out["missing"].append("revenue")
    return out


def _peer_multiple(ds: DataStore, ticker: str) -> tuple[float | None, float | None, int, str, str | None]:
    """(median forward P/E, median forward EPS, member count, basis, group).

    Frozen method: median forward P/E (price layer info()) across the frozen
    industry group; fewer than 3 valid members widens to the GICS sector;
    an open-tier name with no known group starts at its sector."""
    group = peers.peer_group(ticker)
    basis = "industry_group"
    if group is not None:
        members = peers.group_members(group)
    else:
        sec = peers.sector(ticker)
        if sec is None:
            try:
                sec = ds.info(ticker).get("sector") or None
            except Exception:
                sec = None
        members = peers.sector_members(sec) if sec else []
        basis = "sector_fallback"
        group = f"sector:{sec}" if sec else None

    def collect(mems: list[str]) -> tuple[list[float], list[float]]:
        pes, epss = [], []
        for m in mems:
            try:
                info = ds.info(m)
            except Exception:
                continue
            fpe, feps = info.get("forwardPE"), info.get("forwardEps")
            if fpe and 0 < float(fpe) < 500:
                pes.append(float(fpe))
                if feps:
                    epss.append(float(feps))
        return pes, epss

    pes, epss = collect(members)
    if len(pes) < engine.MIN_PEERS and basis == "industry_group":
        sec = peers.sector(ticker)
        wider = peers.sector_members(sec) if sec else []
        pes2, epss2 = collect([m for m in wider if m not in members])
        if len(pes) + len(pes2) >= engine.MIN_PEERS:
            pes, epss, basis = pes + pes2, epss + epss2, "sector_widened"
    if len(pes) < engine.MIN_PEERS:
        return None, None, len(pes), basis, group
    return (round(statistics.median(pes), 4),
            round(statistics.median(epss), 4) if epss else None,
            len(pes), basis, group)


def _surprise(records: list[dict], now: datetime) -> float | None:
    """Guide-vs-consensus surprise for the percentile: anchor EPS guide if one
    passes the guards, else the name's live-period revenue guide."""
    anchor, _, _ = engine._select_anchor(records, {}, now)
    cands = [anchor] if anchor else []
    if not cands:
        by_metric: dict[str, list[dict]] = {}
        for r in records:
            if r.get("metric") == "revenue":
                by_metric.setdefault(
                    engine.period_key(r.get("period") or ""), []).append(r)
        if by_metric:
            live = max(by_metric.values(),
                       key=lambda rows: max(engine._created(r) for r in rows))
            cands = [sorted(live, key=engine._created)[-1]]
    for cand in cands:
        if not cand:
            continue
        mid = engine._mid(cand.get("low"), cand.get("high"))
        cons = cand.get("consensus")
        if mid is not None and cons:
            return (mid - cons) / abs(cons)
    return None


def compute(client, ds: DataStore, *, only: str | None = None,
            dry_run: bool = False, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    grouped = store.all_records(client)
    tickers = [only] if only else sorted(grouped)
    sheets: list[dict] = []

    # One batched price pull for the universe (peer prices come from info()).
    price_map: dict[str, tuple[float | None, object]] = {}
    try:
        frame = ds.prices([t for t in tickers if t in grouped], years=1)
        for t in tickers:
            if t in frame.columns:
                series = frame[t].dropna()
                if len(series):
                    price_map[t] = (float(series.iloc[-1]),
                                    series.index[-1].date())
    except Exception:
        price_map = {}

    # Percentile inputs: surprises for every guided name, grouped by peer group.
    surprises = {t: _surprise(recs, now) for t, recs in grouped.items()}

    for ticker in tickers:
        records = grouped.get(ticker, [])
        if not records:
            continue
        mult, med_eps, count, basis, group = _peer_multiple(ds, ticker)
        price, price_date = price_map.get(ticker, (None, None))
        mates = []
        for other, surp in surprises.items():
            if surp is None:
                continue
            if peers.peer_group(other) == peers.peer_group(ticker) and \
                    peers.peer_group(ticker) is not None:
                mates.append({"ticker": other, "surprise": surp})
        fundamentals = _fundamentals(ds, ticker)
        # Phase B: the peer Price/Sales multiple is computed only when no
        # EPS anchor passes -- the revenue basis never runs beside a live
        # EPS one.
        sales_mult, sales_cnt, sales_basis = None, 0, None
        eps_anchor, _rej, _had = engine._select_anchor(records, fundamentals,
                                                       now)
        if eps_anchor is None:
            sales_mult, sales_cnt, sales_basis, _sg = _peer_sales_multiple(
                ds, ticker, now)
        sheet = engine.build_fact_sheet(
            ticker=ticker, records=records, price=price,
            price_date=price_date, peer_multiple=mult,
            peer_median_fwd_eps=med_eps, peer_count=count, peer_basis=basis,
            guided_peers=mates, fundamentals=fundamentals,
            now=now, tier="watch" if peers.in_watch_tier(ticker) else "open",
            sales_multiple=sales_mult, sales_count=sales_cnt,
            sales_basis=sales_basis)
        sheet["peer_group"] = group
        sheet["inputs"]["peer_members_basis"] = basis
        if not dry_run:
            store.insert_sheet(client, sheet)
        sheets.append(sheet)
    return sheets


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ticker", default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    sheets = compute(get_client(), DataStore(), only=args.ticker,
                     dry_run=args.dry_run)
    for s in sheets:
        bands = s.get("bands") or {}
        print(f"{s['ticker']:6s} {s['tier']:5s} {s['status']:18s} "
              f"verdict={s['baseline_verdict']} "
              f"bear={bands.get('bear')} base={bands.get('base')} "
              f"bull={bands.get('bull')} price={s.get('price')}")
    print(f"{len(sheets)} fact sheets {'computed' if args.dry_run else 'written'}")


if __name__ == "__main__":
    main()
