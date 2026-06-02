import adata

res_df = adata.stock.market.get_market(stock_code='000001', k_type=1, start_date='2026-05-01')
print(res_df)