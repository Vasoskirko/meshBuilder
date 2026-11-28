"""Coverage and overlap in the actual fluid; circle approximation has two bounds."""
from dataclasses import dataclass
import math
from shapely.geometry import Polygon,Point,GeometryCollection
from shapely.ops import unary_union
from shapely.strtree import STRtree


@dataclass(frozen=True)
class GeometryReport:
    status: str
    tolerance: float
    gap_lower: float
    gap_upper: float
    overlap_lower: float
    overlap_upper: float
    collisions: tuple
    wall_collisions: tuple
    invalid_subchannels: tuple
    hydraulic_mismatches: tuple
    overlap_subchannels: tuple
    gap_outlines: tuple
    overlap_outlines: tuple
    recovery_notes: tuple
    label_points: tuple

    def __deepcopy__(self,memo):return self  # Immutable numeric/tuple report, no solver/model references.

    def text(self):
        titles={'ok':'Покрытие жидкости проверено','uncertain':'Малые остатки: требуется проверка','error':'Есть проблемы геометрии'}
        lines=[titles[self.status],f'Непокрытая жидкость: {self.gap_lower:.6g}…{self.gap_upper:.6g} мм²',
               f'Перекрытая жидкость: {self.overlap_lower:.6g}…{self.overlap_upper:.6g} мм²',f'Численный допуск площади: {self.tolerance:.3g} мм²']
        if self.collisions:lines.append('Пересечения стержней: '+', '.join(f'R{a}–R{b}' for a,b in self.collisions))
        if self.wall_collisions:lines.append('Пересечения с оболочкой: '+', '.join('R'+str(k) for k in self.wall_collisions))
        if self.invalid_subchannels:lines.append('Некорректные полигоны: '+', '.join('S'+str(k) for k in self.invalid_subchannels))
        if self.hydraulic_mismatches:lines.append('Площадь гидравлики не соответствует жидкостной области: '+', '.join('S'+str(k) for k in self.hydraulic_mismatches))
        if self.overlap_subchannels:lines.append('Подканалы с перекрытиями: '+', '.join('S'+str(k) for k in self.overlap_subchannels))
        lines.extend(self.recovery_notes)
        lines.append('Проверяется вся геометрия, не только выборка. Интервалы учитывают аппроксимацию окружностей. Это не оценка качества CFD-ячеек.')
        return '\n'.join(lines)


def outlines(geometry,limit=20):
    polygons=[]
    def visit(g):
        if len(polygons)>=limit:return
        if g.geom_type=='Polygon':polygons.append(tuple((float(x),float(y)) for x,y in g.exterior.coords))
        elif hasattr(g,'geoms'):
            for part in g.geoms:visit(part)
    visit(geometry);return tuple(polygons)


def diagnose(model,quad_segs=32,progress=None):
    progress=progress or (lambda value,text:None)
    progress(1,'Подготовка проверки геометрии')
    if type(quad_segs) is not int or not 8<=quad_segs<=256:raise ValueError('quad_segs: требуется целое 8…256')
    shell=Polygon(model.hex_vertices);tol=max(float(shell.area)*1e-10,1e-10)
    rods=list(model.rods.values());inner=[];outer=[]
    for index,rod in enumerate(rods):
        if index%128==0:progress(5+int(10*index/max(len(rods),1)),'Аппроксимация стержней')
        p=Point(rod.x,rod.y);radius=rod.diameter/2
        inner.append(p.buffer(radius,quad_segs=quad_segs))
        outer.append(p.buffer(radius/math.cos(math.pi/(4*quad_segs)),quad_segs=quad_segs))
    progress(15,'Объединение областей стержней')
    rod_inner=unary_union(inner);rod_outer=unary_union(outer)
    collisions=[]
    wall_collisions=[r.rod_id for r in rods if not shell.covers(Point(r.x,r.y)) or shell.boundary.distance(Point(r.x,r.y))<r.diameter/2-1e-8]
    tree=STRtree(inner)
    for i,r in enumerate(rods):
        if i%128==0:progress(17+int(3*i/max(len(rods),1)),'Проверка пересечений стержней')
        for j in tree.query(inner[i]):
            j=int(j)
            if j>i and math.hypot(r.x-rods[j].x,r.y-rods[j].y)<(r.diameter+rods[j].diameter)/2-1e-8:
                collisions.append((r.rod_id,rods[j].rod_id))
    ids=[];polys=[];invalid=[];mismatches=[];labels=[]
    for index,(sid,sub) in enumerate(model.subchannels.items()):
        if index%64==0:progress(20+int(45*index/max(len(model.subchannels),1)),'Проверка жидкостных областей')
        try:poly=Polygon(sub.polygon_points,getattr(sub,'polygon_holes',()))
        except (ValueError,TypeError):invalid.append(sid);continue
        if not poly.is_valid or poly.area<=tol:
            invalid.append(sid);continue
        ids.append(sid);polys.append(poly)
        nearby=[int(j) for j in tree.query(poly)]
        low=poly.intersection(shell).difference(unary_union([outer[j] for j in nearby]))
        high=poly.intersection(shell).difference(unary_union([inner[j] for j in nearby]))
        area=sub.a_fluid_mm2
        if not math.isfinite(area) or not low.area-tol<=area<=high.area+tol:mismatches.append(sid)
        point=Point(*sub.fluid_center)
        if not low.contains(point):point=low.representative_point() if not low.is_empty else high.representative_point()
        if not point.is_empty:labels.append((sid,(float(point.x),float(point.y))))
        if poly.difference(shell).area>tol:invalid.append(sid)
    progress(68,'Проверка покрытия оболочки')
    coverage=unary_union(polys)
    gaps=shell.difference(coverage)
    gap_min=gaps.difference(rod_outer);gap_max=gaps.difference(rod_inner)
    overlaps=[];overlap_ids=set();poly_tree=STRtree(polys)
    for i,poly in enumerate(polys):
        if i%128==0:progress(75+int(18*i/max(len(polys),1)),'Поиск перекрытий подканалов')
        for j in poly_tree.query(poly):
            j=int(j)
            if j<=i:continue
            overlap=poly.intersection(polys[j]).intersection(shell)
            if overlap.area<=tol:continue
            overlaps.append(overlap)
            if overlap.difference(rod_outer).area>tol:overlap_ids.update((ids[i],ids[j]))
    progress(95,'Сборка отчёта геометрии')
    overlap_raw=unary_union(overlaps)
    overlap_min=overlap_raw.difference(rod_outer);overlap_max=overlap_raw.difference(rod_inner)
    definite=bool(collisions or wall_collisions or invalid or mismatches or gap_min.area>tol or overlap_min.area>tol)
    uncertain=gap_max.area>tol or overlap_max.area>tol
    return GeometryReport('error' if definite else 'uncertain' if uncertain else 'ok',tol,
        float(gap_min.area),float(gap_max.area),float(overlap_min.area),float(overlap_max.area),
        tuple(sorted(collisions)),tuple(sorted(wall_collisions)),tuple(sorted(set(invalid))),tuple(sorted(mismatches)),tuple(sorted(overlap_ids)),
        outlines(gap_max),outlines(overlap_max),tuple(getattr(model,'recovery_notes',())),tuple(labels))
