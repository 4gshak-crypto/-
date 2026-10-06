"""Собирает index.html: подставляет data.json в template.html."""
import json, pathlib
here = pathlib.Path(__file__).parent
data = json.loads((here / "data.json").read_text(encoding="utf-8"))
blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
tpl = (here / "template.html").read_text(encoding="utf-8")
(here / "index.html").write_text(tpl.replace("/*DATA*/", blob), encoding="utf-8")
print("index.html:", len(tpl) + len(blob), "bytes")
