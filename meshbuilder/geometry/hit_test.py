"""Select the region under the pointer, not a nearby marker's search radius."""
import math


def inside_polygon(points,x,y,tolerance):
    inside=False
    for i,(ax,ay) in enumerate(points):
        bx,by=points[(i+1)%len(points)];dx,dy=bx-ax,by-ay
        cross=dx*(y-ay)-dy*(x-ax)
        if abs(cross)<=tolerance*max(math.hypot(dx,dy),1e-15) and min(ax,bx)-tolerance<=x<=max(ax,bx)+tolerance and min(ay,by)-tolerance<=y<=max(ay,by)+tolerance:
            return False  # Shared edge: require a click inside a region.
        if (ay>y)!=(by>y) and x<ax+(y-ay)*dx/dy:inside=not inside
    return inside


def hit_subchannels(model,x,y):
    if not math.isfinite(x) or not math.isfinite(y):return ()
    tolerance=max(model.s_flat,model.pitch)*1e-10
    if any(x*n[0]+y*n[1]>model.s_flat/2+tolerance for n in model.normals):return ()
    if any(math.hypot(x-r.x,y-r.y)<=r.diameter/2 for r in model.rods.values()):return ()
    return tuple(sid for sid,sub in model.subchannels.items() if inside_polygon(sub.polygon_points,x,y,tolerance))
