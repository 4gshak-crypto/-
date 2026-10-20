"""Нормализация адресов и поиск дома в реестре.

Правило: программа не выбирает дом молча, если есть сомнения. Результат поиска — одно из:
  found        — найден ровно один дом;
  ambiguous    — подходят несколько домов (например, ул. и пер. с одним названием);
  needs_review — точного совпадения нет, но есть похожий дом (отличается литерой, опечатка в улице);
  not_found    — ничего похожего.
Решения человека по спорным адресам хранятся в config/address_aliases.yaml и больше не спрашиваются.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

# Типы улиц: вариант написания → каноническое сокращение
STREET_TYPES = {
    'ул': 'ул', 'улица': 'ул',
    'пр-кт': 'пр-кт', 'пр-т': 'пр-кт', 'просп': 'пр-кт', 'проспект': 'пр-кт',
    'пер': 'пер', 'переулок': 'пер',
    'ш': 'ш', 'шоссе': 'ш',
    'б-р': 'б-р', 'бульв': 'б-р', 'бул': 'б-р', 'бульвар': 'б-р',
    'пр-д': 'проезд', 'проезд': 'проезд',
    'пл': 'пл', 'площадь': 'пл',
    'наб': 'наб', 'набережная': 'наб',
    'туп': 'туп', 'тупик': 'туп',
    'мкр': 'мкр', 'микрорайон': 'мкр',
    'кв-л': 'кв-л', 'квартал': 'кв-л',
    'аллея': 'аллея', 'тракт': 'тракт',
    'пр': 'пр',  # «пр.» — проспект или проезд, не угадываем
}
# Части адреса до улицы, которые отбрасываем
PREFIX_RE = re.compile(
    r'^(россия|рф|\d{6}|[\w\- ]+\s(обл|область|край|респ|республика)\.?|(г|город)(\.|\s)\s*[\w\- ]+|'
    r'[\w\- ]+\s(р-н|район))$')
FLAT_RE = re.compile(r'\b(кв|квартира|пом|помещение|ком|комната|оф|офис)\.?\s*№?\s*(\d+[а-я]?)\b.*$')
HOUSE_RE = re.compile(r'^(?:д|дом)?\.?\s*(\d+)\s*([а-я](?![а-я]))?\s*(?:/\s*(\d+)\s*([а-я](?![а-я]))?)?\s*(.*)$')
CORPUS_RE = re.compile(r'\b(?:корпус|корп|к)\.?\s*(\d+[а-я]?)\b')
LITERA_RE = re.compile(r'\b(?:литера|литер|лит)\b\.?\s*([а-я])\b')
BUILDING_RE = re.compile(r'\b(?:строение|стр)\.?\s*(\d+[а-я]?)\b')
FUZZY_STREET = 0.85


@dataclass(frozen=True)
class Address:
    raw: str
    street: str              # название улицы без типа, слова по алфавиту: «громовой ульяны»
    street_type: str | None  # «ул», «пр-кт»… или None, если не указан
    house: str               # «11», «5а», «11/47»
    corpus: str = ''
    litera: str = ''
    building: str = ''
    flat: str = ''

    @property
    def key(self) -> str:
        """Ключ для точного сравнения: улица + дом + корпус + литера + строение (без типа улицы и квартиры)."""
        return f'{self.street}|{self.house}|{self.corpus}|{self.litera}|{self.building}'

    @property
    def key_no_litera(self) -> str:
        return f'{self.street}|{self.house}|{self.corpus}||{self.building}'

    def short(self) -> str:
        parts = [self.street_type or '', self.street, self.house]
        for label, v in (('корп.', self.corpus), ('лит.', self.litera), ('стр.', self.building)):
            if v:
                parts.append(f'{label} {v}')
        return ' '.join(p for p in parts if p)


class AddressError(ValueError):
    """Адрес не удалось разобрать: нет улицы или номера дома."""


def _clean(text: str) -> str:
    t = str(text or '').lower().replace('ё', 'е').replace('\xa0', ' ')
    t = re.sub(r'[«»"]', '', t)
    return re.sub(r'\s+', ' ', t).strip(' ,.')


def _street_name(segment: str) -> tuple[str, str | None]:
    """Отделяет тип улицы (в начале или в конце) и нормализует название."""
    words = re.sub(r'[,()]', ' ', segment).split()
    kind = None
    rest = []
    for w in words:
        bare = w.rstrip('.')
        if bare in STREET_TYPES and (kind is None or STREET_TYPES[bare] == kind):
            kind = STREET_TYPES[bare]
            continue
        rest.append(bare)
    name = ' '.join(rest)
    name = re.sub(r'\b(им|имени)\.?\s+', '', name)
    name = re.sub(r'(\d+)\s*-?\s*(летия|лет)\b', r'\1 летия', name)  # «50 лет ВЛКСМ» = «50-летия ВЛКСМ»
    name = name.replace('-', ' ')
    name = re.sub(r'[^\w ]', '', name)
    return ' '.join(sorted(name.split())), kind


def parse_address(raw: str) -> Address:
    text = _clean(raw)
    if not text:
        raise AddressError('пустой адрес')
    flat = ''
    m = FLAT_RE.search(text)
    if m:
        flat = m.group(2)
        text = text[:m.start()].strip(' ,')
    segments = [s.strip() for s in text.split(',') if s.strip()]
    segments = [s for s in segments if not PREFIX_RE.match(s)]
    # сегмент с домом: первый, начинающийся с «д.» или с цифры, после которого нет названия улицы
    house_idx = None
    for i, seg in enumerate(segments):
        if i > 0 and re.match(r'^(д|дом)?\.?\s*\d', seg):
            house_idx = i
            break
    if house_idx is None:
        # «ул. Ленина д. 10» или «Ленина 10» без запятой
        joined = ' '.join(segments)
        m = re.match(r'^(.*?\D)\s+(?:(?:д|дом)\.?\s*)?(\d.*)$', joined)
        if not m:
            raise AddressError(f'не найден номер дома: «{raw}»')
        street_part, house_part = m.group(1), m.group(2)
    else:
        street_part = ' '.join(segments[:house_idx])
        house_part = ' '.join(segments[house_idx:])
    street, kind = _street_name(street_part)
    if not street:
        raise AddressError(f'не найдена улица: «{raw}»')

    house_part = re.sub(r'(\d)к(\d)', r'\1 к\2', house_part.replace('-', ' '))  # «5к2» = «5 корп. 2»
    corpus = (CORPUS_RE.search(house_part) or [None, ''])[1]
    litera = (LITERA_RE.search(house_part) or [None, ''])[1]
    building = (BUILDING_RE.search(house_part) or [None, ''])[1]
    rest = BUILDING_RE.sub(' ', LITERA_RE.sub(' ', CORPUS_RE.sub(' ', house_part)))
    hm = HOUSE_RE.match(rest.strip())
    if not hm:
        raise AddressError(f'не найден номер дома: «{raw}»')
    house = hm.group(1) + (hm.group(2) or '')
    if hm.group(3):
        house += '/' + hm.group(3) + (hm.group(4) or '')
    return Address(raw=str(raw), street=street, street_type=kind, house=house, corpus=corpus,
                   litera=litera, building=building, flat=flat)


# --- реестр домов ---

@dataclass(frozen=True)
class HouseRef:
    id: str                       # ключ дома: GUID ГИС или ID элемента в Битриксе
    title: str
    addresses: tuple[str, ...] = ()


@dataclass
class Candidate:
    house: HouseRef
    reason: str


@dataclass
class MatchResult:
    status: str                   # found | ambiguous | needs_review | not_found
    raw: str
    house: HouseRef | None = None
    candidates: list[Candidate] = field(default_factory=list)
    reason: str = ''

    @property
    def found(self) -> bool:
        return self.status == 'found'


def _same_type(a: str, b: str) -> bool:
    """«пр.» может быть и проспектом, и проездом."""
    return a == b or 'пр' in (a, b) and {a, b} <= {'пр', 'пр-кт', 'проезд'}


def alias_key(raw: str) -> str:
    return _clean(raw)


class HouseIndex:
    def __init__(self, houses: Iterable[HouseRef], aliases: dict[str, str] | None = None):
        self.houses: dict[str, HouseRef] = {}
        self._exact: dict[str, dict[str, set[str | None]]] = {}   # key → {house_id: {типы улиц}}
        self._no_litera: dict[str, set[str]] = {}
        self._by_house_no: dict[str, set[str]] = {}               # номер дома → улицы (для поиска опечаток)
        self.errors: list[tuple[HouseRef, str, str]] = []         # адреса реестра, которые не разобрались
        for h in houses:
            self.houses[h.id] = h
            for raw in {h.title, *h.addresses}:
                if not raw:
                    continue
                try:
                    a = parse_address(raw)
                except AddressError as e:
                    self.errors.append((h, raw, str(e)))
                    continue
                self._exact.setdefault(a.key, {}).setdefault(h.id, set()).add(a.street_type)
                self._no_litera.setdefault(a.key_no_litera, set()).add(h.id)
                self._by_house_no.setdefault(a.house, set()).add(a.street)
        self.aliases = {alias_key(k): v for k, v in (aliases or {}).items()}

    def match(self, raw: str) -> MatchResult:
        ak = alias_key(raw)
        if ak in self.aliases:
            hid = self.aliases[ak]
            if hid in self.houses:
                return MatchResult('found', raw, self.houses[hid], reason='подтверждено вручную')
            return MatchResult('not_found', raw, reason=f'в address_aliases.yaml указан неизвестный дом {hid}')
        try:
            a = parse_address(raw)
        except AddressError as e:
            return MatchResult('not_found', raw, reason=str(e))

        exact = self._exact.get(a.key, {})
        if len(exact) == 1:
            hid, kinds = next(iter(exact.items()))
            known = {k for k in kinds if k}
            if a.street_type and known and not any(_same_type(a.street_type, k) for k in known):
                # в реестре «ул. Гагарина, 5», а в источнике «пер. Гагарина, 5» — может быть другая улица
                return MatchResult('needs_review', raw, candidates=[Candidate(self.houses[hid], 'другой тип улицы')],
                                   reason='точного совпадения нет')
            return MatchResult('found', raw, self.houses[hid])
        if len(exact) > 1:
            if a.street_type:
                same_type = [hid for hid, kinds in exact.items() if any(_same_type(a.street_type, k) for k in kinds if k)]
                if len(same_type) == 1:
                    return MatchResult('found', raw, self.houses[same_type[0]])
            return MatchResult('ambiguous', raw, candidates=[
                Candidate(self.houses[hid], 'тот же адрес, другой тип улицы' if a.street_type else 'не указан тип улицы')
                for hid in sorted(exact)], reason='подходят несколько домов')

        cands: list[Candidate] = []
        for hid in sorted(self._no_litera.get(a.key_no_litera, ())):
            cands.append(Candidate(self.houses[hid], 'отличается литерой'))
        if not cands:
            streets = self._by_house_no.get(a.house, set())
            for st in difflib.get_close_matches(a.street, list(streets), n=3, cutoff=FUZZY_STREET):
                key = f'{st}|{a.house}|{a.corpus}|{a.litera}|{a.building}'
                for hid in sorted(self._exact.get(key, {})):
                    cands.append(Candidate(self.houses[hid], f'похожая улица: «{st}»'))
        if cands:
            return MatchResult('needs_review', raw, candidates=cands, reason='точного совпадения нет')
        return MatchResult('not_found', raw, reason='дом не найден в реестре')


def load_aliases(path: Path) -> dict[str, str]:
    """config/address_aliases.yaml: «адрес как в источнике»: «ключ дома»."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
    return {str(k): str(v) for k, v in (data.get('aliases') or {}).items()}
