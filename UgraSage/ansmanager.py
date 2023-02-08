"""Модуль для формирования ответа пользователю."""

from copy import deepcopy

from common import (
    shuffle_now,
    name2name_s,
    Entities
)
import dbadapter
import entityextractor
import intentextractor
import entitychecker
from intenthandlers import (
    userclar,
    nextclass,
    botinfo,
    classpeer,
    classlist,
    employeeinfo,
    educatorplace
)


def manage(essence):
    # фраза может быть пустой строкой

    ans = {}

    dbadapter.check_user(essence['usr_id'])
    clar = dbadapter.get_clar(essence['usr_id'])

    if 'welcome' in essence:
        dbadapter.reset_tmpdata(essence['usr_id'])

        if not clar:
            welcome_msg = (
                'Здравствуйте! Пожалуйста, назовите свою образовательную'
                ' организацию, а также группу, если вы учащийся, или имя, если'
                ' вы преподаватель.'
            )
        elif clar['isgp']:
            welcome_msg = f'Привет! Твоя группа {clar["name"]}, а '

            if not clar['subgp']:
                welcome_msg += 'подгруппу ты не назвал.'
            else:
                welcome_msg += f'подгруппа {clar["subgp"]}.'
        else:
            usr_fulln = f'{clar["surn"]} {clar["firstn"]} {clar["patro"]}'
            welcome_msg = f'Здравствуйте, {usr_fulln}!'

        welcome_msg += ' Можно спросить, что я умею.'

        ans['text'] = welcome_msg
        return ans

    # команда, основные параметры и дополнительные
    # сущности будут проверяться с конца (см entitychecker)
    handlers = {
        'nextClass': [
            nextclass.handle,
            [[None, 'subgp', 'class'],
             shuffle_now(['group', 'empee', 'place']),
             ['org']],
            {}
        ],
        'botInfo': [
            botinfo.handle,
            [],
            {}
        ],
        'userClar': [
            userclar.handle,
            [[None, 'subgp'],
             shuffle_now(['group', 'empee']),
             ['org']],
            {'usr_id': essence['usr_id']}
        ],
        'classPeer': [
            classpeer.handle,
            [[None, 'subgp', 'class'],
             shuffle_now(['group', 'empee']),
             ['org']],
            {'usr_id': essence['usr_id']}
        ],
        'classList': [
            classlist.handle,
            [[None, 'subgp', 'day'],
             shuffle_now(['group', 'empee']),
             ['org']],
            {'usr_id': essence['usr_id']}
        ],
        'employeeInfo': [
            employeeinfo.handle,
            [['empee'],
             ['org']],
            {'usr_id': essence['usr_id']}
        ],
        'educatorPlace': [
            educatorplace.handle,
            [['empee'],
             ['org']],
            {'usr_id': essence['usr_id']}
        ]
    }

    # начало обработки фразы
    tmpdata = dbadapter.get_tmpdata(essence['usr_id'])

    usr_ans = tmpdata['answer']
    cont_ents = tmpdata['context']['entities']

    # если в subject непустая строка, то вопрос установлен, иначе -- нет
    if usr_ans['subject']:
        usr_ans['text'] = essence['phrase'].strip()
        entities = Entities(cont_ents)
        intent = tmpdata['context']['intent']
        handlers[intent][1] = tmpdata['unchecked_ents']
    else:
        # извлечь сущности непосредственно из фразы
        # во фразе значения сущностей унифицируются (1162б -> group)
        entities, phrase = entityextractor.extract(essence['phrase'])

        # наложить сущности из фразы, которые определил клиент
        if 'entities' in essence:
            entities.update(essence['entities'])

        intent = intentextractor.extract(phrase)

        refs = entityextractor.extract_refs(phrase)

        # добавить сущности из контекста
        entityextractor.cont_fill(phrase, entities, cont_ents, refs, intent)
        cont_ents = deepcopy(entities)

        # добавить сущности из уточнения
        entityextractor.clar_fill(phrase, entities, clar, refs)

    handler, ent_names, ex_params = handlers.get(intent)
    if entitychecker.check(ent_names, entities, usr_ans, ans):
        handler(entities, ans, True, **ex_params)

    # сохранить временные данные
    tmpdata['unchecked_ents'] = ent_names
    tmpdata['context']['intent'] = intent

    if usr_ans['subject']:
        # в след. раз будет обрабатываться ответ, поэтому нужно
        # сохранить все сущности
        tmpdata['context']['entities'] = entities
    else:
        tmpdata['context']['entities'] = cont_ents

    dbadapter.set_tmpdata(essence['usr_id'], tmpdata)

    assert ans['text']
    return ans
