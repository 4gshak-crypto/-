/**
 * Telegram-бот для заказчиков: услуги, вопросы, заявка по шагам,
 * пересылка сообщений вам и ваши ответы клиентам прямо из Telegram.
 * Заявки и переписка пишутся в Google Таблицу. Сюда же приходят заявки с сайта.
 *
 * Свойства скрипта (Настройки проекта → Свойства скрипта):
 *   BOT_TOKEN   — токен от @BotFather (обязательно)
 *   ADMIN_CODE  — код, которым вы назначаете себя администратором: /admin КОД
 *   WEBAPP_URL  — адрес развёрнутого веб-приложения …/exec (для setWebhook)
 * Остальное (SHEET_ID, ADMIN_CHAT_ID) бот заполнит сам.
 */

// ===== Тексты — правьте под себя =====

var BRAND = 'Ведомость';
var WORK_HOURS = { from: 9, to: 18, days: [1, 2, 3, 4, 5] }; // пн–пт, 9:00–18:00 по часовому поясу проекта
var SITE_URL = ''; // адрес сайта, например https://4gshak-crypto.github.io/-/

var SERVICES = [
  { id: 'tracker', title: 'Трекер текущего ремонта',
    text: 'Все работы годового плана по месяцам: адрес, основание, оценка, исполнитель и статус. ' +
          'Сводка план/факт по категориям, перенос сроков, акт и фактическая сумма, журнал изменений.' },
  { id: 'webapp', title: 'Веб-приложение на Google Таблице',
    text: 'Отдельный сайт для сотрудников и подрядчиков с входом по имени и PIN. ' +
          'Роли и права проверяет сервер, таблица остаётся у вас как база и резервная копия.' },
  { id: 'bitrix', title: 'Встраивание в Битрикс24',
    text: 'Трекер открывается пунктом меню облачного портала, сотрудники входят под своей учётной записью. ' +
          'Подрядчики без портала работают по прямой ссылке.' },
  { id: 'excel', title: 'Перенос и сверка данных из Excel',
    text: 'Разбираю годовой план, где статус хранится цветом строки. Нахожу дубли, пустые основания ' +
          'и расхождения итогов, выдаю список открытых вопросов.' },
  { id: 'reports', title: 'Отчёты для руководства и собственников',
    text: 'Сводка выполненных работ по дому или по УК за месяц и год: что сделано, на какие деньги и на каком основании.' },
  { id: 'support', title: 'Сопровождение и доработки',
    text: 'Новые поля, статусы и роли, подключение ещё одной УК, обучение сотрудников, поддержка по договору.' }
];

var PRICE_TEXT =
  '<b>Стоимость и сроки</b>\n\n' +
  'Цена зависит от объёма плана, числа ролей и нужных отчётов. Точную смету называю после разбора ваших файлов, это бесплатно.\n\n' +
  'Типичный трекер для одной УК запускается за 1–2 недели. Оплата по этапам: разбор, прототип на ваших данных, запуск, сопровождение.';

var FAQ = [
  { q: 'Нужно покупать программу?', a: 'Нет. Всё работает на бесплатном Google Apps Script и вашей Google Таблице. Вы платите только за разработку и сопровождение.' },
  { q: 'Где хранятся данные?', a: 'В вашей Google Таблице, на вашем аккаунте. Сотрудники работают через ссылку и саму таблицу не видят.' },
  { q: 'У нас Битрикс24', a: 'Трекер встраивается в облачный Битрикс24 пунктом меню, вход под учётной записью портала.' },
  { q: 'План ведём в Excel с цветными строками', a: 'Это самый частый случай. Статус читается по цвету заливки, номера строк исходного плана сохраняются.' },
  { q: 'Можно не про ремонт?', a: 'Да: журнал заявок, сезонные осмотры, подготовка к отопительному сезону, предписания ГЖИ.' }
];

var BTN = {
  services: 'Услуги',
  price: 'Стоимость и сроки',
  lead: 'Оставить заявку',
  faq: 'Вопросы',
  write: 'Написать сообщение',
  cancel: 'Отмена',
  skip: 'Пропустить',
  phone: 'Отправить мой номер',
  viaTg: 'Пишите сюда, в Telegram'
};

