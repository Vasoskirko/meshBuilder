# -*- coding: utf-8 -*-
"""Расчёт сетки, независимый слой, заполнение ядра и терминальный запуск.

Не требует Qt. Запуск CLI: python mesh_core.py --help
"""
from dataclasses import dataclass, replace, asdict, field
from pathlib import Path
import argparse
from enum import Enum
import json
import math
import os
import sys
import tempfile

import numpy as np


# ========================================================================
# Независимый пристеночный слой
# ========================================================================

"""Independent, radial prism stack. No core or transition parameters."""

LAYER_MODES={"layer_first_growth":"Первый размер + количество + рост (CFD)", "layer_thickness":"Первый размер + количество + толщина", "layer_growth":"Коэффициент роста + количество + толщина"}

def validate_layer_params(p):
    req_keys = ("d_rod","pitch","z_len") if p.mode=="layer_first_growth" else ("d_rod","pitch","z_len","layer_thickness")
    for key in req_keys:
        value=getattr(p,key)
        if not np.isfinite(value) or value<=0:raise ValueError(f"{key}: требуется положительное конечное число")
    for key,minimum in (("ni",2),("nz",1),("wall_layers",2)):
        value=getattr(p,key)
        if isinstance(value,(bool,np.bool_)) or not isinstance(value,(int,np.integer)) or value<minimum:
            raise ValueError(f"{key}: требуется целое число ≥ {minimum}")
    if p.pitch<=p.d_rod:raise ValueError("Шаг решётки должен быть больше диаметра")
    if not isinstance(p.full,(bool,np.bool_)):raise ValueError("full должен быть логическим")
    if p.mode not in LAYER_MODES:raise ValueError("Выберите способ задания пристеночного слоя")
    if p.mode in ("layer_thickness","layer_first_growth") and (not np.isfinite(p.h1) or p.h1<=0):raise ValueError("Первый размер должен быть положительным и конечным")
    if p.mode in ("layer_growth","layer_first_growth") and (not np.isfinite(p.layer_growth) or not 1<=p.layer_growth<=100):raise ValueError("Коэффициент роста слоя должен быть в диапазоне 1 … 100")

def layer_distribution(p):
    n=p.wall_layers;j=np.arange(n,dtype=float)
    def log_sum(logq):
        z=j*logq
        return float(z[-1]+np.log(np.exp(z-z[-1]).sum()))
    if p.mode=="layer_first_growth":
        first=float(p.h1);logq=math.log(p.layer_growth)
        w=np.exp(math.log(first)+j*logq);w[0]=first
        total=float(w.sum())
    elif p.mode=="layer_thickness":
        total=float(p.layer_thickness)
        first=float(p.h1);target=math.log(total)-math.log(first)
        if target<math.log(n)-1e-12:raise ValueError("Толщина слоя меньше N·H1. Измените первый размер, количество или толщину; убывающий слой не выбран.")
        lo,hi=0.,math.log(100.)
        if log_sum(hi)<target-1e-12:raise ValueError("Для заданного слоя требуется коэффициент роста больше внутреннего предела 100")
        for _ in range(65):
            mid=(lo+hi)/2
            if log_sum(mid)<target:lo=mid
            else:hi=mid
        logq=(lo+hi)/2;w=np.exp(math.log(first)+j*logq);w[0]=first
    else:
        total=float(p.layer_thickness)
        logq=math.log(p.layer_growth);w=np.exp(math.log(total)+j*logq-log_sum(logq))
    if not np.all(np.isfinite(w)) or np.any(w<=0):raise ValueError("Слишком сильное растяжение слоя: совпадающие узлы")
    if p.mode!="layer_first_growth" and not math.isclose(float(w.sum()),total,rel_tol=2e-11,abs_tol=0.):raise ValueError("Не удалось выдержать толщину слоя")
    return w,float(math.exp(logq))

def migrate_layer_values(values,version):
    values=dict(values)
    if version==5 and values.get("law")=="wall_core" and values.get("mode")=="layer_growth":
        h=float(values.get("h1",5.7e-6));q=float(values.get("layer_growth",1.02));n=values.get("wall_layers",40)
        if isinstance(n,bool) or not isinstance(n,int) or n<2 or not math.isfinite(h) or h<=0 or not math.isfinite(q) or not 1<=q<=100:
            raise ValueError("Некорректная старая конфигурация пристеночного слоя версии 5")
        z=np.arange(n,dtype=float)*math.log(q)
        logtotal=math.log(h)+float(z[-1]+np.log(np.exp(z-z[-1]).sum()))
        if logtotal>math.log(np.finfo(float).max):raise ValueError("Переполнение толщины старого слоя")
        values["layer_thickness"]=math.exp(logtotal)
    return values


# ========================================================================
# Геометрия, распределения, диагностика и сохранение
# ========================================================================

UNITS={"м":1.,"мм":1e-3,"мкм":1e-6}
LAWS={"geometric":"Геометрическое","two_zone":"Рост у стенки → постоянный шаг",
      "tanh":"Гиперболический тангенс (tanh)","sinh":"Гиперболический синус (sinh)",
      "power":"Степенное","uniform":"Равномерное","wall_core":"Пристеночный слой"}
MODES={"first_count":"Первый шаг и число ячеек","first_max":"Первый шаг и максимальный размер",
       "shape_count":"Задать параметр распределения вручную","first_growth":"Ограничить рост соседних ячеек"}

GEOMETRIC_MODES={"first_count":"Первый размер + число ячеек",
                 "first_max":"Первый размер + предельный размер ячейки",
                 "first_growth":"Первый размер + предел коэффициента роста"}
HYPERBOLIC_MODES={"first_count":"Первый размер + число ячеек",
                  "first_max":"Первый размер + предельный размер ячейки"}
POWER_MODES={"first_count":"Первый размер + число ячеек",
             "first_max":"Первый размер + предельный размер ячейки"}
UNIFORM_MODES={"shape_count":"Число ячеек","first_max":"Предельный размер ячейки"}
MODES.update(LAYER_MODES)
UI_LAWS={"geometric":"Геометрическое","two_zone":"Рост у стенки → постоянный шаг",
         "hyperbolic":"Гиперболическое","power":"Степенное","uniform":"Равномерное","wall_core":"Пристеночный слой"}

def available_modes(law):
    if law=="wall_core":return dict(LAYER_MODES)
    if law=="geometric":return dict(GEOMETRIC_MODES)
    if law in ("tanh","sinh"):return dict(HYPERBOLIC_MODES)
    if law=="power":return dict(POWER_MODES)
    if law=="uniform":return dict(UNIFORM_MODES)
    return {key:label for key,label in MODES.items()
            if key not in LAYER_MODES and (law!="uniform" or key=="shape_count")
            and (key!="first_growth" or law=="two_zone")}

