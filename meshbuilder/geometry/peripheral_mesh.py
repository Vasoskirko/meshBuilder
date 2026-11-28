"""Experimental four-block wall-channel topology; not connected to CFD export."""
import math
import numpy as np


def build_peripheral_preview(model, sid, ni=17, nj=17, *, clustering=0.0, hermite=False, shell_thickness=0.0, shell_cells=4, shell_growth=1.0, gap_distributions=None):
    """Experimental patches in metres, for parallel rod rows and a single wall.

    Independent rod-layer/core controls and automatic neighbour binding are absent.
    It is a topology experiment, not a SubchannelMeshResult.
    """
    sub = model.subchannels[sid]
    if sub.sub_type != 'peripheral' or len(sub.rod_ids) != 2:
        raise ValueError('Прототип поддерживает только периферийный подканал с двумя стержнями.')
    if not all(isinstance(n, int) and not isinstance(n, bool) and 3 <= n <= 513 for n in (ni, nj)):
        raise ValueError('Для прототипа требуется 3…513 узлов по каждому направлению.')
    if isinstance(clustering, bool) or not isinstance(clustering, (int, float)) or not math.isfinite(clustering) or not 0 <= clustering <= 6:
        raise ValueError('Сгущение должно быть конечным числом от 0 до 6.')
    if not isinstance(hermite, bool):raise ValueError('Hermite должен быть логическим значением.')
    gap_profiles={}
    if gap_distributions is not None:
        if not isinstance(gap_distributions,dict) or set(gap_distributions)!=set(sub.rod_ids):
            raise ValueError('Нужны распределения зазора для обоих стержней подканала.')
        for rid,values in gap_distributions.items():
            values=np.asarray(values,dtype=float)
            if values.shape!=(nj,) or not np.all(np.isfinite(values)) or values[0]!=0 or values[-1]!=1 or not np.all(np.diff(values)>0):
                raise ValueError('Распределение зазора: nj возрастающих конечных значений от 0 до 1.')
            gap_profiles[rid]=values.copy()
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
    if isinstance(shell_thickness,bool) or not isinstance(shell_thickness,(int,float)) or not math.isfinite(shell_thickness) or shell_thickness<0:
        raise ValueError('Толщина слоя оболочки должна быть конечной и неотрицательной, в метрах.')
    if not isinstance(shell_cells,int) or isinstance(shell_cells,bool) or not 1<=shell_cells<=128:
        raise ValueError('Требуется 1…128 ячеек слоя оболочки.')
    if isinstance(shell_growth,bool) or not isinstance(shell_growth,(int,float)) or not math.isfinite(shell_growth) or not 1<=shell_growth<=3:
        raise ValueError('Рост слоя оболочки должен быть от 1 до 3.')
    if shell_thickness>=min(h-r for h,r in zip(heights,radius)):
        raise ValueError('Слой оболочки перекрывает зазор до стержня.')
    physical_feet=[c+h*normal for c,h in zip((a,b),heights)]
    feet=[f-shell_thickness*normal for f in physical_feet]
    gap=(a+radius[0]*tangent+b-radius[1]*tangent)/2
    middle=(feet[0]+feet[1])/2
    specs=[(a,radius[0],0,math.pi/4,gap,middle),
           (a,radius[0],math.pi/4,math.pi/2,middle,feet[0]),
           (b,radius[1],math.pi/2,3*math.pi/4,feet[1],middle),
           (b,radius[1],3*math.pi/4,math.pi,middle,gap)]
    blocks=[];u=np.linspace(0,1,ni);v=np.linspace(0,1,nj)
    if clustering:
        v = .5*(1+np.tanh(clustering*(2*v-1))/math.tanh(clustering))
        v[0],v[-1]=0.,1.
    for index,(centre,r,lo,hi,start,end) in enumerate(specs):
        theta=lo+(hi-lo)*u
        arc=centre+r*(np.cos(theta)[:,None]*tangent+np.sin(theta)[:,None]*normal)
        opposite=start+(end-start)*u[:,None]
        distribution=np.broadcast_to(v,(ni,nj)).copy()
        if gap_profiles and index in (0,3):
            rid=sub.rod_ids[0 if index==0 else 1]
            weight=(1-u if index==0 else u)[:,None]
            distribution+=weight*(gap_profiles[rid]-v)
            distribution[:,0],distribution[:,-1]=0.,1.
        if hermite:
            from mesh_subchannel import hermite_tfi_rays
            nodes=hermite_tfi_rays(arc,opposite,distribution)
        else:
            nodes=arc[:,None,:]*(1-distribution[:,:,None])+opposite[:,None,:]*distribution[:,:,None]
        x,y=nodes[:,:,0],nodes[:,:,1]
        signed=(x[1:,0]-x[:-1,0])*(y[:-1,1]-y[:-1,0])-(y[1:,0]-y[:-1,0])*(x[:-1,1]-x[:-1,0])
        if np.all(signed<0):x,y=x[::-1].copy(),y[::-1].copy()
        blocks.append((x,y))
    if shell_thickness:
        physical_middle=(physical_feet[0]+physical_feet[1])/2
        widths=shell_growth**np.arange(shell_cells,dtype=float)
        widths*=shell_thickness/widths.sum()
        offsets=np.concatenate(([0.],np.cumsum(widths)));offsets[-1]=shell_thickness
        for start,end in ((physical_feet[0],physical_middle),(physical_middle,physical_feet[1])):
            wall=start+(end-start)*u[:,None]
            nodes=wall[:,None,:]-offsets[None,:,None]*normal
            x,y=nodes[:,:,0],nodes[:,:,1]
            signed=(x[1,0]-x[0,0])*(y[0,1]-y[0,0])-(y[1,0]-y[0,0])*(x[0,1]-x[0,0])
            if signed<0:x,y=x[::-1].copy(),y[::-1].copy()
            blocks.append((x,y))
    from mesh_subchannel import _check_quad_jacobians
    _check_quad_jacobians(blocks)
    return blocks


