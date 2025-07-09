#!/usr/bin/env python3
import os
import time
import requests
import pandas as pd

# ==== CONFIG ====
# Your GS/WETH pair on Arbitrum
PAIR = "0x223292964fd10e82867d9e6c99ce62106426f204"
# Pushcut webhook URL (set as a GitHub secret)
PUSHCUT_WEBHOOK_URL = os.environ["PUSHCUT_WEBHOOK_URL"]


def fetch_data():
    """
    Fetch last 100 days of GS/WETH hourly data from CoinGecko,
    resample to daily OHLC + volume, return a DataFrame.
    """
    to_ts   = int(time.time())
    from_ts = to_ts - 100 * 86400

    url    = (
      "https://api.coingecko.com/api/v3/coins/arbitrum-one/"
      f"contract/{PAIR}/market_chart/range"
    )
    params = {"vs_currency": "eth", "from": from_ts, "to": to_ts}
    r      = requests.get(url, params=params)
    r.raise_for_status()
    js     = r.json()

    prices  = pd.DataFrame(js["prices"], columns=["ts","price"])
    volumes = pd.DataFrame(js["total_volumes"], columns=["ts","volume"])

    df = (
      prices.merge(volumes, on="ts")
            .assign(timestamp=lambda d: pd.to_datetime(d.ts, unit="ms"))
            .set_index("timestamp")
            .drop("ts", axis=1)
    )

    daily = pd.DataFrame({
      "open"  : df.price.resample("1D").first(),
      "high"  : df.price.resample("1D").max(),
      "low"   : df.price.resample("1D").min(),
      "close" : df.price.resample("1D").last(),
      "volume": df.volume.resample("1D").sum(),
    }).dropna()

    return daily


def compute_indicators(df):
    """Add RSI, volume-MA20, EMA5, yesterday’s RSI."""
    delta = df.close.diff()
    up, down = delta.clip(lower=0), -delta.clip(upper=0)
    rsi = 100 - (100 / (1 + up.rolling(14).mean() / down.rolling(14).mean()))
    df["rsi"]      = rsi
    df["vol_ma20"] = df.volume.rolling(20).mean()
    df["ema5"]     = df.close.ewm(span=5).mean()
    df["y_rsi"]    = df.rsi.shift(1)


def identify_signals(df):
    """
    Returns a list of Timestamps where our straddle‐entry logic fires:
      - rsi below 30
      - volume ≥ 1.2× 20-day MA
      - engulfing day up
      - close above EMA5
      - yesterday’s rsi < 30
    """
    sigs = []
    prev = df.shift(1)
    for t, r in df.iterrows():
        y, s = r.y_rsi, r.rsi
        v, ma = r.volume, r.vol_ma20
        cl, e5 = r.close, r.ema5
        p1 = (y < 30) and (s > 30)
        p2 = v >= 1.2 * ma
        p3 = (cl > prev.loc[t].open)
        p4 = cl > e5
        if p1 and p2 and p3 and p4:
            sigs.append(t)
    return sigs


def backtest_and_alert(df, signals):
    """
    For each signal date, check if next days’ high ever ≥ 1.10× open.
    Print summary and, if **today** is in `signals`, fire Pushcut.
    """
    rows = []
    for sig in signals:
        idx = df.index.get_loc(sig) + 1
        if idx >= len(df): break
        ent = df.index[idx]
        ep  = df.at[ent, "open"]
        tgt = ep * 1.10
        hit = None
        for d, r in df.loc[ent:].iterrows():
            if r.high >= tgt:
                hit = d.date()
                break
        rows.append({
          "signal": sig.date(),
          "entry" : ent.date(),
          "open"  : round(ep, 8),
          "hit"   : hit
        })

    out = pd.DataFrame(rows)
    print(out.to_string(index=False))
    print(f"\nTotal signals: {len(out)}, Hits: {out.hit.notna().sum()}\n")

    # if **today** signaled, push notification
    if df.index[-1].normalize() in [ts.normalize() for ts in signals]:
        requests.post(PUSHCUT_WEBHOOK_URL)
        print(f"[ALERT] 🚀 OPEN STRADDLE NOW – {df.index[-1].date()}")


def main():
    df   = fetch_data()
    compute_indicators(df)
    sigs = identify_signals(df)
    backtest_and_alert(df, sigs)


if __name__ == "__main__":
    main()
chmod +x pushcut_alert.py