@dataclass(frozen=True)
class MeshParams:
    d_rod:float=9.1e-3
    pitch:float=12.75e-3
    z_len:float=0.05
    ni:int=120
    nj:int=200
    nz:int=10
    h1:float=5.7e-6
    hmax:float=30e-6
    full:bool=True
    law:str="geometric"
    mode:str="first_count"
    shape:float=1.02
    wall_layers:int=40
    transition_layers:int=12
    smoothing:str="auto"
    smoothing_percent:float=0.5
    max_transition_layers:int=64
    max_auto_cells:int=5000
    filename:str="two_channels.xyz"
    layer_thickness:float=.35e-3
    layer_growth:float=1.05

    def validate(self):
        if self.law=="wall_core":
            validate_layer_params(self)
            return
        if self.mode in LAYER_MODES:raise ValueError("Этот способ задания относится к пристеночному слою")
        for name in ("d_rod","pitch","z_len"):
            v=getattr(self,name)
            if not np.isfinite(v) or v<=0:
                raise ValueError(f"{name}: требуется положительное конечное число")
        for name,minimum in (("ni",2),("nj",3),("nz",1),("wall_layers",2),
                             ("transition_layers",0),("max_transition_layers",0),("max_auto_cells",2)):
            v=getattr(self,name)
            if isinstance(v,(bool,np.bool_)) or not isinstance(v,(int,np.integer)) or v<minimum:
                raise ValueError(f"{name}: требуется целое число >= {minimum}")
        if self.pitch<=self.d_rod or not isinstance(self.full,(bool,np.bool_)):
            raise ValueError("Шаг решётки должен быть больше диаметра; full должен быть логическим")
        if self.law not in LAWS or self.mode not in MODES:
            raise ValueError("Неизвестный закон или режим")
        if self.law=="geometric" and self.mode=="shape_count":
            raise ValueError("Точное задание коэффициента роста для геометрического закона больше не используется. Выберите первый размер с числом ячеек, пределом размера или пределом роста. Старые настройки не преобразуются автоматически.")
        if self.law in ("tanh","sinh") and self.mode not in HYPERBOLIC_MODES:
            raise ValueError("Гиперболическое распределение поддерживает только первый размер с числом ячеек или с предельным размером. Ручное задание β и ограничение роста для него не используются; старые параметры не преобразуются автоматически.")
        if self.law=="power" and self.mode not in POWER_MODES:
            raise ValueError("Степенное распределение поддерживает только первый размер с числом ячеек или с предельным размером. Ручное задание p и ограничение роста не используются; старые параметры не преобразуются автоматически.")
        if self.law=="uniform" and self.mode not in UNIFORM_MODES:
            raise ValueError("Равномерное распределение: задайте число ячеек или предельный размер. Первый размер и рост независимо не задаются.")
        if self.law!="uniform" and self.mode!="shape_count" and (not np.isfinite(self.h1) or self.h1<=0):
            raise ValueError("Первый шаг должен быть положительным и конечным")
        if self.mode=="first_max":
            if not np.isfinite(self.hmax) or self.hmax<=0:
                raise ValueError("Предельный размер должен быть положительным и конечным")
            if self.law!="uniform" and self.hmax<self.h1:
                raise ValueError("Максимальный размер должен быть не меньше первого шага")
        if self.mode=="first_growth" and self.law not in ("geometric","two_zone"):
            raise ValueError("Ограничение постоянного роста доступно для геометрического и двухзонного законов")
        if self.mode in ("shape_count","first_growth") and self.law!="uniform":
            a,b=shape_bounds(self.law)
            if not np.isfinite(self.shape) or not a<=self.shape<=b:
                raise ValueError(f"Параметр должен быть в диапазоне [{a}, {b}]")
        if self.smoothing not in ("none","auto","manual"):
            raise ValueError("Неизвестный способ сглаживания")
        if self.law=="two_zone" and self.smoothing=="auto":
            if not np.isfinite(self.smoothing_percent) or not 0<self.smoothing_percent<=100:
                raise ValueError("Допуск сглаживания должен быть больше 0 и не больше 100 %")


def shape_bounds(law):
    return {"geometric":(1.,100.),"two_zone":(1.,100.),"tanh":(0.,20.),
            "sinh":(0.,600.),"power":(1.,10000.),"uniform":(1.,1.),"wall_core":(1.,100.)}[law]


def minimum_count(p):
    return p.wall_layers+p.transition_layers+1 if p.law=="two_zone" else 2


def exponents(n,p):
    if p.law!="two_zone":
        return np.arange(n,dtype=float)
    nc=n-p.wall_layers-p.transition_layers
    if nc<1:
        raise ValueError("Зонам не хватает места: после прогрессии и перехода нужна хотя бы одна ячейка ядра")
    wall=np.arange(p.wall_layers,dtype=float)
    r=np.arange(1,p.transition_layers+1)
    transition=wall[-1]+np.cumsum(1-r/(p.transition_layers+1))
    last=transition[-1] if len(transition) else wall[-1]
    return np.r_[wall,transition,np.full(nc,last)]


def fractions(parameter,n,p):
    if p.law=="wall_core":raise ValueError("Для независимого слоя используйте generate_mesh()")
    a=np.atleast_1d(parameter).astype(float)[:,None]
    if p.law in ("geometric","two_zone"):
        e=exponents(n,p)
        w=np.exp(np.log(a)*(e[None,:]-e[-1]))
        return w/w.sum(axis=1,keepdims=True)
    if p.law=="uniform":
        return np.full((len(a),n),1/n)
    t=np.linspace(0,1,n+1)[None,:]
    if p.law=="power":
        s=t**a
    else:
        b=np.where(a<1e-8,1.,a)
        if p.law=="tanh":
            s=np.sinh(b*t)/(np.cosh(b*(1-t))*np.sinh(b))
        else:
            s=np.exp(b*(t-1))*(-np.expm1(-2*b*t))/(-np.expm1(-2*b))
        s=np.where(a<1e-8,t,s)
    s[:,0],s[:,-1]=0.,1.
    return np.diff(s,axis=1)


def fit_first(lengths,n,p):
    if n<minimum_count(p):
        raise ValueError("Недостаточно ячеек для выбранных зон")
    target=p.h1/lengths
    if np.any(target>1/n*(1+1e-12)):
        raise ValueError("Первый шаг больше среднего: уменьшите первый шаг или число ячеек")
    low,high=shape_bounds(p.law)
    lo,hi=np.full(lengths.shape,low),np.full(lengths.shape,high)
    if np.any(fractions(hi,n,p)[:,0]>target*(1+1e-10)):
        raise ValueError("Первый шаг недостижим в допустимом диапазоне параметра")
    for _ in range(65):
        mid=(lo+hi)/2
        larger=fractions(mid,n,p)[:,0]>target
        lo=np.where(larger,mid,lo)
        hi=np.where(larger,hi,mid)
    return (lo+hi)/2


def parameters_for(lengths,n,p):
    if n<minimum_count(p):
        raise ValueError("Недостаточно ячеек для выбранных зон")
    if p.law=="uniform":return np.ones(lengths.shape)
    return np.full(lengths.shape,p.shape) if p.mode=="shape_count" else fit_first(lengths,n,p)


def uniform_count(lengths,p):
    if p.mode=="shape_count":return p.nj-1
    # The snap removes only floating-point noise near an integer quotient.
    with np.errstate(over="ignore",divide="ignore"):
        ratio=float(np.max(lengths)/p.hmax)
    tolerance=32*np.finfo(float).eps
    if not np.isfinite(ratio) or ratio>p.max_auto_cells*(1+tolerance):
        raise ValueError(f"Для предельного размера требуется больше {p.max_auto_cells} ячеек от стенки. Увеличьте предельный размер; достигнуто внутреннее ограничение количества.")
    nearest=float(np.rint(ratio))
    if abs(ratio-nearest)<=tolerance*max(1.,abs(ratio)):ratio=nearest
    count=max(minimum_count(p),int(np.ceil(ratio)))
    if count>p.max_auto_cells:
        raise ValueError("Количество превышает внутреннее ограничение")
    return count

def choose_count(lengths,p):
    if p.law=="uniform":return uniform_count(lengths,p)
    if p.mode in ("first_count","shape_count"):
        return p.nj-1
    lower=minimum_count(p)
    upper=min(p.max_auto_cells,int(np.floor(lengths.min()/p.h1)))
    if upper<lower:
        raise ValueError("Первый шаг или параметры зон не оставляют места для необходимого числа ячеек")
    def good(n):
        try:
            a=parameters_for(lengths,n,p)
        except ValueError:
            return False
        if p.mode=="first_growth":
            return bool(np.all(a<=p.shape*(1+1e-12)))
        return bool(np.all(lengths*fractions(a,n,p)[:,-1]<=p.hmax*(1+1e-12)))
    if not good(upper):
        raise ValueError("Ограничение недостижимо. Измените первый шаг, предел размера/роста или параметры зон")
    lo,hi=lower,upper
    while lo<hi:
        mid=(lo+hi)//2
        if good(mid):
            hi=mid
        else:
            lo=mid+1
    return lo


