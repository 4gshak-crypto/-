/**
 * Трекер текущего ремонта — веб-приложение Google Apps Script.
 * Данные хранятся в Google Таблице, к которой привязан скрипт.
 * Вход по имени и PIN-коду, права проверяются здесь, на сервере.
 *
 * Роли:
 *   Администратор — меняет всё: статус, исполнителя, месяц, факт, акт, добавляет работы, закрывает вопросы, ведёт пользователей.
 *   УК            — меняет статус и комментарий только в работах с исполнителем «УК» (своими силами).
 *   Подрядчики    — меняет статус и комментарий только в работах с исполнителем «Подрядчики».
 *   Исполнитель может отметить «Выполнено, акта нет»; «Принято, акт есть» и «Снято» ставит только администратор.
 *   Просмотр      — только смотрит.
 */

var SHEET_WORKS = 'Работы';
var SHEET_USERS = 'Пользователи';
var SHEET_LOG = 'Журнал';
var SHEET_ISSUES = 'Вопросы';

var WORK_COLS = ['Ключ', 'Строка', 'Месяц', 'Адрес', 'УК', 'Работа', 'Вид работ', 'Основание', 'Оценка, ₽', 'Факт, ₽',
  'Исполнитель', 'Статус', 'Комментарий', 'Из файла', 'КР', 'Изменено', 'Кем', 'Дата выполнения', 'Акт', 'Исходный месяц',
  'Мастер участка', 'Стадия Битрикс24', 'Сроки Битрикс24', 'Сверить'];
var USER_COLS = ['Имя', 'Роль', 'Активен', 'Новый PIN', 'PIN-хэш', 'ID Битрикс24'];
var LOG_COLS = ['Время', 'Пользователь', 'Ключ', 'Адрес', 'Работа', 'Что', 'Было', 'Стало'];
var ISSUE_COLS = ['№', 'Вопрос', 'Ответственный', 'Срок', 'Ссылка', 'Решён', 'Кем', 'Когда'];

var ROLES = ['Администратор', 'УК', 'Подрядчики', 'Просмотр'];
var EXECUTORS = ['Подрядчики', 'УК', 'Не распределено'];
var STATUSES = ['Нужно решение', 'Требует уточнения', 'Нет статуса', 'Вопрос капремонта', 'Голосование ОСС', 'Не начато',
  'Передано исполнителю', 'На контроле', 'Материал заказан', 'В работе', 'Отложено на зиму', 'Выполнено, акта нет', 'Принято, акт есть', 'Снято'];
var DONE_STATUSES = ['Выполнено, акта нет', 'Принято, акт есть'];
var ADMIN_ONLY_STATUSES = ['Принято, акт есть', 'Снято'];
var MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;

var SESSION_HOURS = 6;
var MAX_FAILS = 5;

/* ---------------- web ---------------- */

function doGet() {
  return page_(null);
}

/** Битрикс24 открывает приложение POST-запросом и передаёт AUTH_ID и DOMAIN текущего сотрудника. */
function doPost(e) {
  var p = (e && e.parameter) || {};
  if (!p.AUTH_ID) return page_(null);
  var boot;
  try {
    boot = { bitrix: true, session: bitrixLogin_(p) };
  } catch (err) {
    boot = { bitrix: true, error: err.message };
  }
  return page_(boot);
}

