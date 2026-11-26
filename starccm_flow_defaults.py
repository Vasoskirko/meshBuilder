"""The same Reynolds-based bulk velocity used by the native export parameters."""
import math
import numpy as np


def calculator_mass_flow(catalog,fluid,yplus,surface):
    cap=next((r for r in catalog.get('endcaps',[]) if r['id']==surface),None)
    if cap is None:raise ValueError('Для расчётного расхода выберите вход или выход')
    area=sum(r['area'] for r in catalog['endcaps'] if r['role']=='Inlet')
    perimeter=sum(float(np.linalg.norm(np.diff(line,axis=0),axis=1).sum()) for r in catalog['rods'] for line in r['lines'])
    re=float(yplus.get('reynolds',yplus.get('re',200000.)))
    mu=float(fluid['dyn_vis']);rho=float(fluid['density'])
    if any(not math.isfinite(v) or v<=0 for v in (area,perimeter,re,mu,rho)):raise ValueError('Проверьте Re, свойства и геометрию для расчёта расхода')
    dh=4*area/perimeter
    velocity=re*mu/(rho*dh)
    return rho*velocity*cap['area']
