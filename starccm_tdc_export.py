"""Unified TDC add-on: uses generated geometry/BCs, never a reference-case setup."""
from pathlib import Path
from copy import deepcopy
import json, math, hashlib, tempfile
from starccm_tdc_plan import build_plan
from starccm_export_geometry import plane_label
from starccm_tdc_flux import BOUNDARY_SUPPORT,emit_flux_reports

ROOT=Path(__file__).parent

def replace_method(source,name,body):
    import re
    m=re.search(r'    private [^\n]*\b'+name+r'\([^\n]*\)\s*(?:throws [^{]+)?\{',source)
    if not m:raise ValueError('Missing template method '+name)
    start=m.start();i=m.end();depth=1;quote=None;escape=False;comment=None
    while depth:
        ch=source[i];nxt=source[i:i+2];i+=1
        if comment=='line':
            if ch=='\n':comment=None
        elif comment=='block':
            if nxt=='*/':comment=None;i+=1
        elif quote:
            if escape:escape=False
            elif ch=='\\':escape=True
            elif ch==quote:quote=None
        elif nxt=='//':comment='line';i+=1
        elif nxt=='/*':comment='block';i+=1
        elif ch in ('"',"'"):quote=ch
        elif ch=='{':depth+=1
        elif ch=='}':depth-=1
    return source[:start]+body+source[i:]

