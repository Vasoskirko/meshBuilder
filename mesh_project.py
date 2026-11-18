from dataclasses import asdict, dataclass, replace
from pathlib import Path
import json, math, os, tempfile
from mesh_core import MeshParams, UNITS, migrate_layer_values
FORMAT="mesh-generator-project"
VERSION=1
TARGETS=("full_distribution","layer_only","layer_and_core")
GEOMETRY_KEYS=("d_rod","pitch","z_len","ni","nz","full")
DEFAULT_PARAMS=asdict(MeshParams())
DISTRIBUTION_KEYS=tuple(k for k in DEFAULT_PARAMS if k not in GEOMETRY_KEYS and k!="filename")
class ProjectError(ValueError):pass

def _keys(data,required,name,optional=()):
    if not isinstance(data,dict):raise ProjectError(f"{name}: требуется JSON-объект")
    missing=set(required)-data.keys();extra=data.keys()-set(required)-set(optional)
    if missing:raise ProjectError(f"{name}: отсутствуют поля {', '.join(sorted(missing))}")
    if extra:raise ProjectError(f"{name}: неизвестные поля {', '.join(sorted(extra))}")

def _finite(value,name):
    if type(value) not in (float,int):raise ProjectError(f"{name}: требуется число, не строка или логическое значение")
    try:valid=math.isfinite(value)
    except OverflowError:valid=False
    if not valid:raise ProjectError(f"{name}: требуется конечное число")

def _params(values):
    _keys(values,(),"parameters",DEFAULT_PARAMS)
    for k,v in values.items():
        if type(DEFAULT_PARAMS[k]) is float:_finite(v,k)
        elif type(v) is not type(DEFAULT_PARAMS[k]):raise ProjectError(f"{k}: неверный тип значения")
    try:p=MeshParams(**values);p.validate()
    except (ValueError,TypeError,OverflowError) as exc:raise ProjectError(f"Параметры сетки: {exc}") from exc
    return p

@dataclass(frozen=True)
class ProjectCore:
    growth:float=1.1
    max_size:float=30e-6
    max_cells:int=5000
    def validate(self):
        _finite(self.growth,"core.growth");_finite(self.max_size,"core.max_size")
        if self.growth<1 or self.max_size<=0:raise ProjectError("Недопустимый рост или размер ядра")
        if type(self.max_cells) is not int or self.max_cells<1:raise ProjectError("core.max_cells: требуется положительное целое число")
    @classmethod
    def from_runtime(cls,core):
        try:c=cls(core.growth,core.max_size,core.max_cells)
        except AttributeError as exc:raise ProjectError("Неизвестная структура параметров ядра") from exc
        c.validate();return c

@dataclass(frozen=True)
class MeshProject:
    params:MeshParams
    core:ProjectCore|None=None
    build_target:str="full_distribution"
    geometry_unit:str="мм"
    cell_unit:str="мкм"
    def validate(self):
        if not isinstance(self.params,MeshParams):raise ProjectError("params: требуется MeshParams")
        _params(asdict(self.params))
        for value in (self.geometry_unit,self.cell_unit):
            if type(value) is not str or value not in UNITS:raise ProjectError("Неизвестная единица")
        if type(self.build_target) is not str or self.build_target not in TARGETS:raise ProjectError("Неизвестная цель построения")
        if (self.build_target=="full_distribution")== (self.params.law=="wall_core"):raise ProjectError("Цель не соответствует закону")
        if self.core is not None:
            if not isinstance(self.core,ProjectCore):raise ProjectError("core: требуется ProjectCore")
            self.core.validate()
        if self.build_target=="layer_and_core" and self.core is None:raise ProjectError("Для layer_and_core нужны явные параметры ядра")

@dataclass(frozen=True)
class ProjectLoad:
    project:MeshProject
    source_format:str
    notes:tuple=()

def project_to_dict(project):
    project.validate();p=asdict(project.params)
    return {"format":FORMAT,"version":VERSION,"build_target":project.build_target,
            "units":{"geometry":project.geometry_unit,"cells":project.cell_unit},
            "geometry":{k:p[k] for k in GEOMETRY_KEYS},"distribution":{k:p[k] for k in DISTRIBUTION_KEYS},
            "core":None if project.core is None else asdict(project.core),"export":{"filename":p["filename"]}}

