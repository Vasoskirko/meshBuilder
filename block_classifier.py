# -*- coding: utf-8 -*-
from dataclasses import dataclass
from typing import Dict, List, Tuple, Set, Optional
import numpy as np

@dataclass
class BlockTemplate:
    template_id: int
    name: str
    rod_type: str
    diameter_mm: float
    neighbor_diameter_mm: float
    gap_mm: float
    length_gap_mm: float
    length_center_mm: float
    signature: tuple
    blocks_count: int = 0
    is_custom_override: bool = False
    custom_name: str = ""

@dataclass
class BlockInstance:
    subchannel_id: int
    block_index: int
    template_id: int
    rod_id: int
    neighbor_rod_id: int
    length_gap_mm: float
    length_center_mm: float
    global_block_id: int = 0
    custom_override_id: Optional[int] = None

def classify_subchannel_blocks(bundle_model, selected_sub_ids=None):
    if selected_sub_ids is None:
        sub_ids = sorted(bundle_model.selected_subchannels) if bundle_model.selected_subchannels else sorted(bundle_model.subchannels.keys())
    else:
        sub_ids = sorted(selected_sub_ids)

    sig_to_template: Dict[tuple, BlockTemplate] = {}
    instances: List[BlockInstance] = []
    global_counter = 1

    for sid in sub_ids:
        sub = bundle_model.subchannels.get(sid)
        if not sub or sub.sub_type not in ("interior", "guide_sub", "instrument_sub") or len(sub.rod_ids) != 3:
            continue

        rA_id, rB_id, rC_id = sub.rod_ids
        rA = bundle_model.rods[rA_id]
        rB = bundle_model.rods[rB_id]
        rC = bundle_model.rods[rC_id]

        cA = np.array([rA.x, rA.y]); cB = np.array([rB.x, rB.y]); cC = np.array([rC.x, rC.y])
        O = np.array(sub.fluid_center) if hasattr(sub, "fluid_center") and sub.fluid_center and sub.fluid_center != (0.0, 0.0) else (cA + cB + cC) / 3.0

        def gap_geom(c1, r1, c2, r2):
            v = c2 - c1; d = np.linalg.norm(v); u = v / d; gap = d - (r1 + r2)
            M = c1 + u * (r1 + gap / 2.0)
            return M, gap

        mAB, gapAB = gap_geom(cA, rA.diameter / 2.0, cB, rB.diameter / 2.0)
        mBC, gapBC = gap_geom(cB, rB.diameter / 2.0, cC, rC.diameter / 2.0)
        mCA, gapCA = gap_geom(cC, rC.diameter / 2.0, cA, rA.diameter / 2.0)

        blocks_data = [
            (0, rA, rB, gapAB, mAB, cA),
            (1, rB, rA, gapAB, mAB, cB),
            (2, rB, rC, gapBC, mBC, cB),
            (3, rC, rB, gapBC, mBC, cC),
            (4, rC, rA, gapCA, mCA, cC),
            (5, rA, rC, gapCA, mCA, cA),
        ]

        for blk_idx, r_self, r_other, gap_val, M_pt, c_self in blocks_data:
            r_self_val = round(r_self.diameter / 2.0, 3)
            r_other_val = round(r_other.diameter / 2.0, 3)
            gap_round = round(gap_val, 3)
            d_gap = round(gap_val / 2.0, 3)
            d_center = round(np.linalg.norm(O - c_self) - r_self.diameter / 2.0, 3)
            sig = (r_self_val, r_other_val, gap_round, d_gap, d_center)

            if sig not in sig_to_template:
                tid = len(sig_to_template) + 1
                name_prefix = f"{r_self.rod_type.upper()}"
                name_suffix = f"{r_other.rod_type.upper()}"
                desc = f"Шаблон {tid}: {name_prefix} (D={r_self.diameter:.1f}) -> {name_suffix} (D={r_other.diameter:.1f}), зазор={gap_round:.2f} мм"

                tmpl = BlockTemplate(
                    template_id=tid, name=desc, rod_type=r_self.rod_type,
                    diameter_mm=r_self.diameter, neighbor_diameter_mm=r_other.diameter,
                    gap_mm=gap_round, length_gap_mm=d_gap, length_center_mm=d_center,
                    signature=sig, blocks_count=0
                )
                sig_to_template[sig] = tmpl

            sig_to_template[sig].blocks_count += 1
            tid = sig_to_template[sig].template_id

            instances.append(BlockInstance(
                subchannel_id=sid, block_index=blk_idx, template_id=tid,
                rod_id=r_self.rod_id, neighbor_rod_id=r_other.rod_id,
                length_gap_mm=d_gap, length_center_mm=d_center, global_block_id=global_counter
            ))
            global_counter += 1

    templates = {tmpl.template_id: tmpl for tmpl in sig_to_template.values()}
    return templates, instances
