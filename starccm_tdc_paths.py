"""Side-by-side control-volume accounting; topology never implies equal exchange."""
from copy import deepcopy

METHODS={'boundary','reconstruct','report','unmeasured'}


def side_paths(catalog,workflow):
    rows={r['id']:r for r in catalog['sides']};paired={}
    for i,p in enumerate(workflow['boundary_pairs'],1):
        if p['first'] not in rows or p['second'] not in rows:continue
        for key,other in ((p['first'],p['second']),(p['second'],p['first'])):
            paired[key]=(p,other,i)
    bcs={r['surface']:r['kind'] for r in workflow['boundary_conditions']}
    disabled=set(workflow['disabled_internal_pairs']);result=[]
    for r in catalog['sides']:
        p=dict(id=r['id'],source=r['source'],neighbor=r['neighbor'],area=r['area'],normal=r['normal'],
               center=r['center'],connection=r['id'],kind='wall',default='zero',base=r['id'],interface='',partner=None)
        if r['id'] in paired:
            pair,other,index=paired[r['id']];p.update(connection='__'.join(sorted((r['id'],other))),neighbor=rows[other]['source'],
                kind='periodic' if pair['kind']!='internal' else 'interface',default='boundary',interface=f'SelectedInterface_{index}',partner=other)
        elif r['shared'] and r['pair_id'] not in disabled:
            p.update(connection=f'Gap_Sub{min(r["source"],r["neighbor"])}_Sub{max(r["source"],r["neighbor"])}',
                     kind='fuse' if catalog['fused'] else 'interface',default='unmeasured' if catalog['fused'] else 'boundary',
                     base=f'if_s{r["source"]}_s{r["neighbor"]}',interface='AUTO_INTERNAL')
            p['partner']=next(row['id'] for row in catalog['sides'] if row['source']==r['neighbor'] and row['neighbor']==r['source'] and row['pair_id']==r['pair_id'])
        elif bcs.get(r['id'],'wall')=='symmetry':p['kind']='symmetry'
        elif bcs.get(r['id'],'wall')!='wall':p.update(kind=bcs[r['id']],default='boundary')
        result.append(p)
    return result


def target_connections(paths,a,b):
    found={}
    for p in paths:
        if p['source']==a and p['neighbor']==b and p['default']!='zero':found[p['connection']]=dict(p)
    return sorted(found.values(),key=lambda p:(p['kind']!='fuse',p['connection']))


def account_paths(catalog,workflow,settings):
    paths=side_paths(catalog,workflow);candidates=target_connections(paths,settings['a'],settings['b'])
    target=settings['target'] or (settings['gaps'][0] if len(settings['gaps'])==1 else '')
    if not target:
        if not candidates:raise ValueError('Выберите соединение между A и B, допускающее обмен')
        target=candidates[0]['connection']
    chosen=next((p for p in candidates if p['connection']==target),None)
    if chosen is None:raise ValueError('Целевой зазор TDC устарел или не соединяет A и B')
    ids={p['id'] for p in paths}
    if (set(settings['path_methods'])|set(settings['path_reports']))-ids:raise ValueError('Список боковых поверхностей TDC устарел')
    selected=[]
    for p in paths:
        if p['source'] not in (settings['a'],settings['b']):continue
        p=dict(p);requested=settings['path_methods'].get(p['id'],p['default'])
        if p['connection']==target:
            p['method']='target'
        elif p['default']=='zero':
            if requested!='zero':raise ValueError(f'{p["id"]}: нулевой перенос задаётся граничным условием')
            p['method']='zero'
        else:
            if requested not in METHODS:raise ValueError(f'{p["id"]}: нельзя считать открытый путь нулевым')
            if requested=='boundary' and p['kind']=='fuse':raise ValueError(f'{p["id"]}: внутри Fuse нет Boundary Heat Flux; выберите реконструкцию или готовый отчёт')
            if requested=='reconstruct' and p['kind']!='fuse':raise ValueError('Реконструкция используется только для внутренних поверхностей Fuse')
            if requested=='unmeasured':raise ValueError(f'{p["id"]}: второй неизвестный перенос; задайте измерение или отчёт мощности, Вт')
            if requested=='reconstruct' and not settings['scalar_diffusion_confirmed']:
                raise ValueError('Для реконструкции подтвердите скалярное замыкание диффузии и необходимость проверки баланса')
            if requested=='report' and not settings['path_reports'].get(p['id']):raise ValueError(f'{p["id"]}: укажите знаковый отчёт полной мощности в Вт')
            p['method']=requested
        selected.append(p)
    for n in (settings['a'],settings['b']):
        if sum(p['method']=='target' and p['source']==n for p in selected)!=1:raise ValueError('На контрольный объём должен приходиться ровно один неизвестный целевой перенос')
    return chosen,selected,paths


def channel_labels(result,model,catalog,heat_values):
    """Selection follows original source/rod identities; q is not a temperature claim."""
    original=list(dict.fromkeys(row[0] for row in result.instances_map));out={}
    fuels=[r for r in catalog['rods'] if r['kind']=='fuel']
    kinds={'fuel':'ТВЭЛ','guide':'НК','instrument':'ИК'}
    for n,sid in enumerate(original,1):
        rods=[]
        for rid in model.subchannels[sid].rod_ids:
            rod=model.rods[rid];rods.append(f'R{rid}: {kinds.get(rod.rod_type,rod.rod_type)} Ø{rod.diameter:g} мм')
        q=[f'q{i}={heat_values.get(r["id"],0):g} Вт/м²' for i,r in enumerate(fuels,1) if n in r['sources']]
        out[n]=dict(title=f'Подканал {n} · S{sid} · '+', '.join(f'R{rid}' for rid in model.subchannels[sid].rod_ids),
                    details='; '.join(rods)+'\nНагрев: '+('; '.join(q) or 'не задан'))
    return out
