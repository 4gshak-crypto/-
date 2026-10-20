"""Реестр домов из input/дома_для_импорта.csv (UTF-8 с BOM, разделитель «;»).

Здесь только чтение и проверка файла. Запись в Битрикс24 (import-houses) появится после
подтверждения сопоставления полей (config/fields_map.yaml).
"""
from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .discover import CSV_COLUMNS
from .matching import HouseRef

log = logging.getLogger(__name__)

KEY_COLUMN = 'GUID дома (ГИС)'
FALLBACK_KEY_COLUMN = 'Короткий адрес'
ADDRESS_COLUMNS = ('Короткий адрес', 'Адрес ОЖФ')


@dataclass
class HousesFile:
    path: Path
    rows: list[dict[str, str]]
    missing_columns: list[str] = field(default_factory=list)
    extra_columns: list[str] = field(default_factory=list)


def read_houses_csv(path: Path) -> HousesFile:
    with path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f, delimiter=';')
        header = [h.strip() for h in (reader.fieldnames or [])]
        rows = [{(k or '').strip(): (v or '').strip() for k, v in row.items()} for row in reader]
    hf = HousesFile(path, rows,
                    missing_columns=[c for c in CSV_COLUMNS if c not in header],
                    extra_columns=[c for c in header if c and c not in CSV_COLUMNS])
    log.info('дома: %s — строк %d, нет колонок %d', path.name, len(rows), len(hf.missing_columns))
    return hf


def house_key(row: dict[str, str]) -> str:
    """Ключ дома: GUID ГИС, а если его нет — короткий адрес (с пометкой, чтобы не спутать с GUID)."""
    guid = row.get(KEY_COLUMN, '').strip().lower()
    return guid or 'адрес:' + row.get(FALLBACK_KEY_COLUMN, '').strip()


def house_refs(hf: HousesFile) -> list[HouseRef]:
    return [HouseRef(id=house_key(r), title=r.get('Название', '') or r.get('Короткий адрес', ''),
                     addresses=tuple(r.get(c, '') for c in ADDRESS_COLUMNS if r.get(c)))
            for r in hf.rows]
