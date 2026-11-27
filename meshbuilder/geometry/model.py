"""Public facade for section geometry; calculations live in focused modules."""
from .types import RodData,Subchannel
from . import lattice,subchannels,hydraulics,selection,edits,export,collisions


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
        return selection.deselect_rod(self)

    def clear_all_selection(self):
        return selection.clear_all_selection(self)

    def reset_custom_overrides(self):
        return edits.reset_custom_overrides(self)

    def update_geometry(self):
        return lattice.update_geometry(self)

    def check_clashes_for_coord(self, coord, new_diameter):
        return collisions.check_clashes_for_coord(self,coord,new_diameter)

    def apply_rod_change(self, coord, rod_type, diameter, delete_clashes=False):
        return edits.apply_rod_change(self,coord,rod_type,diameter,delete_clashes)

    def delete_active_rod_manually(self):
        return edits.delete_active_rod_manually(self)

    def restore_deleted_rods(self):
        return edits.restore_deleted_rods(self)

    def select_all_subchannels(self):
        return selection.select_all_subchannels(self)

    def generate_subchannels(self):
        return subchannels.generate_subchannels(self)

    def calc_hydraulics(self, sub):
        return hydraulics.calc_hydraulics(self,sub)

    def select_subchannel(self, sub_id):
        return selection.select_subchannel(self,sub_id)

    def add_subchannel(self, sub_id):
        return selection.add_subchannel(self,sub_id)

    def remove_subchannel(self, sub_id):
        return selection.remove_subchannel(self,sub_id)

    def get_candidate_neighbors(self):
        return selection.get_candidate_neighbors(self)

    def get_selection_summary(self):
        return selection.get_selection_summary(self)

    def get_total_assembly_summary(self):
        return selection.get_total_assembly_summary(self)

    def _calc_summary_for_ids(self, sub_ids):
        return hydraulics._calc_summary_for_ids(self,sub_ids)

    def get_geometry_diagnostics(self):
        if getattr(self,'_diagnostics_cache',None) is None:
            from meshbuilder.geometry.diagnostics import diagnose
            self._diagnostics_cache=diagnose(self)
        return self._diagnostics_cache

    def export_dict(self):
        return export.export_dict(self)
