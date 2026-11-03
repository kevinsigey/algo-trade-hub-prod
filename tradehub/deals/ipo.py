"""IPO builder math (Part B; method = Kevin's Anthropic IPO paper and its
entry test, 2026-11-02). Pure functions over the form inputs: a probability-
weighted scenario ladder, the paper's three-rule entry test at the talk
price, and a fork sensitivity (which assumption moves PW $/share most).
All money $B, shares B, per-share $. A scenario carries either a direct
enterprise value (the paper's value sliders) or a revenue outcome x an exit
multiple; every output is computed from the inputs as entered -- nothing is
invented, and a missing talk range or scenario is a named error."""

from __future__ import annotations


class DealInputError(ValueError):
    pass


def _scenario_ev(s: dict) -> float:
    if s.get("ev_b") is not None:
        return float(s["ev_b"])
    if s.get("revenue_b") is not None and s.get("multiple") is not None:
        return float(s["revenue_b"]) * float(s["multiple"])
    raise DealInputError(f"scenario '{s.get('name', '?')}' needs either ev_b or revenue_b x multiple")


def run_ipo(inp: dict) -> dict:
    shares = float(inp.get("shares_b") or 0)
    if shares <= 0:
        raise DealInputError("shares_b (fully diluted, billions) is required")
    scenarios = inp.get("scenarios") or []
    if len(scenarios) < 2:
        raise DealInputError("at least two scenarios are required")
    weights = [float(s.get("weight") or 0) for s in scenarios]
    if abs(sum(weights) - 1.0) > 0.011:
        raise DealInputError(f"scenario weights must sum to 1 (they sum to {sum(weights):.2f})")
    net_cash = float(inp.get("net_cash_b") or 0)
    ladder = []
    for s, w in zip(scenarios, weights, strict=True):
        ev = _scenario_ev(s)
        equity = ev + net_cash
        ladder.append({"name": s.get("name", "?"), "ev_b": round(ev, 2), "weight": w,
                       "ps": round(equity / shares, 2), "contrib_b": round(equity * w, 2)})
    pw_equity = sum(r["contrib_b"] for r in ladder)
    pw_ps = pw_equity / shares
    bear_ps = min(r["ps"] for r in ladder)

    def entry_test(talk_ps: float) -> dict:
        ev_at = talk_ps * shares - net_cash
        mos = (pw_ps - talk_ps) / pw_ps if pw_ps else 0.0
        bear_down = (bear_ps - talk_ps) / talk_ps if talk_ps else 0.0
        rules = {"beats_pw": talk_ps <= pw_ps,
                 "mos_25": mos >= 0.25,
                 "bear_bound_40": bear_down >= -0.40}
        return {"talk_ps": talk_ps, "ev_at_talk_b": round(ev_at, 1),
                "exp_return_vs_pw_pct": round((pw_ps / talk_ps - 1) * 100, 1) if talk_ps else None,
                "mos_vs_pw_pct": round(mos * 100, 1),
                "bear_downside_pct": round(bear_down * 100, 1),
                "rules": rules, "enter": all(rules.values())}

    talk_low, talk_high = inp.get("talk_low_ps"), inp.get("talk_high_ps")
    entry = {}
    if talk_low is not None and talk_high is not None:
        entry = {"at_mid": entry_test((float(talk_low) + float(talk_high)) / 2),
                 "at_high": entry_test(float(talk_high))}
    elif talk_low is None and talk_high is None:
        entry = {"missing": "no talk range entered -- the entry test needs one"}
    else:
        raise DealInputError("enter both ends of the talk range, or neither")

    # Fork sensitivity: one-at-a-time shocks, ranked by |change in PW $/share|.
    base_pw = pw_ps
    shocks = []
    for i, (s, w) in enumerate(zip(scenarios, weights, strict=True)):
        ev = _scenario_ev(s)
        shocked = (ev * 1.10 + net_cash) * w + sum(
            (_scenario_ev(s2) + net_cash) * w2 for j, (s2, w2) in enumerate(zip(scenarios, weights, strict=True)) if j != i)
        shocks.append({"lever": f"{s.get('name', '?')} value +10%",
                       "d_pw_ps": round(shocked / shares - base_pw, 2)})
        donor = max((j for j in range(len(scenarios)) if j != i), key=lambda j: weights[j])
        w2 = list(weights)
        w2[i] += 0.05
        w2[donor] -= 0.05
        shifted = sum((_scenario_ev(s3) + net_cash) * x for s3, x in zip(scenarios, w2, strict=True))
        shocks.append({"lever": f"{s.get('name', '?')} weight +5 pts",
                       "d_pw_ps": round(shifted / shares - base_pw, 2)})
    shocks.append({"lever": "fully-diluted shares +5% (dilution)",
                   "d_pw_ps": round(pw_equity / (shares * 1.05) - base_pw, 2)})
    shocks.sort(key=lambda x: abs(x["d_pw_ps"]), reverse=True)

    conditions = inp.get("conditions") or []
    joint = None
    if conditions:
        joint = 1.0
        for c in conditions:
            joint *= float(c.get("odds") or 0)
    return {"ladder": ladder, "pw_ev_b": round(pw_equity - net_cash, 1),
            "pw_equity_b": round(pw_equity, 1), "pw_ps": round(pw_ps, 2),
            "bear_ps": round(bear_ps, 2),
            "entry": entry, "sensitivity": shocks,
            "conditions": {"list": conditions, "joint_odds": round(joint, 4) if joint is not None else None},
            "implied_ps_on_run_rate": (round(float(talk_high) * shares / float(inp["revenue_b"]), 1)
                                       if inp.get("revenue_b") and talk_high else None)}
