"""Versioned bundle-project JSON: validated parameters, never mesh/solver results."""
from dataclasses import asdict,dataclass
from copy import deepcopy
from pathlib import Path
import json,math,os,tempfile
from bundle_geometry import BundleModel
from block_classifier import classify_subchannel_blocks
from mesh_core import MeshParams,UNITS
from mesh_project import merge_project_inputs
from starccm_export_profile import validate_options
from yplus_calculator import FLUID_MODES
from fluid_properties import GAS_PRESETS

FORMAT='meshBuilder-bundle-project'
VERSION=1
CALCULATOR_KEYS={'conductivity_model','fluid_mode','gas','temp_c','press_mpa','density','dyn_vis','re','vel','flow','yplus','flow_mode'}
CORE_DEFAULTS=dict(mode='controlled_growth',core_transition=1.1,core_growth=1.1,core_max_size=120e-6,core_max_cells=5000,core_layers=20,mesh_lines=True,core_lines=False,center='equi_clearance',unit='мкм')

class BundleProjectError(ValueError):pass

def keys(obj,expected,label):
    if not isinstance(obj,dict) or set(obj)!=set(expected):raise BundleProjectError(f'{label}: неверный набор полей')

def number(value,label,lo,hi):
    if type(value) not in (int,float) or not math.isfinite(value) or not lo<=value<=hi:raise BundleProjectError(f'{label}: требуется число {lo:g}…{hi:g}')

def integer(value,label,lo,hi):
    if type(value) is not int or not lo<=value<=hi:raise BundleProjectError(f'{label}: требуется целое {lo}…{hi}')

def params(data):
    defaults=asdict(MeshParams());keys(data,defaults,'Параметры сетки')
    for k,v in data.items():
        if type(defaults[k]) is float:
            if type(v) not in (int,float) or not math.isfinite(v):raise BundleProjectError(f'{k}: требуется конечное число')
        elif type(v) is not type(defaults[k]):raise BundleProjectError(f'{k}: неверный тип')
    p=MeshParams(**data);p.validate()
    if p.law not in ('geometric','tanh','sinh','power','uniform','wall_core'):raise BundleProjectError('Закон не поддерживается конструктором')
    if not p.full:raise BundleProjectError('Конструктор сохраняет полное сечение блока')
    for name in ('h1','hmax','z_len','layer_thickness'):number(getattr(p,name),name,1e-18,1000)
    number(p.layer_growth,'Рост слоя',1,100)
    for name,lo,hi in (('ni',2,5000),('nj',3,5001),('nz',1,1000000),('wall_layers',2,5000)):
        integer(getattr(p,name),name,lo,hi)
    return p

def geometry(model):
    return dict(lattice=dict(s_flat=model.s_flat,pitch=model.pitch,d_fuel=model.d_fuel,d_guide=model.d_guide,d_instrument=model.d_instrument),
        rod_types=[dict(q=q,r=r,type=t) for (q,r),t in sorted(model.user_rod_types.items())],
        rod_diameters=[dict(q=q,r=r,diameter=d) for (q,r),d in sorted(model.user_custom_diameters.items())],
        deleted=[list(c) for c in sorted(model.user_deleted_coords)],auto_deleted=[list(c) for c in sorted(model.auto_deleted_clash_coords)],
        selected=[dict(id=sid,rods=sorted([list((model.rods[r].q,model.rods[r].r)) for r in model.subchannels[sid].rod_ids])) for sid in sorted(model.selected_subchannels)])

