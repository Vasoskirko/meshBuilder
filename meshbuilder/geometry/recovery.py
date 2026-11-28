"""Repartition uncovered space after explicit rod deletion, without fake CFD triangles."""
import math
from shapely.geometry import Polygon,Point,box
from shapely.ops import unary_union
from shapely.strtree import STRtree
from .types import Subchannel
from .circle_polygon import circle_area,wetted_arc,fluid_line_length

MAX_INTEGRATION_WORK=2000000


def polygon(sub):return Polygon(sub.polygon_points,getattr(sub,'polygon_holes',()))


def parts(shape):
    if shape.geom_type=='Polygon':return [shape]
    return [p for child in getattr(shape,'geoms',()) for p in parts(child)]


def recover_deleted_regions(model):
    model.recovery_notes=()
    if not model.user_deleted_coords:return
    length_tol=max(model.s_flat,1.)*1e-12
    rods=list(model.rods.values());shell=Polygon(model.hex_vertices);tol=max(shell.area*1e-10,1e-10)
    boxes=[box(r.x-r.diameter/2,r.y-r.diameter/2,r.x+r.diameter/2,r.y+r.diameter/2) for r in rods]
    tree=STRtree(boxes)
    for i,r in enumerate(rods):
        if shell.boundary.distance(Point(r.x,r.y))<r.diameter/2-1e-10:
            model.recovery_notes=('Восстановление отложено: стержень пересекает оболочку.',);return
        for j in tree.query(boxes[i]):
            j=int(j)
            if j>i and math.hypot(r.x-rods[j].x,r.y-rods[j].y)<(r.diameter+rods[j].diameter)/2-1e-10:
                model.recovery_notes=('Восстановление отложено: устраните пересечения стержней.',);return
    ids=[];polys=[];drop=set();work=0
    next_id=max(model.subchannels,default=-1)+1
    for sid,sub in model.subchannels.items():
        poly=polygon(sub)
        if not poly.is_valid or poly.area<=tol or poly.difference(shell).area>tol:drop.add(sid);continue
        local=[rods[int(j)] for j in tree.query(poly)]
        work+=len(local)*(len(poly.exterior.coords)+sum(len(h.coords) for h in poly.interiors))
        if work>MAX_INTEGRATION_WORK:
            model.recovery_notes=('Восстановление отложено: превышен лимит сложности геометрии.',);return
        actual=poly.area-sum(circle_area(poly,r.x,r.y,r.diameter/2) for r in local)
        if abs(actual-sub.a_fluid_mm2)>tol:drop.add(sid)
        ids.append(sid);polys.append(poly)
    poly_tree=STRtree(polys)
    for i,p in enumerate(polys):
        for j in poly_tree.query(p):
            j=int(j)
            if j>i and p.intersection(polys[j]).area>tol:drop.update((ids[i],ids[j]))
    kept=[p for sid,p in zip(ids,polys) if sid not in drop]
    missing=parts(shell.difference(unary_union(kept)))
    missing.sort(key=lambda p:(p.bounds, p.area))
    added=[]
    for poly in missing:
        if poly.area<=tol:continue
        local=[rods[int(j)] for j in tree.query(poly)]
        work+=len(local)*(len(poly.exterior.coords)+sum(len(h.coords) for h in poly.interiors))
        if work>MAX_INTEGRATION_WORK:
            model.recovery_notes=('Восстановление отложено: превышен лимит сложности геометрии.',);return
        area=poly.area-sum(circle_area(poly,r.x,r.y,r.diameter/2) for r in local)
        if area<=tol:continue
        vertex_rods=[r.rod_id for r in local if circle_area(poly,r.x,r.y,r.diameter/2)>tol or wetted_arc(poly,r.x,r.y,r.diameter/2)>length_tol]
        # Only a display/reference point; this is not a six-block meshing centre.
        outer=unary_union([Point(r.x,r.y).buffer(r.diameter/2/math.cos(math.pi/128),quad_segs=32) for r in local])
        safe=poly.difference(outer)
        if safe.is_empty:
            model.recovery_notes=('Восстановление отложено: жидкостная область слишком узкая для надёжного представления.',);return
        point=safe.representative_point();centre=poly.centroid
        sub=Subchannel(next_id,'recovered',sorted(vertex_rods),centroid=(centre.x,centre.y),fluid_center=(point.x,point.y),
            polygon_points=list(poly.exterior.coords)[:-1],polygon_holes=[list(h.coords)[:-1] for h in poly.interiors])
        model.calc_hydraulics(sub);added.append(sub);next_id+=1
    # Commit only after all candidates have been checked.
    for sid in drop:model.subchannels.pop(sid,None)
    for sub in added:model.subchannels[sub.sub_id]=sub
    all_ids=list(model.subchannels);all_polys=[polygon(model.subchannels[k]) for k in all_ids];all_tree=STRtree(all_polys)
    neighbors={k:set() for k in all_ids}
    for i,p in enumerate(all_polys):
        for j in all_tree.query(p):
            j=int(j)
            if j<=i:continue
            shared=p.boundary.intersection(all_polys[j].boundary)
            if shared.length<=1e-9:continue
            local=[rods[int(k)] for k in tree.query(shared)]
            if fluid_line_length(shared,local)>1e-8:
                a,b=all_ids[i],all_ids[j];neighbors[a].add(b);neighbors[b].add(a)
    for sid,sub in model.subchannels.items():sub.neighbor_sub_ids=sorted(neighbors[sid])
    model.recovery_notes=(f'После удаления стержней восстановлено областей: {len(added)}. Их CFD-сетка пока не поддерживается.',) if added else ()


def recovered_hydraulics(model,sub):
    poly=polygon(sub);shell=Polygon(model.hex_vertices)
    local=[model.rods[r] for r in sub.rod_ids]
    area=poly.area-sum(circle_area(poly,r.x,r.y,r.diameter/2) for r in local)
    wet=poly.intersection(shell.boundary).length+sum(wetted_arc(poly,r.x,r.y,r.diameter/2) for r in local)
    return float(poly.area),float(max(area,0)),float(wet),float(4*area/wet if wet>0 else 0.)
