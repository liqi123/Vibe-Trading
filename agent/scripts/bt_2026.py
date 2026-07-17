"""2026年因子周频/月频回测"""
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

def to_wide(fetched, field):
    items = [(k, df[field].rename(k)) for k, df in fetched.items() if field in df.columns]
    return pd.concat([s for _, s in items], axis=1)

def make_factor(panel, top_k=3):
    c = panel["close"]
    v = panel["volume"]
    h = panel["high"]
    vv = rank(-v.rolling(10).std() * c.rolling(5).corr(v))
    cvc = rank(-rank(c).rolling(5).cov(rank(v)))
    hvc = rank(-h.rolling(5).corr(rank(v)))
    if top_k == 2:
        return rank(sum(rank(f) for f in [cvc, hvc]))
    return rank(sum(rank(f) for f in [cvc, hvc, vv]))

def run_bt(f, prices, freq="W", top_n=20, use_costs=True):
    all_dates = pd.DatetimeIndex([d for d in f.index if d >= pd.Timestamp("2026-01-01")])
    dates = list(all_dates)
    if freq == "W":
        rb = set(pd.DatetimeIndex(all_dates.to_series().resample("W").first().dropna()))
    elif freq == "M":
        rb = set(pd.DatetimeIndex(all_dates.to_series().groupby(all_dates.to_series().dt.to_period("M")).first().dropna()))
    else:
        rb = set(dates)

    f = f.shift(1)
    cash = 1_000_000
    holdings = {}
    trades = 0
    daily = []

    for i, date in enumerate(dates):
        if date in rb and i > 0:
            vals = f.loc[date].dropna()
            if len(vals) < top_n:
                continue
            ranked = vals.sort_values(ascending=False)

            for code in list(holdings.keys()):
                if code in ranked.index:
                    if ranked.index.get_loc(code) + 1 <= top_n:
                        continue
                sh = holdings[code]
                px = prices.loc[date, code]
                if np.isnan(px) or px <= 0:
                    cash += 0.0
                else:
                    sp = px * (1 - SLIPPAGE) if use_costs else px
                    proc = sh * sp
                    comm = proc * (COMMISSION if use_costs else 0)
                    st = proc * (STAMP if use_costs else 0)
                    cash += proc - comm - st
                    trades += 1
                del holdings[code]

            cur = set(holdings.keys())
            buy_list = ranked.index[~ranked.index.isin(cur)][:top_n - len(cur)]
            n = len(buy_list)
            if n > 0:
                buy_val = cash * 0.97 / n
            for code in buy_list:
                px = prices.loc[date, code]
                if np.isnan(px) or px <= 0:
                    continue
                bp = px * (1 + SLIPPAGE) if use_costs else px
                sh = int(buy_val / bp) if n > 0 else 0
                if sh <= 0:
                    continue
                cost = sh * bp
                comm = cost * (COMMISSION if use_costs else 0)
                if cost + comm > cash:
                    continue
                cash -= cost + comm
                holdings[code] = sh
                trades += 1

        nav = cash + sum(sh * prices.loc[date, c] for c, sh in holdings.items() if not np.isnan(prices.loc[date, c]))
        daily.append({"date": date, "value": nav, "n": len(holdings)})

    df = pd.DataFrame(daily).set_index("date")
    tr = df["value"].iloc[-1] / df["value"].iloc[0] - 1
    df["ret"] = df["value"].pct_change()
    yrs = len(df) / 252
    ar = (1 + tr) ** (1 / yrs) - 1 if yrs > 0 else 0
    shp = df["ret"].mean() / df["ret"].std() * np.sqrt(252) if df["ret"].std() > 0 else 0
    mdd = (df["value"] / df["value"].cummax() - 1).min()
    m = df.groupby(df.index.to_period("M"))["value"].apply(lambda s: s.iloc[-1] / s.iloc[0] - 1)
    return {"tr": tr, "ar": ar, "sharpe": shp, "mdd": mdd, "trades": trades, "monthly": m.to_dict()}

if __name__ == "__main__":
    t0 = time.time()
    print("Loading ...")
    raw = load_data("2025-07-01", "2026-07-01")
    c = to_wide(raw, "close")
    h_v = to_wide(raw, "high")
    v = to_wide(raw, "volume")
    panel = {"close": c, "high": h_v, "volume": v}
    print(f"Loaded: {c.shape[1]} stocks x {c.shape[0]} days ({time.time()-t0:.0f}s)")

    configs = [
        # (label, factors, freq, top_n)
        ("hvc+cvc 周频Top15", 2, "W", 15),
        ("hvc+cvc 周频Top20", 2, "W", 20),
        ("hvc+cvc 月频Top15", 2, "M", 15),
        ("hvc+cvc 月频Top20", 2, "M", 20),
        ("hvc+cvc+vv 周频Top15", 3, "W", 15),
        ("hvc+cvc+vv 周频Top20", 3, "W", 20),
        ("hvc+cvc+vv 月频Top15", 3, "M", 15),
        ("hvc+cvc+vv 月频Top20", 3, "M", 20),
    ]

    print(f"\n{'Config':<30} {'TR':<10} {'AR':<10} {'Sharpe':<10} {'MDD':<10} {'Trades':<10}  Monthly")
    print("=" * 120)
    for label, k, freq, n in configs:
        f = make_factor(panel, top_k=k)
        bt = run_bt(f, c, freq=freq, top_n=n, use_costs=True)
        m_str = " ".join(f"{k}={v:.0%}" for k, v in sorted(bt["monthly"].items()))
        print(f"{label:<30} {bt['tr']:<10.2%} {bt['ar']:<10.2%} {bt['sharpe']:<10.3f} {bt['mdd']:<10.2%} {bt['trades']:<10}  {m_str}")

    # Market
    mkt_ret = c.pct_change().mean(axis=1)
    mkt_ar = (1 + mkt_ret).prod() ** (252 / len(mkt_ret)) - 1
    mkt_m = mkt_ret.groupby(mkt_ret.index.to_period("M")).apply(lambda s: (1+s).prod()-1)
    mkt_m_str = " ".join(f"{k}={v:.0%}" for k, v in sorted(mkt_m[mkt_m.index >= "2026-01"].items()))
    print(f"\n{'Market EW':<30} {'':10} {mkt_ar:<10.2%} {'':8} {'':10}  {mkt_m_str}")
    print(f"\nTime: {time.time()-t0:.0f}s")
