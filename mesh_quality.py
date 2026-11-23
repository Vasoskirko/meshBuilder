# -*- coding: utf-8 -*-
"""Метрики качества структурированных блоков. Нужен только NumPy, Qt не требуется.

Работает с произвольным списком трёхмерных блоков (ni, nj, nk, 3), не завязан
на геометрию двух каналов. Длины — в единицах входных координат, углы — в градусах.
Метрики определены ниже в явном виде и НЕ обязаны совпадать с одноимёнными
метриками конкретных программ (STAR-CCM+, OpenFOAM и т.д.).
"""
from dataclasses import dataclass
from pathlib import Path
import argparse
import itertools
import json
import math
import os
import sys
import tempfile

import numpy as np

FORMAT = "mesh-quality"
VERSION = 1
FACES = ("i_min", "i_max", "j_min", "j_max")
CELL_METRICS = ("volume", "scaled_jacobian", "skewness", "aspect_ratio")
FACE_METRICS = ("non_orthogonality_deg", "neighbor_volume_ratio")
ALL_METRICS = CELL_METRICS + FACE_METRICS
# Для scaled_jacobian порог означает «значение ниже порога», для остальных — «выше».
BELOW_IS_BAD = {"scaled_jacobian"}
NO_THRESHOLD = {"volume"}


class QualityError(ValueError):
    """Некорректные блоки, стыки или параметры анализа."""


@dataclass(frozen=True)
class Interface:
    block_a: int
    face_a: str
    block_b: int
    face_b: str
    reversed: bool = False


def as_block(block, index=0):
    """Приводит блок к ndarray формы (ni, nj, nk, 3); индекс блока в сообщениях с 1."""
    label = f"Блок {index + 1}"
    if isinstance(block, np.ndarray):
        a = np.asarray(block, dtype=float)
    else:
        parts = list(block)
        if len(parts) == 2:
            raise QualityError(f"{label}: передано два массива (x, y); используйте extrude_blocks()")
        if len(parts) != 3:
            raise QualityError(f"{label}: ожидается (x, y, z) или массив (ni, nj, nk, 3)")
        a = np.stack([np.asarray(c, dtype=float) for c in parts], axis=-1)
    if a.ndim != 4 or a.shape[-1] != 3:
        raise QualityError(f"{label}: ожидается форма (ni, nj, nk, 3), получено {a.shape}")
    if min(a.shape[:3]) < 2:
        raise QualityError(f"{label}: в каждом направлении нужно не менее 2 узлов, получено {a.shape[:3]}")
    if not np.all(np.isfinite(a)):
        bad = np.argwhere(~np.isfinite(a).all(axis=-1))[0] + 1
        raise QualityError(f"{label}: нечисловая координата, узел {tuple(int(v) for v in bad)} (нумерация с 1)")
    return a


def extrude_blocks(blocks2d, z_nodes):
    """Продолжает блоки (x, y) вдоль оси z на уровнях z_nodes."""
    z = np.asarray(z_nodes, dtype=float)
    if z.ndim != 1 or z.size < 2 or not np.all(np.isfinite(z)):
        raise QualityError("z_nodes: нужен вектор из не менее 2 конечных значений")
    out = []
    for n, (x, y) in enumerate(blocks2d):
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        if x.shape != y.shape or x.ndim != 2:
            raise QualityError(f"Блок {n + 1}: x и y должны быть двумерными одинаковой формы")
        out.append(np.stack([np.repeat(x[:, :, None], z.size, 2),
                             np.repeat(y[:, :, None], z.size, 2),
                             np.broadcast_to(z, x.shape + (z.size,)).copy()], axis=-1))
    return out


def blocks_from_result(result):
    """Трёхмерные блоки результата генератора (z как в save_mesh)."""
    p = result.params
    z = p.z_len * np.arange(p.nz + 1) / p.nz
    return extrude_blocks(result.blocks, z)


def interfaces_from_topology(items):
    """Принимает объекты с полями block_a/face_a/block_b/face_b/reversed либо кортежи."""
    out = []
    for item in items:
        if hasattr(item, "block_a"):
            out.append(Interface(int(item.block_a), str(item.face_a), int(item.block_b), str(item.face_b), bool(item.reversed)))
        else:
            a, fa, b, fb, rev = item
            out.append(Interface(int(a), str(fa), int(b), str(fb), bool(rev)))
    return out


def _norm(v):
    return np.sqrt(np.einsum("...i,...i", v, v))


def _dot(a, b):
    return np.einsum("...i,...i", a, b)


def _corner(x, a, b, c):
    ni, nj, nk = x.shape[:3]
    return x[a:ni - 1 + a, b:nj - 1 + b, c:nk - 1 + c]


def _divide(num, den, default):
    out = np.full(np.broadcast(num, den).shape, default, dtype=float)
    np.divide(num, den, out=out, where=den > 0)
    return out


def _plane_vectors(n00, n10, n11, n01):
    """Вектор площади и центр четырёхугольной грани; направление u x v."""
    return 0.5 * np.cross(n11 - n00, n01 - n10), 0.25 * (n00 + n10 + n11 + n01)


def _faces(x):
    """Векторы площади и центры узловых плоскостей по направлениям i, j, k."""
    si = _plane_vectors(x[:, :-1, :-1], x[:, 1:, :-1], x[:, 1:, 1:], x[:, :-1, 1:])
    sj = _plane_vectors(x[:-1, :, :-1], x[:-1, :, 1:], x[1:, :, 1:], x[1:, :, :-1])
    sk = _plane_vectors(x[:-1, :-1, :], x[1:, :-1, :], x[1:, 1:, :], x[:-1, 1:, :])
    return si, sj, sk


