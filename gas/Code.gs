/**
 * Трекер текущего ремонта — веб-приложение Google Apps Script.
 * Данные хранятся в Google Таблице, к которой привязан скрипт.
 * Вход по имени и PIN-коду, права проверяются здесь, на сервере.
 *
 * Роли:
 *   Администратор — меняет всё: статус, исполнителя, комментарий, добавляет работы, закрывает вопросы, ведёт пользователей.
 *   СВОИ          — меняет статус и комментарий только в работах с исполнителем «СВОИ».
 *   Подрядчики    — меняет статус и комментарий только в работах с исполнителем «Подрядчики».
 *   Просмотр      — только смотрит.
 */

var SHEET_WORKS = 'Работы';
var SHEET_USERS = 'Пользователи';
var SHEET_LOG = 'Журнал';
var SHEET_ISSUES = 'Вопросы';

var WORK_COLS = ['Ключ', 'Строка', 'Месяц', 'Адрес', 'УК', 'Работа', 'Вид работ', 'Основание', 'Оценка, ₽', 'Факт, ₽',
  'Исполнитель', 'Статус', 'Комментарий', 'Из файла', 'КР', 'Изменено', 'Кем'];
var USER_COLS = ['Имя', 'Роль', 'Активен', 'Новый PIN', 'PIN-хэш'];
var LOG_COLS = ['Время', 'Пользователь', 'Ключ', 'Адрес', 'Работа', 'Что', 'Было', 'Стало'];
var ISSUE_COLS = ['№', 'Вопрос', 'Ответственный', 'Срок', 'Ссылка', 'Решён', 'Кем', 'Когда'];

var ROLES = ['Администратор', 'СВОИ', 'Подрядчики', 'Просмотр'];
var EXECUTORS = ['Подрядчики', 'СВОИ', 'Не распределено'];
var STATUSES = ['Нужно решение', 'Требует уточнения', 'Нет статуса', 'Вопрос капремонта', 'Голосование ОСС', 'Не начато',
  'Передано исполнителю', 'На контроле', 'Материал заказан', 'В работе', 'Отложено на зиму', 'Выполнено', 'Снято'];
var MONTHS = ['2026-09', '2026-10', '2026-11', '2026-12'];

var SESSION_HOURS = 6;
var MAX_FAILS = 5;

/* ---------------- web ---------------- */

function doGet() {
  return HtmlService.createTemplateFromFile('Index').evaluate()
    .setTitle('Трекер текущего ремонта')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.DEFAULT);
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
    var rows = SEED.items.map(function (it) {
      return [it.key, it.row || '', it.month, it.addr, it.uk || '', it.work, it.cat || '', it.basis || '', it.sum || '', it.fsum || '',
        it.ex, it.status, '', it.src_note || '', it.kr || '', '', ''];
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
    users.appendRow(['Администратор', 'Администратор', true, '', hashPin_(pin)]);
    users.getRange(2, 2, 200, 1).setDataValidation(SpreadsheetApp.newDataValidation().requireValueInList(ROLES).build());
    Logger.log('Администратор создан. Имя: «Администратор», PIN: ' + pin + ' — запишите его, он больше не показывается.');
  }
  var def = ss.getSheetByName('Лист1') || ss.getSheetByName('Sheet1');
  if (def && ss.getSheets().length > 1 && def.getLastRow() === 0) ss.deleteSheet(def);
  bumpRev_();
}

/* ---------------- вход ---------------- */

