# -*- coding: utf-8 -*-
"""Сохранение и загрузка сетки (Plot3D .xyz) и JSON-конфигураций."""
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path

import numpy as np

from mesh_layer import migrate_layer_values
from mesh_params import MeshParams, UNITS


def save_mesh(result, filename):
    """Сохранить полную структурированную сетку в формате Plot3D (.xyz)."""
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
    """Сохранить параметры сетки и единицы измерения в JSON."""
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
    """Загрузить параметры сетки и единицы измерения из JSON."""
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
