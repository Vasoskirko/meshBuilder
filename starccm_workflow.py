"""Versioned settings for the unified export window; independent of Qt."""
from copy import deepcopy
import math

WORKFLOW_DEFAULTS = dict(run_mode='auto',heat_enabled=False,heat_values={},boundary_pairs=[],disabled_internal_pairs=[],quality_thresholds=dict(CellQuality=.01,FaceValidity=.95,VolumeChange=.01,SkewnessAngle=85.),fluid={},version=1, quality_enabled=False, tdc_enabled=False,tdc_equivalence=False,
    viscosity_method='constant', conductivity_method='constant', initial_velocity='theory',
    initial_temperature=573.15, initial_pressure=0., initial_ux=0., initial_uy=0.,
    inner_iterations=5, warmup_duration=.45, block_duration=.45, blocks_per_run=1,
    velocity_seed=True)


def validate_workflow(data):
    if not isinstance(data,dict) or set(data)-set(WORKFLOW_DEFAULTS):
        raise ValueError('Неизвестные настройки единого окна экспорта')
    result=deepcopy(WORKFLOW_DEFAULTS);result.update(deepcopy(data))
    for key,default in WORKFLOW_DEFAULTS.items():
        value=result[key]
        if type(default) is float:
            if type(value) not in (int,float) or not math.isfinite(value):raise ValueError(f'{key}: требуется конечное число')
            result[key]=float(value)
        elif type(value) is not type(default):raise ValueError(f'{key}: неверный тип')
    thresholds=result['quality_thresholds']
    if set(thresholds)!={'CellQuality','FaceValidity','VolumeChange','SkewnessAngle'}:raise ValueError('Неизвестные пороги качества')
    for key,value in thresholds.items():
        if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=(180 if key=='SkewnessAngle' else 1):raise ValueError('Неверный порог качества')
    fluid=result['fluid']
    allowed={'density','dyn_vis','cp','lambda','t_ref_c','p_ref_mpa'}
    if set(fluid)-allowed:raise ValueError('Неизвестные свойства жидкости')
    for key,value in fluid.items():
        if type(value) not in (int,float) or not math.isfinite(value) or (value<=0 and key!='t_ref_c') or (key=='t_ref_c' and value<=-273.15):raise ValueError('Некорректные свойства жидкости')
    if result['version']!=1:raise ValueError('Неизвестная версия настроек окна')
    for key in ('viscosity_method','conductivity_method'):
        if result[key] not in ('constant','iapws'):raise ValueError(f'{key}: неизвестный метод')
    if result['run_mode'] not in ('auto','steady','unsteady'):raise ValueError('Неизвестный режим расчёта')
    for key,value in result['heat_values'].items():
        if not isinstance(key,str) or not key or type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=1e12:raise ValueError('Некорректный тепловой поток группы')
    if any(not isinstance(key,str) for key in result['disabled_internal_pairs']):raise ValueError('Неверный список внутренних интерфейсов')
    for pair in result['boundary_pairs']:
        if not isinstance(pair,dict) or set(pair)!={'first','second','kind'} or any(not isinstance(v,str) for v in pair.values()) or pair['kind'] not in ('periodic_translation','internal'):raise ValueError('Неизвестная настройка интерфейса')
    if result['initial_velocity'] not in ('theory','zero'):raise ValueError('Неизвестная начальная скорость')
    if result['initial_temperature']<=0:raise ValueError('Начальная температура должна быть выше абсолютного нуля')
    for key in ('warmup_duration','block_duration'):
        if result[key]<=0:raise ValueError('Длительность должна быть положительной')
    for key in ('inner_iterations','blocks_per_run'):
        if not 1<=result[key]<=10000:raise ValueError(f'{key}: целое от 1 до 10000')
    return result


def estimate_plot3d_bytes(result):
    """Bounded text estimate; .16e is 22/23 chars, plus one separator per value.

    No coordinate expansion or 3D arrays. Actual coordinates can have larger
    exponents; this is intentionally displayed as an estimate, not an exact size.
    """
    if result is None or not hasattr(result,'blocks'):return None
    nz=result.params.nz
    nodes=sum(x.size for x,y in result.blocks)*(nz+1)
    header=len(str(len(result.blocks)))+1+sum(len(f'{x.shape[0]} {x.shape[1]} {nz+1}\n') for x,y in result.blocks)
    return header+nodes*3*23,header+nodes*3*24
