# -*- coding: utf-8 -*-
"""Типизированные настройки и двухэтапный рабочий процесс (без зависимости от Qt)."""
from dataclasses import asdict, dataclass

import numpy as np

from mesh_core_fill import fill_core
from mesh_layer import validate_layer_params
from mesh_params import MeshParams


@dataclass(frozen=True)
class GeometryParams:
    d_rod: float = 9.1e-3
    pitch: float = 12.75e-3
    z_len: float = 0.05
    ni: int = 120
    nz: int = 10
    full: bool = True

    @classmethod
    def from_mesh_params(cls, p):
        return cls(**{name: getattr(p, name) for name in cls.__dataclass_fields__})

    def validate(self):
        for name in ("d_rod", "pitch", "z_len"):
            value = getattr(self, name)
            if not np.isfinite(value) or value <= 0:
                raise ValueError(f"{name}: требуется положительное конечное число")
        if self.pitch <= self.d_rod:
            raise ValueError("Шаг решётки должен быть больше диаметра")
        for name, minimum in (("ni", 2), ("nz", 1)):
            value = getattr(self, name)
            if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < minimum:
                raise ValueError(f"{name}: требуется целое число >= {minimum}")
        if not isinstance(self.full, (bool, np.bool_)):
            raise ValueError("full должен быть логическим")


@dataclass(frozen=True)
class WallLayerParams:
    mode: str = "layer_thickness"
    h1: float = 5.7e-6
    wall_layers: int = 40
    layer_thickness: float = 350e-6
    layer_growth: float = 1.05

    @classmethod
    def from_mesh_params(cls, p):
        if p.law != "wall_core":
            raise ValueError("Нужны параметры независимого слоя")
        return cls(**{name: getattr(p, name) for name in cls.__dataclass_fields__})

    def validate(self):
        validate_layer_params(MeshParams(law="wall_core", **asdict(self)))

    def to_mesh_params(self, geometry=None):
        geometry = GeometryParams() if geometry is None else geometry
        geometry.validate()
        self.validate()
        return MeshParams(law="wall_core", **asdict(geometry), **asdict(self))

    def active_values(self):
        value = self.h1 if self.mode == "layer_thickness" else self.layer_growth
        return self.mode, self.wall_layers, self.layer_thickness, value


@dataclass(frozen=True)
class CoreParams:
    growth: float = 1.1
    max_size: float = 30e-6
    max_cells: int = 5000

    def validate(self):
        if isinstance(self.growth, (bool, np.bool_)) or not np.isfinite(self.growth) or self.growth < 1:
            raise ValueError("Коэффициент роста ядра должен быть конечным и не меньше 1")
        if isinstance(self.max_size, (bool, np.bool_)) or not np.isfinite(self.max_size) or self.max_size <= 0:
            raise ValueError("Предельный шаг ядра должен быть положительным и конечным")
        if (
            isinstance(self.max_cells, (bool, np.bool_))
            or not isinstance(self.max_cells, (int, np.integer))
            or self.max_cells < 1
        ):
            raise ValueError("Лимит числа ячеек ядра должен быть положительным целым")

    def fill(self, layer):
        self.validate()
        return fill_core(layer, self.growth, self.max_size, self.max_cells)


class MeshWorkflow:
    """Stores a reusable layer separately from the displayed/exportable result."""

    def __init__(self):
        self.layer = None
        self.result = None
        self.stale = True
        self.layer_stale = True

    @property
    def can_fill(self):
        return self.layer is not None and not self.layer_stale

    @property
    def can_export(self):
        return self.result is not None and self.result.complete and not self.stale

    def accept_mesh(self, result):
        if not result.complete and result.params.law != "wall_core":
            raise ValueError("Ожидался независимый пристеночный слой")
        self.result = result
        self.stale = False
        self.layer = None if result.complete else result
        self.layer_stale = result.complete

    def invalidate_layer(self):
        self.layer_stale = True
        self.stale = True

    def invalidate_core(self):
        if self.can_fill:
            self.result = self.layer
            self.stale = False
        elif self.result is not None and self.result.params.law == "wall_core":
            self.stale = True

    def matches_layer(self, params):
        if not self.can_fill or params.law != "wall_core":
            return False
        old = self.layer.requested
        return (
            GeometryParams.from_mesh_params(old) == GeometryParams.from_mesh_params(params)
            and WallLayerParams.from_mesh_params(old).active_values()
            == WallLayerParams.from_mesh_params(params).active_values()
        )

    def accept_core(self, result):
        if not self.can_fill:
            raise ValueError("Нет актуального пристеночного слоя")
        if not result.complete or not self.matches_layer(result.requested):
            raise ValueError("Ядро не соответствует текущему слою")
        self.result = result
        self.stale = False
