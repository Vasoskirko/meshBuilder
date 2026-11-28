"""Section geometry: hydraulics."""
import math
import numpy as np

def calc_hydraulics(self, sub):
    self._diagnostics_cache=None
    if sub.sub_type=='recovered':
        from .recovery import recovered_hydraulics
        sub.a_poly_mm2,sub.a_fluid_mm2,sub.p_wet_mm,sub.d_h_mm=recovered_hydraulics(self,sub)
        return
    pts = np.array(sub.polygon_points)
    n_pts = len(pts)
    a_poly = 0.5 * abs(sum(pts[i, 0] * pts[(i + 1) % n_pts, 1] -
                           pts[(i + 1) % n_pts, 0] * pts[i, 1] for i in range(n_pts)))
    stype = sub.sub_type
    a_rods = 0.0
    p_wet_rods = 0.0
    p_wet_wall = 0.0

    if stype in ("interior", "guide_sub", "instrument_sub"):
        pA, pB, pC = pts[0], pts[1], pts[2]
        a = np.linalg.norm(pB - pC)
        b = np.linalg.norm(pC - pA)
        c = np.linalg.norm(pA - pB)

        cosA = np.clip((b**2 + c**2 - a**2) / max(2.0 * b * c, 1e-9), -1.0, 1.0)
        cosB = np.clip((a**2 + c**2 - b**2) / max(2.0 * a * c, 1e-9), -1.0, 1.0)
        cosC = np.clip((a**2 + b**2 - c**2) / max(2.0 * a * b, 1e-9), -1.0, 1.0)
        angles = [math.acos(cosA), math.acos(cosB), math.acos(cosC)]

        for rid, theta in zip(sub.rod_ids, angles):
            r = self.rods[rid].diameter / 2.0
            a_rods += 0.5 * (r ** 2) * theta
            p_wet_rods += r * theta
    elif stype in ('peripheral','corner'):
        for i,rid in enumerate(sub.rod_ids):
            u=pts[i-1]-pts[i];v=pts[(i+1)%n_pts]-pts[i]
            denominator=np.linalg.norm(u)*np.linalg.norm(v)
            theta=math.acos(np.clip(np.dot(u,v)/denominator,-1.,1.)) if denominator>0 else 0.
            radius=self.rods[rid].diameter/2
            a_rods+=.5*radius**2*theta;p_wet_rods+=radius*theta
        p_wet_wall=np.linalg.norm(pts[2]-pts[3])

    a_fluid = max(a_poly - a_rods, 1e-4)
    p_wet = max(p_wet_rods + p_wet_wall, 1e-4)
    d_h = 4.0 * a_fluid / p_wet

    sub.a_poly_mm2 = float(a_poly)
    sub.a_fluid_mm2 = float(a_fluid)
    sub.p_wet_mm = float(p_wet)
    sub.d_h_mm = float(d_h)


def _calc_summary_for_ids(self, sub_ids):
    if not sub_ids:
        return None
    total_a_fluid = sum(self.subchannels[sid].a_fluid_mm2 for sid in sub_ids if sid in self.subchannels)
    total_p_wet = sum(self.subchannels[sid].p_wet_mm for sid in sub_ids if sid in self.subchannels)
    d_h = (4.0 * total_a_fluid / total_p_wet) if total_p_wet > 0 else 0.0

    by_type = {}
    for sid in sub_ids:
        if sid not in self.subchannels:
            continue
        s = self.subchannels[sid]
        if s.sub_type not in by_type:
            by_type[s.sub_type] = {"count": 0, "a_fluid": 0.0, "p_wet": 0.0}
        by_type[s.sub_type]["count"] += 1
        by_type[s.sub_type]["a_fluid"] += s.a_fluid_mm2
        by_type[s.sub_type]["p_wet"] += s.p_wet_mm

    for st in by_type.values():
        st["d_h"] = (4.0 * st["a_fluid"] / st["p_wet"]) if st["p_wet"] > 0 else 0.0

    return {
        "total_subchannels": len(sub_ids),
        "total_a_fluid_mm2": float(total_a_fluid),
        "total_p_wet_mm": float(total_p_wet),
        "total_d_h_mm": float(d_h),
        "by_type": by_type
    }
