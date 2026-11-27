"""Target-cut diagnostics: advection includes resolved fluctuations, never mean flow alone."""
import json

KEYS=('Target_Advective_A_W','Target_Advective_B_W','Target_Molecular_A_W','Target_Molecular_B_W',
      'Target_NonMolecular_A_W','Target_NonMolecular_B_W','Target_MolecularPairMismatch_W',
      'Target_BalanceRemainder_A_W','Target_BalanceRemainder_B_W')


def emit_target_components(plan,fuse):
    lines=[]
    for side,number in (('A',plan['a']),('B',plan['b'])):
        p=next(p for p in plan['paths'] if p['source']==number and p['method']=='target')
        if p['kind']=='fuse':
            part=f'(NamedObject)required(sim.getPartManager(),{json.dumps(p["connection"])},NamedObject.class)'
        else:
            index=0 if fuse else number-1
            part=f'sidePart(modelRegions.get({index}),{json.dumps(p["base"])},{json.dumps(p["interface"])})'
        nx,ny=p['normal']
        normal=f'({nx:.17g} * $${{Velocity}}[0] + {ny:.17g} * $${{Velocity}}[1])'
        grad=f'({nx:.17g} * grad(${{Temperature}})[0] + {ny:.17g} * grad(${{Temperature}})[1])'
        lines.extend([
            f'        {{ List<NamedObject> target=Collections.singletonList({part});',
            f'          surface("Target_{side}_Advective",target,ff("Target_{side}_AdvectiveFlux","${{"+energy.getFunctionName()+"}} * {normal}",dim(1,0,-3,0)),true);',
            f'          surface("Target_{side}_Molecular",target,ff("Target_{side}_MolecularFlux","-"+ref("Lambda")+" * {grad}",dim(1,0,-3,0)),true); }}',
        ])
    return lines


DERIVED=r'''
        // B signals are outward from B; publish both in the A -> B convention.
        double advA=w.mean("Target_A_Advective"),advB=-w.mean("Target_B_Advective");
        double molA=w.mean("Target_A_Molecular"),molB=-w.mean("Target_B_Molecular");
        r.put("Target_Advective_A_W",advA);r.put("Target_Advective_B_W",advB);
        r.put("Target_Molecular_A_W",molA);r.put("Target_Molecular_B_W",molB);
        // This residual still includes mean convection: do NOT label it turbulent.
        r.put("Target_NonMolecular_A_W",qa-molA);r.put("Target_NonMolecular_B_W",qb-molB);
        r.put("Target_MolecularPairMismatch_W",molA-molB);
        // Contains modeled turbulent diffusion AND reconstruction/balance errors.
        r.put("Target_BalanceRemainder_A_W",qa-advA-molA);r.put("Target_BalanceRemainder_B_W",qb-advB-molB);
'''
