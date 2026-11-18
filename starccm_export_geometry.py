"""Geometry fingerprints and source-subchannel masks for STAR-CCM+ export."""
from collections import defaultdict
import numpy as np


def surface_signature(lines, height):
    area = 0.0
    moment = np.zeros(2)
    for line in lines:
        line = np.asarray(line)
        lengths = np.linalg.norm(np.diff(line, axis=0), axis=1)
        weights = lengths * height
        area += weights.sum()
        moment += (weights[:, None] * (line[1:] + line[:-1]) / 2).sum(axis=0)
    if area <= 0:
        raise ValueError("Пустая или вырожденная поверхность экспорта")
    return float(area * 1e6), *(moment / area)


def export_geometry(result, model):
    """Use the actual block order, not the mutable GUI selection order."""
    blocks = result.blocks
    instances = getattr(result, 'instances_map', [])
    signatures = []
    domains = []
    rod_lines = defaultdict(list)
    if model is None or len(instances) != len(blocks):
        return signatures, domains
    ids = list(dict.fromkeys(row[0] for row in instances))
    for number, sid in enumerate(ids, 1):
        sub = model.subchannels[sid]
        triangle = np.array([(model.rods[r].x, model.rods[r].y) for r in sub.rod_ids]) * 1e-3
        if triangle.shape != (3, 2):
            raise ValueError("Экспорт поддерживает треугольные подканалы")
        a, b = triangle[1] - triangle[0], triangle[2] - triangle[0]
        cross = a[0] * b[1] - a[1] * b[0]
        if cross < 0:
            triangle = triangle[[0, 2, 1]]
        domains.append(dict(number=number, source_id=sid, triangle=triangle,
                            center=np.asarray(sub.fluid_center) * 1e-3))
        per_rod = defaultdict(list)
        gaps = defaultdict(list)
        for idx, row in enumerate(instances):
            if row[0] != sid:
                continue
            x, y = blocks[idx]
            starts = result.wall_starts[idx]
            arc = np.column_stack((x[:, 0 if starts else -1], y[:, 0 if starts else -1]))
            # Identify the physical rod using all wall nodes, independent of CW/CCW ordering.
            errors = []
            for rid in sub.rod_ids:
                r = model.rods[rid]
                error = np.max(np.abs(np.linalg.norm(arc - np.array([r.x, r.y])*1e-3, axis=1) - r.diameter*0.5e-3))
                errors.append((error, rid))
            error, rid = min(errors)
            if error > result.params.pitch * 1e-6:
                raise ValueError("Не удалось сопоставить стенку блока со стержнем")
            per_rod[rid].append(arc)
            rod_lines[rid].append(arc)
            signatures.append((1, rid, *surface_signature([arc], result.params.z_len)))
            gap = np.column_stack((x[-1], y[-1]))
            midpoint = result.geom_data[idx]['opposite'][-1]
            gaps[tuple(np.round(midpoint, 12))].append(gap)
            signatures.append((0, -1, *surface_signature([gap], result.params.z_len)))
        for rid, lines in per_rod.items():
            signatures.append((1, rid, *surface_signature(lines, result.params.z_len)))
        for lines in gaps.values():
            signatures.append((0, -1, *surface_signature(lines, result.params.z_len)))
    # Fuse may join contiguous arcs of a rod across several source subchannels.
    for rid, lines in rod_lines.items():
        remaining = list(lines)
        while remaining:
            component = [remaining.pop()]
            changed = True
            while changed:
                changed = False
                for line in remaining[:]:
                    if any(np.min(np.linalg.norm(line[[0, -1], None] - other[None, [0, -1]], axis=2)) < result.params.pitch*1e-8 for other in component):
                        component.append(line)
                        remaining = [candidate for candidate in remaining if candidate is not line]
                        changed = True
            signatures.append((1, rid, *surface_signature(component, result.params.z_len)))
    return signatures, domains


def plane_positions(count, keys):
    positions = list(np.linspace(0., 1., count)) if count > 1 else []
    if keys:
        positions.extend([0., .5, 1.])
    return sorted(set(round(float(x), 12) for x in positions))


def domain_expression(triangle):
    terms = []
    for a, b in zip(triangle, np.roll(triangle, -1, axis=0)):
        dx, dy = b-a
        terms.append(f'(({dx:.16e})*($$Centroid[1]-({a[1]:.16e}))-({dy:.16e})*($$Centroid[0]-({a[0]:.16e})))>=-1e-16')
    return '(' + ' && '.join(terms) + ') ? 1.0 : 0.0'
