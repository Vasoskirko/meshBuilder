"""Analytic circle/polygon integrals; no circle tessellation in hydraulics."""
import math
from shapely.geometry import Point


def cuts(a,b,cx,cy,radius):
    px,py=a[0]-cx,a[1]-cy;dx,dy=b[0]-a[0],b[1]-a[1]
    aa=dx*dx+dy*dy
    if aa==0:return []
    bb=2*(px*dx+py*dy);cc=px*px+py*py-radius*radius
    disc=bb*bb-4*aa*cc
    epsilon=32*math.ulp(1.)*(bb*bb+abs(4*aa*cc)+1)
    if disc < -epsilon:return []
    root=math.sqrt(max(0.,disc))
    return [t for t in ((-bb-root)/(2*aa),(-bb+root)/(2*aa)) if 0<t<1]


def ring_area(ring,cx,cy,radius):
    total=0.
    for a,b in zip(ring[:-1],ring[1:]):
        times=sorted(set([0.,1.]+cuts(a,b,cx,cy,radius)))
        for lo,hi in zip(times[:-1],times[1:]):
            p=(a[0]+lo*(b[0]-a[0])-cx,a[1]+lo*(b[1]-a[1])-cy)
            q=(a[0]+hi*(b[0]-a[0])-cx,a[1]+hi*(b[1]-a[1])-cy)
            cross=p[0]*q[1]-p[1]*q[0];dot=p[0]*q[0]+p[1]*q[1]
            if ((p[0]+q[0])/2)**2+((p[1]+q[1])/2)**2<radius*radius:
                total+=cross/2
            else:total+=radius*radius*math.atan2(cross,dot)/2
    return abs(total)


def circle_area(poly,cx,cy,radius):
    value=ring_area(list(poly.exterior.coords),cx,cy,radius)-sum(ring_area(list(h.coords),cx,cy,radius) for h in poly.interiors)
    return max(0.,min(math.pi*radius*radius,value))


def wetted_arc(poly,cx,cy,radius):
    angles=[0.,2*math.pi]
    for ring in [poly.exterior,*poly.interiors]:
        points=list(ring.coords)
        for a,b in zip(points[:-1],points[1:]):
            for t in cuts(a,b,cx,cy,radius):
                x=a[0]+t*(b[0]-a[0])-cx;y=a[1]+t*(b[1]-a[1])-cy
                angles.append(math.atan2(y,x)%(2*math.pi))
            # Endpoints on the circle also delimit arcs.
            for x,y in (a,b):
                if abs(math.hypot(x-cx,y-cy)-radius)<=max(radius,1.)*1e-12:angles.append(math.atan2(y-cy,x-cx)%(2*math.pi))
    angles=sorted(set(angles));length=0.
    for a,b in zip(angles[:-1],angles[1:]):
        mid=(a+b)/2
        if poly.covers(Point(cx+radius*math.cos(mid),cy+radius*math.sin(mid))):length+=radius*(b-a)
    return length


def fluid_line_length(geometry,rods):
    if geometry.is_empty:return 0.
    if geometry.geom_type!='LineString':return sum(fluid_line_length(g,rods) for g in getattr(geometry,'geoms',()))
    points=list(geometry.coords);result=0.
    for a,b in zip(points[:-1],points[1:]):
        times=[0.,1.]
        for rod in rods:times+=cuts(a,b,rod.x,rod.y,rod.diameter/2)
        times=sorted(set(times))
        for lo,hi in zip(times[:-1],times[1:]):
            t=(lo+hi)/2;x=a[0]+t*(b[0]-a[0]);y=a[1]+t*(b[1]-a[1])
            if all(math.hypot(x-r.x,y-r.y)>r.diameter/2 for r in rods):result+=(hi-lo)*math.hypot(b[0]-a[0],b[1]-a[1])
    return result
