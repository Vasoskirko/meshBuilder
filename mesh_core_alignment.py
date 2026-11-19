"""Optional core aspect alignment. Remove this module and its GUI hook to retire it.

Keep straight rays and topology. Select a common count minimizing sampled
log-aspect error in the outer half of the core, under hard growth/size limits.
This is a bounded count search, not a general quadrilateral optimizer.
"""
import numpy as np
from mesh_core_fill import CoreDistribution, controlled_distribution


def node_tangents(points):
    """Local tangential edge vector at each ray (one-sided at endpoints)."""
    edges = np.diff(np.asarray(points, dtype=float), axis=0)
    return np.concatenate((edges[:1], (edges[:-1] + edges[1:]) / 2, edges[-1:]))


def aligned_distribution(lengths, last_width, front_tangents, end_tangents,
                         growth, max_size, max_cells, transition_ratio=1.0,
                         progress=None):
    # Reuse validation and feasibility of the strict distribution, but choose
    # count by aspect rather than simply taking the smallest feasible count.
    baseline = controlled_distribution(lengths, last_width, growth, max_size,
                                       max_cells, transition_ratio)
    lengths = np.asarray(lengths, dtype=float)
    first = np.broadcast_to(np.asarray(last_width, dtype=float), lengths.shape) * transition_ratio
    front = np.asarray(front_tangents, dtype=float)
    end = np.asarray(end_tangents, dtype=float)
    if front.shape != (len(lengths), 2) or end.shape != front.shape or not np.isfinite([front,end]).all():
        raise ValueError('Некорректные поперечные размеры ядра')
    if np.any(np.linalg.norm(front, axis=1) <= 0) or np.any(np.linalg.norm(end, axis=1) <= 0):
        raise ValueError('Нулевой поперечный шаг ядра')
    nmin = baseline.count
    nmax = min(int(max_cells), int(np.floor(np.min(lengths / first) + 1e-10)))
    if growth == 1:
        return baseline, dict(count=nmin, sampled_candidates=1, score=None)
    logq = np.log(growth)

    def prefix(n, plateau):
        # Sum min(first*q**j, plateau), j=0..n-1, without allocating ray*count.
        k = np.minimum(n, np.maximum(0, np.ceil(np.log(plateau / first) / logq)))
        last = first * np.exp(np.maximum(k-1, 0) * logq)
        geometric = last * (-np.expm1(-k * logq)) / (-np.expm1(-logq))
        return geometric + (n-k) * plateau

    def fit(n):
        low = first.copy(); high = np.full_like(first, max_size)
        for _ in range(52):
            mid = (low+high)/2
            below = prefix(n, mid) < lengths
            low = np.where(below, mid, low); high = np.where(below, high, mid)
        return (low+high)/2

    def score(n, plateau):
        # Uniform samples of cells in the outer half; do not penalize the
        # intentionally stretched wall-to-core transition as if it were bulk.
        js = np.unique(np.linspace(n//2, n-1, min(24, n-n//2)).astype(int))
        errors = []
        for j in js:
            width = np.exp(np.minimum(np.log(first) + j*logq, np.log(plateau)))
            fraction = np.clip((prefix(j, plateau)+width/2)/lengths, 0, 1)
            tangent = (1-fraction[:,None])*front + fraction[:,None]*end
            local_size = np.linalg.norm(tangent, axis=1)
            errors.append(np.log(width / np.maximum(local_size, 1e-300))**2)
        return float(np.mean(errors))

    # Bounded search keeps preview/build time independent of a huge N range.
    estimate = int(round(float(np.median(lengths / np.linalg.norm(end, axis=1)))))
    if nmax-nmin <= 48:
        candidates = np.arange(nmin,nmax+1)
    else:
        candidates = np.unique(np.r_[np.geomspace(nmin,nmax,32).round().astype(int),
                                     np.clip(np.arange(estimate-4,estimate+5),nmin,nmax)])
    best = None
    for i,n in enumerate(candidates):
        if progress: progress(i/max(1,len(candidates)), 'Выравнивание пропорций: подбор числа слоёв')
        plateau = fit(int(n)); value = score(int(n), plateau)
        if best is None or value < best[0]-1e-12:
            best = value,int(n),plateau
    value,n,plateau = best
    j = np.arange(n)
    nominal = np.exp(np.minimum(np.log(first)[:,None]+j*logq,np.log(max_size)))
    widths = np.minimum(nominal,plateau[:,None])
    widths[:,-1] += lengths-widths.sum(axis=1)
    if np.any(widths<=0) or np.any(widths>max_size*(1+1e-9)) or (n>1 and
            (np.any(widths[:,1:]/widths[:,:-1]>growth*(1+1e-9)) or
             np.any(widths[:,1:] < widths[:,:-1]*(1-1e-9)))):
        raise ValueError('Выравнивание не удовлетворяет ограничениям роста/размера')
    dist = CoreDistribution(widths, widths[:,-1].copy(), np.full(len(first),max_size),
                            nominal,(widths<plateau[:,None]*(1-1e-9)).sum(axis=1),n)
    if progress: progress(1, 'Выравнивание пропорций: распределение готово')
    return dist,dict(count=n,sampled_candidates=len(candidates),score=value,
                    baseline_score=score(baseline.count,baseline.plateau))


def aspect_diagnostics(blocks, wall_counts, wall_starts):
    """Actual edge-aspect ratio in outer half of 2D core; angles are separate."""
    ratios=[]
    for (x,y),count,starts in zip(blocks,wall_counts,wall_starts):
        v=np.stack((x,y),axis=-1)
        core=v[:,count-1:] if starts else v[:,:-(count-1)][:,::-1]
        normal=np.linalg.norm(np.diff(core,axis=1),axis=-1)
        tangent=np.linalg.norm(np.diff(core,axis=0),axis=-1)
        dn=(normal[:-1]+normal[1:])/2
        ds=(tangent[:,:-1]+tangent[:,1:])/2
        aspect=np.maximum(dn/ds,ds/dn)
        ratios.append(aspect[:,aspect.shape[1]//2:].ravel())
    values=np.concatenate(ratios)
    return dict(median=float(np.median(values)),p95=float(np.percentile(values,95)),
                maximum=float(values.max()),fraction_under_1_5=float(np.mean(values<=1.5)))
