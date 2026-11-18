# -*- coding: utf-8 -*-
"""Генератор структурированной сетки подканалов со сбором поблочных профилей нормальных шагов."""
import math, os, sys
import tempfile
from dataclasses import dataclass, field
import numpy as np

import mesh_core as mc
import mesh_quality as mq
from block_classifier import classify_subchannel_blocks

LAW_DISPLAY_NAMES = {
    "geometric": "Геометрический",
    "uniform": "Равномерный",
    "tanh": "tanh (двусторонний)",
    "sinh": "sinh (от стенки)",
    "power": "Степенной",
    "wall_core": "Пристеночный слой"
}

@dataclass
class BlockMetricsInfo:
    global_id: int
    subchannel_id: int
    sector_idx: int
    template_id: int
    law: str
    law_display: str
    rod_name: str
    rod_diameter_mm: float
    ni: int
    nj: int
    nz: int
    h1_um: float
    h_last_um: float
    azimuth_step_wall_um: float
    azimuth_step_opp_um: float
    growth_q: float
    aspect_ratio_wall: float
    special_param_str: str = ""

@dataclass(frozen=True)
class SubchannelMeshResult:
    params: mc.MeshParams
    blocks: list
    subchannels_count: int
    interfaces: tuple
    diagnostics: dict
    complete: bool = True
    layer_widths: np.ndarray = None
    templates: dict = field(default_factory=dict)
    instances_map: list = field(default_factory=list)
    wall_starts: list = field(default_factory=list)
    geom_data: list = field(default_factory=list)
    block_metrics: list = field(default_factory=list)
    all_block_widths: list = field(default_factory=list)

def _face_nodes(block, face):
    v = np.stack(block, axis=-1)
    return {"i_min": v[0], "i_max": v[-1],
            "j_min": v[:, 0], "j_max": v[:, -1]}[face]


def _validate_interfaces(blocks, interfaces, tolerance, layer_only=False):
    for it in interfaces:
        # The opposite fronts of an unfilled layer do not touch yet.
        if layer_only and it.face_a.startswith("j_"):
            continue
        a = _face_nodes(blocks[it.block_a], it.face_a)
        b = _face_nodes(blocks[it.block_b], it.face_b)
        if it.reversed:
            b = b[::-1]
        if a.shape != b.shape or not np.allclose(a, b, rtol=0, atol=tolerance):
            raise ValueError(
                f"Несовместимый стык блоков {it.block_a + 1}/{it.block_b + 1}: "
                "число и координаты узлов на общей грани должны совпадать. "
                "Согласуйте параметры блоков или сбросьте переопределения.")


def order_ccw(cA, rA, cB, rB, cC, rC):
    cross = (cB[0] - cA[0]) * (cC[1] - cA[1]) - (cB[1] - cA[1]) * (cC[0] - cA[0])
    if cross < 0: return cA, rA, cC, rC, cB, rB
    return cA, rA, cB, rB, cC, rC

def _unwrap_angle(theta_start, theta_end):
    diff = (theta_end - theta_start + math.pi) % (2.0 * math.pi) - math.pi
    return theta_start, theta_start + diff

def _check_quad_jacobians(blocks, ni=None):
    minimum = np.inf
    for k, (x, y) in enumerate(blocks):
        v = np.stack((x, y), axis=-1)
        if ni is not None and v.shape[0] != ni:
            raise ValueError(f"Блок {k+1}: не совпадает число узлов по дуге ni ({v.shape[0]} != {ni})")
        if not np.all(np.isfinite(v)):
            raise ValueError(f"Блок {k+1}: нечисловые координаты (NaN или Inf).")
        a, b, c, d = v[:-1, :-1], v[1:, :-1], v[1:, 1:], v[:-1, 1:]
        jac = np.stack((
            mc.cross2(b - a, d - a),
            mc.cross2(b - a, c - b),
            mc.cross2(c - d, c - b),
            mc.cross2(c - d, d - a)
        ))
        if np.any(jac <= 0):
            raise ValueError(f"Блок {k+1}: вырожденные или перевёрнутые ячейки (jac <= 0)")
        minimum = min(minimum, float(jac.min()))
    return minimum