def restore_geometry(data):
    keys(data,('lattice','rod_types','rod_diameters','deleted','auto_deleted','selected'),'Геометрия')
    lat=data['lattice'];keys(lat,('s_flat','pitch','d_fuel','d_guide','d_instrument'),'Решётка')
    number(lat['s_flat'],'Размер сборки',15,300)
    number(lat['pitch'],'Шаг решётки',5,50)
    for k in ('d_fuel','d_guide','d_instrument'):number(lat[k],k,2,40)
    if lat['pitch']<=lat['d_fuel']:raise BundleProjectError('Шаг должен быть больше диаметра ТВЭЛа')
    for name in ('rod_types','rod_diameters','deleted','auto_deleted','selected'):
        if not isinstance(data[name],list):raise BundleProjectError(f'{name}: требуется список')
    def coord(q,r):
        integer(q,'q',-1000,1000);integer(r,'r',-1000,1000);return q,r
    model=BundleModel(**lat)
    for name in ('deleted','auto_deleted'):
        values=[]
        for pair in data[name]:
            if not isinstance(pair,list) or len(pair)!=2:raise BundleProjectError('Неверные координаты стержня')
            values.append(coord(*pair))
        if len(values)!=len(set(values)):raise BundleProjectError('Повторяющиеся/недоступные координаты стержней')
        setattr(model,'user_deleted_coords' if name=='deleted' else 'auto_deleted_clash_coords',set(values))
    for name,mapping in (('rod_types',model.user_rod_types),('rod_diameters',model.user_custom_diameters)):
        field='type' if name=='rod_types' else 'diameter'
        for row in data[name]:
            keys(row,('q','r',field),name);c=coord(row['q'],row['r'])
            if c in mapping:raise BundleProjectError('Повторяющийся/недоступный стержень')
            value=row[field]
            if field=='type':
                if value not in ('fuel','guide','instrument'):raise BundleProjectError('Неизвестный тип стержня')
            else:number(value,'Диаметр стержня',.01,100)
            mapping[c]=value
    model.update_geometry()
    selected=[]
    for row in data['selected']:
        keys(row,('id','rods'),'Выбранный подканал')
        sid=row['id']
        if type(sid) is not int or sid not in model.subchannels or sid in selected:raise BundleProjectError('Недоступный/повторяющийся подканал')
        expected=sorted([list((model.rods[r].q,model.rods[r].r)) for r in model.subchannels[sid].rod_ids])
        if row['rods']!=expected:raise BundleProjectError('Изменилась идентичность подканала; выберите его заново')
        selected.append(sid)
    model.selected_subchannels=set(selected)
    return model


def bindings(model):
    templates,instances=classify_subchannel_blocks(model,selected_sub_ids=sorted(model.selected_subchannels))
    return ({str(k):list(t.signature) for k,t in templates.items()},
            {str(i.global_block_id):[i.subchannel_id,i.block_index,i.rod_id,i.neighbor_rod_id] for i in instances})

@dataclass
class BundleProject:
    data:dict
    model:BundleModel
    base:MeshParams
    templates:dict
    blocks:dict
    legacy:bool=False


