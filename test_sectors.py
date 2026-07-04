import urllib.request

codes = [f'sz3992{i:02d}' for i in range(0, 50)]
url = 'https://qt.gtimg.cn/q=' + ','.join(codes)
resp = urllib.request.urlopen(url, timeout=10)
text = resp.read().decode('gbk', 'replace')
for line in text.strip().split(';'):
    line = line.strip()
    if not line or '=' not in line:
        continue
    raw = line.split('"')[1] if '"' in line else ''
    if not raw or 'pv_none' in raw:
        continue
    fields = raw.split('~')
    if len(fields) > 32:
        code = fields[2]
        name = fields[1]
        price = fields[3]
        change_pct = fields[32]
        print(f'{code} {name} price={price} chg={change_pct}%')
