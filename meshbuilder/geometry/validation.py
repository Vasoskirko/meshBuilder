"""Guard interactive geometry work before allocation or destructive rebuilds."""
import math

MAX_LATTICE_CANDIDATES=20000  # Includes the full existing GUI range S<=300, P>=5.


def positive(value,label):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
        raise ValueError(f'{label}: требуется конечное положительное число')
    return value


def validate_geometry(model):
    for key in ('s_flat','pitch','d_fuel','d_guide','d_instrument'):positive(getattr(model,key),key)
    if model.lattice_type!='triangular':raise ValueError('Поддерживается только треугольная решётка')
    if model.pitch<=model.d_fuel:raise ValueError('Шаг решётки должен быть больше диаметра ТВЭЛа')
    if model.s_flat/model.pitch>68:raise ValueError('Слишком много узлов решётки: увеличьте шаг или уменьшите оболочку')
    ring=math.ceil(model.s_flat/model.pitch)+1
    if (2*ring+1)**2>MAX_LATTICE_CANDIDATES:raise ValueError('Превышен предел числа узлов решётки')
    for diameter in model.user_custom_diameters.values():positive(diameter,'Диаметр стержня')
    if any(t not in ('fuel','guide','instrument') for t in model.user_rod_types.values()):raise ValueError('Неизвестный тип стержня')


def sub_signature(model,sub):
    return (tuple(sorted((model.rods[r].q,model.rods[r].r) for r in sub.rod_ids)),sub.wall_side,sub.corner_index)