var HOUSES = ['до 20', '20–100', '100–300', 'больше 300'];

// ===== Установка =====

/** Запустите один раз из редактора: создаст листы и запомнит таблицу. */
function setup() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) throw new Error('Откройте скрипт из Google Таблицы: Расширения → Apps Script.');
  var props = PropertiesService.getScriptProperties();
  props.setProperty('SHEET_ID', ss.getId());
  ensureSheet_(ss, 'Заявки', ['№', 'Дата', 'Источник', 'Имя', 'Организация', 'Домов', 'Задача', 'Контакт', 'Telegram', 'Chat ID', 'Статус']);
  ensureSheet_(ss, 'Переписка', ['Дата', 'Chat ID', 'Клиент', 'Направление', 'Текст']);
  ensureSheet_(ss, 'Связи', ['Сообщение у админа', 'Chat ID клиента', 'Дата']);
  if (!props.getProperty('ADMIN_CODE')) {
    var code = String(Math.floor(100000 + Math.random() * 900000));
    props.setProperty('ADMIN_CODE', code);
    Logger.log('Код администратора: %s. Отправьте боту: /admin %s', code, code);
  } else {
    Logger.log('Код администратора уже задан в свойствах скрипта (ADMIN_CODE).');
  }
}

/** Запустите после развёртывания веб-приложения и заполнения WEBAPP_URL. */
function setWebhook() {
  var url = prop_('WEBAPP_URL');
  if (!url) throw new Error('Заполните свойство WEBAPP_URL адресом …/exec');
  Logger.log(JSON.stringify(tg_('setWebhook', { url: url, drop_pending_updates: true, allowed_updates: ['message', 'callback_query'] })));
  tg_('setMyCommands', { commands: [
    { command: 'start', description: 'Главное меню' },
    { command: 'lead', description: 'Оставить заявку' },
    { command: 'cancel', description: 'Отменить ввод' }
  ] });
}

/** Проверка: что Telegram знает о вебхуке (последняя ошибка, очередь). */
function webhookInfo() {
  Logger.log(JSON.stringify(tg_('getWebhookInfo', {}), null, 2));
}

// ===== Точка входа =====

function doPost(e) {
  var body;
  try { body = JSON.parse(e.postData.contents); } catch (err) { return ok_(); }

  if (body && body.update_id !== undefined) {
    // Telegram повторяет запрос, если ответ ему не понравился, — обрабатываем каждое обновление один раз.
    var lock = LockService.getScriptLock();
    if (!lock.tryLock(20000)) return ok_(); // Telegram повторит позже
    try {
      var cache = CacheService.getScriptCache();
      var key = 'u:' + body.update_id;
      if (!cache.get(key)) {
        cache.put(key, '1', 21600);
        handleUpdate_(body);
      }
    } catch (err) { console.error(err && err.stack || err); }
    finally { lock.releaseLock(); }
    return ok_();
  }

  if (body && body.source === 'site') {
    var res = { ok: false };
    var siteLock = LockService.getScriptLock();
    if (siteLock.tryLock(20000)) {
      try { res = handleSiteLead_(body); } catch (err) { console.error(err && err.stack || err); }
      finally { siteLock.releaseLock(); }
    }
    return ContentService.createTextOutput(JSON.stringify(res)).setMimeType(ContentService.MimeType.JSON);
  }
  return ok_();
}

function doGet() {
  return ContentService.createTextOutput('Бот работает.');
}

function ok_() { return ContentService.createTextOutput('ok'); }

// ===== Обработка обновлений =====

function handleUpdate_(u) {
  if (u.callback_query) return handleCallback_(u.callback_query);
  var m = u.message;
  if (!m || !m.chat || m.chat.type !== 'private') return;

  var chatId = String(m.chat.id);
  var text = (m.text || '').trim();

  if (/^\/admin(\s|$)/.test(text)) return registerAdmin_(chatId, text);
  if (chatId === prop_('ADMIN_CHAT_ID')) return handleAdmin_(m, text);
  handleClient_(m, chatId, text);
}

