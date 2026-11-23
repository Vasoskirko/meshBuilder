# -*- coding: utf-8 -*-
"""Вода: IF97 Region 1 + IAPWS 2008/2011; газы: идеальный газ."""
import math

from iapws import IAPWS97
from iapws._iapws import _ThCond

WATER_CONDUCTIVITY_MODELS = {
    "background": "Базовая теплопроводность λ (без добавочного вклада)",
    "full": "Теплопроводность λ с добавочным вкладом около критической точки",
}

def _saturation_pressure_mpa(T):
    """IF97 Region 4 saturation pressure; T is in kelvin."""
    n = (1167.0521452767, -724213.16703206, -17.073846940092,
         12020.82470247, -3232555.0322333, 14.91510861353,
         -4823.2657361591, 405113.40542057, -0.23855557567849,
         650.17534844798)
    theta = T + n[8] / (T - n[9])
    A = theta * theta + n[0] * theta + n[1]
    B = n[2] * theta * theta + n[3] * theta + n[4]
    C = n[5] * theta * theta + n[6] * theta + n[7]
    return (2 * C / (-B + math.sqrt(B * B - 4 * A * C))) ** 4


def _saturation_properties(t_c, p_mpa, p_sat):
    """Reference coexistence states at P; no separate phases at/above Pc."""
    result = dict(saturation_pressure_mpa=p_sat, pressure_margin_mpa=p_mpa-p_sat,
        saturation_temperature_c=None, subcooling_k=None,
        saturated_liquid_density=None, saturated_vapor_density=None,
        saturated_liquid_enthalpy=None, saturated_vapor_enthalpy=None, latent_heat=None)
    if p_mpa < 0.000611657:
        result['saturation_status'] = 'P ниже давления тройной точки: состояния насыщения при P не рассчитываются'
    elif p_mpa >= 22.064:
        result['saturation_status'] = 'P ≥ 22.064 МПа: отдельных жидкой и паровой фаз насыщения при P нет'
    else:
        liquid = IAPWS97(P=p_mpa, x=0)
        vapor = IAPWS97(P=p_mpa, x=1)
        tsat = float(liquid.T - 273.15)
        margin = tsat-t_c
        result.update(saturation_temperature_c=tsat,
            subcooling_k=0.0 if abs(margin)<1e-9 else margin,
            saturated_liquid_density=float(liquid.rho), saturated_vapor_density=float(vapor.rho),
            saturated_liquid_enthalpy=float(liquid.h*1000), saturated_vapor_enthalpy=float(vapor.h*1000),
            latent_heat=float((vapor.h-liquid.h)*1000),
            saturation_status='Свойства насыщенной жидкости и пара рассчитаны при заданном P')
    return result


def water_iapws97(t_c: float, p_mpa: float, *, conductivity_model="background") -> dict:
    """Свойства воды: Регион 1 IAPWS-IF97 (жидкость при 0..350 °C, p до 100 МПа)."""
    if conductivity_model not in WATER_CONDUCTIVITY_MODELS:
        raise ValueError("Неизвестная модель теплопроводности воды")
    if not math.isfinite(t_c) or not math.isfinite(p_mpa):
        raise ValueError("Температура и давление должны быть конечными")
    T = t_c + 273.15
    if not (273.15 <= T <= 623.15):
        raise ValueError("Регион 1 IAPWS-IF97 применим при 0…350 °C")
    if not 0 < p_mpa <= 100:
        raise ValueError("Регион 1 IAPWS-IF97: давление должно быть > 0 и <= 100 МПа")
    if p_mpa < _saturation_pressure_mpa(T):
        raise ValueError("Регион 1 IAPWS-IF97: давление ниже давления насыщения; жидкая вода не поддерживается в этой точке")

    # The T,P classifier may choose vapor at saturation due to floating-point
    # roundoff (notably at 100 °C). This API intentionally returns liquid there.
    saturation = _saturation_pressure_mpa(T)
    if math.isclose(p_mpa, saturation, rel_tol=1e-12, abs_tol=1e-14):
        state = IAPWS97(T=T, x=0)
    else:
        state = IAPWS97(T=T, P=p_mpa)
    if state.region != 1:
        raise ValueError("Требуется жидкая вода в регионе 1 IAPWS-IF97")

    # R15-11 separates background conductivity lambda0*lambda1 from the
    # additive critical enhancement. STAR's reported 300 C / 15 MPa value
    # agrees with the background form; do not emulate it with a fitted factor.
    # The pinned, documented _ThCond kernel omits enhancement without a phase.
    conductivity = _ThCond(state.rho, state.T) if conductivity_model == "background" else state.k
    rho, mu, cp_j, lam = map(float, (state.rho, state.mu, state.cp * 1000.0, conductivity))
    if any(not math.isfinite(value) or value <= 0 for value in (rho, mu, cp_j, lam)):
        raise ValueError("IAPWS вернул недопустимые свойства воды")
    result = {
        "density": rho, "dyn_vis": mu, "kin_vis": mu / rho, "cp": cp_j,
        "lambda": lam, "prandtl": mu * cp_j / lam, "enthalpy": float(state.h*1000),
        "t_ref_c": t_c, "p_ref_mpa": p_mpa, "conductivity_model": conductivity_model,
        "desc": f"Вода: IF97, μ — IAPWS 2008, λ — IAPWS 2011 ({WATER_CONDUCTIVITY_MODELS[conductivity_model]}); T={t_c:.1f} °C, P={p_mpa:.2f} МПа"
    }
    result.update(_saturation_properties(t_c, p_mpa, saturation))
    return result


GASES = {
    "Воздух": (0.0289647, 1005.0, 1.40, 1.716e-5, 110.4),
    "Азот": (0.0280134, 1040.0, 1.40, 1.663e-5, 107.0),
    "Гелий": (0.0040026, 5193.0, 1.667, 1.87e-5, 79.4),
    "CO2": (0.04401, 846.0, 1.289, 1.37e-5, 222.0)
}
GAS_PRESETS = GASES

def gas_properties(name: str, t_c: float, p_mpa: float, compressible: bool = True) -> dict:
    M, cp, gam, mu0, S = GASES.get(name, GASES["Воздух"])
    T = t_c + 273.15
    Rg = 8.314462 / M
    p = p_mpa * 1e6 if compressible else 101325.0
    rho = p / (Rg * T)
    mu = mu0 * ((T / 273.15) ** 1.5) * ((273.15 + S) / (T + S))
    lam = mu * (cp + 1.25 * Rg)
    pr = (mu * cp) / max(1e-5, lam)
    return {
        "density": round(rho, 4), "dyn_vis": mu, "cp": cp, "gamma": gam,
        "lambda": round(lam, 4), "prandtl": round(pr, 2),
        "desc": f"{name} ({'сжимаемый' if compressible else 'несжимаемый'})"
    }
