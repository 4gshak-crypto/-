import datetime as dt
from dataclasses import asdict

import pytest

from asu_fixture import APPLICANT, HEADER, make_journal, row
from bitrix_uk.asu import (AsuFormatError, classify, find_repeats, load_rules, mask_pd, parse_comment,
                           read_journal, read_journals)

RULES = load_rules()


@pytest.fixture
def journal(tmp_path):
    return read_journal(make_journal(tmp_path / 'ADocumentJournal_appealss-07-03-2026.xlsx'))


def by_no(j):
    return {r.number: r for r in j.requests}


def test_reads_header_and_period(journal):
    assert len(journal.requests) == 9
    assert journal.period == (dt.datetime(2026, 3, 1, 0, 1), dt.datetime(2026, 3, 7, 17, 19))
    assert any('abc' in w for w in journal.warnings)          # битая строка не потеряна молча


def test_no_personal_data(journal):
    dump = str([asdict(r) for r in journal.requests])
    assert APPLICANT not in dump                               # «Заявитель» не читается
    assert '000-11-22' not in dump and '123456' not in dump    # телефоны в тексте и комментарии
    assert '[телефон]' in by_no(journal)[1001].content


def test_status_and_comment(journal):
    r = by_no(journal)
    assert r[1002].status == 'Третья сторона'
    assert r[1001].basis_task == 5001
    assert r[1001].comments[0].at == dt.datetime(2026, 3, 1, 10, 2)
    assert r[1005].comments == []
    assert r[1004].not_done_by_resident and not r[1001].not_done_by_resident
    assert r[1001].reaction == '5' and r[1001].room == '5'


def test_handed_at_from_comment_or_created(journal):
    r = by_no(journal)
    c = classify(r[1002], RULES)
    assert (c.handed_at, c.handed_at_source) == (dt.datetime(2026, 3, 1, 12, 5), 'комментарий')
    c = classify(r[1005], RULES)
    assert (c.handed_at, c.handed_at_source) == (dt.datetime(2026, 3, 3, 8, 0), 'время создания')


def test_third_party_recipient(journal):
    r = by_no(journal)
    assert classify(r[1002], RULES).recipient == 'Водоканал'
    assert classify(r[1003], RULES).recipient == 'Домофонная организация'   # по типу, если в комментарии нет
    assert not classify(r[1001], RULES).third_party


def test_critical(journal):
    r = by_no(journal)
    assert classify(r[1001], RULES).critical_reasons == ['затопление']
    assert 'колодцы и КНС' in classify(r[1002], RULES).critical_reasons
    assert classify(r[1008], RULES).critical_reasons == ['лифт']
    assert not classify(r[1007], RULES).critical               # свет возле лифта — не авария
    assert not classify(r[1009], RULES).critical               # отопление в одной квартире — не авария
    assert not classify(r[1004], RULES).critical


def test_systems(journal):
    r = by_no(journal)
    assert classify(r[1004], RULES).system == 'ГВС'            # «Сантехника» → по тексту
    assert classify(r[1005], RULES).system == 'ГВС'            # по типу
    assert classify(r[1008], RULES).system == 'Лифты'


def test_repeats(journal):
    items = [(r, classify(r, RULES), r.house.lower()) for r in journal.requests]
    reps = find_repeats(items, RULES)
    assert len(reps) == 1 and reps[0].system == 'ГВС' and sorted(reps[0].numbers) == [1004, 1005, 1006]


def test_missing_columns(tmp_path):
    header = [h for h in HEADER if h != 'Комментарий']
    with pytest.raises(AsuFormatError, match='Комментарий'):
        read_journal(make_journal(tmp_path / 'x.xlsx', rows=[], header=header))
    with pytest.raises(AsuFormatError, match='заголовков'):
        read_journal(make_journal(tmp_path / 'y.xlsx', rows=[], header=['что-то другое']))


def test_latest_file_wins(tmp_path):
    d = dt.datetime(2026, 3, 1, 10)
    old = make_journal(tmp_path / 'ADocumentJournal_appealss-01-03-2026.xlsx',
                       rows=[row(1, d, 'течь', None, 'ул. Ленина, 10', '', 'В работе')])
    new = make_journal(tmp_path / 'ADocumentJournal_appealss-08-03-2026.xlsx',
                       rows=[row(1, d, 'течь', None, 'ул. Ленина, 10', '', 'Закрыт'),
                             row(2, d, 'течь', None, 'ул. Ленина, 10', '', 'Новый')])
    reqs, journals = read_journals([new, old])
    assert len(journals) == 2 and {r.number: r.status for r in reqs} == {1: 'Закрыт', 2: 'Новый'}


def test_parse_comment_multiple_entries():
    e = parse_comment('Передали в водоканал\n01.03.2026 г., 12:05 Иванова И. И.\nПовторно\n02.03.2026 г., 9:15 Петров П. П.')
    assert [x.at.hour for x in e] == [12, 9] and e[1].text == 'Повторно'


@pytest.mark.parametrize('text,hidden', [
    ('звонить 8 (900) 000-11-22', '000-11-22'), ('тел 89000001122', '89000001122'), ('по тел. 123456', '123456'),
    ('Петров П.П. сказал', 'Петров'), ('И. И. Сидорова', 'Сидорова'), ('Тестова Тамара Тестовна просит', 'Тамара'),
    ('пишите на test.user@example.com', 'example'),
])
def test_mask_pd(text, hidden):
    assert hidden not in mask_pd(text)


def test_mask_keeps_streets_and_numbers():
    t = 'ул Розы Люксембург, 52, Задача № 73274 от 06.10.2026'
    assert mask_pd(t) == t