def validate_project(data):
    keys(data,('format','version','geometry','mesh','calculator','export','view'),'Проект')
    if data['format']!=FORMAT or type(data['version']) is not int or data['version']!=VERSION:raise BundleProjectError('Неизвестный формат или версия проекта')
    model=restore_geometry(data['geometry'])
    mesh=data['mesh'];keys(mesh,('base','templates','blocks','core'),'Сетка');base=params(mesh['base'])
    tbind,bbind=bindings(model)
    def overrides(raw,expected):
        if not isinstance(raw,dict):raise BundleProjectError('Неверные переопределения')
        result={}
        for key,row in raw.items():
            keys(row,('binding','params'),'Переопределение')
            if key not in expected or row['binding']!=expected[key]:raise BundleProjectError('Переопределение не соответствует геометрии; перепривязка запрещена')
            p=params(row['params'])
            if (p.z_len,p.nz)!=(base.z_len,base.nz):raise BundleProjectError('Высота и nz должны быть общими')
            result[int(key)]=p
        return result
    templates=overrides(mesh['templates'],tbind);blocks=overrides(mesh['blocks'],bbind)
    core=mesh['core'];keys(core,CORE_DEFAULTS,'Ядро')
    if core['mode'] not in ('controlled_growth','aspect_alignment','fixed_count') or core['center'] not in ('equi_clearance','centroid') or core['unit'] not in UNITS:raise BundleProjectError('Неизвестная настройка ядра/единиц')
    for name in ('mesh_lines','core_lines'):
        if type(core[name]) is not bool:raise BundleProjectError('Неверная форма линий')
    for name,lo,hi in (('core_transition',.1,10),('core_growth',1,100),('core_max_size',1e-18,1000)):
        number(core[name],name,lo,hi)
    integer(core['core_layers'],'Число слоёв ядра',1,500);integer(core['core_max_cells'],'Лимит слоёв ядра',1,100000)
    cal=data['calculator']
    if not isinstance(cal,dict) or set(cal)-CALCULATOR_KEYS or any(type(v) is not str or len(v)>256 for v in cal.values()):raise BundleProjectError('Неверные настройки калькулятора')
    for name,choices in (('fluid_mode',FLUID_MODES),('gas',GAS_PRESETS),('flow_mode',('reynolds','velocity','flow_rate')),('conductivity_model',('background','full'))):
        if name in cal and cal[name] not in choices:raise BundleProjectError('Неизвестная настройка калькулятора: '+name)
    if data['export'] is not None:validate_options(data['export'])
    view=data['view'];keys(view,('scope','template','block','tab','detail','geometry_inputs'),'Вид')
    if view['scope'] not in ('all','template','block'):raise BundleProjectError('Неизвестная область редактирования')
    for name,expected in (('template',tbind),('block',bbind)):
        if view[name] is not None and (type(view[name]) is not int or str(view[name]) not in expected):raise BundleProjectError('Недоступный редактор блока/шаблона')
    if view['scope']!='all' and view[view['scope']] is None:raise BundleProjectError('Не выбран объект редактирования')
    inputs=view['geometry_inputs']
    if not isinstance(inputs,list) or len(inputs)!=5:raise BundleProjectError('Неверные поля геометрии')
    for value,(lo,hi) in zip(inputs,((15,300),(5,50),(2,40),(2,40),(2,40))):number(value,'Поле геометрии',lo,hi)
    integer(view['tab'],'Вкладка',0,2)
    if type(view['detail']) is not int or view['detail'] not in (1,2,4,10):raise BundleProjectError('Неизвестная детализация')
    return BundleProject(deepcopy(data),model,base,templates,blocks)


def commit_active_inputs(owner):
    p=owner.mesh_subpanel
    from PySide6.QtCore import QSignalBlocker
    for widget in owner.geometry_controls():
        if not widget.hasAcceptableInput():raise BundleProjectError('Проверьте ввод геометрии')
        with QSignalBlocker(widget):widget.interpretText()
    if p.current_law()=='wall_core':
        name='core_layers' if p.combo_core_mode.currentData()=='fixed_count' else 'core_max_cells'
        if not p.fields[name].hasAcceptableInput():raise BundleProjectError('Проверьте число слоёв ядра')
        with QSignalBlocker(p.fields[name]):p.fields[name].interpretText()
    current=p.read_params()
    original=owner.base_params
    if p.scope_mode=='template':original=owner.template_configs.get(p.combo_templates.currentData(),original)
    elif p.scope_mode=='block':
        gid=p.combo_blocks.currentData();original=owner.block_custom_configs.get(gid,owner.template_configs.get(owner.get_template_for_block(gid),original))
    merged=merge_project_inputs(original,current)
    p.sync_global_axial(merged)
    if p.scope_mode=='all':owner.base_params=merged
    elif p.scope_mode=='template' and p.combo_templates.currentData() is not None:owner.template_configs[p.combo_templates.currentData()]=merged
    elif p.scope_mode=='block' and p.combo_blocks.currentData() is not None:owner.block_custom_configs[p.combo_blocks.currentData()]=merged
    owner.validate_mesh_inputs()
    p.update_tree_status()


