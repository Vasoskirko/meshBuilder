# -*- coding: utf-8 -*-
"""Независимый пристеночный слой (radial prism stack).

Не содержит параметров ядра или переходной зоны.
"""
import math
import numpy as np


LAYER_MODES = {
    "layer_first_growth": "Первый размер + количество + рост (CFD)",
    "layer_thickness": "Первый размер + количество + толщина",
    "layer_growth": "Коэффициент роста + количество + толщина",
}


def validate_layer_params(p):
    """Проверить корректность параметров пристеночного слоя."""
    req_keys = (
        ("d_rod", "pitch", "z_len")
        if p.mode == "layer_first_growth"
        else ("d_rod", "pitch", "z_len", "layer_thickness")
    )
    for key in req_keys:
        value = getattr(p, key)
        if not np.isfinite(value) or value <= 0:
            raise ValueError(f"{key}: требуется положительное конечное число")

    for key, minimum in (("ni", 2), ("nz", 1), ("wall_layers", 2)):
        value = getattr(p, key)
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, np.integer)) or value < minimum:
            raise ValueError(f"{key}: требуется целое число ≥ {minimum}")

    if p.pitch <= p.d_rod:
        raise ValueError("Шаг решётки должен быть больше диаметра")
    if not isinstance(p.full, (bool, np.bool_)):
        raise ValueError("full должен быть логическим")
    if p.mode not in LAYER_MODES:
        raise ValueError("Выберите способ задания пристеночного слоя")
    if p.mode in ("layer_thickness", "layer_first_growth") and (not np.isfinite(p.h1) or p.h1 <= 0):
        raise ValueError("Первый размер должен быть положительным и конечным")
    if p.mode in ("layer_growth", "layer_first_growth") and (
        not np.isfinite(p.layer_growth) or not 1 <= p.layer_growth <= 100
    ):
        raise ValueError("Коэффициент роста слоя должен быть в диапазоне 1 … 100")


def layer_distribution(p):
    """Рассчитать ширины ячеек пристеночного слоя и коэффициент роста."""
    n = p.wall_layers
    j = np.arange(n, dtype=float)

    def log_sum(logq):
        z = j * logq
        return float(z[-1] + np.log(np.exp(z - z[-1]).sum()))

    if p.mode == "layer_first_growth":
        first = float(p.h1)
        logq = math.log(p.layer_growth)
        w = np.exp(math.log(first) + j * logq)
        w[0] = first
        total = float(w.sum())
    elif p.mode == "layer_thickness":
        total = float(p.layer_thickness)
        first = float(p.h1)
        target = math.log(total) - math.log(first)
        if target < math.log(n) - 1e-12:
            raise ValueError(
                "Толщина слоя меньше N·H1. Измените первый размер, количество или толщину; "
                "убывающий слой не выбран."
            )
        lo, hi = 0.0, math.log(100.0)
        if log_sum(hi) < target - 1e-12:
            raise ValueError("Для заданного слоя требуется коэффициент роста больше внутреннего предела 100")
        for _ in range(65):
            mid = (lo + hi) / 2
            if log_sum(mid) < target:
                lo = mid
            else:
                hi = mid
        logq = (lo + hi) / 2
        w = np.exp(math.log(first) + j * logq)
        w[0] = first
    else:
        total = float(p.layer_thickness)
        logq = math.log(p.layer_growth)
        w = np.exp(math.log(total) + j * logq - log_sum(logq))

    if not np.all(np.isfinite(w)) or np.any(w <= 0):
        raise ValueError("Слишком сильное растяжение слоя: совпадающие узлы")
    if p.mode != "layer_first_growth" and not math.isclose(float(w.sum()), total, rel_tol=2e-11, abs_tol=0.0):
        raise ValueError("Не удалось выдержать толщину слоя")
    return w, float(math.exp(logq))


def migrate_layer_values(values, version):
    """Миграция устаревших параметров пристеночного слоя из конфигурации версии 5."""
    values = dict(values)
    if version == 5 and values.get("law") == "wall_core" and values.get("mode") == "layer_growth":
        h = float(values.get("h1", 5.7e-6))
        q = float(values.get("layer_growth", 1.02))
        n = values.get("wall_layers", 40)
        if (
            isinstance(n, bool)
            or not isinstance(n, int)
            or n < 2
            or not math.isfinite(h)
            or h <= 0
            or not math.isfinite(q)
            or not 1 <= q <= 100
        ):
            raise ValueError("Некорректная старая конфигурация пристеночного слоя версии 5")
        z = np.arange(n, dtype=float) * math.log(q)
        logtotal = math.log(h) + float(z[-1] + np.log(np.exp(z - z[-1]).sum()))
        if logtotal > math.log(np.finfo(float).max):
            raise ValueError("Переполнение толщины старого слоя")
        values["layer_thickness"] = math.exp(logtotal)
    return values
