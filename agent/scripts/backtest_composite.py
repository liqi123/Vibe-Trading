"""5因子回测: 频率+持仓+过滤优化。
用法: python scripts/backtest_composite.py
"""
from __future__ import annotations
import sys, time, json
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.tools.alpha_bench_tool import _load_universe_panel
from src.factors.base import rank

PERIOD = ("2023-01-01", "2026-07-01")
COMMISSION = 0.00025
STAMP = 0.0005
SLIPPAGE = 0.001

def compute_factor(panel, use_gap=True):
    c = panel["close"].astype(float)
    v = panel["volume"]
    o = panel["open"].astype(float)
    h = panel["high"].astype(float)
    vrr = rank(v / v.rolling(20).mean()) * -1
    vv = rank(-v.rolling(10).std() * c.rolling(5).corr(v))
    cvc = rank(-rank(c).rolling(5).cov(rank(v)))
    hvc = rank(-h.rolling(5).corr(rank(v)))
    factors = [vrr, vv, cvc, hvc]
    if use_gap:
        factors.append(rank(o / c.shift(1) - 1))
    return rank(sum(rank(f) for f in factors))

def make_market_filter(bmk, sma_period):
    if sma_period is None:
        return None
    sma = bmk.rolling(sma_period).mean()
    def ok(date):
        return date in sma.index and bmk.loc[date] > sma.loc[date]
    return ok

def run_bt(factor, prices, top_n=3, sell_buf=3, freq="D",
           min_hold=1, nav_dd_stop=None, market_ok=None, use_costs=True):
    dates = factor.index
    f = factor.shift(1)
    rb = dates.to_series().iloc[21:]
    rb = set(pd.DatetimeIndex(rb[rb >= dates[21]].values))

    cash = 1_000_000
    peak = 1_000_000
    stopped = False
    holdings = {}
    trade_dates = {}
    trades = []
    daily = []

    for i, date in enumerate(dates):
        nav = cash
        if not stopped:
            nav += sum(h["shares"] * prices.loc[date, c]
                      for c, h in holdings.items()
                      if not np.isnan(prices.loc[date, c]))
        peak = max(peak, nav)

        # strategy-level DD stop
        if nav_dd_stop is not None and not stopped:
            if peak - nav > nav_dd_stop * peak:
                stopped = True
                for code, h in list(holdings.items()):
                    px = prices.loc[date, code]
                    if np.isnan(px) or px <= 0:
                        continue
                    sp = px * (1 - SLIPPAGE) if use_costs else px
                    proc = h["shares"] * sp
                    comm = proc * (COMMISSION if use_costs else 0)
                    st = proc * (STAMP if use_costs else 0)
                    cash += proc - comm - st
                    trades.append({"date": date, "code": code, "qty": -h["shares"], "price": sp})
                holdings.clear()
                trade_dates.clear()

        # market filter
        if market_ok is not None and not stopped and not market_ok(date):
            for code, h in list(holdings.items()):
                px = prices.loc[date, code]
                if np.isnan(px) or px <= 0:
                    cash += 0.0
                else:
                    sp = px * (1 - SLIPPAGE) if use_costs else px
                    proc = h["shares"] * sp
                    comm = proc * (COMMISSION if use_costs else 0)
                    st = proc * (STAMP if use_costs else 0)
                    cash += proc - comm - st
                    trades.append({"date": date, "code": code, "qty": -h["shares"], "price": sp})
                del holdings[code]
            trade_dates.clear()

        if not stopped and date in rb and i > 0:
            vals = f.loc[date].dropna()
            if len(vals) < max(top_n, sell_buf):
                daily.append({"date": date, "value": nav, "n": len(holdings)})
                continue
            ranked = vals.sort_values(ascending=False)

            for code in list(holdings.keys()):
                held_days = i - trade_dates.get(code, i)
                if code in ranked.index:
                    r = ranked.index.get_loc(code) + 1
                    if r <= sell_buf:
                        continue
                    if held_days < min_hold:
                        continue
                h = holdings[code]
                px = prices.loc[date, code]
                if np.isnan(px) or px <= 0:
                    cash += 0.0
                else:
                    sp = px * (1 - SLIPPAGE) if use_costs else px
                    proc = h["shares"] * sp
                    comm = proc * (COMMISSION if use_costs else 0)
                    st = proc * (STAMP if use_costs else 0)
                    cash += proc - comm - st
                    trades.append({"date": date, "code": code, "qty": -h["shares"], "price": sp})
                del holdings[code]
                trade_dates.pop(code, None)

            cur = set(holdings.keys())
            candidates = ranked.index[~ranked.index.isin(cur)][:top_n - len(cur)]
            n = len(candidates)
            if n > 0:
                buy_val = cash * 0.97 / n
            for code in candidates:
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
                holdings[code] = {"shares": sh, "entry_px": bp}
                trade_dates[code] = i
                trades.append({"date": date, "code": code, "qty": sh, "price": bp})

        daily.append({"date": date, "value": nav, "n": len(holdings)})

    df = pd.DataFrame(daily).set_index("date")
    tr = df["value"].iloc[-1] / df["value"].iloc[0] - 1
    df["ret"] = df["value"].pct_change()
    yrs = len(df) / 252
    ar = (1 + tr) ** (1 / yrs) - 1
    shp = df["ret"].mean() / df["ret"].std() * np.sqrt(252) if df["ret"].std() > 0 else 0
    mdd = (df["value"] / df["value"].cummax() - 1).min()
    yr = df.groupby(df.index.year)["value"].apply(lambda s: s.iloc[-1] / s.iloc[0] - 1)
    return {"tr": tr, "ar": ar, "sharpe": shp, "mdd": mdd,
            "trades": len(trades), "to": len(trades) / 2 / yrs,
            "yr": yr.to_dict(), "daily": df}

