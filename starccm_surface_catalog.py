"""Stable source identities shared by preview, heat table and Java generation."""
from collections import defaultdict
import numpy as np
from starccm_export_geometry import export_geometry,surface_signature


def surface_catalog(result,model,rod_mode='sectors_60'):
    _,domains=export_geometry(result,model)
    if not domains:return dict(domains=[],rods=[],sides=[])
    source={d['source_id']:d['number'] for d in domains}
    wall=defaultdict(list);side=defaultdict(list)
    for i,(sid,*_) in enumerate(result.instances_map):
        x,y=result.blocks[i];starts=result.wall_starts[i]
        arc=np.column_stack((x[:,0 if starts else -1],y[:,0 if starts else -1]))
        sub=model.subchannels[sid]
        rid=min(sub.rod_ids,key=lambda r:np.max(np.abs(np.linalg.norm(arc-np.array([model.rods[r].x,model.rods[r].y])*1e-3,axis=1)-model.rods[r].diameter*.5e-3)))
        wall[source[sid],rid].append(arc)
        midpoint=result.geom_data[i]['opposite'][-1]
        pairs=list(zip(sub.rod_ids,sub.rod_ids[1:]+sub.rod_ids[:1]))
        pair=min(pairs,key=lambda pair:np.linalg.norm((np.array([model.rods[pair[0]].x,model.rods[pair[0]].y])+np.array([model.rods[pair[1]].x,model.rods[pair[1]].y]))*.0005-midpoint))
        side[source[sid],*sorted(pair)].append(np.column_stack((x[-1],y[-1])))
    rods={}
    for (number,rid),lines in sorted(wall.items()):
        kind=model.rods[rid].rod_type
        stem={'fuel':'rod','guide':'guide','instrument':'instrument'}.get(kind,'wall')
        key=f's{number}_R{rid}' if rod_mode=='sectors_60' else (f'R{rid}' if rod_mode=='by_rod' else f's{number}')
        key=stem+'_'+key
        row=rods.setdefault(key,dict(id=key,kind=kind,sources=[],rod_ids=[],lines=[]))
        if number not in row['sources']:row['sources'].append(number)
        if rid not in row['rod_ids']:row['rod_ids'].append(rid)
        row['lines'].extend(line.tolist() for line in lines)
    sides=[];pair_counts=defaultdict(int);neighbors=defaultdict(list)
    original={d['number']:d['source_id'] for d in domains}
    for number,a,b in side:pair_counts[a,b]+=1;neighbors[a,b].append(number)
    for (number,a,b),lines in sorted(side.items()):
        area,cx,cy=surface_signature(lines,result.params.z_len)
        # Normal orientation comes from the source triangle center, not line order.
        centers=[d['center'] for d in domains if d['number']==number]
        a_center=np.array([model.rods[a].x,model.rods[a].y])*1e-3
        b_center=np.array([model.rods[b].x,model.rods[b].y])*1e-3
        tangent=b_center-a_center;tangent/=np.linalg.norm(tangent)
        normal=np.array([-tangent[1],tangent[0]])
        if np.dot(normal,np.array([cx,cy])-centers[0])<0:normal=-normal
        neighbor=next((n for n in neighbors[a,b] if n!=number),None)
        pair_id=f'S{min(original[number],original[neighbor])}_S{max(original[number],original[neighbor])}_R{a}_R{b}' if neighbor else None
        sides.append(dict(id=f'Side_s{number}_R{a}_R{b}',source=number,neighbor=neighbor,pair_id=pair_id,area=area*1e-6,
            center=[cx,cy],normal=normal.tolist(),shared=pair_counts[a,b]>1,
            lines=[line.tolist() for line in lines]))
    return dict(domains=[dict(number=d['number'],triangle=d['triangle'].tolist(),rods=[dict(center=[model.rods[r].x*1e-3,model.rods[r].y*1e-3],radius=model.rods[r].diameter*.5e-3) for r in model.subchannels[d['source_id']].rod_ids]) for d in domains],rods=list(rods.values()),sides=sides)


def validate_pairs(pairs,catalog):
    sides={row['id']:row for row in catalog['sides'] if not row['shared']};used=set()
    for pair in pairs:
        a,b=pair['first'],pair['second']
        if a==b or a not in sides or b not in sides:raise ValueError('Выберите две разные внешние граничные поверхности')
        if a in used or b in used:raise ValueError('Поверхность уже использована в другой паре')
        first,second=sides[a],sides[b]
        if abs(first['area']-second['area'])>max(first['area'],second['area'])*1e-5:raise ValueError('Площади выбранных поверхностей не совпадают')
        if np.dot(first['normal'],second['normal'])>-.999999:raise ValueError('Для выбранного сопряжения нужны противоположные параллельные нормали')
        delta=np.array(second['center'])-first['center']
        p=np.concatenate([np.array(line) for line in first['lines']])+delta
        q=np.concatenate([np.array(line) for line in second['lines']])
        # Endpoints/extents must agree after translation; matching node counts are not assumed.
        if np.max(np.abs(p.min(axis=0)-q.min(axis=0)))>1e-8 or np.max(np.abs(p.max(axis=0)-q.max(axis=0)))>1e-8:raise ValueError('Формы поверхностей не совпадают при переносе')
        if pair['kind']=='internal' and np.linalg.norm(delta)>1e-8:raise ValueError('Internal требует совпадающие поверхности; для переноса выберите Periodic')
        used.update((a,b))
    return pairs


def validate_surface_settings(result,model,options):
    workflow=options.get('workflow')
    if workflow is None:return None
    catalog=surface_catalog(result,model,options.get('rod_wall_mode','sectors_60'))
    if workflow.get('heat_enabled'):
        groups={r['id'] for r in catalog['rods'] if r['kind']=='fuel'}
        if not groups or set(workflow['heat_values'])!=groups:raise ValueError('Состав нагреваемых стенок изменился. Проверьте q для каждой группы ТВЭЛ')
        if not options.get('enable_thermal') and not options.get('use_iapws'):raise ValueError('Для нагрева ТВЭЛ включите уравнение энергии')
    disabled=workflow.get('disabled_internal_pairs',[])
    valid_internal={row['pair_id'] for row in catalog['sides'] if row['shared']}
    if len(disabled)!=len(set(disabled)) or set(disabled)-valid_internal:raise ValueError('Список внутренних интерфейсов не соответствует текущей сетке')
    if disabled and options.get('inter_fuse'):raise ValueError('При Fuse внутренние стыки объединяются; отключение отдельных интерфейсов недоступно')
    validate_pairs(workflow.get('boundary_pairs',[]),catalog)
    if workflow.get('tdc_enabled') and workflow.get('boundary_pairs'):raise ValueError('Боковые пары эталона TDC задаются контроллером. Удалите дополнительные пары')
    return catalog
