#!/usr/bin/env python3
import os, requests, pandas as pd

#─── CONFIG ────────────────────────────────────────────────────────────────────
PUSH_URL = os.environ https://api.pushcut.io/01M6OsxMNYMhhg4OSZugx/notifications/OpenStraddleSignal
SUBGRAPH = "https://api.thegraph.com/subgraphs/name/ianlapham/arbitrum-minimal"
PAIR     = "0x223292964fd10e82867d9e6c99ce62106426f204"
#───────────────────────────────────────────────────────────────────────────────

def fetch_data():
    query = f'''
    {{
      pairDayDatas(first:100, orderBy:date, orderDirection:desc,
                   where:{{pair:"{PAIR}"}}) {{
        date open high low close dailyVolumeToken0
      }}
    }}'''
    r = requests.post(SUBGRAPH, json={"query": query})
    r.raise_for_status()
    payload = r.json()
    if "errors" in payload:
        raise RuntimeError("GraphQL errors:\n" + str(payload["errors"]))
    data = payload["data"]["pairDayDatas"][::-1]  # reverse oldest→newest
    df = (
        pd.DataFrame(data)
          .assign(timestamp=lambda d: pd.to_datetime(d.date, unit="s"))
          .set_index("timestamp")
          .astype(float)
    )
    return df.rename(columns={"dailyVolumeToken0":"volume"})[
        ["open","high","low","close","volume"]
    ]

def compute_indicators(df):
    d      = df.close.diff()
    gain   = d.clip(lower=0); loss = -d.clip(upper=0)
    avg_g  = gain.rolling(14).mean(); avg_l = loss.rolling(14).mean()
    rs     = avg_g/avg_l
    df["rsi"]      = 100 - (100/(1+rs))
    df["vol_ma20"] = df.volume.rolling(20).mean()
    df["ema5"]     = df.close.ewm(span=5,adjust=False).mean()
    df["y_rsi"]    = df.rsi.shift(1)

def identify_signals(df):
    prev   = df.shift(1)
    engulf = (df.open < prev.close) & (df.close > prev.open)
    sigs   = []
    for t, r in df.iterrows():
        y, s   = r.y_rsi, r.rsi
        v, ma  = r.volume, r.vol_ma20
        cl, e5 = r.close, r.ema5
        p1 = (y < 30) and (s > 30) and (v >= 1.5*ma) and (cl > e5)
        p2 = (y < 30) and (s > 30) and (v >= 1.2*ma)
        p3 = (y < 30) and (s > 35) and (v < 1.2*ma)
        p4 = engulf.loc[t] and (v >= ma)
        p5 = (cl > df.high.shift(1).loc[t]) and (s < 35)
        l1, l2, ph = (
            df.low.shift(2).loc[t],
            df.low.shift(1).loc[t],
            df.high.shift(1).loc[t],
        )
        p6 = (l2 < l1) and (cl > ph)
        if any((p1, p2, p3, p4, p5, p6)):
            sigs.append(t)
    return sigs

def backtest_and_alert(df, sigs):
    rows = []
    for sig in sigs:
        idx = df.index.get_loc(sig) + 1
        if idx >= len(df): break
        ent = df.index[idx]
        ep  = df.at[ent,"open"]
        tgt = ep * 1.10
        hit = None
        for d, r in df.loc[ent:].iterrows():
            if r.high >= tgt:
                hit = d.date()
                break
        rows.append({
            "signal": sig.date(),
            "entry": ent.date(),
            "ep": round(ep,8),
            "hit": hit
        })
    res = pd.DataFrame(rows)
    print(res.to_string(index=False))
    print(f"\nTotal signals: {len(res)}, Hits: {res.hit.notna().sum()}\n")
    if df.index[-1] in sigs:
        requests.post(PUSH_URL)
        print(f"[ALERT] 🚀 OPEN STRADDLE NOW — {df.index[-1].date()}")

def main():
    df   = fetch_data()
    compute_indicators(df)
    sigs = identify_signals(df)
    backtest_and_alert(df, sigs)

if __name__ == "__main__":
    main()
