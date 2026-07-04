import akshare as ak
# Get industry board list
df = ak.stock_board_industry_name_em()
print("Columns:", list(df.columns))
print("Sample:")
print(df.head(3))
print("Total industries:", len(df))
