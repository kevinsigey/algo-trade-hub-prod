"""M&A builder math (Part B; method = Kevin's Tesla-SpaceX merger paper).
Pure functions: standalone football fields (revenue + EBITDA multiples and a
compact 5-year DCF per side), the implied exchange-ratio range against the
offered terms, premium, pro forma combination with EPS accretion/dilution,
and the synergy value bridge (who captures the synergy at the offered
terms). All money $B, shares B, per-share $. Missing inputs are named
errors, never zeroed."""

from __future__ import annotations

from tradehub.deals.ipo import DealInputError


def _dcf_ps(side: dict) -> float | None:
    d = side.get("dcf") or {}
    need = ("fcf_margin", "growth", "wacc", "exit_multiple")
    if any(d.get(k) is None for k in need) or side.get("revenue_b") is None:
        return None
    rev, wacc = float(side["revenue_b"]), float(d["wacc"])
    pv_flows, fcf = 0.0, 0.0
    for t in range(1, 6):
        rev_t = rev * (1 + float(d["growth"])) ** t
        fcf = rev_t * float(d["fcf_margin"])
        pv_flows += fcf / (1 + wacc) ** t
    pv_terminal = (fcf * float(d["exit_multiple"])) / (1 + wacc) ** 5
    ev = pv_flows + pv_terminal
    return (ev + float(side.get("net_cash_b") or 0)) / float(side["shares_b"])


def _side(inp: dict, label: str) -> dict:
    if inp.get("shares_b") is None or float(inp.get("shares_b") or 0) <= 0:
        raise DealInputError(f"{label}: shares_b (billions) is required")
    shares = float(inp["shares_b"])
    net_cash = float(inp.get("net_cash_b") or 0)
    fields = {}
    for key, mult_key in (("revenue", "rev_multiples"), ("ebitda", "ebitda_multiples")):
        base = inp.get(f"{key}_b")
        mults = inp.get(mult_key) or {}
        if base is None or mults.get("low") is None or mults.get("high") is None:
            fields[key] = None
        else:
            lo = (float(base) * float(mults["low"]) + net_cash) / shares
            hi = (float(base) * float(mults["high"]) + net_cash) / shares
            fields[key] = {"ps_low": round(lo, 2), "ps_high": round(hi, 2)}
    dcf = _dcf_ps(inp)
    points = [v for f in fields.values() if f for v in (f["ps_low"], f["ps_high"])]
    if dcf is not None:
        points.append(dcf)
    if not points:
        raise DealInputError(f"{label}: no valuation basis entered (multiples or DCF inputs)")
    return {"name": inp.get("name", label), "fields": fields,
            "dcf_ps": round(dcf, 2) if dcf is not None else None,
            "ps_low": round(min(points), 2), "ps_high": round(max(points), 2),
            "ps_mid": round(sum(points) / len(points), 2),
            "price": inp.get("price"), "shares_b": shares,
            "revenue_b": inp.get("revenue_b"), "ebitda_b": inp.get("ebitda_b"),
            "eps": inp.get("eps"), "net_cash_b": net_cash}


