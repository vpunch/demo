from pathlib import Path

from yargy import rule, and_, or_, not_
from yargy.pipelines import morph_pipeline
from yargy.relations import case_relation
from yargy.predicates import gram, eq, in_
from yargy.interpretation import fact

Cls = fact(
    'Cls',
    ['spec', 'name']
)

samples = Path(__file__).resolve().parent.parent.parent / 'data' / 'classes'

base_names = []
with open(samples / 'names.txt') as f:
    for line in f:
        name = line.rstrip()
        base_names.append(name)

case = case_relation()

BASE = morph_pipeline(base_names).match(case).named('BASE')

PREF = gram('ADJF').match(case).named('PREF')

SEP = in_(',и')

# инженерная и компьютерная графика
LONGPREF = rule(
    PREF,
    rule(SEP, PREF).repeatable()
).named('LONGPREF')

# программирование микропроцессорных систем управления
def get_suff(case):
    SUFF = rule(
        and_(
            gram('ADJF'),
            gram(case)
        ).optional(),
        and_(
            gram('NOUN'),
            gram(case),
            not_(or_(gram('CONJ'), gram('PREP')))
        ).repeatable(),
    )

    # химия нефти и газа
    LONGSUFF = rule(
        SUFF,
        rule(SEP, SUFF).repeatable()
    )

    return SUFF, LONGSUFF

GENT_SUFF, GENT_LONGSUFF = get_suff('gent')
DATV_SUFF, DATV_LONGSUFF = get_suff('datv')
SUFF = or_(GENT_SUFF, DATV_SUFF).named('SUFF')
LONGSUFF = or_(GENT_LONGSUFF, DATV_LONGSUFF).named('LONGSUFF')#.interpretation(Cls.name.custom(print))

NAME = rule(
    or_(LONGPREF, PREF).optional(),
    BASE,
    or_(LONGSUFF, SUFF).optional()
).named('NAME')

LONGNAME = rule(
    NAME,
    rule(SEP, NAME).repeatable()
).named('LONGNAME')

# правовые основы противодействия экстремизму и терроризму
INTRO = rule(
    gram('ADJF').optional(),
    morph_pipeline([
        'основы', 
        'введение в', 
        'методы'
    ]),
    eq(':').optional()
).named('INTRO')

# основы кадровой политики и кадрового планирования
FULLNAME = rule(
    INTRO.optional(),
    or_(LONGNAME, NAME)
).interpretation(
    Cls.name
).named('FULLNAME')


DOT = eq('.')

LAB = morph_pipeline([
    'лб',
    'лаб',
    'лаба',
    'лабораторка',
    'лабораторная',
    'лабораторная работа',
]).interpretation(
    Cls.spec.const('лаб')
)

PRAC = morph_pipeline([
    'пр',
    'прак',
    'практика',
    'практическая работа',
]).interpretation(
    Cls.spec.const('пр')
)

LECT = morph_pipeline([
    'лек',
    'лекция',
]).interpretation(
    Cls.spec.const('лек')
)

SPEC = rule(
    or_(
        LAB, 
        PRAC, 
        LECT
    ),
    DOT.optional(),
    eq('по')
).named('SPEC')

CLS = rule(
    SPEC.optional(),
    FULLNAME
).interpretation(
    Cls
)

#from graphviz import Source
#Source('\n'.join(CLS.as_dot.source)).render(f'CLS.gv', view=True)
