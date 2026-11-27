"""Section geometry: subchannels."""
import math
from itertools import combinations
import numpy as np
from .types import Subchannel

def generate_subchannels(self):
    self._diagnostics_cache=None
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
