# -*- coding: utf-8 -*-
"""Законы распределения узлов поперёк пограничного слоя и подбор числа ячеек."""
from dataclasses import replace

import numpy as np

from mesh_params import shape_bounds


def minimum_count(p):
    """Минимальное допустимое число ячеек поперёк слоя."""
    return p.wall_layers + p.transition_layers + 1 if p.law == "two_zone" else 2


def exponents(n, p):
    """Показатели степеней для геометрического и двухзонного распределений."""
    if p.law != "two_zone":
        return np.arange(n, dtype=float)
    nc = n - p.wall_layers - p.transition_layers
    if nc < 1:
        raise ValueError("Зонам не хватает места: после прогрессии и перехода нужна хотя бы одна ячейка ядра")
    wall = np.arange(p.wall_layers, dtype=float)
    r = np.arange(1, p.transition_layers + 1)
    transition = wall[-1] + np.cumsum(1 - r / (p.transition_layers + 1))
    last = transition[-1] if len(transition) else wall[-1]
    return np.r_[wall, transition, np.full(nc, last)]


def fractions(parameter, n, p):
    """Относительные ширины ячеек для заданного параметра формы."""
    if p.law == "wall_core":
        raise ValueError("Для независимого слоя используйте generate_mesh()")
    a = np.atleast_1d(parameter).astype(float)[:, None]
    if p.law in ("geometric", "two_zone"):
        e = exponents(n, p)
        w = np.exp(np.log(a) * (e[None, :] - e[-1]))
        return w / w.sum(axis=1, keepdims=True)
    if p.law == "uniform":
        return np.full((len(a), n), 1 / n)
    t = np.linspace(0, 1, n + 1)[None, :]
    if p.law == "power":
        s = t ** a
    else:
        b = np.where(a < 1e-8, 1.0, a)
        if p.law == "tanh":
            s = np.sinh(b * t) / (np.cosh(b * (1 - t)) * np.sinh(b))
        else:
            s = np.exp(b * (t - 1)) * (-np.expm1(-2 * b * t)) / (-np.expm1(-2 * b))
        s = np.where(a < 1e-8, t, s)
    s[:, 0], s[:, -1] = 0.0, 1.0
    return np.diff(s, axis=1)


def fit_first(lengths, n, p):
    """Подобрать параметр формы под заданный первый шаг h1."""
    if n < minimum_count(p):
        raise ValueError("Недостаточно ячеек для выбранных зон")
    target = p.h1 / lengths
    if np.any(target > 1 / n * (1 + 1e-12)):
        raise ValueError("Первый шаг больше среднего: уменьшите первый шаг или число ячеек")
    low, high = shape_bounds(p.law)
    lo, hi = np.full(lengths.shape, low), np.full(lengths.shape, high)
    if np.any(fractions(hi, n, p)[:, 0] > target * (1 + 1e-10)):
        raise ValueError("Первый шаг недостижим в допустимом диапазоне параметра")
    for _ in range(65):
        mid = (lo + hi) / 2
        larger = fractions(mid, n, p)[:, 0] > target
        lo = np.where(larger, mid, lo)
        hi = np.where(larger, hi, mid)
    return (lo + hi) / 2


def parameters_for(lengths, n, p):
    """Вычислить массив параметров формы для всех радиальных линий."""
    if n < minimum_count(p):
        raise ValueError("Недостаточно ячеек для выбранных зон")
    if p.law == "uniform":
        return np.ones(lengths.shape)
    return np.full(lengths.shape, p.shape) if p.mode == "shape_count" else fit_first(lengths, n, p)


def uniform_count(lengths, p):
    """Определить число ячеек для равномерного распределения."""
    if p.mode == "shape_count":
        return p.nj - 1
    with np.errstate(over="ignore", divide="ignore"):
        ratio = float(np.max(lengths) / p.hmax)
    tolerance = 32 * np.finfo(float).eps
    if not np.isfinite(ratio) or ratio > p.max_auto_cells * (1 + tolerance):
        raise ValueError(
            f"Для предельного размера требуется больше {p.max_auto_cells} ячеек от стенки. "
            "Увеличьте предельный размер; достигнуто внутреннее ограничение количества."
        )
    nearest = float(np.rint(ratio))
    if abs(ratio - nearest) <= tolerance * max(1.0, abs(ratio)):
        ratio = nearest
    count = max(minimum_count(p), int(np.ceil(ratio)))
    if count > p.max_auto_cells:
        raise ValueError("Количество превышает внутреннее ограничение")
    return count


def choose_count(lengths, p):
    """Подобрать минимальное число ячеек, удовлетворяющее ограничениям."""
    if p.law == "uniform":
        return uniform_count(lengths, p)
    if p.mode in ("first_count", "shape_count"):
        return p.nj - 1
    lower = minimum_count(p)
    upper = min(p.max_auto_cells, int(np.floor(lengths.min() / p.h1)))
    if upper < lower:
        raise ValueError("Первый шаг или параметры зон не оставляют места для необходимого числа ячеек")

    def good(n):
        try:
            a = parameters_for(lengths, n, p)
        except ValueError:
            return False
        if p.mode == "first_growth":
            return bool(np.all(a <= p.shape * (1 + 1e-12)))
        return bool(np.all(lengths * fractions(a, n, p)[:, -1] <= p.hmax * (1 + 1e-12)))

    if not good(upper):
        raise ValueError("Ограничение недостижимо. Измените первый шаг, предел размера/роста или параметры зон")
    lo, hi = lower, upper
    while lo < hi:
        mid = (lo + hi) // 2
        if good(mid):
            hi = mid
        else:
            lo = mid + 1
    return lo


def solve_distribution(lengths, p):
    """Подобрать итоговые параметры (включая переходные слои) и параметры формы."""
    if p.law != "two_zone" or p.smoothing != "auto":
        actual = replace(p, transition_layers=0) if p.law == "two_zone" and p.smoothing == "none" else p
        n = choose_count(lengths, actual)
        a = parameters_for(lengths, n, actual)
        return replace(actual, nj=n + 1), a

    epsilon = np.log1p(p.smoothing_percent / 100)
    limit = p.max_transition_layers
    if p.mode in ("first_count", "shape_count"):
        limit = min(limit, p.nj - 1 - p.wall_layers - 1)
    last_error = ""
    for nt in range(max(-1, limit) + 1):
        candidate = replace(p, transition_layers=nt)
        try:
            n = choose_count(lengths, candidate)
            a = parameters_for(lengths, n, candidate)
        except ValueError as exc:
            last_error = str(exc)
            continue
        if np.log(a.max()) / (nt + 1) <= epsilon * (1 + 1e-12):
            return replace(candidate, nj=n + 1), a
    raise ValueError(
        "Не удалось подобрать сглаживание до заданного числа переходных ячеек. "
        "Измените параметры, увеличьте лимит поиска или ослабьте допуск. " + last_error
    )
