"""Portable, validated STAR export settings; no mesh or solver state is stored."""
import json
from starccm_workflow import WORKFLOW_DEFAULTS, validate_workflow
from copy import deepcopy
from starccm_tmc_export import TMC_DEFAULTS,validate_tmc_settings,canonical_tmc_options
import math
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
MEAN_CHOICES = {'enthalpy':'Полная энтальпия', 'velocity': 'Вектор скорости', 'pressure': 'Давление',
    'temperature': 'Температура', 'density': 'Плотность', 'viscosity': 'Динамическая вязкость',
    'wall_shear': 'Вектор напряжения трения на стержнях', 'wall_heat_flux': 'Плотность теплового потока на стержнях'}
DEFAULTS = dict(workflow=deepcopy(WORKFLOW_DEFAULTS),export_mode='general',tmc_settings=deepcopy(TMC_DEFAULTS),import_mesh=True, inner_fuse=True, inter_fuse=False,
    region_mode='by_subchannel', inlet_outlet_mode='by_subchannel', rename_boundaries=True,
    rod_wall_mode='by_rod', turbulence_model='rst', use_iapws=False,
    enable_thermal=True, enable_gravity=False, gravity_axis="-Z", evaluate_solution_reports=False, create_parameters=True, create_physics=True,
    create_mass_reports=True, create_quality_scene=True, create_quality_histograms=True,
    quality_bins=50, gap_sections=False, n_planes=11, n_sub_planes=11,
    key_planes=True, sub_planes=True, axis_probes=True, selected_subchannels=[],
    create_bad_cells=True, group_objects=True, create_summary=True, create_field_functions=True, initialize_solution=True,
    field_functions=list(FIELD_CHOICES), subchannel_reports=[], time_mean_fields=[], mean_start_step=1, time_step=1e-4)
ENUMS = dict(export_mode=('general','tmc_reference'),gravity_axis=('-X','+X','-Y','+Y','-Z','+Z'), region_mode=('by_subchannel','monolithic'), inlet_outlet_mode=('by_subchannel','single'),
    rod_wall_mode=('by_rod','sectors_60','monolithic'), turbulence_model=('rst','hybrid_srh'))


def validate_options(options, sub_count=None):
    if not isinstance(options,dict) or set(options)-set(DEFAULTS):
        raise ValueError('Неизвестные параметры профиля экспорта')
    values=deepcopy(DEFAULTS);values.update(deepcopy(options))
    values['tmc_settings']=validate_tmc_settings(values['tmc_settings'])
    if 'workflow' not in options:
        values['workflow']['quality_enabled']=any(options.get(key,False) for key in ('create_quality_scene','create_quality_histograms','create_bad_cells'))
        if values['export_mode']=='tmc_reference':
            t=values['tmc_settings'];w=values['workflow'];w.update(heat_enabled=True,tdc_enabled=True,initial_temperature=t['temperature_ref'],warmup_duration=t['hydro_duration'],block_duration=t['block_duration'],blocks_per_run=t['blocks_to_run'])
            w['fluid']=dict(density=t['rho'],dyn_vis=t['mu'],cp=t['cp'],**{'lambda':t['conductivity']})
    if isinstance(options.get('workflow'),dict) and options['workflow'].get('tdc_enabled') and 'heat_enabled' not in options['workflow']:
        values['workflow']['heat_enabled']=True
    values['workflow']=validate_workflow(values['workflow'])
    dt=values['time_step']
    if isinstance(dt,bool) or not isinstance(dt,(int,float)) or not math.isfinite(dt) or dt<=0:
        raise ValueError('Шаг времени Δt должен быть конечным положительным числом секунд')
    values['time_step']=float(dt)
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
    report_ids=values['workflow']['report_subchannels']
    if sub_count is not None and report_ids!=[-1] and any(n>sub_count for n in report_ids):raise ValueError('Недоступный подканал отчётов')
    if not values['inner_fuse'] or not values['rename_boundaries'] or not values['create_physics']:
        raise ValueError('Профиль не поддерживает отключение базовой сборки/физики/именования')
    if values['inter_fuse']:
        if values['inlet_outlet_mode']!='single' or values['region_mode']!='monolithic':
            raise ValueError('Несовместимые параметры Fuse')
    elif values['region_mode']!='by_subchannel' or values['inlet_outlet_mode']!='by_subchannel':
        raise ValueError('Несовместимые параметры Internal Interface')
    if values['workflow']['run_mode']=='steady' and values['turbulence_model']=='hybrid_srh':raise ValueError('Hybrid SRH–SST требует нестационарного режима')
    if values['workflow']['tdc_enabled'] != (values['export_mode']=='tmc_reference'):
        raise ValueError('Режим экспорта и флажок TDC не согласованы')
    if values['export_mode']=='tmc_reference':
        if sub_count is not None and sub_count!=2:raise ValueError('Эталон TMC поддерживает два подканала')
        for key,value in canonical_tmc_options(values['tmc_settings']).items():
            if values['workflow']['tdc_enabled'] and key in ('create_quality_scene','create_quality_histograms','create_bad_cells'):continue
            if values[key]!=value:raise ValueError(f'TMC требует согласованную настройку {key}')
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
