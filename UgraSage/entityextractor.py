"""Модуль для извлечения именованных сущностей из фразы пользователя."""

import re
import functools
from threading import Lock

import natasha
from yargy import Parser

# писать правила под обучающую выборку, не пытаться объять необъятное
from grammars.ref import REF
from grammars.cls import CLS
from grammars.day import DAY

from common import Entities

stop_substrs = [
    'вроде',
    'вроде бы',
    'как бы',
    'пусть',
    'пускай',
    'а',
    'но',
    'ну',
    'например',
    'допустим'
]

parsers = {
    'class': (Parser(CLS), Lock()),
    'org': (natasha.OrganisationExtractor(), Lock()),
    'empee': (natasha.NamesExtractor(), Lock()),
    'day': (Parser(DAY), Lock()),
    'ref': (Parser(REF), Lock())
}


def drop_substrs(phrase, substrs=stop_substrs):
    """Функция для удаления неинформативных подстрок."""

    for s in substrs:
        phrase = re.sub(f'\\s*\\b{s}\\b', '', phrase, flags=re.IGNORECASE)

    phrase = re.sub(',{2,}', '', phrase)

    return phrase


def extract_refs(phrase):
    refs = []

    parser, lock = parsers['ref']
    with lock:
        matches = parser.findall(phrase)

    for match in matches:
        refs.append(match.fact)

    return refs


def clar_name_fill(clar, entities):
    if clar['isgp']:
        group_ent = {'name': clar['name']}
        entities.fill('group', group_ent)

        if clar['subgp']:
            subgp_ent = {'name': clar['subgp']}
            entities.fill('subgp', subgp_ent)
    else:
        empee_ent = {
            'name': {
                'firstn': clar['firstn'],
                'surn': clar['surn'],
                'patro': clar['patro']
            },
            'exid': clar['exid']
        }
        entities.fill('empee', empee_ent)


def clar_org_fill(clar, entities):
    org_ent = {'name': clar['org']}
    entities.fill('org', org_ent)


def clar_fill(phrase, entities, clar, refs=[]):
    """Дополнить сущностями из уточнения по ссылке или по умолчанию."""

    if not clar:
        return

    for ref in refs:
        if ref.main == 'я':
            clar_org_fill(clar, entities)
            clar_name_fill(clar, entities)
            return

    clar_org_fill(clar, entities)
    if not any([_ in entities for _ in ['group', 'empee', 'place']]):
        clar_name_fill(clar, entities)


def cont_fill(phrase, entities, cont_ents, refs=[], intent=None):
    """Дополнить сущностями из контекста по ссылке."""

    def fill(ent_names):
        for ent_name in ent_names:
            if ent_name in cont_ents:
                entities.fill(ent_name, cont_ents[ent_name])

                if ent_name in ['group', 'empee']:
                    fill(['org'])

    for ref in refs:
        if ref.main in ['она', 'он']:
            if ref.hint in ['о', 'у', 'с', None]:
                fill(['empee', 'group'])
            elif ref.hint in ['в']:
                fill(['group'])
            elif ref.hint in ['по']:
                fill(['class'])
        elif ref.main in ['они']:
            fill(['group'])
        elif ref.main in ['университет', 'школа', 'колледж']:
            fill(['org'])
        elif ref.main in ['группа', 'класс']:
            fill(['group'])
        elif ref.main in ['преподаватель', 'учитель', 'человек']:
            fill(['empee'])
        elif ref.main in ['дисциплина', 'занятие', 'пара', 'урок']:
            fill(['class'])
        elif ref.main in ['день']:
            fill(['day'])


def extract(phrase):
    """Извлечь сущности, значения которых содержатся во вразе
    непосредственно. Если сущность может иметь несколько значений, то
    она тут же унифицируется."""

    phrase = drop_substrs(phrase)
    #print(phrase)

    entities = Entities()

    # вспомогательные функции извлекают сущность полностью
    # если сущность неполная или не в начальной форме, то она
    # исправляется в чекере
    # поиск сущности осуществляется до первого нахождения для
    # увеличения скорости
    for ent_name, extractor in {
            'org': extract_org,
            'empee': extract_empee,
            'group': extract_group,
            'subgp': extract_subgp,
            'class': extract_class,
            'day': extract_day,
            'place': extract_place}.items():
        entity = {}
        phrase = extractor(phrase, entity)
        if entity:
            entities[ent_name] = entity

    return entities, phrase


def compile_variants(variants):
    return map(functools.partial(re.compile, flags=re.IGNORECASE), variants)


def get_simple_variants(ENTITY, ENV):
    SPACE = r'\s+'

    return compile_variants([
        ENV +       SPACE + ENTITY,
        ENTITY +    SPACE + ENV
    ])


def extract_place(phrase, entity):
    # TODO сейчас не учитываются названия корпусов

    CAMPUS = r'(?P<campus>[1-9])'
    ENV = r'(корп\w*|дом\w*|здани\w*|постройк\w*|камп\w*)'
    phrase = regexp_extract(
        phrase, get_simple_variants(CAMPUS, ENV), 'campus', entity, 'campus')

    ROOM = r'(?P<room>\d+)'
    ENV = r'(кабин\w*|комнат\w*)'
    return regexp_extract(
        phrase, get_simple_variants(ROOM, ENV), 'room', entity, 'room')


