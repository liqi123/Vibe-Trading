"""找出纯OHLCV但未测试的GTJA因子, 按主题分组。"""
import ast
from pathlib import Path
from collections import defaultdict

OHLCV_COLS = {"open", "high", "low", "close", "volume", "amount"}

TESTED_MY_ZOOS = [
    "my_volume_ratio_reversal", "my_high_volume_corr", "my_close_volume_cov",
    "my_volume_volatility", "my_price_structure", "my_volume_momentum",
    "my_mom_vol_divergence", "my_intraday_reversal", "my_gap_reversal",
    "my_distance_from_high", "my_volume_acceleration", "my_close_open_volume",
    "my_momentum_trend", "my_open_weighted_momentum", "my_vwap_range_position",
    "my_open_vs_vwap", "my_trend_acceleration",
    "my_auction_vol_ratio", "my_pe_value", "my_margin_sentiment",
    "my_main_flow", "my_main_net_flow",
]

zoo = Path(__file__).resolve().parent.parent / "src" / "factors" / "zoo" / "gtja191"

by_theme = defaultdict(list)
for f in sorted(zoo.glob("alpha_*.py")):
    src = f.read_text(encoding="utf-8")
    tree = ast.parse(src)
    meta = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__alpha_meta__":
                    meta = ast.literal_eval(node.value)
    if meta is None:
        continue
    cols = set(meta.get("columns_required", []))
    extras = set(meta.get("extras_required", []))
    # 纯OHLCV: 所需列全是OHLCV, 且无需外部数据
    if not cols.issubset(OHLCV_COLS):
        continue
    if extras:
        continue
    aid = meta["id"]
    themes = meta.get("theme", ["unknown"])
    for th in themes:
        by_theme[th].append((aid, meta.get("formula_latex", ""), f.stem))

print(f"OHLCV-only GTJA factors by theme (191 total):\n")
for theme in ["momentum", "volatility", "microstructure", "liquidity", "sentiment", "volume", "reversal"]:
    items = by_theme.get(theme, [])
    if not items:
        continue
    print(f"\n{'='*60}")
    print(f"  {theme.upper()}  ({len(items)} factors)")
    print(f"{'='*60}")
    for aid, formula, stem in sorted(items):
        print(f"  {stem:20s} {formula[:70]}")
