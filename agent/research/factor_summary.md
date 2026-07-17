# 5因子研究成果

## 因子配方

| 因子 | 类别 | 公式 |
|---|---|---|
| `volume_ratio_reversal` | 量比反转 | `rank(volume / volume_20d_mean) * -1` |
| `volume_volatility` | 量价稳定性 | `rank(-volume_10d_std * close_5d_corr(volume))` |
| `close_volume_cov` | 收盘量协方差 | `rank(-rank(close)_5d_cov(rank(volume)))` |
| `high_volume_corr` | 高价量相关性 | `rank(-high_5d_corr(rank(volume)))` |
| `ts_gap_momentum` | 缺口动量 | `rank(open / prev_close - 1)` 仅1天窗口有效 |

合成: `rank(sum(rank(f) for f in [vrr, vv, cvc, hvc, gap]))`

## IC验证 (2023-01 ~ 2025-07)

| 指标 | 值 |
|---|---|
| 日频IC均值 | 0.049 |
| t统计量 | 12.18 |
| IC>0占比 | 68.4% |
| 半年度通过率 | 5/5 |

## 回测结果 (100万初始, 2023-01 ~ 2025-07)

### 无成本(基准)

| 配置 | TR | AR | Sharpe | MDD | TO/yr |
|---|---|---|---|---|---|
| 日频 Top20 | +353.9% | 88.4% | 2.08 | -31% | 4189x |
| 日频 Top30 | +189.9% | 56.1% | 1.61 | -32% | 6245x |
| 周频 Top30 | +14.2% | 5.7% | 0.34 | -36% | 1508x |
| 月频 Top30 | -20.2% | -9.0% | -0.14 | -45% | 355x |

### 有成本(万2.5佣金+万5印花+0.1%滑点)

| 配置 | TR | AR | Sharpe | MDD | TO/yr |
|---|---|---|---|---|---|
| **日频 Top20** | **+5.7%** | **2.3%** | **0.24** | **-55%** | 4189x |
| 日频 Top30 | -32.0% | -14.9% | -0.37 | -60% | 6245x |
| 周频 Top30 | -19.5% | -8.7% | -0.16 | -43% | 1508x |
| 月频 Top30 | -26.5% | -12.1% | -0.25 | -47% | 355x |
| Market EW | — | 6.48% | — | — | — |

## 结论

1. 信号质量极高: 日频IC=0.049 (t=12.18), 无成本年化88%
2. 信号周期极短: 仅1-2天有效, 月频/周频均失效
3. 交易成本瓶颈: 日频Top20换手4189x/年, 单边成本~0.175%, 吃掉98%的alpha
4. 仅有配置(日频Top20)在实盘约+2.3%年化, 跑输市场EW(6.48%)
5. 该因子适合作为信号过滤器/持仓调仓依据, 不适合独立高频交易

## 文件位置

- 因子代码: `src/factors/zoo/my_zoos/volume_volatility.py`, `volume_ratio_reversal.py`, `close_volume_cov.py`, `high_volume_corr.py`, `ts_gap_momentum.py`
- 调优脚本: `scripts/tune_gap_composite.py`
- 回测脚本: `scripts/backtest_composite.py`