def solve_distribution(lengths,p):
    if p.law!="two_zone" or p.smoothing!="auto":
        actual=replace(p,transition_layers=0) if p.law=="two_zone" and p.smoothing=="none" else p
        n=choose_count(lengths,actual)
        a=parameters_for(lengths,n,actual)
        return replace(actual,nj=n+1),a
    epsilon=np.log1p(p.smoothing_percent/100)
    limit=p.max_transition_layers
    if p.mode in ("first_count","shape_count"):
        limit=min(limit,p.nj-1-p.wall_layers-1)
    last_error=""
    for nt in range(max(-1,limit)+1):
        candidate=replace(p,transition_layers=nt)
        try:
            n=choose_count(lengths,candidate)
            a=parameters_for(lengths,n,candidate)
        except ValueError as exc:
            last_error=str(exc)
            continue
        if np.log(a.max())/(nt+1)<=epsilon*(1+1e-12):
            return replace(candidate,nj=n+1),a
    raise ValueError("Не удалось подобрать сглаживание до заданного числа переходных ячеек. "
                     "Измените параметры, увеличьте лимит поиска или ослабьте допуск. "+last_error)


def reflection(point,direction):
    d=direction/np.linalg.norm(direction)
    a=2*np.outer(d,d)-np.eye(2)
    return a,point-a@point

def rotation(center,angle):
    c,s=np.cos(angle),np.sin(angle)
    a=np.array([[c,-s],[s,c]])
    return a,center-a@center

def compose(t1,t2):
    return t1[0]@t2[0],t1[0]@t2[1]+t1[1]

def transform(t,block):
    x,y=block
    v=t[0]@np.stack((x.ravel(),y.ravel()))+t[1][:,None]
    x2,y2=v.reshape((2,)+x.shape)
    return (x2[:,::-1],y2[:,::-1]) if np.linalg.det(t[0])<0 else (x2,y2)

def cross2(a,b):
    return a[...,0]*b[...,1]-a[...,1]*b[...,0]


class MeshState(str, Enum):
    LAYER_ONLY = "layer_only"
    COMPLETE = "complete"

@dataclass(frozen=True)
class BlockInterface:
    block_a: int
    face_a: str
    block_b: int
    face_b: str
    reversed: bool = False

@dataclass(frozen=True)
class MeshTopology:
    name: str
    state: MeshState
    full: bool
    block_count: int
    interfaces: tuple

def mesh_topology(full=True, complete=True):
    if not isinstance(full, (bool, np.bool_)) or not isinstance(complete, (bool, np.bool_)):
        raise ValueError("full и complete должны быть логическими")
    state = MeshState.COMPLETE if complete else MeshState.LAYER_ONLY
    pairs = [(0,"i_max",1,"i_max",True)]
    if full:
        pairs = [(0,"i_min",5,"i_min",True),(0,"i_max",6,"i_max",True),
                 (1,"i_min",2,"i_min",True),(1,"i_max",7,"i_max",True),
                 (3,"i_min",4,"i_min",True),(6,"i_min",11,"i_min",True),
                 (7,"i_min",8,"i_min",True),(9,"i_min",10,"i_min",True)]
        if complete:
            pairs += [(0,"j_max",1,"j_min",False),(2,"j_max",3,"j_min",False),
                      (4,"j_max",5,"j_min",False),(6,"j_min",7,"j_max",False),
                      (8,"j_min",9,"j_max",False),(10,"j_min",11,"j_max",False)]
    return MeshTopology("two_channels",state,bool(full),12 if full else 2,
                        tuple(BlockInterface(*pair) for pair in pairs))

def _block_faces(x,y):
    v=np.stack((x,y),axis=-1)
    return {"i_min":v[0],"i_max":v[-1],"j_min":v[:,0],"j_max":v[:,-1]}

def _check_interfaces(blocks,topology,tolerance,reject_extra=True):
    if len(blocks)!=topology.block_count:
        raise ValueError(f"Топология: требуется {topology.block_count} блоков, получено {len(blocks)}")
    faces=[_block_faces(x,y) for x,y in blocks]
    expected=set();maximum=0.
    for interface in topology.interfaces:
        a,b=interface.block_a,interface.block_b
        fa,fb=interface.face_a,interface.face_b
        va,vb=faces[a][fa],faces[b][fb]
        if interface.reversed:vb=vb[::-1]
        if va.shape!=vb.shape:
            raise ValueError(f"Стык блоков {a+1}:{fa} ↔ {b+1}:{fb}: разные размеры граней")
        error=float(np.max(np.abs(va-vb)))
        if not np.isfinite(error) or error>tolerance:
            raise ValueError(f"Не совпадает ожидаемый стык между блоками {a+1}:{fa} и {b+1}:{fb}; расхождение {error:.8g} м, допуск {tolerance:.8g} м")
        maximum=max(maximum,error)
        expected.add(frozenset(((a,fa),(b,fb))))
    if reject_extra:
        entries=[(k,name,face) for k,group in enumerate(faces) for name,face in group.items()]
        for index,(a,fa,va) in enumerate(entries):
            for b,fb,vb in entries[index+1:]:
                if a==b or va.shape!=vb.shape:continue
                if frozenset(((a,fa),(b,fb))) in expected:continue
                error=min(float(np.abs(va-vb).max()),float(np.abs(va-vb[::-1]).max()))
                if error<=tolerance:
                    raise ValueError(f"Неожиданное совпадение граней {a+1}:{fa} и {b+1}:{fb}")
    return len(topology.interfaces),maximum

def check_mesh(blocks,p=None,*,topology=None):
    """Validate a result, or raw blocks (complete topology by default)."""
    if p is None:
        result=blocks
        if not all(hasattr(result,name) for name in ("blocks","params","complete")):
            raise ValueError("Передайте MeshResult либо blocks и params")
        p=result.params;expected=mesh_topology(p.full,result.complete)
        stored=getattr(result,"topology",None)
        if stored is not None and stored!=expected:
            raise ValueError("Топология не соответствует состоянию результата")
        if topology is not None and topology!=expected:
            raise ValueError("Переданная топология не соответствует состоянию результата")
        topology=stored or expected;blocks=result.blocks
    if topology is None:topology=mesh_topology(p.full,complete=True)
    if not isinstance(topology,MeshTopology) or topology!=mesh_topology(p.full,topology.state==MeshState.COMPLETE):
        raise ValueError("Неподдерживаемая или несогласованная топология")
    if len(blocks)!=topology.block_count:
        raise ValueError(f"Топология: требуется {topology.block_count} блоков, получено {len(blocks)}")
    if not np.isfinite(p.pitch) or p.pitch<=0 or p.ni<2 or p.nj<2:
        raise ValueError("Некорректные параметры геометрической проверки")
    minimum=np.inf;turning=0.
    for k,(x,y) in enumerate(blocks):
        v=np.stack((x,y),axis=-1)
        if v.shape!=(p.ni,p.nj,2) or not np.all(np.isfinite(v)):
            raise ValueError("Некорректные координаты блока")
        a,b,c,d=v[:-1,:-1],v[1:,:-1],v[1:,1:],v[:-1,1:]
        jac=np.stack((cross2(b-a,d-a),cross2(b-a,c-b),cross2(c-d,c-b),cross2(c-d,d-a)))
        if np.any(jac<=0):raise ValueError(f"Блок {k+1}: вырожденные или перевёрнутые ячейки")
        minimum=min(minimum,float(jac.min()))
        edge=np.diff(v,axis=0)
        if len(edge)>1:
            cosine=np.sum(edge[:-1]*edge[1:],axis=-1)/(np.linalg.norm(edge[:-1],axis=-1)*np.linalg.norm(edge[1:],axis=-1))
            turning=max(turning,float(np.degrees(np.arccos(np.clip(cosine,-1,1))).max()))
    count,error=_check_interfaces(blocks,topology,p.pitch*1e-12)
    return minimum,count,error,turning


