"""Per-block core settings stored with mesh overrides, independent of wall cache."""
from dataclasses import replace

DEFAULTS=dict(local_core_mode='inherit',local_core_growth=1.1,local_core_size=120e-6,
              local_core_limit=5000,local_core_layers=20,local_core_transition=1.1,
              local_core_hermite=False)


def wall_params(p):
    return replace(p,**DEFAULTS)


def settings(p):
    if p.local_core_mode=='inherit':return {}
    return dict(core_mode=p.local_core_mode,growth=p.local_core_growth,max_size=p.local_core_size,
                max_cells=p.local_core_limit,core_layers=p.local_core_layers,
                transition_ratio=p.local_core_transition,hermite_tfi=p.local_core_hermite)


def inherited_settings(base,template=None,block=None):
    for p in (block,template,base):
        if p is not None and p.local_core_mode!='inherit':return settings(p)
    return {}
