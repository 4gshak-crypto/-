"""Адреса в тестах вымышленные или типовые (Ленина, Мира), не из реестра УК."""
import pytest

from bitrix_uk.matching import AddressError, HouseIndex, HouseRef, parse_address


@pytest.mark.parametrize('variants', [
    ['ул. Ленина, д. 10', 'Ленина ул, 10', 'улица Ленина, дом 10', 'ул Ленина 10', 'УЛ. ЛЕНИНА, 10',
     'Ульяновская обл., г. Ульяновск, ул. Ленина, д. 10', '432000, г Ульяновск, ул. Ленина, 10, кв. 5'],
    ['пр-кт Мира, 5', 'Мира пр-т, 5', 'проспект Мира, 5', 'просп. Мира, д.5'],
    ['ш Садовое шоссе, 7', 'Садовое ш., 7', 'шоссе Садовое, 7'],
    ['б-р. Солнечный, д. 1', 'бульвар Солнечный, 1', 'Солнечный б-р, 1'],
    ['ул. Зелёная, 3', 'ул Зеленая, 3', 'Зелёная улица, 3'],
    ['пр-кт 40-летия Победы, 2', '40-летия Победы пр-т, 2', 'пр-кт 40 лет Победы, 2'],
    ['ул. Тихая, 5А', 'ул. Тихая, 5 А', 'ул. Тихая, 5а', 'Тихая ул, д. 5-а'],
    ['ул. Речная, 3 корп. 1', 'ул. Речная, 3 к.1', 'ул. Речная, 3 корпус 1', 'ул. Речная, 3к1'],
    ['ул. Ясная, 9/2 лит. А', 'Ясная ул, 9/2 литера А', 'ул Ясная, 9/2 лит А'],
    ['ул. Анны Ивановой, 6', 'ул Ивановой Анны, 6'],
    ['пер. Короткий, 2 стр. 1', 'Короткий пер, 2 строение 1'],
])
def test_same_address(variants):
    keys = {parse_address(v).key for v in variants}
    assert len(keys) == 1, keys


@pytest.mark.parametrize('a,b', [
    ('ул. Ленина, 10', 'ул. Ленина, 10А'),
    ('ул. Ленина, 10', 'ул. Ленина, 10/1'),
    ('ул. Речная, 3', 'ул. Речная, 3 корп. 1'),
    ('ул. Ясная, 6', 'ул. Ясная, 6 лит. А'),
    ('ул. Ленина, 11/47', 'ул. Ленина, 11/48'),
])
def test_different_addresses(a, b):
    assert parse_address(a).key != parse_address(b).key


def test_parts():
    a = parse_address('Ульяновская обл., г. Ульяновск, б-р. Западный, д. 1')
    assert (a.street, a.street_type, a.house) == ('западный', 'б-р', '1')
    a = parse_address('ул Тихая, 11/47, кв. 33')
    assert (a.house, a.flat) == ('11/47', '33')
    a = parse_address('ш Садовое шоссе, 75 лит. А')
    assert (a.street, a.street_type, a.litera) == ('садовое', 'ш', 'а')
    assert parse_address('ул. Гагарина, 5').street == 'гагарина'      # «г» в начале улицы — не «город»


@pytest.mark.parametrize('raw', ['', 'ул. Ленина', 'г. Ульяновск', '   '])
def test_unparsable(raw):
    with pytest.raises(AddressError):
        parse_address(raw)


HOUSES = [
    HouseRef('g1', 'ул. Ленина, 10', ('Ленина ул, 10',)),
    HouseRef('g2', 'ул. Гагарина, 5'),
    HouseRef('g3', 'пер. Гагарина, 5'),
    HouseRef('g4', 'ул. Ясная, 6'),
    HouseRef('g5', 'ул. Промышленная, 3'),
    HouseRef('g6', 'ул. Речная, 3'),
    HouseRef('g7', 'ул. Речная, 3 корп. 1'),
    HouseRef('g8', 'ул. Тихая, 4'),
]


def test_found_exact():
    idx = HouseIndex(HOUSES)
    for raw in ('Ленина ул, 10', 'ул Ленина, 10, кв. 7', 'ул. Речная, 3 к.1', 'ул. Речная, 3'):
        assert idx.match(raw).found, raw
    assert idx.match('ул. Речная, 3 к.1').house.id == 'g7'
    assert idx.match('ул. Речная, 3').house.id == 'g6'


def test_ambiguous_without_street_type():
    m = HouseIndex(HOUSES).match('Гагарина, 5')
    assert m.status == 'ambiguous' and {c.house.id for c in m.candidates} == {'g2', 'g3'}


def test_street_type_resolves_ambiguity():
    idx = HouseIndex(HOUSES)
    assert idx.match('пер Гагарина, 5').house.id == 'g3'
    assert idx.match('Гагарина ул, д. 5').house.id == 'g2'


def test_other_street_type_needs_review():
    m = HouseIndex(HOUSES).match('пер. Тихая, 4')                  # в реестре «ул. Тихая, 4»
    assert m.status == 'needs_review' and m.candidates[0].reason == 'другой тип улицы'


def test_litera_needs_review_not_silent():
    m = HouseIndex(HOUSES).match('ул Ясная, 6 лит. А')
    assert m.status == 'needs_review'
    assert m.candidates[0].house.id == 'g4' and m.candidates[0].reason == 'отличается литерой'


def test_typo_in_street_needs_review():
    m = HouseIndex(HOUSES).match('Промышленая ул, 3')
    assert m.status == 'needs_review' and m.candidates[0].house.id == 'g5'
    assert 'похожая улица' in m.candidates[0].reason


def test_not_found():
    idx = HouseIndex(HOUSES)
    assert idx.match('ул. Ленина, 12').status == 'not_found'
    assert idx.match('мусор без номера').status == 'not_found'


def test_alias_confirmed_by_human():
    idx = HouseIndex(HOUSES, aliases={'ул Ясная, 6 лит. А': 'g4'})
    m = idx.match('ул  Ясная, 6 лит. А')
    assert m.found and m.house.id == 'g4' and m.reason == 'подтверждено вручную'
    assert HouseIndex(HOUSES, aliases={'ул Ясная, 6 лит. А': 'нет-такого'}).match('ул Ясная, 6 лит. А').status == 'not_found'


def test_registry_errors_are_reported():
    idx = HouseIndex([HouseRef('x', 'без номера дома')])
    assert idx.errors and idx.errors[0][0].id == 'x'
