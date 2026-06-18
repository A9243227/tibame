from playwright.sync_api import sync_playwright
import re

with sync_playwright() as p:
    ctx = p.request.new_context(base_url='https://www.trec.org.tw')
    res = ctx.get('/certification')
    token = re.search(r'<meta name="csrf-token" content="([^"]+)">', res.text()).group(1)
    res2 = ctx.post('/certification/data', headers={'X-CSRF-TOKEN': token, 'X-Requested-With': 'XMLHttpRequest'}, form={'draw': '1', 'start': '0', 'length': '1', 'year': '2020'})
    data = res2.json()
    detail = data['data'][0]['detail']
    id = re.search(r'data-case="([^"]+)"', detail).group(1)
    year = re.search(r'data-year="([^"]+)"', detail).group(1)
    date = re.search(r'data-date="([^"]+)"', detail).group(1)
    res3 = ctx.post('/certification/detail', headers={'X-CSRF-TOKEN': token, 'X-Requested-With': 'XMLHttpRequest'}, form={'id': id, 'year': year, 'date': date})
    
    modal_html = res3.text()
    fields = re.findall(r'<label>(.*?)</label>\s*<div>(.*?)</div>', modal_html, re.DOTALL | re.IGNORECASE)
    parsed_data = {}
    for key_html, val_html in fields:
        key = re.sub(r'<[^>]+>', '', key_html).strip()
        val = re.sub(r'<[^>]+>', '', val_html).strip()
        parsed_data[key] = val
        
    import pprint
    print(parsed_data)