function handleClient_(m, chatId, text) {
  var st = getState_(chatId);

  if (text === '/cancel' || text === BTN.cancel) {
    clearState_(chatId);
    return send_(chatId, 'Хорошо, отменил. Чем ещё могу помочь?', mainKeyboard_());
  }
  if (/^\/start/.test(text)) {
    clearState_(chatId);
    var fromSite = /site/.test(text);
    return send_(chatId,
      'Здравствуйте' + (m.from.first_name ? ', ' + esc_(m.from.first_name) : '') + '!\n\n' +
      (fromSite ? 'Спасибо, что пришли с сайта. ' : '') +
      'Это бот <b>' + esc_(BRAND) + '</b>. Помогаю управляющим компаниям и ТСЖ вести текущий ремонт, заявки и отчёты в одной таблице.\n\n' +
      'Выберите, что вас интересует, или просто напишите вопрос — я его прочитаю и отвечу.',
      mainKeyboard_());
  }

  if (st && st.step) return leadStep_(m, chatId, text, st);

  if (text === BTN.services || text === '/services') return sendServices_(chatId);
  if (text === BTN.price) return send_(chatId, PRICE_TEXT, mainKeyboard_());
  if (text === BTN.faq) return sendFaq_(chatId);
  if (text === BTN.lead || text === '/lead') return startLead_(chatId);
  if (text === BTN.write) {
    return send_(chatId, 'Напишите сообщение одним или несколькими сообщениями — можно приложить файл или фото. Я отвечу здесь же.', mainKeyboard_());
  }

  // Любое другое сообщение — пересылаем вам.
  forwardToAdmin_(m, chatId);
}

// ===== Заявка по шагам =====

function startLead_(chatId) {
  setState_(chatId, { step: 'name', lead: {} });
  send_(chatId, 'Оформим заявку, это 5 коротких вопросов.\n\n<b>1/5.</b> Как к вам обращаться?', cancelKeyboard_());
}

function leadStep_(m, chatId, text, st) {
  var lead = st.lead || {};
  var from = m.from || {};

  if (st.step === 'name') {
    if (!text) return send_(chatId, 'Напишите, пожалуйста, имя текстом.');
    lead.name = text.slice(0, 100);
    setState_(chatId, { step: 'org', lead: lead });
    return send_(chatId, '<b>2/5.</b> Название организации (УК, ТСЖ, подрядчик)?', keyboard_([[BTN.skip], [BTN.cancel]]));
  }
  if (st.step === 'org') {
    lead.org = text === BTN.skip ? '' : text.slice(0, 150);
    setState_(chatId, { step: 'houses', lead: lead });
    return send_(chatId, '<b>3/5.</b> Сколько домов в управлении?', {
      inline_keyboard: [HOUSES.slice(0, 2).map(houseBtn_), HOUSES.slice(2).map(houseBtn_)]
    });
  }
  if (st.step === 'houses') {
    // Принимаем и текстом, если человек не нажал кнопку.
    lead.houses = text.slice(0, 50);
    return askTask_(chatId, lead);
  }
  if (st.step === 'task') {
    if (!text) return send_(chatId, 'Опишите задачу текстом, пожалуйста.');
    lead.task = text.slice(0, 2000);
    setState_(chatId, { step: 'contact', lead: lead });
    return send_(chatId, '<b>5/5.</b> Как с вами связаться? Отправьте номер кнопкой ниже, напишите телефон или e-mail — или выберите связь здесь, в Telegram.', {
      keyboard: [[{ text: BTN.phone, request_contact: true }], [{ text: BTN.viaTg }], [{ text: BTN.cancel }]],
      resize_keyboard: true, one_time_keyboard: true
    });
  }
  if (st.step === 'contact') {
    if (m.contact && m.contact.phone_number) lead.contact = '+' + String(m.contact.phone_number).replace(/^\+/, '');
    else if (text === BTN.viaTg) lead.contact = 'Telegram';
    else if (text) lead.contact = text.slice(0, 150);
    else return send_(chatId, 'Напишите телефон или e-mail, или нажмите кнопку.');
    lead.tg = from.username ? '@' + from.username : '';
    setState_(chatId, { step: 'confirm', lead: lead });
    send_(chatId, 'Проверьте заявку:', { remove_keyboard: true });
    return send_(chatId, leadCard_(lead), {
      inline_keyboard: [[{ text: 'Отправить', callback_data: 'lead:send' }, { text: 'Заполнить заново', callback_data: 'lead:redo' }]]
    });
  }
  if (st.step === 'confirm') {
    return send_(chatId, 'Нажмите «Отправить» под заявкой выше или «Отмена», чтобы выйти.', cancelKeyboard_());
  }
}

