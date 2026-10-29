"""Читает страницу «Реестр подтоплений» (HTML, данные внутри скрипта `const DATA = {...}`) и приводит её к записям по домам.

  python3 tools/flood_parse.py <реестр.html>     — печатает сводку и совпадение с домами капремонта

Для страницы капремонта (tools/build_kr.py --flood <реестр.html>) из реестра берутся только цифры и сроки: обращения в АДС и ГИС ЖКХ,
претензии по организациям, ответы по категориям, повторные подтопления и рекомендованные действия. Тексты обращений, ответов и фамилии
сотрудников на страницу не попадают."""
import collections, json, pathlib, re, sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from srcnorm import addr_key

ORGS = [('vodokanal', 'Водоканал'), ('uzhkh', 'Управление ЖКХ'), ('gzhi', 'ГЖИ'), ('prokuratura', 'Прокуратура'), ('teplo', 'Теплосеть'), ('tplus', 'Т Плюс')]
# сокращения и опечатки в адресах перечня капремонта и реестра: приводим к одному написанию
ALIAS = [(r'^м\.?\s*шоссе', 'московское шоссе'), (r'^з\.?\s*бульвар', 'западный бульвар'), (r'^к\.?\s*либк\w*', 'карла либкнехта'),
         (r'^л\.?\s*шевцовой', 'шевцовой'), (r'^ульяны громовой', 'громовой'), (r'^улица громовой', 'громовой')]


def key(addr):
    s = re.sub(r'\(.*?\)', ' ', str(addr)).replace('?', ' ')
    s = re.sub(r'\s+', ' ', s).strip().lower().replace('ё', 'е')
    for rx, rep in ALIAS:
        s = re.sub(rx, rep, s)
    s = re.sub(r'(\d)([а-я])к(\d)', r'\1\2 к\3', s)      # «54бк2» -> «54б к2»
    s = re.sub(r'-\d+п$', '', s)                          # «-2п» (подъезд) в реестре
    return '|'.join(addr_key(s))


def load(path):
    html = pathlib.Path(path).read_text(encoding='utf-8', errors='replace')
    m = re.search(r'const DATA\s*=\s*', html)
    if not m:
        raise SystemExit('В файле нет данных реестра (const DATA = …): это не страница «Реестр подтоплений».')
    D, _ = json.JSONDecoder().raw_decode(html[m.end():])
    if 'addresses' not in D or 'summary' not in D:
        raise SystemExit('В данных реестра нет разделов summary и addresses.')
    return D


def record(a, rec, acts):
    orgs, cats = [], collections.Counter()
    for k, name in ORGS:
        cl = a.get(k) or []
        if not cl:
            continue
        orgs.append(dict(key=k, name=name, sent=len(cl), answered=sum(1 for c in cl if c['answered']), withdrawn=sum(1 for c in cl if c['withdrawn']),
                         pending=sum(1 for c in cl if not c['answered'] and not c['withdrawn'])))
        for c in cl:
            cat = (c.get('answer') or {}).get('cat')
            if cat:
                cats[cat] += 1
    repeat = None
    if rec:
        sig = (rec.get('signals') or [None])[-1]
        repeat = dict(cycles=rec.get('cycles'), fix_date=rec.get('fix_date'), days=rec.get('days_to_repeat'), blame=bool(rec.get('fix_blame')),
                      last_signal=dict(date=sig['date'], kind=sig.get('kind')) if sig else None)
    return dict(name=a['address'], total=a['total'], ads=a['ads_count'], gis=a['gis_total'], gis_answered=a['gis_answered'], gis_pending=a['gis_pending'],
                first=a['first_date'], last=a['last_date'], orgs=orgs, cats=dict(cats), repeat=repeat,
                actions=[dict(prio=x['prio'], group=x['group'], text=x['text'][:260]) for x in sorted(acts, key=lambda x: x['prio'])])


def read(path):
    D = load(path)
    recs = {r['address']: r for r in D.get('recurrence', [])}
    acts = collections.defaultdict(list)
    for x in D.get('actions', []):
        acts[x['address']].append(x)
    by = {}
    for a in D['addresses']:
        k = key(a['address'])
        r = record(a, recs.get(a['address']), acts.get(a['address'], []))
        if k.endswith('|') or k not in by and False:
            continue                                      # адрес без номера дома («Западный бульвар (номер дома не указан)»)
        if k in by:                                        # один дом записан дважды («Полбина 14» и «Проспект Полбина 14») — складываем
            o = by[k]
            for f in ('total', 'ads', 'gis', 'gis_answered', 'gis_pending'):
                o[f] += r[f]
            o['first'] = min(o['first'], r['first'], key=lambda d: d.split('.')[::-1])
            o['last'] = max(o['last'], r['last'], key=lambda d: d.split('.')[::-1])
            for org in r['orgs']:
                t = next((x for x in o['orgs'] if x['key'] == org['key']), None)
                if t:
                    for f in ('sent', 'answered', 'withdrawn', 'pending'):
                        t[f] += org[f]
                else:
                    o['orgs'].append(org)
            for c, n in r['cats'].items():
                o['cats'][c] = o['cats'].get(c, 0) + n
            o['repeat'] = o['repeat'] or r['repeat']
            o['actions'] += r['actions']
        else:
            by[k] = r
    s = D['summary']
    meta = dict(updated=s['updated'], period_start=s['period_start'], period_end=s['period_end'], register_addresses=s['total_addr'], register_total=s['total_obr'],
                register_pending=s['pending_total'], cats=D.get('answer_quality', {}).get('cats', {}))
    return meta, by


if __name__ == '__main__':
    meta, by = read(sys.argv[1])
    print(meta['updated'], '| адресов в реестре:', meta['register_addresses'], '| обращений:', meta['register_total'], '| домов с номером:', len(by))
    try:
        import kr_parse
        pos, _, _ = kr_parse.read(sys.argv[2]) if len(sys.argv) > 2 else ([], None, None)
        for p in pos:
            r = by.get(key(p['addr']))
            print(('  ✔' if r else '  ✘'), p['addr'][:32].ljust(32), r and (r['total'], r['gis_pending'], bool(r['repeat'])))
    except SystemExit:
        pass
