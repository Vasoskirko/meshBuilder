"""Reject unsupported selections before partial six-block CFD construction."""
SUPPORTED_TYPES = frozenset(('interior', 'guide_sub', 'instrument_sub'))
TYPE_NAMES = {'peripheral': 'периферийный', 'corner': 'угловой',
              'recovered': 'восстановленная область'}


def require_supported_mesh(model, ids):
    problems = []
    recovered = False
    for sid in sorted(set(ids)):
        sub = model.subchannels.get(sid)
        if sub is None:
            problems.append(f'S{sid}: отсутствует в текущей геометрии')
        elif sub.sub_type not in SUPPORTED_TYPES or len(sub.rod_ids) != 3:
            recovered |= sub.sub_type == 'recovered'
            name = TYPE_NAMES.get(sub.sub_type, sub.sub_type)
            problems.append(f'S{sid}: {name}, стержней {len(sub.rod_ids)}')
    if problems:
        heading = ('Выбраны восстановленные области или другие неподдерживаемые подканалы.'
                   if recovered else 'Выбраны подканалы, не поддерживаемые шестиблочным построителем.')
        raise ValueError(heading + '\n' + '\n'.join(problems) +
                         '\nЧастичная CFD-сетка не создаётся. Выберите только поддерживаемые '
                         'внутренние треугольные подканалы. Геометрия и гидравлика остальных областей доступны отдельно.')
