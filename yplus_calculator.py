# -*- coding: utf-8 -*-
import math

FLUID_MODES = [
    "Вода IAPWS-97 (T, P)",
    "Идеальный газ (сжимаемый)",
    "Идеальный газ (несжимаемый)",
    "Пользовательская (ручной ввод)"
]

def fmt_step_auto(x_um: float) -> str:
    if x_um >= 1000.0:
        return f"{x_um/1000.0:.3f} мм ({x_um:.1f} мкм)"
    if x_um < 1.0:
        return f"{x_um:.3f} мкм ({x_um*1000.0:.1f} нм)"
    return f"{x_um:.3f} мкм"

def calculate_yplus_and_step(mode, value, rho, mu, dh_mm, area_mm2, y_plus=1.0, target_yplus=None):
    if target_yplus is not None: y_plus = target_yplus
    dh, A = dh_mm * 1e-3, area_mm2 * 1e-6
    if rho <= 0 or mu <= 0: raise ValueError("Плотность и вязкость должны быть > 0.")
    if dh <= 0 or A <= 0: raise ValueError("Гидравлические размеры должны быть > 0.")
    if y_plus <= 0: raise ValueError("Целевой y+ должен быть > 0.")

    if mode == "reynolds":
        re = float(value)
        if re <= 0: raise ValueError("Число Re должно быть > 0.")
        u = re * mu / (rho * dh)
    elif mode == "velocity":
        u = float(value)
        if u <= 0: raise ValueError("Скорость должна быть > 0.")
        re = rho * u * dh / mu
    elif mode == "flow_rate":
        q = float(value)
        if q <= 0: raise ValueError("Расход должен быть > 0.")
        u = q / (A * rho)
        re = rho * u * dh / mu
    else:
        raise ValueError(f"Неизвестный режим: {mode}")

    if re < 100:
        cf = 16.0 / max(1.0, re)
    else:
        term = 2.0 * math.log10(re) - 0.65
        cf = 0.05 if term <= 0 else term ** (-2.3)

    tau = 0.5 * cf * rho * u * u
    ut = math.sqrt(tau / rho) if tau > 0 else 1e-6
    y1_m = (y_plus * mu) / (rho * ut)
    d1_m = 2.0 * y1_m
    d1_um = d1_m * 1e6
    y1_um = y1_m * 1e6

    return {
        "re": re, "u": u, "mass_flow": rho * u * A, "mass_flux": rho * u,
        "cf": cf, "tau_w": tau, "u_tau": ut,
        "y1_um": y1_um, "delta_y1_um": d1_um,
        "h1_insert_um": round(d1_um, 3),
        "step_display_str": f"h1 = Δy₁ = {fmt_step_auto(d1_um)} | y₁ = {fmt_step_auto(y1_um)}"
    }
