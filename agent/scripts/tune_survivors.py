""": baby: 4幸存因子精调 —— 窗口参数 + 阈值门控 + 分量剥离。

运行: python scripts/tune_survivors.py
输出: output/tune_survivors/results.csv + stdout 汇总
"""

from __future__ import annotations

import itertools
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.factors.base import rank, ts_corr, ts_cov, ts_std, ts_mean
from src.data_loader import load_panel

OUT = Path("output/tune_survivors")
OUT.mkdir(parents=True, exist_ok=True)

PERIOD = ("2023-01-01", "2025-07-01")


# ├──────────────────────────────────────────┐
# │   tuning 单体工厂                         │
# └──────────────────────────────────────────┘

def tune_volume_ratio(panel, label="volume_ratio"):
    """Vary MA window + volume-percentile gate."""
    c = panel["close"] if "close" in panel else None
    v = panel["volume"]
    rows = []
    for w in [10, 20, 30, 40, 60]:
        ma = ts_mean(v, w)
        ratio = v / ma.replace(0, np.nan)
        raw = -rank(ratio)
        label_base = f"{label}_ma{w}"
        rows.append(_eval(raw, f"{label_base}"))
        for thresh in [0.0, 0.7, 0.8, 0.9]:
            gate = raw.where(ratio > thresh, np.nan) if thresh > 0 else raw
            rows.append(_eval(gate, f"{label_base}_gate{thresh:.0%}"))
    return pd.DataFrame(rows)


def tune_volume_volatility(panel, label="vol_vol"):
    """Vary std/corr windows + component isolation + gate."""
    c = panel["close"]
    v = panel["volume"]
    rows = []
    for std_w in [5, 10, 20]:
        for corr_w in [3, 5, 10]:
            v_std = ts_std(v, std_w)
            cv_corr = ts_corr(c, v, corr_w)
            combined = -v_std * cv_corr
            rows.append(_eval(combined, f"{label}_s{std_w}c{corr_w}"))
            for thresh in [0.0, 0.7, 0.8]:
                ma = ts_mean(v, 20)
                ratio = v / ma.replace(0, np.nan)
                gated = combined.where(ratio > thresh, np.nan) if thresh > 0 else combined
                tag = f"{label}_s{std_w}c{corr_w}_gate{thresh:.0%}"
                rows.append(_eval(gated, tag))
    return pd.DataFrame(rows)


def tune_close_volume_cov(panel, label="cv_cov"):
    """Vary cov window + gate."""
    c = panel["close"]
    v = panel["volume"]
    rows = []
    for w in [3, 5, 10, 20]:
        cv = ts_cov(rank(c), rank(v), w)
        raw = -rank(cv)
        rows.append(_eval(raw, f"{label}_w{w}"))
        for thresh in [0.0, 0.7, 0.8]:
            ma = ts_mean(v, 20)
            ratio = v / ma.replace(0, np.nan)
            gated = raw.where(ratio > thresh, np.nan) if thresh > 0 else raw
            rows.append(_eval(gated, f"{label}_w{w}_gate{thresh:.0%}"))
    return pd.DataFrame(rows)


def tune_high_volume_corr(panel, label="hv_corr"):
    """Vary corr window + try close/volume vs high/volume + gate."""
    v = panel["volume"]
    rows = []
    for price_col, price_name in [("high", "hv"), ("close", "cv")]:
        p = panel[price_col]
        for w in [3, 5, 10, 20]:
            raw = -ts_corr(p, rank(v), w)
            rows.append(_eval(raw, f"{label}_{price_name}_w{w}"))
            for thresh in [0.0, 0.7, 0.8]:
                ma = ts_mean(v, 20)
                ratio = v / ma.replace(0, np.nan)
                gated = raw.where(ratio > thresh, np.nan) if thresh > 0 else raw
                tag = f"{label}_{price_name}_w{w}_gate{thresh:.0%}"
                rows.append(_eval(gated, tag))
    return pd.DataFrame(rows)


