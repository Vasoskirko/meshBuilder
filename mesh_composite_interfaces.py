"""Explicit node-conformal one-to-many block faces, without exporter assumptions."""
from dataclasses import dataclass
import math
import numpy as np
from mesh_interface_diagnostics import face_nodes,coincident_polylines


@dataclass(frozen=True)
class InterfacePiece:
    block_b: int
    face_b: str
    start_a: int
    stop_a: int  # inclusive; adjacent pieces share exactly one endpoint
    reversed: bool = False


@dataclass(frozen=True)
class CompositeInterface:
    block_a: int
    face_a: str
    pieces: tuple


def _nodes(blocks,block,face):
    if isinstance(block,bool) or not isinstance(block,int) or not 0<=block<len(blocks):
        raise ValueError('Некорректный номер блока составного стыка.')
    nodes=face_nodes(blocks[block],face)
    if len(nodes)<2 or not np.all(np.isfinite(nodes)) or np.any(np.linalg.norm(np.diff(nodes,axis=0),axis=1)==0):
        raise ValueError('Грань составного стыка содержит нечисловые или повторяющиеся узлы.')
    return nodes


def _tolerance(tol):
    if isinstance(tol,bool) or not isinstance(tol,(int,float)) or not math.isfinite(tol) or tol<0:
        raise ValueError('Допуск должен быть конечным неотрицательным числом.')


def partition_composite_interfaces(blocks,interfaces,tol,*,pairwise=()):
    """Validate declarations and classify coordinate/count mismatches.

    Declaration errors (holes, overlapping coverage, reused faces) raise ValueError.
    Only verified node-conformal declarations enter the returned conform tuple.
    This representation is deliberately separate from legacy BlockInterface.
    """
    _tolerance(tol)
    conform=[];problems=[]
    owned={ref for it in pairwise for ref in ((it.block_a,it.face_a),(it.block_b,it.face_b))}
    for interface in interfaces:
        a=_nodes(blocks,interface.block_a,interface.face_a)
        if not isinstance(interface.pieces,tuple) or len(interface.pieces)<2:
            raise ValueError('Составной стык требует как минимум две части.')
        refs={(interface.block_a,interface.face_a)}
        cursor=0;local_problems=[]
        for piece in sorted(interface.pieces,key=lambda p:p.start_a):
            if any(isinstance(k,bool) or not isinstance(k,int) for k in (piece.start_a,piece.stop_a)) or not isinstance(piece.reversed,bool):
                raise ValueError('Неверные индексы или ориентация части стыка.')
            if piece.start_a!=cursor or not piece.start_a<piece.stop_a<len(a):
                raise ValueError('Части должны покрывать грань без дыр и перекрытия рёбер.')
            b=_nodes(blocks,piece.block_b,piece.face_b)
            ref=(piece.block_b,piece.face_b)
            if piece.block_b==interface.block_a or ref in refs:
                raise ValueError('Повторное использование грани или самосопряжение блока.')
            refs.add(ref)
            if piece.reversed:b=b[::-1]
            section=a[piece.start_a:piece.stop_a+1]
            if section.shape!=b.shape or not np.allclose(section,b,rtol=0,atol=tol):
                kind='nonconformal' if coincident_polylines(section,b,tol) else 'geometry_mismatch'
                local_problems.append(dict(block_a=interface.block_a,face_a=interface.face_a,
                    block_b=piece.block_b,face_b=piece.face_b,start_a=piece.start_a,stop_a=piece.stop_a,
                    reversed=piece.reversed,kind=kind,nodes_a=len(section),nodes_b=len(b)))
            cursor=piece.stop_a
        if cursor!=len(a)-1:raise ValueError('Составной стык не покрывает конец грани.')
        if refs & owned:raise ValueError('Грань уже принадлежит другому составному стыку.')
        owned.update(refs)
        if local_problems:problems.extend(local_problems)
        else:conform.append(interface)
    return tuple(conform),problems


def match_composite_interface(blocks,block_a,face_a,candidates,tol):
    """Bind explicit candidate faces to master node ranges, including reversal.

    Every candidate is required to participate; a misplaced face is never skipped.
    Matching endpoints alone does not establish conformity: all nodes are audited.
    """
    _tolerance(tol);a=_nodes(blocks,block_a,face_a);pieces=[]
    for block_b,face_b in candidates:
        b=_nodes(blocks,block_b,face_b);indices=[]
        for endpoint in b[[0,-1]]:
            matches=np.flatnonzero(np.max(np.abs(a-endpoint),axis=1)<=tol)
            if len(matches)!=1:raise ValueError('Конец части не совпадает с единственным узлом общей грани.')
            indices.append(int(matches[0]))
        lo,hi=sorted(indices)
        pieces.append(InterfacePiece(block_b,face_b,lo,hi,indices[0]>indices[1]))
    result=CompositeInterface(block_a,face_a,tuple(sorted(pieces,key=lambda p:p.start_a)))
    conform,problems=partition_composite_interfaces(blocks,[result],tol)
    if problems:raise ValueError('Несовместимый составной стык: '+str(problems))
    return conform[0]