def _centers_volumes(x, faces):
    """Центр ячейки (среднее 8 вершин) и объём по теореме о дивергенции."""
    centre = sum(_corner(x, a, b, c) for a, b, c in itertools.product((0, 1), repeat=3)) / 8.0
    (si, xi), (sj, xj), (sk, xk) = faces
    vi = _dot(si[1:], xi[1:] - centre) - _dot(si[:-1], xi[:-1] - centre)
    vj = _dot(sj[:, 1:], xj[:, 1:] - centre) - _dot(sj[:, :-1], xj[:, :-1] - centre)
    vk = _dot(sk[:, :, 1:], xk[:, :, 1:] - centre) - _dot(sk[:, :, :-1], xk[:, :, :-1] - centre)
    return centre, (vi + vj + vk) / 3.0


def cell_metrics(block):
    """Поячеечные массивы формы (ni-1, nj-1, nk-1) для одного блока."""
    x = as_block(block)
    p = [[[_corner(x, a, b, c) for c in (0, 1)] for b in (0, 1)] for a in (0, 1)]
    ei = [[p[1][b][c] - p[0][b][c] for c in (0, 1)] for b in (0, 1)]
    ej = [[p[a][1][c] - p[a][0][c] for c in (0, 1)] for a in (0, 1)]
    ek = [[p[a][b][1] - p[a][b][0] for b in (0, 1)] for a in (0, 1)]
    length_i = sum(_norm(ei[b][c]) for b in (0, 1) for c in (0, 1)) / 4.0
    length_j = sum(_norm(ej[a][c]) for a in (0, 1) for c in (0, 1)) / 4.0
    length_k = sum(_norm(ek[a][b]) for a in (0, 1) for b in (0, 1)) / 4.0
    longest = np.maximum(np.maximum(length_i, length_j), length_k)
    shortest = np.minimum(np.minimum(length_i, length_j), length_k)
    aspect = np.full(longest.shape, np.inf)
    np.divide(longest, shortest, out=aspect, where=shortest > 0)
    sj_min = np.full(longest.shape, np.inf)
    deviation = np.zeros(longest.shape)
    for a, b, c in itertools.product((0, 1), repeat=3):
        u, v, w = ei[b][c], ej[a][c], ek[a][b]
        nu, nv, nw = _norm(u), _norm(v), _norm(w)
        scaled = _divide(_dot(u, np.cross(v, w)), nu * nv * nw, 0.0)
        sj_min = np.minimum(sj_min, scaled)
        su, sv, sw = u * (1 - 2 * a), v * (1 - 2 * b), w * (1 - 2 * c)
        for s, t in ((su, sv), (sv, sw), (su, sw)):
            angle = np.arctan2(_norm(np.cross(s, t)), _dot(s, t))
            deviation = np.maximum(deviation, np.abs(angle - 0.5 * math.pi))
    _, volume = _centers_volumes(x, _faces(x))
    return {"volume": volume, "scaled_jacobian": sj_min, "skewness": deviation / (0.5 * math.pi),
            "aspect_ratio": aspect, "length_i": length_i, "length_j": length_j, "length_k": length_k}


def _internal_face_metrics(x):
    """Для каждого направления: угол неортогональности и отношение объёмов соседей."""
    faces = _faces(x)
    centre, volume = _centers_volumes(x, faces)
    out = []
    for axis, (s, _) in enumerate(faces):
        n = volume.shape[axis]
        if n < 2:
            out.append(None)
            continue
        lo = [slice(None)] * 3
        hi = [slice(None)] * 3
        lo[axis] = slice(0, n - 1)
        hi[axis] = slice(1, n)
        inner = [slice(None)] * 3
        inner[axis] = slice(1, n)
        d = centre[tuple(hi)] - centre[tuple(lo)]
        area = s[tuple(inner)]
        cosine = _divide(np.abs(_dot(area, d)), _norm(area) * _norm(d), 0.0)
        angle = np.degrees(np.arccos(np.clip(cosine, 0.0, 1.0)))
        va, vb = volume[tuple(lo)], volume[tuple(hi)]
        hi_v, lo_v = np.maximum(va, vb), np.minimum(va, vb)
        ratio = np.full(va.shape, np.inf)
        np.divide(hi_v, lo_v, out=ratio, where=lo_v > 0)
        out.append((angle, ratio))
    return out, centre, volume


def _face_slices(face):
    axis, side = face.split("_")
    index = 0 if side == "min" else -1
    return (index, slice(None), slice(None)) if axis == "i" else (slice(None), index, slice(None))


def _layer(x, centre, volume, face):
    sl = _face_slices(face)
    return np.array(x[sl]), np.array(centre[sl]), np.array(volume[sl])


def detect_interfaces(blocks, tolerance=None, relative=1e-10):
    """Находит совпадающие грани i/j разных блоков; возвращает (интерфейсы, предупреждения, допуск)."""
    arrays = [as_block(b, n) for n, b in enumerate(blocks)]
    if tolerance is None:
        lo = np.min([a.reshape(-1, 3).min(axis=0) for a in arrays], axis=0)
        hi = np.max([a.reshape(-1, 3).max(axis=0) for a in arrays], axis=0)
        tolerance = relative * float(np.linalg.norm(hi - lo))
    faces = [(n, f, arrays[n][_face_slices(f)]) for n in range(len(arrays)) for f in FACES]
    found, used, warnings = [], {}, []
    for ia, (na, fa, va) in enumerate(faces):
        for nb, fb, vb in faces[ia + 1:]:
            if na == nb or va.shape != vb.shape:
                continue
            direct = float(np.max(np.abs(va - vb)))
            flipped = float(np.max(np.abs(va - vb[::-1])))
            best = min(direct, flipped)
            if best <= tolerance:
                for key in ((na, fa), (nb, fb)):
                    used[key] = used.get(key, 0) + 1
                found.append(Interface(na, fa, nb, fb, flipped < direct))
    ambiguous = sorted(k for k, v in used.items() if v > 1)
    if ambiguous:
        warnings.append("Грани совпадают более чем с одной гранью: " + ", ".join(f"блок {n + 1}:{f}" for n, f in ambiguous))
    return found, warnings, tolerance


