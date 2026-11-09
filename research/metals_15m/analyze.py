"""Exploratory replay: metals 15M, family math (drift-scaled RW) on HL xyz tapes,
gated at the family's 0.10 net-of-fee bar vs Kalshi freeze-minute quotes.
Freeze convention: the 1m candle ending 5 minutes into the window (elapsed 5, remaining 10)."""
import math, statistics, sys, time
import datetime as dt
import requests

KB = "https://api.elections.kalshi.com/trade-api/v2"
HL = "https://api.hyperliquid.xyz/info"
FEE = 0.07

def fee(c): return FEE * c * (1 - c)

def prob_up(o, p, s, rem):
    return statistics.NormalDist().cdf(math.log(p / o) / (s * math.sqrt(max(rem, 1.0))))

def sigma_1m(closes):
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
    if len(rets) < 30: return None
    return max(0.0002, statistics.stdev(rets))

def hl_candles(coin, start_ms, end_ms):
    r = requests.post(HL, json={"type": "candleSnapshot", "req": {"coin": coin, "interval": "1m",
                        "startTime": start_ms, "endTime": end_ms}}, timeout=30)
    out = {}
    for c in r.json():
        out[int(c["t"]) // 60000] = float(c["c"])  # key: minute-start epoch -> close
    return out

def kalshi_markets(series, limit):
    r = requests.get(KB + "/markets", params={"series_ticker": series, "status": "settled", "limit": limit}, timeout=30)
    return r.json().get("markets", [])

def kalshi_candles(series, ticker, start_ts, end_ts):
    r = requests.get(f"{KB}/series/{series}/markets/{ticker}/candlesticks",
                     params={"start_ts": start_ts, "end_ts": end_ts, "period_interval": 1}, timeout=30)
    return r.json().get("candlesticks", [])

def run(series, coin, n_markets):
    now = dt.datetime.now(dt.UTC)
    tape = hl_candles(coin, int((now - dt.timedelta(days=4)).timestamp() * 1000), int(now.timestamp() * 1000))
    markets = kalshi_markets(series, n_markets)
    rows = []
    for m in markets:
        T = dt.datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
        open_min = int((T - dt.timedelta(minutes=15)).timestamp() // 60)
        freeze_min = open_min + 4          # candle starting open+4 ends at elapsed 5
        close_min = open_min + 14          # candle ending at window close
        o = tape.get(open_min - 1)         # close of candle ending at window open
        p = tape.get(freeze_min)
        pc = tape.get(close_min)
        if o is None or p is None: continue
        run_closes = [tape[k] for k in range(freeze_min - 90, freeze_min + 1) if k in tape]
        if len(run_closes) < 31: continue
        s = sigma_1m(run_closes)
        if s is None: continue
        prob = prob_up(o, p, s, 10.0)
        cs = kalshi_candles(series, m["ticker"], int(T.timestamp()) - 1200, int(T.timestamp()))
        q = None
        for c in cs:
            if int(c["end_period_ts"]) == int(T.timestamp()) - 600:  # candle ending at elapsed 5
                try:
                    q = (float(c["yes_bid"]["close_dollars"]), float(c["yes_ask"]["close_dollars"]))
                except (KeyError, TypeError, ValueError):
                    q = None
        if q is None: continue
        bid, ask = q
        if not (0.02 < bid <= ask < 0.98): continue
        yes = (m["result"] == "yes")
        mid = (bid + ask) / 2
        # gated pick, family rule
        ye, ne = prob - ask - fee(ask), bid - prob - fee(1 - bid)
        trade = None
        if max(ye, ne) >= 0.10:
            if ye >= ne: trade = ("yes", ask)
            else: trade = ("no", 1 - bid)
        pnl = None
        if trade:
            side, cost = trade
            win = yes if side == "yes" else not yes
            pnl = (1.0 if win else 0.0) - cost - fee(cost)
        rows.append({"yes": yes, "prob": prob, "mid": mid, "pnl": pnl,
                     "hl_dir_match": (pc >= o) == yes if pc is not None else None,
                     "spread": ask - bid})
        time.sleep(0.05)
    n = len(rows)
    if n == 0: return {"series": series, "n": 0}
    mb = statistics.mean((r["prob"] - r["yes"]) ** 2 for r in rows)
    kb_ = statistics.mean((r["mid"] - r["yes"]) ** 2 for r in rows)
    trades = [r for r in rows if r["pnl"] is not None]
    tp = [r["pnl"] for r in trades]
    low95 = (statistics.mean(tp) - 1.96 * statistics.stdev(tp) / math.sqrt(len(tp))) if len(tp) > 1 else None
    dm = [r["hl_dir_match"] for r in rows if r["hl_dir_match"] is not None]
    return {"series": series, "n": n, "model_brier": round(mb, 4), "market_brier": round(kb_, 4),
            "gated_n": len(tp), "gated_mean_c": round(statistics.mean(tp) * 100, 1) if tp else None,
            "gated_low95_c": round(low95 * 100, 1) if low95 is not None else None,
            "gated_win": round(statistics.mean(1.0 if x > - (0) else 0.0 for x in tp), 2) if False else (round(sum(1 for r in trades if (r["pnl"] + 0) > -0.9) / len(tp), 2) if tp else None),
            "hl_dir_match_pct": round(100 * statistics.mean(dm), 1) if dm else None,
            "median_spread_c": round(statistics.median(r["spread"] for r in rows) * 100, 1)}

for series, coin, n in [("KXGOLD15M", "xyz:GOLD", 150), ("KXSILVER15M", "xyz:SILVER", 150), ("KXCOPPER15M", "xyz:COPPER", 120)]:
    print(run(series, coin, n), flush=True)