@dataclass(frozen=True)
class MeshResult:
    params:MeshParams
    requested:MeshParams
    blocks:list
    wall_start:list
    parameter:np.ndarray
    layer_widths:np.ndarray
    distances:np.ndarray
    diagnostics:dict
    complete:bool=True
    outer_boundaries:list=field(default_factory=list)
    outer_normals:list=field(default_factory=list)
    domain_outline:list=field(default_factory=list)
    topology:MeshTopology|None=None

    def __post_init__(self):
        expected=mesh_topology(self.params.full,self.complete)
        if self.topology is None:object.__setattr__(self,"topology",expected)
        elif self.topology!=expected:raise ValueError("Топология не соответствует состоянию результата")

    @property
    def state(self):
        return MeshState.COMPLETE if self.complete else MeshState.LAYER_ONLY


def wall_geometry_diagnostics(arc,direction,widths,radius):
    normal=arc/np.linalg.norm(arc,axis=1)[:,None]
    unit=direction/np.linalg.norm(direction,axis=1)[:,None]
    dot=np.sum(normal*unit,axis=1)
    angle=np.degrees(np.arctan2(np.abs(cross2(normal,unit)),dot));index=int(np.argmax(angle))
    projection=widths*dot;first=arc+widths[:,None]*unit
    distance=widths*(2*radius*dot+widths)/(np.linalg.norm(first,axis=1)+radius)
    return dict(wall_normal_angle_max_deg=float(angle[index]),wall_normal_angle_max_line=index+1,
                wall_normal_angle_max_theta_deg=float(np.degrees(np.arctan2(arc[index,1],arc[index,0]))),
                first_normal_projection_min=float(projection.min()),first_normal_projection_max=float(projection.max()),
                first_wall_distance_min=float(distance.min()),first_wall_distance_max=float(distance.max()))


def verify_layer_interfaces(blocks,p):
    _check_interfaces(blocks,mesh_topology(p.full,complete=False),p.pitch*1e-12)



def domain_outline(blocks,pitch):
    faces=[]
    for xx,yy in blocks:
        v=np.stack((xx,yy),axis=-1)
        faces.extend([v[0],v[-1],v[:,0],v[:,-1]])
    outline=[]
    for i,face in enumerate(faces):
        shared=False
        for j,other in enumerate(faces):
            if i==j or face.shape!=other.shape:continue
            error=min(float(np.abs(face-other).max()),float(np.abs(face-other[::-1]).max()))
            if error<=pitch*1e-12:shared=True;break
        if not shared:outline.append(face.copy())
    return outline


def generate_mesh(p):
    p.validate()
    a,b=np.array([0.,0.]),np.array([p.pitch,0.])
    c=np.array([p.pitch/2,p.pitch*np.sqrt(3)/2])
    o,m=(a+b+c)/3,(a+b)/2
    theta=np.linspace(np.arctan2(o[1],o[0]),0,p.ni)
    arc=p.d_rod/2*np.column_stack((np.cos(theta),np.sin(theta)))
    opposite=o+np.linspace(0,1,p.ni)[:,None]*(m-o)
    reference=arc[:,None,:]+np.array([0.,1.])[None,:,None]*(opposite-arc)[:,None,:]
    layer=p.law=="wall_core"
    if layer:
        wall,q=layer_distribution(p)
        thickness=float(wall.sum())
        gap=(p.pitch-p.d_rod)/2
        if thickness>=gap*(1-1e-12):
            raise ValueError(f"Слой толщиной {thickness*1e6:.6g} мкм не помещается без соприкосновения соседних слоёв. Доступно менее {gap*1e6:.6g} мкм. Параметры слоя не изменены.")
        n=p.wall_layers
        actual=replace(p,nj=n+1,h1=float(wall[0]),transition_layers=0,smoothing="none")
        parameter=np.full(p.ni,q)
        widths=np.broadcast_to(wall,(p.ni,n)).copy()
        opposite=(p.d_rod/2+thickness)*np.column_stack((np.cos(theta),np.sin(theta)))
    direction=opposite-arc
    lengths=np.linalg.norm(direction,axis=1)
    if not layer:
        actual,parameter=solve_distribution(lengths,p)
        n=actual.nj-1
        widths=lengths[:,None]*fractions(parameter,n,actual)
    s=np.column_stack((np.zeros(p.ni),np.cumsum(widths,axis=1)))
    if not np.all(np.isfinite(s)) or np.any(widths<=0):
        raise ValueError("Слишком сильное растяжение: совпадающие узлы")
    s[:,-1]=lengths
    if np.any(np.diff(s,axis=1)<=0):
        raise ValueError("Совпадающие координаты узлов")
    if p.law!="uniform" and p.mode!="shape_count" and not np.allclose(widths[:,0],actual.h1,rtol=1e-9,atol=0):
        raise ValueError("Не удалось выдержать первый шаг")
    if np.any(widths[:,1:]<widths[:,:-1]-lengths[:,None]*1e-11):
        raise ValueError("Размеры ячеек убывают от стенки")
    v=arc[:,None,:]+s[:,:,None]*(direction/lengths[:,None])[:,None,:]
    v[:,-1]=opposite
    x,y=v[:,:,0],v[:,:,1]
    mo,ma=reflection(o,m-o),reflection(a,b-a)
    ch1=[]
    for k in range(3):
        turn=rotation(o,2*np.pi*k/3)
        ch1 += [transform(turn,(x,y)),transform(compose(turn,mo),(x,y))]
    ch2=[transform(ma,block) for block in ch1]
    blocks=ch1+ch2 if p.full else [ch1[0],ch2[0]]
    walls=[True,False]*3+[False,True]*3 if p.full else [True,False]
    minimum,count,error,turning=check_mesh(blocks,actual,topology=mesh_topology(p.full,complete=not layer))
    d={"layers":n,"blocks":len(blocks),"cells":len(blocks)*(p.ni-1)*n*p.nz,
       "max_wall":float(np.hypot(np.diff(x,axis=1),np.diff(y,axis=1)).max()),
       "max_azimuth":float(np.hypot(np.diff(x,axis=0),np.diff(y,axis=0)).max()),"max_height":p.z_len/p.nz,
       "first_min":float(widths[:,0].min()),"first_max":float(widths[:,0].max()),
       "parameter_min":float(parameter.min()),"parameter_max":float(parameter.max()),
       "growth_max":float((widths[:,1:]/widths[:,:-1]).max()),"min_jacobian":minimum,
       "interfaces":count,"interface_error":error,"max_turning_deg":turning}
    if p.law=="two_zone":
        nt=actual.transition_layers
        j=p.wall_layers+nt
        d.update(wall_layers=p.wall_layers,transition_layers=nt,core_layers=n-j,
                 smoothing_change_percent=float(np.expm1(np.log(parameter.max())/(nt+1))*100),
                 core_start_min=float(s[:,j].min()),core_start_max=float(s[:,j].max()),
                 core_step_min=float(widths[:,j:].min()),core_step_max=float(widths[:,j:].max()))
    if p.mode=="first_max" and d["max_wall"]>p.hmax*(1+1e-9):
        raise ValueError("Нарушен предел максимального размера")
    d.update(wall_geometry_diagnostics(arc,direction,widths[:,0],p.d_rod/2))
    if layer:
        verify_layer_interfaces(blocks,p)
        frontiers=[];normals=[]
        for (xx,yy),starts in zip(blocks,walls):
            coords=np.stack((xx,yy),axis=-1)
            outer=coords[:,-1] if starts else coords[:,0]
            inner=coords[:,0] if starts else coords[:,-1]
            vectors=outer-inner
            frontiers.append(outer.copy());normals.append(vectors/np.linalg.norm(vectors,axis=1)[:,None])
        reference_blocks=[]
        for k in range(3):
            turn=rotation(o,2*np.pi*k/3)
            reference_blocks += [transform(turn,(reference[:,:,0],reference[:,:,1])),transform(compose(turn,mo),(reference[:,:,0],reference[:,:,1]))]
        other=[transform(ma,block) for block in reference_blocks]
        reference_blocks=reference_blocks+other if p.full else [reference_blocks[0],other[0]]
        outline=domain_outline(reference_blocks,p.pitch)
        d.update(layer_thickness_actual=thickness,layer_growth_actual=q,layer_last=float(wall[-1]),core_built=False)
        return MeshResult(actual,p,blocks,walls,parameter,widths,s,d,False,frontiers,normals,outline)
    return MeshResult(actual,p,blocks,walls,parameter,widths,s,d)


