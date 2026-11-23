"""Allocation-light shape/resource forecasts; bounds are not a mesh validity check."""
import numpy as np
import math
import mesh_core as mc
from block_classifier import classify_subchannel_blocks


def resource_range(shapes,nz):
    """Shapes: (ni,nj_min,nj_max). Counts include duplicate interface nodes."""
    cells=[sum((ni-1)*(nj-1)*nz for ni,lo,hi in shapes for nj in [(lo,hi)[end]]) for end in (0,1)]
    points=[sum(ni*nj*(nz+1) for ni,lo,hi in shapes for nj in [(lo,hi)[end]]) for end in (0,1)]
    # .16e finite double + separator: 23..25 ASCII bytes per coordinate.
    header=32*(len(shapes)+1)
    return dict(cells=tuple(cells),block_points=tuple(points),
                coordinates_3d=tuple(n*24 for n in points),
                xyz_bytes=(points[0]*3*23,points[1]*3*25+header),
                quality_memory_hint=(points[0]*24+cells[0]*600,points[1]*24+cells[1]*2000))


def forecast(model,base,templates,overrides,core,layer=None,progress=None):
    base.validate()
    if core['mode'] not in ('controlled_growth','aspect_alignment','fixed_count'):raise ValueError('Неизвестный режим ядра')
    for key in ('limit','layers'):
        if type(core[key]) is not int or core[key]<1:raise ValueError('Лимит/число слоёв должны быть положительными целыми')
    if any(not math.isfinite(core[k]) or core[k]<=0 for k in ('growth','size','transition')) or core['growth']<1:raise ValueError('Неверные параметры ядра')
    if progress:progress(5,'Подсчёт блоков и разбиений')
    _,instances=classify_subchannel_blocks(model,selected_sub_ids=sorted(model.selected_subchannels))
    if not instances:raise ValueError('Выберите внутренние треугольные подканалы')
    specs=[];local_settings=[]
    from bundle_local_core import inherited_settings
    for inst in instances:
        p=overrides.get((inst.subchannel_id,inst.block_index),overrides.get(inst.global_block_id,templates.get(inst.template_id,base)))
        p.validate()
        if (p.nz,p.z_len)!=(base.nz,base.z_len):raise ValueError('Переопределения должны сохранять общие ni, nz и высоту')
        specs.append(p)
        local_settings.append(inherited_settings(base,templates.get(inst.template_id),overrides.get((inst.subchannel_id,inst.block_index),overrides.get(inst.global_block_id))))
    notes=['Числа условны: при несовместимых стыках/параметрах построение может быть отклонено.',
           'Прогноз использует применённую геометрию, без построения массивов 3D.']
    layer_shapes=None
    if any(p.law=='wall_core' for p in specs):
        layer_shapes=[(p.ni,p.wall_layers+1,p.wall_layers+1) if p.law=='wall_core' else (p.ni,p.nj,p.nj) for p in specs]
        from bundle_local_core import settings
        groups={}
        for i,p in enumerate(specs):
            if p.law!='wall_core':continue
            local=local_settings[i]
            cfg=dict(mode=local.get('core_mode',core['mode']),growth=local.get('growth',core['growth']),size=local.get('max_size',core['size']),limit=local.get('max_cells',core['limit']),layers=local.get('core_layers',core['layers']),transition=local.get('transition_ratio',core['transition']))
            groups.setdefault((p.ni,tuple(sorted(cfg.items()))),[]).append(i)
        ranges={}
        for (_,items),indices in groups.items():
            cfg=dict(items)
            if cfg['mode']=='fixed_count':nlo=nhi=cfg['layers']
            elif layer is not None:
                remaining=[];last=[]
                if len(layer.blocks)!=len(specs):raise ValueError('Слой не соответствует выбранным блокам')
                for i in indices:
                    g=layer.geom_data[i]
                    front=g['arc']+g['layer_thickness']*g['direction']/g['lengths'][:,None]
                    remaining.append(np.linalg.norm(g['opposite']-front,axis=1));last.append(layer.all_block_widths[i][:,-1])
                nlo,nhi=mc.controlled_distribution(np.concatenate(remaining),np.concatenate(last),cfg['growth'],cfg['size'],cfg['limit'],cfg['transition'],count_only=True)
                if cfg['mode']=='controlled_growth':nhi=nlo
            else:nlo,nhi=1,cfg['limit']
            for i in indices:ranges[i]=(nlo,nhi)
        shapes=[]
        for i,p in enumerate(specs):
            if p.law=='wall_core':lo,hi=p.wall_layers+ranges[i][0]+1,p.wall_layers+ranges[i][1]+1
            elif p.mode in ('first_count','shape_count'):lo=hi=p.nj
            else:lo,hi=mc.minimum_count(p)+1,p.max_auto_cells+1
            shapes.append((p.ni,lo,hi))
            if p.law!='wall_core':layer_shapes[i]=(p.ni,lo,hi)
        notes.append('Ядро оценивается по локальным настройкам групп. Автоматический диапазон уточняется после построения слоя; 1:1 может выбирать N внутри диапазона.')
    else:
        shapes=[]
        for p in specs:
            if p.mode in ('first_count','shape_count'):lo=hi=p.nj-1
            else:lo,hi=mc.minimum_count(p),p.max_auto_cells
            shapes.append((p.ni,lo+1,hi+1))
        if any(lo!=hi for _,lo,hi in shapes):notes.append('Автоматическое число узлов: диапазон ограничен внутренним лимитом, не является точным прогнозом выбранного N.')
    if progress:progress(90,'Оценка памяти и файла Plot3D')
    supported=len({i.subchannel_id for i in instances})
    return dict(blocks=len(specs),supported=supported,skipped=len(model.selected_subchannels)-supported,
                full=resource_range(shapes,base.nz),layer=resource_range(layer_shapes,base.nz) if layer_shapes else None,
                exact=all(lo==hi for _,lo,hi in shapes),notes=notes)


def size_text(value):
    for unit in ('Б','КиБ','МиБ','ГиБ','ТиБ','ПиБ'):
        if value<1024:return f'{value:.1f} {unit}'
        value/=1024
    return f'{value:.1f} ЭиБ'


def format_forecast(data):
    r=data['full']
    def count(pair):return f'{pair[0]:,}' if pair[0]==pair[1] else f'{pair[0]:,} … {pair[1]:,}'
    def size(pair):return f'{size_text(pair[0])} … {size_text(pair[1])}'
    rows=['ПРОГНОЗ СЕТКИ — '+('число ячеек определено' if data['exact'] else 'диапазон, не точное число'),
          f'Подканалы: {data["supported"]}; блоки: {data["blocks"]}; пропущено периферийных: {data["skipped"]}.']
    if data['layer']:rows.append('Только пристеночный слой, ячеек 3D: '+count(data['layer']['cells']))
    rows += ['После заполнения / полная сетка, ячеек 3D: '+count(r['cells']),
             'Узлов блоков (включая дубликаты стыков): '+count(r['block_points']),
             'Только массивы координат 3D: '+size(r['coordinates_3d']),
             'Файл XYZ (ASCII), оценка: '+size(r['xyz_bytes']),
             'Память проверки качества, грубый ориентир: '+size(r['quality_memory_hint']),
             'Память — эвристика, не гарантия пика; GUI/библиотеки и другие процессы не учтены.']
    return '\n'.join(rows+data['notes'])
