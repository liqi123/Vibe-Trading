"""因子在2025年的表现诊断: IC分年+子因子贡献。
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.tools.alpha_bench_tool import _load_universe_panel
from src.factors.base import rank

PERIOD = ("2023-01-01", "2025-07-01")

def compute_all_factors(panel):
    c = panel["close"].astype(float)
    v = panel["volume"]
    o = panel["open"].astype(float)
    h = panel["high"].astype(float)

    factors = {}
    # 4 survivors
    factors["vrr"] = rank(v / v.rolling(20).mean()) * -1
    factors["vv"] = rank(-v.rolling(10).std() * c.rolling(5).corr(v))
    factors["cvc"] = rank(-rank(c).rolling(5).cov(rank(v)))
    factors["hvc"] = rank(-h.rolling(5).corr(rank(v)))
    # gap momentum
    factors["gap"] = rank(o / c.shift(1) - 1)
    # 合成
    factors["composite"] = rank(sum(rank(f) for f in factors.values()))
    return factors, c

def ic_series(factor, returns):
    """每日截面IC (Spearman rank)."""
    f = factor.shift(1)
    dates = f.index.intersection(returns.index)
    ics = []
    for d in dates:
        fv = f.loc[d].dropna()
        rv = returns.loc[d].dropna()
        common = fv.index.intersection(rv.index)
        if len(common) < 50:
            continue
        ics.append((d, fv[common].corr(rv[common], method="spearman")))
    return pd.DataFrame(ics, columns=["date", "ic"]).set_index("date")

if __name__ == "__main__":
    panel = _load_universe_panel("all-a-share", f"{PERIOD[0]}/{PERIOD[1]}")
    rets = panel["close"].astype(float).pct_change().shift(-1)  # next day return
    c = panel["close"].astype(float)

    print("Computing factors ...")
    factors, _ = compute_all_factors(panel)

    # 逐年IC
    for name, f in factors.items():
        ic_df = ic_series(f, rets)
        # 去掉2025年过滤掉2025-01-01之前的数据
        ic_df = ic_df[ic_df.index >= "2023-01-01"]
        print(f"\n{'='*60}")
        print(f"  {name}")
        print(f"{'='*60}")
        for yr in ["2023", "2024", "2025"]:
            yr_ic = ic_df[ic_df.index.year == int(yr)]["ic"]
            if len(yr_ic) == 0:
                print(f"    {yr}: 无数据")
                continue
            mean_ic = yr_ic.mean()
            t_stat = mean_ic / (yr_ic.std() / np.sqrt(len(yr_ic))) if yr_ic.std() > 0 else 0
            pct_pos = (yr_ic > 0).mean()
            print(f"    {yr}: IC={mean_ic:.4f} t={t_stat:.2f} IC+%=>{pct_pos:.1%} n={len(yr_ic)}")

    # 月度IC热力图
    print(f"\n{'='*60}")
    print(f"  月度IC (composite)")
    print(f"{'='*60}")
    ic_df = ic_series(factors["composite"], rets)
    ic_df = ic_df[ic_df.index >= "2023-01-01"]
    for yr in ["2023", "2024", "2025"]:
        yr_df = ic_df[ic_df.index.year == int(yr)]
        month_ics = yr_df.groupby(yr_df.index.month)["ic"].mean()
        row = f"  {yr}: "
        for m in range(1, 13):
            if m in month_ics.index:
                row += f"{m:2d}月={month_ics[m]:+.3f}  "
        print(row)

    # 2025年回撤期间IC
    dd_periods = [
        ("2025-01-03", "2025-02-12"),
        ("2025-03-31", "2025-05-29"),
    ]
    print(f"\n{'='*60}")
    print(f"  2025回撤期IC")
    print(f"{'='*60}")
    for s, e in dd_periods:
        seg = ic_df[s:e]
        print(f"  {s} → {e}: IC={seg['ic'].mean():.4f} t={seg['ic'].mean()/(seg['ic'].std()/np.sqrt(len(seg))):.2f}")

    # 子因子在2025年的IC对比
    print(f"\n{'='*60}")
    print(f"  各子因子2024 vs 2025 IC对比")
    print(f"{'='*60}")
    print(f"  {'Factor':<12} {'2024 IC':<10} {'2025 IC':<10} {'变化':<10}")
    print(f"  {'-'*42}")
    for name, f in factors.items():
        ic_df = ic_series(f, rets)
        ic_2024 = ic_df[ic_df.index.year == 2024]["ic"].mean()
        ic_2025 = ic_df[ic_df.index.year == 2025]["ic"].mean()
        chg = ic_2025 - ic_2024
        print(f"  {name:<12} {ic_2024:<+.4f}     {ic_2025:<+.4f}     {chg:<+.4f}")
