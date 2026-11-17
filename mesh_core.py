# -*- coding: utf-8 -*-
"""Расчёт сетки, независимый слой, заполнение ядра и терминальный запуск.

Не требует Qt. Запуск CLI: python mesh_core.py --help
"""
import argparse
import json
import sys
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

import numpy as np

from mesh_core_fill import (  # noqa: F401
    CoreDistribution,
    CoreFillError,
    MeshDiagnosticError,
    capped_distribution,
    fill_core,
    fixed_count_distribution,
    save_diagnostic,
)
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
from mesh_io import (  # noqa: F401
    load_configuration,
    save_configuration,
    save_mesh,
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
from mesh_workflow import (  # noqa: F401
    CoreParams,
    GeometryParams,
    MeshWorkflow,
    WallLayerParams,
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