def project_from_dict(data):
    if not isinstance(data,dict):raise ProjectError("project: требуется JSON-объект")
    if "format" in data:
        _keys(data,("format","version","build_target","units","geometry","distribution","core","export"),"project")
        if data["format"]!=FORMAT or type(data["version"]) is not int or data["version"]!=1:raise ProjectError("Неизвестный формат или версия проекта")
        _keys(data["units"],("geometry","cells"),"units");_keys(data["geometry"],GEOMETRY_KEYS,"geometry")
        _keys(data["distribution"],DISTRIBUTION_KEYS,"distribution");_keys(data["export"],("filename",),"export")
        core=None
        if data["core"] is not None:
            _keys(data["core"],("growth","max_size","max_cells"),"core");core=ProjectCore(**data["core"])
        project=MeshProject(_params({**data["geometry"],**data["distribution"],**data["export"]}),core,data["build_target"],data["units"]["geometry"],data["units"]["cells"])
        project.validate();return ProjectLoad(project,FORMAT)
    if data.get("module")=="core_fill":raise ProjectError("Это CLI-отчёт .core.json, не проект")
    _keys(data,("version","parameters"),"legacy",("geometry_unit","cell_unit","unit","resolved_parameters"))
    version=data["version"]
    if type(version) is not int or version not in range(2,8):raise ProjectError("Неподдерживаемая версия настроек")
    _keys(data["parameters"],(),"parameters",DEFAULT_PARAMS)
    values=dict(data["parameters"])
    for k,v in values.items():
        if type(DEFAULT_PARAMS[k]) is float:_finite(v,k)
        elif type(v) is not type(DEFAULT_PARAMS[k]):raise ProjectError(f"{k}: неверный тип значения")
    if version<4:values["smoothing"]="manual"
    try:values=migrate_layer_values(values,version)
    except (ValueError,TypeError,OverflowError) as exc:raise ProjectError(f"Миграция: {exc}") from exc
    p=_params(values);target="layer_only" if p.law=="wall_core" else "full_distribution"
    project=MeshProject(p,None,target,data.get("geometry_unit",data.get("unit","мм")),data.get("cell_unit",data.get("unit","мкм")))
    project.validate();notes=[f"Импортированы старые настройки версии {version}; источник не изменён."]
    if p.law=="wall_core":notes.append("Параметры ядра отсутствуют. Импортирована цель «только слой».")
    if "resolved_parameters" in data:notes.append("resolved_parameters не используются: сетку нужно построить заново.")
    return ProjectLoad(project,f"legacy-v{version}",tuple(notes))

def _pairs(pairs):
    d={}
    for k,v in pairs:
        if k in d:raise ProjectError(f"Повторяющийся ключ: {k}")
        d[k]=v
    return d

def _constant(token):raise ProjectError(f"Недопустимая константа: {token}")

def load_project_info(filename):
    try:data=json.loads(Path(filename).read_text(encoding="utf-8-sig"),object_pairs_hook=_pairs,parse_constant=_constant)
    except (json.JSONDecodeError,UnicodeError,RecursionError) as exc:raise ProjectError(f"Ошибка чтения JSON: {exc}") from exc
    return project_from_dict(data)

def load_project(filename):return load_project_info(filename).project

def save_project(project,filename):
    text=json.dumps(project_to_dict(project),ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    target=Path(filename);fd,temp=tempfile.mkstemp(prefix=".project_",suffix=".tmp",dir=target.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as stream:
            fd=None;stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,target)
    finally:
        if fd is not None:os.close(fd)
        Path(temp).unlink(missing_ok=True)
    return str(target)

def rebuild_project(project):
    from mesh_core import generate_mesh,fill_core
    project.validate();result=generate_mesh(project.params)
    if project.build_target=="layer_and_core":
        c=project.core;result=fill_core(result,c.growth,c.max_size,c.max_cells)
    return result

def merge_project_inputs(base,current):
    """Keep unexposed saved fields; always overwrite active GUI inputs."""
    if base is None or (base.law,base.mode)!=(current.law,current.mode):return current
    keys=list(GEOMETRY_KEYS)+["law","mode"]
    if current.law=="wall_core":
        keys.append("wall_layers")
        if current.mode != "layer_first_growth":keys.append("layer_thickness")
        if current.mode in ("layer_thickness","layer_first_growth"):keys.append("h1")
        if current.mode in ("layer_growth","layer_first_growth"):keys.append("layer_growth")
    else:
        if current.mode in ("first_count","shape_count"):keys.append("nj")
        if current.law!="uniform" and current.mode!="shape_count":keys.append("h1")
        if current.mode=="first_max":keys.append("hmax")
        if current.law=="geometric" and current.mode=="first_growth":keys.append("shape")
        if current.law=="two_zone":
            keys += ["wall_layers","transition_layers","smoothing","smoothing_percent","max_transition_layers","max_auto_cells"]
            if current.mode in ("shape_count","first_growth"):keys.append("shape")
    return replace(base,**{k:getattr(current,k) for k in keys})
