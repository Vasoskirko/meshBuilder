"""Generate signed lateral sensible-energy measurements without wall flux on cuts."""
import json

BOUNDARY_SUPPORT=r'''
    private NamedObject sidePart(Region owner,String base,String iface) {
        NamedObject found=null;
        for(Object o:objects(owner.getBoundaryManager())) {
            if(!(o instanceof Boundary))continue;Boundary b=(Boundary)o;String name=b.getPresentationName();
            boolean matches=iface.isEmpty()?name.equals(base):
                (b instanceof InterfaceBoundary && (iface.equals("AUTO_INTERNAL")?name.startsWith(base+" ["):
                 name.startsWith(base+" ["+iface+" ")||name.equals(base+" ["+iface+"]")));
            if(matches){if(found!=null)throw new IllegalStateException("Ambiguous side: "+base);found=b;}
        }
        if(found==null)throw new IllegalStateException("Active boundary side not found: "+base+" ["+iface+"]");
        return found;
    }
    private void externalPower(String output,String name) {
        Report input=(Report)required(sim.getReportManager(),name,Report.class);
        if(input.getUnits()==null || !input.getUnits().equals(sim.getUnitsManager().getObject("W")))
            throw new IllegalStateException("Side power report must use W: "+name);
        expression(output,"${"+name+"Report}",dim(1,2,-3,0),true);
    }
'''


def emit_flux_reports(plan,fuse):
    lines=[];measured={};by_connection={}
    for path in plan['paths']:
        stem='Path_'+path['id'];out=stem+'_Out'
        measured[path['id']]=out
        if path['method']=='zero':
            ridx=0 if fuse else path['source']-1
            expected='SymmetryBoundary' if path['kind']=='symmetry' else 'WallBoundary'
            lines.append(f'        if(!call(sidePart(modelRegions.get({ridx}),{json.dumps(path["base"])},""),"getBoundaryType").getClass().getSimpleName().equals("{expected}"))throw new IllegalStateException("Zero-flux BC changed: {path["id"]}");')
            lines.append(f'        expression("{out}","0",dim(1,2,-3,0),false);');continue
        nx,ny=path['normal'];normal=f'({nx:.17g} * $${{Velocity}}[0] + {ny:.17g} * $${{Velocity}}[1])'
        if path['kind']=='fuse':
            part=f'(NamedObject)required(sim.getPartManager(),{json.dumps(path["connection"])},NamedObject.class)'
        else:
            ridx=0 if fuse else path['source']-1
            part=f'sidePart(modelRegions.get({ridx}),{json.dumps(path["base"])},{json.dumps(path["interface"])})'
        lines.append(f'        surface("{stem}_MassFlowOut",Collections.singletonList({part}),ff("{stem}_MassFlux",ref("Rho")+" * {normal}",dim(1,-2,-1,0)),true);')
        if path['method']=='target':continue
        if path['method']=='report':
            lines.append(f'        externalPower("{out}",{json.dumps(plan["settings"]["path_reports"][path["id"]])});');continue
        if path['method']=='boundary':
            ridx=0 if fuse else path['source']-1
            part=f'sidePart(modelRegions.get({ridx}),{json.dumps(path["base"])},{json.dumps(path["interface"])})'
            diff='field("BoundaryConductionHeatFlux")'
            by_connection.setdefault(path['connection'],[]).append(out)
        else:
            part=f'(NamedObject)required(sim.getPartManager(),{json.dumps(path["connection"])},NamedObject.class)'
            gradient=f'({nx:.17g} * grad(${{Temperature}})[0] + {ny:.17g} * grad(${{Temperature}})[1])'
            # Primitive effective conductivity must match the scalar diffusion closure.
            definition=f'"-${{"+field("EffectiveConductivity").getFunctionName()+"}} * {gradient}"'
            diff=f'ff("{stem}_DiffusiveFlux",{definition},dim(1,0,-3,0))'
        lines.append(f'        {{ List<NamedObject> side=Collections.singletonList({part});')
        lines.append(f'          UserFieldFunction adv=ff("{stem}_AdvectiveFlux","${{"+energy.getFunctionName()+"}} * {normal}",dim(1,0,-3,0));')
        lines.append(f'          surface("{stem}_Advective",side,adv,true);')
        lines.append(f'          surface("{stem}_Diffusive",side,{diff},true);')
        lines.append(f'          expression("{out}",rr("{stem}_Advective")+" + "+rr("{stem}_Diffusive"),dim(1,2,-3,0),true); }}')
    for logical,n in enumerate((plan['a'],plan['b']),1):
        terms=[f'rr("{measured[p["id"]]}")' for p in plan['paths'] if p['source']==n and p['method'] not in ('target','zero')]
        expression='+" + "+'.join(terms) or '"0"'
        lines.append(f'        expression("Sub{logical}_OtherOut",{expression},dim(1,2,-3,0),true);')
    # Two native sides of the same periodic/internal connection must be opposite.
    checks=[]
    for powers in by_connection.values():
        if len(powers)==2:
            x,y=powers;checks.append(f'Math.abs(w.mean("{x}")+w.mean("{y}"))/Math.max(Math.max(Math.abs(w.mean("{x}")),Math.abs(w.mean("{y}"))),1e-12)')
    pair_check='0.'
    for c in checks:pair_check=f'Math.max({pair_check},{c})'
    return lines,pair_check
