"""Physical-time planning; block count is a budget, not independent statistics."""
import math
from starccm_flow_defaults import calculator_mass_flow


def schedule(workflow,catalog,fluid,yplus,height,dt):
    flight=None
    if catalog.get('endcaps'):
        cap=next(r for r in catalog['endcaps'] if r['role']=='Inlet')
        velocity=calculator_mass_flow(catalog,fluid,yplus,cap['id'])/(fluid['density']*cap['area'])
        flight=height/velocity
    if workflow['time_input_mode']=='passes':
        if flight is None:raise ValueError('Для числа пролётов нужна построенная геометрия и опорная скорость')
        warmup=workflow['runup_passes']*flight;block=workflow['block_passes']*flight
    else:warmup=workflow['warmup_duration'];block=workflow['block_duration']
    if workflow.get('tdc_enabled'):
        warmup=math.ceil(warmup/dt-1e-12)*dt;block=math.ceil(block/dt-1e-12)*dt
    budget=warmup+block*workflow['blocks_per_run']
    if not math.isfinite(budget/dt):raise ValueError('Слишком большой диапазон времён')
    minimum=max(budget,math.ceil(budget/dt)*dt)
    end=workflow['end_time'] or minimum
    if end<minimum:raise ValueError(f'Время окончания должно быть не меньше {minimum:.12g} с')
    return dict(flight=flight,warmup=warmup,block=block,minimum=minimum,end=end)
