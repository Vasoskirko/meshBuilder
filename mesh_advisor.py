# -*- coding: utf-8 -*-
import math
from typing import Tuple, Dict, Any

_UNIT_DEC = {"мкм": 1, "мм": 3, "м": 5}

def _udec(unit: str) -> int:
    return _UNIT_DEC.get(unit, 3)

def evaluate_azimuth_hint_for_assembly(ni: int, rods_dict: dict = None, unit: str = "мкм", uscale: float = 1e6) -> str:
    if ni <= 1: return "Узлов ni должно быть ≥ 2"
    n_intervals = ni - 1
    nd = _udec(unit)
    types_found = {}
    if rods_dict:
        for r in rods_dict.values():
            types_found[r.rod_type] = r.diameter

    items = []
    if "fuel" in types_found or not types_found:
        d = types_found.get("fuel", 9.1)
        ds = ((math.pi * d) / 6.0 / n_intervals) * 1e-3 * uscale
        items.append(f"ТВЭЛ: {ds:.{nd}f} {unit} (D={d:.1f} мм)")
    if "guide" in types_found:
        d = types_found["guide"]
        ds = ((math.pi * d) / 6.0 / n_intervals) * 1e-3 * uscale
        items.append(f"НК: {ds:.{nd}f} {unit} (D={d:.1f} мм)")
    if "instrument" in types_found:
        d = types_found["instrument"]
        ds = ((math.pi * d) / 6.0 / n_intervals) * 1e-3 * uscale
        items.append(f"ИК: {ds:.{nd}f} {unit} (D={d:.1f} мм)")

    return f"💡 Шаг по дуге (азимут, 60°): Δφ ≈ {' … '.join(items)} при ni = {ni}"

