import sys
sys.path.insert(0, "C:/Users/XYXS/trading")
from utils.sector_utils import get_industry_map, calc_sector_momentum
print("Testing get_industry_map...")
m = get_industry_map()
print(f"Industry map size: {len(m)}")
if m:
    items = list(m.items())[:5]
    print(f"Sample: {items}")
print("\nTesting calc_sector_momentum...")
result = calc_sector_momentum("20260703")
print(f"Momentum result: {len(result)} sectors")
if result:
    top5 = sorted(result.items(), key=lambda x: x[1], reverse=True)[:5]
    print(f"Top 5: {top5}")
