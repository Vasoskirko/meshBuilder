"""Reject unsupported recovered regions before partial CFD construction."""
def require_supported_mesh(model,ids):
    unsupported=[k for k in ids if k in model.subchannels and model.subchannels[k].sub_type=='recovered']
    if unsupported:raise ValueError('Выбраны восстановленные области '+', '.join('S'+str(k) for k in unsupported)+'. Геометрия и гидравлика построены, но шестиблочная CFD-сетка для этих областей пока не поддерживается. Выберите только поддерживаемые треугольные подканалы.')
