# Scores free oil and gas feeds against Kalshi's 15-minute strikes and results. Read-only. Run: python3 -I this file.
import datetime as D
import json
import statistics as st
import time
import urllib.request
UA={"User-Agent":"tradehub-research","Content-Type":"application/json"}
def g(u,data=None):
    try:
        r=urllib.request.Request(u,data=json.dumps(data).encode() if data else None,headers=UA)
        return json.load(urllib.request.urlopen(r,timeout=20))
    except Exception as e:
        return {"err":str(e)[:100]}
ts=lambda s:int(D.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp())
print("hermes public:",str(g("https://hermes.pyth.network/v2/updates/price/latest?ids[]=67784f72e95ac01337edb7d7bd5bbd1c03669101b7068a620df228ed4e52ef14&parsed=true"))[:220])
print("wti1m public:",str(g("https://hermes.pyth.network/v2/updates/price/latest?ids[]=f2464139c45f26097e0173b03207c4a490dbd8bf1b72dfbf064eeb832c7c2933&parsed=true").get("parsed"))[:220])
print("hist syms:",str(g("https://history.pyth-lazer.dourolabs.app/history/v1/symbols?query=PYTHOIL"))[:300])
print("okx inst:",[x["instId"] for x in g("https://www.okx.com/api/v5/public/instruments?instType=SWAP").get("data",[]) if x["instId"].split("-")[0] in("CL","BZ","NG","BRENT","BRN","NATGAS","WTI","OIL")])
now=int(time.time()); start=now-4*86400
def hl(c):
    d=g("https://api.hyperliquid.xyz/info",{"type":"candleSnapshot","req":{"coin":c,"interval":"1m","startTime":start*1000,"endTime":now*1000}})
    return {int(x["t"])//1000:float(x["c"]) for x in d} if isinstance(d,list) else {}
def okx(i):
    out={};after=""
    for _ in range(70):
        d=g(f"https://www.okx.com/api/v5/market/history-candles?instId={i}&bar=1m&limit=100"+(f"&after={after}" if after else "")).get("data") or []
        if not d: break
        for r in d: out[int(r[0])//1000]=float(r[4])
        after=d[-1][0]; time.sleep(.12)
        if int(after)//1000<start: break
    return out
def yahoo(sym):
    d=g(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}?range=5d&interval=1m")
    try:
        r=d["chart"]["result"][0]; return {t:c for t,c in zip(r["timestamp"],r["indicators"]["quote"][0]["close"]) if c}
    except Exception: return {}
SETS={"KXWTI15M":{"HL xyz:CL":lambda:hl("xyz:CL"),"OKX CL swap":lambda:okx("CL-USDT-SWAP"),"Yahoo CL=F":lambda:yahoo("CL=F")},
"KXBRENT15M":{"HL xyz:BRENTOIL":lambda:hl("xyz:BRENTOIL"),"OKX BZ swap":lambda:okx("BZ-USDT-SWAP"),"Yahoo BZ=F":lambda:yahoo("BZ=F")},
"KXNATGAS15M":{"HL xyz:NATGAS":lambda:hl("xyz:NATGAS"),"OKX NG swap":lambda:okx("NG-USDT-SWAP"),"Yahoo NG=F":lambda:yahoo("NG=F")}}
for s,feeds in SETS.items():
    ms=[m for m in g(f"https://api.elections.kalshi.com/trade-api/v2/markets?series_ticker={s}&status=settled&limit=500").get("markets",[]) if m.get("result") in("yes","no") and m.get("floor_strike")]
    ms=[(ts(m["open_time"]),ts(m["close_time"]),m["floor_strike"],m["result"]) for m in ms if ts(m["open_time"])>=start]
    print(f"\n{s}: {len(ms)} settled windows")
    for name,fn in feeds.items():
        tape=fn()
        if not tape: print(" ",name,"no data"); continue
        for off,lab in ((-60,"candle ending at open"),(0,"candle starting at open")):
            basis=[];ok=tot=0;n_flat=0
            for o,c,k,r in ms:
                a,b=tape.get(o+off),tape.get(c+off)
                if a is None: continue
                basis.append(a-k)
                if b is None: continue
                tot+=1
                ok+=(b>=a)==(r=="yes")
            if tot:
                e=st.pstdev(basis)
                print(f"  {name:18s} {lab:24s} n={tot:4d} direction_match={100*ok/tot:5.1f}% basis mean={st.mean(basis):+.3f} sd={e:.3f}")
