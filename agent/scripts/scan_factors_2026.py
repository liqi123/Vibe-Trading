"""2026年因子全面扫描"""
from __future__ import annotations
import sys, time, sqlite3
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.factors.base import rank

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

def ic_series(factor, rets):
    f = factor.shift(1)
    dates = f.index.intersection(rets.index)
    ics = []
    for d in dates:
        fv = f.loc[d].dropna()
        rv = rets.loc[d].dropna()
        common = fv.index.intersection(rv.index)
        if len(common) < 50:
            continue
        ics.append(fv[common].corr(rv[common], method="spearman"))
    return pd.Series(ics, index=dates[:len(ics)])

def test_factor(name, factor_series, rets, period):
    ic = ic_series(factor_series, rets)
    ic_period = ic[ic.index >= period[0]]
    if len(ic_period) < 5:
        return None
    mean_ic = ic_period.mean()
    t = mean_ic / (ic_period.std() / np.sqrt(len(ic_period))) if ic_period.std() > 0 else 0
    pos = (ic_period > 0).mean()
    return {"IC": mean_ic, "t": t, "IC+%": pos, "n": len(ic_period)}

if __name__ == "__main__":
    t0 = time.time()
    print("Loading 2025-07 to 2026-07 ...")
    raw = load_data("2025-07-01", "2026-07-01")
    c = to_wide(raw, "close")
    o = to_wide(raw, "open")
    h = to_wide(raw, "high")
    l = to_wide(raw, "low")
    v = to_wide(raw, "volume")
    a = to_wide(raw, "amount")
    print(f"Loaded: {c.shape[1]} stocks x {c.shape[0]} days ({time.time()-t0:.0f}s)")

    rets = c.pct_change().shift(-1)  # next day return
    rets_5d = c.pct_change(5).shift(-5)  # 5-day forward return
    rets_20d = c.pct_change(20).shift(-20)  # 20-day forward return

    period_2026 = (pd.Timestamp("2026-01-01"), pd.Timestamp("2026-07-01"))

    # === Factor zoo ===
    factors = {}

    # --- Time-series momentum / reversal ---
    factors["ret1d"] = rank(-c.pct_change(1))           # short-term reversal
    factors["ret5d"] = rank(-c.pct_change(5))           # 5d reversal
    factors["ret20d"] = rank(c.pct_change(20))           # 20d momentum
    factors["ret60d"] = rank(c.pct_change(60))           # 60d momentum

    # --- volume ---
    factors["vol_1d"] = rank(v.pct_change(1))            # 1d volume change
    factors["vol_5d"] = rank(v / v.rolling(5).mean())    # 5d relative volume
    factors["vol_20d"] = rank(v / v.rolling(20).mean())  # 20d relative volume
    factors["vol_std_20"] = rank(-v.rolling(20).std())   # low volume variability

    # --- volatility ---
    factors["volatility_20"] = rank(-c.pct_change().rolling(20).std())  # low vol
    factors["volatility_5"] = rank(-c.pct_change().rolling(5).std())   # low vol 5d
    factors["range_20"] = rank(-(h - l) / c)              # narrow range (low vol)

    # --- price-level ---
    factors["price_vs_ma20"] = rank(c / c.rolling(20).mean())   # above/below MA
    factors["price_vs_ma60"] = rank(c / c.rolling(60).mean())   # above/below MA60
    factors["near_low_20"] = rank((c - l.rolling(20).min()) / (h.rolling(20).max() - l.rolling(20).min()))  # near high

    # --- volume-price (our survivors) ---
    factors["vrr"] = rank(v / v.rolling(20).mean()) * -1
    factors["vv"] = rank(-v.rolling(10).std() * c.rolling(5).corr(v))
    factors["cvc"] = rank(-rank(c).rolling(5).cov(rank(v)))
    factors["hvc"] = rank(-h.rolling(5).corr(rank(v)))
    factors["gap"] = rank(o / c.shift(1) - 1)

    # --- new combinations ---
    factors["volume_reversal"] = rank(rank(-c.pct_change(1)) * rank(v / v.rolling(20).mean()))
    factors["low_vol_momentum"] = rank(rank(c.pct_change(20)) * rank(-c.pct_change().rolling(20).std()))
    factors["ma_volume_break"] = rank((c > c.rolling(20).mean()).astype(float) * rank(v / v.rolling(20).mean()))

    # --- overnight return ---
    factors["overnight"] = rank((o / c.shift(1) - 1))  # same as gap
    factors["intraday"] = rank((c / o - 1))             # intraday return

    # — 4-factor composite (the survivors) ---
    factors["composite4"] = rank(sum(rank(factors[n]) for n in ["vrr", "vv", "cvc", "hvc"]))

    # --- Test on 2026 ---
    print(f"\n{'Factor':<30} {'IC':<10} {'t':<10} {'IC+%':<10} {'n':<10}")
    print("=" * 70)
    results = []
    for name, f in factors.items():
        r = test_factor(name, f, rets, period_2026)
        if r is not None:
            results.append((name, r))
            print(f"{name:<30} {r['IC']:<+.4f}   {r['t']:<+.2f}   {r['IC+%']:<.1%}     {r['n']:<}")

    results.sort(key=lambda x: abs(x[1]["t"]), reverse=True)

    print(f"\n=== 按 |t| 排序 Top 10 ===")
    print(f"{'Factor':<30} {'IC':<10} {'t':<10} {'IC+%':<10}")
    print("=" * 65)
    for name, r in results[:10]:
        print(f"{name:<30} {r['IC']:<+.4f}   {r['t']:<+.2f}   {r['IC+%']:<.1%}")

    # Test multi-day forward returns for top factors
    print(f"\n=== Top 因子在不同预测周期 ===")
    for name, _ in results[:5]:
        for label, rts in [("1d", rets), ("5d", rets_5d), ("20d", rets_20d)]:
            r = test_factor(name, factors[name], rts, period_2026)
            if r:
                print(f"  {name:<25} {label:<5} IC={r['IC']:<+.4f} t={r['t']:<+.2f}")

    print(f"\nTime: {time.time()-t0:.0f}s")
