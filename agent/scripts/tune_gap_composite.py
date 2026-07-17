"""调优: gap_momentum窗口 + 5因子IC加权合成 → 长周期验证。"""
from __future__ import annotations

import sys, time
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.tools.alpha_bench_tool import _load_universe_panel
from src.factors.base import rank

PERIOD_SLICES = {
    "2023-H1": ("2023-01-01", "2023-07-01"),
    "2023-H2": ("2023-07-01", "2024-01-01"),
    "2024-H1": ("2024-01-01", "2024-07-01"),
    "2024-H2": ("2024-07-01", "2025-01-01"),
    "2025-H1": ("2025-01-01", "2025-07-01"),
}

def eval_factor(factor: pd.DataFrame, ret: pd.DataFrame) -> dict:
    ic_list = []
    for d in factor.index:
        if d not in ret.index:
            continue
        x = factor.loc[d].values
        y = ret.loc[d].values
        mask = ~(np.isnan(x) | np.isnan(y))
        n = mask.sum()
        if n < 30:
            continue
        ic, _ = spearmanr(x[mask], y[mask])
        if not np.isnan(ic):
            ic_list.append(ic)
    n_obs = len(ic_list)
    if n_obs < 5:
        return dict(ic_mean=0.0, ir=0.0, ic_plus=0.0, t=0.0, n=0)
    ic_arr = np.array(ic_list)
    ic_mean = float(np.mean(ic_arr))
    ic_std = float(np.std(ic_arr, ddof=1))
    t = ic_mean * np.sqrt(n_obs) / ic_std if ic_std > 0 else 0
    return dict(ic_mean=ic_mean, ir=ic_mean/ic_std if ic_std > 0 else 0,
                ic_plus=float(np.mean(ic_arr > 0)), t=t, n=n_obs)

def compute_gap(panel, lookback: int):
    o = panel["open"].astype(float)
    c = panel["close"].astype(float)
    gap = o / c.shift(lookback) - 1
    return rank(gap)

def compute_vrr(panel):
    v = panel["volume"]
    return -rank(v / v.rolling(20).mean())

def compute_vv(panel):
    c = panel["close"].astype(float)
    v = panel["volume"]
    v_std = v.rolling(10).std()
    cv_corr = c.rolling(5).corr(v)
    return -v_std * cv_corr

def compute_cvc(panel):
    c = rank(panel["close"].astype(float))
    v = rank(panel["volume"])
    return -rank(c.rolling(5).corr(v))  # simplified: corr not cov

def compute_hvc(panel):
    return -panel["high"].astype(float).rolling(5).corr(rank(panel["volume"]))

if __name__ == "__main__":
    t0 = time.time()
    print("Loading 2023-01-01/2025-07-01 ...")
    panel = _load_universe_panel("all-a-share", "2023-01-01/2025-07-01")
    c = panel["close"]
    ret = c.pct_change().shift(-1)
    print(f"Panel: {c.shape[1]} stocks x {c.shape[0]} days ({time.time()-t0:.0f}s)")

    # 1. gap_momentum 窗口调优
    print("\n===== gap_momentum 窗口调优 =====")
    gap_results = []
    for lb in [1, 2, 3, 5, 10, 20]:
        fac = compute_gap(panel, lb)
        for label, (s, e) in PERIOD_SLICES.items():
            idx = fac.index[(fac.index >= s) & (fac.index < e)]
            if len(idx) < 10:
                continue
            r = eval_factor(fac.loc[idx], ret)
            gap_results.append({**r, "lookback": lb, "period": label})
    df_gap = pd.DataFrame(gap_results)
    print(f"{'lookback':<10} {'period':<12} {'IC_mean':<10} {'IR':<8} {'t':<8} {'IC+%':<8} {'n':<6}")
    for lb in sorted(df_gap["lookback"].unique()):
        sub = df_gap[df_gap["lookback"] == lb]
        passes = (sub["t"] > 2.0).sum()
        mean_ic = sub["ic_mean"].mean()
        print(f"  LB={lb:<4} passes={passes}/5  avg_IC={mean_ic:.5f}")

    # 找出最佳窗口
    best_lb = df_gap.groupby("lookback")["t"].mean().idxmax()
    print(f"\nBest gap lookback: {best_lb} (avg t={df_gap.groupby('lookback')['t'].mean().max():.3f})")

    # 2. 5因子合成
    print("\n===== 5因子合成 =====")
    print("Computing factors ...")
    facs = {
        "vrr": compute_vrr(panel),
        "vv": compute_vv(panel),
        "cvc": compute_cvc(panel),
        "hvc": compute_hvc(panel),
        "gap": compute_gap(panel, best_lb),
    }

    # Period-by-period IC计算 + 权重
    ic_table = {}
    for fname, fac in facs.items():
        ic_table[fname] = {}
        for label, (s, e) in PERIOD_SLICES.items():
            idx = fac.index[(fac.index >= s) & (fac.index < e)]
            r = eval_factor(fac.loc[idx], ret)
            ic_table[fname][label] = r["ic_mean"]

    df_ic = pd.DataFrame(ic_table).T
    print("\nPeriod IC table:")
    print(df_ic.round(5))

    # Equal weight composite
    print("\n--- Equal weight composite ---")
    ew = sum(facs.values()) / len(facs)
    for label, (s, e) in PERIOD_SLICES.items():
        idx = ew.index[(ew.index >= s) & (ew.index < e)]
        r = eval_factor(ew.loc[idx], ret)
        mark = " PASS" if r["t"] > 2.0 else ""
        print(f"  {label}: IC={r['ic_mean']:.5f} t={r['t']:.2f} IC+%={r['ic_plus']:.3f}{mark}")

    # IC-weighted composite (using prev period IC)
    print("\n--- IC-weighted composite ---")
    periods = list(PERIOD_SLICES.keys())
    for pi in range(1, len(periods)):
        label = periods[pi]
        prev_label = periods[pi-1]
        weights = np.array([abs(ic_table[f][prev_label]) for f in facs])
        w_sum = weights.sum()
        if w_sum > 0:
            weights = weights / w_sum
        else:
            weights = np.ones(len(facs)) / len(facs)
        weighted = sum(w * facs[f] for w, f in zip(weights, facs.keys()))
        s, e = PERIOD_SLICES[label]
        idx = weighted.index[(weighted.index >= s) & (weighted.index < e)]
        r = eval_factor(weighted.loc[idx], ret)
        mark = " PASS" if r["t"] > 2.0 else ""
        print(f"  {label}: IC={r['ic_mean']:.5f} t={r['t']:.2f} IC+%={r['ic_plus']:.3f}  weights={np.round(weights,3)}{mark}")

    # Full-period EW composite
    print("\n--- Full-period EW composite ---")
    r = eval_factor(ew, ret)
    print(f"  2023-2025: IC={r['ic_mean']:.5f} t={r['t']:.2f} IC+%={r['ic_plus']:.3f} n={r['n']}")

    print(f"\nTotal: {time.time()-t0:.0f}s")
