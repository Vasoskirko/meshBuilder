"""Geometry/physics contract for effective, dimensionless energy-balance TDC."""
from copy import deepcopy
import math
import re
from starccm_tdc_paths import account_paths
from starccm_surface_catalog import surface_catalog, validate_pairs
from starccm_flow_defaults import calculator_mass_flow
from starccm_time_schedule import schedule

TDC_DEFAULTS=dict(target_components=True,target='',path_methods={},path_reports={},scalar_diffusion_confirmed=False,a=1,b=2,gaps=[],equivalent=False,min_delta_t=.01,balance_tolerance=.05,
                  sections=11,blocks=True,conduction=False,compensating_source=True)

def validate_tdc(data):
    if not isinstance(data,dict) or set(data)-set(TDC_DEFAULTS):raise ValueError('Неизвестные настройки TDC')
    v=deepcopy(TDC_DEFAULTS);v.update(deepcopy(data))
    for k,d in TDC_DEFAULTS.items():
        if type(d) is float:
            if type(v[k]) not in (int,float) or not math.isfinite(v[k]) or v[k]<=0:raise ValueError('TDC: неверный '+k)
            v[k]=float(v[k])
        elif type(v[k]) is not type(d):raise ValueError('TDC: неверный тип '+k)
    if v['a']<1 or v['b']<1 or v['a']==v['b']:raise ValueError('Выберите два разных подканала TDC')
    if not 3<=v['sections']<=101:raise ValueError('TDC: число сечений 3…101')
    if v['balance_tolerance']>1:raise ValueError('TDC: допуск баланса не больше 1')
    if any(not isinstance(k,str) for k in v['gaps']) or len(v['gaps'])!=len(set(v['gaps'])):raise ValueError('TDC: повторяющиеся зазоры')
    if v['target'] and v['gaps'] and v['gaps']!=[v['target']]:raise ValueError('Устаревший выбор зазоров конфликтует с целевым соединением')
    if len(v['gaps'])>1 and not v['target']:raise ValueError('Выберите один целевой зазор вместо прежней суммы эквивалентных зазоров')
    if any(not isinstance(k,str) or m not in ('boundary','reconstruct','report','unmeasured','zero') for k,m in v['path_methods'].items()):raise ValueError('Неверный способ учёта боковой поверхности')
    if any(not isinstance(k,str) or not isinstance(name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',name) for k,name in v['path_reports'].items()):raise ValueError('Отчёт мощности: используйте имя из латинских букв, цифр и _')
    return v

def build_plan(result,model,options,fluid,yplus=None):
    w=options['workflow'];v=validate_tdc(w['tdc_settings']);a,b=v['a'],v['b']
    if options['use_iapws'] or not options['enable_thermal'] or w['run_mode']=='steady' or (w['run_mode']=='auto' and options['turbulence_model']!='hybrid_srh'):
        raise ValueError('TDC требует нестационарный расчёт с энергией и постоянными свойствами')
    if options['enable_gravity']:raise ValueError('Для TDC отключите гравитацию; баланс чувствительной энергии не включает механическую работу')
    if not options['create_parameters']:raise ValueError('TDC требует создания физических параметров')
    cat=surface_catalog(result,model,options['rod_wall_mode'],options['inter_fuse'])
    numbers={d['number'] for d in cat['domains']}
    if not {a,b}<=numbers:raise ValueError('Выбранные подканалы TDC отсутствуют в сетке')
    rows={r['id']:r for r in cat['sides']};pairs=w['boundary_pairs'];validate_pairs(pairs,cat)
    capids={r['id'] for r in cat['endcaps']}
    axial_pairs=[p for p in pairs if p['first'] in capids or p['second'] in capids]
    if any(p['kind']!='fully_developed' for p in axial_pairs):raise ValueError('TDC требует Fully Developed с фиксированным расходом на входе–выходе')
    for p in axial_pairs:
        expected=calculator_mass_flow(cat,fluid,yplus or {},p['first'])
        if not p.get('mass_flow_auto',False) and abs(p['mass_flow']-expected)>max(expected,1e-30)*1e-6:
            raise ValueError('Расход TDC должен совпадать с аналитическим G=ρU_b; включите расчётный расход пары')
    axial={p[k] for p in pairs if p['kind']!='internal' for k in ('first','second') if p[k] in capids}
    if any(r['id'] not in axial for r in cat['endcaps'] if set(r['sources'])&{a,b}):
        raise ValueError('Для балансового TDC задайте периодические пары вход–выход во вкладке «Сетка»')
    assigned={r['surface']:r['kind'] for r in w['boundary_conditions']}
    for r in cat['rods']:
        if set(r['sources'])&{a,b} and assigned.get(r['id'],'wall')!='wall':raise ValueError('Для TDC поверхности ТВЭЛ/НК/ИК должны оставаться стенками')
    target,paths,all_paths=account_paths(cat,w,v)
    exchanges=[dict(id=target['connection'],area=target['area'],periodic=target['kind']=='periodic',normal=target['normal'])]
    if v['conduction']:raise ValueError('Турбулентная поправка пока недоступна: нужно отдельно определить перенос средним течением; молекулярный поток доступен как диагностика целевого зазора')
    if not v['compensating_source']:raise ValueError('Периодический нагреваемый TDC требует компенсационного объёмного стока')
    if not w['heat_enabled'] or not w['heat_values']:raise ValueError('Задайте нагрев во вкладке «Физика»')
    time=schedule(w,cat,fluid,yplus or {},result.params.z_len,options['time_step'])
    dt=options['time_step'];time['warmup']=math.ceil(time['warmup']/dt-1e-12)*dt;time['block']=math.ceil(time['block']/dt-1e-12)*dt
    minimum=time['warmup']+w['blocks_per_run']*time['block']
    if w['end_time'] and w['end_time']+dt*1e-8<minimum:raise ValueError(f'TDC: после округления этапов окончание должно быть не меньше {minimum:.12g} с')
    time['end']=w['end_time'] or minimum;time['minimum']=minimum
    cap=next(r for r in cat['endcaps'] if r['role']=='Inlet')
    mass=calculator_mass_flow(cat,fluid,yplus or {},cap['id'])
    g=mass/cap['area']
    # Separate regions: calculator may supply per-source mass; G stays a common reference.
    source_cat=surface_catalog(result,model,options['rod_wall_mode'],False)
    volumes={r['sources'][0]:r['area']*result.params.z_len for r in source_cat['endcaps'] if r['role']=='Inlet'}
    return dict(target=target,paths=paths,all_paths=all_paths,volumes=volumes,settings=v,catalog=cat,exchanges=exchanges,area=target['area'],
                height=result.params.z_len,g_ref=g,time=time,a=a,b=b)


def result_from_means(qa,qb,ha0,ha1,hb0,hb1,duration,delta,area,cp,g,min_delta,tolerance,other_a=0.,other_b=0.):
    vals=(qa,qb,ha0,ha1,hb0,hb1,duration,delta,area,cp,g,min_delta,tolerance,other_a,other_b)
    if any(not math.isfinite(x) for x in vals) or min(duration,area,cp,g,min_delta,tolerance)<=0:raise ValueError('Неверные данные TDC')
    q_a=qa-other_a-(ha1-ha0)/duration;q_b=-(qb-other_b-(hb1-hb0)/duration)
    residual=q_a-q_b;relative=abs(residual)/max(abs(q_a),abs(q_b),1e-30)
    valid=abs(delta)>=min_delta and q_a*delta>0 and relative<=tolerance
    return dict(q_a=q_a,q_b=q_b,residual=residual,relative=relative,valid=valid,
                tdc=q_a/(area*cp*g*delta) if valid else None)
