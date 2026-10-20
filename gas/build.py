"""Собирает Seed.gs (данные для первичной загрузки в таблицу) и demo.html (локальная демо-версия).

Данные берутся из сведения трёх выгрузок:
  python3 tools/merge_sources.py <годовой план .xls> <файл исполнителей .xlsx> <выгрузка Битрикс24 .xlsx>
  python3 tools/questions.py
  python3 gas/build.py
"""
import json, pathlib
here = pathlib.Path(__file__).parent
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
html = (here / "Index.html").read_text(encoding="utf-8").replace("<?!= BOOT ?>", "null")
inject = "<script>window.DEMO_SEED=" + json.dumps(demo, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + ";</script>\n"
(here / "demo.html").write_text(html.replace("<script>\n(function(){", inject + "<script>\n(function(){", 1), encoding="utf-8")
print(len(items), "работ,", len(issues), "вопросов")
