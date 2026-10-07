/**
 * Татарча тәрҗемәче — веб-приложение на Google Apps Script.
 * Страница Index.html та же, что translator/index.html в репозитории.
 * Перевод делает встроенный в Apps Script сервис LanguageApp (Google Переводчик).
 */

var LANGS = { tt: 'tt', ru: 'ru', en: 'en' };

function doGet() {
  return HtmlService.createHtmlOutputFromFile('Index')
    .setTitle('Татарча тәрҗемәче')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

/**
 * Переводит text с языка from на язык to. Вызывается со страницы через google.script.run.
 * @param {string} text  Текст (до 5000 символов).
 * @param {string} from  tt | ru | en
 * @param {string} to    tt | ru | en
 * @return {string} перевод
 */
function translateText(text, from, to) {
  text = String(text || '').slice(0, 5000);
  if (!text.trim()) return '';
  var src = LANGS[from], dst = LANGS[to];
  if (!src || !dst) throw new Error('Неизвестный язык: ' + from + ' → ' + to);
  // LanguageApp не сохраняет переносы строк: переводим построчно.
  var lines = text.split('\n');
  var out = [];
  for (var i = 0; i < lines.length; i++) {
    out.push(lines[i].trim() ? LanguageApp.translate(lines[i], src, dst) : '');
  }
  return out.join('\n');
}