function askTask_(chatId, lead) {
  setState_(chatId, { step: 'task', lead: lead });
  send_(chatId, '<b>4/5.</b> Коротко опишите задачу. Например: «План ремонта ведём в Excel, подрядчики шлют отметки в WhatsApp, итоги месяца сводим вручную».', cancelKeyboard_());
}

function houseBtn_(h) { return { text: h, callback_data: 'h:' + h }; }

function submitLead_(chatId, from) {
  var st = getState_(chatId);
  if (!st || !st.lead || !st.lead.name) return send_(chatId, 'Заявка устарела, давайте заполним заново.', mainKeyboard_());
  var lead = st.lead;
  lead.source = 'Telegram';
  lead.chatId = chatId;
  var num = saveLead_(lead);
  clearState_(chatId);
  logMessage_(chatId, clientName_(from), 'заявка', leadCard_(lead));

  send_(chatId,
    'Заявка №' + num + ' отправлена. ' + replyEta_() + '\n\nЕсли захотите что-то добавить — просто напишите сюда.',
    mainKeyboard_());
  notifyAdminLead_(num, lead);
}

// ===== Кнопки под сообщениями =====

function handleCallback_(q) {
  var chatId = String(q.message.chat.id);
  var data = q.data || '';
  tg_('answerCallbackQuery', { callback_query_id: q.id });

  if (data.indexOf('svc:') === 0) {
    var s = SERVICES.filter(function (x) { return x.id === data.slice(4); })[0];
    if (!s) return;
    return send_(chatId, '<b>' + esc_(s.title) + '</b>\n\n' + esc_(s.text), {
      inline_keyboard: [[{ text: 'Оставить заявку', callback_data: 'lead:start' }], [{ text: 'Все услуги', callback_data: 'svc:list' }]]
    });
  }
  if (data === 'svc:list') return sendServices_(chatId);
  if (data.indexOf('faq:') === 0) {
    var f = FAQ[Number(data.slice(4))];
    if (f) send_(chatId, '<b>' + esc_(f.q) + '</b>\n\n' + esc_(f.a));
    return;
  }
  if (data === 'lead:start') return startLead_(chatId);
  if (data.indexOf('h:') === 0) {
    var st = getState_(chatId);
    if (!st || st.step !== 'houses') return;
    st.lead.houses = data.slice(2);
    editMarkup_(chatId, q.message.message_id, null);
    send_(chatId, 'Домов: ' + esc_(st.lead.houses));
    return askTask_(chatId, st.lead);
  }
  if (data === 'lead:send') {
    editMarkup_(chatId, q.message.message_id, null);
    return submitLead_(chatId, q.from);
  }
  if (data === 'lead:redo') {
    editMarkup_(chatId, q.message.message_id, null);
    return startLead_(chatId);
  }

  // Кнопки администратора под заявкой
  if ((data.indexOf('take:') === 0 || data.indexOf('close:') === 0) && chatId === prop_('ADMIN_CHAT_ID')) {
    var parts = data.split(':');
    var status = parts[0] === 'take' ? 'В работе' : 'Закрыта';
    var row = setLeadStatus_(Number(parts[1]), status);
    editMarkup_(chatId, q.message.message_id, statusKeyboard_(Number(parts[1]), status));
    if (row && row.chatId && status === 'В работе') {
      send_(row.chatId, 'Ваша заявка №' + parts[1] + ' взята в работу. Скоро свяжусь.');
    }
  }
}