def save_mesh(result,filename):
    if not result.complete:raise ValueError("Построен только пристеночный слой. Ядро не построено; экспорт полной сетки заблокирован.")
    p=result.params
    target=Path(filename)
    fd,temp=tempfile.mkstemp(prefix=".mesh_",suffix=".tmp",dir=target.parent)
    os.close(fd)
    try:
        with Path(temp).open("w",encoding="ascii",newline="\n") as f:
            f.write(f"{len(result.blocks)}\n")
            for _ in result.blocks:f.write(f"{p.ni} {p.nj} {p.nz+1}\n")
            for x,y in result.blocks:
                for coordinate in (x,y,None):
                    for k in range(p.nz+1):
                        flat=coordinate.ravel(order="F") if coordinate is not None else np.full(p.ni*p.nj,p.z_len*k/p.nz)
                        for start in range(0,len(flat),6):
                            f.write(" ".join(f"{v:.16e}" for v in flat[start:start+6])+"\n")
        os.replace(temp,target)
    finally:Path(temp).unlink(missing_ok=True)
    return str(target)


def save_configuration(p,geometry_unit,cell_unit,filename,resolved=None):
    p.validate()
    if geometry_unit not in UNITS or cell_unit not in UNITS:raise ValueError("Неизвестная единица")
    data={"version":7,"geometry_unit":geometry_unit,"cell_unit":cell_unit,"parameters":asdict(p)}
    if resolved is not None:data["resolved_parameters"]=asdict(resolved)
    text=json.dumps(data,ensure_ascii=False,indent=2)
    target=Path(filename);fd,temp=tempfile.mkstemp(prefix=".settings_",suffix=".tmp",dir=target.parent);os.close(fd)
    try:
        with Path(temp).open("w",encoding="utf-8") as stream:
            stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,target)
    finally:Path(temp).unlink(missing_ok=True)


def load_configuration(filename):
    d=json.loads(Path(filename).read_text(encoding="utf-8"))
    version=d.get("version")
    if version not in (2,3,4,5,6,7):raise ValueError("Неподдерживаемая версия настроек")
    values=dict(d["parameters"])
    if version<4:values["smoothing"]="manual"
    values=migrate_layer_values(values,version)
    p=MeshParams(**values)
    p.validate()
    gu=d.get("geometry_unit",d.get("unit","мм"))
    cu=d.get("cell_unit",d.get("unit","мкм"))
    if gu not in UNITS or cu not in UNITS:raise ValueError("Неизвестная единица настроек")
    return p,gu,cu


# ========================================================================
# Заполнение ядра без изменения слоя
# ========================================================================

"""Fill the core after an independent layer from mesh_generator 0.6.0.

No azimuthal coarsening. The layer coordinates are copied unchanged.
Nominal steps grow by q and then repeat the last admissible step.
For exact length closure a constant plateau is fitted separately on each line;
its entry ratio may be smaller than q. Widths never decrease and never exceed H.
"""

