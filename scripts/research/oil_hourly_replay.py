# Replay: hourly model on the live Hyperliquid tape, every minute-mark, against real Kalshi quotes.
import datetime as D
import json
import math
import statistics as st
import time
import urllib.request
UA={"User-Agent":"tradehub-research","Content-Type":"application/json"}
def g(u,data=None):
    for i in range(4):
        try:
            r=urllib.request.Request(u,data=json.dumps(data).encode() if data else None,headers=UA)
            return json.load(urllib.request.urlopen(r,timeout=20))
        except Exception: time.sleep(1+i)
    return {}
K="https://api.elections.kalshi.com/trade-api/v2"
ts=lambda s:int(D.datetime.fromisoformat(s.replace("Z","+00:00")).timestamp())
now=int(time.time()); start=now-int(3.4*86400)
hl=g("https://api.hyperliquid.xyz/info",{"type":"candleSnapshot","req":{"coin":"xyz:CL","interval":"1m","startTime":start*1000,"endTime":now*1000}})
tape={int(c["t"])//1000+60:float(c["c"]) for c in hl}   # keyed by candle END
# official hourly values from the 15-minute strikes, for the trailing sigma
ms=[]; cur=""
for _ in range(3):
    d=g(f"{K}/markets?series_ticker=KXWTI15M&status=settled&limit=1000"+(f"&cursor={cur}" if cur else "")); ms+=d.get("markets") or []; cur=d.get("cursor")
    if not cur: break
hv=sorted((ts(m["open_time"]),m["floor_strike"]) for m in ms if m.get("floor_strike") and ts(m["open_time"])%3600==0)
def sigma(t):
    v=[(a,b) for a,b in hv if a<t]; ch=[y[1]-x[1] for x,y in zip(v,v[1:]) if y[0]-x[0]==3600][-72:]
    return max(.05,st.stdev(ch)) if len(ch)>=24 else None
Phi=st.NormalDist().cdf
events={}
cur=""
for _ in range(6):
    d=g(f"{K}/markets?series_ticker=KXWTIH&status=settled&limit=1000"+(f"&cursor={cur}" if cur else ""))
    for m in d.get("markets") or []:
        if m.get("result") in("yes","no") and m.get("floor_strike") and ts(m["close_time"])>start+3600:
            events.setdefault(m["event_ticker"],[]).append(m)
    cur=d.get("cursor")
    if not cur or min((ts(m["close_time"]) for m in d.get("markets") or [{"close_time":"2000-01-01T00:00:00Z"}]))<start: break
print("events",len(events))
def candles(t,a,b):
    d=g(f"{K}/series/KXWTIH/markets/{t}/candlesticks?start_ts={a}&end_ts={b}&period_interval=1"); out={}
    for c in d.get("candlesticks") or []:
        y=c.get("yes_bid") or {};n=c.get("yes_ask") or {}
        try: out[c["end_period_ts"]]=(float(y["close_dollars"]),float(n["close_dollars"]))
        except Exception: pass
    return out
def at(cs,x):
    k=[i for i in cs if x-120<=i<=x]; return cs[max(k)] if k else None
fee=lambda c:.07*c*(1-c)
LEADS=(50,40,30,20,10)
rows=[]; n=0
for ev,mks in sorted(events.items()):
    close=ts(mks[0]["close_time"])
    p0=tape.get(close-55*60) or tape.get(close-54*60)
    if p0 is None: continue
    sig=sigma(close-3600)
    if not sig: continue
    near=[m for m in mks if abs(m["floor_strike"]-p0)<=1.0]
    q={m["ticker"]:candles(m["ticker"],close-3660,close) for m in near}
    n+=len(near); time.sleep(.05*len(near))
    for lead in LEADS:
        t=close-lead*60; px=tape.get(t)
        if px is None: continue
        s=sig*math.sqrt(lead/60)
        best=None
        for m in near:
            qq=at(q[m["ticker"]],t)
            if not qq or qq[1]-qq[0]>.08 or qq[0]<=0 or qq[1]>=1: continue
            pu=1-Phi((m["floor_strike"]-px)/s)
            for side,pr,c in (("yes",pu,qq[1]),("no",1-pu,1-qq[0])):
                if .2<=c<=.8:
                    e=pr-c
                    if best is None or e>best["e"]:
                        best={"e":e,"side":side,"c":c,"t":m["ticker"],"k":m["floor_strike"],"res":m["result"],"mid":sum(qq)/2,"p":pr}
        if best and best["e"]>=.05:
            hit=best["res"]==best["side"]; sgn=1 if best["side"]=="yes" else -1
            later={}
            for dt in (10,20,30):
                if lead-dt>=2:
                    qq=at(q[best["t"]],t+dt*60)
                    if qq: later[dt]=(sum(qq)/2-best["mid"])*sgn
            rows.append(dict(ev=ev,lead=lead,hit=hit,net=(1 if hit else 0)-best["c"]-fee(best["c"]),c=best["c"],e=best["e"],later=later))
print("markets read",n)
print("lead  picks hit%  model_said  cost  net_c(se)   mid toward model +10/+20/+30 (share up)")
for lead in LEADS:
    r=[x for x in rows if x["lead"]==lead]
    if not r: continue
    ev=[x["net"] for x in r]
    tw=[]
    for dt in (10,20,30):
        v=[x["later"][str(dt)] if str(dt) in x["later"] else x["later"].get(dt) for x in r]; v=[a for a in v if a is not None]
        tw.append(f"{100*st.mean(v):+.1f}c/{100*sum(a>0 for a in v)/len(v):.0f}%" if v else "-")
    print(f"T-{lead:2d} {len(r):4d} {100*sum(x['hit'] for x in r)/len(r):4.0f}%  {100*st.mean(x['c']+x['e'] for x in r):5.0f}%  {st.mean(x['c'] for x in r):.2f}  {100*st.mean(ev):+5.1f}({100*st.pstdev(ev)/math.sqrt(len(ev)):.1f})  {' '.join(tw)}")
