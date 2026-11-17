# -*- coding: utf-8 -*-
"""2D-преобразования, топология блоков и геометрические проверки сетки."""
from dataclasses import dataclass
from enum import Enum

import numpy as np


def reflection(point, direction):
    """Матрица и сдвиг отражения относительно прямой."""
    d = direction / np.linalg.norm(direction)
    a = 2 * np.outer(d, d) - np.eye(2)
    return a, point - a @ point


def rotation(center, angle):
    """Матрица и сдвиг поворота вокруг центра."""
    c, s = np.cos(angle), np.sin(angle)
    a = np.array([[c, -s], [s, c]])
    return a, center - a @ center


def compose(t1, t2):
    """Композиция двух аффинных преобразований."""
    return t1[0] @ t2[0], t1[0] @ t2[1] + t1[1]


def transform(t, block):
    """Применить аффинное преобразование к блоку координат (x, y)."""
    x, y = block
    v = t[0] @ np.stack((x.ravel(), y.ravel())) + t[1][:, None]
    x2, y2 = v.reshape((2,) + x.shape)
    return (x2[:, ::-1], y2[:, ::-1]) if np.linalg.det(t[0]) < 0 else (x2, y2)


def cross2(a, b):
    """Двумерное векторное произведение."""
    return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]


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
    """Построить описание топологии стыков для двухканальной модели."""
    if not isinstance(full, (bool, np.bool_)) or not isinstance(complete, (bool, np.bool_)):
        raise ValueError("full и complete должны быть логическими")
    state = MeshState.COMPLETE if complete else MeshState.LAYER_ONLY
    pairs = [(0, "i_max", 1, "i_max", True)]
    if full:
        pairs = [
            (0, "i_min", 5, "i_min", True),
            (0, "i_max", 6, "i_max", True),
            (1, "i_min", 2, "i_min", True),
            (1, "i_max", 7, "i_max", True),
            (3, "i_min", 4, "i_min", True),
            (6, "i_min", 11, "i_min", True),
            (7, "i_min", 8, "i_min", True),
            (9, "i_min", 10, "i_min", True),
        ]
        if complete:
            pairs += [
                (0, "j_max", 1, "j_min", False),
                (2, "j_max", 3, "j_min", False),
                (4, "j_max", 5, "j_min", False),
                (6, "j_min", 7, "j_max", False),
                (8, "j_min", 9, "j_max", False),
                (10, "j_min", 11, "j_max", False),
            ]
    return MeshTopology(
        "two_channels",
        state,
        bool(full),
        12 if full else 2,
        tuple(BlockInterface(*pair) for pair in pairs),
    )


def _block_faces(x, y):
    v = np.stack((x, y), axis=-1)
    return {"i_min": v[0], "i_max": v[-1], "j_min": v[:, 0], "j_max": v[:, -1]}


def _check_interfaces(blocks, topology, tolerance, reject_extra=True):
    if len(blocks) != topology.block_count:
        raise ValueError(f"Топология: требуется {topology.block_count} блоков, получено {len(blocks)}")
    faces = [_block_faces(x, y) for x, y in blocks]
    expected = set()
    maximum = 0.0
    for interface in topology.interfaces:
        a, b = interface.block_a, interface.block_b
        fa, fb = interface.face_a, interface.face_b
        va, vb = faces[a][fa], faces[b][fb]
        if interface.reversed:
            vb = vb[::-1]
        if va.shape != vb.shape:
            raise ValueError(f"Стык блоков {a + 1}:{fa} ↔ {b + 1}:{fb}: разные размеры граней")
        error = float(np.max(np.abs(va - vb)))
        if not np.isfinite(error) or error > tolerance:
            raise ValueError(
                f"Не совпадает ожидаемый стык между блоками {a + 1}:{fa} и {b + 1}:{fb}; "
                f"расхождение {error:.8g} м, допуск {tolerance:.8g} м"
            )
        maximum = max(maximum, error)
        expected.add(frozenset(((a, fa), (b, fb))))
    if reject_extra:
        entries = [(k, name, face) for k, group in enumerate(faces) for name, face in group.items()]
        for index, (a, fa, va) in enumerate(entries):
            for b, fb, vb in entries[index + 1 :]:
                if a == b or va.shape != vb.shape:
                    continue
                if frozenset(((a, fa), (b, fb))) in expected:
                    continue
                error = min(float(np.abs(va - vb).max()), float(np.abs(va - vb[::-1]).max()))
                if error <= tolerance:
                    raise ValueError(f"Неожиданное совпадение граней {a + 1}:{fa} и {b + 1}:{fb}")
    return len(topology.interfaces), maximum


