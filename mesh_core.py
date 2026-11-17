# -*- coding: utf-8 -*-
"""Расчёт сетки, независимый слой, заполнение ядра и терминальный запуск.

Не требует Qt. Запуск CLI: python mesh_core.py --help
"""
import argparse
import json
import math
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import numpy as np

from mesh_distributions import (  # noqa: F401
    choose_count,
    exponents,
    fit_first,
    fractions,
    minimum_count,
    parameters_for,
    solve_distribution,
    uniform_count,
)
from mesh_layer import (  # noqa: F401
    LAYER_MODES,
    layer_distribution,
    migrate_layer_values,
    validate_layer_params,
)
from mesh_params import (  # noqa: F401
    GEOMETRIC_MODES,
    HYPERBOLIC_MODES,
    LAWS,
    MODES,
    MeshParams,
    POWER_MODES,
    UI_LAWS,
    UNIFORM_MODES,
    UNITS,
    available_modes,
    shape_bounds,
)
from mesh_topology import (  # noqa: F401
    BlockInterface,
    MeshState,
    MeshTopology,
    check_mesh,
    compose,
    cross2,
    domain_outline,
    mesh_topology,
    reflection,
    rotation,
    transform,
    verify_layer_interfaces,
    wall_geometry_diagnostics,
)


@dataclass(frozen=True)
class MeshResult:
    params: MeshParams
    requested: MeshParams
    blocks: list
    wall_start: list
    parameter: np.ndarray
    layer_widths: np.ndarray
    distances: np.ndarray
    diagnostics: dict
    complete: bool = True
    outer_boundaries: list = field(default_factory=list)
    outer_normals: list = field(default_factory=list)
    domain_outline: list = field(default_factory=list)
    topology: MeshTopology | None = None

    def __post_init__(self):
        expected = mesh_topology(self.params.full, self.complete)
        if self.topology is None:
            object.__setattr__(self, "topology", expected)
        elif self.topology != expected:
            raise ValueError("Топология не соответствует состоянию результата")

    @property
    def state(self):
        return MeshState.COMPLETE if self.complete else MeshState.LAYER_ONLY