def hermite_tfi_rays(arc, opposite, s_norm, stiffness=0.45):
    ni, nj = s_norm.shape
    rem_dir = opposite - arc
    lengths = np.linalg.norm(rem_dir, axis=1, keepdims=True)
    straight_unit = rem_dir / np.maximum(lengths, 1e-15)

    d_arc = np.zeros_like(arc)
    d_arc[1:-1] = arc[2:] - arc[:-2]
    d_arc[0] = arc[1] - arc[0]
    d_arc[-1] = arc[-1] - arc[-2]
    n0 = np.column_stack([-d_arc[:, 1], d_arc[:, 0]])
    n0 = n0 / np.maximum(np.linalg.norm(n0, axis=1, keepdims=True), 1e-15)
    n0 = np.where(np.sum(n0 * straight_unit, axis=1, keepdims=True) < 0.0, -n0, n0)

    opp_vec = opposite[-1] - opposite[0]
    n1_base = np.array([-opp_vec[1], opp_vec[0]], dtype=float)
    n1_len = np.linalg.norm(n1_base)
    n1_base = n1_base / n1_len if n1_len > 1e-15 else straight_unit[0]
    n1 = np.broadcast_to(n1_base, (ni, 2)).copy()
    n1 = np.where(np.sum(n1 * straight_unit, axis=1, keepdims=True) < 0.0, -n1, n1)

    blend = np.sin(np.pi * np.linspace(0.0, 1.0, ni))[:, None]
    n0 = (1.0 - blend) * straight_unit + blend * n0
    n0 = n0 / np.maximum(np.linalg.norm(n0, axis=1, keepdims=True), 1e-15)
    n1 = (1.0 - blend) * straight_unit + blend * n1
    n1 = n1 / np.maximum(np.linalg.norm(n1, axis=1, keepdims=True), 1e-15)

    T0 = (stiffness * lengths)[:, None, :] * n0[:, None, :]
    T1 = (stiffness * lengths)[:, None, :] * n1[:, None, :]

    n_dense = 128
    u = np.linspace(0.0, 1.0, n_dense)[None, :, None]
    h00 = 2.0 * u**3 - 3.0 * u**2 + 1.0
    h10 = u**3 - 2.0 * u**2 + u
    h01 = -2.0 * u**3 + 3.0 * u**2
    h11 = u**3 - u**2
    pts_dense = h00 * arc[:, None, :] + h10 * T0 + h01 * opposite[:, None, :] + h11 * T1

    seg_lens = np.linalg.norm(np.diff(pts_dense, axis=1), axis=2)
    cum_arc = np.column_stack((np.zeros(ni), np.cumsum(seg_lens, axis=1)))
    u_arc = cum_arc / np.maximum(cum_arc[:, -1:], 1e-15)

    v = np.empty((ni, nj, 2), dtype=float)
    for i in range(ni):
        v[i, :, 0] = np.interp(s_norm[i], u_arc[i], pts_dense[i, :, 0])
        v[i, :, 1] = np.interp(s_norm[i], u_arc[i], pts_dense[i, :, 1])
    v[:, 0, :] = arc
    v[:, -1, :] = opposite
    return v

def _build_sector_block(c_rod, r_rod, theta_start, theta_end, pt_O, pt_M, p, flip=False, auto_fill_core=False, hermite_tfi=False):
    ni = p.ni
    t_start, t_end = _unwrap_angle(theta_start, theta_end)
    theta = np.linspace(t_start, t_end, ni)
    arc = c_rod + r_rod * np.column_stack((np.cos(theta), np.sin(theta)))

    opposite = pt_O + np.linspace(0, 1, ni)[:, None] * (pt_M - pt_O)
    direction = opposite - arc
    lengths = np.linalg.norm(direction, axis=1)

    layer_mode = (p.law == "wall_core")
    param_val = 1.0

    if layer_mode:
        wall, q_val = mc.layer_distribution(p)
        param_val = q_val
        thickness = float(wall.sum())
        n_wall = len(wall)
        actual = mc.replace(p, nj=n_wall + 1, h1=float(wall[0]))

        if auto_fill_core:
            rem_lengths = lengths - thickness
            if np.any(rem_lengths <= 0):
                raise ValueError(f"Толщина слоя ({thickness*1e3:.2f} мм) превышает зазор ({lengths.min()*1e3:.2f} мм)!")
            last_w = float(wall[-1])
            eff_max = max(100e-6, last_w * 1.05)
            h0_vec = np.full(ni, last_w, dtype=float)
            dist = mc.capped_distribution(rem_lengths, h0_vec, growth=1.1, max_size=eff_max, max_cells=5000)

            widths = np.column_stack([np.broadcast_to(wall, (ni, n_wall)), dist.widths])
            s = np.column_stack((np.zeros(ni), np.cumsum(widths, axis=1)))
            s[:, -1] = lengths
            target_opp = opposite
            v = arc[:, None, :] + s[:, :, None] * (direction / lengths[:, None])[:, None, :]
            v[:, -1] = target_opp
            actual = mc.replace(p, nj=widths.shape[1] + 1)
        else:
            widths = np.broadcast_to(wall, (ni, n_wall)).copy()
            s = np.column_stack((np.zeros(ni), np.cumsum(widths, axis=1)))
            target_opp = arc + thickness * (direction / lengths[:, None])
            v = arc[:, None, :] + s[:, :, None] * (direction / lengths[:, None])[:, None, :]
            v[:, -1] = target_opp
    else:
        actual, parameter = mc.solve_distribution(lengths, p)
        param_val = float(np.mean(parameter))
        n = actual.nj - 1
        widths = lengths[:, None] * mc.fractions(parameter, n, actual)
        s = np.column_stack((np.zeros(ni), np.cumsum(widths, axis=1)))
        s[:, -1] = lengths
        target_opp = opposite
        if hermite_tfi:
            v = hermite_tfi_rays(arc, target_opp, s / lengths[:, None])
        else:
            v = arc[:, None, :] + s[:, :, None] * (direction / lengths[:, None])[:, None, :]
            v[:, -1] = target_opp

    x, y = v[:, :, 0], v[:, :, 1]
    if flip: x, y = x[:, ::-1], y[:, ::-1]

    v_chk = np.stack((x, y), axis=-1)
    a, b, c, d = v_chk[:-1, :-1], v_chk[1:, :-1], v_chk[1:, 1:], v_chk[:-1, 1:]
    jac = mc.cross2(b - a, d - a)
    if np.any(jac <= 0): x, y = x[:, ::-1], y[:, ::-1]

    arc_len = abs(t_end - t_start) * r_rod
    ds_wall = arc_len / max(1, ni - 1)
    ds_opp = np.linalg.norm(pt_M - pt_O) / max(1, ni - 1)

    geom_info = {
        "arc": arc, "opposite": opposite, "direction": direction, "lengths": lengths, "flip": flip,
        "layer_thickness": float(wall.sum()) if layer_mode else None,
        "ds_wall": ds_wall, "ds_opp": ds_opp, "param_val": param_val, "actual_params": actual
    }
    return (x, y), widths, actual, geom_info

