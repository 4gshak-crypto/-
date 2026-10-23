"""Собирает Seed.gs (данные для первичной загрузки в таблицу) и demo.html (локальная демо-версия).

Данные берутся из сведения трёх выгрузок:
  python3 tools/merge_sources.py <годовой план .xls> <файл исполнителей .xlsx> <выгрузка Битрикс24 .xlsx>
  python3 tools/questions.py
  python3 gas/build.py
"""
import json, pathlib
here = pathlib.Path(__file__).parent

# --- модуль сведения Excel (merge.js) вставляется в Index.html между метками merge:start и merge:end
_idx = (here / "Index.html").read_text(encoding="utf-8")
_a, _b = _idx.index("/* merge:start */") + len("/* merge:start */"), _idx.index("/* merge:end */")
_mj = (here / "merge.js").read_text(encoding="utf-8")
assert "</script" not in _mj
_new = _idx[:_a] + "\n" + _mj.strip() + "\n" + _idx[_b:]
if _new != _idx:
    (here / "Index.html").write_text(_new, encoding="utf-8")
    print("Index.html: merge.js обновлён")
T = here.parent / "tracker"
M = json.loads((T / "merged.json").read_text(encoding="utf-8"))
Q = json.loads((T / "questions.json").read_text(encoding="utf-8"))

items = []
for i in M["items"]:
    items.append(dict(key=i["key"], row=i["row"], month=i["month"], addr=i["addr"], uk=i["uk"], work=i["work"], cat=i["cat"],
                      basis=i["basis"], sum=i["sum"], fsum=i["fsum"], ex=i["ex"], status=i["status"], src_note=i["src_note"], kr=i["kr"],
                      act=i["act"], master=i["master"], bx_stage=i["bx_stage"], bx_dates=i["bx_dates"], check=i["check"]))
items.sort(key=lambda x: (x["month"], x["row"] or 9999, x["addr"]))

issues = [{"text": q["text"] + (" Перечень: %d поз." % q["count"] if q["count"] else ""), "resp": q["to"], "term": q["term"],
           "ref": "вопрос %d в файле «Вопросы для трекера»" % q["n"]} for q in Q["questions"]]

seed = {"generated": M["generated"], "sources": M["sources"], "items": items, "issues": issues}
blob = json.dumps(seed, ensure_ascii=False, separators=(",", ":"))
(here / "Seed.gs").write_text("/** Сводные данные трекера: годовой план 16.10, файл исполнителей 08.10 (+ пополнения 16.10), Битрикс24 19.10. "
                              "Загружаются в таблицу функцией setup(). Сгенерировано build.py. */\nvar SEED = " + blob + ";\n", encoding="utf-8")

demo_items = []
for i in json.loads(blob)["items"]:
    d = dict(i, src=i.pop("src_note"), bxStage=i.pop("bx_stage"), bxDates=i.pop("bx_dates"))
    demo_items.append(d)
demo = dict(seed, items=demo_items)
import re
strip_merge = lambda t: re.sub(r"<script>\n/\* merge:start \*/.*?/\* merge:end \*/\n</script>\n", "", t, flags=re.S)   # в демо загрузка обновлений скрыта
html = strip_merge((here / "Index.html").read_text(encoding="utf-8")).replace("<?!= BOOT ?>", "null")
inject = "<script>window.DEMO_SEED=" + json.dumps(demo, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + ";</script>\n"
(here / "demo.html").write_text(html.replace("<script>\n(function(){", inject + "<script>\n(function(){", 1), encoding="utf-8")
print(len(items), "работ,", len(issues), "вопросов")

# --- файл для кнопки «Загрузить обновление» в трекере: те же работы, что в Seed.gs, но для уже работающей таблицы
d = M["generated"].split("-")
imp = here.parent / "reports" / ("Обновление для трекера %s.%s.%s.json" % (d[2], d[1], d[0]))
imp.parent.mkdir(exist_ok=True)
imp.write_text(json.dumps(dict(format="tracker-import-1", generated=M["generated"], sources=M["sources"], items=items), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(imp.name + ":", round(imp.stat().st_size / 1024), "КБ,", len(items), "работ")

# --- страница для показа (claude.ai): без входа по PIN, телефоны жильцов скрыты, тема по правилам площадки
mask = lambda t: re.sub(r'\(?\s*(?:\+7|8)[\s-]?\(?\d{3}\)?[\s-]?\d{3}[\s-]?\d{2}[\s-]?\d{2}\s*\)?', '(тел. скрыт)', t) if isinstance(t, str) else t
show_items = [{k: mask(v) for k, v in i.items()} for i in demo_items]
show = dict(demo, items=show_items)
page = strip_merge((here / "Index.html").read_text(encoding="utf-8")).replace("<?!= BOOT ?>", "null")
head_end = page.index("</head>")
style = page[page.index("<style>"):page.index("</style>") + 8]
dark = re.search(r"@media \(prefers-color-scheme:dark\)\{:root\{(.*?)\}\}", style, re.S)
style = style.replace(dark.group(0), '@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){' + dark.group(1) + '}}\n:root[data-theme="dark"]{' + dark.group(1) + '}')
fonts = re.search(r'<link rel="stylesheet"[^>]+>', page).group(0)
bodyhtml = page[page.index("<body>") + 6:page.index("</body>")]
inject_show = "<script>window.DEMO_SEED=" + json.dumps(show, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + ";</script>\n"
bodyhtml = bodyhtml.replace("<script>\n(function(){", inject_show + "<script>\n(function(){", 1)
(here / "meeting.html").write_text("<title>Трекер текущего ремонта</title>\n" + fonts + "\n" + style + "\n" + bodyhtml, encoding="utf-8")
print("meeting.html:", round((here / "meeting.html").stat().st_size / 1024), "КБ; телефонов скрыто:",
      sum(json.dumps(i, ensure_ascii=False).count("тел. скрыт") for i in show_items))

# --- та же страница отдельным файлом для скачивания: открывается в браузере без интернета (кроме шрифтов)
dl = here.parent / "reports" / ("Трекер текущего ремонта %s.%s.%s.html" % (d[2], d[1], d[0]))
dl.write_text('<!DOCTYPE html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n'
              "<title>Трекер текущего ремонта</title>\n" + fonts + "\n" + style + "\n</head>\n<body>\n" + bodyhtml + "\n</body>\n</html>\n", encoding="utf-8")
print(dl.name + ":", round(dl.stat().st_size / 1024), "КБ")
