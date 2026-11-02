"""Страница «Капитальный ремонт» из перечня работ (.xls): один HTML-файл, вход не нужен.

  python3 tools/build_kr.py <перечень .xls> [--today ГГГГ-ММ-ДД] [--saved ГГГГ-ММ-ДД]

Пишет reports/Капитальный ремонт <дата>.html (для скачивания) и capital/kr.html (для публикации).
Оформление берётся из gas/Index.html, чтобы страница выглядела так же, как «Текущий ремонт». Этапы определяются по проценту выполнения:
статуса в файле нет."""
import argparse, datetime, json, pathlib, re, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import kr_parse, flood_parse
from srcnorm import addr_key

ROOT = pathlib.Path(__file__).resolve().parent.parent
ap = argparse.ArgumentParser()
ap.add_argument('xls')
ap.add_argument('--today', default=datetime.date.today().isoformat(), help='на какую дату считать сроки')
ap.add_argument('--saved', help='дата сохранения файла (по умолчанию — из его свойств)')
ap.add_argument('--flood', help='страница «Реестр подтоплений» (HTML): добавляет на страницу сведения о подтоплениях по домам')
A = ap.parse_args()

pos, total, col = kr_parse.read(A.xls)
saved = A.saved
if not saved:
    import subprocess
    out = subprocess.run(['file', A.xls], capture_output=True, text=True).stdout   # дата сохранения лежит в свойствах документа
    m = re.search(r'Last Saved Time/Date: \w+ (\w+)\s+(\d+) [\d:]+ (\d{4})', out)
    saved = datetime.datetime.strptime('%s %s %s' % (m.group(1), m.group(2), m.group(3)), '%b %d %Y').date().isoformat() if m else A.today

mask = lambda t: re.sub(r'\(?\s*(?:\+7|8)[\s-]?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\s*\)?', '(тел. скрыт)', t) if isinstance(t, str) else t
iso = lambda d: d.isoformat() if d else None
fmeta, fby = flood_parse.read(A.flood) if A.flood else (None, {})
data = dict(today=A.today, saved=saved, total=total, flood=dict(fmeta, by=fby) if A.flood else None, positions=[])
for i, p in enumerate(pos):
    data['positions'].append(dict(
        id=i, row=p['row'], addr=mask(p['addr']), kr=p['kr'], bank=p['bank'], contractor=p['contractor'], executor=p['executor'], pay=p['pay'], contract=p['contract'],
        pct=p['pct'], state=p['state'], start=iso(p['start']), start_txt=p['start_txt'], end=iso(p['end']), end_txt=p['end_txt'], vote=p['vote'], notes=p['notes'],
        fill=p['fills'][0] if p['fills'] else None, hk=flood_parse.key(p['addr']),
        lines=[dict(row=l['row'], work=mask(l['work']), sum=l['sum'], sum_txt=l['sum_txt'], contract=l['contract'], cancelled=l['cancelled']) for l in p['lines']]))

# оформление — из страницы «Текущий ремонт»
idx = (ROOT / 'gas' / 'Index.html').read_text(encoding='utf-8')
style = idx[idx.index('<style>'):idx.index('</style>') + 8]
dark = re.search(r"@media \(prefers-color-scheme:dark\)\{:root\{(.*?)\}\}", style, re.S)
style = style.replace(dark.group(0), '@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){' + dark.group(1) + '}}\n:root[data-theme="dark"]{' + dark.group(1) + '}')
fonts = re.search(r'<link rel="stylesheet"[^>]+>', idx).group(0)

CSS = '<style>\n.kr-bar-in{max-width:1200px;margin:0 auto;padding:0 16px;display:flex;align-items:center;justify-content:space-between;gap:16px;min-height:56px}\n@media (max-width:720px){.kr-bar-in .brand{display:block}}\n@media print{.bar{position:static}}\n' + (ROOT / 'gas' / 'kr.css').read_text(encoding='utf-8') + '</style>'

BODY = r'''
<header class="bar"><div class="kr-bar-in"><span class="brand">Капитальный ремонт</span></div></header>
<main id="kr"></main>
<script>window.KR=__DATA__;</script>
<script>
__KRJS__
KrView.mount(document.getElementById("kr"),window.KR,{today:window.KR.today});
</script>'''


def page(doc):
    body = BODY.replace('__KRJS__', (ROOT / 'gas' / 'kr.js').read_text(encoding='utf-8').replace('</', '<\\/')).replace('__DATA__', json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/'))
    head = '<title>Капитальный ремонт</title>\n' + fonts + '\n' + style + CSS
    if doc:
        return '<!DOCTYPE html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n' + head + '\n</head>\n<body>\n' + body + '\n</body>\n</html>\n'
    return head + '\n' + body


d = A.today.split('-')
out = ROOT / 'reports' / ('Капитальный ремонт %s.%s.%s.html' % (d[2], d[1], d[0]))
out.parent.mkdir(exist_ok=True)
out.write_text(page(True), encoding='utf-8')
(ROOT / 'capital').mkdir(exist_ok=True)
(ROOT / 'capital' / 'kr.html').write_text(page(False), encoding='utf-8')
(ROOT / 'capital' / 'kr.json').write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding='utf-8')
print(out.name, round(out.stat().st_size / 1024), 'КБ;', len(pos), 'позиций;', len({q['hk'] for q in data['positions']}), 'домов', ('; в реестре подтоплений: %d позиций' % sum(1 for p in data['positions'] if p['hk'] in fby)) if A.flood else '')
