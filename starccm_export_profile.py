"""Portable, validated STAR export settings; no mesh or solver state is stored."""
import json
import os
import tempfile
from pathlib import Path

FIELD_CHOICES = {
    'z_fraction': 'Относительная высота Z/L: 0 на входе, 1 на выходе',
    'speed': 'Модуль скорости |U|, м/с — для сцен и графиков',
    'mass_flux': 'Массовый поток ρ|U|, кг/(м²·с) — для распределений',
    'quality': 'Удобные имена нативных полей качества — значения не пересчитываются',
    'balances': 'Знаковые суммы потоков массы и энергии — для контроля баланса',
}
REPORT_CHOICES = {
    'geometry': 'Площади, объёмы, смоченный периметр и гидравлический диаметр',
    'hydraulics': 'Расход, средняя осевая скорость, давление, перепад и Reynolds',
    'wall': 'Напряжение трения на стенке, Cf и Darcy по трению',
    'thermal': 'Среднемассовая температура, температура стенки и тепловая мощность',
}
MEAN_CHOICES = {'velocity': 'Вектор скорости', 'pressure': 'Давление',
    'temperature': 'Температура', 'density': 'Плотность', 'viscosity': 'Динамическая вязкость',
    'wall_shear': 'Вектор напряжения трения на стержнях', 'wall_heat_flux': 'Плотность теплового потока на стержнях'}
DEFAULTS = dict(import_mesh=True, inner_fuse=True, inter_fuse=False,
    region_mode='by_subchannel', inlet_outlet_mode='by_subchannel', rename_boundaries=True,
    rod_wall_mode='by_rod', turbulence_model='rst', use_iapws=False,
    enable_thermal=True, enable_gravity=False, gravity_axis="-Z", evaluate_solution_reports=False, create_parameters=True, create_physics=True,
    create_mass_reports=True, create_quality_scene=True, create_quality_histograms=True,
    quality_bins=50, gap_sections=False, n_planes=11, n_sub_planes=11,
    key_planes=True, sub_planes=True, axis_probes=True, selected_subchannels=[],
    create_bad_cells=True, group_objects=True, create_summary=True, create_field_functions=True, initialize_solution=True,
    field_functions=list(FIELD_CHOICES), subchannel_reports=[], time_mean_fields=[], mean_start_step=1)
ENUMS = dict(gravity_axis=('-X','+X','-Y','+Y','-Z','+Z'), region_mode=('by_subchannel','monolithic'), inlet_outlet_mode=('by_subchannel','single'),
    rod_wall_mode=('by_rod','sectors_60','monolithic'), turbulence_model=('rst','hybrid_srh'))


def validate_options(options, sub_count=None):
    if not isinstance(options,dict) or set(options)-set(DEFAULTS):
        raise ValueError('Неизвестные параметры профиля экспорта')
    values=dict(DEFAULTS,**options)
    for key,default in DEFAULTS.items():
        value=values[key]
        if type(value) is not type(default):
            raise ValueError(f'{key}: неверный тип значения')
        if key in ENUMS and value not in ENUMS[key]:
            raise ValueError(f'{key}: неизвестный вариант')
    for key, choices in (('field_functions', FIELD_CHOICES), ('subchannel_reports', REPORT_CHOICES), ('time_mean_fields', MEAN_CHOICES)):
        selected = values[key]
        if any(type(v) is not str or v not in choices for v in selected) or len(set(selected)) != len(selected):
            raise ValueError(f'{key}: неизвестный или повторяющийся выбор')
    if not 1 <= values['mean_start_step'] <= 1000000000:
        raise ValueError('Начальный шаг усреднения должен быть положительным целым')
    if not 5<=values['quality_bins']<=500:
        raise ValueError('quality_bins: требуется значение 5…500')
    for key in ('n_planes','n_sub_planes'):
        if values[key] != 0 and not 2<=values[key]<=100:
            raise ValueError(f'{key}: требуется 0 или 2…100')
    selected=values['selected_subchannels']
    if any(type(i) is not int or i<1 or (sub_count is not None and i>sub_count) for i in selected) or len(set(selected))!=len(selected):
        raise ValueError('Профиль содержит недоступные или повторяющиеся номера подканалов')
    if not values['inner_fuse'] or not values['rename_boundaries'] or not values['create_physics']:
        raise ValueError('Профиль не поддерживает отключение базовой сборки/физики/именования')
    if values['inter_fuse']:
        if values['rod_wall_mode']=='sectors_60' or values['inlet_outlet_mode']!='single' or values['region_mode']!='monolithic':
            raise ValueError('Несовместимые параметры Fuse')
    elif values['region_mode']!='by_subchannel' or values['inlet_outlet_mode']!='by_subchannel' or values['rod_wall_mode']=='monolithic':
        raise ValueError('Несовместимые параметры Internal Interface')
    return values


def save_profile(options,path):
    values=validate_options(options)
    text=json.dumps(dict(format='meshBuilder-star-export',version=1,options=values),ensure_ascii=False,indent=2)+'\n'
    target=Path(path)
    fd,temp=tempfile.mkstemp(prefix='.star_profile_',suffix='.tmp',dir=target.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f:f.write(text)
        os.replace(temp,target)
    finally:
        Path(temp).unlink(missing_ok=True)


def load_profile(path,sub_count=None):
    def pairs(items):
        obj={}
        for k,v in items:
            if k in obj:raise ValueError(f'Повторяющийся ключ: {k}')
            obj[k]=v
        return obj
    data=json.loads(Path(path).read_text(encoding='utf-8-sig'),object_pairs_hook=pairs)
    if not isinstance(data,dict) or set(data)!={'format','version','options'} or data['format']!='meshBuilder-star-export' or type(data['version']) is not int or data['version']!=1:
        raise ValueError('Неизвестный формат или версия профиля экспорта')
    return validate_options(data['options'],sub_count)