function page_(boot) {
  var t = HtmlService.createTemplateFromFile('Index');
  t.BOOT = JSON.stringify(boot || null).replace(/</g, '\\u003c');
  return t.evaluate()
    .setTitle('Трекер текущего ремонта')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    // ALLOWALL нужен, чтобы трекер показывался внутри Битрикс24
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/* ---------------- вход через Битрикс24 ---------------- */

function bitrixLogin_(p) {
  var domain = String(PropertiesService.getScriptProperties().getProperty('BITRIX_DOMAIN') || '')
    .replace(/^https?:\/\//, '').replace(/\/.*$/, '').trim().toLowerCase();
  if (!domain) throw new Error('Битрикс24 не подключён: администратору нужно задать свойство скрипта BITRIX_DOMAIN.');
  if (String(p.DOMAIN || '').toLowerCase() !== domain) throw new Error('Трекер подключён к другому порталу Битрикс24.');
  // спрашиваем только у своего портала: чужой AUTH_ID там не пройдёт
  var resp = UrlFetchApp.fetch('https://' + domain + '/rest/user.current.json', {
    method: 'post', payload: { auth: String(p.AUTH_ID) }, muteHttpExceptions: true
  });
  var me = null;
  try { me = JSON.parse(resp.getContentText()).result; } catch (x) { me = null; }
  if (resp.getResponseCode() !== 200 || !me || !me.ID) throw new Error('Битрикс24 не подтвердил вход. Закройте и снова откройте приложение.');
  var bxId = String(me.ID);
  var fullName = [me.NAME, me.LAST_NAME].filter(function (x) { return x; }).join(' ').trim() || ('Сотрудник ' + bxId);

  var lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    var sh = sheet_(SHEET_USERS);
    var data = sh.getDataRange().getValues();
    for (var i = 1; i < data.length; i++) {
      if (String(data[i][5] || '').trim() !== bxId) continue;
      if (!isTrue_(data[i][2])) throw new Error('Ваш доступ к трекеру отключён. Обратитесь к администратору.');
      return newSession_(String(data[i][0]).trim(), data[i][1]);
    }
    // первый вход сотрудника: заводим его с ролью «Просмотр», роль назначит администратор
    var names = data.map(function (r) { return String(r[0]).trim(); });
    var name = names.indexOf(fullName) >= 0 ? fullName + ' (Б24 ' + bxId + ')' : fullName;
    sh.appendRow([safe_(name), 'Просмотр', true, '', '', bxId]);
    return newSession_(name, 'Просмотр');
  } finally {
    lock.releaseLock();
  }
}

function newSession_(name, role) {
  var token = Utilities.getUuid();
  var user = { name: name, role: ROLES.indexOf(role) >= 0 ? role : 'Просмотр' };
  CacheService.getScriptCache().put('s:' + token, JSON.stringify(user), SESSION_HOURS * 3600);
  return { token: token, user: user };
}

/* ---------------- первичная настройка ---------------- */

/** Запустите один раз из редактора скриптов: создаёт листы, загружает план и администратора. */
function setup() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var props = PropertiesService.getScriptProperties();
  if (!props.getProperty('SALT')) props.setProperty('SALT', Utilities.getUuid());

  var works = ss.getSheetByName(SHEET_WORKS);
  if (!works) {
    works = ss.insertSheet(SHEET_WORKS);
    // месяцы — текстом, иначе таблица превратит «2026-09» в дату
    works.getRange('C:C').setNumberFormat('@');
    works.getRange('T:T').setNumberFormat('@');
    var rows = SEED.items.map(function (it) {
      return [it.key, it.row || '', it.month, it.addr, it.uk || '', it.work, it.cat || '', it.basis || '', it.sum || '', it.fsum || '',
        it.ex, it.status, '', it.src_note || '', it.kr || '', '', '', '', it.act || '', it.month,
        it.master || '', it.bx_stage || '', it.bx_dates || '', it.check || ''];
    });
    works.getRange(1, 1, 1, WORK_COLS.length).setValues([WORK_COLS]).setFontWeight('bold');
    works.getRange(2, 1, rows.length, WORK_COLS.length).setValues(rows);
    works.setFrozenRows(1);
    works.getRange(2, 11, rows.length, 1).setDataValidation(SpreadsheetApp.newDataValidation().requireValueInList(EXECUTORS).build());
    works.getRange(2, 12, rows.length, 1).setDataValidation(SpreadsheetApp.newDataValidation().requireValueInList(STATUSES).build());
  }

  var issues = ss.getSheetByName(SHEET_ISSUES);
  if (!issues) {
    issues = ss.insertSheet(SHEET_ISSUES);
    issues.getRange(1, 1, 1, ISSUE_COLS.length).setValues([ISSUE_COLS]).setFontWeight('bold');
    var ir = SEED.issues.map(function (x, i) { return [i + 1, x.text, x.resp, x.term, x.ref || '', false, '', '']; });
    if (ir.length) issues.getRange(2, 1, ir.length, ISSUE_COLS.length).setValues(ir);
    issues.setFrozenRows(1);
  }

  if (!ss.getSheetByName(SHEET_LOG)) {
    var log = ss.insertSheet(SHEET_LOG);
    log.getRange(1, 1, 1, LOG_COLS.length).setValues([LOG_COLS]).setFontWeight('bold');
    log.setFrozenRows(1);
  }

  var users = ss.getSheetByName(SHEET_USERS);
  if (!users) {
    users = ss.insertSheet(SHEET_USERS);
    users.getRange(1, 1, 1, USER_COLS.length).setValues([USER_COLS]).setFontWeight('bold');
    users.setFrozenRows(1);
    var pin = String(Math.floor(100000 + Math.random() * 900000));
    users.appendRow(['Администратор', 'Администратор', true, '', hashPin_(pin), '']);
    users.getRange('F:F').setNumberFormat('@');
    users.getRange(2, 2, 200, 1).setDataValidation(SpreadsheetApp.newDataValidation().requireValueInList(ROLES).build());
    Logger.log('Администратор создан. Имя: «Администратор», PIN: ' + pin + ' — запишите его, он больше не показывается.');
  }
  var def = ss.getSheetByName('Лист1') || ss.getSheetByName('Sheet1');
  if (def && ss.getSheets().length > 1 && def.getLastRow() === 0) ss.deleteSheet(def);
  bumpRev_();
}

/* ---------------- вход ---------------- */

function getLoginNames() {
  return readUsers_().filter(function (u) { return u.active && u.hasPin; }).map(function (u) { return u.name; });
}

