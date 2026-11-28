"""Bounded, strip-wise diagnostics for uniform axial extrusion; no full 3D cache."""
import heapq
import math
import numpy as np
from mesh_quality import extrude_blocks,cell_metrics

METRICS={
    'jacobian':dict(title='Якобиан формы',symbol='<',default=.2,minimum=0,maximum=1,unit=''),
    'angle':dict(title='Отклонение углов от 90°',symbol='>',default=30.,minimum=0,maximum=90,unit='°'),
    'aspect':dict(title='Пропорции в сечении',symbol='>',default=5.,minimum=1,maximum=1e6,unit=''),
    'transition':dict(title='Перепад объёмов внутри блока',symbol='>',default=2.,minimum=1,maximum=1e6,unit=''),
}


def _ratios(volumes):
    ratios=np.ones_like(volumes)
    for axis in (0,1):
        a=[slice(None),slice(None)];b=a.copy();a[axis]=slice(None,-1);b[axis]=slice(1,None)
        aa,bb=np.abs(volumes[tuple(a)]),np.abs(volumes[tuple(b)])
        with np.errstate(divide='ignore',invalid='ignore'):pair=np.maximum(aa/bb,bb/aa)
        pair=np.where(np.isfinite(pair),pair,np.inf)
        ratios[tuple(a)]=np.maximum(ratios[tuple(a)],pair);ratios[tuple(b)]=np.maximum(ratios[tuple(b)],pair)
    return ratios


def diagnose(result,metric,threshold,limit=2000,chunk_cells=10000,progress=None):
    if metric not in METRICS:raise ValueError('Неизвестная метрика подсветки')
    spec=METRICS[metric]
    if not math.isfinite(threshold) or not spec['minimum']<=threshold<=spec['maximum']:raise ValueError('Неверный порог подсветки')
    if type(limit) is not int or not 1<=limit<=5000 or type(chunk_cells) is not int or chunk_cells<1:raise ValueError('Неверный лимит диагностики')
    dz=result.params.z_len/result.params.nz
    if not math.isfinite(dz) or dz<=0:raise ValueError('Неверный осевой шаг')
    total=sum((x.shape[0]-1)*(x.shape[1]-1) for x,y in result.blocks)
    if not total:raise ValueError('Нет ячеек для диагностики')
    heap=[];scanned=bad_count=invalid_count=serial=0
    minimum=maximum=None
    for block,(x,y) in enumerate(result.blocks):
        if x.shape!=y.shape or min(x.shape)<2:raise ValueError('Неверная форма блока')
        ni,nj=x.shape;rows=max(1,chunk_cells//(nj-1))
        for start in range(0,ni-1,rows):
            stop=min(start+rows,ni-1);lo=max(0,start-1);hi=min(ni,stop+2)
            if progress:progress(int(5+90*scanned/total),f'Диагностика: блок {block+1}/{len(result.blocks)}')
            # One axial slab is sufficient for the current uniform, untwisted extrusion.
            raw=cell_metrics(extrude_blocks([(x[lo:hi],y[lo:hi])],[0,dz])[0])
            cut=slice(start-lo,stop-lo)
            volume=raw['volume'][:,:,0]
            with np.errstate(divide='ignore',invalid='ignore'):
                aspect=np.maximum(raw['length_i'][:,:,0]/raw['length_j'][:,:,0],raw['length_j'][:,:,0]/raw['length_i'][:,:,0])
            values=dict(jacobian=raw['scaled_jacobian'][:,:,0][cut],angle=raw['skewness'][:,:,0][cut]*90,
                        aspect=aspect[cut],transition=_ratios(volume)[cut],volume=volume[cut])
            value=values[metric]
            invalid=(~np.isfinite(values['jacobian'])) | (values['jacobian']<=0) | (~np.isfinite(values['volume'])) | (values['volume']<=0)
            bad=invalid | (~np.isfinite(value)) | ((value<threshold) if metric=='jacobian' else (value>threshold))
            bad_count+=int(bad.sum());invalid_count+=int(invalid.sum());scanned+=value.size
            finite=value[np.isfinite(value)]
            if finite.size:
                vmin,vmax=float(finite.min()),float(finite.max())
                minimum=vmin if minimum is None else min(minimum,vmin);maximum=vmax if maximum is None else max(maximum,vmax)
            priority=np.where(invalid | ~np.isfinite(value),np.inf,threshold-value if metric=='jacobian' else value-threshold)
            indices=np.flatnonzero(bad)
            if len(heap)==limit:indices=indices[priority.flat[indices]>heap[0][0]]
            if indices.size>limit:indices=indices[np.argpartition(priority.flat[indices],-limit)[-limit:]]
            for index in indices:
                ii,j=np.unravel_index(index,value.shape);i=start+int(ii);j=int(j)
                record=dict(block=block,i=i,j=j,normal_cell=j+1 if result.wall_starts[block] else nj-1-j,
                    corners=[[float(x[a,b]),float(y[a,b])] for a,b in ((i,j),(i+1,j),(i+1,j+1),(i,j+1))],
                    metrics={k:float(v[ii,j]) for k,v in values.items()})
                serial+=1;item=(float(priority[ii,j]),serial,record)
                if len(heap)<limit:heapq.heappush(heap,item)
                elif item[0]>heap[0][0]:heapq.heapreplace(heap,item)
    if progress:progress(96,'Подготовка подсветки')
    return dict(metric=metric,threshold=threshold,total=total,bad=bad_count,invalid=invalid_count,
                minimum=minimum,maximum=maximum,records=[record for _,_,record in sorted(heap,reverse=True)],limit=limit)


def describe(data,nz):
    spec=METRICS[data['metric']]
    return (f'ПОДСВЕТКА: {spec["title"]} {spec["symbol"]} {data["threshold"]:g}{spec["unit"]}\n'
            f'Ячеек в сечении: {data["total"]:,}; отмечено: {data["bad"]:,}; невалидных: {data["invalid"]:,}.\n'
            f'Показаны {len(data["records"]):,} худших (лимит {data["limit"]:,}). Каждая соответствует {nz} осевым ячейкам.\n'
            'Нажмите подсвеченную ячейку для подробностей. Метрики относятся к текущей геометрии, не к CFD-решению.\n'
            'Пропорции — в плоскости; вытянутый пристеночный слой допустим. Перепад объёмов проверяется только внутри блоков.')