function getLoginNames() {
  return readUsers_().filter(function (u) { return u.active; }).map(function (u) { return u.name; });
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
      var token = Utilities.getUuid();
      var user = { name: name, role: ROLES.indexOf(r[1]) >= 0 ? r[1] : 'Просмотр' };
      cache.put('s:' + token, JSON.stringify(user), SESSION_HOURS * 3600);
      return { token: token, user: user };
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

/* ---------------- запись ---------------- */

/** patch: {status?, note?, ex?} */
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

    var changes = [];
    if (patch.status != null && patch.status !== item.status) {
      if (STATUSES.indexOf(patch.status) < 0) throw new Error('Неизвестный статус.');
      changes.push(['Статус', item.status, patch.status]);
      row[11] = patch.status;
    }
    if (patch.note != null && String(patch.note).trim() !== item.note) {
      var note = String(patch.note).trim().slice(0, 2000);
      changes.push(['Комментарий', item.note, note]);
      row[12] = note;
    }
    if (patch.ex != null && patch.ex !== item.ex) {
      if (user.role !== 'Администратор') throw new Error('Исполнителя меняет только администратор.');
      if (EXECUTORS.indexOf(patch.ex) < 0) throw new Error('Неизвестный исполнитель.');
      changes.push(['Исполнитель', item.ex, patch.ex]);
      row[10] = patch.ex;
    }
    if (!changes.length) return workFromRow_(row);
    var now = new Date();
    row[15] = now;
    row[16] = user.name;
    sh.getRange(rowIdx, 1, 1, WORK_COLS.length).setValues([row]);
    var log = sheet_(SHEET_LOG);
    changes.forEach(function (c) { log.appendRow([now, user.name, key, item.addr, item.work, c[0], c[1], c[2]]); });
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
  if (MONTHS.indexOf(w.month) < 0) throw new Error('Выберите месяц.');
  var ex = EXECUTORS.indexOf(w.ex) >= 0 ? w.ex : 'Не распределено';
  var sum = w.sum === '' || w.sum == null ? '' : Number(w.sum);
  if (sum !== '' && !(sum >= 0)) throw new Error('Оценка — число в рублях.');
  var lock = LockService.getScriptLock();
  lock.waitLock(15000);
  try {
    var key = 'n' + Utilities.getUuid().slice(0, 8);
    var now = new Date();
    var row = [key, '', w.month, addr, String(w.uk || ''), work, 'Добавлено вручную', String(w.basis || ''), sum, '',
      ex, 'Не начато', '', '', '', now, user.name];
    sheet_(SHEET_WORKS).appendRow(row);
    sheet_(SHEET_LOG).appendRow([now, user.name, key, addr, work, 'Добавлена работа', '', ex]);
    bumpRev_();
    return workFromRow_(row);
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
  return readUsers_().map(function (u) { return { name: u.name, role: u.role, active: u.active, hasPin: u.hasPin }; });
}

/** u: {name, role, active, pin?, oldName?} */
function saveUser(token, u) {
  var admin = requireAdmin_(token);
  var name = String(u.name || '').trim();
  if (!name) throw new Error('Укажите имя.');
  if (ROLES.indexOf(u.role) < 0) throw new Error('Выберите роль.');
  var pin = String(u.pin || '').trim();
  if (pin && !/^\d{4,8}$/.test(pin)) throw new Error('PIN — от 4 до 8 цифр.');
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
    }
    if (idx && target === admin.name && (u.role !== 'Администратор' || !u.active)) throw new Error('Нельзя снять права администратора с себя.');
    if (!idx) {
      if (!pin) throw new Error('Для нового пользователя задайте PIN.');
      sh.appendRow([name, u.role, !!u.active, '', hashPin_(pin)]);
    } else {
      var hash = pin ? hashPin_(pin) : data[idx - 1][4];
      sh.getRange(idx, 1, 1, 5).setValues([[name, u.role, !!u.active, '', hash]]);
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
  if (user.role === 'СВОИ') return item.ex === 'СВОИ';
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
    out.push({ name: String(r[0]).trim(), role: ROLES.indexOf(r[1]) >= 0 ? r[1] : 'Просмотр', active: isTrue_(r[2]), hasPin: !!(r[3] || r[4]) });
  }
  return out;
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
    at: r[15] instanceof Date ? r[15].getTime() : null, by: String(r[16] || '')
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
  if (v instanceof Date) return Utilities.formatDate(v, Session.getScriptTimeZone(), 'yyyy-MM');
  return String(v || '');
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