function login(name, pin) {
  name = String(name || '').trim();
  pin = String(pin || '').trim();
  var cache = CacheService.getScriptCache();
  var failKey = 'fail:' + name;
  var fails = Number(cache.get(failKey) || 0);
  if (fails >= MAX_FAILS) throw new Error('Слишком много неверных попыток. Подождите 15 минут.');

  var lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    var sh = sheet_(SHEET_USERS);
    var data = sh.getDataRange().getValues();
    for (var i = 1; i < data.length; i++) {
      var r = data[i];
      if (String(r[0]).trim() !== name || !isTrue_(r[2])) continue;
      var newPin = String(r[3] || '').trim();
      var ok = false;
      if (newPin && newPin === pin) {
        // PIN, который администратор вписал в таблицу, превращаем в хэш и стираем
        sh.getRange(i + 1, 4, 1, 2).setValues([['', hashPin_(pin)]]);
        ok = true;
      } else if (r[4] && r[4] === hashPin_(pin)) {
        ok = true;
      }
      if (!ok) break;
      cache.remove(failKey);
      return newSession_(name, r[1]);
    }
  } finally {
    lock.releaseLock();
  }
  cache.put(failKey, String(fails + 1), 900);
  throw new Error('Неверное имя или PIN.');
}

function logout(token) {
  CacheService.getScriptCache().remove('s:' + token);
  return true;
}

/* ---------------- чтение ---------------- */

function bootstrap(token) {
  var user = auth_(token);
  ensureKeys_();
  return {
    user: user,
    rev: getRev_(),
    asof: SEED.generated,
    items: readWorks_(),
    issues: readIssues_(),
    log: readLog_(60)
  };
}

function getRev(token) {
  auth_(token);
  return getRev_();
}

/** Полная история одной работы из журнала. */
function getHistory(token, key) {
  auth_(token);
  var sh = sheet_(SHEET_LOG);
  var last = sh.getLastRow();
  if (last < 2) return [];
  return sh.getRange(2, 1, last - 1, LOG_COLS.length).getValues()
    .filter(function (r) { return String(r[2]) === key; }).reverse().slice(0, 50)
    .map(function (r) { return { at: r[0] instanceof Date ? r[0].getTime() : null, by: String(r[1]), what: String(r[5]), from: String(r[6]), to: String(r[7]) }; });
}

/* ---------------- запись ---------------- */

/** patch: {status?, note?, ex?, month?, fsum?, act?, master?, check?} — всё, кроме статуса и комментария, только администратор. */
function updateWork(token, key, patch) {
  var user = auth_(token);
  patch = patch || {};
  var lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    var sh = sheet_(SHEET_WORKS);
    var rowIdx = findRow_(sh, key);
    if (!rowIdx) throw new Error('Работа не найдена — обновите страницу.');
    var row = sh.getRange(rowIdx, 1, 1, WORK_COLS.length).getValues()[0];
    var item = workFromRow_(row);
    if (!canEditWork_(user, item)) throw new Error('У вас нет прав менять эту работу.');

    var admin = user.role === 'Администратор';
    var now = new Date();
    var changes = [];
    if (patch.status != null && patch.status !== item.status) {
      if (STATUSES.indexOf(patch.status) < 0) throw new Error('Неизвестный статус.');
      if (!admin && (ADMIN_ONLY_STATUSES.indexOf(patch.status) >= 0 || ADMIN_ONLY_STATUSES.indexOf(item.status) >= 0))
        throw new Error('Принимает работу и снимает её с плана только администратор.');
      changes.push(['Статус', item.status, patch.status]);
      row[11] = patch.status;
      var wasDone = DONE_STATUSES.indexOf(item.status) >= 0, isDone = DONE_STATUSES.indexOf(patch.status) >= 0;
      if (isDone && !wasDone) row[17] = now;
      if (!isDone) row[17] = '';
    }
    if (patch.note != null && String(patch.note).trim() !== item.note) {
      var note = String(patch.note).trim().slice(0, 2000);
      changes.push(['Комментарий', item.note, note]);
      row[12] = safe_(note);
    }
    var adminFields = ['ex', 'month', 'fsum', 'act', 'master', 'check'].filter(function (k) { return patch[k] != null; });
    if (adminFields.length && !admin) throw new Error('Исполнителя, мастера, месяц, факт и акт меняет только администратор.');
    if (patch.master != null && String(patch.master).trim() !== item.master) {
      var ms = String(patch.master).trim().slice(0, 80);
      changes.push(['Мастер участка', item.master, ms]);
      row[20] = ms;
    }
    if (patch.check != null && String(patch.check) !== item.check) {
      changes.push(['Сверка', item.check, patch.check ? String(patch.check).slice(0, 300) : 'сверено']);
      row[23] = String(patch.check).slice(0, 300);
    }
    if (patch.ex != null && patch.ex !== item.ex) {
      if (EXECUTORS.indexOf(patch.ex) < 0) throw new Error('Неизвестный исполнитель.');
      changes.push(['Исполнитель', item.ex, patch.ex]);
      row[10] = patch.ex;
    }
    if (patch.month != null && patch.month !== item.month) {
      if (!MONTH_RE.test(patch.month)) throw new Error('Неверный месяц.');
      changes.push(['Перенос срока', item.month, patch.month]);
      row[2] = patch.month;
      if (!row[19]) row[19] = item.month;
    }
    if (patch.fsum != null && String(patch.fsum) !== String(item.fsum || '')) {
      var f = patch.fsum === '' ? '' : Number(patch.fsum);
      if (f !== '' && !(f >= 0)) throw new Error('Фактическая сумма — число в рублях.');
      changes.push(['Факт, ₽', item.fsum || '', f]);
      row[9] = f;
    }
    if (patch.act != null && String(patch.act).trim() !== item.act) {
      var act = String(patch.act).trim().slice(0, 200);
      changes.push(['Акт', item.act, act]);
      row[18] = safe_(act);
    }
    if (!changes.length) return workFromRow_(row);
    row[15] = now;
    row[16] = user.name;
    // строка пишется целиком, поэтому экранируем все текстовые ячейки, а не только изменённые:
    // getValues() отдаёт текст без апострофа, и «=…» снова стал бы формулой
    sh.getRange(rowIdx, 1, 1, WORK_COLS.length).setValues([row.map(safe_)]);
    var log = sheet_(SHEET_LOG);
    changes.forEach(function (c) { log.appendRow([now, user.name, key, item.addr, item.work, c[0], safe_(c[1]), safe_(c[2])]); });
    bumpRev_();
    return workFromRow_(row);
  } finally {
    lock.releaseLock();
  }
}