def check_mesh(blocks, p=None, *, topology=None):
    """Проверить корректность сетки (якобиан, углы поворота и стыки блоков)."""
    if p is None:
        result = blocks
        if not all(hasattr(result, name) for name in ("blocks", "params", "complete")):
            raise ValueError("Передайте MeshResult либо blocks и params")
        p = result.params
        expected = mesh_topology(p.full, result.complete)
        stored = getattr(result, "topology", None)
        if stored is not None and stored != expected:
            raise ValueError("Топология не соответствует состоянию результата")
        if topology is not None and topology != expected:
            raise ValueError("Переданная топология не соответствует состоянию результата")
        topology = stored or expected
        blocks = result.blocks
    if topology is None:
        topology = mesh_topology(p.full, complete=True)
    if not isinstance(topology, MeshTopology) or topology != mesh_topology(
        p.full, topology.state == MeshState.COMPLETE
    ):
        raise ValueError("Неподдерживаемая или несогласованная топология")
    if len(blocks) != topology.block_count:
        raise ValueError(f"Топология: требуется {topology.block_count} блоков, получено {len(blocks)}")
    if not np.isfinite(p.pitch) or p.pitch <= 0 or p.ni < 2 or p.nj < 2:
        raise ValueError("Некорректные параметры геометрической проверки")

    minimum = np.inf
    turning = 0.0
    for k, (x, y) in enumerate(blocks):
        v = np.stack((x, y), axis=-1)
        if v.shape != (p.ni, p.nj, 2) or not np.all(np.isfinite(v)):
            raise ValueError("Некорректные координаты блока")
        a, b, c, d = v[:-1, :-1], v[1:, :-1], v[1:, 1:], v[:-1, 1:]
        jac = np.stack((cross2(b - a, d - a), cross2(b - a, c - b), cross2(c - d, c - b), cross2(c - d, d - a)))
        if np.any(jac <= 0):
            raise ValueError(f"Блок {k + 1}: вырожденные или перевёрнутые ячейки")
        minimum = min(minimum, float(jac.min()))
        edge = np.diff(v, axis=0)
        if len(edge) > 1:
            cosine = np.sum(edge[:-1] * edge[1:], axis=-1) / (
                np.linalg.norm(edge[:-1], axis=-1) * np.linalg.norm(edge[1:], axis=-1)
            )
            turning = max(turning, float(np.degrees(np.arccos(np.clip(cosine, -1, 1))).max()))
    count, error = _check_interfaces(blocks, topology, p.pitch * 1e-12)
    return minimum, count, error, turning


def wall_geometry_diagnostics(arc, direction, widths, radius):
    """Диагностика углов отклонения от нормали и пристеночных расстояний."""
    normal = arc / np.linalg.norm(arc, axis=1)[:, None]
    unit = direction / np.linalg.norm(direction, axis=1)[:, None]
    dot = np.sum(normal * unit, axis=1)
    angle = np.degrees(np.arctan2(np.abs(cross2(normal, unit)), dot))
    index = int(np.argmax(angle))
    projection = widths * dot
    first = arc + widths[:, None] * unit
    distance = widths * (2 * radius * dot + widths) / (np.linalg.norm(first, axis=1) + radius)
    return dict(
        wall_normal_angle_max_deg=float(angle[index]),
        wall_normal_angle_max_line=index + 1,
        wall_normal_angle_max_theta_deg=float(np.degrees(np.arctan2(arc[index, 1], arc[index, 0]))),
        first_normal_projection_min=float(projection.min()),
        first_normal_projection_max=float(projection.max()),
        first_wall_distance_min=float(distance.min()),
        first_wall_distance_max=float(distance.max()),
    )


def verify_layer_interfaces(blocks, p):
    """Проверить стыки блоков для режима независимого пристеночного слоя."""
    _check_interfaces(blocks, mesh_topology(p.full, complete=False), p.pitch * 1e-12)


def domain_outline(blocks, pitch):
    """Найти внешние (непарные) грани расчётной области."""
    faces = []
    for xx, yy in blocks:
        v = np.stack((xx, yy), axis=-1)
        faces.extend([v[0], v[-1], v[:, 0], v[:, -1]])
    outline = []
    for i, face in enumerate(faces):
        shared = False
        for j, other in enumerate(faces):
            if i == j or face.shape != other.shape:
                continue
            error = min(float(np.abs(face - other).max()), float(np.abs(face - other[::-1]).max()))
            if error <= pitch * 1e-12:
                shared = True
                break
        if not shared:
            outline.append(face.copy())
    return outline