// ===== Администратор =====

function registerAdmin_(chatId, text) {
  var code = text.replace(/^\/admin\s*/, '').trim();
  if (!code || code !== prop_('ADMIN_CODE')) return send_(chatId, 'Неверный код.');
  PropertiesService.getScriptProperties().setProperty('ADMIN_CHAT_ID', chatId);
  send_(chatId, 'Готово, вы администратор. Сюда будут приходить заявки и сообщения клиентов.\n\n' + adminHelp_(), { remove_keyboard: true });
}

function adminHelp_() {
  return '<b>Как отвечать</b>\n' +
    'Ответьте (свайп или «Ответить») на сообщение клиента — бот перешлёт ответ ему. Можно отправлять текст, фото и файлы.\n\n' +
    '<b>Команды</b>\n' +
    '/leads — последние 10 заявок\n' +
    '/reply CHAT_ID текст — написать клиенту по номеру чата\n' +
    '/help — эта подсказка';
}

function handleAdmin_(m, text) {
  var adminId = String(m.chat.id);

  if (m.reply_to_message) {
    var target = findLink_(m.reply_to_message.message_id);
    if (!target) return send_(adminId, 'Не знаю, кому отвечать: это сообщение не связано с клиентом. Заявки с сайта без Telegram — свяжитесь по указанному контакту.');
    var r = tg_('copyMessage', { chat_id: target, from_chat_id: adminId, message_id: m.message_id });
    if (!r.ok) return send_(adminId, 'Не доставлено: ' + esc_(r.description || 'ошибка Telegram') + '. Возможно, клиент остановил бота.');
    logMessage_(target, '', 'ответ', text || m.caption || '[вложение]');
    return; // молча: Telegram и так показывает, что сообщение ушло
  }

  if (text === '/leads') return send_(adminId, lastLeads_(10));
  var rep = text.match(/^\/reply\s+(-?\d+)\s+([\s\S]+)/);
  if (rep) {
    var res = send_(rep[1], esc_(rep[2]));
    if (res.ok) logMessage_(rep[1], '', 'ответ', rep[2]);
    return send_(adminId, res.ok ? 'Отправлено.' : 'Не доставлено: ' + esc_(res.description || ''));
  }
  if (/^\/start|^\/help/.test(text)) return send_(adminId, adminHelp_());
  send_(adminId, 'Чтобы ответить клиенту, ответьте на его сообщение. /help — подсказка.');
}

function forwardToAdmin_(m, chatId) {
  var adminId = prop_('ADMIN_CHAT_ID');
  var name = clientName_(m.from);
  logMessage_(chatId, name, 'входящее', m.text || m.caption || '[вложение]');

  if (adminId) {
    var head = send_(adminId, '💬 <b>' + esc_(name) + '</b>' + (m.from.username ? ' @' + esc_(m.from.username) : '') +
      ' · <code>' + chatId + '</code>\nОтветьте на это или следующее сообщение, чтобы написать клиенту.');
    var copy = tg_('copyMessage', { chat_id: adminId, from_chat_id: chatId, message_id: m.message_id });
    if (head.ok) saveLink_(head.result.message_id, chatId);
    if (copy.ok) saveLink_(copy.result.message_id, chatId);
  }

  // Автоответ — не чаще раза в час, чтобы не мешать переписке.
  var cache = CacheService.getScriptCache();
  if (!cache.get('ack:' + chatId)) {
    cache.put('ack:' + chatId, '1', 3600);
    send_(chatId, 'Сообщение получил. ' + replyEta_(), mainKeyboard_());
  }
}

function notifyAdminLead_(num, lead) {
  var adminId = prop_('ADMIN_CHAT_ID');
  if (!adminId) return;
  var r = send_(adminId, '🆕 <b>Заявка №' + num + '</b> · ' + esc_(lead.source) + '\n\n' + leadCard_(lead) +
    (lead.chatId ? '\n\nОтветьте на это сообщение, чтобы написать клиенту.' : ''),
    statusKeyboard_(num, 'Новая'));
  if (r.ok && lead.chatId) saveLink_(r.result.message_id, lead.chatId);
}