def generate_mesh(p):
    p.validate()
    a, b = np.array([0.0, 0.0]), np.array([p.pitch, 0.0])
    c = np.array([p.pitch / 2, p.pitch * np.sqrt(3) / 2])
    o, m = (a + b + c) / 3, (a + b) / 2
    theta = np.linspace(np.arctan2(o[1], o[0]), 0, p.ni)
    arc = p.d_rod / 2 * np.column_stack((np.cos(theta), np.sin(theta)))
    opposite = o + np.linspace(0, 1, p.ni)[:, None] * (m - o)
    reference = arc[:, None, :] + np.array([0.0, 1.0])[None, :, None] * (opposite - arc)[:, None, :]
    layer = p.law == "wall_core"
    if layer:
        wall, q = layer_distribution(p)
        thickness = float(wall.sum())
        gap = (p.pitch - p.d_rod) / 2
        if thickness >= gap * (1 - 1e-12):
            raise ValueError(
                f"Слой толщиной {thickness * 1e6:.6g} мкм не помещается без соприкосновения соседних слоёв. "
                f"Доступно менее {gap * 1e6:.6g} мкм. Параметры слоя не изменены."
            )
        n = p.wall_layers
        actual = replace(p, nj=n + 1, h1=float(wall[0]), transition_layers=0, smoothing="none")
        parameter = np.full(p.ni, q)
        widths = np.broadcast_to(wall, (p.ni, n)).copy()
        opposite = (p.d_rod / 2 + thickness) * np.column_stack((np.cos(theta), np.sin(theta)))
    direction = opposite - arc
    lengths = np.linalg.norm(direction, axis=1)
    if not layer:
        actual, parameter = solve_distribution(lengths, p)
        n = actual.nj - 1
        widths = lengths[:, None] * fractions(parameter, n, actual)
    s = np.column_stack((np.zeros(p.ni), np.cumsum(widths, axis=1)))
    if not np.all(np.isfinite(s)) or np.any(widths <= 0):
        raise ValueError("Слишком сильное растяжение: совпадающие узлы")
    s[:, -1] = lengths
    if np.any(np.diff(s, axis=1) <= 0):
        raise ValueError("Совпадающие координаты узлов")
    if p.law != "uniform" and p.mode != "shape_count" and not np.allclose(widths[:, 0], actual.h1, rtol=1e-9, atol=0):
        raise ValueError("Не удалось выдержать первый шаг")
    if np.any(widths[:, 1:] < widths[:, :-1] - lengths[:, None] * 1e-11):
        raise ValueError("Размеры ячеек убывают от стенки")
    v = arc[:, None, :] + s[:, :, None] * (direction / lengths[:, None])[:, None, :]
    v[:, -1] = opposite
    x, y = v[:, :, 0], v[:, :, 1]
    mo, ma = reflection(o, m - o), reflection(a, b - a)
    ch1 = []
    for k in range(3):
        turn = rotation(o, 2 * np.pi * k / 3)
        ch1 += [transform(turn, (x, y)), transform(compose(turn, mo), (x, y))]
    ch2 = [transform(ma, block) for block in ch1]
    blocks = ch1 + ch2 if p.full else [ch1[0], ch2[0]]
    walls = [True, False] * 3 + [False, True] * 3 if p.full else [True, False]
    minimum, count, error, turning = check_mesh(blocks, actual, topology=mesh_topology(p.full, complete=not layer))
    d = {
        "layers": n,
        "blocks": len(blocks),
        "cells": len(blocks) * (p.ni - 1) * n * p.nz,
        "max_wall": float(np.hypot(np.diff(x, axis=1), np.diff(y, axis=1)).max()),
        "max_azimuth": float(np.hypot(np.diff(x, axis=0), np.diff(y, axis=0)).max()),
        "max_height": p.z_len / p.nz,
        "first_min": float(widths[:, 0].min()),
        "first_max": float(widths[:, 0].max()),
        "parameter_min": float(parameter.min()),
        "parameter_max": float(parameter.max()),
        "growth_max": float((widths[:, 1:] / widths[:, :-1]).max()),
        "min_jacobian": minimum,
        "interfaces": count,
        "interface_error": error,
        "max_turning_deg": turning,
    }
    if p.law == "two_zone":
        nt = actual.transition_layers
        j = p.wall_layers + nt
        d.update(
            wall_layers=p.wall_layers,
            transition_layers=nt,
            core_layers=n - j,
            smoothing_change_percent=float(np.expm1(np.log(parameter.max()) / (nt + 1)) * 100),
            core_start_min=float(s[:, j].min()),
            core_start_max=float(s[:, j].max()),
            core_step_min=float(widths[:, j:].min()),
            core_step_max=float(widths[:, j:].max()),
        )
    if p.mode == "first_max" and d["max_wall"] > p.hmax * (1 + 1e-9):
        raise ValueError("Нарушен предел максимального размера")
    d.update(wall_geometry_diagnostics(arc, direction, widths[:, 0], p.d_rod / 2))
    if layer:
        verify_layer_interfaces(blocks, p)
        frontiers = []
        normals = []
        for (xx, yy), starts in zip(blocks, walls):
            coords = np.stack((xx, yy), axis=-1)
            outer = coords[:, -1] if starts else coords[:, 0]
            inner = coords[:, 0] if starts else coords[:, -1]
            vectors = outer - inner
            frontiers.append(outer.copy())
            normals.append(vectors / np.linalg.norm(vectors, axis=1)[:, None])
        reference_blocks = []
        for k in range(3):
            turn = rotation(o, 2 * np.pi * k / 3)
            reference_blocks += [
                transform(turn, (reference[:, :, 0], reference[:, :, 1])),
                transform(compose(turn, mo), (reference[:, :, 0], reference[:, :, 1])),
            ]
        other = [transform(ma, block) for block in reference_blocks]
        reference_blocks = reference_blocks + other if p.full else [reference_blocks[0], other[0]]
        outline = domain_outline(reference_blocks, p.pitch)
        d.update(
            layer_thickness_actual=thickness,
            layer_growth_actual=q,
            layer_last=float(wall[-1]),
            core_built=False,
        )
        return MeshResult(actual, p, blocks, walls, parameter, widths, s, d, False, frontiers, normals, outline)
    return MeshResult(actual, p, blocks, walls, parameter, widths, s, d)


def save_mesh(result, filename):
    if not result.complete:
        raise ValueError("Построен только пристеночный слой. Ядро не построено; экспорт полной сетки заблокирован.")
    p = result.params
    target = Path(filename)
    fd, temp = tempfile.mkstemp(prefix=".mesh_", suffix=".tmp", dir=target.parent)
    os.close(fd)
    try:
        with Path(temp).open("w", encoding="ascii", newline="\n") as f:
            f.write(f"{len(result.blocks)}\n")
            for _ in result.blocks:
                f.write(f"{p.ni} {p.nj} {p.nz + 1}\n")
            for x, y in result.blocks:
                for coordinate in (x, y, None):
                    for k in range(p.nz + 1):
                        flat = (
                            coordinate.ravel(order="F")
                            if coordinate is not None
                            else np.full(p.ni * p.nj, p.z_len * k / p.nz)
                        )
                        for start in range(0, len(flat), 6):
                            f.write(" ".join(f"{v:.16e}" for v in flat[start : start + 6]) + "\n")
        os.replace(temp, target)
    finally:
        Path(temp).unlink(missing_ok=True)
    return str(target)