def get_subchannel_interfaces():
    return (
        mc.BlockInterface(0, "i_min", 5, "i_min", True),
        mc.BlockInterface(0, "j_max", 1, "j_min", False),
        mc.BlockInterface(1, "i_min", 2, "i_min", True),
        mc.BlockInterface(2, "j_max", 3, "j_min", False),
        mc.BlockInterface(3, "i_min", 4, "i_min", True),
        mc.BlockInterface(4, "j_max", 5, "j_min", False),
    )

def find_equi_clearance_point(cA, rA, cB, rB, cC, rC):
    """
    Аналитическое решение задачи Аполлония (Точка равного зазора / Метод 3):
    Находит точку O = (x, y) такую, что:
      ||O - cA|| - rA = ||O - cB|| - rB = ||O - cC|| - rC = delta
    где delta > 0 - одинаковый нормальный зазор от точки O до поверхностей всех 3 стержней.
    Если стержни одинаковые (rA == rB == rC), точка O строго совпадает с центроидом.
    """
    cA = np.asarray(cA, dtype=float)
    cB = np.asarray(cB, dtype=float)
    cC = np.asarray(cC, dtype=float)
    rA = float(rA)
    rB = float(rB)
    rC = float(rC)

    centroid = (cA + cB + cC) / 3.0

    if max(abs(rA - rB), abs(rB - rC), abs(rC - rA)) < 1e-7:
        return centroid

    xA, yA = cA
    xB, yB = cB
    xC, yC = cC

    A1 = 2.0 * (xB - xA)
    B1 = 2.0 * (yB - yA)
    C1 = (xB**2 + yB**2 - rB**2) - (xA**2 + yA**2 - rA**2)
    D1 = 2.0 * (rA - rB)

    A2 = 2.0 * (xC - xA)
    B2 = 2.0 * (yC - yA)
    C2 = (xC**2 + yC**2 - rC**2) - (xA**2 + yA**2 - rA**2)
    D2 = 2.0 * (rA - rC)

    det = A1 * B2 - A2 * B1
    if abs(det) < 1e-12:
        return centroid

    x0 = (C1 * B2 - C2 * B1) / det
    kx = (D1 * B2 - D2 * B1) / det

    y0 = (A1 * C2 - A2 * C1) / det
    ky = (A1 * D2 - A2 * D1) / det

    dx = x0 - xA
    dy = y0 - yA

    qa = kx**2 + ky**2 - 1.0
    qb = 2.0 * (dx * kx + dy * ky - rA)
    qc = dx**2 + dy**2 - rA**2

    disc = qb**2 - 4.0 * qa * qc
    if disc < 0:
        return centroid

    sqrt_d = math.sqrt(disc)
    delta1 = (-qb + sqrt_d) / (2.0 * qa) if abs(qa) > 1e-12 else -qc / qb
    delta2 = (-qb - sqrt_d) / (2.0 * qa) if abs(qa) > 1e-12 else -qc / qb

    candidates = []
    for d in (delta1, delta2):
        if d > 0:
            cand = np.array([x0 + kx * d, y0 + ky * d])
            candidates.append((d, cand))

    if not candidates:
        return centroid

    best_cand = min(candidates, key=lambda c: np.linalg.norm(c[1] - centroid))[1]
    return best_cand