class _Accumulator:
    def __init__(self, name, scope):
        self.name, self.scope = name, scope
        self.bad_is_low = name in BELOW_IS_BAD
        self.count = self.nonfinite = 0
        self.total = 0.0
        self.low = self.high = None
        self.low_where = self.high_where = None
        self.exceed = {}
        self.per_block = {}
        # Непересекающиеся зоны для интерпретации, ключ — risk-порог:
        # zone_ok — без замечаний, zone_caution — предупреждение (без красной зоны),
        # zone_risk — высокий риск, zone_nonfinite — невычисленные значения.
        self.zone_ok = {}
        self.zone_caution = {}
        self.zone_risk = {}
        self.zone_nonfinite = {}
        # True, если порог передан как caution-уровень (без risk): зона у порога — жёлтая, а не красная
        self.threshold_is_caution = {}

    def add(self, values, locate, block):
        values = np.asarray(values, dtype=float)
        finite = np.isfinite(values)
        self.count += values.size
        self.nonfinite += int(values.size - np.count_nonzero(finite))
        if finite.any():
            self.total += float(values[finite].sum())
            safe = np.where(finite, values, np.nan)
            imin, imax = int(np.nanargmin(safe)), int(np.nanargmax(safe))
            vmin, vmax = float(safe.flat[imin]), float(safe.flat[imax])
            if self.low is None or vmin < self.low:
                self.low, self.low_where = vmin, locate(np.unravel_index(imin, values.shape))
            if self.high is None or vmax > self.high:
                self.high, self.high_where = vmax, locate(np.unravel_index(imax, values.shape))
            if block is not None:
                worst = vmin if self.bad_is_low else vmax
                old = self.per_block.get(block)
                if old is None or (worst < old if self.bad_is_low else worst > old):
                    self.per_block[block] = worst

    def add_threshold(self, values, threshold, caution=None):
        """Считает непересекающиеся зоны. Граница порога включается в худшую зону.

        Для метрик «меньше — хуже» (scaled_jacobian): risk — значение <= threshold,
        caution — threshold < значение <= caution, ok — значение > caution.
        Для метрик «больше — хуже»: risk — значение >= threshold,
        caution — caution <= значение < threshold, ok — значение < caution.
        """
        values = np.asarray(values, dtype=float)
        finite = np.isfinite(values)
        hits = values < threshold if self.bad_is_low else values > threshold
        self.exceed[threshold] = self.exceed.get(threshold, 0) + int(np.count_nonzero(hits))
        risk_mask = np.zeros(values.shape, dtype=bool)
        caution_mask = np.zeros(values.shape, dtype=bool)
        ok_mask = finite.copy()
        if self.bad_is_low:
            if caution is not None:
                risk_mask = finite & (values <= threshold)
                caution_mask = finite & (values > threshold) & (values <= caution)
                ok_mask = finite & (values > caution)
            else:
                risk_mask = finite & (values <= threshold)
                caution_mask = np.zeros(values.shape, dtype=bool)
                ok_mask = finite & (values > threshold)
        else:
            if caution is not None:
                risk_mask = finite & (values >= threshold)
                caution_mask = finite & (values >= caution) & (values < threshold)
                ok_mask = finite & (values < caution)
            else:
                risk_mask = finite & (values >= threshold)
                caution_mask = np.zeros(values.shape, dtype=bool)
                ok_mask = finite & (values < threshold)
        nonfinite_mask = ~finite
        if self.threshold_is_caution.get(threshold):
            # порог — это caution-уровень: зона у порога — жёлтая, красная пустая
            self.zone_caution[threshold] = self.zone_caution.get(threshold, 0) + int(np.count_nonzero(risk_mask))
            self.zone_risk[threshold] = self.zone_risk.get(threshold, 0) + int(np.count_nonzero(caution_mask))
        else:
            self.zone_risk[threshold] = self.zone_risk.get(threshold, 0) + int(np.count_nonzero(risk_mask))
            self.zone_caution[threshold] = self.zone_caution.get(threshold, 0) + int(np.count_nonzero(caution_mask))
        self.zone_ok[threshold] = self.zone_ok.get(threshold, 0) + int(np.count_nonzero(ok_mask))
        self.zone_nonfinite[threshold] = self.zone_nonfinite.get(threshold, 0) + int(np.count_nonzero(nonfinite_mask))

    def result(self, thresholds):
        finite_count = self.count - self.nonfinite
        worst = self.low if self.bad_is_low else self.high
        where = self.low_where if self.bad_is_low else self.high_where
        item = {"scope": self.scope, "worst_is": "min" if self.bad_is_low else "max", "count": self.count,
                "nonfinite": self.nonfinite, "min": self.low, "max": self.high,
                "mean": None if finite_count == 0 else self.total / finite_count,
                "worst_value": worst, "worst_location": where,
                "per_block_worst": {str(k + 1): v for k, v in sorted(self.per_block.items())}}
        if self.name in thresholds:
            t = float(thresholds[self.name])
            item["threshold"] = {"value": t, "bad_when": "below" if self.bad_is_low else "above",
                                 "count": self.exceed.get(t, 0)}
            if t in self.zone_risk:
                item["zone_ok_count"] = self.zone_ok.get(t, 0)
                item["zone_caution_count"] = self.zone_caution.get(t, 0)
                item["zone_risk_count"] = self.zone_risk.get(t, 0)
                item["zone_nonfinite_count"] = self.zone_nonfinite.get(t, 0)
        return item