def render_controller(plan,options):
    """Reuse the tested time-weighted CSV/continuation kernel, replace all case setup."""
    cat=plan['catalog'];v=plan['settings'];height=plan['height'];dt=options['time_step'];w=options['workflow']
    source=(ROOT/'tmc'/'TMC_Hybrid.java').read_text().replace('TMC','TDC')
    source=source.replace('// STAR-CCM+ 2602 add-on for the two-subchannel reference mesh.','// STAR-CCM+ 2602 unified effective energy-balance TDC; see TDC_START.txt.')
    source=source.replace('private static final String OWNER="meshBuilder.TDC.v1"','private static final String OWNER="meshBuilder.TDC.unified.v3"')
    import re
    source=re.sub(r'    private static final String\[\] WALLS[12]=.*?;\n','',source)
    source=source.replace('    private NamedObject gap;','    private NamedObject gap;\n    private final List<Region> modelRegions=new ArrayList<>();')
    # All domains, regions and wall identities come from the same catalog as the preview.
    pre=['    private void preflightGeometry() {','        domains.clear();walls.clear();planes.clear();modelRegions.clear();']
    regnames=['TVS_Assembly'] if options['inter_fuse'] else [f'Subchannel_{i}' for i in range(1,len(cat['domains'])+1)]
    for name in regnames:pre.append(f'        modelRegions.add((Region)required(sim.getRegionManager(),"{name}",Region.class));')
    pre.append('        region=modelRegions.get(0);')
    for n in (plan['a'],plan['b']):
        pre.append(f'        domains.add((NamedObject)required(sim.getPartManager(),"Subchannel_{n}_Domain",NamedObject.class));')
        pre.append('        { List<NamedObject> list=new ArrayList<>();')
        # Reuse shared interior sections; endpoint data come from actual periodic interface sides.
        for k in range(v['sections']):
            name=f'TDC_Sub{n}_Inlet' if k==0 else f'TDC_Sub{n}_Outlet' if k==v['sections']-1 else plane_label(f'Subchannel_{n}_Section',k/(v['sections']-1),height)
            pre.append(f'          list.add((NamedObject)required(sim.getPartManager(),"{name}",NamedObject.class));')
        pre.append('          planes.add(list); List<Boundary> rod=new ArrayList<>();')
        ridx=0 if options['inter_fuse'] else n-1
        for row in cat['rods']:
            if n in row['sources']:pre.append(f'          rod.add((Boundary)required(modelRegions.get({ridx}).getBoundaryManager(),"{row["id"]}",Boundary.class));')
        pre.append('          walls.add(rod); }')
    pre.append('    }');source=replace_method(source,'preflightGeometry','\n'.join(pre))
    defaults=dict(Action=(0,'dim()',''),Schema=(3,'dim()',''),Ready=(0,'dim()',''),Length=(height,'dim(0,1,0,0)','m'),
      HydroDuration=(math.ceil(plan['time']['warmup']/dt-1e-12)*dt,'dim(0,0,1,0)','s'),
      BlockDuration=(math.ceil(plan['time']['block']/dt-1e-12)*dt if v['blocks'] else plan['time']['end']-math.ceil(plan['time']['warmup']/dt-1e-12)*dt,'dim(0,0,1,0)','s'),
      PlannedBlocks=(w['blocks_per_run'] if v['blocks'] else 1,'dim()',''),EndTime=(plan['time']['end'],'dim(0,0,1,0)','s'),BlocksToRun=(w['blocks_per_run'] if v['blocks'] else 1,'dim()',''),SeriesId=(0,'dim()',''),CompletedBlocks=(0,'dim()',''),AllowStatistics=(0,'dim()',''),
      MinDeltaT=(v['min_delta_t'],'dim(0,0,0,1)','K'),BalanceTolerance=(v['balance_tolerance'],'dim()',''),CreateFieldMeans=(int(bool(options['time_mean_fields'])),'dim()',''),MaxStepsPerAction=(100000000,'dim()',''))
    body=['    private void defaults() {']+[f'        param("{k}",{val},{dim},{json.dumps(unit)});' for k,(val,dim,unit) in defaults.items()]+['    }']
    source=replace_method(source,'defaults','\n'.join(body))
    source=replace_method(source,'configureBoundaries','    private void configureBoundaries() { /* Geometry/BCs/physics belong to the import macro. */ }')
    source=replace_method(source,'periodic','')
    source=replace_method(source,'configureLateralBalances','')
    source=replace_method(source,'auditGeometry',f'''    private void auditGeometry() {{
        double[] expected=new double[] {{{plan['volumes'][plan['a']]:.17g},{plan['volumes'][plan['b']]:.17g}}};
        for(int i=1;i<=2;i++) if(Math.abs(reportValue((i==1?"A_":"B_")+"Volume")-expected[i-1])>1e-4*expected[i-1])throw new IllegalStateException("TDC domain volume does not match exported mesh");
    }}''')
    source=replace_method(source,'validateConstants','''    private void validateConstants() {
        for(String key:new String[]{"Rho","Mu","Cp","Lambda","Length","TimeStep","BlockDuration","MinDeltaT","BalanceTolerance"})positive(value(key),key);
    }''')
    source=source.replace('            requireSetup(); bindReports();', '            requireSetup(); bindReports();if((action==1||action==2||action==3||action==4) && !((Boolean)call(sim.getSolution(),"isInitialized")))throw new IllegalStateException("Initialize after TDC Action=0 before advancing time or starting statistics");')
    source=source.replace('parameterOr("Schema",0)!=1','parameterOr("Schema",0)!=3')
    source=source.replace('region.getConditions().get(EnergyUserVolumeSourceOption.class).setSelected(EnergyUserVolumeSourceOption.Type.VOLUMETRIC_HEAT_SOURCE);','for(Region r:modelRegions) r.getConditions().get(EnergyUserVolumeSourceOption.class).setSelected(EnergyUserVolumeSourceOption.Type.VOLUMETRIC_HEAT_SOURCE);')
    source=replace_method(source,'configureSource','''    private void configureSource() {
        for(Region r:modelRegions) r.getValues().get(VolumetricHeatSourceProfile.class).getMethod(ConstantScalarProfileMethod.class).getQuantity().setDefinition(rr("qvSource"));
    }''')
    # No duplicate physical parameters; use the shared export parameters.
    source=source.replace('private String ref(String name){return "${"+P+name+"}";}','''private String parameterName(String name) {
        switch(name) {case "Rho":return "rho";case "Mu":return "dynvis";case "Cp":return "Cp";case "Lambda":return "lambda";case "TemperatureRef":return "T_init";case "TimeStep":return "timeStep";case "Ub":return "U_b";case "Re":return "Re_in";default:return P+name;}
    }
    private String ref(String name){return "${"+parameterName(name)+"}";}''')
    source=source.replace('Object p=find(sim.get(GlobalParameterManager.class),P+name);','Object p=find(sim.get(GlobalParameterManager.class),parameterName(name));')
    source=source.replace('if(p==null)return fallback;requireOwned((NamedObject)p);','if(p==null)return fallback;if(parameterName(name).startsWith(P))requireOwned((NamedObject)p);')
    source=source.replace('f.getTypeOption().setSelected','f.setSyncName(true);f.getTypeOption().setSelected')
    # Explicit time-step control, no solver iterations during setup or series creation.
    source=source.replace('case 1: phase(true,','case 1: phase(false,')
    source=source.replace('case 2: phase(false,value("ThermalDuration"));','case 2: phase(false,value("HydroDuration"));')
    source=source.replace('Action: 1 hydro, 2 thermal, 3 NEW series, 4 append blocks, 5 export, 6 status.', 'Action: 1 coupled warmup, 3 NEW series, 4 collect, 5 export, 6 status; 2 is a legacy alias for 1.')
    source=replace_method(source,'status','''    private void status() {
        sim.println("[TDC] Physical time="+time()+", completed blocks="+value("CompletedBlocks")+" / "+value("PlannedBlocks")+", series="+(long)value("SeriesId"));
        sim.println("[TDC] Coupled warmup target="+value("HydroDuration")+", block duration="+value("BlockDuration")+", end time="+value("EndTime"));
    }''')
    source=source.replace('No guessed solver was modified.','No guessed solver was modified.')
    source=source.replace('double start=time(),target=start+duration;','double start=time(),target=value("HydroDuration");\n        if(start>target+1e-12)throw new IllegalStateException("Runup target already passed; choose Action=3 after checking stationarity");')
    source=source.replace('setEnergyFrozen(false);validateSample();','setEnergyFrozen(false);validateSample();\n        if(time()+1e-12<value("HydroDuration"))throw new IllegalStateException("Run the shared warmup first");')
    source=source.replace('        long id=System.currentTimeMillis();setValue("SeriesId",id);', '        double requiredEnd=time()+integer("PlannedBlocks",1,10000)*value("BlockDuration");if(value("EndTime")+1e-10<requiredEnd)throw new IllegalStateException("Increase EndTime to at least "+requiredEnd+" before a new series");\n        long id=System.currentTimeMillis();setValue("SeriesId",id);')
    # Source/report generation resolves periodic child sides, never original inactive Inlet/Outlet.
    lines=['    private void configureReports() {','        sampled.clear();','        UserFieldFunction one=ff("One","1",dim());',
      '        UserFieldFunction massZ=ff("MassFluxZ",ref("Rho")+" * $${Velocity}[2]",dim(1,-2,-1,0));',
      '        UserFieldFunction energy=ff("SensibleEnergyDensity",ref("Rho")+" * "+ref("Cp")+" * (${Temperature}-"+ref("TemperatureRef")+")",dim(1,-1,-2,0));',
      '        UserFieldFunction fluxZ=ff("SensibleFluxZ","${"+energy.getFunctionName()+"} * $${Velocity}[2]",dim(1,0,-3,0));',
      '        UserFieldFunction tempFlux=ff("TemperatureMassFluxZ","${Temperature} * ${"+massZ.getFunctionName()+"}",dim(1,-2,-1,1));',
      '        volume("Volume_All",modelRegions,one,false);']
    # Heat input is analytical boundary q times measured area; safe before initialization.
    heat_terms=[]
    for row in cat['rods']:
        if row['kind']!='fuel':continue
        ridx=0 if options['inter_fuse'] else row['sources'][0]-1
        qindex=[r['id'] for r in cat['rods'] if r['kind']=='fuel'].index(row['id'])+1
        lines.append(f'        surface("HeatArea_{row["id"]}",Collections.singletonList((Boundary)required(modelRegions.get({ridx}).getBoundaryManager(),"{row["id"]}",Boundary.class)),one,false);')
        heat_terms.append(f'"${{q{qindex}}} * "+rr("HeatArea_{row["id"]}")')
    lines.append('        expression("Heating_All",'+ ('+" + "+'.join(heat_terms)) +',dim(1,2,-3,0),false);')
    lines.append('        expression("qvSource","-"+rr("Heating_All")+" / "+rr("Volume_All"),dim(1,-1,-3,0),false);')
    for logical,n in enumerate((plan['a'],plan['b']),1):
        s=f'Sub{logical}_';lines.extend([f'        volume("{s}Volume",Collections.singletonList(domains.get({logical-1})),one,false);',f'        volume("{s}SensibleEnergy",Collections.singletonList(domains.get({logical-1})),energy,true);',f'        volume("{s}VolumeSource",Collections.singletonList(domains.get({logical-1})),field("UserSpecifiedEnergySource"),true);'])
        terms=[]
        for row in cat['rods']:
            if n in row['sources'] and row['kind']=='fuel':
                qi=[r['id'] for r in cat['rods'] if r['kind']=='fuel'].index(row['id'])+1
                lines.append(f'        surface("HeatArea_Sub{logical}_{row["id"]}",Collections.singletonList((NamedObject)required(sim.getPartManager(),"TDC_Sub{n}_Heat_{row["id"]}",NamedObject.class)),one,false);')
                terms.append(f'"${{q{qi}}} * "+rr("HeatArea_Sub{logical}_{row["id"]}")')
        lines.append(f'        expression("{s}WallHeating",'+ ('+" + "+'.join(terms) or '"0"') +',dim(1,2,-3,0),true);')
        tterms=[]
        for k in range(v['sections']):
            at=s+f'z{k}';part=f'Collections.singletonList(planes.get({logical-1}).get({k}))'
            lines.append(f'        surface("{at}_MassFlow",{part},massZ,false);')
            lines.append(f'        surface("{at}_TemperatureFlux",{part},tempFlux,false);')
            lines.append(f'        expression("{at}_TemperatureBulk",rr("{at}_TemperatureFlux")+" / "+rr("{at}_MassFlow"),dim(0,0,0,1),false);')
            tterms.append((f'"0.5 * "+rr("{at}_TemperatureBulk")') if k in (0,v['sections']-1) else f'rr("{at}_TemperatureBulk")')
        lines.append(f'        expression("{s}TemperatureBulkLength",'+'+" + "+'.join(tterms)+f'+"",dim(0,0,0,1),false);')
        # Divide the length sum using a separate expression to keep dimensions explicit.
        lines[-1]=f'        expression("{s}TemperatureBulkLength","("+'+'+" + "+'.join(tterms)+f'+") / {v["sections"]-1}",dim(0,0,0,1),true);'
        # End sides prepared by the import macro, masked to the source subchannel for Fuse.
        for role in ('Inlet','Outlet'):
            lines.append(f'        surface("{s}{role}SensibleFlow",Collections.singletonList((NamedObject)required(sim.getPartManager(),"TDC_Sub{n}_{role}",NamedObject.class)),fluxZ,true);')
        lines.append(f'        expression("{s}Exchange_NoStorage",rr("{s}WallHeating")+" + "+rr("{s}VolumeSource")+" - "+rr("{s}OutletSensibleFlow")+" + "+rr("{s}InletSensibleFlow"),dim(1,2,-3,0),true);')
    lines.append('        expression("DeltaT_BulkLength",rr("Sub1_TemperatureBulkLength")+" - "+rr("Sub2_TemperatureBulkLength"),dim(0,0,0,1),true);')
    # Fixed analytical reference, not mean of a changing mass-flux signal.
    lines.append('        expression("MassFluxRef","${rho} * ${U_b}",dim(1,-2,-1,0),true);')
    side_lines,pair_check=emit_flux_reports(plan,options['inter_fuse'])
    lines.extend(side_lines)
    lines.append('        for(Object o:objects(sim.getReportManager())) if(o instanceof Report) { Report r=(Report)o;String name=r.getPresentationName();if(tagged(r,"meshBuilder.Managed") && !name.startsWith("Quality_") && name.matches(".*(MassFlow|Imbalance|PressureDrop|Reynolds|Darcy|BulkTemperature|WallTemperature|HeatPower|Heat_Flux|Energy_Flow|TotalEnthalpy|NormalVelocity|MassFluxMean|EnthalpyFlux).*"))sample(r); }')
    lines.append('        createMonitors();\n    }')
    source=replace_method(source,'configureReports','\n'.join(lines))
    source=replace_method(source,'derived',f'''    private Map<String,Double> derived(WeightedWindow w) {{
        Map<String,Double> r=new LinkedHashMap<>();
        double otherA=w.mean("Sub1_OtherOut"),otherB=w.mean("Sub2_OtherOut");
        double qa=w.mean("Sub1_Exchange_NoStorage")-otherA-(w.last("Sub1_SensibleEnergy")-w.first("Sub1_SensibleEnergy"))/w.duration();
        double qb=-(w.mean("Sub2_Exchange_NoStorage")-otherB-(w.last("Sub2_SensibleEnergy")-w.first("Sub2_SensibleEnergy"))/w.duration());
        double delta=w.mean("DeltaT_BulkLength"),g=w.mean("MassFluxRef");
        double relative=Math.abs(qa-qb)/Math.max(Math.max(Math.abs(qa),Math.abs(qb)),1e-30);
        double pairRelative={pair_check};
        boolean valid=pairRelative<=value("BalanceTolerance") && Math.abs(delta)>=value("MinDeltaT") && qa*delta>0 && relative<=value("BalanceTolerance") && g>0;
        r.put("Duration_s",w.duration());r.put("DeltaTMean_K",delta);r.put("MassFluxMean_kg_m2_s",g);
        r.put("OtherOut_A_W",otherA);r.put("OtherOut_B_W",otherB);r.put("SidePairRelative",pairRelative);
        r.put("Exchange_A_W",qa);r.put("Exchange_B_W",qb);r.put("BalanceMismatch_W",qa-qb);
        r.put("BalanceRelative",relative);r.put("ResultValid",valid?1.:0.);
        if(valid)r.put("TDC_Effective",qa/({plan['area']:.17g}*value("Cp")*g*delta));
        return r;
    }}''')
    # Save invalid blocks and diagnostics; never replace a failed ratio by an accepted result.
    source=source.replace('if(!exists)out.write("block,start_s,end_s,"+String.join(",",data.keySet())+"\\n");','if(!exists)out.write("block,start_s,end_s,"+String.join(",",derivedKeys())+"\\n");')
    source=source.replace('for(double v:data.values())out.write(","+v);out.newLine();','for(String key:derivedKeys())out.write(","+(data.containsKey(key)?data.get(key):""));out.newLine();')
    source=source.replace('    private void appendBlock(','''    private List<String> derivedKeys(){return Arrays.asList("Duration_s","DeltaTMean_K","MassFluxMean_kg_m2_s","Exchange_A_W","Exchange_B_W","OtherOut_A_W","OtherOut_B_W","SidePairRelative","BalanceMismatch_W","BalanceRelative","ResultValid","TDC_Effective");}
    private void appendBlock(''')
    source=source.replace('    private int actionSteps=0;', '    private int actionSteps=0;\n    private WeightedWindow cumulative;')
    source=source.replace('        ensureContinuation(directory);', '        ensureContinuation(directory);\n        cumulative=loadTotal(directory,integer("CompletedBlocks",0,1000000));')
    source=source.replace('window.add(start,initial);writeRow(out,start,initial);', 'window.add(start,initial);writeRow(out,start,initial);if(cumulative.count==0)cumulative.add(start,initial);')
    source=source.replace('double[] values=validateSample();window.add(now,values);writeRow(out,now,values);', 'double[] values=validateSample();window.add(now,values);writeRow(out,now,values);cumulative.add(now,values);publish(cumulative,"Cumulative_");writeCumulative(cumulative);')
    source=source.replace('    private void exportSummary()', r'''    private WeightedWindow loadTotal(Path directory,int blocks) throws Exception {
        WeightedWindow total=new WeightedWindow(new ArrayList<>(sampled.keySet()));
        for(int i=1;i<=blocks;i++)try(BufferedReader in=Files.newBufferedReader(directory.resolve(String.format(Locale.ROOT,"block_%05d.csv",i)),StandardCharsets.UTF_8)) {
            if(!("time_s,"+String.join(",",sampled.keySet())).equals(in.readLine()))throw new IllegalStateException("Schema changed");
            String line;boolean first=true;
            while((line=in.readLine())!=null){String[] cells=line.split(",");double t=Double.parseDouble(cells[0]);double[] values=new double[cells.length-1];for(int j=0;j<values.length;j++)values[j]=Double.parseDouble(cells[j+1]);
                if(first&&total.count>0){if(Math.abs(t-total.lastTime)>1e-9)throw new IllegalStateException("Discontinuous blocks");first=false;continue;}
                total.add(t,values);first=false;}
        }
        return total;
    }
    private void writeCumulative(WeightedWindow window) throws Exception {
        Path path=seriesDirectory().resolve("cumulative.csv");boolean exists=Files.exists(path);Map<String,Double> data=derived(window);
        try(BufferedWriter out=Files.newBufferedWriter(path,StandardCharsets.UTF_8,StandardOpenOption.CREATE,StandardOpenOption.APPEND)){
            if(!exists)out.write("time_s,"+String.join(",",derivedKeys())+"\n");
            out.write(Double.toString(window.lastTime));for(String key:derivedKeys())out.write(","+(data.containsKey(key)?data.get(key):""));out.newLine();
        }
    }
    private void exportSummary()''')
    # Publish mean values with dimensions; unavailable TDC is deliberately not a stale report value.
    source=source.replace('for(Map.Entry<String,Double> entry:derived(w).entrySet()) {','''Map<String,Double> result=derived(w);
        Object previous=find(sim.getReportManager(),P+prefix+"TDC_Effective");
        if(!result.containsKey("TDC_Effective") && previous!=null) {
            requireOwned((NamedObject)previous);
            ((NamedObject)previous).setPresentationName(P+prefix+"Unavailable_TDC_"+System.currentTimeMillis());
        }
        for(Map.Entry<String,Double> entry:result.entrySet()) {''')
    source=source.replace('entry.getKey().contains("TDC")||entry.getKey().startsWith("CfSigned")','entry.getKey().contains("TDC")||entry.getKey().equals("ResultValid")||entry.getKey().equals("BalanceRelative")||entry.getKey().equals("SidePairRelative")')
    source=source.replace('r.setDimensions(units);r.setDefinition(Double.toString(entry.getValue()));','r.setDimensions(units);r.setDefinition(Double.toString(entry.getValue()));if(prefix.equals("Cumulative_") && Arrays.asList("DeltaTMean_K","Exchange_A_W","BalanceRelative","ResultValid","TDC_Effective").contains(entry.getKey()))cumulativePlot(r);')
    source=source.replace('    private void createMonitors() {', r'''
    private void cumulativePlot(Report r) {
        String name=r.getPresentationName()+"_Monitor";
        if(find(sim.getMonitorManager(),name)!=null)return;
        ReportMonitor monitor=r.createMonitor();monitor.setPresentationName(name);own(monitor);
        monitor.getStarUpdate().getUpdateModeOption().setSelected(StarUpdateModeOption.Type.EVENT);
        monitor.getStarUpdate().getEventUpdateFrequency().setUpdateEvent((FrequencyMonitorUpdateEvent)required(sim.getUpdateEventManager(),P+"ReportSteps",FrequencyMonitorUpdateEvent.class));
        try {
            Object plot=find(sim.getPlotManager(),r.getPresentationName());if(plot==null)plot=call(sim.getPlotManager(),"createMonitorPlot");else requireOwned((NamedObject)plot);
            ((NamedObject)plot).setPresentationName(r.getPresentationName());own((NamedObject)plot);
            Object selected=call(plot,"getMonitors");
            try {call(selected,"setObjects",Collections.singletonList(monitor));}
            catch(Exception e){call(selected,"addObjects",(Object)new Monitor[]{monitor});}
        }catch(Exception e){sim.println("[TDC OPTIONAL] Native plot API: "+e.getMessage()+"; use cumulative.csv. Plot samples follow the next solver update; CSV has exact timestamps.");}
    }
    private void createMonitors() {
''')
    # Avoid updating every scalar snapshot on every solver step. Cumulative plots
    # need only the nine derived diagnostics; all scalar means publish per block.
    source=source.replace('        for(int i=0;i<w.names.size();i++) {','        if(!prefix.equals("Cumulative_")) for(int i=0;i<w.names.size();i++) {')
    source=source.replace('    private int actionSteps=0;', '    private final Map<String,Report> reportCache=new HashMap<>();\n    private final Set<String> curveReports=new HashSet<>();\n    private int actionSteps=0;')
    source=source.replace('        Object found=find(sim.getReportManager(),name);', '        Object found=reportCache.get(name);if(found==null)found=find(sim.getReportManager(),name);')
    source=source.replace('return type.cast(found);','reportCache.put(name,(Report)found);return type.cast(found);')
    source=source.replace('r.setPresentationName(name);own(r);return r;', 'r.setPresentationName(name);own(r);reportCache.put(name,r);return r;')
    source=source.replace('        String name=r.getPresentationName()+"_Monitor";', '        if(!curveReports.add(r.getPresentationName()))return;\n        String name=r.getPresentationName()+"_Monitor";')
    source=source.replace('            requireOwned((NamedObject)previous);', '            requireOwned((NamedObject)previous);String oldName=P+prefix+"TDC_Effective";reportCache.remove(oldName);curveReports.remove(oldName);\n            Object oldMonitor=find(sim.getMonitorManager(),oldName+"_Monitor");if(oldMonitor instanceof NamedObject && tagged((NamedObject)oldMonitor,OWNER))((NamedObject)oldMonitor).setPresentationName(oldName+"_Unavailable_Monitor_"+System.currentTimeMillis());\n            try{Object oldPlot=find(sim.getPlotManager(),oldName);if(oldPlot instanceof NamedObject && tagged((NamedObject)oldPlot,OWNER))((NamedObject)oldPlot).setPresentationName(oldName+"_Unavailable_"+System.currentTimeMillis());}catch(Exception ignored){}\n            requireOwned((NamedObject)previous);')
    # Read-only snapshot values, with proper units; raw histories and total are time weighted.
    source=source.replace('w.names.get(i).substring(P.length())','(w.names.get(i).startsWith(P)?w.names.get(i).substring(P.length()):w.names.get(i))')
    source=source.replace('    private Dimensions sampleDimensions(String name) {','    private Dimensions sampleDimensions(String name) {\n        if(!name.startsWith(P)){Report original=sampled.get(name);return original.getUnits()==null?dim():original.getUnits().getDimensions();}')
    source=source.replace('            monitor.getStarUpdate().getUpdateModeOption()', '            if(!tagged(monitor,OWNER) && !tagged(monitor,"meshBuilder.Managed"))continue;\n            monitor.getStarUpdate().getUpdateModeOption()')
    source=source.replace('            if(monitor==null){monitor=r.createMonitor();','            if(monitor==null && !tagged(r,OWNER))continue;\n            if(monitor==null){monitor=r.createMonitor();')
    source=source.replace('r.getParts().setObjects(parts);' ,'r.getParts().setQuery(null);r.getParts().setObjects(parts);')
    # Shared selected field components. No separate all-or-nothing list in the TDC tab.
    fields=options['time_mean_fields'];native=[]
    for key in fields:
        native.append({'enthalpy':'TotalEnthalpy','pressure':'Pressure','temperature':'Temperature','wall_heat_flux':'BoundaryHeatFlux'}.get(key,'Velocity_'+key[-1] if key.startswith('velocity_') else 'WallShearStress_'+key[-1] if key.startswith('wall_shear_') else 'Density' if key=='density' else 'DynamicViscosity'))
    source=source.replace('new String[]{"Velocity","Pressure","Temperature","WallShearStress","TotalEnthalpy"}', 'new String[]{'+','.join(json.dumps(x) for x in native)+'}')
    source=source.replace('if(key.equals("WallShearStress"))','if(key.startsWith("WallShearStress")||key.equals("BoundaryHeatFlux"))')
    source=source.replace('else parts.add(region);','else parts.addAll(modelRegions);')
    source=source.replace('if(count!=5)',f'if(count!={len(native)})')
    source=replace_method(source,'fingerprint',f'''    private String fingerprint() {{
        StringBuilder text=new StringBuilder({json.dumps(hashlib.sha256(json.dumps(options,sort_keys=True).encode()).hexdigest())});
        for(String key:new String[]{{"Rho","Mu","Cp","Lambda","TemperatureRef","TimeStep","BlockDuration","Ub","Re","CreateFieldMeans"}})text.append(key).append(value(key));
        for(Object o:objects(sim.getFieldFunctionManager()))if(o instanceof UserFieldFunction)text.append(((UserFieldFunction)o).getFunctionName()).append(((UserFieldFunction)o).getDefinition());
        text.append(manifestReportNames());return text.toString();
    }}''')
    source=source.replace('        groupManaged();\n        sim.println("[TDC] NEW statistics series:', '        writeUnits(directory);\n        groupManaged();\n        sim.println("[TDC] NEW statistics series:')
    source=source.replace('    private void writeManifest()', r'''    private void writeUnits(Path directory) throws Exception {
        try(BufferedWriter out=Files.newBufferedWriter(directory.resolve("units.csv"),StandardCharsets.UTF_8,StandardOpenOption.CREATE_NEW)){
            out.write("report,units\n");for(Map.Entry<String,Report> e:sampled.entrySet())out.write(e.getKey()+",\""+(e.getValue().getUnits()==null?"":e.getValue().getUnits().getPresentationName()).replace("\"","\"\"")+"\"\n");
        }
    }
    private void writeManifest()''')
    source=source.replace('Object groups=call(manager,"getGroupsManager");moveGroup(groups,"TDC",all);', 'Object groups=call(manager,"getGroupsManager");Object root=find(groups,"TDC");if(root==null){call(groups,"createGroup","TDC");root=find(groups,"TDC");}if(root==null)throw new IllegalStateException("TDC folder unavailable");moveGroup(groups,"TDC",all);')
    source=source.replace('TDC reference setup v1'  ,'Unified effective TDC v2')
    source=source.replace('            Path path=directory.resolve(String.format(Locale.ROOT,"block_%05d.csv",number));', '            if(number>integer("PlannedBlocks",1,10000))throw new IllegalStateException("Planned blocks completed; extend plan in a new series");\n            Path path=directory.resolve(String.format(Locale.ROOT,"block_%05d.csv",number));')
    source=source.replace('runUntil(start+value("BlockDuration"),window,out);', 'double target=number==integer("PlannedBlocks",1,10000)?value("EndTime"):start+value("BlockDuration");\n                if(target<=start)throw new IllegalStateException("End time reached");runUntil(target,window,out);')
    source=source.replace('        int max=integer("MaxStepsPerAction",1,100000000);', '        sim.getSolverStoppingCriterionManager().getSolverStoppingCriterion("Maximum Physical Time");\n        PhysicalTimeStoppingCriterion stop=(PhysicalTimeStoppingCriterion)sim.getSolverStoppingCriterionManager().getSolverStoppingCriterion("Maximum Physical Time");\n        stop.getMaximumTime().setValueAndUnits(target,sim.getUnitsManager().getObject("s"));stop.setIsUsed(true);\n        int max=integer("MaxStepsPerAction",1,100000000);')
    source=source.replace("    // Pure Java numerical kernel,",BOUNDARY_SUPPORT+"\n    // Pure Java numerical kernel,")
    source=source.replace('"Sub1_', '"A_').replace('"Sub2_', '"B_')
    return source