def generate_subchannel_mesh(center_A, r_A, center_B, r_B, center_C, r_C, params_list_or_single, auto_fill_core=False, pt_center=None, center_method="equi_clearance", hermite_tfi=False):
    requested = list(params_list_or_single) if isinstance(params_list_or_single, (list, tuple)) else [params_list_or_single] * 6
    if len(requested) != 6:
        raise ValueError("Нужно шесть наборов параметров блоков")
    for p in requested:
        p.validate()
    if len({(p.ni, p.nz, p.z_len) for p in requested}) != 1:
        raise ValueError("Число узлов ni, nz и высота z_len должны совпадать у блоков подканала")
    if len({p.law == "wall_core" for p in requested}) != 1:
        raise ValueError("Нельзя смешивать независимый слой и полную сетку в одном подканале")
    cA, rA, cB, rB, cC, rC = order_ccw(center_A, r_A, center_B, r_B, center_C, r_C)
    cA = np.asarray(cA, dtype=float); cB = np.asarray(cB, dtype=float); cC = np.asarray(cC, dtype=float)
    rA, rB, rC = float(rA), float(rB), float(rC)

    if pt_center is not None:
        O = np.asarray(pt_center, dtype=float)
    elif center_method == "centroid":
        O = (cA + cB + cC) / 3.0
    else:
        O = find_equi_clearance_point(cA, rA, cB, rB, cC, rC)

    def gap_midpoint(c1, r1, c2, r2):
        v = c2 - c1; d = np.linalg.norm(v); u = v / d; gap = d - (r1 + r2)
        if gap <= 1e-6: raise ValueError(f"Стержни пересекаются: зазор {gap*1e3:.2f} мм")
        return c1 + u * (r1 + gap / 2.0)

    mAB = gap_midpoint(cA, rA, cB, rB)
    mBC = gap_midpoint(cB, rB, cC, rC)
    mCA = gap_midpoint(cC, rC, cA, rA)

    theta_AO = math.atan2((O - cA)[1], (O - cA)[0])
    theta_AB = math.atan2((cB - cA)[1], (cB - cA)[0])
    theta_AC = math.atan2((cC - cA)[1], (cC - cA)[0])

    theta_BO = math.atan2((O - cB)[1], (O - cB)[0])
    theta_BA = math.atan2((cA - cB)[1], (cA - cB)[0])
    theta_BC = math.atan2((cC - cB)[1], (cC - cB)[0])

    theta_CO = math.atan2((O - cC)[1], (O - cC)[0])
    theta_CB = math.atan2((cB - cC)[1], (cB - cC)[0])
    theta_CA = math.atan2((cA - cC)[1], (cA - cC)[0])

    p0, p1, p2, p3, p4, p5 = params_list_or_single if isinstance(params_list_or_single, (list, tuple)) else [params_list_or_single]*6

    b0, w0, act0, g0 = _build_sector_block(cA, rA, theta_AO, theta_AB, O, mAB, p0, flip=False, auto_fill_core=auto_fill_core, hermite_tfi=hermite_tfi)
    b1, w1, act1, g1 = _build_sector_block(cB, rB, theta_BO, theta_BA, O, mAB, p1, flip=True, auto_fill_core=auto_fill_core, hermite_tfi=hermite_tfi)
    b2, w2, act2, g2 = _build_sector_block(cB, rB, theta_BO, theta_BC, O, mBC, p2, flip=False, auto_fill_core=auto_fill_core, hermite_tfi=hermite_tfi)
    b3, w3, act3, g3 = _build_sector_block(cC, rC, theta_CO, theta_CB, O, mBC, p3, flip=True, auto_fill_core=auto_fill_core, hermite_tfi=hermite_tfi)
    b4, w4, act4, g4 = _build_sector_block(cC, rC, theta_CO, theta_CA, O, mCA, p4, flip=False, auto_fill_core=auto_fill_core, hermite_tfi=hermite_tfi)
    b5, w5, act5, g5 = _build_sector_block(cA, rA, theta_AO, theta_AC, O, mCA, p5, flip=True, auto_fill_core=auto_fill_core, hermite_tfi=hermite_tfi)

    blocks = [b0, b1, b2, b3, b4, b5]
    interfaces = get_subchannel_interfaces()
    min_jac = _check_quad_jacobians(blocks)
    is_layer = any(p.law == "wall_core" and not auto_fill_core for p in (p0, p1, p2, p3, p4, p5))

    _validate_interfaces(blocks, interfaces, requested[0].pitch * 1e-11, layer_only=is_layer)

    diagnostics = {
        "blocks": 6,
        "cells_2d": sum((bx.shape[0] - 1) * (bx.shape[1] - 1) for bx, by in blocks),
        "cells_3d": sum((bx.shape[0] - 1) * (bx.shape[1] - 1) * p0.nz for bx, by in blocks),
        "min_jacobian": min_jac, "internal_interfaces": len(interfaces), "complete": not is_layer
    }
    return SubchannelMeshResult(
        params=act0, blocks=blocks, subchannels_count=1, interfaces=interfaces,
        diagnostics=diagnostics, complete=not is_layer, layer_widths=w0,
        wall_starts=[True, False, True, False, True, False],
        geom_data=[g0, g1, g2, g3, g4, g5],
        all_block_widths=[w0, w1, w2, w3, w4, w5]
    )