function addWork(token, w) {
  var user = auth_(token);
  if (user.role !== 'Администратор') throw new Error('Добавлять работы может только администратор.');
  w = w || {};
  var addr = String(w.addr || '').trim(), work = String(w.work || '').trim();
  if (!addr || !work) throw new Error('Укажите адрес и вид работы.');
  if (!MONTH_RE.test(String(w.month))) throw new Error('Выберите месяц.');
  var ex = EXECUTORS.indexOf(w.ex) >= 0 ? w.ex : 'Не распределено';
  var sum = w.sum === '' || w.sum == null ? '' : Number(w.sum);
  if (sum !== '' && !(sum >= 0)) throw new Error('Оценка — число в рублях.');
  var lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    var key = 'n' + Utilities.getUuid().slice(0, 8);
    var now = new Date();
    var row = [key, '', w.month, safe_(addr), String(w.uk || ''), safe_(work), 'Добавлено вручную', safe_(String(w.basis || '')), sum, '',
      ex, 'Не начато', '', '', '', now, user.name, '', '', w.month, safe_(String(w.master || '')), '', '', ''];
    sheet_(SHEET_WORKS).appendRow(row);
    sheet_(SHEET_LOG).appendRow([now, user.name, key, safe_(addr), safe_(work), 'Добавлена работа', '', ex]);
    bumpRev_();
    return workFromRow_(row);
  } finally {
    lock.releaseLock();
  }
}

/* ---------------- обновление из выгрузок (администратор) ---------------- */

var IMPORT_FORMAT = 'tracker-import-1';
var IMPORT_MAX_ITEMS = 3000;
// стадии по ходу работы: обновление из источников не откатывает работу назад
var STAGE_RANK = { 'Нужно решение': -1, 'Требует уточнения': -1, 'Нет статуса': -1, 'Вопрос капремонта': -1, 'Голосование ОСС': -1,
  'Не начато': 0, 'Передано исполнителю': 0, 'В работе': 1, 'На контроле': 1, 'Материал заказан': 1, 'Отложено на зиму': 1,
  'Выполнено, акта нет': 2, 'Принято, акт есть': 3, 'Снято': 4 };

/**
 * Обновляет лист «Работы» из файла «Обновление для трекера» (его собирает build.py из трёх выгрузок).
 * apply=false — только показывает, что изменится; apply=true — записывает.
 * Отметки сотрудников не стираются: у работы, которую кто-то менял в трекере, статус, исполнитель, мастер, акт, факт и месяц остаются,
 * а расхождение с источниками попадает в «Сверить». Пустые поля заполняются всегда. Работы, которых нет в файле, не удаляются.
 */
function importWorks(token, json, apply) {
  var user = requireAdmin_(token);
  var src;
  try { src = JSON.parse(json); } catch (e) { throw new Error('Файл не читается. Нужен файл «Обновление для трекера … .json».'); }
  if (!src || src.format !== IMPORT_FORMAT || !Array.isArray(src.items)) throw new Error('Это не файл обновления трекера. Нужен файл «Обновление для трекера … .json».');
  if (!src.items.length) throw new Error('В файле нет работ.');
  if (src.items.length > IMPORT_MAX_ITEMS) throw new Error('В файле слишком много работ.');
  var lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    return importWorks_(user, src, !!apply);
  } finally {
    lock.releaseLock();
  }
}