def prepare_options(options):
    o=deepcopy(options)
    o.update(gap_sections=True,create_parameters=True)
    # Native field means belong to the series controller; setup only defines selected components.
    return o


def write_bundle(directory,xyz,result,model,fluid,yplus,options,progress):
    from starccm_tmc_export import bundle_names,_publish
    from starccm_macro_generator import generate_starccm_java_macro
    from mesh_subchannel import export_subchannel_plot3d
    from mesh_interface_diagnostics import require_star_conformity
    bundle_names(xyz);require_star_conformity(result)
    options=prepare_options(options);plan=build_plan(result,model,options,fluid,yplus)
    target=Path(directory)
    names=(xyz,'setup_starccm_subchannels.java','TDC_Hybrid.java','TDC_export.json','TDC_START.txt')
    progress(2,'Генерация баланса и усреднения TDC')
    setup=generate_starccm_java_macro(xyz,result,model,fluid,yplus,options)
    control=render_controller(plan,options)
    guide=f'''STAR-CCM+ 2602 — эффективный безразмерный TDC, без BMBC.
Пара: A=Sub{plan['a']}, B=Sub{plan['b']}; целевой путь: {plan['target']['connection']}; Q>0 из A в B; ΔT=T_A-T_B.
Площадь целевого соединения: {plan['area']:.12g} м².
1. Новый пустой .sim: setup_starccm_subchannels.java. Физика, нагрев и пары — из общего окна.
2. TDC_Hybrid.java, TDC_Action=0: отчёты, равномерный компенсационный сток. Решатель НЕ запускается.
3. Проверить условия, периодическое преобразование, источники и инициализировать вручную.
4. TDC_Action=1: совместный разгон с энергией до абсолютного времени TDC_HydroDuration.
5. Проверить установление. TDC_AllowStatistics=1, TDC_Action=3: новая серия. Старые файлы не удаляются.
6. TDC_Action=4: сбор заданных блоков; запуск решателя только этим явным действием.
   TDC_Action=5: итоговый CSV; TDC_Action=6: статус. Action сбрасывается в 0 после запуска.
Общие средние поля выбираются во вкладке 5, включены только при сборе серии.
Средние скалярных мгновенных отчётов: интеграл трапециями по фактическому времени / длительность.
Поля: один отсчёт на завершённый шаг, постоянный dt; отличие от трапеций ограничено весами концов окна.
Общий результат — из объединённой истории, не среднее блочных TDC. ΔH/Δt учитывается для каждого окна.
Q_target=mean(нагрев+сток−осевой перенос−OtherOut_A)−ΔH_A/Δt.
TDC=Q_target/(A_target*Cp*(rho*U_b)*ΔT_mean). Проверяется согласованность балансов A/B.
ResultValid=0: TDC не публикуется; исходные сигналы, балансы и средние сохраняются.
Плохой результат не блокирует сохранение блока. Проверить ΔT, знак, баланс, периодичность.
Физические wall-условия помимо заданного нагрева должны быть адиабатическими.
Осевые диффузионные потоки на периодических копиях должны компенсироваться.
Зазоры независимы: из баланса вычитается каждый прочий боковой поток. Эквивалентность не предполагается.
Boundary Conduction Heat Flux должен быть определён на действительной стороне интерфейса; проверяйте до сбора.
Реконструкция на Fuse использует EffectiveConductivity и grad(Temperature), это приближённая постобработка для скалярного замыкания.
Пользовательские отчёты — полная знаковая мощность в Вт, наружу из соответствующего подканала.
Все компоненты используют чувствительную энтальпию Cp*(T−T_init), а не смешение с TotalEnthalpy.
Это эффективный обмен: включает молекулярную и среднюю конвективную составляющие.
Проверьте средние Path_*_MassFlowOut: ненулевой направленный расход не является чистым перемешиванием; мощность зависит от T_init.
Молекулярная поправка и оценка статистической погрешности не реализованы.
Не менять dt, физику, BC и не запускать шаги вне контроллера в активной серии.
После изменения физики/геометрии — новый экспорт и новая симуляция.
Нативный запуск и Siemens SDK должны быть проверены в STAR 2602; Python/Java-контракты их не заменяют.
'''
    with tempfile.TemporaryDirectory(prefix='.tdc_',dir=target) as tmp:
        staging=Path(tmp)
        for name,text in zip(names[1:],(setup,control,json.dumps(dict(options=options,area=plan['area'],target=plan['target'],paths=plan['paths']),ensure_ascii=False,indent=2),guide)):
            (staging/name).write_text(text,encoding='utf-8')
        export_subchannel_plot3d(result,staging/xyz,progress_callback=progress)
        progress(95,'Публикация комплекта TDC')
        _publish({target/name:staging/name for name in names})
    return [target/name for name in names]


