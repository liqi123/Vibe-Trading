"""分析Top10回撤来源：大盘vs组合对比。
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.tools.alpha_bench_tool import _load_universe_panel
from src.factors.base import rank

def compute_factor(panel):
    c = panel["close"].astype(float)
    v = panel["volume"]
    o = panel["open"].astype(float)
    h = panel["high"].astype(float)
    vrr = rank(v / v.rolling(20).mean()) * -1
    vv = rank(-v.rolling(10).std() * c.rolling(5).corr(v))
    cvc = rank(-rank(c).rolling(5).cov(rank(v)))
    hvc = rank(-h.rolling(5).corr(rank(v)))
    gap = rank(o / c.shift(1) - 1)
    return rank(sum(rank(f) for f in [vrr, vv, cvc, hvc, gap]))

COMMISSION = 0.00025
STAMP = 0.0005
SLIPPAGE = 0.001

def run_bt_verbose(factor, prices, top_n=10, use_costs=True):
    dates = factor.index
    f = factor.shift(1)
    rb = set(pd.DatetimeIndex(dates.to_series().iloc[21:][dates.to_series().iloc[21:] >= dates[21]].values))

    cash = 1_000_000
    holdings = {}
    trades = []
    daily = []

    for i, date in enumerate(dates):
        if date in rb and i > 0:
            vals = f.loc[date].dropna()
            if len(vals) < top_n:
                continue
            ranked = vals.sort_values(ascending=False)

            for code in list(holdings.keys()):
                if code in ranked.index:
                    r = ranked.index.get_loc(code) + 1
                    if r <= top_n:
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
                holdings[code] = {"shares": sh, "entry_px": bp}

        nav = cash + sum(h["shares"] * prices.loc[date, c]
                        for c, h in holdings.items()
                        if not np.isnan(prices.loc[date, c]))
        daily.append({"date": date, "nav": nav, "n": len(holdings)})

    return pd.DataFrame(daily).set_index("date")

if __name__ == "__main__":
    panel = _load_universe_panel("all-a-share", "2023-01-01/2025-07-01")
    c = panel["close"].astype(float)
    print("Computing factor ...")
    factor = compute_factor(panel)

    # 找大盘指数
    bmk_cols = [x for x in c.columns if "000001" in x]
    bmk = c[bmk_cols[0]] if bmk_cols else None
    sh = bmk / bmk.iloc[0] * 1_000_000

    df = run_bt_verbose(factor, c, top_n=10, use_costs=True)
    df["bmk"] = sh.loc[df.index]
    df["ret"] = df["nav"].pct_change()
    df["peak"] = df["nav"].cummax()
    df["dd"] = df["nav"] / df["peak"] - 1

    print(f"\nTop10 与大盘对比 (100万起):")
    print(f"  最终组合: {df['nav'].iloc[-1]:.0f}")
    print(f"  最终大盘: {df['bmk'].iloc[-1]:.0f}")
    print(f"  最大回撤: {df['dd'].min():.1%}")

    # 回撤期间分析
    dd_peak = df["dd"].idxmin()
    print(f"\n最大回撤发生在: {dd_peak.date()}")
    peak_date = df.loc[:dd_peak, "peak"].idxmax()
    print(f"  从峰值{peak_date.date()}开始")
    print(f"  期间组合: {df.loc[peak_date, 'nav']:.0f} → {df.loc[dd_peak, 'nav']:.0f}")
    print(f"  期间大盘: {df.loc[peak_date, 'bmk']:.0f} → {df.loc[dd_peak, 'bmk']:.0f}")

    # 找出回撤最大的几个区间
    dd_start = None
    dd_periods = []
    for date, row in df.iterrows():
        if row["nav"] == row["peak"]:
            if dd_start is not None:
                dd_periods.append((dd_start, date, (df.loc[dd_start, "nav"] / df.loc[date, "nav"] - 1)))
            dd_start = None
        elif dd_start is None and row["dd"] < -0.15:
            dd_start = date
    if dd_start is not None:
        dd_periods.append((dd_start, df.index[-1], (df.loc[dd_start, "nav"] / df.loc[df.index[-1], "nav"] - 1)))

    dd_periods.sort(key=lambda x: x[2])
    print(f"\n最大3次回撤(>15%):")
    for s, e, d in dd_periods[:3]:
        bmk_ret = df.loc[e, "bmk"] / df.loc[s, "bmk"] - 1
        print(f"  {s.date()} → {e.date()}: 组合{d:.1%}, 大盘{bmk_ret:.1%}")

    # 组合持仓的日收益分布
    print(f"\n组合日收益统计:")
    print(f"  均值: {df['ret'].mean():.4f}")
    print(f"  标准差: {df['ret'].std():.4f}")
    print(f"  日最大涨: {df['ret'].max():.1%}")
    print(f"  日最大跌: {df['ret'].min():.1%}")
    print(f"  胜率: {(df['ret'] > 0).mean():.1%}")