function importText_(addr, work) {
  var n = function (v) { return String(v == null ? '' : v).toLowerCase().replace(/\s+/g, ' ').trim(); };
  return n(addr) + '|' + n(work);
}

function importItem_(x) {
  if (!x || typeof x !== 'object') return 'не объект';
  var s = function (v, n) { return String(v == null ? '' : v).trim().slice(0, n); };
  var num = function (v) { v = Number(v); return v > 0 ? v : null; };
  var it = { key: s(x.key, 40), month: s(x.month, 7), addr: s(x.addr, 300), work: s(x.work, 2000) };
  if (!it.key) return 'нет ключа';
  if (!MONTH_RE.test(it.month)) return 'неверный месяц «' + it.month + '»';
  if (!it.addr || !it.work) return 'нет адреса или работы';
  it.row = Number(x.row) || null;
  it.uk = s(x.uk, 80); it.cat = s(x.cat, 80); it.basis = s(x.basis, 500);
  it.sum = num(x.sum); it.fsum = num(x.fsum);
  it.ex = EXECUTORS.indexOf(x.ex) >= 0 ? x.ex : 'Не распределено';
  it.status = STATUSES.indexOf(x.status) >= 0 ? x.status : 'Нет статуса';
  it.src = s(x.src_note, 2000); it.kr = s(x.kr, 100); it.act = s(x.act, 200); it.master = s(x.master, 80);
  it.bxStage = s(x.bx_stage, 80); it.bxDates = s(x.bx_dates, 200); it.check = s(x.check, 1000);
  return it;
}

function importDate_(iso) {
  var m = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(iso || ''));
  return m ? m[3] + '.' + m[2] + '.' + m[1] : '';
}

