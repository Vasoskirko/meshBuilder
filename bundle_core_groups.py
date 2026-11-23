"""Fill compatible ray groups independently, retaining original block ordering."""
from dataclasses import replace
from collections import defaultdict
from mesh_interface_diagnostics import completed_interfaces


def fill_groups(layer,model,defaults,overrides,progress):
    from mesh_subchannel import fill_subchannel_core,_check_quad_jacobians
    groups=defaultdict(list)
    for i,(x,y) in enumerate(layer.blocks):
        if layer.geom_data[i]["layer_thickness"] is None:continue
        options=dict(defaults,**overrides.get(i,{}))
        options['align_core']=options['core_mode']=='aspect_alignment'
        options['hermite_tfi']=bool(options['hermite_tfi']) and options['core_mode']=='fixed_count'
        groups[(x.shape[0],tuple(sorted(options.items())))].append(i)
    blocks=list(layer.blocks);widths=list(layer.all_block_widths);metrics=list(layer.block_metrics) if layer.block_metrics else [None]*len(blocks)
    reports=[]
    for number,((ni,items),indices) in enumerate(groups.items()):
        if progress:progress(number/len(groups),f'Ядро: группа {number+1}/{len(groups)}')
        # No interface validation in the partial group: recheck all intended
        # faces after every block has its final coordinates.
        subset=replace(layer,params=replace(layer.params,ni=ni),
            blocks=[layer.blocks[i] for i in indices],interfaces=(),intended_interfaces=(),
            wall_starts=[layer.wall_starts[i] for i in indices],geom_data=[layer.geom_data[i] for i in indices],
            all_block_widths=[layer.all_block_widths[i] for i in indices],
            layer_widths=layer.all_block_widths[indices[0]],
            block_metrics=[layer.block_metrics[i] for i in indices] if layer.block_metrics else [],
            block_params=[layer.block_params[i] for i in indices] if layer.block_params else [])
        result=fill_subchannel_core(subset,model,**dict(items),allow_nonconformal=True,_group=True,
            progress_callback=(lambda f,t:progress((number+f)/len(groups),t)) if progress else None)
        reports.append(result.diagnostics)
        for j,i in enumerate(indices):
            blocks[i]=result.blocks[j];widths[i]=result.all_block_widths[j]
            if result.block_metrics:metrics[i]=result.block_metrics[j]
    intended=layer.intended_interfaces or layer.interfaces
    interfaces,problems,intended=completed_interfaces(blocks,intended,layer.params.pitch*1e-11)
    cells=sum((x.shape[0]-1)*(x.shape[1]-1) for x,y in blocks)
    diag=dict(reports[0] if len(reports)==1 else layer.diagnostics,complete=True,is_layer_only=False,cells_2d=cells,
              cells_3d=cells*layer.params.nz,min_jacobian=_check_quad_jacobians(blocks),
              interface_problems=problems,matched_interfaces=len(interfaces),core_groups=len(groups))
    return replace(layer,blocks=blocks,interfaces=interfaces,diagnostics=diag,complete=True,
        params=replace(layer.params,nj=blocks[0][0].shape[1]),all_block_widths=widths,intended_interfaces=intended,
        block_metrics=[m for m in metrics if m is not None])