# Structured failure diagnostics. Successful numerical paths are unchanged.
def _diagnostic_json(value):
    if isinstance(value,(bool,np.bool_)):return bool(value)
    if isinstance(value,(int,np.integer)):return int(value)
    if isinstance(value,(float,np.floating)):
        number=float(value)
        return number if math.isfinite(number) else ("NaN" if math.isnan(number) else "Infinity" if number>0 else "-Infinity")
    if value is None or isinstance(value,str):return value
    if isinstance(value,np.ndarray):return _diagnostic_json(value.tolist())
    if isinstance(value,dict):return {str(k):_diagnostic_json(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [_diagnostic_json(v) for v in value]
    return repr(value)

class MeshDiagnosticError(ValueError):
    def __init__(self,message,*,code="UNCLASSIFIED_ERROR",stage="unknown",category="unclassified",location=None,values=None,hint=None):
        self.message=str(message)
        self.diagnostic={"format":"mesh-diagnostic","version":1,"code":code,"stage":stage,
            "category":category,"message":self.message,"location":_diagnostic_json(location or {}),
            "values":_diagnostic_json(values or {}),"hint":hint,
            "scope":"current_algorithm","coordinate_units":"m"}
        super().__init__(self.message)
    @property
    def code(self):return self.diagnostic["code"]
    def to_dict(self):
        return json.loads(json.dumps(self.diagnostic,ensure_ascii=False,allow_nan=False))
    def __str__(self):
        place=self.diagnostic["location"]
        suffix=(f" Линия {place['line']}." if "line" in place else "")
        return f"[{self.code}] {self.message}{suffix}"

class CoreFillError(MeshDiagnosticError):
    """ValueError-compatible; failure leaves the supplied layer unchanged."""
    def __init__(self,message,*,code="CORE_UNCLASSIFIED",stage="core",category="unclassified",location=None,values=None,hint=None):
        super().__init__(message,code=code,stage=stage,category=category,location=location,values=values,hint=hint)

def save_diagnostic(error,filename,context=None):
    if isinstance(error,MeshDiagnosticError):data=error.to_dict()
    else:
        data=MeshDiagnosticError(str(error),stage="external",values={"exception_type":type(error).__name__}).to_dict()
    if context is not None:data["context"]=_diagnostic_json(context)
    text=json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+"\n"
    target=Path(filename);fd,temp=tempfile.mkstemp(prefix=".diagnostic_",suffix=".tmp",dir=target.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as stream:
            fd=None;stream.write(text);stream.flush();os.fsync(stream.fileno())
        os.replace(temp,target)
    finally:
        if fd is not None:os.close(fd)
        Path(temp).unlink(missing_ok=True)
    return str(target)

def _core_nominal_capacity(count,h0,logq,m,cap):
    """O(lines) nominal sum for diagnostics only, without allocating count cells."""
    count=float(count)
    with np.errstate(over="ignore",divide="ignore",invalid="ignore",under="ignore"):
        if logq==0:return count*h0
        k=np.minimum(count,m)
        logtotal=np.log(h0)+k*logq+np.log(-np.expm1(-k*logq))-math.log(-math.expm1(-logq))
        rising=np.where(k>0,np.exp(logtotal),0.)
        return rising+np.maximum(0.,count-k)*cap

def _core_count_failure(lengths,h0,growth,max_size,max_cells,upper,physical_ratio,m,cap,capacity):
    with np.errstate(over="ignore",divide="ignore"):
        ratios=lengths/h0
    limiting=int(np.argmin(ratios))
    deficits=lengths-capacity
    blocking=int(np.argmax(deficits/lengths))
    physical=None;physical_capacity=None
    if math.isfinite(physical_ratio):
        physical=int(math.floor(physical_ratio+1e-11))
        physical_capacity=capacity.copy() if physical==upper else _core_nominal_capacity(physical,h0,math.log(growth),m,cap)
    if physical_capacity is not None and np.any(physical_capacity<lengths*(1-1e-12)):
        code="CORE_NO_COMMON_COUNT";category="incompatible_constraints"
        message="Нет общего количества ячеек: даже без лимита поиска длинной линии не хватает длины при максимальном числе ячеек, допустимом короткой линией."
        assessment="infeasible_at_physical_upper_with_algorithm_tolerance"
        i=int(np.argmax((lengths-physical_capacity)/lengths));blocking=i
        hint="Одного увеличения max_cells недостаточно. Пересмотрите предел/рост ядра или параметры слоя; убывающий переход этот алгоритм не поддерживает."
    else:
        code="CORE_CELL_LIMIT_REACHED";category="search_limit"
        message="Достигнут лимит числа ячеек ядра; допустимость за пределами текущего поиска проверена отдельно, если численно представима."
        assessment="feasible_at_physical_upper_with_algorithm_tolerance" if physical_capacity is not None else "not_checked_nonfinite_physical_upper"
        hint="Можно увеличить max_cells; это не меняет исходный слой. Также можно пересмотреть предел и рост ядра."
    message+=f" Проверено N={upper}: линия {blocking+1}, требуется {lengths[blocking]:.8g} м, номинально доступно {capacity[blocking]:.8g} м."
    if physical is not None:message+=f" Линия {limiting+1} ограничивает общее количество сверху: N <= {physical}."
    values={"growth_requested":growth,"max_size_requested_m":max_size,"max_cells_requested":max_cells,
        "tested_count_upper":upper,"physical_count_upper":physical,"physical_count_upper_assessment":assessment,
        "limiting_line":limiting+1,"limiting_length_m":lengths[limiting],"limiting_last_layer_width_m":h0[limiting],
        "blocking_line":blocking+1,"blocking_length_m":lengths[blocking],"blocking_last_layer_width_m":h0[blocking],
        "nominal_plateau_m":cap[blocking],"capacity_at_tested_upper_m":capacity[blocking],
        "deficit_at_tested_upper_m":lengths[blocking]-capacity[blocking],
        "capacity_at_physical_upper_m":None if physical_capacity is None else physical_capacity[blocking],
        "length_tolerance_relative":1e-12,"beyond_limit_check":"closed_form_nominal_sum_not_mesh_generation"}
    return CoreFillError(message+" Пристеночный слой не изменён.",code=code,category=category,
        location={"scope":"distribution_input","line":blocking+1,"index_base":1},values=values,hint=hint)


@dataclass(frozen=True)
class CoreDistribution:
    widths:np.ndarray
    plateau:np.ndarray
    nominal_plateau:np.ndarray
    nominal_steps:np.ndarray
    growth_cells:np.ndarray
    count:int

def _positive_vector(values,name):
    a=np.asarray(values,dtype=float)
    if a.ndim!=1 or not a.size or not np.all(np.isfinite(a)) or np.any(a<=0):
        location={}
        if a.ndim==1 and a.size:
            bad=np.flatnonzero(~np.isfinite(a)|(a<=0))
            if bad.size:location={"scope":"distribution_input","line":int(bad[0])+1,"index_base":1}
        raise CoreFillError(f"{name}: требуется непустой вектор положительных конечных чисел",
            code="CORE_INVALID_VECTOR",category="invalid_input",location=location,
            values={"parameter":name,"shape":list(a.shape),"first_bad_value":None if not location else a[location["line"]-1]})
    return a

def capped_distribution(lengths,last_layer_width,growth,max_size,max_cells=5000,transition_ratio=1.0):
    lengths=_positive_vector(lengths,"Длина области ядра")
    h0=np.asarray(last_layer_width,dtype=float)
    if h0.ndim==0:h0=np.full(lengths.shape,float(h0))
    h0=_positive_vector(h0,"Последние размеры слоя")
    transition_ratio=float(transition_ratio)
    if not math.isfinite(transition_ratio) or transition_ratio<=0:
        raise CoreFillError("Коэффициент перехода (ядро / призма) должен быть положительным числом.",code="CORE_INVALID_TRANSITION",category="invalid_input",values={"transition_ratio":transition_ratio})
    h0=h0*transition_ratio
    growth=float(growth);max_size=float(max_size)
    if not math.isfinite(growth) or growth<1:raise CoreFillError("Коэффициент роста должен быть не меньше 1",code="CORE_INVALID_GROWTH",category="invalid_input",values={"growth":growth,"minimum":1})
    if not math.isfinite(max_size) or max_size<=0:raise CoreFillError("Максимальный размер ячейки должен быть положительным",code="CORE_INVALID_MAXSIZE",category="invalid_input",values={"max_size_m":max_size})
    if isinstance(max_cells,(bool,np.bool_)) or not isinstance(max_cells,(int,np.integer)) or max_cells<1:
        raise CoreFillError("Ограничение числа ячеек должно быть целым числом не меньше 1",code="CORE_INVALID_COUNT_LIMIT",category="invalid_input",values={"max_cells":max_cells})

    h0=np.minimum(h0, max_size)

    # Общее число слоёв N ограничивается самым узким лучом: первая ячейка
    # везде строго h0 (q_trans * h_prism_last), поэтому N <= floor(L_i/h0_i).
    # Рост ячеек только монотонный: сначала q_core до целевого размера,
    # затем плато; на длинных лучах плато/рост подстраиваются под длину.
    n_fit=int(np.floor(np.min(lengths/h0)))
    n=int(min(max(n_fit,1),int(max_cells)))

    if growth==1.0:
        # q_core = 1: равномерное заполнение размером ~h_core_1,
        # адаптированное под целое число ячеек на каждом луче.
        # Целевой размер при этом не используется.
        widths=np.repeat((lengths/n)[:,None],n,axis=1)
        plateau=lengths/n
        cap_vec=h0.copy()
        nominal=np.repeat(h0[:,None],n,axis=1)
        growth_cells=np.zeros(len(lengths),dtype=int)
        return CoreDistribution(widths,plateau,cap_vec,nominal,growth_cells,n)

    logq=math.log(growth)
    j=np.arange(n,dtype=float)
    widths=np.empty((len(lengths),n),dtype=float)
    plateau=np.empty(len(lengths),dtype=float)
    nominal=np.empty_like(widths)
    cap_vec=np.empty(len(lengths),dtype=float)

    for i,(L,first) in enumerate(zip(lengths,h0)):
        if n==1:
            widths[i,0]=L;plateau[i]=L;cap_vec[i]=min(first,max_size)
            nominal[i,0]=min(first,max_size);continue
        geo=first*np.exp(j*logq) if growth>1 else np.full(n,first)
        cap_i=min(max_size,float(geo[-1]))
        ideal=np.minimum(geo,cap_i)
        nominal[i]=ideal;cap_vec[i]=cap_i
        if ideal.sum()>=L*(1-1e-12):
            lo,hi=first,cap_i
        elif geo.sum()>=L*(1-1e-12):
            # плато получается крупнее целевого размера (луч длинный)
            lo,hi=cap_i,float(geo[-1])
        else:
            # рост q_core не заполняет луч: круче рост, первая ячейка строго h0
            q_lo,q_hi=growth,2.0
            def _gs(q,first=first,n=n):
                if q<=1.0:return first*n
                return first*(q**n-1.0)/(q-1.0)
            guard=0
            while _gs(q_hi)<L and guard<60:
                q_hi*=2.0;guard+=1
            if _gs(q_hi)>=L:
                for _ in range(80):
                    mid=0.5*(q_lo+q_hi)
                    if _gs(mid)<L:q_lo=mid
                    else:q_hi=mid
                qe=0.5*(q_lo+q_hi)
                w=first*(qe**j)
                w*=L/w.sum()
                widths[i]=w;plateau[i]=w[-1]
                continue
            w=np.full(n,L/n);widths[i]=w;plateau[i]=L/n
            continue
        for _ in range(80):
            mid=0.5*(lo+hi)
            if np.minimum(geo,mid).sum()<L:lo=mid
            else:hi=mid
        p=0.5*(lo+hi)
        w=np.minimum(geo,p)
        w*=L/w.sum()
        widths[i]=w;plateau[i]=p

    growth_cells=(widths<plateau[:,None]*(1-1e-9)).sum(axis=1)
    return CoreDistribution(widths,plateau,cap_vec,nominal,growth_cells,n)

def fixed_count_distribution(lengths,last_layer_width,count,transition_ratio=1.0):
    lengths=_positive_vector(lengths,"Длина области ядра")
    h0=np.asarray(last_layer_width,dtype=float)
    if h0.ndim==0:h0=np.full(lengths.shape,float(h0))
    h0=_positive_vector(h0,"Последние размеры слоя")
    transition_ratio=float(transition_ratio)
    if not math.isfinite(transition_ratio) or transition_ratio<=0:
        raise CoreFillError("Коэффициент перехода (ядро / призма) должен быть положительным числом.",code="CORE_INVALID_TRANSITION",category="invalid_input",values={"transition_ratio":transition_ratio})
    h0=h0*transition_ratio
    count=int(count)
    if count<1:
        raise CoreFillError("Число слоёв ядра должно быть не меньше 1.",code="CORE_INVALID_COUNT",category="invalid_input",values={"count":count})
    widths=np.empty((len(lengths),count),dtype=float)
    for i,(L,first) in enumerate(zip(lengths,h0)):
        if count==1:
            widths[i,0]=L; continue
        if first*count>=L*(1-1e-12):
            # строгое h0 невозможно: равномерно (первая ячейка меньше h0)
            widths[i,:]=L/count; continue
        lo,hi=1.0,10.0
        while first*(hi**count-1.0)/(hi-1.0)<L:
            hi*=2.0
            if hi>1e6:break
        for _ in range(64):
            mid=0.5*(lo+hi)
            s=first*count if abs(mid-1.0)<1e-12 else first*(mid**count-1.0)/(mid-1.0)
            if s<L:lo=mid
            else:hi=mid
        q=0.5*(lo+hi)
        w=first*(q**np.arange(count,dtype=float))
        w*=L/w.sum()
        widths[i,:]=w
    plateau=widths[:,-1].copy()
    return CoreDistribution(widths,plateau,plateau,widths,np.full(len(lengths),count,dtype=int),count)

def fill_core(layer,growth,max_size,max_cells=5000):
    """Return a complete MeshResult; require the independent result from 0.6.0.

    Result metadata keeps the original layer's parameters and adds core_*
    diagnostics. Every original layer node is copied bit-for-bit.
    Changing the supplied layer object is never necessary.
    """
    if getattr(layer,"complete",True):raise CoreFillError("Нужен результат отдельного пристеночного слоя версии 0.6.0, а не готовая полная сетка")
    required=("params","blocks","wall_start","layer_widths","outer_boundaries","diagnostics")
    if any(not hasattr(layer,key) for key in required):raise CoreFillError("Неподдерживаемая структура результата слоя")
    p=layer.params
    ni=p.ni;nwall=layer.layer_widths.shape[1]
    expected_blocks=12 if p.full else 2
    if len(layer.blocks)!=expected_blocks or len(layer.wall_start)!=expected_blocks:
        raise CoreFillError("Неверное число участков пристеночного слоя")
    if layer.layer_widths.shape[0]!=ni:raise CoreFillError("Неверная размерность размеров слоя")
    if not layer.wall_start[0]:raise CoreFillError("Первый участок должен быть направлен от стенки")
    x0,y0=layer.blocks[0]
    if x0.shape!=(ni,nwall+1) or y0.shape!=x0.shape:raise CoreFillError("Некорректные размеры первого участка")
    front=np.column_stack((x0[:,-1],y0[:,-1]))
    pitch=p.pitch;a=np.array([0.,0.]);b=np.array([pitch,0.]);c=np.array([pitch/2,pitch*np.sqrt(3)/2])
    centre=(a+b+c)/3;middle=(a+b)/2
    target=centre+np.linspace(0.,1.,ni)[:,None]*(middle-centre)
    vector=target-front;lengths=np.linalg.norm(vector,axis=1)
    try:
        distribution=capped_distribution(lengths,layer.layer_widths[:,-1],growth,max_size,max_cells)
    except CoreFillError as exc:
        if "line" in exc.diagnostic["location"]:
            exc.diagnostic["location"].update(scope="base_block_line",block=1,symmetry_copies_not_enumerated=True)
        raise
    n=distribution.count
    distance=np.column_stack((np.zeros(ni),np.cumsum(distribution.widths,axis=1)))
    distance[:,-1]=lengths
    if np.any(np.diff(distance,axis=1)<=0):raise CoreFillError("Совпадающие узлы ядра")
    coords=front[:,None,:]+distance[:,:,None]*(vector/lengths[:,None])[:,None,:]
    coords[:,0]=front;coords[:,-1]=target
    base=(coords[:,:,0],coords[:,:,1])
    mirror=reflection(centre,middle-centre);other_channel=reflection(a,b-a)
    first=[]
    for k in range(3):
        turn=rotation(centre,2*np.pi*k/3)
        first += [transform(turn,base),transform(compose(turn,mirror),base)]
    second=[transform(other_channel,block) for block in first]
    core_blocks=first+second if p.full else [first[0],second[0]]
    blocks=[]
    tolerance=p.pitch*1e-12
    for index,((xl,yl),(xc,yc),starts) in enumerate(zip(layer.blocks,core_blocks,layer.wall_start)):
        if xl.shape!=(ni,nwall+1) or yl.shape!=xl.shape:raise CoreFillError(f"Неверные размеры участка слоя {index+1}")
        if starts:
            mismatch=max(float(np.abs(xl[:,-1]-xc[:,0]).max()),float(np.abs(yl[:,-1]-yc[:,0]).max()))
            xx=np.concatenate((xl,xc[:,1:]),axis=1);yy=np.concatenate((yl,yc[:,1:]),axis=1)
        else:
            mismatch=max(float(np.abs(xl[:,0]-xc[:,-1]).max()),float(np.abs(yl[:,0]-yc[:,-1]).max()))
            xx=np.concatenate((xc[:,:-1],xl),axis=1);yy=np.concatenate((yc[:,:-1],yl),axis=1)
        if mismatch>tolerance:raise CoreFillError(f"Граница ядра не совпадает со слоем в участке {index+1}")
        blocks.append((xx,yy))
    actual=replace(p,nj=nwall+n+1,hmax=float(max_size))
    topology=mesh_topology(p.full,complete=True)
    try:minimum,interfaces,error,turning=check_mesh(blocks,actual,topology=topology)
    except ValueError as exc:raise CoreFillError("Ядро не прошло геометрическую проверку: "+str(exc)) from exc
    widths=np.concatenate((layer.layer_widths,distribution.widths),axis=1)
    distances=np.column_stack((np.zeros(ni),np.cumsum(widths,axis=1)))
    diagnostics=dict(layer.diagnostics)
    xx,yy=blocks[0]
    direction=vector/lengths[:,None]
    wall_direction=front-np.column_stack((x0[:,0],y0[:,0]))
    wall_direction/=np.linalg.norm(wall_direction,axis=1)[:,None]
    join_angle=np.degrees(np.arctan2(np.abs(wall_direction[:,0]*direction[:,1]-wall_direction[:,1]*direction[:,0]),np.sum(wall_direction*direction,axis=1)))
    diagnostics.update(layers=nwall+n,blocks=len(blocks),cells=len(blocks)*(ni-1)*(nwall+n)*p.nz,
        max_wall=float(np.hypot(np.diff(xx,axis=1),np.diff(yy,axis=1)).max()),
        max_azimuth=float(np.hypot(np.diff(xx,axis=0),np.diff(yy,axis=0)).max()),
        growth_max=float((widths[:,1:]/widths[:,:-1]).max()),min_jacobian=minimum,
        interfaces=interfaces,interface_error=error,max_turning_deg=turning,
        core_built=True,wall_layers=nwall,core_layers=n,core_growth_requested=float(growth),
        core_max_requested=float(max_size),core_step_min=float(distribution.widths.min()),
        core_step_max=float(distribution.widths.max()),core_plateau_min=float(distribution.plateau.min()),
        core_plateau_max=float(distribution.plateau.max()),
        core_nominal_plateau_min=float(distribution.nominal_plateau.min()),
        core_nominal_plateau_max=float(distribution.nominal_plateau.max()),
        core_plateau_reduction_max_percent=float((1-distribution.plateau/distribution.nominal_plateau).max()*100),
        core_growth_cells_min=int(distribution.growth_cells.min()),core_growth_cells_max=int(distribution.growth_cells.max()),
        core_join_angle_max_deg=float(join_angle.max()),core_closure="fit_constant_plateau",
        core_line_lengths=lengths.tolist(),core_plateau_by_line=distribution.plateau.tolist())
    metadata={"topology":topology} if isinstance(layer,MeshResult) else {}
    return replace(layer,params=actual,blocks=blocks,layer_widths=widths,distances=distances,
                   diagnostics=diagnostics,complete=True,**metadata)


# ========================================================================
# Командная строка
# ========================================================================


# ========================================================================
# Typed settings and independent two-stage workflow (no Qt dependency)
# ========================================================================

@dataclass(frozen=True)
class GeometryParams:
    d_rod:float=9.1e-3
    pitch:float=12.75e-3
    z_len:float=0.05
    ni:int=120
    nz:int=10
    full:bool=True

    @classmethod
    def from_mesh_params(cls,p):
        return cls(**{name:getattr(p,name) for name in cls.__dataclass_fields__})

    def validate(self):
        for name in ("d_rod","pitch","z_len"):
            value=getattr(self,name)
            if not np.isfinite(value) or value<=0:raise ValueError(f"{name}: требуется положительное конечное число")
        if self.pitch<=self.d_rod:raise ValueError("Шаг решётки должен быть больше диаметра")
        for name,minimum in (("ni",2),("nz",1)):
            value=getattr(self,name)
            if isinstance(value,(bool,np.bool_)) or not isinstance(value,(int,np.integer)) or value<minimum:
                raise ValueError(f"{name}: требуется целое число >= {minimum}")
        if not isinstance(self.full,(bool,np.bool_)):raise ValueError("full должен быть логическим")


@dataclass(frozen=True)
class WallLayerParams:
    mode:str="layer_thickness"
    h1:float=5.7e-6
    wall_layers:int=40
    layer_thickness:float=350e-6
    layer_growth:float=1.05

    @classmethod
    def from_mesh_params(cls,p):
        if p.law!="wall_core":raise ValueError("Нужны параметры независимого слоя")
        return cls(**{name:getattr(p,name) for name in cls.__dataclass_fields__})

    def validate(self):
        validate_layer_params(MeshParams(law="wall_core",**asdict(self)))

    def to_mesh_params(self,geometry=None):
        geometry=GeometryParams() if geometry is None else geometry
        geometry.validate();self.validate()
        return MeshParams(law="wall_core",**asdict(geometry),**asdict(self))

    def active_values(self):
        value=self.h1 if self.mode=="layer_thickness" else self.layer_growth
        return self.mode,self.wall_layers,self.layer_thickness,value


@dataclass(frozen=True)
class CoreParams:
    growth:float=1.1
    max_size:float=30e-6
    max_cells:int=5000

    def validate(self):
        if isinstance(self.growth,(bool,np.bool_)) or not np.isfinite(self.growth) or self.growth<1:
            raise ValueError("Коэффициент роста ядра должен быть конечным и не меньше 1")
        if isinstance(self.max_size,(bool,np.bool_)) or not np.isfinite(self.max_size) or self.max_size<=0:
            raise ValueError("Предельный шаг ядра должен быть положительным и конечным")
        if isinstance(self.max_cells,(bool,np.bool_)) or not isinstance(self.max_cells,(int,np.integer)) or self.max_cells<1:
            raise ValueError("Лимит числа ячеек ядра должен быть положительным целым")

    def fill(self,layer):
        self.validate()
        return fill_core(layer,self.growth,self.max_size,self.max_cells)


class MeshWorkflow:
    """Stores a reusable layer separately from the displayed/exportable result."""
    def __init__(self):
        self.layer=None
        self.result=None
        self.stale=True
        self.layer_stale=True

    @property
    def can_fill(self):
        return self.layer is not None and not self.layer_stale

    @property
    def can_export(self):
        return self.result is not None and self.result.complete and not self.stale

    def accept_mesh(self,result):
        if not result.complete and result.params.law!="wall_core":
            raise ValueError("Ожидался независимый пристеночный слой")
        self.result=result;self.stale=False
        self.layer=None if result.complete else result
        self.layer_stale=result.complete

    def invalidate_layer(self):
        self.layer_stale=True;self.stale=True

    def invalidate_core(self):
        if self.can_fill:
            self.result=self.layer;self.stale=False
        elif self.result is not None and self.result.params.law=="wall_core":
            self.stale=True

    def matches_layer(self,params):
        if not self.can_fill or params.law!="wall_core":return False
        old=self.layer.requested
        return (GeometryParams.from_mesh_params(old)==GeometryParams.from_mesh_params(params)
                and WallLayerParams.from_mesh_params(old).active_values()
                    ==WallLayerParams.from_mesh_params(params).active_values())

    def accept_core(self,result):
        if not self.can_fill:raise ValueError("Нет актуального пристеночного слоя")
        if not result.complete or not self.matches_layer(result.requested):
            raise ValueError("Ядро не соответствует текущему слою")
        self.result=result;self.stale=False


def cli_main():
    parser=argparse.ArgumentParser(description="Заполнение ядра после независимого пристеночного слоя")
    parser.add_argument("--settings",help="JSON-настройки отдельного слоя версии 0.6.0")
    parser.add_argument("--growth",type=float,default=1.1,help="Номинальный коэффициент роста после слоя")
    parser.add_argument("--max-size-um",type=float,default=30.,help="Предел шага в направлении от слоя, мкм")
    parser.add_argument("--max-cells",type=int,default=5000,help="Лимит числа ячеек ядра на линии")
    parser.add_argument("--output",default="mesh_with_core.xyz")
    parser.add_argument("--error-report",help="JSON-диагностика только при отказе; не проект")
    args=parser.parse_args()
    try:
        if "layer_thickness" not in MeshParams.__dataclass_fields__:
            raise CoreFillError("Нужна программа 0.6.0. Не заменяйте её mesh_core.py исходной версией 0.4.6.")
        if args.settings:
            p,gu,cu=load_configuration(args.settings)
            if p.law!="wall_core":raise CoreFillError("В JSON должен быть выбран отдельный пристеночный слой")
        else:
            p=MeshParams(law="wall_core",mode="layer_thickness",h1=5.7e-6,wall_layers=40,layer_thickness=350e-6)
            gu,cu="мм","мкм"
        layer=generate_mesh(p)
        complete=fill_core(layer,args.growth,args.max_size_um*1e-6,args.max_cells)
        filename=save_mesh(complete,args.output)
        report=Path(args.output).with_suffix(".core.json")
        data={"module":"core_fill","layer_parameters":asdict(p),"geometry_unit":gu,"cell_unit":cu,
              "core_parameters":{"growth":args.growth,"max_size":args.max_size_um*1e-6,"max_cells":args.max_cells},
              "diagnostics":complete.diagnostics}
        report.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
        d=complete.diagnostics
        print("Сохранено:",filename)
        print("Отчёт:",report)
        print("Ячеек пристеночного слоя:",d["wall_layers"])
        print("Ячеек ядра на линии:",d["core_layers"])
        print("Постоянный шаг по линиям, мкм:",d["core_plateau_min"]*1e6,"…",d["core_plateau_max"]*1e6)
        print("Проверено стыков:",d["interfaces"])
        print("Угол изменения направления на выходе из слоя, град:",d["core_join_angle_max_deg"])
    except (ValueError,OSError) as exc:
        print("Ядро не построено:",exc,file=sys.stderr)
        if args.error_report:
            try:
                protected={Path(args.output).resolve(),Path(args.output).with_suffix(".core.json").resolve()}
                if args.settings:protected.add(Path(args.settings).resolve())
                if Path(args.error_report).resolve() in protected:
                    raise ValueError("Путь диагностики совпадает с настройками, XYZ или обычным отчётом CLI")
                save_diagnostic(exc,args.error_report,context={"settings_file":args.settings,"output_file":args.output,"growth":args.growth,"max_size_um":args.max_size_um,"max_cells":args.max_cells})
            except (ValueError,OSError) as report_error:print("Не удалось сохранить диагностику:",report_error,file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
