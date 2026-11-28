"""Keep interface warnings distinct from block ownership and selection badges."""
import numpy as np
from matplotlib import patheffects
from matplotlib.lines import Line2D
from mesh_interface_diagnostics import face_nodes


def draw_interface_overlay(ax,result,selected=False,custom=False):
    problems=result.diagnostics.get('interface_problems',[])
    kinds=set()
    for number,issue in enumerate(problems,1):
        kind=issue['kind'];kinds.add(kind)
        color='#b500c5' if kind=='geometry_mismatch' else '#df001b'
        # Coincident polylines need one stroke, otherwise dashes superimpose.
        sides=('a','b') if kind=='geometry_mismatch' else ('a',)
        anchor=None
        for side in sides:
            nodes=face_nodes(result.blocks[issue['block_'+side]],issue['face_'+side])*1e3
            line,=ax.plot(nodes[:,0],nodes[:,1],color=color,linewidth=3,
                          linestyle='--' if kind=='geometry_mismatch' else '-',zorder=9,
                          path_effects=[patheffects.Stroke(linewidth=6,foreground='white'),patheffects.Normal()])
            line.set_gid('mesh-interface-problem')
            if anchor is None:anchor=nodes[len(nodes)//2]
        if number<=20:
            label=ax.annotate(f'С{number}',xy=anchor,xytext=(8,8),textcoords='offset points',
                fontsize=8,fontweight='bold',color=color,zorder=10,
                bbox=dict(boxstyle='round,pad=.2',facecolor='white',edgecolor=color),
                arrowprops=dict(arrowstyle='-',color=color))
            label.set_gid('mesh-interface-problem-label')
    legend=[]
    if 'nonconformal' in kinds:legend.append(Line2D([],[],color='#df001b',lw=3,label='С№ — неконформный стык'))
    if 'geometry_mismatch' in kinds:legend.append(Line2D([],[],color='#b500c5',lw=3,ls='--',label='С№ — несовпадение геометрии'))
    if selected:legend.append(Line2D([],[],color='#087ac1',marker='s',ls='',label='Синяя метка Б№ — выбранный блок'))
    if custom:legend.append(Line2D([],[],color='#333333',marker='*',ls='',label='★ — индивидуальные настройки блока'))
    if legend:ax.legend(handles=legend,loc='upper left',fontsize=8,framealpha=.95)