def run_ma(inp: dict) -> dict:
    acq = _side(inp.get("acquirer") or {}, "acquirer")
    tgt = _side(inp.get("target") or {}, "target")
    offer = inp.get("offer") or {}
    ratio = float(offer.get("exchange_ratio") or 0)
    cash_ps = float(offer.get("cash_ps") or 0)
    if ratio <= 0 and cash_ps <= 0:
        raise DealInputError("the offer needs an exchange ratio and/or cash per share")
    acq_price = float((inp.get("acquirer") or {}).get("price") or acq["ps_mid"])
    offer_ps = cash_ps + ratio * acq_price
    undisturbed = float(offer.get("undisturbed_ps") or (inp.get("target") or {}).get("price") or tgt["ps_mid"])
    premium_pct = (offer_ps / undisturbed - 1) * 100 if undisturbed else None

    ratio_range = None
    if ratio > 0:
        ratio_range = {"low": round(tgt["ps_low"] / acq["ps_high"], 3),
                       "high": round(tgt["ps_high"] / acq["ps_low"], 3),
                       "offered": ratio,
                       "inside": bool(tgt["ps_low"] / acq["ps_high"] <= ratio <= tgt["ps_high"] / acq["ps_low"])}

    new_shares = ratio * tgt["shares_b"]
    combined_shares = acq["shares_b"] + new_shares
    syn = inp.get("synergies") or {}
    tax = float(inp.get("tax_rate") if inp.get("tax_rate") is not None else 0.21)
    cap_mult = float(inp.get("synergy_multiple") or 10)
    debt_rate = float(inp.get("debt_rate") or 0)
    cash_total = cash_ps * tgt["shares_b"]

    def case(name: str) -> dict:
        pre = syn.get(name)
        if pre is None:
            return {"synergy_pre_tax_b": None, "synergy_pv_b": None, "eps_pro_forma": None,
                    "accretion_pct": None, "target_captures_b": None, "acquirer_captures_b": None}
        after = float(pre) * (1 - tax)
        pv = after * cap_mult
        out = {"synergy_pre_tax_b": float(pre), "synergy_pv_b": round(pv, 2)}
        if acq["eps"] is not None and tgt["eps"] is not None:
            ni = float(acq["eps"]) * acq["shares_b"] + float(tgt["eps"]) * tgt["shares_b"] \
                + after - cash_total * debt_rate * (1 - tax)
            eps_pf = ni / combined_shares
            out["eps_pro_forma"] = round(eps_pf, 3)
            out["accretion_pct"] = round((eps_pf / float(acq["eps"]) - 1) * 100, 1) if acq["eps"] else None
        else:
            out["eps_pro_forma"] = None
            out["accretion_pct"] = None
        offer_equity = offer_ps * tgt["shares_b"]
        standalone_equity = tgt["ps_mid"] * tgt["shares_b"]
        out["target_captures_b"] = round(offer_equity - standalone_equity, 2)
        out["acquirer_captures_b"] = round(pv - out["target_captures_b"], 2)
        return out

    # The hub's fair-value estimate for the TARGET: a stated blend of the
    # method midpoints (revenue 40 / EBITDA 30 / DCF 30, renormalized over
    # the methods actually present) -- our number, next to the offer.
    methods = {}
    for key, field in (("revenue", tgt["fields"].get("revenue")), ("ebitda", tgt["fields"].get("ebitda"))):
        if field:
            methods[key] = ((field["ps_low"] + field["ps_high"]) / 2, field["ps_low"], field["ps_high"])
    if tgt["dcf_ps"] is not None:
        methods["dcf"] = (tgt["dcf_ps"], tgt["dcf_ps"], tgt["dcf_ps"])
    weights = {"revenue": 0.40, "ebitda": 0.30, "dcf": 0.30}
    wsum = sum(weights[k] for k in methods) or 1.0
    fair = None
    if methods:
        ps = sum(methods[k][0] * weights[k] for k in methods) / wsum
        lo = sum(methods[k][1] * weights[k] for k in methods) / wsum
        hi = sum(methods[k][2] * weights[k] for k in methods) / wsum
        if offer_ps < lo:
            verdict = "the offer sits BELOW our fair-value range -- target holders are leaving money on the table"
        elif offer_ps > hi:
            verdict = "the offer pays ABOVE our fair-value range -- the acquirer is paying for the synergies upfront"
        else:
            verdict = "the offer sits inside our fair-value range"
        fair = {"ps": round(ps, 2), "ps_low": round(lo, 2), "ps_high": round(hi, 2),
                "methods": {k: round(v[0], 2) for k, v in methods.items()},
                "weights": {k: round(weights[k] / wsum, 2) for k in methods},
                "vs_offer_pct": round((offer_ps / ps - 1) * 100, 1) if ps else None,
                "verdict": verdict}
    if ratio_range is not None and ratio_range["high"] > ratio_range["low"]:
        ratio_range["position"] = round(
            min(1.0, max(0.0, (ratio - ratio_range["low"]) / (ratio_range["high"] - ratio_range["low"]))), 2)
    combined_rev = (None if acq["revenue_b"] is None or tgt["revenue_b"] is None
                    else round(float(acq["revenue_b"]) + float(tgt["revenue_b"]), 2))
    combined_ebitda = (None if acq["ebitda_b"] is None or tgt["ebitda_b"] is None
                       else round(float(acq["ebitda_b"]) + float(tgt["ebitda_b"]), 2))
    combined_ev = acq_price * acq["shares_b"] + offer_ps * tgt["shares_b"]

    return {"acquirer": acq, "target": tgt, "fair_value": fair,
            "offer": {"cash_ps": cash_ps, "exchange_ratio": ratio, "value_ps": round(offer_ps, 2),
                      "undisturbed_ps": undisturbed, "premium_pct": round(premium_pct, 1) if premium_pct is not None else None},
            "ratio_range": ratio_range,
            "pro_forma": {"combined_revenue_b": (None if acq["revenue_b"] is None or tgt["revenue_b"] is None
                                                 else round(float(acq["revenue_b"]) + float(tgt["revenue_b"]), 2)),
                          "combined_ebitda_b": (None if acq["ebitda_b"] is None or tgt["ebitda_b"] is None
                                                else round(float(acq["ebitda_b"]) + float(tgt["ebitda_b"]), 2)),
                          "new_shares_b": round(new_shares, 3), "combined_shares_b": round(combined_shares, 3),
                          "ev_at_offer_b": round(combined_ev, 2),
                          "ev_to_revenue": round(combined_ev / combined_rev, 2) if combined_rev else None,
                          "ev_to_ebitda": round(combined_ev / combined_ebitda, 2) if combined_ebitda else None,
                          "ownership": {"acquirer_pct": round(acq["shares_b"] / combined_shares * 100, 1),
                                        "target_pct": round(new_shares / combined_shares * 100, 1)}},
            "cases": {name: case(name) for name in ("bear", "base", "bull")},
            "assumptions": {"tax_rate": tax, "synergy_multiple": cap_mult, "debt_rate": debt_rate,
                            "standalone_basis": "target mid of its football field"}}