def peripheral_wall_metrics(model, sid, blocks):
    """Measured first-edge lengths, normal projections and angles, in SI units.

    Endpoint rays remain shared straight edges. Orthogonality is therefore
    measured, never assumed, even when Hermite interpolation is enabled.
    """
    sub=model.subchannels[sid]
    if len(blocks) not in (4,6,8,10):raise ValueError('Неверное число блоков прототипа.')
    has_rod_layer=len(blocks) in (8,10)
    has_shell_layer=len(blocks) in (6,10)
    rod_start=len(blocks)-4 if has_rod_layer else 0
    observations={'rods':[], 'shell':[]}
    wa=np.asarray(model.hex_vertices[sub.wall_side])*1e-3
    wb=np.asarray(model.hex_vertices[(sub.wall_side+1)%6])*1e-3
    shell_normal=np.array([-(wb-wa)[1],(wb-wa)[0]])
    shell_normal/=np.linalg.norm(shell_normal)
    rod=model.rods[sub.rod_ids[0]]
    if np.dot(shell_normal,np.array([rod.x,rod.y])*1e-3-wa)<0:shell_normal=-shell_normal
    for index,(x,y) in enumerate(blocks):
        nodes=np.stack((x,y),axis=-1)
        edges=[]
        if (not has_rod_layer and index<4) or (has_rod_layer and index>=rod_start):
            rod_index=index-rod_start if has_rod_layer else index
            rod=model.rods[sub.rod_ids[0 if rod_index<2 else 1]]
            radial=nodes[:,0]-np.array([rod.x,rod.y])*1e-3
            radial/=np.linalg.norm(radial,axis=1)[:,None]
            edges=[('rods',nodes[:,1]-nodes[:,0],radial)]
        if not has_shell_layer and index in (1,2):
            edges.append(('shell',nodes[:,-2]-nodes[:,-1],np.broadcast_to(shell_normal,nodes[:,0].shape)))
        if has_shell_layer and index in (4,5):
            edges.append(('shell',nodes[:,1]-nodes[:,0],np.broadcast_to(shell_normal,nodes[:,0].shape)))
        for kind,edge,normal in edges:
            length=np.linalg.norm(edge,axis=1)
            projection=np.sum(edge*normal,axis=1)
            angle=np.degrees(np.arccos(np.clip(projection/length,-1,1)))
            observations[kind].extend(zip(length,projection,angle))
    result={}
    for kind,values in observations.items():
        values=np.asarray(values)
        result[kind]={name:(float(values[:,i].min()),float(values[:,i].max()))
                      for i,name in enumerate(('edge_m','normal_m','angle_deg'))}
        result[kind]['median_angle_deg']=float(np.median(values[:,2]))
    return result


def build_peripheral_layered_preview(model, sid, ni=17, nj=17, *, rod_thickness,
                                     rod_cells=4, rod_growth=1.0, **core_options):
    """Add independent circular rod layers around the four core patches.

    Thickness is in metres. Core gap profiles refer to the layer front, not
    the physical rod. Caller must split a neighbour's full profile explicitly.
    The input model is never modified, including on a failed build.
    """
    from copy import deepcopy
    if isinstance(rod_thickness,bool) or not isinstance(rod_thickness,(int,float)) or not math.isfinite(rod_thickness) or rod_thickness<=0:
        raise ValueError('Толщина слоя стержня должна быть конечной и положительной, в метрах.')
    if not isinstance(rod_cells,int) or isinstance(rod_cells,bool) or not 1<=rod_cells<=128:
        raise ValueError('Требуется 1…128 ячеек слоя стержня.')
    if isinstance(rod_growth,bool) or not isinstance(rod_growth,(int,float)) or not math.isfinite(rod_growth) or not 1<=rod_growth<=3:
        raise ValueError('Рост слоя стержня должен быть от 1 до 3.')
    sub=model.subchannels[sid]
    if sub.sub_type!='peripheral' or len(sub.rod_ids)!=2:
        raise ValueError('Слой поддерживает периферийный подканал с двумя стержнями.')
    expanded=deepcopy(model)
    for rid in sub.rod_ids:expanded.rods[rid].diameter+=2*rod_thickness*1e3
    blocks=build_peripheral_preview(expanded,sid,ni,nj,**core_options)
    widths=rod_growth**np.arange(rod_cells,dtype=float)
    widths*=rod_thickness/widths.sum()
    offsets=np.concatenate(([0.],np.cumsum(widths)));offsets[-1]=rod_thickness
    for index,(x,y) in enumerate(blocks[:4]):
        rod=model.rods[sub.rod_ids[0 if index<2 else 1]]
        centre=np.array([rod.x,rod.y])*1e-3
        front=np.stack((x[:,0],y[:,0]),axis=-1)
        radial=front-centre
        radial/=np.linalg.norm(radial,axis=1)[:,None]
        nodes=centre+radial[:,None,:]*(rod.diameter*.5e-3+offsets)[None,:,None]
        # Use the exact core boundary to avoid independent roundoff at the seam.
        nodes[:,-1]=front
        blocks.append((nodes[:,:,0],nodes[:,:,1]))
    from mesh_subchannel import _check_quad_jacobians
    _check_quad_jacobians(blocks)
    return blocks
