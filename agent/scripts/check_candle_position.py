""":microscope: 验证 my_candle_position 跨周期稳定性。
用法: python scripts/check_candle_position.py
"""
from __future__ import annotations

import sys, time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.tools.alpha_bench_tool import _load_universe_panel
from src.factors.zoo.my_zoos.candle_position import compute as candle_compute
from src.factors.zoo.my_zoos.volume_ratio_reversal import compute as vrr_compute

PERIOD_SLICES = {
    "2023-H1": ("2023-01-01", "2023-07-01"),
    "2023-H2": ("2023-07-01", "2024-01-01"),
    "2024-H1": ("2024-01-01", "2024-07-01"),
    "2024-H2": ("2024-07-01", "2025-01-01"),
    "2025-H1": ("2025-01-01", "2025-07-01"),
}

def eval_factor(factor: pd.DataFrame, ret: pd.DataFrame) -> dict:
    dates = factor.index
    ic_list = []
    for d in dates:
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
        return dict(ic_mean=0, ir=0, ic_plus=0, t=0, n=0)
    ic_arr = np.array(ic_list)
    ic_mean = float(np.mean(ic_arr))
    ic_std = float(np.std(ic_arr, ddof=1))
    t = ic_mean * np.sqrt(n_obs) / ic_std if ic_std > 0 else 0
    return dict(
        ic_mean=round(ic_mean, 5), ir=round(ic_mean/ic_std, 4) if ic_std > 0 else 0,
        ic_plus=round(float(np.mean(ic_arr > 0)), 3), t=round(t, 3), n=n_obs
    )

if __name__ == "__main__":
    t0 = time.time()
    print("Loading 2023-01-01/2025-07-01 ...")
    panel = _load_universe_panel("all-a-share", "2023-01-01/2025-07-01")
    ohlc = panel.get("ohlcv") or panel
    c = ohlc["close"]
    next_ret = c.pct_change().shift(-1)
    print(f"Panel: {c.shape[1]} stocks x {c.shape[0]} days ({time.time()-t0:.0f}s)")

    print("Computing factors ...")
    fac_cp = candle_compute(panel)
    fac_vrr = vrr_compute(panel)
    print(f"  candle_position: {fac_cp.shape},  vrr: {fac_vrr.shape}")

    results = []
    for label, (s, e) in PERIOD_SLICES.items():
        idx = fac_cp.index[(fac_cp.index >= s) & (fac_cp.index < e)]
        if len(idx) < 10:
            print(f"  {label}: no data")
            continue
        r_cp = eval_factor(fac_cp.loc[idx], next_ret)
        r_vrr = eval_factor(fac_vrr.loc[idx], next_ret)
        r_cp["factor"] = "my_candle_position"
        r_cp["period"] = label
        r_vrr["factor"] = "my_volume_ratio_reversal"
        r_vrr["period"] = label
        results.extend([r_cp, r_vrr])
        print(f"  {label}: candle IC={r_cp['ic_mean']:.5f} t={r_cp['t']:.2f} ({r_cp['n']}d)"
              f"  vrr IC={r_vrr['ic_mean']:.5f} t={r_vrr['t']:.2f} ({r_vrr['n']}d)")

    df = pd.DataFrame(results)
    print(f"\n{'='*90}")
    print(f"{'Factor':<25} {'Period':<10} {'IC_mean':<10} {'IR':<8} {'IC+%':<8} {'t':<8} {'n':<6}")
    print(f"{'='*90}")
    for _, r in df.iterrows():
        mark = " PASS" if r["t"] > 2.0 else ""
        print(f"{r['factor']:<25} {r['period']:<10} {r['ic_mean']:<10} {r['ir']:<8} {r['ic_plus']:<8} {r['t']:<8} {r['n']:<6}{mark}")

    print(f"\nDone in {time.time()-t0:.0f}s")