def _cell_where(block):
    return lambda idx: {"kind": "cell", "block": block + 1, "cell": [int(v) + 1 for v in idx], "index_base": 1}


def _face_where(block, axis):
    def locate(idx):
        a = [int(v) + 1 for v in idx]
        b = list(a)
        b["ijk".index(axis)] += 1
        return {"kind": "internal_face", "block": block + 1, "axis": axis, "between_cells": [a, b], "index_base": 1}
    return locate


def _validate_interfaces(interfaces, count):
    for it in interfaces:
        for block in (it.block_a, it.block_b):
            if not 0 <= block < count:
                raise QualityError(f"Стык ссылается на несуществующий блок {block + 1}")
        for face in (it.face_a, it.face_b):
            if face not in FACES:
                raise QualityError(f"Неподдерживаемая грань стыка {face!r}; допустимы {FACES}")
        if it.block_a == it.block_b:
            raise QualityError("Стык блока с самим собой не поддерживается")


def analyse_blocks(blocks, interfaces=None, *, thresholds=None, tolerance=None, profile=None, progress_callback=None):
    """Сводный отчёт. interfaces=None — найти автоматически, [] — стыков нет."""
    thresholds = dict(thresholds or {})
    caution_only = {}
    if profile is not None:
        # Проверить и нормализовать профиль; любой заданный уровень (risk или caution)
        # становится порогом для накопления зон. Прежняя семантика CLI threshold не меняется:
        # без профиля порог работает как раньше (только счётчик exceed).
        profile = validate_profile(profile)
        for name, p in profile.items():
            risk = p.get("risk")
            caution = p.get("caution")
            if risk is not None:
                thresholds[name] = risk
            elif caution is not None:
                # только caution: порог — caution-уровень, зона у порога — жёлтая
                thresholds[name] = caution
                caution_only[name] = float(caution)
    for name in thresholds:
        if name not in ALL_METRICS or name in NO_THRESHOLD:
            raise QualityError(f"Порог для {name!r} не поддерживается")
        if not math.isfinite(float(thresholds[name])):
            raise QualityError(f"Порог {name} должен быть конечным числом")
    arrays = [as_block(b, n) for n, b in enumerate(blocks)]
    if not arrays:
        raise QualityError("Пустой список блоков")
    warnings = []
    source = "explicit"
    if interfaces is None:
        interfaces, warnings, tolerance = detect_interfaces(arrays, tolerance)
        source = "detected"
    else:
        interfaces = interfaces_from_topology(interfaces)
        _validate_interfaces(interfaces, len(arrays))
        if tolerance is None:
            lo = np.min([a.reshape(-1, 3).min(axis=0) for a in arrays], axis=0)
            hi = np.max([a.reshape(-1, 3).max(axis=0) for a in arrays], axis=0)
            tolerance = 1e-10 * float(np.linalg.norm(hi - lo))
    needed = {(it.block_a, it.face_a) for it in interfaces} | {(it.block_b, it.face_b) for it in interfaces}
    acc = {name: _Accumulator(name, "cell" if name in CELL_METRICS else "face") for name in ALL_METRICS}
    for name, value in caution_only.items():
        acc[name].threshold_is_caution[value] = True
    layers, summary_blocks = {}, []
    invalid_volume = invalid_jacobian = 0
    for n, x in enumerate(arrays):
        if progress_callback:progress_callback(.1+.8*n/len(arrays),f'Качество блока {n+1}/{len(arrays)}')
        cm = cell_metrics(x)
        for name in CELL_METRICS:
            acc[name].add(cm[name], _cell_where(n), n)
            if name in thresholds:
                p_ = (profile or {}).get(name)
                caution = p_.get("caution") if isinstance(p_, dict) else None
                risk_ = p_.get("risk") if isinstance(p_, dict) else None
                # если risk не задан, порог — это caution; не передавать его как отдельную границу
                if risk_ is None:
                    caution = None
                acc[name].add_threshold(cm[name], float(thresholds[name]), caution=caution)
        invalid_volume += int(np.count_nonzero(~(cm["volume"] > 0)))
        invalid_jacobian += int(np.count_nonzero(~(cm["scaled_jacobian"] > 0)))
        faces_internal, centre, volume = _internal_face_metrics(x)
        for axis, item in zip("ijk", faces_internal):
            if item is None:
                continue
            angle, ratio = item
            for name, values in (("non_orthogonality_deg", angle), ("neighbor_volume_ratio", ratio)):
                acc[name].add(values, _face_where(n, axis), n)
                if name in thresholds:
                    p_ = (profile or {}).get(name)
                    caution = p_.get("caution") if isinstance(p_, dict) else None
                    risk_ = p_.get("risk") if isinstance(p_, dict) else None
                    if risk_ is None:
                        caution = None
                    acc[name].add_threshold(values, float(thresholds[name]), caution=caution)
        for face in FACES:
            if (n, face) in needed:
                layers[(n, face)] = _layer(x, centre, volume, face)
        summary_blocks.append({"index": n + 1, "dims": [int(v) for v in x.shape[:3]],
                               "cells": int(cm["volume"].size), "nodes": int(x.shape[0] * x.shape[1] * x.shape[2])})
        del cm, faces_internal, centre, volume
    interface_report = []
    for number, it in enumerate(interfaces):
        xa, ca, va = layers[(it.block_a, it.face_a)]
        xb, cb, vb = layers[(it.block_b, it.face_b)]
        record = {"interface": number + 1, "block_a": it.block_a + 1, "face_a": it.face_a,
                  "block_b": it.block_b + 1, "face_b": it.face_b, "reversed": it.reversed, "matched": False}
        if it.reversed:
            xb, cb, vb = xb[::-1], cb[::-1], vb[::-1]
        if xa.shape != xb.shape:
            record["reason"] = "shape_mismatch"
            warnings.append(f"Стык {number + 1}: разные размеры граней {xa.shape[:2]} и {xb.shape[:2]}")
            interface_report.append(record)
            continue
        gap = float(np.max(np.abs(xa - xb)))
        record["max_node_gap"] = gap
        if gap > tolerance:
            record["reason"] = "nodes_do_not_coincide"
            warnings.append(f"Стык {number + 1}: узлы не совпадают, максимальное расхождение {gap:.8g}")
            interface_report.append(record)
            continue
        record["matched"] = True
        area, _ = _plane_vectors(xa[:-1, :-1], xa[1:, :-1], xa[1:, 1:], xa[:-1, 1:])
        d = cb - ca
        cosine = _divide(np.abs(_dot(area, d)), _norm(area) * _norm(d), 0.0)
        angle = np.degrees(np.arccos(np.clip(cosine, 0.0, 1.0)))
        hi_v, lo_v = np.maximum(va, vb), np.minimum(va, vb)
        ratio = np.full(va.shape, np.inf)
        np.divide(hi_v, lo_v, out=ratio, where=lo_v > 0)

        def locate(idx, it=it, number=number, rows=va.shape[0]):
            along, k = (int(v) for v in idx)
            other = rows - 1 - along if it.reversed else along
            return {"kind": "interface", "interface": number + 1, "block_a": it.block_a + 1, "face_a": it.face_a,
                    "along_cell_a": along + 1, "block_b": it.block_b + 1, "face_b": it.face_b,
                    "along_cell_b": other + 1, "layer_cell": k + 1, "index_base": 1}
        for name, values in (("non_orthogonality_deg", angle), ("neighbor_volume_ratio", ratio)):
            acc[name].add(values, locate, None)
            if name in thresholds:
                p_ = (profile or {}).get(name)
                caution = p_.get("caution") if isinstance(p_, dict) else None
                risk_ = p_.get("risk") if isinstance(p_, dict) else None
                if risk_ is None:
                    caution = None
                acc[name].add_threshold(values, float(thresholds[name]), caution=caution)
        interface_report.append(record)
    report = {"format": FORMAT, "version": VERSION, "units": {"length": "input", "angle": "deg"},
            "definitions": DEFINITIONS, "blocks": summary_blocks,
            "totals": {"blocks": len(arrays), "cells": sum(b["cells"] for b in summary_blocks),
                       "nodes": sum(b["nodes"] for b in summary_blocks)},
            "interfaces": {"source": source, "count": len(interfaces), "matched": sum(1 for r in interface_report if r["matched"]),
                           "tolerance": float(tolerance), "items": interface_report},
            "invalid": {"non_positive_volume_cells": invalid_volume, "non_positive_scaled_jacobian_cells": invalid_jacobian},
            "metrics": {name: acc[name].result(thresholds) for name in ALL_METRICS},
            "warnings": warnings}
    if profile is not None:
        # Профиль, по которому рассчитаны зоны; None означает отсутствие зон.
        report["quality_profile"] = {"version": PROFILE_VERSION,
                                     "thresholds": {k: dict(v) for k, v in profile.items()},
                                     "boundary_included_in_worse_zone": True}
    if progress_callback:progress_callback(1.,'Проверка качества завершена')
    return report


