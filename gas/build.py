"""Собирает Seed.gs (план для первичной загрузки в таблицу) и demo.html (локальная демо-версия) из ../tracker/data.json."""
import json, pathlib
here = pathlib.Path(__file__).parent
D = json.loads((here.parent / "tracker" / "data.json").read_text(encoding="utf-8"))
ST = {"blocked": "Нужно решение", "unclear": "Требует уточнения", "nostatus": "Нет статуса", "capital": "Вопрос капремонта",
      "vote": "Голосование ОСС", "todo": "Не начато", "assigned": "Передано исполнителю", "watch": "На контроле",
      "material": "Материал заказан", "work": "В работе", "winter": "Отложено на зиму", "done": "Выполнено, акта нет", "cancel": "Снято"}


def status_of(it):
    # в годовом плане зелёная заливка — выполнено и принято с актом, жёлтая — выполнено без акта.
    # «Акта нет» в строке важнее цвета (стр. 213: в снимке была ошибочно отнесена к зелёным)
    if it["status"] == "done" and "зелён" in (it.get("st_why") or "") and "акта нет" not in (it.get("fact_txt") or "").lower():
        return "Принято, акт есть"
    return ST.get(it["status"], "Нет статуса")


# явные ошибки автоматической классификации видов работ (по номеру строки файла)
CAT_FIX = {208: "Санитарное содержание", 374: "Инженерные сети"}


def src_note(it):
    parts = [x for x in (it.get("fact_txt"), it.get("upd")) if x]
    if it["status"] == "done" and "прежней отметке" in (it.get("st_why") or ""):
        parts.append("ПРОВЕРИТЬ: «выполнено» по отметке 23.09, в файле 06.10 строка не жёлтая и не зелёная")
    return " · ".join(parts)
items = []
for g in D["groups"]:
    kr = "; ".join(g["kr"]["works"]) if g.get("kr") else ""
    for it in g["items"]:
        src = src_note(it)
        items.append({"key": "r%d" % it["row"], "row": it["row"], "month": it["month"], "addr": it["addr"], "uk": it.get("uk", ""),
                      "work": it["work"].strip(), "cat": CAT_FIX.get(it["row"], it.get("cat", "")), "basis": it.get("basis", ""), "sum": it.get("sum"),
                      "fsum": it.get("fsum"), "ex": it["ex"], "status": status_of(it), "src_note": src, "kr": kr})
# работы февраля–августа, выполненные без акта: долг по актам (tools/extract_backlog.py)
for b in json.loads((here.parent / "tracker" / "backlog.json").read_text(encoding="utf-8")):
    items.append(dict(key="r%d" % b["row"], row=b["row"], month=b["month"], addr=b["addr"], uk=b["uk"], work=b["work"], cat=b["cat"],
                      basis=b["basis"], sum=b["sum"], fsum=b["fsum"], ex="Не распределено", status="Выполнено, акта нет",
                      src_note=b["src_note"], kr=""))
items.sort(key=lambda x: x["row"])
EXTRA_ISSUES = [  # найдено при сверке трекера с файлом 06.10
    {"text": "37 работ сентября–октября числятся «выполненными» только по отметке от 23.09: в годовом плане от 06.10 они не залиты ни жёлтым, ни зелёным. Подтвердить выполнение или вернуть статус. В трекере они помечены «ПРОВЕРИТЬ» в поле «Из файла».",
     "resp": "ПТО", "term": "до 14.10", "ref": "поиск по слову «ПРОВЕРИТЬ»"},
    {"text": "54 работы февраля–августа выполнены, но акта нет (жёлтые строки), самые старые — с февраля. Без акта их нельзя закрыть и оплатить. Добавлены в трекер со статусом «Выполнено, акта нет» и исполнителем «Не распределено».",
     "resp": "ПТО / бухгалтерия", "term": "до 31.10", "ref": "месяцы февраль–август"},
    {"text": "Название УК в годовом плане написано с ошибками: «ООО \"УК В» (стр. 52, Терешковой 14), «ООО \"УК МИДЕ\"» (стр. 136, Воробьёва 38/2), «ТСЖ «Зведа»». Уточнить и исправить в файле.",
     "resp": "ПТО", "term": "при следующем обновлении", "ref": "стр. 52, 136"},
    {"text": "Пушкарева 8А, ремонт лестничного марша (стр. 29, апрель): строка залита нестандартным цветом и без отметки о выполнении. Уточнить, выполнена ли работа.",
     "resp": "ПТО", "term": "до 14.10", "ref": "стр. 29"},
]
seed = {"generated": D["generated"], "items": items,
        "issues": [{"text": i["text"], "resp": i["resp"], "term": i["term"], "ref": i.get("ref", "")} for i in D["issues"]] + EXTRA_ISSUES}
blob = json.dumps(seed, ensure_ascii=False, separators=(",", ":"))
(here / "Seed.gs").write_text("/** План текущего ремонта на 06.10.2026 — загружается в таблицу функцией setup(). Сгенерировано build.py. */\nvar SEED = " + blob + ";\n", encoding="utf-8")
demo_items = [dict(i, src=i.pop("src_note")) for i in json.loads(blob)["items"]]
demo = dict(seed, items=demo_items)
html = (here / "Index.html").read_text(encoding="utf-8").replace("<?!= BOOT ?>", "null")
inject = "<script>window.DEMO_SEED=" + json.dumps(demo, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/") + ";</script>\n"
(here / "demo.html").write_text(html.replace("<script>\n(function(){", inject + "<script>\n(function(){", 1), encoding="utf-8")
print(len(items), "работ,", len(seed["issues"]), "вопросов")
