# -*- coding: utf-8 -*-
"""Параметры сетки, константы законов распределения и их валидация."""
from dataclasses import dataclass

import numpy as np

from mesh_layer import LAYER_MODES, validate_layer_params


UNITS = {"м": 1.0, "мм": 1e-3, "мкм": 1e-6}

LAWS = {
    "geometric": "Геометрическое",
    "two_zone": "Рост у стенки → постоянный шаг",
    "tanh": "Гиперболический тангенс (tanh)",
    "sinh": "Гиперболический синус (sinh)",
    "power": "Степенное",
    "uniform": "Равномерное",
    "wall_core": "Пристеночный слой",
}

MODES = {
    "first_count": "Первый шаг и число ячеек",
    "first_max": "Первый шаг и максимальный размер",
    "shape_count": "Задать параметр распределения вручную",
    "first_growth": "Ограничить рост соседних ячеек",
}
MODES.update(LAYER_MODES)

GEOMETRIC_MODES = {
    "first_count": "Первый размер + число ячеек",
    "first_max": "Первый размер + предельный размер ячейки",
    "first_growth": "Первый размер + предел коэффициента роста",
}
HYPERBOLIC_MODES = {
    "first_count": "Первый размер + число ячеек",
    "first_max": "Первый размер + предельный размер ячейки",
}
POWER_MODES = {
    "first_count": "Первый размер + число ячеек",
    "first_max": "Первый размер + предельный размер ячейки",
}
UNIFORM_MODES = {
    "shape_count": "Число ячеек",
    "first_max": "Предельный размер ячейки",
}

UI_LAWS = {
    "geometric": "Геометрическое",
    "two_zone": "Рост у стенки → постоянный шаг",
    "hyperbolic": "Гиперболическое",
    "power": "Степенное",
    "uniform": "Равномерное",
    "wall_core": "Пристеночный слой",
}


def available_modes(law):
    """Вернуть доступные режимы задания сетки для выбранного закона."""
    if law == "wall_core":
        return dict(LAYER_MODES)
    if law == "geometric":
        return dict(GEOMETRIC_MODES)
    if law in ("tanh", "sinh"):
        return dict(HYPERBOLIC_MODES)
    if law == "power":
        return dict(POWER_MODES)
    if law == "uniform":
        return dict(UNIFORM_MODES)
    return {
        key: label
        for key, label in MODES.items()
        if key not in LAYER_MODES
        and (law != "uniform" or key == "shape_count")
        and (key != "first_growth" or law == "two_zone")
    }


def shape_bounds(law):
    """Вернуть допустимые границы параметра формы для закона распределения."""
    return {
        "geometric": (1.0, 100.0),
        "two_zone": (1.0, 100.0),
        "tanh": (0.0, 20.0),
        "sinh": (0.0, 600.0),
        "power": (1.0, 10000.0),
        "uniform": (1.0, 1.0),
        "wall_core": (1.0, 100.0),
    }[law]


