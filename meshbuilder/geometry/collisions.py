"""Rod collision detection, separate from lattice construction and editing."""
import math
from itertools import combinations
import numpy as np


def annotate_clashes(self,candidate_rods):
    large_rods = [r for r in candidate_rods if r.rod_type in ("guide", "instrument") or r.custom_diameter]
    for g in large_rods:
        cg = np.array([g.x, g.y])
        rg = g.diameter / 2.0
        for f in candidate_rods:
            if f.rod_id != g.rod_id and f.rod_type == "fuel":
                cf = np.array([f.x, f.y])
                rf = f.diameter / 2.0
                dist = np.linalg.norm(cg - cf)
                if dist < (rg + rf - 1e-4):
                    f.is_clashing = True
                    self.detected_clashes.append({
                        "fuel_rod_id": f.rod_id,
                        "fuel_coord": (f.q, f.r),
                        "large_rod_id": g.rod_id,
                        "large_rod_type": g.rod_type,
                        "distance_mm": round(dist, 2),
                        "required_clearance_mm": round(rg + rf, 2)
                    })

    # Special tubes also collide with each other; neither may enter a fluid triangle.
    for a,b in combinations([r for r in candidate_rods if r.rod_type!='fuel'],2):
        distance=math.hypot(a.x-b.x,a.y-b.y);required=(a.diameter+b.diameter)/2
        if distance<required-1e-4:
            a.is_clashing=b.is_clashing=True
            self.detected_clashes.append(dict(rod_ids=(a.rod_id,b.rod_id),distance_mm=distance,required_clearance_mm=required))



def check_clashes_for_coord(self, coord, new_diameter):
    x = self.pitch * (coord[0] + coord[1] / 2.0)
    y = self.pitch * (math.sqrt(3.0) / 2.0 * coord[1])
    cg = np.array([x, y])
    rg = float(new_diameter) / 2.0

    clashes = []
    for r_id, rod in self.rods.items():
        if (rod.q, rod.r) != coord and rod.rod_type == "fuel":
            cf = np.array([rod.x, rod.y])
            rf = rod.diameter / 2.0
            dist = np.linalg.norm(cg - cf)
            if dist < (rg + rf - 1e-4):
                clashes.append(rod)
    return clashes