function importWorks_(user, src, apply) {
  var N = WORK_COLS.length, sh = sheet_(SHEET_WORKS), now = new Date();
  var data = sh.getLastRow() > 1 ? sh.getRange(2, 1, sh.getLastRow() - 1, N).getValues() : [];
  var byKey = {}, byText = {};
  data.forEach(function (r, i) {
    if (r[0]) byKey[String(r[0])] = i;
    var t = importText_(r[3], r[5]);
    (byText[t] = byText[t] || []).push(i);
  });
  var rep = { generated: String(src.generated || ''), total: src.items.length, invalid: 0, errors: [], matched: 0, viaText: 0, added: 0, updated: 0,
    kept: 0, flagged: 0, missing: 0, changes: {}, addedList: [], statusList: [], flagList: [], missingList: [], applied: false };
  var items = [], used = {}, matches = [], rest = [], newRows = [], logRows = [], dirty = false;

  src.items.forEach(function (raw, n) {
    var it = importItem_(raw);
    if (typeof it === 'string') {
      rep.invalid++;
      if (rep.errors.length < 5) rep.errors.push('Работа ' + (n + 1) + ': ' + it);
      return;
    }
    items.push(it);
  });
  // сначала сопоставляем по ключу, затем оставшиеся — по адресу и тексту работы (месяц в плане мог измениться)
  items.forEach(function (it) {
    var i = byKey[it.key];
    if (i !== undefined && !used[i]) { used[i] = true; matches.push([i, it]); } else rest.push(it);
  });
  rest.forEach(function (it) {
    var cand = byText[importText_(it.addr, it.work)] || [], i;
    for (var c = 0; c < cand.length; c++) if (!used[cand[c]]) { i = cand[c]; break; }
    if (i !== undefined) { used[i] = true; matches.push([i, it]); rep.viaText++; } else newRows.push(it);
  });
  rep.matched = matches.length;

  var count = function (k) { rep.changes[k] = (rep.changes[k] || 0) + 1; };
  matches.forEach(function (m) {
    var r = data[m[0]], it = m[1], touched = !!(r[15] || r[16]), meaningful = false, rowLog = [];
    var blank = function (v) { return v === '' || v == null; };
    var put = function (idx, val, label, counter) {   // записывает значение, если оно отличается
      if (String(r[idx]) === String(val)) return false;
      if (counter) { meaningful = true; count(counter); rowLog.push([label, r[idx], val]); }
      r[idx] = val; dirty = true;
      return true;
    };
    // что приходит из источников всегда
    if (it.row) put(1, it.row);
    if (it.src) put(13, it.src);
    if (it.bxStage || it.bxDates) {
      var b1 = it.bxStage && String(r[21]) !== it.bxStage, b2 = it.bxDates && String(r[22]) !== it.bxDates;
      if (b1) put(21, it.bxStage); if (b2) put(22, it.bxDates);
      if (b1 || b2) { meaningful = true; count('bx'); }
    }
    // что трогает только непомеченные работы; пустое поле заполняется всегда
    var free = !touched;
    if (it.basis && (free || blank(r[7]))) put(7, it.basis);
    if (it.cat && (free || blank(r[6]) || r[6] === 'Добавлено вручную')) put(6, it.cat);
    if (it.uk && (free || blank(r[4]))) put(4, it.uk, 'Упр. компания', 'uk');
    if (it.sum && (free || !Number(r[8])) && Number(r[8]) !== it.sum) put(8, it.sum, 'Оценка, ₽', 'sum');
    if (it.ex !== 'Не распределено' && (free || r[10] === 'Не распределено')) put(10, it.ex, 'Исполнитель', 'ex');
    if (it.master && (free || blank(r[20]))) put(20, it.master, 'Мастер участка', 'master');
    if (it.fsum && (free || !Number(r[9])) && Number(r[9]) !== it.fsum) put(9, it.fsum, 'Факт, ₽', 'fsum');
    if (it.act && (free || blank(r[18]))) put(18, it.act, 'Акт', 'act');
    var curMonth = monthStr_(r[2]);
    if (free && it.month !== curMonth) {
      if (blank(r[19])) r[19] = curMonth;
      put(2, it.month, 'Перенос срока', 'month');
    }
    // статус: вперёд — да, назад — никогда
    var cur = String(r[11]), rank = function (s) { return STAGE_RANK[s] === undefined ? -1 : STAGE_RANK[s]; }, flag = '';
    if (it.status !== cur) {
      if (free) {
        if (rank(it.status) >= rank(cur)) put(11, it.status, 'Статус', 'status'); else rep.kept++;
      } else if (it.status === 'Снято' || rank(it.status) > rank(cur)) {
        flag = 'Обновление от ' + importDate_(src.generated) + ': в источниках «' + it.status + '», в трекере «' + cur + '»';
      }
    }
    if (flag) {
      if (put(23, flag, 'Сверка', 'check')) {
        rep.flagged++;
        if (rep.flagList.length < 12) rep.flagList.push({ addr: String(r[3]), work: String(r[5]), text: flag });
      }
    } else if (it.check && it.check !== String(r[23]) && (free || !blank(r[23]))) {
      put(23, it.check, 'Сверка', 'check');
    }
    if (meaningful) rep.updated++;
    rowLog.forEach(function (c) {
      if (c[0] === 'Статус' && rep.statusList.length < 12) rep.statusList.push({ addr: String(r[3]), work: String(r[5]), from: String(c[1]), to: String(c[2]) });
      if (['Статус', 'Исполнитель', 'Мастер участка', 'Перенос срока', 'Сверка', 'Акт', 'Факт, ₽'].indexOf(c[0]) >= 0)
        logRows.push([now, user.name, String(r[0]), String(r[3]), String(r[5]), 'Импорт: ' + c[0].toLowerCase(), c[1], c[2]]);
    });
  });

  rep.added = newRows.length;
  newRows.forEach(function (it, n) {
    if (rep.addedList.length < 12) rep.addedList.push({ addr: it.addr, work: it.work, month: it.month });
    if (n < 100) logRows.push([now, user.name, it.key, it.addr, it.work, 'Импорт: новая работа', '', it.status]);
  });
  data.forEach(function (r, i) {
    if (used[i] || r[6] === 'Добавлено вручную' || /^n[0-9a-f]{8}$/.test(String(r[0]))) return;
    rep.missing++;
    if (rep.missingList.length < 12) rep.missingList.push({ addr: String(r[3]), work: String(r[5]) });
  });

  if (apply && (dirty || newRows.length)) {
    var pad = function (r) { var o = r.slice(0, N); while (o.length < N) o.push(''); return o.map(safe_); };
    if (dirty) sh.getRange(2, 1, data.length, N).setValues(data.map(pad));
    if (newRows.length) {
      var rows = newRows.map(function (it) {
        return pad([it.key, it.row || '', it.month, it.addr, it.uk, it.work, it.cat, it.basis, it.sum || '', it.fsum || '', it.ex, it.status, '', it.src,
          it.kr, '', '', '', it.act, it.month, it.master, it.bxStage, it.bxDates, it.check]);
      });
      sh.getRange(sh.getLastRow() + 1, 1, rows.length, N).setValues(rows);
    }
    logRows.push([now, user.name, 'импорт', '', 'Обновление от ' + (importDate_(src.generated) || 'без даты'), 'Импорт данных', '',
      'добавлено ' + rep.added + ', обновлено ' + rep.updated + ', на сверку ' + rep.flagged]);
    var log = sheet_(SHEET_LOG);
    log.getRange(log.getLastRow() + 1, 1, logRows.length, 8).setValues(logRows.map(function (r) { return r.map(safe_); }));
    bumpRev_();
    rep.applied = true;
  }
  return rep;
}

