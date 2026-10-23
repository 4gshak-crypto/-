/* Проверка: браузерное сведение (gas/merge.js) даёт те же работы, что Python (tools/merge_sources.py).
   Запуск после изменения merge.js или merge_sources.py:
     python3 tools/merge_sources.py <план .xls> <исполнители .xlsx> <Битрикс24 .xlsx>
     npm install xlsx@0.18.5
     node tools/test_merge_js.js <план .xls> <исполнители .xlsx> <Битрикс24 .xlsx> [дата плана] [дата исполнителей] [дата Битрикс24]
   Даты в формате ГГГГ-ММ-ДД; по умолчанию 2026-10-16, 2026-10-08, 2026-10-19 (даты выгрузок текущего tracker/merged.json). */
const fs = require('fs'), path = require('path');
const TM = require('../gas/merge.js');
TM.setLib(require('xlsx'));
const ab = p => { const b = fs.readFileSync(p); return b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength); };
const T = path.join(__dirname, '..', 'tracker');
const py = JSON.parse(fs.readFileSync(path.join(T, 'merged.json'), 'utf8'));
const data = JSON.parse(fs.readFileSync(path.join(T, 'data.json'), 'utf8'));
const backlog = JSON.parse(fs.readFileSync(path.join(T, 'backlog.json'), 'utf8'));
const [plan, exec, bx, d1, d2, d3] = process.argv.slice(2);
if (!bx) { console.error('Нужны три файла: план, исполнители, Битрикс24'); process.exit(2); }
const res = TM.merge({
  plan: ab(plan), exec: ab(exec), bx: ab(bx), dates: { plan: d1 || '2026-10-16', exec: d2 || '2026-10-08', bx: d3 || '2026-10-19' }, today: py.generated,
  canon: data.groups.map(g => g.addr).concat(backlog.map(b => b.addr)),
  prev: [].concat(...data.groups.map(g => g.items.map(i => ({ addr: i.addr, work: i.work, month: i.month, cat: i.cat }))))
});
const F = ['key', 'row', 'month', 'addr', 'uk', 'work', 'cat', 'basis', 'sum', 'fsum', 'ex', 'master', 'status', 'act', 'kr', 'bx_stage', 'bx_dates', 'src_note', 'check'];
let bad = 0;
for (let i = 0; i < Math.max(res.items.length, py.items.length); i++) {
  const a = res.items[i], b = py.items[i];
  if (!a || !b) { bad++; console.log('нет пары', i); continue; }
  F.forEach(f => {
    const x = a[f] === undefined ? null : a[f], y = b[f] === undefined ? null : b[f];
    const same = typeof x === 'number' || typeof y === 'number' ? Math.abs((x || 0) - (y || 0)) < 1e-9 : x === y || (x === '' && y === null) || (x === null && y === '');
    if (!same) { bad++; if (bad <= 15) console.log('РАЗНИЦА #' + i, f, 'JS:', JSON.stringify(x), 'Python:', JSON.stringify(y), '|', a.addr); }
  });
}
console.log('работ: JS', res.items.length, ', Python', py.items.length, '| расхождений:', bad);
process.exit(bad ? 1 : 0);
