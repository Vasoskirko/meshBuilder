"""Experimental block-interior elliptic smoothing with conservative acceptance."""
import numpy as np


def core_quality(points):
    a,b,c,d=points[:-1,:-1],points[1:,:-1],points[1:,1:],points[:-1,1:]
    pairs=((b-a,d-a),(b-a,c-b),(c-d,c-b),(c-d,d-a))
    crosses=[];cosines=[]
    for u,v in pairs:
        denom=np.linalg.norm(u,axis=-1)*np.linalg.norm(v,axis=-1)
        cross=u[...,0]*v[...,1]-u[...,1]*v[...,0]
        crosses.append(np.divide(cross,denom,out=np.zeros_like(cross),where=denom>0))
        cosines.append(np.divide(np.sum(u*v,axis=-1),denom,out=np.ones_like(cross),where=denom>0))
    signed=np.stack(crosses);orientation=1 if np.median(signed)>=0 else -1
    normalized=signed*orientation
    angles=np.degrees(np.arcsin(np.clip(np.abs(cosines),0,1)))
    return dict(min_scaled_jacobian=float(normalized.min()),
        mean_angle_error_deg=float(angles.mean()),max_angle_error_deg=float(angles.max()),
        orientation=orientation)


def smooth_core(points,iterations=15,*,growth_limit=None,size_limit=None,progress=None):
    """Keep perimeter and first core cell fixed; accept only non-worsening steps.

    points are wall-front -> opposite boundary. Either orientation is supported.
    Constraints refer to actual Euclidean normal-edge lengths after smoothing.
    """
    if isinstance(iterations,bool) or not isinstance(iterations,(int,np.integer)) or not 0<=iterations<=100:
        raise ValueError('Число шагов сглаживания должно быть целым от 0 до 100')
    original=np.asarray(points,dtype=float)
    if original.ndim!=3 or original.shape[-1]!=2 or min(original.shape[:2])<2 or not np.isfinite(original).all():
        raise ValueError('Для сглаживания нужны конечные координаты (ni,nj,2)')
    grid=original.copy();before=core_quality(grid)
    if before['min_scaled_jacobian']<=0:raise ValueError('Нельзя сглаживать перевёрнутое ядро')
    current=before;accepted=0
    if grid.shape[0]>=3 and grid.shape[1]>=4:
        for step in range(iterations):
            if progress:progress(step,iterations)
            # Weighted elliptic averaging; fixes both interface edges, the core
            # front, first core cell and opposite boundary.
            east=grid[2:,2:-1];west=grid[:-2,2:-1]
            north=grid[1:-1,3:];south=grid[1:-1,1:-2]
            alpha=np.sum((north-south)**2,axis=-1)
            gamma=np.sum((east-west)**2,axis=-1)
            denom=2*(alpha+gamma)
            target=(alpha[...,None]*(east+west)+gamma[...,None]*(north+south))/np.maximum(denom[...,None],1e-300)
            movement=target-grid[1:-1,2:-1]
            accepted_step=False
            for attempt in range(10):
                trial=grid.copy();trial[1:-1,2:-1]+=movement*(.5*(.5**attempt))
                if not np.isfinite(trial).all():continue
                quality=core_quality(trial)
                if quality['orientation']!=before['orientation'] or quality['min_scaled_jacobian']<before['min_scaled_jacobian']-1e-12:continue
                if quality['mean_angle_error_deg']>=current['mean_angle_error_deg']-1e-10:continue
                widths=np.linalg.norm(np.diff(trial,axis=1),axis=-1)
                if size_limit is not None and np.any(widths>size_limit*(1+1e-10)):continue
                if growth_limit is not None:
                    ratios=widths[:,1:]/widths[:,:-1]
                    if np.any(ratios>growth_limit*(1+1e-10)) or np.any(ratios<1-1e-10):continue
                grid=trial;current=quality;accepted+=1;accepted_step=True;break
            if not accepted_step:break
    if progress:progress(iterations,iterations)
    return grid,dict(before=before,after=current,accepted_steps=accepted,
        requested_steps=iterations,max_displacement_m=float(np.linalg.norm(grid-original,axis=-1).max()))