function addIssue(token, q) {
  var user = auth_(token);
  if (user.role !== 'Администратор') throw new Error('Добавлять вопросы может только администратор.');
  q = q || {};
  var text = String(q.text || '').trim().slice(0, 1000);
  if (!text) throw new Error('Опишите вопрос.');
  var lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    var sh = sheet_(SHEET_ISSUES);
    var nums = sh.getLastRow() > 1 ? sh.getRange(2, 1, sh.getLastRow() - 1, 1).getValues().map(function (r) { return Number(r[0]) || 0; }) : [];
    var num = Math.max.apply(null, nums.concat([0])) + 1;
    sh.appendRow([num, safe_(text), safe_(String(q.resp || '').trim()), safe_(String(q.term || '').trim()), '', false, '', '']);
    sheet_(SHEET_LOG).appendRow([new Date(), user.name, 'q' + num, '', safe_(text.slice(0, 120)), 'Новый вопрос', '', '']);
    bumpRev_();
    return readIssues_();
  } finally {
    lock.releaseLock();
  }
}

function setIssue(token, num, done) {
  var user = auth_(token);
  if (user.role !== 'Администратор') throw new Error('Закрывать вопросы может только администратор.');
  var lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    var sh = sheet_(SHEET_ISSUES);
    var data = sh.getDataRange().getValues();
    for (var i = 1; i < data.length; i++) {
      if (Number(data[i][0]) === Number(num)) {
        sh.getRange(i + 1, 6, 1, 3).setValues([[!!done, user.name, new Date()]]);
        sheet_(SHEET_LOG).appendRow([new Date(), user.name, 'q' + num, '', String(data[i][1]).slice(0, 120), 'Вопрос', '', done ? 'решён' : 'открыт']);
        bumpRev_();
        return true;
      }
    }
    throw new Error('Вопрос не найден.');
  } finally {
    lock.releaseLock();
  }
}

/* ---------------- пользователи (администратор) ---------------- */

function listUsers(token) {
  requireAdmin_(token);
  return readUsers_().map(function (u) { return { name: u.name, role: u.role, active: u.active, hasPin: u.hasPin, bxId: u.bxId }; });
}

/** u: {name, role, active, pin?, bxId?, oldName?} */
function saveUser(token, u) {
  var admin = requireAdmin_(token);
  var name = String(u.name || '').trim();
  if (!name) throw new Error('Укажите имя.');
  if (ROLES.indexOf(u.role) < 0) throw new Error('Выберите роль.');
  var pin = String(u.pin || '').trim();
  if (pin && !/^\d{4,8}$/.test(pin)) throw new Error('PIN — от 4 до 8 цифр.');
  var bxId = String(u.bxId || '').trim();
  if (bxId && !/^\d+$/.test(bxId)) throw new Error('ID в Битрикс24 — число из адреса профиля сотрудника.');
  var lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    var sh = sheet_(SHEET_USERS);
    var data = sh.getDataRange().getValues();
    var target = String(u.oldName || name).trim();
    var idx = 0;
    for (var i = 1; i < data.length; i++) {
      var n = String(data[i][0]).trim();
      if (n === target) idx = i + 1;
      else if (n === name) throw new Error('Пользователь с таким именем уже есть.');
      else if (bxId && String(data[i][5] || '').trim() === bxId) throw new Error('Этот ID Битрикс24 уже привязан к «' + n + '».');
    }
    if (idx && target === admin.name && (u.role !== 'Администратор' || !u.active)) throw new Error('Нельзя снять права администратора с себя.');
    if (!idx) {
      if (!pin && !bxId) throw new Error('Задайте PIN или ID в Битрикс24.');
      sh.appendRow([safe_(name), u.role, !!u.active, '', pin ? hashPin_(pin) : '', bxId]);
    } else {
      var hash = pin ? hashPin_(pin) : data[idx - 1][4];
      sh.getRange(idx, 1, 1, 6).setValues([[safe_(name), u.role, !!u.active, '', hash, bxId]]);
    }
    return listUsers(token);
  } finally {
    lock.releaseLock();
  }
}

/* ---------------- служебное ---------------- */

function auth_(token) {
  var raw = token && CacheService.getScriptCache().get('s:' + token);
  if (!raw) throw new Error('SESSION_EXPIRED');
  var user = JSON.parse(raw);
  // роль берём из таблицы: администратор мог её поменять или отключить пользователя
  var cur = readUsers_().filter(function (u) { return u.name === user.name; })[0];
  if (!cur || !cur.active) throw new Error('SESSION_EXPIRED');
  user.role = cur.role;
  return user;
}

function requireAdmin_(token) {
  var u = auth_(token);
  if (u.role !== 'Администратор') throw new Error('Только для администратора.');
  return u;
}

function canEditWork_(user, item) {
  if (user.role === 'Администратор') return true;
  if (user.role === 'УК') return item.ex === 'УК';
  if (user.role === 'Подрядчики') return item.ex === 'Подрядчики';
  return false;
}

