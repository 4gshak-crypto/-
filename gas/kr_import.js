/* Чтение перечня работ по капремонту (.xls/.xlsx) и реестра подтоплений (.html) в браузере.
   Порт tools/kr_parse.py и tools/flood_parse.py: результат должен совпадать с Python (проверка: tools/test_kr_import.js).
   Нужны TrackerMerge (gas/merge.js) и библиотека чтения Excel, переданная в TrackerMerge.setLib().
   Править здесь; build.py вставляет файл в Index.html между метками krimport:start и krimport:end. */
var KrImport = (function () {
  'use strict';
  var TM = null;
  function init(tm) { TM = tm || TrackerMerge; }
  var HEAD = [['work', 'решение'], ['kr', 'сумма кр'], ['bank', 'аванс из банка'], ['contractor', 'основной подрядчик'], ['sec', 'сумма по разделам'],
    ['executor', 'исполнитель'], ['pay', 'аванс/'], ['start', 'график начала'], ['end', 'срок окончания'], ['contract', 'сумма договора'], ['pct', 'процент'], ['fact', 'фактическая']];
  var PHONE = /\(?\s*(?:\+7|8)[\s-]?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\s*\)?/g;
  var mask = function (t) { return typeof t === 'string' ? t.replace(PHONE, '(тел. скрыт)') : t; };
  var p2 = function (n) { return (n < 10 ? '0' : '') + n; };
  var iso = function (d) { return d.getUTCFullYear() + '-' + p2(d.getUTCMonth() + 1) + '-' + p2(d.getUTCDate()); };
  var dmyTxt = function (d) { return p2(d.getUTCDate()) + '.' + p2(d.getUTCMonth() + 1) + '.' + d.getUTCFullYear(); };

  function textSum(v) {   // «450т.р+438т.р» -> 888000
    var s = TM.sp(v).toLowerCase().replace(/ /g, '');
    if (!/^(\d+(?:[.,]\d+)?)т\.?р\.?(?:\+(\d+(?:[.,]\d+)?)т\.?р\.?)*$/.test(s)) return null;
    var t = 0, m, re = /(\d+(?:[.,]\d+)?)т\.?р/g;
    while ((m = re.exec(s))) t += parseFloat(m[1].replace(',', '.'));
    return t * 1000;
  }

  // срок -> [дата ГГГГ-ММ-ДД | null, подпись]; «4кв 2026» — конец квартала (для начала — его начало), «2027» — конец года
  function parseTerm(v, edge, xls) {
    var d;
    if (v instanceof Date) { d = v; return [iso(d), dmyTxt(d)]; }
    if (typeof v === 'number' && v > 40000 && v < 60000) { d = new Date(Math.round((v - 25569) * 86400) * 1000); return [iso(d), dmyTxt(d)]; }
    if (typeof v === 'number' && v >= 2000 && v <= 2100 && v === Math.floor(v)) return [(edge === 'start' ? v + '-01-01' : v + '-12-31'), v + ' г.'];
    var s = TM.sp(v, xls);
    if (!s) return [null, ''];
    var m = /^(\d{2})\.(\d{2})\.(\d{4})$/.exec(s);
    if (m) return [m[3] + '-' + m[2] + '-' + m[1], s];
    m = /^(\d)\s*кв\.?\s*(\d{4})$/i.exec(s);
    if (m) {
      var q = +m[1], y = +m[2], mm = q * 3;
      return [edge === 'start' ? y + '-' + p2(mm - 2) + '-01' : iso(new Date(Date.UTC(y, mm, 0))), q + ' кв. ' + y];
    }
    return [null, s];
  }

  // сокращения и опечатки в адресах перечня и реестра -> одно написание (ключ дома)
  var ALIAS = [[/^м\.?\s*шоссе/, 'московское шоссе'], [/^з\.?\s*бульвар/, 'западный бульвар'], [/^к\.?\s*либк[а-я]*/, 'карла либкнехта'],
    [/^л\.?\s*шевцовой/, 'шевцовой'], [/^ульяны громовой/, 'громовой'], [/^улица громовой/, 'громовой']];
  function houseKey(addr) {
    var s = String(addr).replace(/\(.*?\)/g, ' ').split('?').join(' ');
    s = s.replace(/\s+/g, ' ').trim().toLowerCase().split('ё').join('е');
    ALIAS.forEach(function (a) { s = s.replace(a[0], a[1]); });
    s = s.replace(/(\d)([а-я])к(\d)/g, '$1$2 к$3').replace(/-\d+п$/, '');
    return TM.addrKey(s).join('|');
  }

  /* ---------- перечень работ ---------- */
  function readList(buf) {
    var wb = TM.open(buf), xls = wb.__xls, s = new TM.Sheet(wb.Sheets[wb.SheetNames[0]]);
    var sp = function (v) { return TM.sp(v, xls); }, num = TM.num, hr = -1, r, c, i;
    for (r = 0; r < s.nrows; r++) if (sp(s.val(r, 0)).toLowerCase() === 'адрес') { hr = r; break; }
    if (hr < 0) throw new Error('В файле нет строки заголовков с «Адрес» в первой колонке: это не перечень работ капремонта.');
    var col = { addr: 0 };
    for (c = 0; c < s.ncols; c++) {
      var h = sp(s.val(hr, c)).toLowerCase();
      HEAD.forEach(function (k) { if (h.indexOf(k[1]) >= 0 && col[k[0]] === undefined) col[k[0]] = c; });
    }
    var miss = ['work', 'kr', 'contractor', 'executor', 'start', 'end'].filter(function (k) { return col[k] === undefined; });
    if (miss.length) throw new Error('В перечне не найдены колонки: ' + miss.join(', ') + '. Проверьте, что выбран файл перечня капремонта.');
    var val = function (r, k) { return col[k] === undefined ? null : s.val(r, col[k]); };
    var pos = [], cur = null, total = null, warnings = [];
    for (r = hr + 1; r < s.nrows; r++) {
      var any = false;
      for (c = 0; c < s.ncols; c++) if (sp(s.val(r, c))) { any = true; break; }
      if (!any) continue;
      var addr = sp(val(r, 'addr'));
      if (!addr && !sp(val(r, 'work')) && num(val(r, 'kr')) && r === s.nrows - 1) { total = { kr: num(val(r, 'kr')), bank: num(val(r, 'bank')) }; continue; }
      if (addr) {
        cur = { id: pos.length, row: r + 1, addr: mask(addr), kr: null, bank: null, contractor: '', executor: '', pay: null, contract: null, pct: null, state: '',
          start: null, start_txt: '', end: null, end_txt: '', vote: false, notes: [], fill: s.fill(r, col.addr), hk: houseKey(addr), lines: [] };
        pos.push(cur);
      }
      if (!cur) continue;
      ['kr', 'bank', 'pay', 'contract'].forEach(function (k) {
        if (col[k] === undefined) return;
        var v = num(val(r, k));
        if (v !== null) cur[k] = k === 'contract' ? (cur[k] || 0) + v : (cur[k] !== null ? cur[k] : v);
      });
      if (col.pct !== undefined && cur.pct === null && !cur.state) {
        var pv = val(r, 'pct');
        if (num(pv) !== null) cur.pct = num(pv); else if (sp(pv)) cur.state = sp(pv);
      }
      ['contractor', 'executor'].forEach(function (k) { var t = sp(val(r, k)); if (t && !cur[k]) cur[k] = t; });
      ['start', 'end'].forEach(function (k) {
        if (cur[k] === null && !cur[k + '_txt']) { var t = parseTerm(val(r, k), k, xls); cur[k] = t[0]; cur[k + '_txt'] = t[1]; }
      });
      var work = sp(val(r, 'work')), sec = num(val(r, 'sec')), secTxt = sec === null ? sp(val(r, 'sec')) : '';
      if (sec === null && secTxt) {
        sec = textSum(secTxt);
        if (sec !== null) { cur.notes.push('сумма по разделу записана текстом: «' + secTxt + '»'); secTxt = ''; }
      }
      var cancelled = sp(val(r, 'contractor')).toLowerCase() === 'отмена';
      if (work || sec || secTxt) cur.lines.push({ row: r + 1, work: mask(work || '(без названия)'), sum: sec, sum_txt: secTxt, contract: num(val(r, 'contract')), cancelled: cancelled && !!work });
      if (cancelled && !work) cur.notes.push('в колонке «Основной подрядчик» стоит «отмена»');
    }
    pos.forEach(function (p) {
      var txt = [p.executor, p.contractor, p.state].concat(p.lines.map(function (l) { return l.work + ' ' + l.sum_txt; })).join(' ').toLowerCase();
      p.vote = txt.indexOf('переголос') >= 0;
      if (p.executor.toLowerCase().indexOf('переголос') >= 0) p.executor = '';
      p.lines.forEach(function (l) { if (l.sum_txt.toLowerCase().indexOf('переголос') >= 0) l.sum_txt = ''; });
    });
    if (!total && s.nrows) {
      var last = s.row(s.nrows - 1);
      if (!sp(last[0]) && num(last[col.kr])) total = { kr: num(last[col.kr]), bank: col.bank !== undefined ? num(last[col.bank]) : null };
    }
    if (!pos.length) throw new Error('В перечне не найдено ни одной позиции.');
    var sumKr = pos.reduce(function (a, p) { return a + (p.kr || 0); }, 0);
    if (total && Math.abs(total.kr - sumKr) > 1) warnings.push('Сумма КР по позициям (' + Math.round(sumKr).toLocaleString('ru-RU') + ' ₽) не совпала с итоговой строкой файла (' + Math.round(total.kr).toLocaleString('ru-RU') + ' ₽): проверьте файл.');
    if (col.pct === undefined) warnings.push('В файле нет колонки «процент выполнения»: этапы работ определить нельзя.');
    return { positions: pos, total: total, warnings: warnings };
  }

  /* ---------- реестр подтоплений ---------- */
  function jsonAt(text, from) {   // JSON-объект, начинающийся с первой «{» после from
    var i = text.indexOf('{', from), depth = 0, inStr = false, esc = false, j;
    for (j = i; j < text.length; j++) {
      var ch = text.charAt(j);
      if (inStr) { if (esc) esc = false; else if (ch === '\\') esc = true; else if (ch === '"') inStr = false; continue; }
      if (ch === '"') inStr = true; else if (ch === '{') depth++; else if (ch === '}') { depth--; if (!depth) return JSON.parse(text.slice(i, j + 1)); }
    }
    throw new Error('Данные реестра обрываются: файл повреждён.');
  }
  var ORGS = [['vodokanal', 'Водоканал'], ['uzhkh', 'Управление ЖКХ'], ['gzhi', 'ГЖИ'], ['prokuratura', 'Прокуратура'], ['teplo', 'Теплосеть'], ['tplus', 'Т Плюс']];
  var dkey = function (d) { return d.split('.').reverse().join(''); };

  function readFlood(html) {
    var m = /const DATA\s*=\s*/.exec(html);
    if (!m) throw new Error('В файле нет данных реестра (const DATA = …): это не страница «Реестр подтоплений».');
    var D = jsonAt(html, m.index + m[0].length);
    if (!D.addresses || !D.summary) throw new Error('В данных реестра нет разделов summary и addresses.');
    var recs = {}, acts = {}, by = {};
    (D.recurrence || []).forEach(function (r) { recs[r.address] = r; });
    (D.actions || []).forEach(function (x) { (acts[x.address] = acts[x.address] || []).push(x); });
    D.addresses.forEach(function (a) {
      var orgs = [], cats = {};
      ORGS.forEach(function (o) {
        var cl = a[o[0]] || [];
        if (!cl.length) return;
        orgs.push({ key: o[0], name: o[1], sent: cl.length, answered: cl.filter(function (c) { return c.answered; }).length, withdrawn: cl.filter(function (c) { return c.withdrawn; }).length,
          pending: cl.filter(function (c) { return !c.answered && !c.withdrawn; }).length });
        cl.forEach(function (c) { var cat = c.answer && c.answer.cat; if (cat) cats[cat] = (cats[cat] || 0) + 1; });
      });
      var rec = recs[a.address], repeat = null;
      if (rec) {
        var sig = (rec.signals || []).slice(-1)[0];
        repeat = { cycles: rec.cycles, fix_date: rec.fix_date, days: rec.days_to_repeat, blame: !!rec.fix_blame, last_signal: sig ? { date: sig.date, kind: sig.kind } : null };
      }
      var r = { name: a.address, total: a.total, ads: a.ads_count, gis: a.gis_total, gis_answered: a.gis_answered, gis_pending: a.gis_pending, first: a.first_date, last: a.last_date,
        orgs: orgs, cats: cats, repeat: repeat,
        actions: (acts[a.address] || []).slice().sort(function (x, y) { return x.prio - y.prio; }).map(function (x) { return { prio: x.prio, group: x.group, text: String(x.text).slice(0, 260) }; }) };
      var k = houseKey(a.address);
      if (/\|$/.test(k)) return;   // адрес без номера дома
      var o = by[k];
      if (o) {   // один дом записан дважды («Полбина 14» и «Проспект Полбина 14») — складываем
        ['total', 'ads', 'gis', 'gis_answered', 'gis_pending'].forEach(function (f) { o[f] += r[f]; });
        if (dkey(r.first) < dkey(o.first)) o.first = r.first;
        if (dkey(r.last) > dkey(o.last)) o.last = r.last;
        r.orgs.forEach(function (org) {
          var t = o.orgs.filter(function (x) { return x.key === org.key; })[0];
          if (t) ['sent', 'answered', 'withdrawn', 'pending'].forEach(function (f) { t[f] += org[f]; }); else o.orgs.push(org);
        });
        Object.keys(r.cats).forEach(function (c) { o.cats[c] = (o.cats[c] || 0) + r.cats[c]; });
        o.repeat = o.repeat || r.repeat;
        o.actions = o.actions.concat(r.actions);
      } else by[k] = r;
    });
    var s = D.summary;
    return { meta: { updated: s.updated, period_start: s.period_start, period_end: s.period_end, register_addresses: s.total_addr, register_total: s.total_obr, register_pending: s.pending_total,
      cats: (D.answer_quality || {}).cats || {} }, by: by };
  }

  /**
   * opts: { list: ArrayBuffer|null, flood: string|null, existing: данные из таблицы|null, today: 'ГГГГ-ММ-ДД', saved: 'ГГГГ-ММ-ДД' }
   * Что не передано, берётся из existing. Возвращает { data, info, warnings }.
   */
  function build(opts) {
    init(opts.tm);
    var E = opts.existing || null, warnings = [], L = null, F = null;
    if (!opts.list && !opts.flood) throw new Error('Выберите хотя бы один файл: перечень работ или реестр подтоплений.');
    if (opts.list) { L = readList(opts.list); warnings = warnings.concat(L.warnings); }
    if (opts.flood) F = readFlood(opts.flood);
    if (!L && !(E && E.positions && E.positions.length)) throw new Error('Реестр подтоплений привязывается к перечню работ: сначала загрузите перечень.');
    var data = {
      today: opts.today, saved: L ? opts.saved : (E && E.saved) || opts.saved, total: L ? L.total : E.total,
      flood: F ? Object.assign({}, F.meta, { by: F.by }) : (E && E.flood) || null,
      positions: L ? L.positions : E.positions
    };
    var hks = {};
    data.positions.forEach(function (p) { hks[p.hk] = 1; });
    var matched = data.flood ? Object.keys(data.flood.by).filter(function (k) { return hks[k]; }).length : 0;
    return { data: data, warnings: warnings, info: { positions: data.positions.length, houses: Object.keys(hks).length, kr: data.positions.reduce(function (a, p) { return a + (p.kr || 0); }, 0),
      floodHouses: matched, floodRegister: data.flood ? Object.keys(data.flood.by).length : 0, fromList: !!L, fromFlood: !!F } };
  }

  return { build: build, readList: readList, readFlood: readFlood, houseKey: houseKey, init: init };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = KrImport;