def capture_project(owner):
    commit_active_inputs(owner)
    p=owner.mesh_subpanel
    tb,bb=bindings(owner.model)
    def encode(mapping,bind):
        if any(str(k) not in bind for k in mapping):raise BundleProjectError('Есть переопределения для прежней геометрии. Сбросьте их перед сохранением.')
        return {str(k):dict(binding=bind[str(k)],params=asdict(v)) for k,v in mapping.items()}
    core={k:p.fields[k].value() for k in CORE_DEFAULTS if k.startswith('core_') and k!='core_lines'}
    core.update(mode=p.combo_core_mode.currentData(),mesh_lines=bool(p.combo_mesh_lines.currentData()),
        core_lines=bool(p.combo_core_lines.currentData()) if p.combo_core_mode.currentData()=='fixed_count' else bool(getattr(p,'_fixed_core_line_index',0)),
        center=p.combo_center_method.currentData(),unit=p.cell_unit)
    view=dict(scope=p.scope_mode,template=p.combo_templates.currentData(),block=p.combo_blocks.currentData(),tab=owner.tabs.currentIndex(),detail=owner.combo_detail.currentData(),geometry_inputs=[w.value() for w in owner.geometry_controls()])
    # Geometry view may not have populated block editors yet.
    if not tb:view.update(scope='all',template=None,block=None)
    data=dict(format=FORMAT,version=VERSION,geometry=geometry(owner.model),mesh=dict(base=asdict(owner.base_params),templates=encode(owner.template_configs,tb),blocks=encode(owner.block_custom_configs,bb),core=core),
        calculator=deepcopy(p.yplus_saved_state),export=deepcopy(getattr(owner,'star_export_options',None)),view=view)
    return validate_project(data)


def save_project(project,path):
    valid=validate_project(project.data)
    text=json.dumps(valid.data,ensure_ascii=False,allow_nan=False,indent=2)+'\n'
    target=Path(path);fd,tmp=tempfile.mkstemp(prefix='.'+target.name+'.',suffix='.tmp',dir=target.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as stream:stream.write(text)
        os.replace(tmp,target)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)


def legacy_project(data):
    if data.get('format')!='bundle-cross-section' or data.get('version')!=3:raise BundleProjectError('Неизвестный формат сечения')
    lat=data['lattice']
    if lat.get('type')!='triangular':raise BundleProjectError('Поддерживается треугольная решётка')
    g=dict(lattice=dict(s_flat=lat['s_across_flats_mm'],pitch=lat['pitch_mm'],d_fuel=lat['default_d_fuel_mm'],d_guide=lat['default_d_guide_mm'],d_instrument=lat.get('default_d_instrument_mm',10.3)),
           rod_types=[],rod_diameters=[],deleted=data.get('user_deleted_coords',[]),auto_deleted=[],selected=[])
    old_rods={r['rod_id']:[r['q'],r['r']] for r in data['rods']}
    g['selected']=[dict(id=s['subchannel_id'],rods=sorted(old_rods[r] for r in s['rod_ids'])) for s in data['subchannels']]
    for rod in data['rods']:
        g['rod_types'].append(dict(q=rod['q'],r=rod['r'],type=rod['type']))
        if rod.get('custom_diameter'):g['rod_diameters'].append(dict(q=rod['q'],r=rod['r'],diameter=rod['diameter_mm']))
    result=validate_project(dict(format=FORMAT,version=VERSION,geometry=g,mesh=dict(base=asdict(MeshParams(law='geometric',mode='first_count',h1=2.5e-6,nj=100)),templates={},blocks={},core=CORE_DEFAULTS.copy()),calculator={},export=None,view=dict(scope='all',template=None,block=None,tab=0,detail=1,geometry_inputs=list(g['lattice'].values()))))
    result.legacy=True
    return result


def load_project(path):
    def pairs(rows):
        obj={}
        for k,v in rows:
            if k in obj:raise BundleProjectError('Повторяющееся поле JSON: '+k)
            obj[k]=v
        return obj
    def constant(token):raise BundleProjectError('Неконечное число JSON: '+token)
    try:
        if Path(path).stat().st_size>16*1024*1024:raise BundleProjectError('Файл проекта больше 16 МиБ')
        data=json.loads(Path(path).read_text(encoding='utf-8-sig'),object_pairs_hook=pairs,parse_constant=constant)
        if not isinstance(data,dict):raise BundleProjectError('Требуется JSON-объект')
        return validate_project(data) if data.get('format')==FORMAT else legacy_project(data)
    except (KeyError,TypeError,ValueError,OverflowError,RecursionError) as exc:
        raise BundleProjectError(str(exc)) from exc