function statusKeyboard_(num, status) {
  if (status === 'Закрыта') return { inline_keyboard: [[{ text: 'Закрыта', callback_data: 'noop' }]] };
  if (status === 'В работе') return { inline_keyboard: [[{ text: 'В работе · закрыть', callback_data: 'close:' + num }]] };
  return { inline_keyboard: [[{ text: 'Взять в работу', callback_data: 'take:' + num }, { text: 'Закрыть', callback_data: 'close:' + num }]] };
}

// ===== Заявки с сайта =====

function handleSiteLead_(b) {
  if (b.website) return { ok: true }; // ловушка для ботов: поле скрыто от людей
  var name = String(b.name || '').trim().slice(0, 100);
  var contact = String(b.contact || '').trim().slice(0, 150);
  if (!name || !contact) return { ok: false, error: 'Укажите имя и контакт' };

  // Не больше 20 заявок с сайта в час — защита от спама.
  var cache = CacheService.getScriptCache();
  var n = Number(cache.get('site:rate') || 0);
  if (n >= 20) return { ok: false, error: 'Слишком много заявок, попробуйте позже' };
  cache.put('site:rate', String(n + 1), 3600);

  var lead = {
    source: 'Сайт', name: name,
    org: String(b.org || '').slice(0, 150),
    houses: String(b.size || '').slice(0, 50),
    task: [String(b.need || ''), String(b.msg || '')].filter(String).join('. ').slice(0, 2000),
    contact: contact, tg: '', chatId: ''
  };
  var num = saveLead_(lead);
  notifyAdminLead_(num, lead);
  return { ok: true, num: num };
}

// ===== Таблица =====

function sheet_(name) {
  return SpreadsheetApp.openById(prop_('SHEET_ID')).getSheetByName(name);
}

function ensureSheet_(ss, name, header) {
  var sh = ss.getSheetByName(name) || ss.insertSheet(name);
  if (sh.getLastRow() === 0) {
    sh.appendRow(header);
    sh.getRange(1, 1, 1, header.length).setFontWeight('bold');
    sh.setFrozenRows(1);
  }
  return sh;
}

function saveLead_(lead) {
  var sh = sheet_('Заявки');
  var num = Math.max(sh.getLastRow(), 1); // строка 1 — заголовок
  sh.appendRow([num, new Date(), lead.source, lead.name, lead.org || '', lead.houses || '', lead.task || '',
    lead.contact || '', lead.tg || '', lead.chatId || '', 'Новая']);
  return num;
}

function setLeadStatus_(num, status) {
  var sh = sheet_('Заявки');
  var row = num + 1;
  if (row > sh.getLastRow()) return null;
  sh.getRange(row, 11).setValue(status);
  return { chatId: String(sh.getRange(row, 10).getValue() || '') };
}

function lastLeads_(count) {
  var sh = sheet_('Заявки');
  var last = sh.getLastRow();
  if (last < 2) return 'Заявок пока нет.';
  var from = Math.max(2, last - count + 1);
  var rows = sh.getRange(from, 1, last - from + 1, 11).getValues().reverse();
  return rows.map(function (r) {
    return '<b>№' + r[0] + '</b> · ' + esc_(r[10]) + ' · ' + Utilities.formatDate(new Date(r[1]), Session.getScriptTimeZone(), 'dd.MM HH:mm') + '\n' +
      esc_(r[3]) + (r[4] ? ', ' + esc_(r[4]) : '') + ' — ' + esc_(r[7]) + (r[8] ? ' ' + esc_(r[8]) : '');
  }).join('\n\n');
}

function logMessage_(chatId, name, dir, text) {
  sheet_('Переписка').appendRow([new Date(), chatId, name, dir, String(text).slice(0, 5000)]);
}

function saveLink_(adminMsgId, chatId) {
  sheet_('Связи').appendRow([adminMsgId, chatId, new Date()]);
}