def emit_dependencies(plan,fuse):
    """Placed after sourceParts creation, where masks/report interface sides exist."""
    lines=[];count=plan['settings']['sections']
    for n in (plan['a'],plan['b']):
        if not fuse:
            lines.append(f'            UserFieldFunction tdcMask{n}=getOrCreateFF(sim,"TDC_SourceMask_{n}","1");')
            lines.append(f'            threshold(sim,sourceParts.get({n-1}),tdcMask{n},"Subchannel_{n}_Domain");')
        mask=f'mask{n}' if fuse else f'tdcMask{n}'
        for row in plan['catalog']['rods']:
            if n not in row['sources'] or row['kind']!='fuel':continue
            ridx=0 if fuse else n-1
            parts=f'Collections.singletonList(subchannelRegions.get({ridx}).getBoundaryManager().getBoundary("{row["id"]}"))'
            lines.append(f'            threshold(sim,{parts},{mask},"TDC_Sub{n}_Heat_{row["id"]}");')
        for k in range(1,count-1):
            name=plane_label(f'Subchannel_{n}_Section',k/(count-1),plan['height'])
            lines.append(f'            createPlaneSection(sim,labCoord,uLen,sourceParts.get({n-1}),"{name}",lz*{k/(count-1):.17g});planesCreated++;')
        for role,report in (('Inlet','reportInlets'),('Outlet','reportOutlets')):
            parts=report if fuse else f'Collections.singletonList({report}.get({n-1}))'
            mask=f'mask{n}' if fuse else f'tdcMask{n}'
            lines.append(f'            threshold(sim,{parts},{mask},"TDC_Sub{n}_{role}");')
    return lines