def save_configuration(p, geometry_unit, cell_unit, filename, resolved=None):
    p.validate()
    if geometry_unit not in UNITS or cell_unit not in UNITS:
        raise ValueError("Неизвестная единица")
    data = {"version": 7, "geometry_unit": geometry_unit, "cell_unit": cell_unit, "parameters": asdict(p)}
    if resolved is not None:
        data["resolved_parameters"] = asdict(resolved)
    text = json.dumps(data, ensure_ascii=False, indent=2)
    target = Path(filename)
    fd, temp = tempfile.mkstemp(prefix=".settings_", suffix=".tmp", dir=target.parent)
    os.close(fd)
    try:
        with Path(temp).open("w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
    finally:
        Path(temp).unlink(missing_ok=True)


def load_configuration(filename):
    d = json.loads(Path(filename).read_text(encoding="utf-8"))
    version = d.get("version")
    if version not in (2, 3, 4, 5, 6, 7):
        raise ValueError("Неподдерживаемая версия настроек")
    values = dict(d["parameters"])
    if version < 4:
        values["smoothing"] = "manual"
    values = migrate_layer_values(values, version)
    p = MeshParams(**values)
    p.validate()
    gu = d.get("geometry_unit", d.get("unit", "мм"))
    cu = d.get("cell_unit", d.get("unit", "мкм"))
    if gu not in UNITS or cu not in UNITS:
        raise ValueError("Неизвестная единица настроек")
    return p, gu, cu


# ========================================================================
# Заполнение ядра без изменения слоя
# ========================================================================


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
    metadata = {"topology": topology} if isinstance(layer, MeshResult) else {}
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


# ========================================================================
# Typed settings and independent two-stage workflow (no Qt dependency)
# ========================================================================


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


def cli_main():
    parser = argparse.ArgumentParser(description="Заполнение ядра после независимого пристеночного слоя")
    parser.add_argument("--settings", help="JSON-настройки отдельного слоя версии 0.6.0")
    parser.add_argument("--growth", type=float, default=1.1, help="Номинальный коэффициент роста после слоя")
    parser.add_argument("--max-size-um", type=float, default=30.0, help="Предел шага в направлении от слоя, мкм")
    parser.add_argument("--max-cells", type=int, default=5000, help="Лимит числа ячеек ядра на линии")
    parser.add_argument("--output", default="mesh_with_core.xyz")
    parser.add_argument("--error-report", help="JSON-диагностика только при отказе; не проект")
    args = parser.parse_args()
    try:
        if "layer_thickness" not in MeshParams.__dataclass_fields__:
            raise CoreFillError("Нужна программа 0.6.0. Не заменяйте её mesh_core.py исходной версией 0.4.6.")
        if args.settings:
            p, gu, cu = load_configuration(args.settings)
            if p.law != "wall_core":
                raise CoreFillError("В JSON должен быть выбран отдельный пристеночный слой")
        else:
            p = MeshParams(law="wall_core", mode="layer_thickness", h1=5.7e-6, wall_layers=40, layer_thickness=350e-6)
            gu, cu = "мм", "мкм"
        layer = generate_mesh(p)
        complete = fill_core(layer, args.growth, args.max_size_um * 1e-6, args.max_cells)
        filename = save_mesh(complete, args.output)
        report = Path(args.output).with_suffix(".core.json")
        data = {
            "module": "core_fill",
            "layer_parameters": asdict(p),
            "geometry_unit": gu,
            "cell_unit": cu,
            "core_parameters": {
                "growth": args.growth,
                "max_size": args.max_size_um * 1e-6,
                "max_cells": args.max_cells,
            },
            "diagnostics": complete.diagnostics,
        }
        report.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        d = complete.diagnostics
        print("Сохранено:", filename)
        print("Отчёт:", report)
        print("Ячеек пристеночного слоя:", d["wall_layers"])
        print("Ячеек ядра на линии:", d["core_layers"])
        print("Постоянный шаг по линиям, мкм:", d["core_plateau_min"] * 1e6, "…", d["core_plateau_max"] * 1e6)
        print("Проверено стыков:", d["interfaces"])
        print("Угол изменения направления на выходе из слоя, град:", d["core_join_angle_max_deg"])
    except (ValueError, OSError) as exc:
        print("Ядро не построено:", exc, file=sys.stderr)
        if args.error_report:
            try:
                protected = {Path(args.output).resolve(), Path(args.output).with_suffix(".core.json").resolve()}
                if args.settings:
                    protected.add(Path(args.settings).resolve())
                if Path(args.error_report).resolve() in protected:
                    raise ValueError("Путь диагностики совпадает с настройками, XYZ или обычным отчётом CLI")
                save_diagnostic(
                    exc,
                    args.error_report,
                    context={
                        "settings_file": args.settings,
                        "output_file": args.output,
                        "growth": args.growth,
                        "max_size_um": args.max_size_um,
                        "max_cells": args.max_cells,
                    },
                )
            except (ValueError, OSError) as report_error:
                print("Не удалось сохранить диагностику:", report_error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(cli_main())