DEFINITIONS = {
    "volume": "Объём ячейки по теореме о дивергенции; положителен для правой системы i,j,k.",
    "scaled_jacobian": "Минимум по 8 углам det(e_i,e_j,e_k)/(|e_i||e_j||e_k|); 1 — идеал, <=0 — вырождена или вывернута.",
    "skewness": "Эквиугловая: max|угол грани - 90 градусов|/90 по всем 24 углам граней; 0 — идеал, 1 — вырождена.",
    "aspect_ratio": "Отношение наибольшей к наименьшей из средних длин рёбер по направлениям i, j, k.",
    "non_orthogonality_deg": "Угол между нормалью грани и линией центров соседних ячеек; центр ячейки — среднее 8 вершин; для внутренних граней и стыков блоков, граничные грани не учитываются.",
    "neighbor_volume_ratio": "Отношение большего объёма к меньшему для соседей через внутреннюю грань или стык блоков."}


def analyse_result(result, **kwargs):
    """Анализ результата генератора с использованием его явной топологии стыков."""
    blocks = blocks_from_result(result)
    topology = getattr(result, "topology", None)
    interfaces = None if topology is None else topology.interfaces
    return analyse_blocks(blocks, interfaces, **kwargs)


def read_plot3d_ascii(path):
    tokens = Path(path).read_text(encoding="ascii").split()
    try:
        count = int(tokens[0])
        dims = [tuple(int(v) for v in tokens[1 + 3 * i:4 + 3 * i]) for i in range(count)]
    except (ValueError, IndexError) as exc:
        raise QualityError("Файл не похож на ASCII Plot3D: заголовок блоков не читается") from exc
    if count < 1 or any(len(d) != 3 or min(d) < 2 for d in dims):
        raise QualityError("Размеры блоков должны быть не менее 2 по каждому направлению")
    values = np.array(tokens[1 + 3 * count:], dtype=float)
    expected = 3 * sum(a * b * c for a, b, c in dims)
    if values.size != expected:
        raise QualityError(f"Ожидалось {expected} координат, найдено {values.size}")
    blocks, pos = [], 0
    for ni, nj, nk in dims:
        size = ni * nj * nk
        comp = [values[pos + m * size:pos + (m + 1) * size].reshape((ni, nj, nk), order="F") for m in range(3)]
        pos += 3 * size
        blocks.append(np.stack(comp, axis=-1))
    return blocks