function readUsers_() {
  var sh = sheet_(SHEET_USERS);
  var data = sh.getDataRange().getValues();
  var out = [];
  for (var i = 1; i < data.length; i++) {
    var r = data[i];
    if (!String(r[0]).trim()) continue;
    out.push({ name: String(r[0]).trim(), role: ROLES.indexOf(r[1]) >= 0 ? r[1] : 'Просмотр', active: isTrue_(r[2]), hasPin: !!(r[3] || r[4]), bxId: String(r[5] || '').trim() });
  }
  return out;
}

/** Строки, вставленные в лист «Работы» вручную без ключа, получают ключ — так план можно дополнять прямо в таблице. */
function ensureKeys_() {
  var sh = sheet_(SHEET_WORKS);
  var last = sh.getLastRow();
  if (last < 2) return;
  var vals = sh.getRange(2, 1, last - 1, 6).getValues();
  var missing = [];
  vals.forEach(function (r, i) { if (!r[0] && r[3] && r[5]) missing.push(i); });
  if (!missing.length) return;
  var lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    missing.forEach(function (i) { sh.getRange(i + 2, 1).setValue('n' + Utilities.getUuid().slice(0, 8)); });
    bumpRev_();
  } finally {
    lock.releaseLock();
  }
}

function readWorks_() {
  var data = sheet_(SHEET_WORKS).getDataRange().getValues();
  var out = [];
  for (var i = 1; i < data.length; i++) if (data[i][0]) out.push(workFromRow_(data[i]));
  return out;
}

function workFromRow_(r) {
  return {
    key: String(r[0]), row: r[1] || null, month: monthStr_(r[2]), addr: String(r[3]), uk: String(r[4] || ''), work: String(r[5]),
    cat: String(r[6] || ''), basis: String(r[7] || ''), sum: Number(r[8]) || null, fsum: Number(r[9]) || null,
    ex: EXECUTORS.indexOf(r[10]) >= 0 ? r[10] : 'Не распределено', status: STATUSES.indexOf(r[11]) >= 0 ? r[11] : 'Нет статуса',
    note: String(r[12] || ''), src: String(r[13] || ''), kr: String(r[14] || ''),
    at: r[15] instanceof Date ? r[15].getTime() : null, by: String(r[16] || ''),
    doneAt: r[17] instanceof Date ? r[17].getTime() : null, act: String(r[18] || ''), month0: monthStr_(r[19]) || monthStr_(r[2]),
    master: String(r[20] || ''), bxStage: String(r[21] || ''), bxDates: String(r[22] || ''), check: String(r[23] || '')
  };
}

function readIssues_() {
  var data = sheet_(SHEET_ISSUES).getDataRange().getValues();
  var out = [];
  for (var i = 1; i < data.length; i++) {
    var r = data[i];
    if (!r[1]) continue;
    out.push({ num: Number(r[0]), text: String(r[1]), resp: String(r[2] || ''), term: String(r[3] || ''), ref: String(r[4] || ''),
      done: isTrue_(r[5]), by: String(r[6] || ''), at: r[7] instanceof Date ? r[7].getTime() : null });
  }
  return out;
}

function readLog_(n) {
  var sh = sheet_(SHEET_LOG);
  var last = sh.getLastRow();
  if (last < 2) return [];
  var from = Math.max(2, last - n + 1);
  return sh.getRange(from, 1, last - from + 1, LOG_COLS.length).getValues().reverse().map(function (r) {
    return { at: r[0] instanceof Date ? r[0].getTime() : null, by: String(r[1]), key: String(r[2]), addr: String(r[3]),
      work: String(r[4]), what: String(r[5]), from: String(r[6]), to: String(r[7]) };
  });
}

function findRow_(sh, key) {
  var keys = sh.getRange(1, 1, sh.getLastRow(), 1).getValues();
  for (var i = 1; i < keys.length; i++) if (String(keys[i][0]) === key) return i + 1;
  return 0;
}

function monthStr_(v) {
  if (v instanceof Date) return Utilities.formatDate(v, SpreadsheetApp.getActiveSpreadsheet().getSpreadsheetTimeZone(), 'yyyy-MM');
  return String(v || '');
}

/** Текст, начинающийся с = + - @, таблица считает формулой — экранируем апострофом. */
function safe_(v) {
  return typeof v === 'string' && /^[=+\-@]/.test(v) ? "'" + v : v;
}

function isTrue_(v) { return v === true || String(v).toLowerCase() === 'true' || v === 'да' || v === 'Да'; }

function hashPin_(pin) {
  var salt = PropertiesService.getScriptProperties().getProperty('SALT') || '';
  var bytes = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, salt + ':' + pin, Utilities.Charset.UTF_8);
  return Utilities.base64Encode(bytes);
}

function sheet_(name) {
  var sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(name);
  if (!sh) throw new Error('Нет листа «' + name + '». Запустите setup() в редакторе скриптов.');
  return sh;
}

function getRev_() { return Number(PropertiesService.getScriptProperties().getProperty('REV') || 0); }
function bumpRev_() { var p = PropertiesService.getScriptProperties(); p.setProperty('REV', String(getRev_() + 1)); }