def build_mesh_from_bundle_model(bundle_model, base_params, template_overrides=None, block_custom_overrides=None, selected_sub_ids=None, auto_fill_core=False, center_method="equi_clearance", hermite_tfi=False):
    if template_overrides is None: template_overrides = {}
    if block_custom_overrides is None: block_custom_overrides = {}

    sub_ids = list(bundle_model.selected_subchannels) if selected_sub_ids is None else list(selected_sub_ids)
    templates, instances = classify_subchannel_blocks(bundle_model, selected_sub_ids=sub_ids)
    inst_lookup = {(inst.subchannel_id, inst.block_index): inst for inst in instances}

    all_blocks = []; base_act = None; base_widths = None; all_interfaces = []
    skipped_peripheral = 0; instances_map = []; all_wall_starts = []; all_geom_data = []
    block_metrics = []; all_block_widths = []

    valid_subs = [sid for sid in sub_ids if sid in bundle_model.subchannels and bundle_model.subchannels[sid].sub_type in ("interior", "guide_sub", "instrument_sub") and len(bundle_model.subchannels[sid].rod_ids) == 3]
    skipped_peripheral = len(sub_ids) - len(valid_subs)
    if not valid_subs: raise ValueError("Нет внутренних треугольных подканалов среди выбранных.")

    for sub_idx, sid in enumerate(valid_subs):
        s = bundle_model.subchannels[sid]
        rA, rB, rC = bundle_model.rods[s.rod_ids[0]], bundle_model.rods[s.rod_ids[1]], bundle_model.rods[s.rod_ids[2]]
        cA = np.array([rA.x, rA.y]) * 1e-3; cB = np.array([rB.x, rB.y]) * 1e-3; cC = np.array([rC.x, rC.y]) * 1e-3
        rA_m, rB_m, rC_m = rA.diameter * 0.5e-3, rB.diameter * 0.5e-3, rC.diameter * 0.5e-3
        if center_method == "centroid":
            pt_c = (cA + cB + cC) / 3.0
        else:
            pt_c = find_equi_clearance_point(cA, rA_m, cB, rB_m, cC, rC_m)

        sub_p_list = []
        for b_idx in range(6):
            inst = inst_lookup.get((sid, b_idx))
            gid = inst.global_block_id if inst else (sub_idx * 6 + b_idx + 1)
            tid = inst.template_id if inst else 1
            if (sid, b_idx) in block_custom_overrides: p_blk = block_custom_overrides[(sid, b_idx)]
            elif gid in block_custom_overrides: p_blk = block_custom_overrides[gid]
            elif tid in template_overrides: p_blk = template_overrides[tid]
            else: p_blk = base_params
            if (p_blk.ni, p_blk.nz, p_blk.z_len) != (base_params.ni, base_params.nz, base_params.z_len):
                raise ValueError("Переопределения должны сохранять общие ni, nz и z_len сетки")
            sub_p_list.append(p_blk)
            instances_map.append((sid, b_idx, tid, gid))

        sub_res = generate_subchannel_mesh(cA, rA_m, cB, rB_m, cC, rC_m, sub_p_list, auto_fill_core=auto_fill_core, pt_center=pt_c, center_method=center_method, hermite_tfi=hermite_tfi)
        base_act = sub_res.params
        if base_widths is None: base_widths = sub_res.layer_widths

        offset = sub_idx * 6
        all_blocks.extend(sub_res.blocks)
        all_wall_starts.extend(sub_res.wall_starts)
        all_geom_data.extend(sub_res.geom_data)
        all_block_widths.extend(sub_res.all_block_widths)

        rods_cycle = [rA, rB, rB, rC, rC, rA]
        for b_idx in range(6):
            gid = offset + b_idx + 1
            inst = inst_lookup.get((sid, b_idx))
            tid = inst.template_id if inst else 1
            bx, by = sub_res.blocks[b_idx]; g = sub_res.geom_data[b_idx]
            p_curr = sub_p_list[b_idx]; r_curr = rods_cycle[b_idx]

            ni_val, nj_val, nz_val = bx.shape[0], bx.shape[1], p_curr.nz
            if sub_res.wall_starts[b_idx]:
                h1_val = np.hypot(bx[:, 1] - bx[:, 0], by[:, 1] - by[:, 0]).mean()
                h_last_val = np.hypot(bx[:, -1] - bx[:, -2], by[:, -1] - by[:, -2]).mean()
            else:
                h1_val = np.hypot(bx[:, -2] - bx[:, -1], by[:, -2] - by[:, -1]).mean()
                h_last_val = np.hypot(bx[:, 1] - bx[:, 0], by[:, 1] - by[:, 0]).mean()

            ds_w, ds_o = g["ds_wall"], g["ds_opp"]
            q_est = g["param_val"]
            ar_wall = ds_w / max(1e-9, h1_val)
            law_disp = LAW_DISPLAY_NAMES.get(p_curr.law, p_curr.law)

            if p_curr.law == "wall_core":
                if p_curr.mode == "layer_first_growth":
                    spec_desc = f"Слой {p_curr.wall_layers} сл. (h1={p_curr.h1*1e6:.1f} мкм, q={p_curr.layer_growth:.2f})"
                else:
                    spec_desc = f"Слой {p_curr.layer_thickness*1e3:.2f} мм ({p_curr.wall_layers} сл.)"
            elif p_curr.law == "uniform": spec_desc = "Равномерный шаг"
            elif p_curr.law in ("tanh", "sinh"): spec_desc = f"Крутизна β = {q_est:.2f}"
            elif p_curr.law == "power": spec_desc = f"Степень α = {p_curr.shape:.2f}"
            else: spec_desc = f"Рост q = {q_est:.3f}"

            r_type_ru = "ТВЭЛ" if r_curr.rod_type == "fuel" else ("НК" if r_curr.rod_type == "guide" else "ИК")

            block_metrics.append(BlockMetricsInfo(
                global_id=gid, subchannel_id=sid, sector_idx=b_idx + 1, template_id=tid,
                law=p_curr.law, law_display=law_disp, rod_name=f"{r_type_ru} R{r_curr.rod_id}",
                rod_diameter_mm=r_curr.diameter, ni=ni_val, nj=nj_val, nz=nz_val,
                h1_um=h1_val * 1e6, h_last_um=h_last_val * 1e6,
                azimuth_step_wall_um=ds_w * 1e6, azimuth_step_opp_um=ds_o * 1e6,
                growth_q=q_est, aspect_ratio_wall=ar_wall, special_param_str=spec_desc
            ))

        for it in sub_res.interfaces:
            all_interfaces.append(mc.BlockInterface(
                it.block_a + offset, it.face_a, it.block_b + offset, it.face_b, it.reversed
            ))

    layer_flags = {g["layer_thickness"] is not None and not auto_fill_core for g in all_geom_data}
    if len(layer_flags) != 1:
        raise ValueError("Нельзя смешивать независимый слой и полную сетку в одной сборке")
    is_layer_only = layer_flags == {True}
    tol = base_params.pitch * 1e-11 if hasattr(base_params, "pitch") else 1e-11
    faces = []
    for k, (bx, by) in enumerate(all_blocks):
        bv = np.stack((bx, by), axis=-1)
        faces.append((k, "i_min", bv[0])); faces.append((k, "i_max", bv[-1]))
        faces.append((k, "j_min", bv[:, 0])); faces.append((k, "j_max", bv[:, -1]))

    existing_pairs = {frozenset(((it.block_a, it.face_a), (it.block_b, it.face_b))) for it in all_interfaces}
    for i in range(len(faces)):
        ka, fa, va = faces[i]
        for j in range(i + 1, len(faces)):
            kb, fb, vb = faces[j]
            if ka == kb: continue
            if is_layer_only:
                continue
            endpoints_match = (np.allclose(va[[0, -1]], vb[[0, -1]], rtol=0, atol=tol)
                               or np.allclose(va[[0, -1]], vb[[-1, 0]], rtol=0, atol=tol))
            if endpoints_match and (va.shape != vb.shape or
                    min(np.max(np.abs(va - vb)), np.max(np.abs(va - vb[::-1]))) > tol):
                raise ValueError("Несовместимые узлы на общей грани подканалов; согласуйте переопределения")
            if va.shape != vb.shape: continue
            pair_key = frozenset(((ka, fa), (kb, fb)))
            if pair_key in existing_pairs: continue
            diff1 = np.max(np.abs(va - vb)); diff2 = np.max(np.abs(va - vb[::-1]))
            if min(diff1, diff2) <= tol:
                all_interfaces.append(mc.BlockInterface(ka, fa, kb, fb, diff2 < diff1))
                existing_pairs.add(pair_key)

    min_jac = _check_quad_jacobians(all_blocks)

    diagnostics = {
        "blocks": len(all_blocks), "subchannels": len(valid_subs),
        "cells_2d": sum((bx.shape[0] - 1) * (bx.shape[1] - 1) for bx, by in all_blocks),
        "cells_3d": sum((bx.shape[0] - 1) * (bx.shape[1] - 1) * base_params.nz for bx, by in all_blocks),
        "min_jacobian": min_jac, "matched_interfaces": len(all_interfaces),
        "skipped_peripheral": skipped_peripheral, "templates_count": len(templates),
        "is_layer_only": is_layer_only
    }
    return SubchannelMeshResult(
        params=base_act, blocks=all_blocks, subchannels_count=len(valid_subs),
        interfaces=tuple(all_interfaces), diagnostics=diagnostics, complete=not is_layer_only,
        layer_widths=base_widths, templates=templates, instances_map=instances_map,
        wall_starts=all_wall_starts, geom_data=all_geom_data, block_metrics=block_metrics,
        all_block_widths=all_block_widths
    )