def _clean(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else ("NaN" if math.isnan(value) else "Infinity" if value > 0 else "-Infinity")
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    return value


def save_report(report, filename):
    text = json.dumps(_clean(report), ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    target = Path(filename)
    fd, temp = tempfile.mkstemp(prefix=".quality_", suffix=".tmp", dir=target.parent)
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


def format_report(report):
    names = {"volume": "объём ячейки", "scaled_jacobian": "масштаб. якобиан (мин. по углам)", "skewness": "скошенность (эквиугл.)",
             "aspect_ratio": "вытянутость", "non_orthogonality_deg": "неортогональность, град", "neighbor_volume_ratio": "отн. объёмов соседей"}
    t = report["totals"]
    lines = [f"Блоков: {t['blocks']}, ячеек: {t['cells']}, узлов: {t['nodes']}; стыков: {report['interfaces']['count']} "
             f"({report['interfaces']['source']}, совпало {report['interfaces']['matched']})",
             f"Ячеек с неположительным объёмом: {report['invalid']['non_positive_volume_cells']}; "
             f"с неположительным якобианом: {report['invalid']['non_positive_scaled_jacobian_cells']}", ""]
    for name in ALL_METRICS:
        m = report["metrics"][name]
        mean = "—" if m["mean"] is None else f"{m['mean']:.6g}"
        low = "—" if m["min"] is None else f"{m['min']:.6g}"
        high = "—" if m["max"] is None else f"{m['max']:.6g}"
        lines.append(f"{names[name]:36s} min {low:>12s}  max {high:>12s}  среднее {mean:>12s}  [{m['scope']}]")
        if m["nonfinite"]:
            lines.append(f"{'':36s} нечисловых значений: {m['nonfinite']}")
        if "threshold" in m:
            th = m["threshold"]
            lines.append(f"{'':36s} порог {th['value']:g} ({'ниже' if th['bad_when'] == 'below' else 'выше'}): {th['count']}")
        if name != "volume" and m["worst_location"]:
            lines.append(f"{'':36s} худшее значение {m['worst_value']:.6g}: {json.dumps(m['worst_location'], ensure_ascii=False)}")
    for w in report["warnings"]:
        lines.append("ПРЕДУПРЕЖДЕНИЕ: " + w)
    return "\n".join(lines)


def _parse_thresholds(items):
    out = {}
    for item in items or []:
        name, sep, value = item.partition("=")
        if not sep:
            raise QualityError(f"Порог должен иметь вид имя=значение, получено {item!r}")
        try:
            out[name.strip()] = float(value)
        except ValueError as exc:
            raise QualityError(f"Некорректное число порога: {item!r}") from exc
    return out



# ---------------- Интерпретация отчёта для интерфейса ----------------

# Базовый профиль порогов: ориентировочные границы программы, НЕ нормы решателя.
DEFAULT_PROFILE = {
    "scaled_jacobian": {"caution": 0.5, "risk": 0.2},
    "skewness":        {"caution": 0.5, "risk": 0.75},
    "non_orthogonality_deg": {"caution": 30.0, "risk": 60.0},
    "neighbor_volume_ratio": {"caution": 1.5, "risk": 3.0},
    "aspect_ratio":    {"caution": None, "risk": None},
}

PROFILE_VERSION = 1

METRIC_INFO = {
    "volume": {"title": "Объём ячейки", "direction": "Положительный объём — правильная ориентация; нулевой или отрицательный — ошибка."},
    "scaled_jacobian": {"title": "Искажение формы — масштабированный якобиан", "direction": "Ближе к 1 — лучше. Меньше 0,2 — высокий риск; <=0 — ошибка."},
    "skewness": {"title": "Искажение углов — скошенность", "direction": "Ближе к 0 — лучше. Больше 0,75 — высокий риск."},
    "aspect_ratio": {"title": "Вытянутость ячейки", "direction": "Высокое значение может быть ожидаемым у стенки. Оценивается отдельно по направлению и расположению."},
    "non_orthogonality_deg": {"title": "Наклон граней — неортогональность", "direction": "Меньше угла — лучше. Больше 60° — высокий риск."},
    "neighbor_volume_ratio": {"title": "Плавность изменения объёмов", "direction": "Отношение ближе к 1 — плавнее. Больше 3 — высокий риск."},
}


def _status_for(metric_name, worst, profile):
    """Статус по худшему значению. Граница порога включается в худшую зону."""
    if metric_name == "aspect_ratio":
        return ("info", "Требует контекста: проверьте положение вытянутых ячеек")
    if worst is None or not math.isfinite(float(worst)):
        return ("error", "Недостаточно данных")
    p = (profile or {}).get(metric_name) or {}
    caution, risk = p.get("caution"), p.get("risk")
    if caution is None and risk is None:
        return ("info", "Пороги для этой метрики не заданы")
    if metric_name == "scaled_jacobian":
        if risk is not None and worst <= float(risk):
            return ("risk", "Высокий риск: значение слишком близко к вырождению")
        if caution is not None and worst <= float(caution):
            return ("caution", "Требует проверки: значение ниже или равно ориентиру")
        return ("ok", "Без замечаний по профилю")
    else:
        if risk is not None and worst >= float(risk):
            return ("risk", "Высокий риск: значение выше или равно ориентиру")
        if caution is not None and worst >= float(caution):
            return ("caution", "Требует проверки: значение выше или равно ориентиру")
        return ("ok", "Без замечаний по профилю")


def validate_profile(profile):
    """Проверка корректности профиля порогов. Возвращает нормализованный профиль.

    Все значения приводятся к float. Для scaled_jacobian (меньше — хуже): caution >= risk.
    Для остальных метрик (больше — хуже): caution <= risk.
    Выбрасывает QualityError при ошибке. Атомарно: не изменяет вход."""
    if profile is None:
        return {k: dict(v) for k, v in DEFAULT_PROFILE.items()}
    out = {}
    for name, p in profile.items():
        if name not in METRIC_INFO:
            raise QualityError(f"Неизвестная метрика в профиле: {name!r}")
        if not isinstance(p, dict):
            raise QualityError(f"Пороги для {name!r} должны быть словарём")
        caution = p.get("caution")
        risk = p.get("risk")
        try:
            caution_f = None if caution is None else float(caution)
            risk_f = None if risk is None else float(risk)
        except (TypeError, ValueError):
            raise QualityError(f"Пороги для {name!r} должны быть числами или None")
        for key, value in (("caution", caution_f), ("risk", risk_f)):
            if value is None:
                continue
            if not math.isfinite(value):
                raise QualityError(f"Порог {name}.{key} должен быть конечным числом")
        if caution_f is not None and risk_f is not None:
            if name == "scaled_jacobian":
                if caution_f < risk_f:
                    raise QualityError("Для масштабированного якобиана жёлтая зона не может быть меньше красной (меньше — хуже).")
            else:
                if caution_f > risk_f:
                    raise QualityError(f"Для метрики {name} жёлтая зона не может быть больше красной (больше — хуже).")
        out[name] = {"caution": caution_f, "risk": risk_f}
    return out


def _fmt_num(v, metric):
    if v is None:
        return "—"
    if metric == "volume":
        return f"{float(v):.3e} м³"
    if metric == "non_orthogonality_deg":
        return f"{float(v):.1f}°"
    if metric == "aspect_ratio":
        v = float(v)
        return f"{v:.0f} : 1" if v >= 100 else f"{v:.2f} : 1"
    if metric == "neighbor_volume_ratio":
        return f"{float(v):.2f} раза"
    return f"{float(v):.3f}"


def _fmt_loc(loc):
    if not isinstance(loc, dict):
        return "—"
    kind = loc.get("kind")
    if kind == "cell":
        c = loc.get("cell", [0, 0, 0])
        return f"блок {loc.get('block')}, ячейка [{c[0]},{c[1]},{c[2]}]"
    if kind == "internal_face":
        bc = loc.get("between_cells", [[0], [0]])
        return f"блок {loc.get('block')}, ось {loc.get('axis')}, между [{bc[0][0]},{bc[0][1]},{bc[0][2]}] и [{bc[1][0]},{bc[1][1]},{bc[1][2]}]"
    if kind == "interface":
        return (f"стык {loc.get('interface')}, блок {loc.get('block_a')} грань {loc.get('face_a')}"
                f" — блок {loc.get('block_b')} грань {loc.get('face_b')}, слой {loc.get('layer_cell')}")
    return "—"


def interpret_report(report, profile=None):
    """Строки для вкладки «Обзор». Не меняет отчёт, не зависит от Qt.

    Порядок оценки: 1) полнота данных; 2) геометрические ошибки; 3) профиль порогов.
    Неполная проверка или невычисленные значения не дают зелёного итога."""
    profile = validate_profile(profile)
    metrics = report.get("metrics", {})
    invalid = report.get("invalid", {})
    rows = []
    notes = []
    has_invalid_volume = invalid.get("non_positive_volume_cells", 0) > 0
    has_invalid_jac = invalid.get("non_positive_scaled_jacobian_cells", 0) > 0
    report_warnings = list(report.get("warnings", []))

    for name in ("scaled_jacobian", "skewness", "aspect_ratio",
                 "non_orthogonality_deg", "neighbor_volume_ratio"):
        m = metrics.get(name)
        if m is None:
            rows.append({
                "name": name, "title": METRIC_INFO[name]["title"],
                "direction": METRIC_INFO[name]["direction"],
                "worst_value": None, "worst_fmt": "—",
                "location_fmt": "—", "count": None,
                "status": "error", "status_text": "Метрика отсутствует в отчёте",
                "threshold": None,
                "zone_ok_count": None, "zone_caution_count": None,
                "zone_risk_count": None, "zone_nonfinite_count": None,
            })
            continue
        worst = m.get("worst_value")
        loc = m.get("worst_location")
        nonfinite = m.get("nonfinite", 0)
        status, status_text = _status_for(name, worst, profile)
        # невычисленные значения — не зелёный статус при любом статусе
        if nonfinite:
            status = "error"
            status_text = f"Часть значений невычислена: {nonfinite} из {m.get('count', 0)}"
        # aspect_ratio без числа — ошибка; с числом — контекстная оценка
        if name == "aspect_ratio":
            if worst is None or not math.isfinite(float(worst)):
                status, status_text = ("error", "Недостаточно данных")
            else:
                status, status_text = ("info", "Требует контекста: проверьте положение вытянутых ячеек")
        rows.append({
            "name": name, "title": METRIC_INFO[name]["title"],
            "direction": METRIC_INFO[name]["direction"],
            "worst_value": worst, "worst_fmt": _fmt_num(worst, name),
            "location_fmt": _fmt_loc(loc), "count": m.get("count"),
            "status": status, "status_text": status_text,
            "threshold": m.get("threshold"),
            "zone_ok_count": m.get("zone_ok_count"),
            "zone_caution_count": m.get("zone_caution_count"),
            "zone_risk_count": m.get("zone_risk_count"),
            "zone_nonfinite_count": m.get("zone_nonfinite_count"),
            "nonfinite": nonfinite,
        })

    # Объём проверяется отдельно: неположительный объём — ошибка,
    # невычисленный объём, отсутствие метрики или нулевая выборка — неполная проверка.
    vol = metrics.get("volume")
    vol_worst = vol.get("worst_value") if isinstance(vol, dict) else None
    vol_nonfinite = vol.get("nonfinite", 0) if isinstance(vol, dict) else 0
    vol_count = vol.get("count", 0) if isinstance(vol, dict) else 0
    vol_incomplete = (vol is None or vol_worst is None
                      or not math.isfinite(float(vol_worst)) or vol_nonfinite > 0 or vol_count == 0)

    ok = sum(1 for r in rows if r["status"] == "ok")
    caution = sum(1 for r in rows if r["status"] == "caution")
    risk = sum(1 for r in rows if r["status"] == "risk")
    info = sum(1 for r in rows if r["status"] == "info")
    errors = sum(1 for r in rows if r["status"] == "error")
    expected = 5

    # Неполнота: метрики отсутствуют, невычислены, нулевая выборка или ошибки.
    # Отдельно от тяжести проблем: может быть одновременно «неполная» и «высокий риск».
    row_incomplete = len(rows) < expected or errors > 0
    for r in rows:
        if r["status"] == "error":
            row_incomplete = True
        if r.get("nonfinite"):
            row_incomplete = True
        if r.get("count") == 0:
            row_incomplete = True
    incomplete = row_incomplete or vol_incomplete

    if has_invalid_volume or has_invalid_jac:
        summary_status = "error"
        summary = ("Обнаружены геометрические ошибки: неположительный объём или якобиан. "
                   "Такую сетку нельзя считать пригодной без исправления.")
    elif incomplete:
        summary_status = "error"
        summary = ("Оценка неполная: часть метрик отсутствует, невычислена или имеет нулевую выборку. "
                   "Заключение «замечаний нет» в этом случае не выдаётся.")
    def _plural(n, one, few, many):
        if n % 10 == 1 and n % 100 != 11:
            return f"{n} {one}"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return f"{n} {few}"
        return f"{n} {many}"

    if has_invalid_volume or has_invalid_jac:
        summary_status = "error"
        summary = ("Обнаружены геометрические ошибки: неположительный объём или якобиан. "
                   "Такую сетку нельзя считать пригодной без исправления.")
    elif incomplete:
        summary_status = "error"
        summary = ("Оценка неполная: часть метрик отсутствует, невычислена или имеет нулевую выборку. "
                   "Заключение «замечаний нет» в этом случае не выдаётся.")
    elif risk > 0:
        summary_status = "risk"
        summary = (f"Оценка по профилю: {_plural(ok, 'показатель', 'показателя', 'показателей')} без замечаний, "
                   f"{_plural(caution, 'требует', 'требуют', 'требуют')} проверки, "
                   f"{_plural(risk, 'показатель', 'показателя', 'показателей')} с высоким риском. "
                   "Основное замечание — см. ниже.")
    elif caution > 0:
        summary_status = "caution"
        summary = (f"Оценка по профилю: {_plural(ok, 'показатель', 'показателя', 'показателей')} без замечаний, "
                   f"{_plural(caution, 'требует', 'требуют', 'требуют')} проверки. "
                   "Высокого риска не обнаружено.")
    elif report_warnings:
        summary_status = "caution"
        summary = (f"Оценка по профилю: {_plural(ok, 'показатель', 'показателя', 'показателей')} без замечаний. "
                   "Дополнительно есть предупреждения о стыках блоков — см. «Подробности».")
    else:
        summary_status = "ok"
        summary = (f"Оценка по профилю: {_plural(ok, 'показатель', 'показателя', 'показателей')} без замечаний, "
                   f"{_plural(info, 'требует', 'требуют', 'требуют')} контекста. "
                   "Высокого риска и замечаний не обнаружено.")

    notes.append("Это оценка геометрии сетки по порогам программы, а не гарантия точности CFD-расчёта.")
    notes.append("Определения метрик заданы в этой программе и могут отличаться от одноимённых метрик STAR-CCM+ и других пакетов.")
    if has_invalid_volume:
        notes.append(f"Ячеек с неположительным объёмом: {invalid.get('non_positive_volume_cells')}.")
    if has_invalid_jac:
        notes.append(f"Ячеек с неположительным масштабированным якобианом: {invalid.get('non_positive_scaled_jacobian_cells')}.")
    for w in report_warnings[:5]:
        notes.append(f"Предупреждение анализа: {w}")
    ar = next((r for r in rows if r["name"] == "aspect_ratio"), None)
    if ar is not None and ar["worst_value"] is not None and math.isfinite(float(ar["worst_value"])) and float(ar["worst_value"]) >= 10:
        notes.append(f"Вытянутость ячеек высокая ({ar['worst_fmt']}). В пристеночных сетках это может быть ожидаемым; оцените расположение таких ячеек и направление вытянутости.")
    return {"profile": profile, "profile_version": PROFILE_VERSION,
            "summary": summary, "summary_status": summary_status,
            "rows": rows, "notes": notes, "invalid": dict(invalid),
            "ok_count": ok, "caution_count": caution, "risk_count": risk,
            "info_count": info, "error_count": errors,
            "incomplete": incomplete, "report_warnings": report_warnings}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Метрики качества многоблочного ASCII Plot3D (XYZ)")
    parser.add_argument("file")
    parser.add_argument("--json", help="сохранить полный отчёт в JSON")
    parser.add_argument("--threshold", action="append", metavar="ИМЯ=ЗНАЧЕНИЕ",
                        help="порог для подсчёта: " + ", ".join(n for n in ALL_METRICS if n not in NO_THRESHOLD))
    parser.add_argument("--tolerance", type=float, help="допуск совпадения узлов стыка в единицах файла")
    args = parser.parse_args(argv)
    try:
        report = analyse_blocks(read_plot3d_ascii(args.file), thresholds=_parse_thresholds(args.threshold), tolerance=args.tolerance)
        if args.json:
            save_report(report, args.json)
    except (QualityError, OSError, UnicodeError) as exc:
        print("Ошибка:", exc, file=sys.stderr)
        return 1
    print(format_report(report))
    bad = report["invalid"]
    return 2 if bad["non_positive_volume_cells"] or bad["non_positive_scaled_jacobian_cells"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