function findLink_(adminMsgId) {
  var sh = sheet_('Связи');
  var last = sh.getLastRow();
  if (last < 2) return null;
  var cell = sh.getRange(2, 1, last - 1, 1).createTextFinder(String(adminMsgId)).matchEntireCell(true).findNext();
  return cell ? String(sh.getRange(cell.getRow(), 2).getValue()) : null;
}

// ===== Состояние диалога (до 6 часов) =====

function getState_(chatId) {
  var v = CacheService.getScriptCache().get('st:' + chatId);
  return v ? JSON.parse(v) : null;
}
function setState_(chatId, st) { CacheService.getScriptCache().put('st:' + chatId, JSON.stringify(st), 21600); }
function clearState_(chatId) { CacheService.getScriptCache().remove('st:' + chatId); }

// ===== Сообщения и клавиатуры =====

function sendServices_(chatId) {
  send_(chatId, '<b>Услуги</b>\n\nНажмите на услугу, чтобы узнать подробнее.', {
    inline_keyboard: SERVICES.map(function (s) { return [{ text: s.title, callback_data: 'svc:' + s.id }]; })
      .concat([[{ text: 'Оставить заявку', callback_data: 'lead:start' }]])
  });
}

function sendFaq_(chatId) {
  send_(chatId, '<b>Частые вопросы</b>\n\nВыберите вопрос или напишите свой.', {
    inline_keyboard: FAQ.map(function (f, i) { return [{ text: f.q, callback_data: 'faq:' + i }]; })
  });
}

function leadCard_(l) {
  return [
    'Имя: ' + esc_(l.name),
    l.org ? 'Организация: ' + esc_(l.org) : null,
    l.houses ? 'Домов: ' + esc_(l.houses) : null,
    l.task ? 'Задача: ' + esc_(l.task) : null,
    'Контакт: ' + esc_(l.contact) + (l.tg ? ' (' + esc_(l.tg) + ')' : '')
  ].filter(Boolean).join('\n');
}

function mainKeyboard_() {
  return keyboard_([[BTN.services, BTN.price], [BTN.lead], [BTN.faq, BTN.write]]);
}
function cancelKeyboard_() { return keyboard_([[BTN.cancel]]); }
function keyboard_(rows) {
  return { keyboard: rows.map(function (r) { return r.map(function (t) { return { text: t }; }); }), resize_keyboard: true };
}

function replyEta_() {
  var now = new Date();
  var tz = Session.getScriptTimeZone();
  var day = Number(Utilities.formatDate(now, tz, 'u')); // 1 = пн … 7 = вс
  var hour = Number(Utilities.formatDate(now, tz, 'H'));
  var working = WORK_HOURS.days.indexOf(day) >= 0 && hour >= WORK_HOURS.from && hour < WORK_HOURS.to;
  return working ? 'Отвечу в течение часа.' : 'Сейчас нерабочее время, отвечу в ближайший рабочий день с ' + WORK_HOURS.from + ':00.';
}

function clientName_(from) {
  from = from || {};
  return [from.first_name, from.last_name].filter(Boolean).join(' ') || (from.username ? '@' + from.username : 'Клиент');
}

function send_(chatId, html, markup) {
  var p = { chat_id: chatId, text: html, parse_mode: 'HTML', disable_web_page_preview: true };
  if (markup) p.reply_markup = markup;
  return tg_('sendMessage', p);
}

function editMarkup_(chatId, messageId, markup) {
  return tg_('editMessageReplyMarkup', { chat_id: chatId, message_id: messageId, reply_markup: markup || { inline_keyboard: [] } });
}

function tg_(method, payload) {
  var res = UrlFetchApp.fetch('https://api.telegram.org/bot' + prop_('BOT_TOKEN') + '/' + method, {
    method: 'post', contentType: 'application/json', payload: JSON.stringify(payload), muteHttpExceptions: true
  });
  try { return JSON.parse(res.getContentText()); } catch (e) { return { ok: false, description: res.getContentText() }; }
}

function prop_(k) { return PropertiesService.getScriptProperties().getProperty(k) || ''; }

function esc_(s) {
  return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
