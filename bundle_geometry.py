# -*- coding: utf-8 -*-
"""Геометрическая модель пучка стержней и подканалов ТВС (версия 2.8)."""
import math, json
from dataclasses import dataclass, field
import numpy as np
from itertools import combinations
from bundle_geometry_validation import positive,validate_geometry,sub_signature

@dataclass
class RodData:
    rod_id: int
    q: int
    r: int
    x: float
    y: float
    diameter: float
    rod_type: str = "fuel"  # "fuel", "guide", "instrument"
    custom_diameter: bool = False
    is_clashing: bool = False

@dataclass
class Subchannel:
    sub_id: int
    sub_type: str  # "interior", "guide_sub", "instrument_sub", "peripheral", "corner"
    rod_ids: list  # [rod_id, ...]
    wall_side: int = -1  # 0..5
    corner_index: int = -1  # 0..5
    centroid: tuple = (0.0, 0.0)
    fluid_center: tuple = (0.0, 0.0)
    polygon_points: list = field(default_factory=list)
    neighbor_sub_ids: list = field(default_factory=list)
    boundary_edges: list = field(default_factory=list)
    # Гидравлика
    a_poly_mm2: float = 0.0
    a_fluid_mm2: float = 0.0
    p_wet_mm: float = 0.0
    d_h_mm: float = 0.0