def evaluate_mesh_hints(law: str, mode: str, fields: dict, min_gap_mm: float = 0.95, unit: str = "мкм", uscale: float = 1e6) -> Tuple[str, str]:
    L = max(0.1e-3, min_gap_mm * 1e-3)

    if law == "geometric":
        try:
            h1 = fields["h1"].value()
            n_cells = max(1, fields["layers"].value())
            hmax = fields["hmax"].value()
            growth_val = fields["growth_limit"].value()
        except Exception: return "ok", ""

        if h1 <= 0: return "error", "🔴 Ошибка: Первый шаг h1 должен быть строго больше 0."
        if h1 >= L: return "error", f"🔴 Ошибка: Первый шаг h1 ({h1*1e3:.3f} мм) превышает зазор ({L*1e3:.3f} мм)."

        if mode == "first_count":
            h_avg = L / n_cells
            if h1 >= h_avg:
                return "warning", f"🟡 Сетка сжимается: h1 ({h1*1e6:.1f} мкм) ≥ среднему шагу ({h_avg*1e6:.1f} мкм). Рост q < 1.0."
            try:
                from scipy.optimize import brentq
                def f(q):
                    if abs(q - 1.0) < 1e-7: return h1 * n_cells - L
                    return h1 * (q**n_cells - 1.0) / (q - 1.0) - L
                q_sol = brentq(f, 1.000001, 3.5)
                h_last = h1 * (q_sol**(n_cells - 1))
                if q_sol <= 1.20:
                    return "ok", f"🟢 Рост ячеек q = {q_sol:.3f} | Шаг в зазоре: h_N = {h_last*1e6:.1f} мкм (отлично для CFD)"
                elif q_sol <= 1.35:
                    return "warning", f"🟡 Рост q = {q_sol:.3f} высоковат (рекомендуется q ≤ 1.20) | h_N = {h_last*1e6:.1f} мкм."
                else:
                    return "warning", f"🟠 Рост q = {q_sol:.3f} резкий | h_N = {h_last*1e6:.1f} мкм."
            except Exception:
                return "ok", f"💡 Первый шаг: {h1*1e6:.1f} мкм, слоёв: {n_cells}"

        elif mode == "first_max":
            if hmax <= h1: return "error", f"🔴 Ошибка: hmax ({hmax*1e6:.1f} мкм) ≤ h1 ({h1*1e6:.1f} мкм)."
            return "ok", f"🟢 Предельный размер: {hmax*1e6:.1f} мкм"

        elif mode == "first_growth":
            q = growth_val
            if q <= 1.0: return "error", "🔴 Коэффициент роста q должен быть > 1.0."
            arg = 1.0 + L * (q - 1.0) / h1
            if arg > 0:
                n_est = int(math.ceil(math.log(arg) / math.log(q)))
                h_last = h1 * (q**(n_est - 1))
                return "ok", f"🟢 Рост q = {q:.3f} | Расчётных слоёв: ~{n_est} | h_N = {h_last*1e6:.1f} мкм"

    elif law in ("hyperbolic", "tanh", "sinh"):
        try:
            h1 = fields["h1"].value()
            n_cells = max(1, fields["layers"].value())
        except Exception: return "ok", ""

        if h1 <= 0: return "error", "🔴 Первый шаг h1 должен быть > 0."
        if h1 >= L: return "error", f"🔴 Первый шаг h1 ({h1*1e3:.3f} мм) превышает зазор."

        h_avg = L / n_cells
        if h1 >= h_avg:
            return "error", f"🔴 Первый шаг h1 ({h1*1e6:.1f} мкм) ≥ среднему шагу ({h_avg*1e6:.1f} мкм). Сгущение от стенки невозможно."

        import mesh_core as mc
        actual_law = "sinh" if "sinh" in law else "tanh"
        p_hyp = mc.MeshParams(law=actual_law, mode="first_count", h1=h1, nj=n_cells + 1)
        try:
            import numpy as np
            _, param_hyp = mc.solve_distribution(np.array([L]), p_hyp)
            beta = float(param_hyp[0])
            frac = mc.fractions(param_hyp, n_cells, p_hyp)
            w_all = L * frac[0]
            growth_steps = w_all[1:] / np.maximum(1e-12, w_all[:-1])
            max_q = float(growth_steps.max())
            if max_q <= 1.20 and beta <= 5.5:
                return "ok", f"🟢 Крутизна β = {beta:.2f} | Плавный переход: {h1*1e6:.1f} мкм → {w_all[-1]*1e6:.1f} мкм (макс. q = {max_q:.3f})"
            elif max_q <= 1.35:
                return "warning", f"🟡 Крутизна β = {beta:.2f} высоковат | Переход: {h1*1e6:.1f} → {w_all[-1]*1e6:.1f} мкм (макс. q = {max_q:.3f})"
            else:
                return "warning", f"🟠 Резкий гиперболический профиль (β = {beta:.2f}, макс. q = {max_q:.2f})"
        except Exception:
            return "ok", f"💡 Первый шаг: {h1*1e6:.1f} мкм, слоёв: {n_cells}"

    elif law == "power":
        try:
            h1 = fields["h1"].value()
            n_cells = max(1, fields["layers"].value())
        except Exception: return "ok", ""

        if h1 <= 0: return "error", "🔴 Первый шаг h1 должен быть > 0."
        if h1 >= L: return "error", f"🔴 Первый шаг h1 ({h1*1e3:.3f} мм) превышает зазор."

        h_avg = L / n_cells
        if h1 >= h_avg:
            return "error", f"🔴 Первый шаг h1 ({h1*1e6:.1f} мкм) ≥ среднему шагу ({h_avg*1e6:.1f} мкм). Степенное сгущение невозможно."

        import mesh_core as mc
        p_pow = mc.MeshParams(law="power", mode="first_count", h1=h1, nj=n_cells + 1)
        try:
            import numpy as np
            _, param_pow = mc.solve_distribution(np.array([L]), p_pow)
            alpha = float(param_pow[0])
            frac = mc.fractions(param_pow, n_cells, p_pow)
            w_all = L * frac[0]
            if alpha <= 2.2:
                return "ok", f"🟢 Показатель степени α = {alpha:.2f} | Плавное степенное сгущение: {h1*1e6:.1f} мкм → {w_all[-1]*1e6:.1f} мкм"
            elif alpha <= 3.5:
                return "warning", f"🟡 Показатель степени α = {alpha:.2f} высоковат | Перепад: {h1*1e6:.1f} → {w_all[-1]*1e6:.1f} мкм"
            else:
                return "warning", f"🟠 Резкий степенной закон (α = {alpha:.2f} > 3.5)"
        except Exception:
            return "ok", f"💡 Степенной закон: h1 = {h1*1e6:.1f} мкм, слоёв: {n_cells}"

    elif law == "wall_core":
        try:
            thick = fields["layer_thickness"].value()
            core_max = fields["core_max_size"].value()
            h1 = fields["h1"].value()
            n_wall = fields["layer_cells"].value()
        except Exception: return "ok", ""

        half_gap = L / 2.0
        if thick >= half_gap:
            return "error", f"🔴 Толщина слоя ({thick*1e3:.3f} мм) ≥ полузазору ({half_gap*1e3:.3f} мм). Ядру не останется места!"

        rem_gap = half_gap - thick
        nd = _udec(unit)
        import mesh_core as mc
        p_l = mc.MeshParams(law="wall_core", mode="layer_thickness", wall_layers=n_wall, layer_thickness=thick, h1=h1)
        try:
            w_layer, _ = mc.layer_distribution(p_l)
            h_last_layer = w_layer[-1] * uscale
            safe_core = max(60e-6 * uscale, h_last_layer * 3.0)
            return "ok", (f"🟢 Слой {thick*1e3:.2f} мм (h_кон = {h_last_layer:.{nd}f} {unit}, "
                          f"остаток под ядро {rem_gap*1e3:.2f} мм). "
                          f"Рекомендуемый шаг ядра: {safe_core:.{nd}f}–{160e-6*uscale:.{nd}f} {unit}.")
        except Exception:
            return "ok", f"🟢 Слой: {thick*1e3:.2f} мм (остаток под ядро: {rem_gap*1e3:.2f} мм)."

    return "ok", ""

def format_friendly_error(exc: Exception) -> str:
    msg = str(exc)
    if "CORE_NO_COMMON_COUNT" in msg:
        return (
            "⚠️ Конфликт заполнения ядра: не удалось подобрать общее число слоёв N.\n\n"
            "Что произошло:\n"
            "В узком зазоре между стержнями и в широком центре подканала сильно отличается свободная длина.\n\n"
            "Как исправить:\n"
            "1. Увеличьте «Макс. ячейка в ядре» до 120–160 мкм.\n"
            "2. Увеличьте «Рост в ядре q» с 1.10 до 1.15–1.20.\n"
            "3. Уменьшите «Толщину слоя» в Группе 3 (например, с 350 до 250 мкм)."
        )
    if "превышает зазор" in msg or "превышает физический зазор" in msg:
        return "⚠️ Толщина слоя превышает зазор между стержнями! Уменьшите «Толщину слоя» в Группе 3."
    if "Первый шаг больше среднего" in msg:
        return "⚠️ Первый шаг сетки h1 слишком велик! Уменьшите h1 или увеличьте число слоёв nj."
    return f"⚠️ Ошибка построения сетки:\n\n{msg}"
