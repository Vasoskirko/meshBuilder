"""Section geometry: export."""


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