def extract_group(phrase, entity):
    # А1071
    # 2251
    # озбу-2н93н
    YSU = r'(\b([а-я]{1,4}\-|А)?[0-9]([0-9]|[а-я])[0-9]{2}[а-я]?\b)'

    # 11Г
    SCHOOL = r'(\b([1-9]|1[01])[а-я]\b)'

    GROUP = '|'.join([YSU, SCHOOL])
    GROUP = f'(?P<group>{GROUP})'

    return regexp_extract(
        phrase, [re.compile(GROUP, re.IGNORECASE)], 'group', entity, 'name')


def extract_subgp(phrase, entity):
    SUBGP = r'(?P<subgp>[1-9])'
    ENV = r'(подгруп\w*)'

    return regexp_extract(
        phrase, get_simple_variants(SUBGP, ENV), 'subgp', entity, 'name')


def regexp_extract(phrase, VARIANTS, holder, entity, field):
    for exp in VARIANTS:
        res = re.search(exp, phrase)
        if res:
            entity[field] = res.group(holder)
            return replace_entity(
                phrase, [[res.start(holder), res.end(holder)]], holder)

    return phrase


def extract_org(phrase, entity):
    # не приводится к начальной форме
    extractor, lock = parsers['org']
    with lock:
        matches = extractor(phrase)

    for match in matches:
        #print(' '.join([token.forms[0].normalized for token in match.tokens]))
        if any([_ in match.fact.name for _ in ['универ', 'школ', 'колледж']]):
            entity['name'] = match.fact.name
            # если заменять на ОРГАНИЗАЦИЯ, то его захватит
            # extract_class
            return replace_entity(phrase, [match.span], 'org')

    return phrase


def extract_empee(phrase, entity):
    #extractor = natasha.SimpleNamesExtractor()
    extractor, lock = parsers['empee']
    with lock:
        matches = extractor(phrase)

    name = {}
    spans = []

    # .title() позволит лучше распознавать имена в нижнем регистре, но
    # приведет к большому количеству ложных срабатываний
    for match in matches:
        fact = match.fact
        for k, v in zip(
                ['firstn', 'surn', 'patro'],
                [fact.first, fact.last, fact.middle]):
            # капитализировать не надо, так как будет коррекция из базы
            if v:
                name[k] = v

        spans.append(match.span)

    if name:
        entity['name'] = name
        return replace_entity(phrase, spans, 'empee')

    return phrase


def extract_class(phrase, entity):
    parser, lock = parsers['class']
    with lock:
        matches = parser.findall(phrase)

    for match in matches:
        #from graphviz import Source
        #Source('\n'.join(match.tree.as_dot.source)).render(
        #    'clsmatch.gv', view=True)

        for k, v in zip(['name', 'spec'], [match.fact.name, match.fact.spec]):
            if v:
                entity[k] = v

        return replace_entity(phrase, [match.span], 'class')

    return phrase


def extract_day(phrase, entity):
    """Смещение относительно текущего дня. Для абсолютных дат лучше
    подойдет расписание."""

    parser, lock = parsers['day']
    with lock:
        matches = parser.findall(phrase)

    spans = []

    for match in matches:
        f = match.fact
        if match.fact.offset is not None:
            entity['offset'] = f.offset * f.count * (-1 if f.backward else 1)
        else:
            entity['weekday'] = f.weekday * (-1 if f.backward else 1)

        spans.append(match.span)

    if entity:
        return replace_entity(phrase, spans, 'day')

    return phrase


def replace_entity(phrase, spans, holder):
    d = 0
    for span in spans:
        phrase = phrase[:span[0]-d] + holder + phrase[span[1]-d:]
        d += (span[1] - span[0]) - len(holder)

    return phrase


def test_file():
    import json

    with open('../samples/classPeer.json', 'r') as f:
        samples = json.load(f)
    #with open('../samples/cls/samples.txt', 'r') as samples:
        for sample in samples:
            sample = sample['example']
            if sample:
                test_print(sample)


def test_lines():
    samples = """Какие пары, например, на следующей неделе в пятницу в 10а классе?
    А кто вел химию нефти и газа позавчера у группы 1162?
    я учусь в югорском государственном университете в группе 1491м, моя подгруппа 2
    кабинет 312 в корпусе 2 свободен
    где сейчас Кутышкин Андрей?"""

    for sample in samples.splitlines():
        test_print(sample)


def test_print(text):
    print(text)

    clar = {
        'isgp': True,
        'name': '1162б',
        'subgp': None,
        'org': 'Югорский государсвенный университет',
    }
    cont_ents = {
        'group': '1111',
    }

    entities, text = extract(text)

    print(text)
    print(entities, '\n')


if __name__ == '__main__':
    test_lines()
    #test_file()
