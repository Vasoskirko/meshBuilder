"""Section geometry: edits."""
import math
from .validation import positive

def reset_custom_overrides(self):
    """Полный сброс всех настроек к исходному пучку ТВЭЛов."""
    self.user_rod_types.clear()
    self.user_custom_diameters.clear()
    self.user_deleted_coords.clear()
    self.auto_deleted_clash_coords.clear()
    self.selected_subchannels.clear()
    self.active_rod_coord = None
    self.active_sub_id = None




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
