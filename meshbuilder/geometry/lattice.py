"""Section geometry: lattice."""
import math
import numpy as np
from .types import RodData
from .collisions import annotate_clashes
from .validation import validate_geometry,sub_signature

def update_geometry(self):
    validate_geometry(self)
    selected={sub_signature(self,self.subchannels[k]) for k in self.selected_subchannels if k in self.subchannels}
    active=sub_signature(self,self.subchannels[self.active_sub_id]) if self.active_sub_id in self.subchannels else None
    self._diagnostics_cache=None
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

    annotate_clashes(self,candidate_rods)

    for r in candidate_rods:
        self.rods[r.rod_id] = r
        self.coord_to_rod_id[(r.q, r.r)] = r.rod_id

    self.generate_subchannels()
    self.selected_subchannels={k for k,v in self.subchannels.items() if sub_signature(self,v) in selected}
    self.active_sub_id=next((k for k,v in self.subchannels.items() if sub_signature(self,v)==active),None)
    if self.active_rod_coord not in self.coord_to_rod_id:self.active_rod_coord=None
