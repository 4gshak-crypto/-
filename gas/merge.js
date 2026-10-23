/* Сведение трёх выгрузок Excel в файл обновления трекера.
   Порт tools/merge_sources.py, tools/srcnorm.py и части tools/extract_backlog.py: результат должен совпадать с Python до буквы,
   иначе ключи работ разойдутся и загрузка перестанет находить старые строки. Проверка: tools/test_merge_js.js.
   Работает в браузере и в Node; библиотека чтения Excel (SheetJS) передаётся через setLib().
   Править здесь, а не в Index.html: build.py вставляет этот файл в Index.html между метками merge:start и merge:end. */
var TrackerMerge = (function () {
  'use strict';
  var X = null;
  var W = '[\\p{L}\\p{N}_]';                       // «буква слова» в смысле \w из Python (Юникод)
  var B_BEFORE = '(?<!' + W + ')', B_AFTER = '(?!' + W + ')';
  var MONTHS_RU = { 'Январь': 1, 'Февраль': 2, 'Март': 3, 'Апрель': 4, 'Май': 5, 'Июнь': 6, 'Июль': 7, 'Август': 8,
    'Сентябрь': 9, 'Октябрь': 10, 'Ноябрь': 11, 'Декабрь': 12 };
  var MASTERS = [  // фамилия -> как показывать (порядок важен)
    ['гайдуков', 'Гайдуков А.В.'], ['зеленцов', 'Зеленцов А.В.'], ['сандюк', 'Сандюк Ю.В.'], ['вазюков', 'Вазюков В.С.'],
    ['шарафутдинов', 'Шарафутдинов Р.Р.'], ['евграфов', 'Евграфов С.В.'], ['алиев', 'Алиев Р.Р.'], ['чернов', 'Чернов Р.А.'],
    ['наумова', 'Наумова Т.Ю.'], ['братчинин', 'Братчинин Н.А.'], ['мастер', 'Мастер участка (Север)']];
  var SOURCES = ['exec', 'per', 'plan', 'add', 'bx'];   // порядок при одинаковой дате: позже в списке — свежее

  function setLib(lib) { X = lib; }
  function has(o, k) { return Object.prototype.hasOwnProperty.call(o, k); }
  function rall(s, a, b) { return s.split(a).join(b); }          // str.replace из Python заменяет все вхождения
  function cap(s) { return s ? s.charAt(0).toUpperCase() + s.slice(1).toLowerCase() : s; }
  function pad2(n) { return (n < 10 ? '0' : '') + n; }

  /* ---------- значения ячеек как в Python ---------- */
  // Date у нас — даты Excel; str(datetime) в Python даёт «2026-10-01 00:00:00»
  function pstr(v, xls) {
    if (v === null || v === undefined) return '';
    if (v instanceof Date) return v.getUTCFullYear() + '-' + pad2(v.getUTCMonth() + 1) + '-' + pad2(v.getUTCDate()) + ' ' + pad2(v.getUTCHours()) + ':' + pad2(v.getUTCMinutes()) + ':' + pad2(v.getUTCSeconds());
    if (typeof v === 'number') return xls && Number.isInteger(v) ? v + '.0' : String(v);   // xlrd отдаёт все числа как float
    return String(v);
  }
  function sp(v, xls) { return pstr(v, xls).replace(/\s+/g, ' ').trim(); }
  function num(v) { return typeof v === 'number' && v ? v : null; }
  function money(v, xls) {
    if (num(v) !== null) return num(v);
    var s = rall(rall(rall(rall(sp(v, xls), '₽', ''), ' ', ''), ' ', ''), ',', '.');
    var f = parseFloat(s);
    return /^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(s) && f ? f : null;
  }
  function masterOf(s) {
    s = sp(s).toLowerCase();
    for (var i = 0; i < MASTERS.length; i++) if (s.indexOf(MASTERS[i][0]) >= 0) return MASTERS[i][1];
    return null;
  }
  function ymd(d) { return d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1); }
  function dmy(d) { return pad2(d.getUTCDate()) + '.' + pad2(d.getUTCMonth() + 1) + '.' + d.getUTCFullYear(); }

  /* ---------- адреса и тексты работ (srcnorm.py) ---------- */
  var STREET_TYPES = '(улица|проспект|пр-кт|пр-т|пр-д|проезд|шоссе|переулок|бульвар|б-р|площадь|ул|пр|ш|пер|пл|д)';
  var HOUSE = '(\\d+(?:\\s*[а-я](?![а-я]))?(?:\\s*/\\s*\\d+(?:\\s*[а-я](?![а-я]))?)?)';
  var KORP = '(?:\\s*(?:корпус|корп\\.?|к\\.?)\\s*(\\d+))?';
  var RE_HOUSE_COMMA = new RegExp(HOUSE + KORP), RE_HOUSE_END = new RegExp(HOUSE + KORP + '\\s*$');
  var RE_TYPES = new RegExp('(?<![а-я])' + STREET_TYPES + '(?![а-я])\\.?', 'g'), RE_TYPO = /(?<![а-я])(л|у)(?![а-я])/g;
  var RE_THIRD = new RegExp(B_BEFORE + 'третьего' + B_AFTER, 'gu');

  function addrKey(a) {
    var s = (a ? String(a) : '').toLowerCase();
    s = rall(rall(s, 'ё', 'е'), ' ', ' ').trim();
    s = s.replace(/50\s*-?\s*(летия|лет)/g, '50 лет');
    s = rall(s.replace(RE_THIRD, '3'), 'уица ', 'улица ');
    s = rall(rall(rall(rall(s, 'промышленая', 'промышленная'), 'пушкаревау', 'пушкарева'), 'роьеспьера', 'робеспьера'), 'люксембур ', 'люксембург ');
    var street, m, c = s.indexOf(',');
    if (c >= 0) {
      street = s.slice(0, c);
      m = RE_HOUSE_COMMA.exec(s.slice(c + 1));
    } else {
      m = RE_HOUSE_END.exec(s);
      street = m ? s.slice(0, m.index) : s;
    }
    if (!m) return [s, ''];
    var house = m[1].replace(/\s/g, ''), korp = m[2];
    street = street.replace(RE_TYPES, ' ').replace(RE_TYPO, ' ').replace(/[^а-я0-9 ]/g, ' ');
    street = street.split(/\s+/).filter(function (w) { return w && w !== 'го'; }).join(' ');
    if (korp) house += 'к' + korp;
    return [street.trim(), house];
  }
  var akCache = {};
  function ak(a) { var r = akCache[a]; if (!r) r = akCache[a] = addrKey(a); return r; }
  function akStr(k) { return k[0] + '\u0001' + k[1]; }

  var TYPOS = [['сиситем', 'систем'], ['ситем', 'систем'], ['уплортнит', 'уплотнит'], ['библеотек', 'библиотек'], ['ковли', 'кровли'], ['заамен', 'замен'],
    ['ремонтсист', 'ремонт сист'], ['ремонткровл', 'ремонт кровл'], ['кварна', 'крана'], ['прочитск', 'прочистк']];
  function workNorm(w) {
    var s = rall((w ? String(w) : '').toLowerCase(), 'ё', 'е');
    s = s.replace(/\(?\s*8\s*\d{3}[\s\d-]{6,}\)?/g, ' ');          // телефоны в тексте работы
    s = s.replace(/[^а-я0-9№ ]/g, ' ');
    TYPOS.forEach(function (t) { s = rall(s, t[0], t[1]); });
    return s.split(/\s+/).filter(Boolean).join(' ');
  }

  // difflib.SequenceMatcher(None, a, b).ratio() — дословно по алгоритму Python
  function ratio(a, b) {
    var b2j = new Map(), i, j, n = b.length;
    for (i = 0; i < n; i++) { var l = b2j.get(b[i]); if (!l) b2j.set(b[i], l = []); l.push(i); }
    if (n >= 200) {                                                  // autojunk: частые символы отбрасываются
      var ntest = Math.floor(n / 100) + 1;
      Array.from(b2j.keys()).forEach(function (k) { if (b2j.get(k).length > ntest) b2j.delete(k); });
    }
    function longest(alo, ahi, blo, bhi) {
      var besti = alo, bestj = blo, bestsize = 0, j2len = new Map(), nothing = [];
      for (var i = alo; i < ahi; i++) {
        var newj2len = new Map(), js = b2j.get(a[i]) || nothing;
        for (var q = 0; q < js.length; q++) {
          var j = js[q];
          if (j < blo) continue;
          if (j >= bhi) break;
          var k = (j2len.get(j - 1) || 0) + 1;
          newj2len.set(j, k);
          if (k > bestsize) { besti = i - k + 1; bestj = j - k + 1; bestsize = k; }
        }
        j2len = newj2len;
      }
      while (besti > alo && bestj > blo && a[besti - 1] === b[bestj - 1]) { besti--; bestj--; bestsize++; }
      while (besti + bestsize < ahi && bestj + bestsize < bhi && a[besti + bestsize] === b[bestj + bestsize]) bestsize++;
      return [besti, bestj, bestsize];
    }
    var queue = [[0, a.length, 0, n]], matches = 0;
    while (queue.length) {
      var t = queue.pop(), m = longest(t[0], t[1], t[2], t[3]);
      if (m[2]) {
        matches += m[2];
        if (t[0] < m[0] && t[2] < m[1]) queue.push([t[0], m[0], t[2], m[1]]);
        if (m[0] + m[2] < t[1] && m[1] + m[2] < t[3]) queue.push([m[0] + m[2], t[1], m[1] + m[2], t[3]]);
      }
    }
    var total = a.length + n;
    return total ? 2.0 * matches / total : 1.0;
  }
  var wnCache = {};
  function wn(w) { var r = wnCache[w]; if (r === undefined) r = wnCache[w] = workNorm(w); return r; }
  function workSim(a, b) {
    a = wn(a); b = wn(b);
    if (!a || !b) return 0.0;
    if (a === b) return 1.0;
    var r = ratio(a, b), ta = new Set(a.split(/\s+/).filter(Boolean)), tb = new Set(b.split(/\s+/).filter(Boolean)), inter = 0;
    ta.forEach(function (x) { if (tb.has(x)) inter++; });
    var union = ta.size + tb.size - inter, j = inter / Math.max(1, union);
    var na = new Set(a.match(/\d+/g) || []), nb = new Set(b.match(/\d+/g) || []), common = false;
    na.forEach(function (x) { if (nb.has(x)) common = true; });
    if (na.size && nb.size && !common) return Math.min(r, j) * 0.5;
    return Math.max(r, j);
  }

  /* ---------- нормализация из extract_backlog.py ---------- */
  function normAddr(a, xls) {
    a = pstr(a, xls).replace(/\s+/g, ' ').trim();
    a = a.replace(/,(?=\S)/g, ', ');
    a = a.replace(new RegExp('(\\d)([а-яё])' + B_AFTER, 'gu'), function (m, d, l) { return d + l.toUpperCase(); });
    return rall(rall(rall(a, 'проезд', 'пр-д'), '50 лет ВЛКСМ', '50-летия ВЛКСМ'), ' корпус ', ' корп. ');
  }
  var UK_KNOWN = { 'ук св': 'УК «СВ»', 'ук союз': 'УК «Союз»', 'ук домовой': 'УК «Домовой»', 'ук домок': 'УК «Домок»', 'тсж звезда': 'ТСЖ «Звезда»', 'тсж зведа': 'ТСЖ «Звезда»' };
  function normUk(u, xls) {
    u = u ? pstr(u, xls) : '';
    u = u.replace(/^ООО\s*/, '').trim().replace(/^["«»]+|["«»]+$/g, '');
    u = rall(rall(rall(u, '"', ''), '«', ''), '»', '');
    u = u.replace(/\s+/g, ' ').trim();
    return has(UK_KNOWN, u.toLowerCase()) ? UK_KNOWN[u.toLowerCase()] : u;
  }
  var CATS = [
    ['ТРЖ', B_BEFORE + 'ТРЖ' + B_AFTER], ['Приборы учёта', 'УУТЭ|ОДПУ|прибор' + W + '* учет|расходомер|поверк|калибров'],
    ['Кровля и козырьки', 'кровл|козыр|крыш'], ['Фасад и МПШ', 'МПШ|межпанел|фасад|балкон'],
    ['Электрика', 'светил|освещ|электр|ВРУ|прожектор|домофон|кабел'],
    ['Инженерные сети', 'стоя|ГВС|ХВС|ЦО' + B_AFTER + '|канализ|КНС|розлив|трубопров|радиатор|насос|кран|вентил|задвиж|отоплен|фильтр|ИТП'],
    ['Двери, окна, входные группы', 'двер|окн|входн|рам[ыа]?' + B_AFTER + '|фрамуг|стекл'],
    ['Благоустройство', 'плитк|асфальт|крыл|отмост|дерев|лавоч|скамей|урн|площадк|забор|МАФ|столбик|полусфер|клумб|газон|песк|удобрен'],
    ['Подъезды', 'подъезд|л/к|лестн|покраск|побелк|штукатур'], ['Санитарное содержание', 'мусор|уборк|дезинс|дератиз']
  ].map(function (c) { return [c[0], new RegExp(c[1], 'iu')]; });
  function catOf(work) {
    for (var i = 0; i < CATS.length; i++) if (CATS[i][1].test(work)) return CATS[i][0];
    return 'Прочее';
  }

  /* ---------- SHA-1 (ключ работы: sha1(...)[:10]) ---------- */
  function utf8(s) {
    var o = [];
    for (var i = 0; i < s.length; i++) {
      var c = s.codePointAt(i);
      if (c > 0xffff) i++;
      if (c < 0x80) o.push(c);
      else if (c < 0x800) o.push(0xc0 | c >> 6, 0x80 | c & 63);
      else if (c < 0x10000) o.push(0xe0 | c >> 12, 0x80 | c >> 6 & 63, 0x80 | c & 63);
      else o.push(0xf0 | c >> 18, 0x80 | c >> 12 & 63, 0x80 | c >> 6 & 63, 0x80 | c & 63);
    }
    return o;
  }
  function sha1hex(s) {
    var m = utf8(s), l = m.length, h = [0x67452301, 0xefcdab89, 0x98badcfe, 0x10325476, 0xc3d2e1f0], i, j;
    m.push(0x80);
    while (m.length % 64 !== 56) m.push(0);
    var hi = Math.floor(l * 8 / 0x100000000), lo = (l * 8) >>> 0;
    m.push(hi >>> 24 & 255, hi >>> 16 & 255, hi >>> 8 & 255, hi & 255, lo >>> 24 & 255, lo >>> 16 & 255, lo >>> 8 & 255, lo & 255);
    var rol = function (x, n) { return (x << n | x >>> 32 - n) >>> 0; };
    for (i = 0; i < m.length; i += 64) {
      var w = [];
      for (j = 0; j < 16; j++) w[j] = (m[i + 4 * j] << 24 | m[i + 4 * j + 1] << 16 | m[i + 4 * j + 2] << 8 | m[i + 4 * j + 3]) >>> 0;
      for (j = 16; j < 80; j++) w[j] = rol(w[j - 3] ^ w[j - 8] ^ w[j - 14] ^ w[j - 16], 1);
      var a = h[0], b = h[1], c = h[2], d = h[3], e = h[4];
      for (j = 0; j < 80; j++) {
        var f, k;
        if (j < 20) { f = b & c | ~b & d; k = 0x5a827999; } else if (j < 40) { f = b ^ c ^ d; k = 0x6ed9eba1; }
        else if (j < 60) { f = b & c | b & d | c & d; k = 0x8f1bbcdc; } else { f = b ^ c ^ d; k = 0xca62c1d6; }
        var t = (rol(a, 5) + f + e + k + w[j]) >>> 0;
        e = d; d = c; c = rol(b, 30); b = a; a = t;
      }
      h = [(h[0] + a) >>> 0, (h[1] + b) >>> 0, (h[2] + c) >>> 0, (h[3] + d) >>> 0, (h[4] + e) >>> 0];
    }
    return h.map(function (x) { return ('00000000' + x.toString(16)).slice(-8); }).join('');
  }
  function keyOf(addr, work, month) {
    return 'w' + sha1hex(ak(addr).join('|') + '|' + workNorm(work) + '|' + (month === null || month === undefined ? 'None' : month)).slice(0, 10);
  }

  /* ---------- чтение листов ---------- */
  var INDEXED = ['000000', 'FFFFFF', 'FF0000', '00FF00', '0000FF', 'FFFF00', 'FF00FF', '00FFFF', '000000', 'FFFFFF', 'FF0000', '00FF00', '0000FF', 'FFFF00', 'FF00FF', '00FFFF',
    '800000', '008000', '000080', '808000', '800080', '008080', 'C0C0C0', '808080', '9999FF', '993366', 'FFFFCC', 'CCFFFF', '660066', 'FF8080', '0066CC', 'CCCCFF',
    '000080', 'FF00FF', 'FFFF00', '00FFFF', '800080', '800000', '008080', '0000FF', '00CCFF', 'CCFFFF', 'CCFFCC', 'FFFF99', '99CCFF', 'FF99CC', 'CC99FF', 'FFCC99',
    '3366FF', '33CCCC', '99CC00', 'FFCC00', 'FF9900', 'FF6600', '666699', '969696', '003366', '339966', '003300', '333300', '993300', '993366', '333399', '333333'];
  function isCfb(buf) { var u = new Uint8Array(buf, 0, 4); return u[0] === 0xd0 && u[1] === 0xcf && u[2] === 0x11 && u[3] === 0xe0; }
  function open(buf) {
    if (!X) throw new Error('Не загружена библиотека чтения Excel.');
    var wb = X.read(buf, { type: 'array', cellStyles: true, cellNF: true, sheetStubs: false });
    wb.__xls = isCfb(buf);
    return wb;
  }
  function Sheet(ws) {
    var ref = X.utils.decode_range(ws['!ref'] || 'A1:A1');
    this.ws = ws; this.nrows = ref.e.r + 1; this.ncols = ref.e.c + 1;
  }
  Sheet.prototype.cell = function (r, c) { return this.ws[X.utils.encode_cell({ r: r, c: c })]; };
  Sheet.prototype.val = function (r, c) {      // значение, как его отдаёт xlrd/openpyxl: строка, число, Date или null
    var x = this.cell(r, c);
    if (!x || x.v === undefined || x.v === null || x.t === 'e') return null;
    if (x.t === 'n' && x.z && X.SSF.is_date(x.z)) return new Date(Math.round(x.v * 86400) * 1000 + Date.UTC(1899, 11, 30));
    if (x.t === 's' && x.v === '') return null;
    return x.v;
  };
  Sheet.prototype.row = function (r, n) { var o = []; for (var c = 0; c < (n || this.ncols); c++) o.push(this.val(r, c)); return o; };
  Sheet.prototype.fill = function (r, c) {
    var x = this.cell(r, c), s = x && x.s, f = s && s.fgColor;
    if (!f) return null;
    if (f.rgb) return String(f.rgb).slice(-6).toUpperCase();
    if (f.indexed !== undefined && f.indexed !== null) return INDEXED[f.indexed] || null;
    return null;
  };
  function sheetsOf(wb) { return wb.SheetNames.map(function (n) { return { name: n, sh: new Sheet(wb.Sheets[n]) }; }); }
  function find(list, re) { for (var i = 0; i < list.length; i++) if (re.test(list[i].name)) return list[i]; return null; }
  function dateOfName(name) {
    var m = /(\d\d)\.(\d\d)\.(\d{4})/.exec(name);
    return m ? m[3] + '-' + m[2] + '-' + m[1] : null;
  }

  // ---------- годовой план ----------
  function readPlan(wb, year) {
    var all = sheetsOf(wb), xls = wb.__xls, pick = find(all, new RegExp('^' + year + '$'));
    if (!pick) {                                   // лист с названием года: берём самый свежий, где есть месяцы плана
      var yrs = all.filter(function (s) { return /^\d{4}$/.test(s.name); }).sort(function (a, b) { return b.name - a.name; });
      pick = yrs[0] || null;
    }
    if (!pick) throw new Error('В годовом плане нет листа с годом в названии (например «' + year + '»).');
    var s = pick.sh, yr = pick.name, out = [], sec = null, colored = 0;
    for (var r = 0; r < s.nrows; r++) {
      var a = sp(s.val(r, 0), xls);
      if (has(MONTHS_RU, a)) { sec = a; continue; }
      if (!sec || a.indexOf('Всего') === 0 || !(sp(s.val(r, 1), xls) && sp(s.val(r, 2), xls))) continue;
      var fill = s.fill(r, 1);
      if (fill && fill !== 'FFFFFF') colored++;
      var f6 = s.val(r, 6), fact = f6 instanceof Date ? 'дата ' + dmy(f6) : sp(f6, xls), fs = s.val(r, 7);
      out.push({ row: r + 1, month: yr + '-' + pad2(MONTHS_RU[sec]), uk: normUk(s.val(r, 0), xls), addr: normAddr(s.val(r, 1), xls), work: sp(s.val(r, 2), xls),
        basis: sp(s.val(r, 3), xls), sum: num(s.val(r, 4)), fact: fact, fsum: num(fs), fsum_txt: num(fs) ? '' : sp(fs, xls), act_col: sp(s.val(r, 8), xls), fill: fill });
    }
    if (!out.length) throw new Error('В листе «' + yr + '» годового плана не найдено работ: проверьте, что выбран годовой план ПТО.');
    return { rows: out, sheet: yr, colored: colored };
  }
  function planStatus(p) {
    var f = p.fill, t = p.fact.toLowerCase(), a = (p.fsum_txt + ' ' + p.act_col).toLowerCase();
    if (f === '008000' || f === '339966') return 'Принято, акт есть';
    if (f === 'FF0000' || t.indexOf('отмен') >= 0 || t.indexOf('отказ') >= 0) return 'Снято';
    if (f === 'FFFF00' || t.indexOf('выпол') >= 0 || a.indexOf('акта нет') >= 0 || a.indexOf('нет акта') >= 0) return 'Выполнено, акта нет';
    if (t.indexOf('в работе') >= 0) return 'В работе';
    if (t.indexOf('голосу') >= 0) return 'Голосование ОСС';
    return null;
  }

  // ---------- файл исполнителей ----------
  var EX_STATUS = [['выполн', 'Выполнено, акта нет'], ['установили', 'Выполнено, акта нет'], ['в работе', 'В работе'], ['в  работе', 'В работе'],
    ['на контроле', 'На контроле'], ['зима', 'Отложено на зиму'], ['отказ', 'Снято'], ['отмена', 'Снято'], ['голосу', 'Голосование ОСС'], ['?', 'Требует уточнения'], ['ждем', 'В работе']];
  function exStatus(g, xls) {
    g = sp(g, xls).toLowerCase();
    if (!g || /^\d{4}-\d\d-\d\d/.test(g)) return null;
    for (var i = 0; i < EX_STATUS.length; i++) if (g.indexOf(EX_STATUS[i][0]) >= 0) return EX_STATUS[i][1];
    return 'В работе';   // «ремонт зонта», «альпинисты» — работа идёт с оговоркой
  }
  function actState(h, xls) {
    var s = sp(h, xls).toLowerCase();
    if (!s || num(h) !== null) return null;
    if (s.indexOf('акт в пто') >= 0) return 'передан в ПТО';
    if (s.indexOf('акт есть') >= 0) return 'есть';
    if (s.indexOf('электрон') >= 0) return 'электронный';
    if (s.indexOf('как подписыв') >= 0) return 'не знают, как подписать';
    if (s.indexOf('акта нет') >= 0 || s.indexOf('не сдан') >= 0) return 'нет';
    if (s.indexOf('по содержанию') >= 0) return 'по содержанию';
    return null;
  }
  function monthOf(v) { return v instanceof Date ? ymd(v) : null; }
  function readExec(wb) {
    var all = sheetsOf(wb), xls = wb.__xls, mainS = find(all, /^тек\.?\s*рем/i);
    if (!mainS) throw new Error('В файле исполнителей нет листа «Тек.Рем (дата)».');
    var adds = all.filter(function (s) { return /^пополнение/i.test(s.name); });
    var rest = all.filter(function (s) { return s !== mainS && adds.indexOf(s) < 0; });
    var main = [], r, s = mainS.sh;
    for (r = 0; r < s.nrows; r++) {
      var v = s.row(r, 9);
      if (!(v[0] && v[1])) continue;
      var h = v[7], act = actState(h, xls), hn = num(h);
      main.push({ src_row: r + 1, addr: sp(v[0], xls), work: sp(v[1], xls), basis: sp(v[2], xls), sum: num(v[3]), month: monthOf(v[4]), who: sp(v[5], xls),
        status_raw: sp(v[6], xls), status: exStatus(v[6], xls), act: act, fsum: hn,
        note: hn !== null || (act && sp(h, xls).length <= 12) ? '' : sp(h, xls) });
    }
    var addRows = [];
    adds.forEach(function (a) {
      for (var r = 2; r < a.sh.nrows; r++) {
        var v = a.sh.row(r, 11);
        if (!(v[2] && v[3])) continue;
        addRows.push({ sheet: a.name, uk: normUk(v[1], xls), addr: sp(v[2], xls), work: sp(v[3], xls), month: monthOf(v[4]), sum: num(v[5]), basis: sp(v[6], xls),
          master: masterOf(v[7]), status_raw: sp(v[8], xls), status: exStatus(v[8], xls), executor: sp(v[9], xls), act: sp(v[10], xls) });
      }
    });
    var per = [], STAT = ['в работе', 'на контроле', 'зима', '?????', ' в работе', 'в  работе'], STAT2 = ['в работе', 'на контроле', 'зима'];
    rest.forEach(function (p) {
      for (var r = 0; r < p.sh.nrows; r++) {
        var row = p.sh.row(r), cells = row.filter(function (c) { return c !== null; });
        if (cells.length < 4) continue;
        var txt = cells.filter(function (c) { return typeof c === 'string'; }).map(function (c) { return sp(c, xls); });
        var ai = -1;
        for (var i = 0; i < txt.length; i++) if (/\d/.test(txt[i]) && ak(txt[i])[1]) { ai = i; break; }
        if (ai < 0 || ai + 1 >= txt.length) continue;
        var stat = '';
        for (i = 0; i < txt.length; i++) {
          var tl = txt[i].toLowerCase();
          if ((exStatus(txt[i], xls) && STAT.indexOf(tl) >= 0) || STAT2.indexOf(tl.trim()) >= 0) { stat = txt[i]; break; }
        }
        var tail = txt.slice(ai + 2).filter(function (t) { return t !== stat && !masterOf(t) && t.toLowerCase().indexOf('на основ') !== 0; });
        per.push({ sheet: p.name, master: masterOf(p.name), addr: txt[ai], work: txt[ai + 1], status: stat ? exStatus(stat, xls) : null, status_raw: stat,
          note: tail.filter(function (t) { return t.length > 3; }).join('; ') });
      }
    });
    return { main: main, adds: addRows, per: per, mainName: mainS.name, addNames: adds.map(function (a) { return a.name; }) };
  }

  // ---------- Битрикс24 ----------
  var BX_STAGE = { 'Успешно': 'Успешно', 'Запланировано': null, 'В работе': 'В работе', 'В работе. Утверждена дата завершения': 'В работе', 'Просрочено': 'В работе',
    'Выполнено, документы не сданы': 'Выполнено, акта нет', 'Отказано': 'Снято' };
  function ddmmyyyy(v, xls) {
    var m = /^(\d\d)\.(\d\d)\.(\d{4})/.exec(sp(v, xls));
    return m ? m[3] + '-' + m[2] + '-' + m[1] : null;
  }
  function readBitrix(wb) {
    var xls = wb.__xls, s = new Sheet(wb.Sheets[wb.SheetNames[0]]), out = [], sec = null;
    for (var r = 1; r < s.nrows; r++) {
      var v = s.row(r, 13);
      if (v[0] && !v[1] && String(v[0]).indexOf('·') >= 0) {
        var m = /^(\S+)\s+(\d{4})/.exec(cap(String(v[0]).trim()));
        if (!m || !has(MONTHS_RU, cap(m[1]))) throw new Error('В выгрузке Битрикс24 не удалось определить месяц в строке ' + (r + 1) + ': «' + v[0] + '».');
        sec = m[2] + '-' + pad2(MONTHS_RU[cap(m[1])]);
        continue;
      }
      if (!v[1]) continue;
      var resp = sp(v[12], xls), w2 = sp(v[2], xls);
      var junk = !w2 || w2.length < 4 || /тест/.test(w2.toLowerCase()) || /^[\d\s]+$/.test(w2) || sp(v[1], xls).toLowerCase().indexOf('не выбрано') >= 0 || resp.toLowerCase().indexOf('тестович') >= 0;
      out.push({ src_row: r + 1, month: sec, uk: normUk(v[0], xls), addr_raw: sp(v[1], xls), work: w2, basis_type: sp(v[3], xls), basis_doc: sp(v[4], xls),
        start: ddmmyyyy(v[5], xls), end: ddmmyyyy(v[6], xls), created: ddmmyyyy(v[7], xls), act_file: sp(v[8], xls), sum: money(v[9], xls), fsum: money(v[10], xls),
        stage: sp(v[11], xls), resp: resp === '' || resp === '0' || resp.toLowerCase().indexOf('тестович') >= 0 ? null : (masterOf(resp) || resp), junk: !!junk });
    }
    if (!out.length) throw new Error('В выгрузке Битрикс24 не найдено работ: проверьте, что выбран файл «План текущего ремонта».');
    return out;
  }

  /* ---------- сопоставление ---------- */
  function Index() { this.m = new Map(); }
  Index.prototype.add = function (w) { var k = akStr(ak(w.addr)), l = this.m.get(k); if (!l) this.m.set(k, l = []); l.push(w); };
  Index.prototype.get = function (k) { return this.m.get(akStr(k)) || []; };

  function best(item, idx, used, minSim) {
    minSim = minSim === undefined ? 0.55 : minSim;
    var k = ak(has(item, 'addr') ? item.addr : item.addr_raw), bc = null, bs = 0, cs = idx.get(k);
    for (var i = 0; i < cs.length; i++) {
      var c = cs[i];
      if (used && used.has(c)) continue;
      var s = workSim(item.work, c.work);
      if (item.month && c.month && item.month === c.month) s += 0.05;
      if (s > bs) { bc = c; bs = s; }
    }
    return bs >= minSim ? [bc, bs] : [null, bs];
  }
  function globMatch(r, works, name, minSim) {
    minSim = minSim === undefined ? 0.9 : minSim;
    var k = ak(r.addr_raw), bw = null, bs = 0;
    for (var i = 0; i < works.length; i++) {
      var w = works[i];
      if (has(w.src, name)) continue;
      var s = workSim(r.work, w.work);
      if (ak(w.addr)[0] === k[0]) s += 0.1;
      else if (w.month !== r.month) continue;
      if (s > bs) { bw = w; bs = s; }
    }
    return bs >= minSim + 0.1 || (bs >= minSim && bw && ak(bw.addr)[0] === k[0]) ? bw : null;
  }
  function bxAddr(a, xls) {
    a = rall(rall(sp(a, xls), 'ё', 'е'), 'Ё', 'Е');
    var T = [['улица', 'ул'], ['проспект', 'пр-т'], ['проезд', 'пр-д'], ['шоссе', 'шоссе']];
    for (var i = 0; i < T.length; i++) {
      var m = new RegExp('^(?:' + T[i][0] + '\\s+(.+?)|(.+?)\\s+' + T[i][0] + '),\\s*(.+)$', 'i').exec(a);
      if (m) return (m[1] || m[2]) + ' ' + T[i][1] + ', ' + m[3];
    }
    return normAddr(a);
  }
  function fmtDate(d) { return d ? d.split('-').reverse().join('.') : ''; }
  function ddmm(iso) { return iso.slice(8, 10) + '.' + iso.slice(5, 7); }

  /**
   * opts: { plan, exec, bx: ArrayBuffer, dates: {plan, exec, bx: 'YYYY-MM-DD'}, today: 'YYYY-MM-DD',
   *         canon: [адреса в проверенном написании], prev: [{addr, work, month, cat}] (работы, уже лежащие в трекере) }
   * Возвращает { items, generated, sources, info:{...}, warnings:[...] } — items в формате файла обновления.
   */
  function merge(opts) {
    var dates = opts.dates, warnings = [];
    var planWb = open(opts.plan), execWb = open(opts.exec), bxWb = open(opts.bx);
    var P = readPlan(planWb, dates.plan.slice(0, 4)), plan = P.rows, E = readExec(execWb), bx = readBitrix(bxWb);
    if (!P.colored) warnings.push('В годовом плане не прочитаны цвета строк (зелёная, жёлтая, красная): статусы «Принято» и «Выполнено» из плана не определятся. Сохраните план как .xls или .xlsx из Excel без изменения оформления.');
    var xlsE = execWb.__xls;
    var canon = {};
    (opts.canon || []).forEach(function (a) { var k = akStr(ak(a)); if (!has(canon, k)) canon[k] = a; });
    canon[akStr(ak('50 лет ВЛКСМ д.24'))] = '50-летия ВЛКСМ пр-т, 24';
    canon[akStr(ak('Высотный проезд, 2'))] = 'Высотный пр-д, 2';
    var rep = {};
    var repAdd = function (k, v) { (rep[k] = rep[k] || []).push(v); };

    var works = plan.map(function (p) { return Object.assign({}, p, { src: { plan: p } }); });
    var idx = new Index();
    works.forEach(function (w) { idx.add(w); });
    E.adds.forEach(function (a) {
      var c = best(a, idx)[0];
      if (c) c.src.add = a;
      else {
        var w = { row: null, month: a.month, uk: a.uk, addr: normAddr(a.addr, xlsE), work: a.work, basis: a.basis, sum: a.sum, fact: '', fsum: null, fsum_txt: '', act_col: '', fill: null, src: { add: a } };
        works.push(w); idx.add(w); repAdd('только в пополнении', a);
      }
    });
    function attach(rows, name) {
      var used = new Set();
      rows.forEach(function (r) {
        var c = best(r, idx, used)[0];
        if (c && !has(c.src, name)) { c.src[name] = r; used.add(c); }
        else if (c) repAdd('дубль в ' + name, r);
        else repAdd('не найдено: ' + name, r);
      });
    }
    attach(E.main, 'exec');
    (rep['не найдено: exec'] || []).forEach(function (r) {
      var nw = { row: null, month: r.month, uk: '', addr: normAddr(r.addr, xlsE), work: r.work, basis: r.basis, sum: r.sum, fact: '', fsum: r.fsum, fsum_txt: '', act_col: '', fill: null, src: { exec: r }, only: 'exec' };
      works.push(nw); idx.add(nw); repAdd('только в файле исполнителей', r);
    });
    delete rep['не найдено: exec'];
    attach(E.per, 'per');
    attach(opts.prev || [], 'prev');

    var used = new Set();
    bx.forEach(function (r) {
      if (!r.junk && r.start && r.end && r.end < r.start) repAdd('Битрикс24: дата завершения раньше начала', r);
      if (r.junk) { repAdd('Битрикс24: тестовые и пустые записи', r); return; }
      var item = Object.assign({}, r, { addr: r.addr_raw }), c = best(item, idx, used)[0];
      if (c) { c.src.bx = r; used.add(c); }
      else if (best(item, idx)[0]) repAdd('Битрикс24: повторная карточка той же работы', r);
      else {
        var g = globMatch(r, works, 'bx');
        if (g) { g.src.bx = r; g.addr_conflict = r.addr_raw; repAdd('Битрикс24: другой адрес', r); }
        else {
          var nw = { row: null, month: r.month, uk: r.uk, addr: bxAddr(r.addr_raw), work: r.work, basis: r.basis_type, sum: r.sum, fact: '', fsum: r.fsum, fsum_txt: '', act_col: '', fill: null, src: { bx: r }, only: 'bx' };
          works.push(nw); repAdd('только в Битрикс24', r);
        }
      }
    });

    var ukByAddr = {};
    works.forEach(function (w) { var k = akStr(ak(w.addr)); if (w.uk && !has(ukByAddr, k)) ukByAddr[k] = w.uk; });
    var D = { exec: ddmm(dates.exec), per: ddmm(dates.exec), plan: ddmm(dates.plan), add: ddmm(dates.plan), bx: ddmm(dates.bx) };
    var DFULL = { exec: dates.exec, per: dates.exec, plan: dates.plan, add: dates.plan, bx: dates.bx };
    var LABEL = { exec: function (d) { return d; }, per: function (d) { return d + ' лист мастера'; }, plan: function (d) { return d; }, add: function (d) { return d + ' пополнение'; }, bx: function (d) { return d + ' Битрикс'; } };
    var DONE = ['Выполнено, акта нет', 'Принято, акт есть'], out = [];

    works.forEach(function (w) {
      var S = w.src, p = S.plan, e = S.exec, a = S.add, pe = S.per, pr = S.prev, b = S.bx;
      var cand = [];                                   // {src, label, status}
      var push = function (src, status) { if (status) cand.push({ src: src, label: LABEL[src](D[src]), status: status, date: DFULL[src], ord: SOURCES.indexOf(src) }); };
      if (e) push('exec', e.status);
      if (pe) push('per', pe.status);
      var ps = p ? planStatus(p) : null;
      push('plan', ps);
      if (a) push('add', a.status);
      var bs = b ? BX_STAGE[b.stage] : null;
      if (bs === 'Успешно') bs = b.act_file || ps === 'Принято, акт есть' ? 'Принято, акт есть' : 'Выполнено, акта нет';
      push('bx', bs);
      cand.sort(function (x, y) { return x.date < y.date ? -1 : x.date > y.date ? 1 : x.ord - y.ord; });   // свежая выгрузка — последняя; при равной дате — по порядку источников
      var last = cand.length ? cand[cand.length - 1] : null;
      var status = last ? last.status : ((a || (b && b.stage === 'Запланировано')) ? 'Не начато' : 'Нет статуса');
      var conflict = '', strong = cand.filter(function (c) { return DONE.indexOf(c.status) >= 0; }), sd = strong.length ? strong[strong.length - 1] : null;
      if (DONE.indexOf(status) < 0 && status !== 'Снято' && sd && last.src === 'bx') {
        conflict = 'Битрикс24: «' + b.stage + '», а ' + sd.label + ' — ' + sd.status.toLowerCase();
        status = sd.status;
      } else if (DONE.indexOf(status) < 0 && status !== 'Снято' && sd) {
        conflict = sd.label + ' — ' + sd.status.toLowerCase() + ', позже ' + last.label + ' — ' + last.status.toLowerCase();
      }
      if (DONE.indexOf(status) < 0 && status !== 'Снято' && ((e && e.note) || '').concat((pe && pe.note) || '').indexOf('???') >= 0) status = 'Требует уточнения';
      if (ps === 'Принято, акт есть' && status !== 'Снято') status = 'Принято, акт есть';   // принятие по плану ПТО главнее отметок исполнителя
      if (DONE.indexOf(status) >= 0 && b && b.stage === 'Запланировано') repAdd('Битрикс24: выполнено, а стадия «Запланировано»', w.addr);

      var ex = null;                                     // исполнитель: УК (своими силами) / Подрядчики (в файлах — «ПТО»)
      if (a && a.executor) ex = a.executor.toLowerCase().indexOf('пто') >= 0 && a.executor.toLowerCase().indexOf('филимон') < 0 ? 'Подрядчики' : 'УК';
      if (!ex && e) {
        var wl = e.who.toLowerCase();
        if (wl.indexOf('пто') >= 0) ex = 'Подрядчики';
        else if (masterOf(wl) || wl.indexOf('алеев') >= 0) ex = 'УК';
      }
      if (!ex && p && p.fill === 'FFCC99') ex = 'УК';
      if (!ex && p && (p.fill === '969696' || p.fill === 'C0C0C0')) ex = 'Подрядчики';
      ex = ex || 'Не распределено';

      var master = (a && a.master) || (pe && pe.master) || (e && masterOf(e.who)) || (b && b.resp) || '';
      var mconf = !!(b && b.resp && master && b.resp !== master && b.resp !== 'Наумова Т.Ю.');
      if (b && b.resp === 'Наумова Т.Ю.' && master) repAdd('Битрикс24: ответственный Наумова, мастер другой', w.addr);

      var act = '';
      if (status === 'Принято, акт есть') act = 'есть';
      else if (e && e.act) act = e.act;
      if (b && b.act_file) act = 'есть (КС-2 в Битрикс24)';
      var notes = [];
      if (p && p.fact && ['выполнено', 'выполено'].indexOf(p.fact.toLowerCase()) < 0) notes.push('План: ' + p.fact);
      if (e && e.note) notes.push('Исполнитель ' + D.exec + ': ' + e.note);
      if (pe && pe.note) notes.push((pe.master || pe.sheet) + ': ' + pe.note);
      if (a && a.status_raw && !a.status) notes.push('Пополнение: ' + a.status_raw);
      if (e && e.status_raw && e.status === 'В работе' && e.status_raw.toLowerCase() !== 'в работе') notes.push('Исполнитель: ' + e.status_raw);
      var fsum = (p && p.fsum) || (b && b.fsum) || (e && e.fsum) || null;
      var fdiff = !!(p && p.fsum && e && e.fsum && Math.abs(p.fsum - e.fsum) > 1);
      if (fdiff) repAdd('факт различается', w.addr);
      var check = [];
      if (conflict) check.push('статус расходится: ' + conflict);
      if (e && e.who.toLowerCase().indexOf('/пто') >= 0) check.push('исполнитель: в файле исполнителей «' + e.who + '» — УК или подрядчик?');
      if (w.addr_conflict) check.push('в Битрикс24 другой адрес: «' + w.addr_conflict + '»');
      if (mconf) check.push('мастер: у исполнителей — ' + master + ', в Битрикс24 — ' + b.resp);
      if (w.only === 'exec') check.push('работа есть только в файле исполнителей, в годовом плане ' + D.plan + ' её нет');
      if (w.only === 'bx') check.push('работа есть только в Битрикс24, в годовом плане ' + D.plan + ' её нет');
      var ru = function (x) { return x.toFixed(2).replace('.', ','); };
      if (fdiff) check.push('факт: в плане ' + ru(p.fsum) + ' ₽, у исполнителей ' + ru(e.fsum) + ' ₽');
      var bxDates = '';
      if (b && (b.start || b.end)) {
        bxDates = 'срок ' + fmtDate(b.start) + ' – ' + fmtDate(b.end);
        if (b.start && b.end && b.end < b.start) bxDates += ' (завершение раньше начала)';
      }
      if (b && b.created) bxDates += (bxDates ? '; ' : '') + 'создана ' + fmtDate(b.created);
      var hist = cand.map(function (c) { return c.label + ': ' + c.status; }).join(' → ');
      var k = akStr(ak(w.addr));
      out.push({
        key: keyOf(w.addr, w.work, w.month), row: w.row, month: w.month, addr: canon[k] || w.addr, uk: w.uk || (b && b.uk) || ukByAddr[k] || '',
        work: w.work, cat: (pr && pr.cat) || catOf(w.work), basis: w.basis || (b && b.basis_type) || '', sum: w.sum || (b && b.sum) || null, fsum: fsum,
        ex: ex, master: master, status: status, act: act, kr: '', bx_stage: b ? b.stage : '', bx_dates: bxDates,
        src_note: (hist ? [hist] : []).concat(notes).join(' · '), check: check.join('; ')
      });
      if (conflict) repAdd('статусы расходятся', w.addr);
    });
    var cnt = {};
    out.forEach(function (i) { cnt[i.key] = (cnt[i.key] || 0) + 1; });
    out.forEach(function (i) { if (cnt[i.key] > 1) i.key += '-' + (i.row || out.length); });   // одинаковые работы по одному адресу в одном месяце

    var rcount = {};
    Object.keys(rep).forEach(function (k) { rcount[k] = rep[k].length; });
    return {
      items: out, generated: opts.today,
      sources: { plan: fmtDate(dates.plan), exec: fmtDate(dates.exec) + ' + пополнения', bitrix: fmtDate(dates.bx) },
      info: { planRows: plan.length, planSheet: P.sheet, execRows: E.main.length, execAdds: E.adds.length, execMasters: E.per.length, bitrixRows: bx.length,
        bitrixJunk: bx.filter(function (x) { return x.junk; }).length, execSheet: E.mainName, execSheetDate: dateOfName(E.mainName), colored: P.colored, report: rcount },
      warnings: warnings
    };
  }

  return { setLib: setLib, merge: merge, addrKey: addrKey, workNorm: workNorm, workSim: workSim, ratio: ratio, sha1hex: sha1hex, keyOf: keyOf, catOf: catOf, normAddr: normAddr, normUk: normUk,
    dateOfName: dateOfName };
})();
if (typeof module !== 'undefined' && module.exports) module.exports = TrackerMerge;
