"""Physical edge ranges and reference wall-unit diagnostics for bundle meshes."""
import math
import numpy as np


def edge_ranges(result):
    """Use actual i/j edges, not nominal spacing or decimated plot geometry."""
    if not result.blocks:raise ValueError('Нет построенных блоков')
    ranges={}
    def include(name, values):
        values=np.asarray(values)
        if not values.size or not np.isfinite(values).all() or np.any(values<=0):
            raise ValueError('Некорректная длина ребра сетки')
        lo,hi=float(values.min()),float(values.max())
        old=ranges.get(name,(lo,hi));ranges[name]=(min(old[0],lo),max(old[1],hi))
    for i,(x,y) in enumerate(result.blocks):
        az=np.hypot(np.diff(x,axis=0),np.diff(y,axis=0))
        normal=np.hypot(np.diff(x,axis=1),np.diff(y,axis=1))
        starts=result.wall_starts[i]
        include('azimuth',az);include('normal',normal)
        include('wall_azimuth',az[:,0 if starts else -1])
        include('first_normal',normal[:,0 if starts else -1])
    nz=result.params.nz; length=result.params.z_len
    if not isinstance(nz,(int,np.integer)) or nz<=0 or not math.isfinite(length) or length<=0:
        raise ValueError('Некорректное осевое разбиение')
    include('axial',[length/nz])
    return ranges


def wall_units(ranges, calculator_result):
    """One reference scale from one calculator snapshot, no fluid-state mixing."""
    data=calculator_result or {}
    nu=float(data.get('nu',float('nan')));ut=float(data.get('u_tau',float('nan')))
    if not math.isfinite(nu) or not math.isfinite(ut) or min(nu,ut)<=0:
        raise ValueError('Рассчитайте вязкий масштаб в калькуляторе y+')
    ell=nu/ut
    if not math.isfinite(ell) or ell<=0:raise ValueError('Некорректный вязкий масштаб')
    return ell,{key:tuple(float(v)/ell for v in pair) for key,pair in ranges.items()}


def format_wall_units(ranges, calculator_result):
    ell,plus=wall_units(ranges,calculator_result)
    rows=[('Азимут Δφ+',plus['azimuth']),
          ('Азимут у стенки Δφ_wall+',plus['wall_azimuth']),
          ('По высоте Δz+',plus['axial']),
          ('По нормали Δn+',plus['normal']),
          ('Первый слой Δn₁+',plus['first_normal']),
          ('Центр первого слоя y₁+ ≈',tuple(v/2 for v in plus['first_normal']))]
    lines=['РАЗМЕРЫ В ВЯЗКИХ ЕДИНИЦАХ',
           f'ℓν = {ell*1e6:.5g} мкм  |  ν = {calculator_result["nu"]:.5g} м²/с  |  uτ = {calculator_result["u_tau"]:.5g} м/с',
           '',f'{"Направление":<30} {"min":>12} {"max":>12}', '─'*56]
    for label,(lo,hi) in rows:
        lines.append(f'{label:<30} {lo:>12.4g} {hi:>12.4g}')
    lines.extend(['─'*56,'Δφ+ — длина азимутального ребра / ℓν; y₁+ ≈ Δn₁+/2.',
                  'Опорный uτ, не локальные значения CFD. Пригодность LES/DNS проверяется отдельно.'])
    return '\n'.join(lines)
