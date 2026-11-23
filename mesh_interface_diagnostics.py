"""Conformity and polyline coincidence; never treats a gap as a usable interface."""
import numpy as np


def face_nodes(block, face):
    x,y=block
    if face=='i_min':return np.column_stack((x[0],y[0]))
    if face=='i_max':return np.column_stack((x[-1],y[-1]))
    if face=='j_min':return np.column_stack((x[:,0],y[:,0]))
    if face=='j_max':return np.column_stack((x[:,-1],y[:,-1]))
    raise ValueError('Unknown face: '+face)


def coincident_polylines(a,b,tol):
    def parameter(v):
        d=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(v,axis=0),axis=1))]
        if d[-1]<=0 or np.any(np.diff(d)<=0):return None
        return d/d[-1]
    ta,tb=parameter(a),parameter(b)
    if ta is None or tb is None:return False
    t=np.union1d(ta,tb)
    aa=np.column_stack([np.interp(t,ta,a[:,d]) for d in (0,1)])
    bb=np.column_stack([np.interp(t,tb,b[:,d]) for d in (0,1)])
    return bool(np.max(np.abs(aa-bb))<=tol)


def partition_interfaces(blocks,interfaces,tol,layer_only=False):
    conform=[];problems=[]
    for it in interfaces:
        if layer_only and it.face_a.startswith('j_'):
            conform.append(it);continue
        a=face_nodes(blocks[it.block_a],it.face_a)
        b=face_nodes(blocks[it.block_b],it.face_b)
        if it.reversed:b=b[::-1]
        if a.shape==b.shape and np.allclose(a,b,rtol=0,atol=tol):
            conform.append(it);continue
        kind='nonconformal' if coincident_polylines(a,b,tol) else 'geometry_mismatch'
        problems.append(dict(block_a=it.block_a,face_a=it.face_a,block_b=it.block_b,
                             face_b=it.face_b,reversed=bool(it.reversed),kind=kind,
                             nodes_a=len(a),nodes_b=len(b)))
    return tuple(conform),problems


def require_star_conformity(result):
    if getattr(result,'diagnostics',{}).get('interface_problems'):
        raise ValueError('STAR-CCM+: обнаружены несовместимые стыки блоков. Текущий экспорт не создаёт '
                         'неконформные интерфейсы внутри подканала. Согласуйте настройки блоков; '
                         'сетка доступна для просмотра и диагностического Plot3D, но не для этого CFD-экспорта.')


def completed_interfaces(blocks,intended,tol):
    """Recover inter-subchannel contacts that did not exist on partial layers."""
    from mesh_subchannel import _candidate_face_pairs
    from mesh_core import BlockInterface
    faces=[(i,face,face_nodes(block,face)) for i,block in enumerate(blocks)
           for face in ('i_min','i_max','j_min','j_max')]
    intended=list(intended)
    seen={frozenset(((it.block_a,it.face_a),(it.block_b,it.face_b))) for it in intended}
    for i,j in _candidate_face_pairs(faces,tol):
        ai,af,a=faces[i];bi,bf,b=faces[j]
        key=frozenset(((ai,af),(bi,bf)))
        if ai==bi or key in seen:continue
        direct=np.max(np.abs(a[[0,-1]]-b[[0,-1]]))
        reverse=np.max(np.abs(a[[0,-1]]-b[[-1,0]]))
        if min(direct,reverse)>tol:continue
        intended.append(BlockInterface(ai,af,bi,bf,bool(reverse<direct)));seen.add(key)
    conform,problems=partition_interfaces(blocks,intended,tol)
    return conform,problems,tuple(intended)