def fill_subchannel_core(layer_result, bundle_model, growth=1.1, max_size=100e-6, max_cells=5000, transition_ratio=1.0, core_mode="cfd_growth", core_layers=20, hermite_tfi=False):
    if layer_result.complete: return layer_result
    p = layer_result.params; ni = p.ni; blocks = layer_result.blocks
    if any(x.shape != y.shape or x.shape[0] != ni for x, y in blocks):
        raise ValueError("Несовместимое число узлов ni в пристеночном слое; перестройте слой")
    wall_starts = layer_result.wall_starts; geom_data = layer_result.geom_data

    last_w = float(layer_result.layer_widths[0, -1]) if layer_result.layer_widths is not None else float(p.h1)
    effective_max_size = max(float(max_size), last_w * 1.05)

    all_rem_lines = []; block_rem_lengths = []
    for idx, (bx, by) in enumerate(blocks):
        g = geom_data[idx]
        arc, opp, dir_vec, lens, thick = g["arc"], g["opposite"], g["direction"], g["lengths"], g["layer_thickness"]
        front = arc + thick * (dir_vec / lens[:, None])
        rem_dir = opp - front
        rem_lens = np.linalg.norm(rem_dir, axis=1)
        block_rem_lengths.append((front, opp, rem_dir, rem_lens))
        all_rem_lines.append(rem_lens)

    combined_rem = np.concatenate(all_rem_lines)
    h0_combined = np.full(len(combined_rem), last_w, dtype=float)

    h0_first = last_w * float(transition_ratio)
    if core_mode == "isotropic":
        opp_steps = [float(g["ds_opp"]) for g in geom_data if "ds_opp" in g]
        if opp_steps:
            effective_max_size = max(min(opp_steps), h0_first * 1.01)
        global_dist = mc.capped_distribution(combined_rem, h0_combined, growth, effective_max_size, max_cells, transition_ratio=transition_ratio)
    elif core_mode == "fixed_count":
        global_dist = mc.fixed_count_distribution(combined_rem, h0_combined, core_layers, transition_ratio=transition_ratio)
        effective_max_size = float(np.max(global_dist.widths))
    else:
        effective_max_size = max(float(max_size), h0_first * 1.01)
        global_dist = mc.capped_distribution(combined_rem, h0_combined, growth, effective_max_size, max_cells, transition_ratio=transition_ratio)

    filled_blocks = []; filled_block_widths = []; offset = 0
    for idx, (bx, by) in enumerate(blocks):
        starts = wall_starts[idx]
        front, opposite, rem_dir, rem_lens = block_rem_lengths[idx]
        widths_block = global_dist.widths[offset:offset + ni]
        offset += ni

        s_core = np.column_stack((np.zeros(ni), np.cumsum(widths_block, axis=1)))
        s_core[:, -1] = rem_lens
        if hermite_tfi:
            v_core = hermite_tfi_rays(front, opposite, s_core / rem_lens[:, None])
        else:
            v_core = front[:, None, :] + s_core[:, :, None] * (rem_dir / rem_lens[:, None])[:, None, :]
            v_core[:, -1] = opposite

        if starts:
            xx = np.concatenate((bx, v_core[:, 1:, 0]), axis=1); yy = np.concatenate((by, v_core[:, 1:, 1]), axis=1)
        else:
            v_flip = v_core[:, ::-1, :]
            xx = np.concatenate((v_flip[:, :-1, 0], bx), axis=1); yy = np.concatenate((v_flip[:, :-1, 1], by), axis=1)
        filled_blocks.append((xx, yy))

        orig_w = layer_result.all_block_widths[idx] if idx < len(layer_result.all_block_widths) else layer_result.layer_widths
        filled_block_widths.append(np.column_stack((orig_w, widths_block)))

    _validate_interfaces(filled_blocks, layer_result.interfaces, p.pitch * 1e-11)
    new_nj = filled_blocks[0][0].shape[1]
    new_p = mc.replace(p, nj=new_nj)
    min_jac = _check_quad_jacobians(filled_blocks)

    diag = dict(layer_result.diagnostics)
    diag["complete"] = True
    diag["cells_2d"] = len(filled_blocks) * (new_p.ni - 1) * (new_nj - 1)
    diag["cells_3d"] = diag["cells_2d"] * new_p.nz
    diag["min_jacobian"] = min_jac
    diag["is_layer_only"] = False
    diag["core_layers_count"] = int(global_dist.count)
    diag["core_step_min_m"] = float(global_dist.widths.min())
    diag["core_step_max_m"] = float(global_dist.widths.max())
    diag["core_plateau_min_m"] = float(global_dist.plateau.min())
    diag["core_plateau_max_m"] = float(global_dist.plateau.max())
    diag["core_target_m"] = float(effective_max_size)
    diag["core_target_exceeded"] = bool(
        float(growth) > 1.0 + 1e-12 and global_dist.plateau.max() > effective_max_size * 1.02
    )

    updated_metrics = []
    for m in layer_result.block_metrics:
        m_copy = BlockMetricsInfo(
            global_id=m.global_id, subchannel_id=m.subchannel_id, sector_idx=m.sector_idx,
            template_id=m.template_id, law=m.law, law_display=m.law_display, rod_name=m.rod_name,
            rod_diameter_mm=m.rod_diameter_mm, ni=m.ni, nj=new_nj, nz=m.nz,
            h1_um=m.h1_um, h_last_um=float(global_dist.widths.max()) * 1e6,
            azimuth_step_wall_um=m.azimuth_step_wall_um, azimuth_step_opp_um=m.azimuth_step_opp_um,
            growth_q=m.growth_q, aspect_ratio_wall=m.aspect_ratio_wall,
            special_param_str=f"Ядро: {global_dist.count} сл., плато {global_dist.plateau.min()*1e6:.1f}–{global_dist.plateau.max()*1e6:.1f} мкм"
        )
        updated_metrics.append(m_copy)

    return SubchannelMeshResult(
        params=new_p, blocks=filled_blocks, subchannels_count=layer_result.subchannels_count,
        interfaces=layer_result.interfaces, diagnostics=diag, complete=True,
        layer_widths=layer_result.layer_widths, templates=layer_result.templates,
        instances_map=layer_result.instances_map, wall_starts=layer_result.wall_starts,
        geom_data=layer_result.geom_data, block_metrics=updated_metrics,
        all_block_widths=filled_block_widths
    )

def export_subchannel_plot3d(result, filename):
    if not result.complete:
        raise ValueError("Нельзя экспортировать неполную сетку: сначала заполните ядро")
    p, nz, z_len = result.params, result.params.nz, result.params.z_len
    target = os.fspath(filename)
    fd, temp = tempfile.mkstemp(prefix=".bundle_mesh_", suffix=".tmp", dir=os.path.dirname(os.path.abspath(target)))
    os.close(fd)
    try:
        with open(temp, "w", encoding="ascii", newline="\n") as f:
            f.write(f"{len(result.blocks)}\n")
            for bx, by in result.blocks: f.write(f"{bx.shape[0]} {bx.shape[1]} {nz + 1}\n")
            for x, y in result.blocks:
                b_ni, b_nj = x.shape
                for coord in (x, y, None):
                    for k in range(nz + 1):
                        flat = coord.ravel(order="F") if coord is not None else np.full(b_ni * b_nj, z_len * k / nz)
                        for start in range(0, len(flat), 6):
                            f.write(" ".join(f"{v:.16e}" for v in flat[start:start + 6]) + "\n")
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