@dataclass(frozen=True)
class MeshParams:
    """Параметры построения структурированной сетки пучка стержней."""

    d_rod: float = 9.1e-3
    pitch: float = 12.75e-3
    z_len: float = 0.05
    ni: int = 120
    nj: int = 200
    nz: int = 10
    h1: float = 5.7e-6
    hmax: float = 30e-6
    full: bool = True
    law: str = "geometric"
    mode: str = "first_count"
    shape: float = 1.02
    wall_layers: int = 40
    transition_layers: int = 12
    smoothing: str = "auto"
    smoothing_percent: float = 0.5
    max_transition_layers: int = 64
    max_auto_cells: int = 5000
    filename: str = "two_channels.xyz"
    layer_thickness: float = 0.35e-3
    layer_growth: float = 1.05

    local_core_mode: str = 'inherit'
    local_core_growth: float = 1.1
    local_core_size: float = 120e-6
    local_core_limit: int = 5000
    local_core_layers: int = 20
    local_core_transition: float = 1.1
    local_core_hermite: bool = False

    def validate(self):
        if self.local_core_mode not in ('inherit','controlled_growth','aspect_alignment','fixed_count'):
            raise ValueError('Неизвестный локальный режим ядра')
        if (not np.isfinite(self.local_core_growth) or not 1<=self.local_core_growth<=100 or
            not np.isfinite(self.local_core_size) or not 0<self.local_core_size<=1000 or
            not np.isfinite(self.local_core_transition) or not .1<=self.local_core_transition<=10 or
            type(self.local_core_limit) is not int or not 1<=self.local_core_limit<=100000 or
            type(self.local_core_layers) is not int or not 1<=self.local_core_layers<=500 or
            type(self.local_core_hermite) is not bool):
            raise ValueError('Некорректные локальные параметры ядра')
        if self.law == "wall_core":
            validate_layer_params(self)
            return
        if self.mode in LAYER_MODES:
            raise ValueError("Этот способ задания относится к пристеночному слою")

        for name in ("d_rod", "pitch", "z_len"):
            v = getattr(self, name)
            if not np.isfinite(v) or v <= 0:
                raise ValueError(f"{name}: требуется положительное конечное число")

        for name, minimum in (
            ("ni", 2),
            ("nj", 3),
            ("nz", 1),
            ("wall_layers", 2),
            ("transition_layers", 0),
            ("max_transition_layers", 0),
            ("max_auto_cells", 2),
        ):
            v = getattr(self, name)
            if isinstance(v, (bool, np.bool_)) or not isinstance(v, (int, np.integer)) or v < minimum:
                raise ValueError(f"{name}: требуется целое число >= {minimum}")

        if self.pitch <= self.d_rod or not isinstance(self.full, (bool, np.bool_)):
            raise ValueError("Шаг решётки должен быть больше диаметра; full должен быть логическим")
        if self.law not in LAWS or self.mode not in MODES:
            raise ValueError("Неизвестный закон или режим")

        if self.law == "geometric" and self.mode == "shape_count":
            raise ValueError(
                "Точное задание коэффициента роста для геометрического закона больше не используется. "
                "Выберите первый размер с числом ячеек, пределом размера или пределом роста. "
                "Старые настройки не преобразуются автоматически."
            )
        if self.law in ("tanh", "sinh") and self.mode not in HYPERBOLIC_MODES:
            raise ValueError(
                "Гиперболическое распределение поддерживает только первый размер с числом ячеек "
                "или с предельным размером. Ручное задание β и ограничение роста для него не "
                "используются; старые параметры не преобразуются автоматически."
            )
        if self.law == "power" and self.mode not in POWER_MODES:
            raise ValueError(
                "Степенное распределение поддерживает только первый размер с числом ячеек или с "
                "предельным размером. Ручное задание p и ограничение роста не используются; "
                "старые параметры не преобразуются автоматически."
            )
        if self.law == "uniform" and self.mode not in UNIFORM_MODES:
            raise ValueError(
                "Равномерное распределение: задайте число ячеек или предельный размер. "
                "Первый размер и рост независимо не задаются."
            )

        if self.law != "uniform" and self.mode != "shape_count" and (not np.isfinite(self.h1) or self.h1 <= 0):
            raise ValueError("Первый шаг должен быть положительным и конечным")

        if self.mode == "first_max":
            if not np.isfinite(self.hmax) or self.hmax <= 0:
                raise ValueError("Предельный размер должен быть положительным и конечным")
            if self.law != "uniform" and self.hmax < self.h1:
                raise ValueError("Максимальный размер должен быть не меньше первого шага")

        if self.mode == "first_growth" and self.law not in ("geometric", "two_zone"):
            raise ValueError("Ограничение постоянного роста доступно для геометрического и двухзонного законов")

        if self.mode in ("shape_count", "first_growth") and self.law != "uniform":
            a, b = shape_bounds(self.law)
            if not np.isfinite(self.shape) or not a <= self.shape <= b:
                raise ValueError(f"Параметр должен быть в диапазоне [{a}, {b}]")

        if self.smoothing not in ("none", "auto", "manual"):
            raise ValueError("Неизвестный способ сглаживания")
        if self.law == "two_zone" and self.smoothing == "auto":
            if not np.isfinite(self.smoothing_percent) or not 0 < self.smoothing_percent <= 100:
                raise ValueError("Допуск сглаживания должен быть больше 0 и не больше 100 %")