def tune_corr_components(panel, label="vol_vol_parts"):
    """Isolate std part and corr part of volume_volatility."""
    c = panel["close"]
    v = panel["volume"]
    rows = []
    for std_w in [5, 10, 20]:
        v_std = ts_std(v, std_w)
        rows.append(_eval(-rank(v_std), f"stdonly_w{std_w}"))
    for corr_w in [3, 5, 10]:
        cv_corr = ts_corr(c, v, corr_w)
        rows.append(_eval(-cv_corr, f"corronly_w{corr_w}"))
    return pd.DataFrame(rows)


# ├──────────────────────────────────────────┐
# │   估值                                                  │
# └──────────────────────────────────────────┘

def _eval(factor: pd.DataFrame, label: str) -> dict:
    """Compute daily IC, t-stat, IC+%."""
    next_ret = _forward_ret
    dates = factor.columns
    ret = next_ret[dates]
    vals = factor.values
    ret_vals = ret.values
    ic_list = []
    n_list = []
    for i in range(vals.shape[1]):
        x = vals[:, i]
        y = ret_vals[:, i]
        mask = ~(np.isnan(x) | np.isnan(y))
        n = mask.sum()
        if n < 30:
            continue
        ic, _ = spearmanr(x[mask], y[mask])
        ic_list.append(ic)
        n_list.append(n)
    n_obs = len(ic_list)
    if n_obs < 5:
        return dict(label=label, ic_mean=0.0, ir=0.0, ic_plus=0.0, t=0.0, n=0)
    ic_arr = np.array(ic_list)
    ic_mean = float(np.mean(ic_arr))
    ic_std = float(np.std(ic_arr, ddof=1))
    ir = ic_mean / ic_std if ic_std > 0 else 0.0
    t = ic_mean * np.sqrt(n_obs) / ic_std if ic_std > 0 else 0.0
    ic_plus = float(np.mean(ic_arr > 0))
    return dict(label=label, ic_mean=round(ic_mean, 5), ir=round(ir, 4),
                ic_plus=round(ic_plus, 3), t=round(t, 3), n=n_obs)


# ├──────────────────────────────────────────┐
#   main
# └──────────────────────────────────────────┘

if __name__ == "__main__":
    print(f" Loading {PERIOD} ...")
    panel = load_panel("all-a-share", PERIOD[0], PERIOD[1])
    print(f" Panel: {len(panel['close'])} stocks x {panel['close'].shape[1]} days")

    ohlc = panel.get("ohlcv") or panel
    c = ohlc["close"]
    v = ohlc["volume"]

    next_ret = c.pct_change().shift(-1)
    global _forward_ret
    _forward_ret = next_ret
    assert isinstance(next_ret, pd.DataFrame)

    all_rows = []

    t0 = time.time()
    all_rows += tune_volume_ratio(panel)
    all_rows += tune_volume_volatility(panel)
    all_rows += tune_close_volume_cov(panel)
    all_rows += tune_high_volume_corr(panel)
    all_rows += tune_corr_components(panel)

    # 原始因子 baseline
    for fn, label in [
        (lambda p: -rank(p["volume"] / ts_mean(p["volume"], 20)), "ratio_reversal_baseline"),
        (lambda p: -ts_std(p["volume"], 10) * ts_corr(p["close"], p["volume"], 5), "vol_vol_baseline"),
        (lambda p: -rank(ts_cov(rank(p["close"]), rank(p["volume"]), 5)), "cv_cov_baseline"),
        (lambda p: -ts_corr(p["high"], rank(p["volume"]), 5), "hv_corr_baseline"),
    ]:
        f = fn(panel)
        all_rows.append(_eval(f, label))

    df = pd.DataFrame(all_rows)
    df = df.sort_values("ic_mean", ascending=False).reset_index(drop=True)

    print(f"\n Done in {time.time() - t0:.0f}s\n")
    print(f"{'Rank':<5} {'Label':<40} {'IC_mean':<10} {'IR':<8} {'IC+%':<8} {'t':<8} {'n':<6}")
    print("-" * 90)
    for i, r in df.iterrows():
        mark = " \u2705" if r["t"] > 2.0 else ""
        print(f"{i+1:<5} {r['label']:<40} {r['ic_mean']:<10} {r['ir']:<8} {r['ic_plus']:<8} {r['t']:<8} {r['n']:<6}{mark}")

    df.to_csv(OUT / "results.csv", index=False)
    print(f"\n Saved to {OUT / 'results.csv'}")
