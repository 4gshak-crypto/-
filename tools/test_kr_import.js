/* Проверка: разбор перечня капремонта и реестра подтоплений в браузере (gas/kr_import.js) даёт то же, что Python (tools/build_kr.py).
     python3 tools/build_kr.py <перечень .xls> --flood <реестр .html> --today ГГГГ-ММ-ДД      (пишет capital/kr.json)
     npm install xlsx@0.18.5
     node tools/test_kr_import.js <перечень .xls> <реестр .html> */
const fs = require('fs'), path = require('path');
const TM = require('../gas/merge.js'), KI = require('../gas/kr_import.js');
TM.setLib(require('xlsx'));
const [xls, html] = process.argv.slice(2);
if (!html) { console.error('Нужны два файла: перечень и реестр подтоплений'); process.exit(2); }
const py = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'capital', 'kr.json'), 'utf8'));
const b = fs.readFileSync(xls), buf = b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength);
const r = KI.build({ tm: TM, list: buf, flood: fs.readFileSync(html, 'utf8'), existing: null, today: py.today, saved: py.saved });
let bad = 0;
const diff = (a, b, p) => {
  if (a === b) return;
  if (typeof a === 'number' && typeof b === 'number' && Math.abs(a - b) < 1e-9) return;
  if (/\.fill$/.test(p) && (a || 'FFFFFF') === (b || 'FFFFFF')) return;   // «нет заливки» и «белая» — одно и то же
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const keys = new Set(Object.keys(a).concat(Object.keys(b)));
    keys.forEach(k => diff(a[k], b[k], p + '.' + k));
    return;
  }
  bad++; if (bad <= 15) console.log('РАЗНИЦА', p, 'JS:', JSON.stringify(a), 'Python:', JSON.stringify(b));
};
diff(r.data.positions, py.positions, 'positions');
diff(r.data.total, py.total, 'total');
diff(r.data.flood, py.flood, 'flood');
console.log('позиций: JS', r.data.positions.length, ', Python', py.positions.length, '| домов с подтоплениями:', r.info.floodHouses, '| предупреждения:', r.warnings, '| расхождений:', bad);
process.exit(bad ? 1 : 0);
