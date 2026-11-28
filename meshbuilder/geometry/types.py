"""Section model records, stored as numbers in project JSON."""
from dataclasses import dataclass,field

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

    polygon_holes: list = field(default_factory=list)