if __name__ == "__main__":
    t0 = time.time()
    period = sys.argv[1] if len(sys.argv) > 1 else f"{PERIOD[0]}/{PERIOD[1]}"
    print(f"Loading {period} ...")
    panel = _load_universe_panel("all-a-share", period)
    c = panel["close"].astype(float)
    print(f"Panel: {c.shape[1]} stocks x {c.shape[0]} days ({time.time()-t0:.0f}s)")

    factor5 = compute_factor(panel, use_gap=True)
    factor4 = compute_factor(panel, use_gap=False)

    bmk_cols = [x for x in c.columns if "000001" in x]
    bmk = c[bmk_cols[0]] if bmk_cols else None

    bt4 = run_bt(factor4, c, top_n=5, sell_buf=5, use_costs=True)
    bt5 = run_bt(factor5, c, top_n=5, sell_buf=5, use_costs=True)

    df = bt4["daily"]
    df["ret"] = df["value"].pct_change()

    print(f"\n=== Top5 4因子 总览 ===")
    print(f"  TR={bt4['tr']:.2%}  AR={bt4['ar']:.2%}  Sharpe={bt4['sharpe']:.3f}  MDD={bt4['mdd']:.2%}")
    for yr, v in sorted(bt4["yr"].items()):
        print(f"  {yr}: {v:.2%}")

    print(f"\n=== 2026年明细 ===")
    df26 = df[df.index >= "2026-01-01"]
    tr26 = df26["value"].iloc[-1] / df26["value"].iloc[0] - 1
    max_dd26 = (df26["value"] / df26["value"].cummax() - 1).min()
    sharpe26 = df26["ret"].mean() / df26["ret"].std() * np.sqrt(252) if df26["ret"].std() > 0 else 0

    # Monthly returns for 2026
    m26 = df26.groupby(df26.index.to_period("M"))["value"].apply(lambda s: s.iloc[-1] / s.iloc[0] - 1)
    mkt26 = c.loc[df26.index].pct_change().mean(axis=1)
    mkt_m26 = mkt26.groupby(mkt26.index.to_period("M")).apply(lambda s: (1+s).prod()-1)

    print(f"  TR={tr26:.2%}  Sharpe={sharpe26:.3f}  MDD={max_dd26:.2%}  #Trades={bt4['trades']}")
    print(f"  {'Month':<10} {'组合':<12} {'市场EW':<12}")
    for m in m26.index:
        print(f"  {m:<10} {m26[m]:<+10.2%}   {mkt_m26[m]:<+10.2%}" if m in mkt_m26.index else f"  {m:<10} {m26[m]:<+10.2%}")

    # Holdings in 2026
    print(f"\n=== 2026年6月最后5个交易日持仓 ===")
    h26 = bt4["daily"][bt4["daily"].index >= "2026-06-01"]
    for date, row in h26.iterrows():
        if row["n"] > 0:
            print(f"  {date.date()}: {int(row['n'])}只  NAV={row['value']:.0f}")

    print(f"\n\n=== Top5 5因子 对比 ===")
    df5 = bt5["daily"]
    df5_26 = df5[df5.index >= "2026-01-01"]
    tr5_26 = df5_26["value"].iloc[-1] / df5_26["value"].iloc[0] - 1
    print(f"  2026: TR={tr5_26:.2%}")
    for yr, v in sorted(bt5["yr"].items()):
        print(f"  {yr}: {v:.2%}")

    print(f"\nMarket EW AR: {(1+c.pct_change().mean(axis=1)).prod()**(252/len(c))-1:.2%}")
    print(f"Time: {time.time()-t0:.0f}s")
