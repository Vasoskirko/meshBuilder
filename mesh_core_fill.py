# -*- coding: utf-8 -*-
"""Заполнение ядра без изменения пристеночного слоя и структурированная диагностика."""
import json
import math
import os
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from mesh_topology import check_mesh, compose, mesh_topology, reflection, rotation, transform


def _diagnostic_json(value):
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return (
            number
            if math.isfinite(number)
            else ("NaN" if math.isnan(number) else "Infinity" if number > 0 else "-Infinity")
        )
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, np.ndarray):
        return _diagnostic_json(value.tolist())
    if isinstance(value, dict):
        return {str(k): _diagnostic_json(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_diagnostic_json(v) for v in value]
    return repr(value)


class MeshDiagnosticError(ValueError):
    def __init__(
        self,
        message,
        *,
        code="UNCLASSIFIED_ERROR",
        stage="unknown",
        category="unclassified",
        location=None,
        values=None,
        hint=None,
    ):
        self.message = str(message)
        self.diagnostic = {
            "format": "mesh-diagnostic",
            "version": 1,
            "code": code,
            "stage": stage,
            "category": category,
            "message": self.message,
            "location": _diagnostic_json(location or {}),
            "values": _diagnostic_json(values or {}),
            "hint": hint,
            "scope": "current_algorithm",
            "coordinate_units": "m",
        }
        super().__init__(self.message)

    @property
    def code(self):
        return self.diagnostic["code"]

    def to_dict(self):
        return json.loads(json.dumps(self.diagnostic, ensure_ascii=False, allow_nan=False))

    def __str__(self):
        place = self.diagnostic["location"]
        suffix = f" Линия {place['line']}." if "line" in place else ""
        return f"[{self.code}] {self.message}{suffix}"


class CoreFillError(MeshDiagnosticError):
    """ValueError-compatible; failure leaves the supplied layer unchanged."""

    def __init__(
        self,
        message,
        *,
        code="CORE_UNCLASSIFIED",
        stage="core",
        category="unclassified",
        location=None,
        values=None,
        hint=None,
    ):
        super().__init__(
            message,
            code=code,
            stage=stage,
            category=category,
            location=location,
            values=values,
            hint=hint,
        )


def save_diagnostic(error, filename, context=None):
    """Сохранить диагностику ошибки в JSON-файл."""
    if isinstance(error, MeshDiagnosticError):
        data = error.to_dict()
    else:
        data = MeshDiagnosticError(
            str(error),
            stage="external",
            values={"exception_type": type(error).__name__},
        ).to_dict()
    if context is not None:
        data["context"] = _diagnostic_json(context)
    text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    target = Path(filename)
    fd, temp = tempfile.mkstemp(prefix=".diagnostic_", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            fd = None
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
    finally:
        if fd is not None:
            os.close(fd)
        Path(temp).unlink(missing_ok=True)
    return str(target)


def _core_nominal_capacity(count, h0, logq, m, cap):
    """O(lines) nominal sum for diagnostics only, without allocating count cells."""
    count = float(count)
    with np.errstate(over="ignore", divide="ignore", invalid="ignore", under="ignore"):
        if logq == 0:
            return count * h0
        k = np.minimum(count, m)
        logtotal = np.log(h0) + k * logq + np.log(-np.expm1(-k * logq)) - math.log(-math.expm1(-logq))
        rising = np.where(k > 0, np.exp(logtotal), 0.0)
        return rising + np.maximum(0.0, count - k) * cap


def _core_count_failure(lengths, h0, growth, max_size, max_cells, upper, physical_ratio, m, cap, capacity):
    with np.errstate(over="ignore", divide="ignore"):
        ratios = lengths / h0
    limiting = int(np.argmin(ratios))
    deficits = lengths - capacity
    blocking = int(np.argmax(deficits / lengths))
    physical = None
    physical_capacity = None
    if math.isfinite(physical_ratio):
        physical = int(math.floor(physical_ratio + 1e-11))
        physical_capacity = (
            capacity.copy() if physical == upper else _core_nominal_capacity(physical, h0, math.log(growth), m, cap)
        )
    if physical_capacity is not None and np.any(physical_capacity < lengths * (1 - 1e-12)):
        code = "CORE_NO_COMMON_COUNT"
        category = "incompatible_constraints"
        message = (
            "Нет общего количества ячеек: даже без лимита поиска длинной линии не хватает длины "
            "при максимальном числе ячеек, допустимом короткой линией."
        )
        assessment = "infeasible_at_physical_upper_with_algorithm_tolerance"
        i = int(np.argmax((lengths - physical_capacity) / lengths))
        blocking = i
        hint = (
            "Одного увеличения max_cells недостаточно. Пересмотрите предел/рост ядра или "
            "параметры слоя; убывающий переход этот алгоритм не поддерживает."
        )
    else:
        code = "CORE_CELL_LIMIT_REACHED"
        category = "search_limit"
        message = (
            "Достигнут лимит числа ячеек ядра; допустимость за пределами текущего поиска "
            "проверена отдельно, если численно представима."
        )
        assessment = (
            "feasible_at_physical_upper_with_algorithm_tolerance"
            if physical_capacity is not None
            else "not_checked_nonfinite_physical_upper"
        )
        hint = (
            "Можно увеличить max_cells; это не меняет исходный слой. "
            "Также можно пересмотреть предел и рост ядра."
        )
    message += (
        f" Проверено N={upper}: линия {blocking + 1}, требуется {lengths[blocking]:.8g} м, "
        f"номинально доступно {capacity[blocking]:.8g} м."
    )
    if physical is not None:
        message += f" Линия {limiting + 1} ограничивает общее количество сверху: N <= {physical}."
    values = {
        "growth_requested": growth,
        "max_size_requested_m": max_size,
        "max_cells_requested": max_cells,
        "tested_count_upper": upper,
        "physical_count_upper": physical,
        "physical_count_upper_assessment": assessment,
        "limiting_line": limiting + 1,
        "limiting_length_m": lengths[limiting],
        "limiting_last_layer_width_m": h0[limiting],
        "blocking_line": blocking + 1,
        "blocking_length_m": lengths[blocking],
        "blocking_last_layer_width_m": h0[blocking],
        "nominal_plateau_m": cap[blocking],
        "capacity_at_tested_upper_m": capacity[blocking],
        "deficit_at_tested_upper_m": lengths[blocking] - capacity[blocking],
        "capacity_at_physical_upper_m": None if physical_capacity is None else physical_capacity[blocking],
        "length_tolerance_relative": 1e-12,
        "beyond_limit_check": "closed_form_nominal_sum_not_mesh_generation",
    }
    return CoreFillError(
        message + " Пристеночный слой не изменён.",
        code=code,
        category=category,
        location={"scope": "distribution_input", "line": blocking + 1, "index_base": 1},
        values=values,
        hint=hint,
    )


@dataclass(frozen=True)
class CoreDistribution:
    widths: np.ndarray
    plateau: np.ndarray
    nominal_plateau: np.ndarray
    nominal_steps: np.ndarray
    growth_cells: np.ndarray
    count: int


def _positive_vector(values, name):
    a = np.asarray(values, dtype=float)
    if a.ndim != 1 or not a.size or not np.all(np.isfinite(a)) or np.any(a <= 0):
        location = {}
        if a.ndim == 1 and a.size:
            bad = np.flatnonzero(~np.isfinite(a) | (a <= 0))
            if bad.size:
                location = {"scope": "distribution_input", "line": int(bad[0]) + 1, "index_base": 1}
        raise CoreFillError(
            f"{name}: требуется непустой вектор положительных конечных чисел",
            code="CORE_INVALID_VECTOR",
            category="invalid_input",
            location=location,
            values={
                "parameter": name,
                "shape": list(a.shape),
                "first_bad_value": None if not location else a[location["line"] - 1],
            },
        )
    return a


def capped_distribution(lengths, last_layer_width, growth, max_size, max_cells=5000, transition_ratio=1.0):
    """Подобрать распределение ячеек ядра с ростом и выходом на плато."""
    lengths = _positive_vector(lengths, "Длина области ядра")
    h0 = np.asarray(last_layer_width, dtype=float)
    if h0.ndim == 0:
        h0 = np.full(lengths.shape, float(h0))
    h0 = _positive_vector(h0, "Последние размеры слоя")
    transition_ratio = float(transition_ratio)
    if not math.isfinite(transition_ratio) or transition_ratio <= 0:
        raise CoreFillError(
            "Коэффициент перехода (ядро / призма) должен быть положительным числом.",
            code="CORE_INVALID_TRANSITION",
            category="invalid_input",
            values={"transition_ratio": transition_ratio},
        )
    h0 = h0 * transition_ratio
    growth = float(growth)
    max_size = float(max_size)
    if not math.isfinite(growth) or growth < 1:
        raise CoreFillError(
            "Коэффициент роста должен быть не меньше 1",
            code="CORE_INVALID_GROWTH",
            category="invalid_input",
            values={"growth": growth, "minimum": 1},
        )
    if not math.isfinite(max_size) or max_size <= 0:
        raise CoreFillError(
            "Максимальный размер ячейки должен быть положительным",
            code="CORE_INVALID_MAXSIZE",
            category="invalid_input",
            values={"max_size_m": max_size},
        )
    if isinstance(max_cells, (bool, np.bool_)) or not isinstance(max_cells, (int, np.integer)) or max_cells < 1:
        raise CoreFillError(
            "Ограничение числа ячеек должно быть целым числом не меньше 1",
            code="CORE_INVALID_COUNT_LIMIT",
            category="invalid_input",
            values={"max_cells": max_cells},
        )

    h0 = np.minimum(h0, max_size)
    n_fit = int(np.floor(np.min(lengths / h0)))
    n = int(min(max(n_fit, 1), int(max_cells)))

    if growth == 1.0:
        widths = np.repeat((lengths / n)[:, None], n, axis=1)
        plateau = lengths / n
        cap_vec = h0.copy()
        nominal = np.repeat(h0[:, None], n, axis=1)
        growth_cells = np.zeros(len(lengths), dtype=int)
        return CoreDistribution(widths, plateau, cap_vec, nominal, growth_cells, n)

    logq = math.log(growth)
    j = np.arange(n, dtype=float)
    widths = np.empty((len(lengths), n), dtype=float)
    plateau = np.empty(len(lengths), dtype=float)
    nominal = np.empty_like(widths)
    cap_vec = np.empty(len(lengths), dtype=float)

    for i, (L, first) in enumerate(zip(lengths, h0)):
        if n == 1:
            widths[i, 0] = L
            plateau[i] = L
            cap_vec[i] = min(first, max_size)
            nominal[i, 0] = min(first, max_size)
            continue
        geo = first * np.exp(j * logq) if growth > 1 else np.full(n, first)
        cap_i = min(max_size, float(geo[-1]))
        ideal = np.minimum(geo, cap_i)
        nominal[i] = ideal
        cap_vec[i] = cap_i
        if ideal.sum() >= L * (1 - 1e-12):
            lo, hi = first, cap_i
        elif geo.sum() >= L * (1 - 1e-12):
            lo, hi = cap_i, float(geo[-1])
        else:
            q_lo, q_hi = growth, 2.0

            def _gs(q, first=first, n=n):
                if q <= 1.0:
                    return first * n
                return first * (q**n - 1.0) / (q - 1.0)

            guard = 0
            while _gs(q_hi) < L and guard < 60:
                q_hi *= 2.0
                guard += 1
            if _gs(q_hi) >= L:
                for _ in range(80):
                    mid = 0.5 * (q_lo + q_hi)
                    if _gs(mid) < L:
                        q_lo = mid
                    else:
                        q_hi = mid
                qe = 0.5 * (q_lo + q_hi)
                w = first * (qe**j)
                w *= L / w.sum()
                widths[i] = w
                plateau[i] = w[-1]
                continue
            w = np.full(n, L / n)
            widths[i] = w
            plateau[i] = L / n
            continue
        for _ in range(80):
            mid = 0.5 * (lo + hi)
            if np.minimum(geo, mid).sum() < L:
                lo = mid
            else:
                hi = mid
        p = 0.5 * (lo + hi)
        w = np.minimum(geo, p)
        w *= L / w.sum()
        widths[i] = w
        plateau[i] = p

    growth_cells = (widths < plateau[:, None] * (1 - 1e-9)).sum(axis=1)
    return CoreDistribution(widths, plateau, cap_vec, nominal, growth_cells, n)


def fixed_count_distribution(lengths, last_layer_width, count, transition_ratio=1.0):
    """Подобрать геометрическое распределение ячеек ядра при фиксированном их числе."""
    lengths = _positive_vector(lengths, "Длина области ядра")
    h0 = np.asarray(last_layer_width, dtype=float)
    if h0.ndim == 0:
        h0 = np.full(lengths.shape, float(h0))
    h0 = _positive_vector(h0, "Последние размеры слоя")
    transition_ratio = float(transition_ratio)
    if not math.isfinite(transition_ratio) or transition_ratio <= 0:
        raise CoreFillError(
            "Коэффициент перехода (ядро / призма) должен быть положительным числом.",
            code="CORE_INVALID_TRANSITION",
            category="invalid_input",
            values={"transition_ratio": transition_ratio},
        )
    h0 = h0 * transition_ratio
    count = int(count)
    if count < 1:
        raise CoreFillError(
            "Число слоёв ядра должно быть не меньше 1.",
            code="CORE_INVALID_COUNT",
            category="invalid_input",
            values={"count": count},
        )
    widths = np.empty((len(lengths), count), dtype=float)
    for i, (L, first) in enumerate(zip(lengths, h0)):
        if count == 1:
            widths[i, 0] = L
            continue
        if first * count >= L * (1 - 1e-12):
            widths[i, :] = L / count
            continue
        lo, hi = 1.0, 10.0
        while first * (hi**count - 1.0) / (hi - 1.0) < L:
            hi *= 2.0
            if hi > 1e6:
                break
        for _ in range(64):
            mid = 0.5 * (lo + hi)
            s = first * count if abs(mid - 1.0) < 1e-12 else first * (mid**count - 1.0) / (mid - 1.0)
            if s < L:
                lo = mid
            else:
                hi = mid
        q = 0.5 * (lo + hi)
        w = first * (q ** np.arange(count, dtype=float))
        w *= L / w.sum()
        widths[i, :] = w
    plateau = widths[:, -1].copy()
    return CoreDistribution(widths, plateau, plateau, widths, np.full(len(lengths), count, dtype=int), count)


def fill_core(layer, growth, max_size, max_cells=5000):
    """Return a complete MeshResult; require the independent result from 0.6.0."""
    if getattr(layer, "complete", True):
        raise CoreFillError("Нужен результат отдельного пристеночного слоя версии 0.6.0, а не готовая полная сетка")
    required = ("params", "blocks", "wall_start", "layer_widths", "outer_boundaries", "diagnostics")
    if any(not hasattr(layer, key) for key in required):
        raise CoreFillError("Неподдерживаемая структура результата слоя")
    p = layer.params
    ni = p.ni
    nwall = layer.layer_widths.shape[1]
    expected_blocks = 12 if p.full else 2
    if len(layer.blocks) != expected_blocks or len(layer.wall_start) != expected_blocks:
        raise CoreFillError("Неверное число участков пристеночного слоя")
    if layer.layer_widths.shape[0] != ni:
        raise CoreFillError("Неверная размерность размеров слоя")
    if not layer.wall_start[0]:
        raise CoreFillError("Первый участок должен быть направлен от стенки")
    x0, y0 = layer.blocks[0]
    if x0.shape != (ni, nwall + 1) or y0.shape != x0.shape:
        raise CoreFillError("Некорректные размеры первого участка")
    front = np.column_stack((x0[:, -1], y0[:, -1]))
    pitch = p.pitch
    a = np.array([0.0, 0.0])
    b = np.array([pitch, 0.0])
    c = np.array([pitch / 2, pitch * np.sqrt(3) / 2])
    centre = (a + b + c) / 3
    middle = (a + b) / 2
    target = centre + np.linspace(0.0, 1.0, ni)[:, None] * (middle - centre)
    vector = target - front
    lengths = np.linalg.norm(vector, axis=1)
    try:
        distribution = capped_distribution(lengths, layer.layer_widths[:, -1], growth, max_size, max_cells)
    except CoreFillError as exc:
        if "line" in exc.diagnostic["location"]:
            exc.diagnostic["location"].update(scope="base_block_line", block=1, symmetry_copies_not_enumerated=True)
        raise
    n = distribution.count
    distance = np.column_stack((np.zeros(ni), np.cumsum(distribution.widths, axis=1)))
    distance[:, -1] = lengths
    if np.any(np.diff(distance, axis=1) <= 0):
        raise CoreFillError("Совпадающие узлы ядра")
    coords = front[:, None, :] + distance[:, :, None] * (vector / lengths[:, None])[:, None, :]
    coords[:, 0] = front
    coords[:, -1] = target
    base = (coords[:, :, 0], coords[:, :, 1])
    mirror = reflection(centre, middle - centre)
    other_channel = reflection(a, b - a)
    first = []
    for k in range(3):
        turn = rotation(centre, 2 * np.pi * k / 3)
        first += [transform(turn, base), transform(compose(turn, mirror), base)]
    second = [transform(other_channel, block) for block in first]
    core_blocks = first + second if p.full else [first[0], second[0]]
    blocks = []
    tolerance = p.pitch * 1e-12
    for index, ((xl, yl), (xc, yc), starts) in enumerate(zip(layer.blocks, core_blocks, layer.wall_start)):
        if xl.shape != (ni, nwall + 1) or yl.shape != xl.shape:
            raise CoreFillError(f"Неверные размеры участка слоя {index + 1}")
        if starts:
            mismatch = max(float(np.abs(xl[:, -1] - xc[:, 0]).max()), float(np.abs(yl[:, -1] - yc[:, 0]).max()))
            xx = np.concatenate((xl, xc[:, 1:]), axis=1)
            yy = np.concatenate((yl, yc[:, 1:]), axis=1)
        else:
            mismatch = max(float(np.abs(xl[:, 0] - xc[:, -1]).max()), float(np.abs(yl[:, 0] - yc[:, -1]).max()))
            xx = np.concatenate((xc[:, :-1], xl), axis=1)
            yy = np.concatenate((yc[:, :-1], yl), axis=1)
        if mismatch > tolerance:
            raise CoreFillError(f"Граница ядра не совпадает со слоем в участке {index + 1}")
        blocks.append((xx, yy))
    actual = replace(p, nj=nwall + n + 1, hmax=float(max_size))
    topology = mesh_topology(p.full, complete=True)
    try:
        minimum, interfaces, error, turning = check_mesh(blocks, actual, topology=topology)
    except ValueError as exc:
        raise CoreFillError("Ядро не прошло геометрическую проверку: " + str(exc)) from exc
    widths = np.concatenate((layer.layer_widths, distribution.widths), axis=1)
    distances = np.column_stack((np.zeros(ni), np.cumsum(widths, axis=1)))
    diagnostics = dict(layer.diagnostics)
    xx, yy = blocks[0]
    direction = vector / lengths[:, None]
    wall_direction = front - np.column_stack((x0[:, 0], y0[:, 0]))
    wall_direction /= np.linalg.norm(wall_direction, axis=1)[:, None]
    join_angle = np.degrees(
        np.arctan2(
            np.abs(wall_direction[:, 0] * direction[:, 1] - wall_direction[:, 1] * direction[:, 0]),
            np.sum(wall_direction * direction, axis=1),
        )
    )
    diagnostics.update(
        layers=nwall + n,
        blocks=len(blocks),
        cells=len(blocks) * (ni - 1) * (nwall + n) * p.nz,
        max_wall=float(np.hypot(np.diff(xx, axis=1), np.diff(yy, axis=1)).max()),
        max_azimuth=float(np.hypot(np.diff(xx, axis=0), np.diff(yy, axis=0)).max()),
        growth_max=float((widths[:, 1:] / widths[:, :-1]).max()),
        min_jacobian=minimum,
        interfaces=interfaces,
        interface_error=error,
        max_turning_deg=turning,
        core_built=True,
        wall_layers=nwall,
        core_layers=n,
        core_growth_requested=float(growth),
        core_max_requested=float(max_size),
        core_step_min=float(distribution.widths.min()),
        core_step_max=float(distribution.widths.max()),
        core_plateau_min=float(distribution.plateau.min()),
        core_plateau_max=float(distribution.plateau.max()),
        core_nominal_plateau_min=float(distribution.nominal_plateau.min()),
        core_nominal_plateau_max=float(distribution.nominal_plateau.max()),
        core_plateau_reduction_max_percent=float((1 - distribution.plateau / distribution.nominal_plateau).max() * 100),
        core_growth_cells_min=int(distribution.growth_cells.min()),
        core_growth_cells_max=int(distribution.growth_cells.max()),
        core_join_angle_max_deg=float(join_angle.max()),
        core_closure="fit_constant_plateau",
        core_line_lengths=lengths.tolist(),
        core_plateau_by_line=distribution.plateau.tolist(),
    )
    metadata = {"topology": topology} if hasattr(layer, "topology") else {}
    return replace(
        layer,
        params=actual,
        blocks=blocks,
        layer_widths=widths,
        distances=distances,
        diagnostics=diagnostics,
        complete=True,
        **metadata,
    )