class BundleModel:
    def __init__(self, s_flat=65.0, pitch=12.75, d_fuel=9.1, d_guide=12.0, d_instrument=10.3, lattice_type="triangular"):
        self.s_flat = float(s_flat)
        self.pitch = float(pitch)
        self.d_fuel = float(d_fuel)
        self.d_guide = float(d_guide)
        self.d_instrument = float(d_instrument)
        self.lattice_type = lattice_type

        self.rods = {}                    # rod_id -> RodData
        self.coord_to_rod_id = {}         # (q, r) -> rod_id
        self.user_rod_types = {}          # (q, r) -> "guide" | "instrument"
        self.user_custom_diameters = {}   # (q, r) -> float diameter
        self.user_deleted_coords = set()  # set of (q, r) удалённых вручную стержней
        self.auto_deleted_clash_coords = set() # (q, r) удалённых при подтверждении коллизий

        self.subchannels = {}             # sub_id -> Subchannel
        self.selected_subchannels = set() # set of sub_id
        self.active_rod_coord = None      # (q, r) выбранного стержня (стабильный ключ!)
        self.active_sub_id = None
        self.detected_clashes = []

        self.update_geometry()

    @property
    def active_rod_id(self):
        if self.active_rod_coord in self.coord_to_rod_id:
            return self.coord_to_rod_id[self.active_rod_coord]
        return None

    def deselect_rod(self):
        """Снимает выделение со стержня."""
        self.active_rod_coord = None

    def clear_all_selection(self):
        """Сбрасывает выбор подканалов и снимает выделение со стержня."""
        self.selected_subchannels.clear()
        self.active_rod_coord = None
        self.active_sub_id = None

    def reset_custom_overrides(self):
        """Полный сброс всех настроек к исходному пучку ТВЭЛов."""
        self.user_rod_types.clear()
        self.user_custom_diameters.clear()
        self.user_deleted_coords.clear()
        self.auto_deleted_clash_coords.clear()
        self.selected_subchannels.clear()
        self.active_rod_coord = None
        self.active_sub_id = None

    def update_geometry(self):
        validate_geometry(self)
        selected={sub_signature(self,self.subchannels[k]) for k in self.selected_subchannels if k in self.subchannels}
        active=sub_signature(self,self.subchannels[self.active_sub_id]) if self.active_sub_id in self.subchannels else None
        self.rods.clear()
        self.coord_to_rod_id.clear()
        self.subchannels.clear()
        self.detected_clashes.clear()

        R_vertex = (self.s_flat / 2.0) / math.cos(math.radians(30))
        self.hex_vertices = [
            np.array([R_vertex * math.cos(math.radians(60 * i)),
                      R_vertex * math.sin(math.radians(60 * i))])
            for i in range(6)
        ]
        angles_deg = [30, 90, 150, 210, 270, 330]
        self.normals = [np.array([math.cos(math.radians(a)), math.sin(math.radians(a))]) for a in angles_deg]

        max_ring = int(math.ceil(self.s_flat / self.pitch)) + 1

        all_sites = []
        for q in range(-max_ring, max_ring + 1):
            for r in range(-max_ring, max_ring + 1):
                x = self.pitch * (q + r / 2.0)
                y = self.pitch * (math.sqrt(3.0) / 2.0 * r)
                pt = np.array([x, y])
                dists = [(self.s_flat / 2.0) - np.dot(pt, n) for n in self.normals]
                if all(dist >= (self.d_fuel / 2.0) - 1e-4 for dist in dists):
                    all_sites.append((r, q, x, y))

        all_sites.sort()
        permanent_site_ids = {(q, r): idx for idx, (r, q, x, y) in enumerate(all_sites)}

        candidate_rods = []
        for (r, q, x, y) in all_sites:
            coord = (q, r)
            if coord in self.user_deleted_coords or coord in self.auto_deleted_clash_coords:
                continue

            pt = np.array([x, y])
            rtype = self.user_rod_types.get(coord, "fuel")

            if coord in self.user_custom_diameters:
                diam = self.user_custom_diameters[coord]
                custom = True
            else:
                if rtype == "guide":
                    diam = self.d_guide
                elif rtype == "instrument":
                    diam = self.d_instrument
                else:
                    diam = self.d_fuel
                custom = False

            radius = diam / 2.0
            dists = [(self.s_flat / 2.0) - np.dot(pt, n) for n in self.normals]
            if all(dist >= radius - 1e-4 for dist in dists):
                permanent_id = permanent_site_ids[coord]
                rod = RodData(
                    rod_id=permanent_id,
                    q=q, r=r,
                    x=x, y=y,
                    diameter=diam,
                    rod_type=rtype,
                    custom_diameter=custom
                )
                candidate_rods.append(rod)

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

        for r in candidate_rods:
            self.rods[r.rod_id] = r
            self.coord_to_rod_id[(r.q, r.r)] = r.rod_id

        self.generate_subchannels()
        self.selected_subchannels={k for k,v in self.subchannels.items() if sub_signature(self,v) in selected}
        self.active_sub_id=next((k for k,v in self.subchannels.items() if sub_signature(self,v)==active),None)
        if self.active_rod_coord not in self.coord_to_rod_id:self.active_rod_coord=None

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

    def apply_rod_change(self, coord, rod_type, diameter, delete_clashes=False):
        if coord not in self.coord_to_rod_id:raise ValueError('Стержень отсутствует в текущей геометрии')
        if rod_type not in ('fuel','guide','instrument'):raise ValueError('Неизвестный тип стержня')
        use_custom=diameter is not None
        default={'fuel':self.d_fuel,'guide':self.d_guide,'instrument':self.d_instrument}[rod_type]
        diameter=default if diameter is None else positive(diameter,'Диаметр стержня')
        rod=self.rods[self.coord_to_rod_id[coord]]
        if any(self.s_flat/2-rod.x*n[0]-rod.y*n[1]<diameter/2-1e-4 for n in self.normals):
            raise ValueError('Стержень пересекает оболочку')
        if delete_clashes:
            clashes = self.check_clashes_for_coord(coord, diameter)
            for c in clashes:
                self.auto_deleted_clash_coords.add((c.q, c.r))

        if rod_type == "fuel":
            self.user_rod_types.pop(coord, None)
            if math.isclose(diameter,self.d_fuel,rel_tol=0,abs_tol=1e-12):self.user_custom_diameters.pop(coord,None)
            else:self.user_custom_diameters[coord]=float(diameter)
        else:
            self.user_rod_types[coord] = rod_type
            if use_custom:
                self.user_custom_diameters[coord] = float(diameter)
            else:
                self.user_custom_diameters.pop(coord, None)

        self.active_rod_coord = coord
        self.update_geometry()

    def delete_active_rod_manually(self):
        if self.active_rod_coord is None:
            return
        self.user_deleted_coords.add(self.active_rod_coord)
        self.user_rod_types.pop(self.active_rod_coord, None)
        self.user_custom_diameters.pop(self.active_rod_coord, None)
        self.active_rod_coord = None
        self.update_geometry()

    def restore_deleted_rods(self):
        self.user_deleted_coords.clear()
        self.auto_deleted_clash_coords.clear()
        self.update_geometry()

    def select_all_subchannels(self):
        self.selected_subchannels = set(self.subchannels.keys())
        self.active_sub_id = None

    def generate_subchannels(self):
        self.subchannels.clear()
        sub_counter = 0

        def _has_missing_neighbors(rod):
            for dq, dr in [(1, 0), (-1, 0), (0, 1), (0, -1), (1, -1), (-1, 1)]:
                nq, nr = rod.q + dq, rod.r + dr
                if (nq, nr) in self.user_deleted_coords or (nq, nr) in self.auto_deleted_clash_coords:
                    return True
                nid = self.coord_to_rod_id.get((nq, nr))
                if nid is not None and self.rods[nid].is_clashing:
                    return True
            return False

        enlarged_tubes = [r for r in self.rods.values() if not r.is_clashing and r.diameter > self.pitch * 0.95 and _has_missing_neighbors(r)]
        created_triangles = set()

        for g in enlarged_tubes:
            g_id = g.rod_id
            cg = np.array([g.x, g.y])
            surrounding = []
            for r in self.rods.values():
                if r.rod_id != g_id and not r.is_clashing:
                    cr = np.array([r.x, r.y])
                    d = np.linalg.norm(cr - cg)
                    if d <= self.pitch * 2.25:
                        ang = math.atan2(cr[1] - cg[1], cr[0] - cg[0])
                        surrounding.append((ang, r.rod_id, cr))

            surrounding.sort(key=lambda t: t[0])
            n_surr = len(surrounding)
            for i in range(n_surr):
                r1_id = surrounding[i][1]
                r2_id = surrounding[(i + 1) % n_surr][1]
                p1 = surrounding[i][2]
                p2 = surrounding[(i + 1) % n_surr][2]

                d_ang = (surrounding[(i + 1) % n_surr][0] - surrounding[i][0]) % (2 * math.pi)
                if d_ang < math.radians(110):
                    tri_key = tuple(sorted([g_id, r1_id, r2_id]))
                    if tri_key not in created_triangles:
                        created_triangles.add(tri_key)
                        centroid = (cg + p1 + p2) / 3.0

                        mid_gap = (p1 + p2) / 2.0
                        dir_to_gap = mid_gap - cg
                        dist_gap = np.linalg.norm(dir_to_gap)
                        if dist_gap > 1e-4:
                            dir_to_gap /= dist_gap
                            surface_pt = cg + dir_to_gap * (g.diameter / 2.0)
                            f_center = (surface_pt + mid_gap) / 2.0
                        else:
                            f_center = centroid

                        if all((self.s_flat / 2.0) - np.dot(centroid, n) >= 0.0 for n in self.normals):
                            stype = "guide_sub" if g.rod_type == "guide" else ("instrument_sub" if g.rod_type == "instrument" else "interior")
                            sub = Subchannel(
                                sub_id=sub_counter,
                                sub_type=stype,
                                rod_ids=[g_id, r1_id, r2_id],
                                centroid=tuple(centroid),
                                fluid_center=tuple(f_center),
                                polygon_points=[cg.tolist(), p1.tolist(), p2.tolist()],
                                boundary_edges=[(min(g_id, r1_id), max(g_id, r1_id)),
                                                (min(r1_id, r2_id), max(r1_id, r2_id)),
                                                (min(r2_id, g_id), max(r2_id, g_id))]
                            )
                            self.calc_hydraulics(sub)
                            self.subchannels[sub_counter] = sub
                            sub_counter += 1

        valid_rods = [rod for rod in self.rods.values() if not rod.is_clashing]
        pts = np.array([[rod.x, rod.y] for rod in valid_rods])
        rod_ids = [r.rod_id for r in valid_rods]

        if len(pts) >= 3 and np.linalg.matrix_rank(pts-pts[0])>=2:
            from scipy.spatial import Delaunay
            tri = Delaunay(pts)
            for sim in tri.simplices:
                r1, r2, r3 = rod_ids[sim[0]], rod_ids[sim[1]], rod_ids[sim[2]]
                tri_key = tuple(sorted([r1, r2, r3]))
                if tri_key in created_triangles:
                    continue

                p1 = np.array([self.rods[r1].x, self.rods[r1].y])
                p2 = np.array([self.rods[r2].x, self.rods[r2].y])
                p3 = np.array([self.rods[r3].x, self.rods[r3].y])

                edges = [np.linalg.norm(p1 - p2), np.linalg.norm(p2 - p3), np.linalg.norm(p3 - p1)]
                if max(edges) <= self.pitch * 1.25:
                    created_triangles.add(tri_key)
                    centroid = (p1 + p2 + p3) / 3.0
                    if all((self.s_flat / 2.0) - np.dot(centroid, n) >= 0.0 for n in self.normals):
                        rtypes = {self.rods[r1].rod_type, self.rods[r2].rod_type, self.rods[r3].rod_type}
                        if "guide" in rtypes:
                            stype = "guide_sub"
                        elif "instrument" in rtypes:
                            stype = "instrument_sub"
                        else:
                            stype = "interior"

                        sub = Subchannel(
                            sub_id=sub_counter,
                            sub_type=stype,
                            rod_ids=[r1, r2, r3],
                            centroid=tuple(centroid),
                            fluid_center=tuple(centroid),
                            polygon_points=[p1.tolist(), p2.tolist(), p3.tolist()],
                            boundary_edges=[(min(r1, r2), max(r1, r2)),
                                            (min(r2, r3), max(r2, r3)),
                                            (min(r3, r1), max(r3, r1))]
                        )
                        self.calc_hydraulics(sub)
                        self.subchannels[sub_counter] = sub
                        sub_counter += 1

        for side_idx in range(6):
            n = self.normals[side_idx]
            v_start = self.hex_vertices[side_idx]
            v_end = self.hex_vertices[(side_idx + 1) % 6]
            side_vec = v_end - v_start
            side_len = np.linalg.norm(side_vec)
            side_dir = side_vec / side_len

            rods_on_side = []
            for r_id, rod in self.rods.items():
                if rod.is_clashing:
                    continue
                pt = np.array([rod.x, rod.y])
                dist_wall = (self.s_flat / 2.0) - np.dot(pt, n)
                if dist_wall < self.pitch * 1.15:
                    proj = np.dot(pt - v_start, side_dir)
                    rods_on_side.append((proj, r_id, pt))

            rods_on_side.sort(key=lambda t: t[0])

            for i in range(len(rods_on_side) - 1):
                r1_id = rods_on_side[i][1]
                r2_id = rods_on_side[i + 1][1]
                p1 = rods_on_side[i][2]
                p2 = rods_on_side[i + 1][2]

                dist1 = (self.s_flat / 2.0) - np.dot(p1, n)
                dist2 = (self.s_flat / 2.0) - np.dot(p2, n)
                w1 = p1 + dist1 * n
                w2 = p2 + dist2 * n

                is_first = (i == 0)
                is_last = (i == len(rods_on_side) - 2)

                if is_first and is_last:
                    poly=[p1.tolist(),p2.tolist(),v_end.tolist(),v_start.tolist()]
                    stype='corner';c_idx=-1
                    f_center=((p1+p2)/2+(v_start+v_end)/2)/2
                elif is_first:
                    poly = [p1.tolist(), p2.tolist(), w2.tolist(), v_start.tolist()]
                    stype = "corner"
                    c_idx = side_idx
                    mid_gap = (p1 + p2) / 2.0
                    mid_wall = (w2 + v_start) / 2.0
                    f_center = mid_gap * 0.30 + mid_wall * 0.70
                elif is_last:
                    poly = [p1.tolist(), p2.tolist(), v_end.tolist(), w1.tolist()]
                    stype = "corner"
                    c_idx = (side_idx + 1) % 6
                    mid_gap = (p1 + p2) / 2.0
                    mid_wall = (w1 + v_end) / 2.0
                    f_center = mid_gap * 0.30 + mid_wall * 0.70
                else:
                    poly = [p1.tolist(), p2.tolist(), w2.tolist(), w1.tolist()]
                    stype = "peripheral"
                    c_idx = -1
                    mid_rods = (p1 + p2) / 2.0
                    mid_wall = (w1 + w2) / 2.0
                    f_center = (mid_rods + mid_wall) / 2.0

                centroid = np.mean(poly, axis=0)
                sub = Subchannel(
                    sub_id=sub_counter,
                    sub_type=stype,
                    rod_ids=[r1_id, r2_id],
                    wall_side=side_idx,
                    corner_index=c_idx,
                    centroid=tuple(centroid),
                    fluid_center=tuple(f_center),
                    polygon_points=poly,
                    boundary_edges=[(min(r1_id, r2_id), max(r1_id, r2_id))]
                )
                self.calc_hydraulics(sub)
                self.subchannels[sub_counter] = sub
                sub_counter += 1

        edge_index={};corner_index={}
        for sid,sub in self.subchannels.items():
            for edge in sub.boundary_edges:edge_index.setdefault(edge,[]).append(sid)
            if sub.sub_type=='corner':
                corners=[sub.corner_index] if sub.corner_index>=0 else [sub.wall_side,(sub.wall_side+1)%6]
                for corner in corners:corner_index.setdefault(corner,[]).append(sid)
        neighbors={sid:set() for sid in self.subchannels}
        for ids in list(edge_index.values())+list(corner_index.values()):
            for a,b in combinations(ids,2):neighbors[a].add(b);neighbors[b].add(a)
        for sid,sub in self.subchannels.items():sub.neighbor_sub_ids=sorted(neighbors[sid])

    def calc_hydraulics(self, sub):
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

        sub.a_poly_mm2 = round(a_poly, 3)
        sub.a_fluid_mm2 = round(a_fluid, 3)
        sub.p_wet_mm = round(p_wet, 3)
        sub.d_h_mm = round(d_h, 3)

    def select_subchannel(self, sub_id):
        if sub_id not in self.subchannels:raise ValueError('Подканал отсутствует в текущей геометрии')
        if sub_id in self.selected_subchannels:
            self.selected_subchannels.remove(sub_id)
        else:
            self.selected_subchannels.add(sub_id)
        self.active_sub_id = sub_id

    def add_subchannel(self, sub_id):
        if sub_id not in self.subchannels:raise ValueError('Подканал отсутствует в текущей геометрии')
        self.selected_subchannels.add(sub_id)
        self.active_sub_id = sub_id

    def remove_subchannel(self, sub_id):
        self.selected_subchannels.discard(sub_id)
        if self.active_sub_id == sub_id:
            self.active_sub_id = None

    def get_candidate_neighbors(self):
        if not self.selected_subchannels:
            return set()
        candidates = set()
        for sub_id in self.selected_subchannels:
            sub = self.subchannels[sub_id]
            for n_id in sub.neighbor_sub_ids:
                if n_id not in self.selected_subchannels:
                    candidates.add(n_id)
        return candidates

    def get_selection_summary(self):
        return self._calc_summary_for_ids(self.selected_subchannels)

    def get_total_assembly_summary(self):
        return self._calc_summary_for_ids(self.subchannels.keys())

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
            "total_a_fluid_mm2": round(total_a_fluid, 3),
            "total_p_wet_mm": round(total_p_wet, 3),
            "total_d_h_mm": round(d_h, 3),
            "by_type": by_type
        }

    def export_dict(self):
        selected_rods = set()
        sub_list = []
        for s_id in sorted(self.selected_subchannels):
            s = self.subchannels[s_id]
            sub_list.append({
                "subchannel_id": s.sub_id,
                "type": s.sub_type,
                "rod_ids": s.rod_ids,
                "wall_side": s.wall_side,
                "corner_index": s.corner_index,
                "centroid_mm": list(s.centroid),
                "a_fluid_mm2": s.a_fluid_mm2,
                "p_wet_mm": s.p_wet_mm,
                "d_h_mm": s.d_h_mm
            })
            selected_rods.update(s.rod_ids)

        rods_list = []
        for r_id in sorted(selected_rods):
            r = self.rods[r_id]
            rods_list.append({
                "rod_id": r.rod_id,
                "q": r.q, "r": r.r,
                "center_mm": [r.x, r.y],
                "diameter_mm": r.diameter,
                "type": r.rod_type,
                "custom_diameter": r.custom_diameter
            })

        return {
            "format": "bundle-cross-section",
            "version": 3,
            "lattice": {
                "type": self.lattice_type,
                "pitch_mm": self.pitch,
                "s_across_flats_mm": self.s_flat,
                "default_d_fuel_mm": self.d_fuel,
                "default_d_guide_mm": self.d_guide,
                "default_d_instrument_mm": self.d_instrument
            },
            "selected_subchannels_count": len(sub_list),
            "selected_rods_count": len(rods_list),
            "subchannels": sub_list,
            "rods": rods_list,
            "user_deleted_coords": list(self.user_deleted_coords),
            "summary_hydraulics": self.get_selection_summary(),
            "assembly_hydraulics": self.get_total_assembly_summary()
        }
