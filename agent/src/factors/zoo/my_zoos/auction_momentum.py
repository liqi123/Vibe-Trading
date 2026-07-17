from __future__ import annotations

import numpy as np
import pandas as pd

from src.factors.base import rank, safe_div

__alpha_meta__ = {
    "id": "my_auction_momentum",
    "nickname": "竞价动量 — auction_gap + vol_ratio + price_slippage 三维合成",
    "theme": ["momentum", "microstructure"],
    "formula_latex": "RANK(auction_gap) + RANK(vol_ratio) - RANK(price_slippage)",
    "columns_required": [
        "open", "close", "amount",
        "fund:auction_vol", "fund:auction_amount", "fund:auction_price",
    ],
    "extras_required": [],
    "requires_sector": False,
    "universe": ["equity_cn"],
    "frequency": ["1d"],
    "decay_horizon": 1,
    "min_warmup_bars": 5,
    "notes": (
        "集合竞价三维合成因子: "
        "(1)竞价涨幅: (auction_price/prev_close-1) 隔夜多空力量; "
        "(2)竞价量比: auction_vol / MA5(auction_vol) 参与者参与度; "
        "(3)开盘滑点: (open-auction_price)/auction_price 竞价到开盘的信息消耗。"
        "低滑点+高量比+强竞价涨幅=强势延续信号。"
    ),
}


def compute(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    c = panel["close"].astype(float)
    o = panel["open"].astype(float)
    amt = panel["amount"].astype(float)

    auction_vol = panel.get("fund:auction_vol")
    auction_amount = panel.get("fund:auction_amount")
    auction_price = panel.get("fund:auction_price")

    if auction_vol is None or auction_price is None:
        return rank(o / c.shift(1) - 1)

    prev_c = c.shift(1)
    gap = safe_div(auction_price - prev_c, prev_c)
    f1 = rank(gap.fillna(0))

    av_ma5 = auction_vol.rolling(5, min_periods=2).mean()
    vol_ratio = safe_div(auction_vol, av_ma5)
    f2 = rank(vol_ratio.fillna(0))

    slippage = abs(safe_div(o - auction_price, auction_price))
    f3 = -rank(slippage.fillna(0))

    if auction_amount is not None:
        amt_ratio = safe_div(auction_amount * 10000, amt)
        f4 = rank(amt_ratio.fillna(0))
        composite = (f1 + f2 + f3 + f4) / 4.0
    else:
        composite = (f1 + f2 + f3) / 3.0

    return composite
