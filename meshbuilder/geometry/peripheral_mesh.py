"""Experimental four-block wall-channel topology; not connected to CFD export."""
import math
import numpy as np


def build_peripheral_preview(model, sid, ni=17, nj=17):
    """Uniform ruled patches in metres, for parallel rod rows and a single wall.

    This deliberately excludes layer/core controls and neighbour conformity.
    It is a topology experiment, not a SubchannelMeshResult.
    """
    sub = model.subchannels[sid]
    if sub.sub_type != 'peripheral' or len(sub.rod_ids) != 2:
        raise ValueError('Прототип поддерживает только периферийный подканал с двумя стержнями.')
    if not all(isinstance(n, int) and not isinstance(n, bool) and 3 <= n <= 513 for n in (ni, nj)):
        raise ValueError('Для прототипа требуется 3…513 узлов по каждому направлению.')
    rods = [model.rods[r] for r in sub.rod_ids]
    a, b = [np.array([r.x, r.y], dtype=float)*1e-3 for r in rods]
    radius = [r.diameter*.5e-3 for r in rods]
    wall_a = np.asarray(model.hex_vertices[sub.wall_side], dtype=float)*1e-3
    wall_b = np.asarray(model.hex_vertices[(sub.wall_side+1)%6], dtype=float)*1e-3
    delta=b-a; distance=np.linalg.norm(delta)
    if distance <= sum(radius):raise ValueError('Стержни пересекаются или касаются.')
    tangent=delta/distance
    normal=np.array([-tangent[1],tangent[0]])
    if np.dot((wall_a+wall_b)/2-a,normal)<0:normal=-normal
    heights=[np.dot(wall_a-c,normal) for c in (a,b)]
    wall_tangent=(wall_b-wall_a)/np.linalg.norm(wall_b-wall_a)
    if abs(np.dot(tangent,wall_tangent))<1-1e-10 or abs(heights[0]-heights[1])>1e-10:
        raise ValueError('Ряд стержней должен быть параллелен прямой стенке.')
    if min(h-r for h,r in zip(heights,radius))<=0:raise ValueError('Нет зазора со стенкой.')
    feet=[c+h*normal for c,h in zip((a,b),heights)]
    gap=(a+radius[0]*tangent+b-radius[1]*tangent)/2
    middle=(feet[0]+feet[1])/2
    specs=[(a,radius[0],0,math.pi/4,gap,middle),
           (a,radius[0],math.pi/4,math.pi/2,middle,feet[0]),
           (b,radius[1],math.pi/2,3*math.pi/4,feet[1],middle),
           (b,radius[1],3*math.pi/4,math.pi,middle,gap)]
    blocks=[];u=np.linspace(0,1,ni);v=np.linspace(0,1,nj)
    for centre,r,lo,hi,start,end in specs:
        theta=lo+(hi-lo)*u
        arc=centre+r*(np.cos(theta)[:,None]*tangent+np.sin(theta)[:,None]*normal)
        opposite=start+(end-start)*u[:,None]
        nodes=arc[:,None,:]*(1-v[None,:,None])+opposite[:,None,:]*v[None,:,None]
        x,y=nodes[:,:,0],nodes[:,:,1]
        signed=(x[1:,0]-x[:-1,0])*(y[:-1,1]-y[:-1,0])-(y[1:,0]-y[:-1,0])*(x[:-1,1]-x[:-1,0])
        if np.all(signed<0):x,y=x[::-1].copy(),y[::-1].copy()
        blocks.append((x,y))
    from mesh_subchannel import _check_quad_jacobians
    _check_quad_jacobians(blocks)
    return blocks
