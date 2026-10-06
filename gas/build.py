"""Собирает Seed.gs (план для первичной загрузки в таблицу) и demo.html (локальная демо-версия) из ../tracker/data.json."""
import json, pathlib
here = pathlib.Path(__file__).parent
D = json.loads((here.parent / "tracker" / "data.json").read_text(encoding="utf-8"))
ST = {"blocked": "Нужно решение", "unclear": "Требует уточнения", "nostatus": "Нет статуса", "capital": "Вопрос капремонта",
      "vote": "Голосование ОСС", "todo": "Не начато", "assigned": "Передано исполнителю", "watch": "На контроле",
      "material": "Материал заказан", "work": "В работе", "winter": "Отложено на зиму", "done": "Выполнено, акта нет", "cancel": "Снято"}


def status_of(it):
    # в годовом плане зелёная заливка — выполнено и принято с актом, жёлтая — выполнено без акта
    if it["status"] == "done" and "зелён" in (it.get("st_why") or ""):
        return "Принято, акт есть"
    return ST.get(it["status"], "Нет статуса")
items = []
for g in D["groups"]:
    kr = "; ".join(g["kr"]["works"]) if g.get("kr") else ""
    for it in g["items"]:
        src = " · ".join(x for x in (it.get("fact_txt"), it.get("upd")) if x)
        items.append({"key": "r%d" % it["row"], "row": it["row"], "month": it["month"], "addr": it["addr"], "uk": it.get("uk", ""),
                      "work": it["work"].strip(), "cat": it.get("cat", ""), "basis": it.get("basis", ""), "sum": it.get("sum"),
                      "fsum": it.get("fsum"), "ex": it["ex"], "status": status_of(it), "src_note": src, "kr": kr})
items.sort(key=lambda x: x["row"])
seed = {"generated": D["generated"], "items": items,
        "issues": [{"text": i["text"], "resp": i["resp"], "term": i["term"], "ref": i.get("ref", "")} for i in D["issues"]]}
blob = json.dumps(seed, ensure_ascii=False, separators=(",", ":"))
(here / "Seed.gs").write_text("/** План текущего ремонта на 06.10.2026 — загружается в таблицу функцией setup(). Сгенерировано build.py. */\nvar SEED = " + blob + ";\n", encoding="utf-8")
demo_items = [dict(i, src=i.pop("src_note")) for i in json.loads(blob)["items"]]
demo = dict(seed, items=demo_items)
html = (here / "Index.html").read_text(encoding="utf-8")
inject = "<script>window.DEMO_SEED=" + json.dumps(demo, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + ";</script>\n"
(here / "demo.html").write_text(html.replace("<script>\n(function(){", inject + "<script>\n(function(){", 1), encoding="utf-8")
print(len(items), "работ,", len(seed["issues"]), "вопросов")
