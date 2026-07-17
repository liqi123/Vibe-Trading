"""Top5 4因子 2026年上半年表现"""
from __future__ import annotations
import sys, time, sqlite3
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.factors.base import rank

COMMISSION = 0.00025
STAMP = 0.0005
SLIPPAGE = 0.001
DB = r"G:\tdx_data\tdx_daily.db"

def load_data(start, end):
    conn = sqlite3.connect(DB)
    sd, ed = start.replace("-", ""), end.replace("-", "")
    valid = {r[0] for r in conn.execute("SELECT code FROM stock_names").fetchall()}
    df = pd.read_sql_query(
        "SELECT code, market, trade_date, open, high, low, close, amount, volume "
        "FROM daily_kline WHERE trade_date >= ? AND trade_date <= ?",
        conn, params=(int(sd), int(ed)))
    conn.close()
    df = df[df["code"].isin(valid)]
    df["identifier"] = df["code"].str[2:] + "." + df["market"].str.upper()
    fetched = {}
    for identifier, grp in df.groupby("identifier"):
        grp = grp.sort_values("trade_date")
        grp["trade_date"] = pd.to_datetime(grp["trade_date"].astype(str), format="%Y%m%d")
        grp = grp.set_index("trade_date")
        grp = grp[["open", "high", "low", "close", "volume", "amount"]]
        for col in grp.columns:
            grp[col] = pd.to_numeric(grp[col], errors="coerce")
        fetched[identifier] = grp[grp["close"].notna()]
    return fetched

def to_wide(fetched, field="close"):
    items = [(k, df[field].rename(k)) for k, df in fetched.items() if field in df.columns]
    return pd.concat([s for _, s in items], axis=1)

def factor4(panel):
    c = panel["close"]
    v = panel["volume"]
    h = panel["high"]
    vrr = rank(v / v.rolling(20).mean()) * -1
    vv = rank(-v.rolling(10).std() * c.rolling(5).corr(v))
    cvc = rank(-rank(c).rolling(5).cov(rank(v)))
    hvc = rank(-h.rolling(5).corr(rank(v)))
    return rank(sum(rank(f) for f in [vrr, vv, cvc, hvc]))

def run_bt(f, prices):
    dates = [d for d in f.index if d >= pd.Timestamp("2026-01-01")]
    rb = set(dates)
    f = f.shift(1)
    cash = 1_000_000
    holdings = {}
    trades = []
    daily = []

    for i, date in enumerate(dates):
        if date in rb and i > 0:
            vals = f.loc[date].dropna()
            if len(vals) < 5:
                continue
            ranked = vals.sort_values(ascending=False)

            for code in list(holdings.keys()):
                if code in ranked.index:
                    if ranked.index.get_loc(code) + 1 <= 5:
                        continue
                sh = holdings[code]
                px = prices.loc[date, code]
                if np.isnan(px) or px <= 0:
                    cash += 0.0
                else:
                    sp = px * (1 - SLIPPAGE)
                    proc = sh * sp
                    comm = proc * COMMISSION
                    st = proc * STAMP
                    cash += proc - comm - st
                    trades.append({"date": date, "code": code, "qty": -sh})
                del holdings[code]

            cur = set(holdings.keys())
            buy_list = ranked.index[~ranked.index.isin(cur)][:5 - len(cur)]
            n = len(buy_list)
            if n > 0:
                buy_val = cash * 0.97 / n
            for code in buy_list:
                px = prices.loc[date, code]
                if np.isnan(px) or px <= 0:
                    continue
                bp = px * (1 + SLIPPAGE)
                sh = int(buy_val / bp) if n > 0 else 0
                if sh <= 0:
                    continue
                cost = sh * bp
                comm = cost * COMMISSION
                if cost + comm > cash:
                    continue
                cash -= cost + comm
                holdings[code] = sh
                trades.append({"date": date, "code": code, "qty": sh})

        nav = cash + sum(sh * prices.loc[date, c] for c, sh in holdings.items() if not np.isnan(prices.loc[date, c]))
        daily.append({"date": date, "value": nav, "n": len(holdings)})

    return pd.DataFrame(daily).set_index("date"), trades

if __name__ == "__main__":
    t0 = time.time()
    print("Loading 2025-12 + 2026 ...")
    raw = load_data("2025-12-01", "2026-07-01")
    c = to_wide(raw, "close")
    o = to_wide(raw, "open")
    h_v = to_wide(raw, "high")
    v = to_wide(raw, "volume")
    print(f"Fetched stocks: {len(raw)}")
    print(f"Close cols: {c.shape[1]}, Open cols: {o.shape[1]}")
    panel = {"close": c, "open": o, "high": h_v, "volume": v}
    print(f"Loaded: {c.shape[1]} stocks x {c.shape[0]} days ({time.time()-t0:.0f}s)")

    print("Computing factor ...")
    f = factor4(panel)

    print("Running backtest ...")
    df, trades = run_bt(f, c)

    df["ret"] = df["value"].pct_change()
    tr = df["value"].iloc[-1] / df["value"].iloc[0] - 1
    sharpe = df["ret"].mean() / df["ret"].std() * np.sqrt(252) if df["ret"].std() > 0 else 0
    mdd = (df["value"] / df["value"].cummax() - 1).min()

    print(f"\n=== Top5 4因子 2026年上半年 ===")
    print(f"  初始: 1,000,000")
    print(f"  终值: {df['value'].iloc[-1]:.0f}")
    print(f"  TR: {tr:.2%}")
    print(f"  Sharpe: {sharpe:.3f}")
    print(f"  MDD: {mdd:.2%}")
    print(f"  交易次数: {len(trades)}")

    m = df.groupby(df.index.to_period("M"))["value"].apply(lambda s: s.iloc[-1] / s.iloc[0] - 1)
    print(f"\n  月度收益:")
    for mi, v in m.items():
        print(f"    {mi}: {v:.2%}")

    print(f"\n  NAV曲线最低5日:")
    df["peak"] = df["value"].cummax()
    df["dd"] = df["value"] / df["peak"] - 1
    worst = df.nsmallest(5, "dd")
    for d, row in worst.iterrows():
        print(f"    {d.date()}: {row['value']:.0f} DD={row['dd']:.2%}")

    print(f"\nTime: {time.time()-t0:.0f}s")
