import urllib.request, json

names = [
    'RPT_SECTOR_TRADE',
    'RPT_INDUSTRY_TRADE_LATEST',
    'RPT_BOARD_TRADE_STAT',
    'RPT_SECTOR_FUND_FLOW',
    'RPT_INDUSTRY_BOARD_RANKING',
    'RPT_MAIN_CAPITAL_FLOW_INDUSTRY',
]
for name in names:
    url = f'https://datacenter-web.eastmoney.com/api/data/v1/get?reportName={name}&columns=ALL&pageNumber=1&pageSize=2&source=WEB&client=WEB'
    try:
        req = urllib.request.Request(url, headers={'User-Agent':'Mozilla/5.0'})
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        success = data.get('success')
        msg = data.get('message', '')[:60]
        result = data.get('result')
        count = len(result.get('data', [])) if result and result.get('data') else 0
        print(f'{name}: success={success} count={count} msg={msg}')
    except Exception as e:
        print(f'{name}: error={e}')
