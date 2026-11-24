// STAR-CCM+ 2602 add-on for the two-subchannel reference mesh.
// Run setup_starccm_subchannels first. This macro never imports or initializes.
package macro;

import java.util.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.io.*;
import star.common.*;
import star.base.report.*;
import star.energy.*;
import star.flow.*;
import star.segregatedflow.*;

public class TMC_Hybrid extends StarMacro {
    private static final String OWNER="meshBuilder.TMC.v1";
    private static final String P="TMC_";
    private Simulation sim;
    private Region region;
    private final List<NamedObject> domains=new ArrayList<>();
    private final List<List<Boundary>> walls=new ArrayList<>();
    private final List<List<NamedObject>> planes=new ArrayList<>();
    private NamedObject gap;
    private int actionSteps=0;
    private final LinkedHashMap<String,Report> sampled=new LinkedHashMap<>();
    private final List<String> optionalWarnings=new ArrayList<>();
    private static final String[] WALLS1={"rod_s1_R9_part2","rod_s1_R13_part1","rod_s1_R14_part3"};
    private static final String[] WALLS2={"rod_s2_R13_part4","rod_s2_R14_part6","rod_s2_R17_part5"};

    @Override public void execute() {
        sim=getActiveSimulation();
        try {
            double rawAction=parameterOr("Action",0);
            int action=(int)Math.rint(rawAction);
            if(rawAction!=action || action<0 || action>6) throw new IllegalArgumentException("Action must be 0..6");
            if(action==0) { setup(); return; }
            requireSetup(); bindReports();
            switch(action) {
                case 1: phase(true,value("HydroDuration")); break;
                case 2: phase(false,value("ThermalDuration")); break;
                case 3: startSeries(); break;
                case 4: collectBlocks(); break;
                case 5: exportSummary(); break;
                case 6: status(); break;
                default: throw new IllegalArgumentException("Unknown action");
            }
        } catch(Exception ex) {
            sim.println("[TMC ERROR] "+ex.getMessage());
            throw new IllegalStateException("TMC action stopped: "+ex.getMessage(),ex);
        } finally {
            // Never accidentally repeat a time-advancing action on the next launch.
            if(find(sim.get(GlobalParameterManager.class),P+"Action")!=null) setValue("Action",0);
            pauseFieldMeans();
        }
    }

    private void setup() throws Exception {
        preflightGeometry();
        defaults();setValue("Ready",0);
        validateConstants();
        configureBoundaries();
        region.getConditions().get(EnergyUserVolumeSourceOption.class).setSelected(EnergyUserVolumeSourceOption.Type.VOLUMETRIC_HEAT_SOURCE);
        configureReports();
        auditGeometry();
        configureSource();
        groupManaged();
        setTimeStep();
        writeManifest();setValue("Ready",1);
        sim.println("[TMC] Setup complete. No initialization, time advancement or statistics reset.");
        sim.println("[TMC] Action: 1 hydro, 2 thermal, 3 NEW series, 4 append blocks, 5 export, 6 status.");
        sim.println("[TMC] Thermal residual is sensible-energy/advection based; axial diffusive cancellation must hold at periodic copies.");
        sim.println("[TMC] TMC_Effective includes molecular/mean-flow contributions; not a pure resolved turbulent covariance.");
        for(String message:optionalWarnings) sim.println("[TMC OPTIONAL] "+message);
    }

    private void preflightGeometry() {
        region=(Region)required(sim.getRegionManager(),"TVS_Assembly",Region.class);
        for(int sub=1;sub<=2;sub++) {
            domains.add((NamedObject)required(sim.getPartManager(),"Subchannel_"+sub+"_Domain",NamedObject.class));
            List<NamedObject> list=new ArrayList<>();
            for(int k=0;k<=10;k++) list.add((NamedObject)required(sim.getPartManager(),"Subchannel_"+sub+"_Section_Z_"+(30*k)+"mm",NamedObject.class));
            planes.add(list);
            List<Boundary> rod=new ArrayList<>();
            Object merged=find(region.getBoundaryManager(),"rod_s"+sub);
            if(merged!=null) rod.add((Boundary)merged);
            else for(String name:sub==1?WALLS1:WALLS2) rod.add((Boundary)required(region.getBoundaryManager(),name,Boundary.class));
            walls.add(rod);
        }
        gap=(NamedObject)required(sim.getPartManager(),"Gap_Sub1_Sub2",NamedObject.class);
        for(String field:new String[]{"Temperature","Velocity","Density","DynamicViscosity"}) field(field);
        required(region.getBoundaryManager(),"Inlet",Boundary.class);
        required(region.getBoundaryManager(),"Outlet",Boundary.class);
        // Resolve all four lateral faces before changing any boundary condition.
        for(String name:new String[]{"sym/per","sym/per 2","sym/per 3","sym/per 4"}) required(region.getBoundaryManager(),name,Boundary.class);
    }

    private void defaults() {
        param("Action",0,dim(),"");
        param("Schema",1,dim(),"");param("Ready",0,dim(),"");
        param("Length",.3,dim(0,1,0,0),"m");
        param("GapWidth",.00254,dim(0,1,0,0),"m");
        param("EquivalentGapCount",3,dim(),"");
        param("Rho",747.3390805476422,dim(1,-3,0,0),"kg/m^3");
        param("Mu",9.271750031043231e-5,dim(1,-1,-1,0),"Pa-s");
        param("Cp",5225.098000687438,dim(0,2,-2,-1),"J/kg-K");
        param("Lambda",.5753275671409854,dim(1,1,-3,-1),"W/m-K");
        param("TemperatureRef",563.15,dim(0,0,0,1),"K");
        param("HeatFlux_Sub1",10000,dim(1,0,-3,0),"W/m^2");
        param("HeatFlux_Sub2",300000,dim(1,0,-3,0),"W/m^2");
        param("MassFlow",.1325444593154614,dim(1,0,-1,0),"kg/s");
        param("TimeStep",2.5e-5,dim(0,0,1,0),"s");
        param("HydroDuration",.45,dim(0,0,1,0),"s");
        param("ThermalDuration",.45,dim(0,0,1,0),"s");
        param("BlockDuration",.45,dim(0,0,1,0),"s");
        param("BlocksToRun",1,dim(),"");
        param("SeriesId",0,dim(),""); param("CompletedBlocks",0,dim(),"");
        param("AllowStatistics",0,dim(),"");
        param("MinDeltaT",.01,dim(0,0,0,1),"K");
        param("CreateFieldMeans",0,dim(),"");
        param("EnableOptionalGapConduction",0,dim(),"");
        param("MaxStepsPerAction",1000000,dim(),"");
    }

    private void configureBoundaries() {
        for(int i=0;i<2;i++) for(Boundary wall:walls.get(i)) {
            wall.getConditions().get(WallThermalOption.class).setSelected(WallThermalOption.Type.HEAT_FLUX);
            HeatFluxProfile profile=wall.getValues().get(HeatFluxProfile.class);
            profile.setMethod(ConstantScalarProfileMethod.class);
            profile.getMethod(ConstantScalarProfileMethod.class).getQuantity().setDefinition(ref("HeatFlux_Sub"+(i+1)));
        }
        periodic("sym/per","sym/per 4","TMC_Lateral_1",false);
        periodic("sym/per 2","sym/per 3","TMC_Lateral_2",false);
        BoundaryInterface axial=periodic("Inlet","Outlet","TMC_Axial",true);
        axial.getConditions().get(FullyDevelopedFlowOption.class).setSelected(FullyDevelopedFlowOption.Type.MASS_FLOW_RATE);
        axial.getValues().get(FullyDevelopedMassFlowRate.class).getFullyDevelopedMassFlowRate().setDefinition(ref("MassFlow"));
        // Constant properties are explicitly linked, using the user's reference model.
        Object physics=call(region,"getPhysicsContinuum");
        Object material=call(call(call(physics,"getModelManager"),"getModel",loadProperty("SingleComponentLiquidModel")),"getMaterial");
        for(String[] pair:new String[][]{{"ConstantDensityProperty","Rho"},{"DynamicViscosityProperty","Mu"},{"SpecificHeatProperty","Cp"},{"ThermalConductivityProperty","Lambda"}}) {
            Object property=call(call(material,"getMaterialProperties"),"getMaterialProperty",loadProperty(pair[0]));
            Object method=call(property,"getMethod");
            if(!method.getClass().getSimpleName().equals("ConstantMaterialPropertyMethod"))
                throw new IllegalStateException("Expected constant material property: "+pair[0]);
            call(call(method,"getQuantity"),"setDefinition",ref(pair[1]));
        }
    }

    private BoundaryInterface periodic(String a,String b,String name,boolean fullyDeveloped) {
        Boundary first=(Boundary)required(region.getBoundaryManager(),a,Boundary.class);
        Boundary second=(Boundary)required(region.getBoundaryManager(),b,Boundary.class);
        BoundaryInterface found=null;
        for(Object candidate:objects(sim.getInterfaceManager())) if(candidate instanceof BoundaryInterface) {
            Set<Boundary> ends=new HashSet<>();
            for(Method method:candidate.getClass().getMethods()) if(method.getParameterCount()==0 && Boundary.class.isAssignableFrom(method.getReturnType())) {
                try { ends.add((Boundary)method.invoke(candidate)); } catch(Exception ex) { throw new IllegalStateException("Cannot inspect interface endpoints",ex); }
            }
            if(ends.contains(first)||ends.contains(second)) {
                if(!ends.contains(first)||!ends.contains(second)) throw new IllegalStateException("Boundary already belongs to another interface: "+a+" / "+b);
                if(found!=null) throw new IllegalStateException("Duplicate interface pair");
                found=(BoundaryInterface)candidate;
            }
        }
        if(found==null) { found=sim.getInterfaceManager().createBoundaryInterface(first,second,name); own(found); }
        if(fullyDeveloped) found.setInterfaceType(sim.get(ConditionTypeManager.class).get(FullyDevelopedInterface.class));
        found.getTopology().setSelected(InterfaceConfigurationOption.Type.PERIODIC);
        return found;
    }

    private void configureReports() {
        sampled.clear();
        for(Object candidate:objects(sim.getReportManager()))if(candidate instanceof Report&&tagged((NamedObject)candidate,OWNER))unmark((NamedObject)candidate,OWNER+".Sample");
        UserFieldFunction one=ff("One","1",dim());
        UserFieldFunction uz=ff("Uz","$$Velocity[2]",dim(0,1,-1,0));
        UserFieldFunction un=ff("GapNormalVelocity","$$Velocity[1]",dim(0,1,-1,0));
        UserFieldFunction massZ=ff("MassFluxZ",ref("Rho")+" * $$Velocity[2]",dim(1,-2,-1,0));
        UserFieldFunction massY=ff("MassFluxY",ref("Rho")+" * $$Velocity[1]",dim(1,-2,-1,0));
        String sensible=ref("Rho")+" * "+ref("Cp")+" * (${Temperature} - "+ref("TemperatureRef")+")";
        UserFieldFunction energy=ff("SensibleEnergyDensity",sensible,dim(1,-1,-2,0));
        UserFieldFunction fluxZ=ff("SensibleFluxZ",sensible+" * $$Velocity[2]",dim(1,0,-3,0));
        UserFieldFunction fluxY=ff("SensibleFluxY",sensible+" * $$Velocity[1]",dim(1,0,-3,0));
        volume("Volume_All",Collections.singletonList(region),one,false);
        surface("GapArea",Collections.singletonList(gap),one,false);
        expression("GapAreaExpected",ref("GapWidth")+" * "+ref("Length"),dim(0,2,0,0),false);
        for(int sub=1;sub<=2;sub++) {
            String s="Sub"+sub+"_";
            List<NamedObject> domain=Collections.singletonList(domains.get(sub-1));
            List<NamedObject> rod=new ArrayList<NamedObject>(walls.get(sub-1));
            volume(s+"Volume",domain,one,false);
            average(s+"CentroidY",domain,ff("CentroidY","$$Centroid[1]",dim(0,1,0,0)),true,false);
            surface(s+"WallArea",rod,one,false);
            expression(s+"WettedPerimeter",rr(s+"WallArea")+" / "+ref("Length"),dim(0,1,0,0),false);
            HeatTransferReport heat=report(s+"WallHeatSigned",HeatTransferReport.class);
            heat.getParts().setObjects(rod);
            average(s+"WallTemperature",rod,field("Temperature"),false,true);
            expression(s+"WallHeating","-"+rr(s+"WallHeatSigned"),dim(1,2,-3,0),true);
            volume(s+"VolumeSource",domain,field("UserSpecifiedEnergySource"),true);
            volume(s+"SensibleEnergy",domain,energy,true);
            average(s+"TemperatureVolume",domain,field("Temperature"),true,true);
            StringBuilder lengthMean=new StringBuilder("(");
            for(int k=0;k<=10;k++) {
                List<NamedObject> section=Collections.singletonList(planes.get(sub-1).get(k));
                String at=s+"z"+(30*k);
                surface(s+"Area_z"+(30*k),section,one,false);
                average(at+"_TemperatureBulk",section,field("Temperature"),false,false);
                lengthMean.append(k==0?"":" + ").append((k==0||k==10)?"0.5 * ":"").append(rr(at+"_TemperatureBulk"));
                if(k==0||k==10) {
                    surface(at+"_MassFlow",section,massZ,true);
                    surface(at+"_SensibleFlow",section,fluxZ,true);
                    average(at+"_Pressure",section,field("Pressure"),false,true);
                    try {
                        FieldFunction h0=field("TotalEnthalpy");
                        average(at+"_TotalEnthalpy",section,h0,false,true);
                        surface(at+"_TotalEnthalpyFlow",section,ff("TotalEnthalpyFluxZ",ref("Rho")+" * $$Velocity[2] * ${TotalEnthalpy}",dim(1,0,-3,0)),true);
                    } catch(Exception ex) { optionalWarnings.add("Total enthalpy diagnostics: "+ex.getMessage()); }
                }
            }
            expression(s+"HydraulicDiameter","4 * "+rr(s+"Area_z0")+" / "+rr(s+"WettedPerimeter"),dim(0,1,0,0),false);
            lengthMean.append(") / 10");
            expression(s+"TemperatureBulkLength",lengthMean.toString(),dim(0,0,0,1),true);
            expression(s+"AxialMassResidual",rr(s+"z300_MassFlow")+" - "+rr(s+"z0_MassFlow"),dim(1,0,-1,0),true);
            expression(s+"AxialSensibleFlow",rr(s+"z300_SensibleFlow")+" - "+rr(s+"z0_SensibleFlow"),dim(1,2,-3,0),true);
            expression(s+"Exchange_NoStorage",rr(s+"WallHeating")+" + "+rr(s+"VolumeSource")+" - "+rr(s+"AxialSensibleFlow"),dim(1,2,-3,0),true);
            expression(s+"BulkVelocity",rr(s+"z0_MassFlow")+" / ("+ref("Rho")+" * "+rr(s+"Area_z0")+")",dim(0,1,-1,0),true);
            expression(s+"Reynolds",ref("Rho")+" * "+rr(s+"BulkVelocity")+" * "+rr(s+"HydraulicDiameter")+" / "+ref("Mu"),dim(),false);
            try {
                UserFieldFunction shear=ff("WallShearZ","$$WallShearStress[2]",dim(1,-1,-2,0));
                average(s+"WallShearZ",rod,shear,false,true);
                expression(s+"CfSigned",rr(s+"WallShearZ")+" / (0.5 * "+ref("Rho")+" * pow("+rr(s+"BulkVelocity")+", 2))",dim(),false);
            } catch(Exception ex) { optionalWarnings.add(s+"wall shear: "+ex.getMessage()); }
        }
        expression("Area_All",rr("Sub1_Area_z0")+" + "+rr("Sub2_Area_z0"),dim(0,2,0,0),false);
        expression("Prandtl",ref("Mu")+" * "+ref("Cp")+" / "+ref("Lambda"),dim(),false);
        expression("WallHeatSigned_All",rr("Sub1_WallHeatSigned")+" + "+rr("Sub2_WallHeatSigned"),dim(1,2,-3,0),false);
        expression("qvSource",rr("WallHeatSigned_All")+" / "+rr("Volume_All"),dim(1,-1,-3,0),false);
        volume("VolumeSource_All",Collections.singletonList(region),field("UserSpecifiedEnergySource"),false);
        expression("HeatingPlusSource","-"+rr("WallHeatSigned_All")+" + "+rr("VolumeSource_All"),dim(1,2,-3,0),true);
        expression("EnergyResidual_NoStorage",rr("HeatingPlusSource")+" - "+rr("Sub1_AxialSensibleFlow")+" - "+rr("Sub2_AxialSensibleFlow"),dim(1,2,-3,0),true);
        expression("DeltaT_BulkLength",rr("Sub2_TemperatureBulkLength")+" - "+rr("Sub1_TemperatureBulkLength"),dim(0,0,0,1),true);
        expression("DeltaT_Volume",rr("Sub2_TemperatureVolume")+" - "+rr("Sub1_TemperatureVolume"),dim(0,0,0,1),true);
        expression("MassFluxRef","("+rr("Sub1_z0_MassFlow")+" + "+rr("Sub2_z0_MassFlow")+") / ("+rr("Sub1_Area_z0")+" + "+rr("Sub2_Area_z0")+")",dim(1,-2,-1,0),true);
        surface("GapMassFlow_Positive1to2",Collections.singletonList(gap),massY,true);
        surface("GapSensibleAdvection_Positive1to2",Collections.singletonList(gap),fluxY,true);
        average("GapNormalVelocity",Collections.singletonList(gap),un,false,false);
        try {
            FieldFunction cflField=field("ConvectiveCourantNumber");
            MaximumReport cfl=report("CFL_Max",MaximumReport.class);cfl.setFieldFunction(cflField);cfl.getParts().setObjects(region);sample(cfl);
            average("CFL_VolumeAverage",Collections.singletonList(region),cflField,true,false);
        } catch(Exception ex) { optionalWarnings.add("CFL: "+ex.getMessage()); }
        if(value("EnableOptionalGapConduction")==1) {
            UserFieldFunction conduction=ff("GapMolecularFluxY","-"+ref("Lambda")+" * grad(${Temperature})[1]",dim(1,0,-3,0));
            surface("GapMolecularPower_Positive1to2",Collections.singletonList(gap),conduction,true);
        }
        configureLateralBalances(energy);
        expression("MassResidual_All",rr("Sub1_MassResidual")+" + "+rr("Sub2_MassResidual"),dim(1,0,-1,0),true);
        createMonitors();
    }

    private void configureLateralBalances(UserFieldFunction energy) {
        UserFieldFunction cy=ff("CentroidY","$$Centroid[1]",dim(0,1,0,0));
        UserFieldFunction cx=ff("CentroidX","$$Centroid[0]",dim(0,1,0,0));
        String[] sides={"sym/per","sym/per 2","sym/per 3","sym/per 4"};
        List<String> s1=new ArrayList<>(),s2=new ArrayList<>();
        for(int i=0;i<sides.length;i++) {
            Boundary side=(Boundary)required(region.getBoundaryManager(),sides[i],Boundary.class);
            List<NamedObject> parts=Collections.singletonList(side);
            average("Side"+i+"_CentroidY",parts,cy,false,false);
            average("Side"+i+"_CentroidX",parts,cx,false,false);
            double y=reportValue("Side"+i+"_CentroidY"),x=reportValue("Side"+i+"_CentroidX");
            int sub=y<.010080535700050866?1:2;
            double nx=x<0?-Math.sqrt(3)/2:Math.sqrt(3)/2,ny=sub==1?-.5:.5;
            String normal="("+nx+" * $$Velocity[0] + "+ny+" * $$Velocity[1])";
            UserFieldFunction mass=ff("Side"+i+"_MassFlux",ref("Rho")+" * "+normal,dim(1,-2,-1,0));
            UserFieldFunction heat=ff("Side"+i+"_SensibleFlux", "${"+energy.getFunctionName()+"} * "+normal,dim(1,0,-3,0));
            surface("Side"+i+"_MassFlow",parts,mass,false);
            surface("Side"+i+"_SensibleFlow",parts,heat,false);
            (sub==1?s1:s2).add(rr("Side"+i+"_MassFlow"));
        }
        if(s1.size()!=2||s2.size()!=2)throw new IllegalStateException("Reference lateral boundary geometry changed");
        expression("Sub1_MassResidual",rr("Sub1_AxialMassResidual")+" + "+String.join(" + ",s1)+" + "+rr("GapMassFlow_Positive1to2"),dim(1,0,-1,0),true);
        expression("Sub2_MassResidual",rr("Sub2_AxialMassResidual")+" + "+String.join(" + ",s2)+" - "+rr("GapMassFlow_Positive1to2"),dim(1,0,-1,0),true);
    }

    private void configureSource() {
        region.getConditions().get(EnergyUserVolumeSourceOption.class).setSelected(EnergyUserVolumeSourceOption.Type.VOLUMETRIC_HEAT_SOURCE);
        region.getValues().get(VolumetricHeatSourceProfile.class).getMethod(ConstantScalarProfileMethod.class).getQuantity().setDefinition(rr("qvSource"));
    }

    private void requireSetup() {
        if(parameterOr("Schema",0)!=1||parameterOr("Ready",0)!=1) throw new IllegalStateException("Run Action=0 setup first");
        preflightGeometry(); validateConstants();
    }
    private void bindReports() {
        sampled.clear();
        String list=manifestReportNames();
        for(String name:list.split(";")) if(!name.isEmpty()) sampled.put(name,(Report)required(sim.getReportManager(),name,Report.class));
    }
    private String manifestReportNames() {
        // Reports are identified by a separate sample tag, not name heuristics.
        List<String> names=new ArrayList<>();
        for(Object candidate:objects(sim.getReportManager())) if(candidate instanceof Report && tagged((NamedObject)candidate,OWNER+".Sample")) names.add(((Report)candidate).getPresentationName());
        Collections.sort(names);return String.join(";",names);
    }

    private void phase(boolean frozen,double duration) throws Exception {
        positive(duration,"phase duration");pauseFieldMeans();setValue("AllowStatistics",0);setEnergyFrozen(frozen);setTimeStep();
        double start=time(),target=start+duration;
        runUntil(target,null,null);
        sim.println("[TMC] "+(frozen?"Hydrodynamic":"Thermal")+" phase: "+start+" -> "+time()+" s. No statistics were collected.");
    }
    private void startSeries() throws Exception {
        if(value("AllowStatistics")!=1) throw new IllegalStateException("Set TMC_AllowStatistics=1 only after checking hydrodynamic AND thermal stationarity");
        setEnergyFrozen(false);validateSample();
        long id=System.currentTimeMillis();setValue("SeriesId",id);setValue("CompletedBlocks",0);
        Path directory=seriesDirectory();Files.createDirectories(directory);
        Files.write(directory.resolve("configuration.txt"),fingerprint().getBytes(StandardCharsets.UTF_8),StandardOpenOption.CREATE_NEW);
        if(value("CreateFieldMeans")==1) createFieldMeans(id);
        groupManaged();
        sim.println("[TMC] NEW statistics series: "+directory+". Previous series files retained. No steps run.");
    }
    private void collectBlocks() throws Exception {
        if(value("AllowStatistics")!=1 || value("SeriesId")==0) throw new IllegalStateException("Start an approved statistics series with Action=3 first");
        int count=integer("BlocksToRun",1,10000);positive(value("BlockDuration"),"block duration");
        Path directory=seriesDirectory();
        String original=new String(Files.readAllBytes(directory.resolve("configuration.txt")),StandardCharsets.UTF_8);
        if(!original.equals(fingerprint())) throw new IllegalStateException("Physical settings/report definitions changed: start a NEW series");
        ensureContinuation(directory);
        setEnergyFrozen(false);setTimeStep();
        enableFieldMeans();
        try {
        for(int k=0;k<count;k++) {
            int number=integer("CompletedBlocks",0,1000000)+1;
            Path path=directory.resolve(String.format(Locale.ROOT,"block_%05d.csv",number));
            if(Files.exists(path)) throw new IllegalStateException("Refusing to overwrite "+path);
            double start=time();WeightedWindow window=new WeightedWindow(new ArrayList<>(sampled.keySet()));
            Path partial=directory.resolve(String.format(Locale.ROOT,"block_%05d.partial.csv",number));
            try(BufferedWriter out=Files.newBufferedWriter(partial,StandardCharsets.UTF_8,StandardOpenOption.CREATE_NEW)) {
                out.write("time_s,"+String.join(",",sampled.keySet()));out.newLine();
                double[] initial=validateSample();window.add(start,initial);writeRow(out,start,initial);
                runUntil(start+value("BlockDuration"),window,out);
            }
            // Validate derived values before accepting any block file.
            derived(window);
            Files.move(partial,path);
            appendBlock(directory,number,window);
            setValue("CompletedBlocks",number);
            publish(window,"LastBlock_");
            sim.println("[TMC] Completed block "+number+", duration="+window.duration()+" s. File: "+path);
        }
        exportSummary();
        } finally { pauseFieldMeans(); }
    }
    private void runUntil(double target,WeightedWindow window,BufferedWriter out) throws Exception {
        int max=integer("MaxStepsPerAction",1,100000000);
        for(int step=0;time()<target-1e-12;step++) {
            if(actionSteps++>=max) throw new IllegalStateException("MaxStepsPerAction reached");
            double before=time();
            sim.getSimulationIterator().step(1);
            double now=time();
            if(!Double.isFinite(now)||now<=before) throw new IllegalStateException("Physical time did not advance after step(1); check stopping criteria/solver setup");
            if(window!=null) {
                if(value("CreateFieldMeans")==1 && Math.abs((now-before)-value("TimeStep"))>1e-8*value("TimeStep"))
                    throw new IllegalStateException("Variable dt is incompatible with enabled equal-step field means; scalar CSV remains in .partial file");
                double[] values=validateSample();window.add(now,values);writeRow(out,now,values);
            }
        }
    }
    private void exportSummary() throws Exception {
        Path directory=seriesDirectory();int blocks=integer("CompletedBlocks",1,1000000);
        WeightedWindow total=new WeightedWindow(new ArrayList<>(sampled.keySet()));
        for(int block=1;block<=blocks;block++) {
            Path path=directory.resolve(String.format(Locale.ROOT,"block_%05d.csv",block));
            try(BufferedReader in=Files.newBufferedReader(path,StandardCharsets.UTF_8)) {
                String expected="time_s,"+String.join(",",sampled.keySet());
                if(!expected.equals(in.readLine())) throw new IllegalStateException("CSV report schema mismatch: "+path);
                String line;boolean first=true;
                while((line=in.readLine())!=null) {
                    String[] cells=line.split(",",-1);double t=Double.parseDouble(cells[0]);double[] data=new double[cells.length-1];
                    for(int i=0;i<data.length;i++)data[i]=Double.parseDouble(cells[i+1]);
                    if(first && total.count>0) {
                        if(Math.abs(t-total.lastTime)>1e-9) throw new IllegalStateException("Gap between statistics blocks; start a new series after manual/warmup steps");
                        first=false;continue;
                    }
                    total.add(t,data);first=false;
                }
            }
        }
        publish(total,"Mean_");
        Path temporary=Files.createTempFile(directory,"summary_",".tmp");
        try(BufferedWriter out=Files.newBufferedWriter(temporary,StandardCharsets.UTF_8)) {
            out.write("report,time_mean,time_stddev\n");
            for(int i=0;i<total.names.size();i++)out.write(total.names.get(i)+","+total.mean(i)+","+total.sd(i)+"\n");
            for(Map.Entry<String,Double> entry:derived(total).entrySet())out.write(entry.getKey()+","+entry.getValue()+",\n");
        }
        Files.move(temporary,directory.resolve("summary.csv"),StandardCopyOption.REPLACE_EXISTING);
        groupManaged();
        sim.println("[TMC] Time-weighted summary: "+directory.resolve("summary.csv"));
    }
    private Map<String,Double> derived(WeightedWindow w) {
        Map<String,Double> r=new LinkedHashMap<>();
        double storage1=(w.last("Sub1_SensibleEnergy")-w.first("Sub1_SensibleEnergy"))/w.duration();
        double storage2=(w.last("Sub2_SensibleEnergy")-w.first("Sub2_SensibleEnergy"))/w.duration();
        double hot=w.mean("Sub2_Exchange_NoStorage")-storage2;
        double cold=-(w.mean("Sub1_Exchange_NoStorage")-storage1);
        double dt=w.mean("DeltaT_BulkLength"),mass=w.mean("MassFluxRef");
        if(dt<value("MinDeltaT")||mass<=0||hot<=0) throw new IllegalStateException("TMC undefined: Sub2 must be hotter than Sub1, exchange out of Sub2 and reference mass flux must be positive");
        double area=value("GapWidth")*value("Length"),n=integer("EquivalentGapCount",1,3);
        r.put("DeltaTMean_K",dt);r.put("MassFluxMean_kg_m2_s",mass);
        r.put("Duration_s",w.duration());r.put("Storage_Sub1_W",storage1);r.put("Storage_Sub2_W",storage2);
        r.put("ThermalResidual_WithStorage_W",w.mean("EnergyResidual_NoStorage")-storage1-storage2);
        r.put("Exchange_HotBalance_W",hot);r.put("Exchange_ColdBalance_W",cold);r.put("ExchangeMismatch_W",hot-cold);
        r.put("GapExchange_AssumingEquivalent_W",hot/n);
        for(int sub=1;sub<=2;sub++)if(w.names.contains(P+"Sub"+sub+"_WallShearZ")) {
            double u=w.mean("Sub"+sub+"_BulkVelocity");
            if(Math.abs(u)>1e-12)r.put("CfSigned_Sub"+sub+"_FromMeans",w.mean("Sub"+sub+"_WallShearZ")/(.5*value("Rho")*u*u));
        }
        r.put("TMC_Effective",tmcCoefficient(hot,n,area,value("Cp"),mass,dt,value("MinDeltaT")));
        if(w.names.contains(P+"GapMolecularPower_Positive1to2")) {
            double conduction=-w.mean("GapMolecularPower_Positive1to2");
            r.put("GapMolecularHotToCold_W",conduction);
            r.put("TMC_MolecularCorrected",(hot/n-conduction)/(area*value("Cp")*mass*dt));
        }
        double dv=w.mean("DeltaT_Volume");
        if(Math.abs(dv)>=value("MinDeltaT"))r.put("TMC_VolumeTemperatureDiagnostic",hot/(n*area*value("Cp")*mass*dv));
        return r;
    }
    private void appendBlock(Path directory,int number,WeightedWindow window) throws Exception {
        Map<String,Double> data=derived(window);Path path=directory.resolve("blocks.csv");
        boolean exists=Files.exists(path);
        try(BufferedWriter out=Files.newBufferedWriter(path,StandardCharsets.UTF_8,StandardOpenOption.CREATE,StandardOpenOption.APPEND)) {
            if(!exists)out.write("block,start_s,end_s,"+String.join(",",data.keySet())+"\n");
            out.write(number+","+window.startTime+","+window.lastTime);
            for(double v:data.values())out.write(","+v);out.newLine();
        }
    }
    private void publish(WeightedWindow w,String prefix) {
        for(int i=0;i<w.names.size();i++) {
            ExpressionReport mean=reportExact(P+prefix+w.names.get(i).substring(P.length()),ExpressionReport.class);
            mean.setDimensions(sampleDimensions(w.names.get(i)));mean.setDefinition(Double.toString(w.mean(i)));
        }
        for(Map.Entry<String,Double> entry:derived(w).entrySet()) {
            String name=P+prefix+entry.getKey();ExpressionReport r=reportExact(name,ExpressionReport.class);
            Dimensions units=entry.getKey().equals("Duration_s")?dim(0,0,1,0):entry.getKey().equals("DeltaTMean_K")?dim(0,0,0,1):entry.getKey().equals("MassFluxMean_kg_m2_s")?dim(1,-2,-1,0):(entry.getKey().contains("TMC")||entry.getKey().startsWith("CfSigned"))?dim():dim(1,2,-3,0);
            r.setDimensions(units);r.setDefinition(Double.toString(entry.getValue()));
        }
    }

    private void createFieldMeans(long id) {
        // Scalar TMC statistics always use measured dt. Native field means are
        // explicitly opt-in, only for constant dt and uninterrupted sampling.
        PhysicalTimeMonitor clock=null;
        for(Object candidate:objects(sim.getMonitorManager()))if(candidate instanceof PhysicalTimeMonitor)clock=(PhysicalTimeMonitor)candidate;
        if(clock==null)throw new IllegalStateException("PhysicalTimeMonitor unavailable");
        String name=P+"Series"+id+"_Event";
        FrequencyMonitorUpdateEvent event=sim.getUpdateEventManager().createUpdateEvent(FrequencyMonitorUpdateEvent.class);
        event.setPresentationName(name);own(event);event.setMonitor(clock);event.setSampleFrequency(1);event.setStartCount(1);
        for(String key:new String[]{"Velocity","Pressure","Temperature","WallShearStress","TotalEnthalpy"}) {
            FieldFunction f=field(key);
            FieldMeanMonitor mean=sim.getMonitorManager().createMonitor(FieldMeanMonitor.class);
            mean.setPresentationName(P+"Series"+id+"_Mean_"+key);own(mean);
            List<NamedObject> parts=new ArrayList<>();
            if(key.equals("WallShearStress")){parts.addAll(walls.get(0));parts.addAll(walls.get(1));}else parts.add(region);
            mean.setObjects(parts);mean.setFieldFunction(f);
            try { call(mean.getStarUpdate(),"setEnabled",false); }
            catch(Exception ex) { sim.getMonitorManager().remove(mean);throw new IllegalStateException("Native field-mean pause API not available; leave CreateFieldMeans=0 and use scalar time-weighted statistics",ex); }
            mean.getStarUpdate().getUpdateModeOption().setSelected(StarUpdateModeOption.Type.EVENT);
            mean.getStarUpdate().getEventUpdateFrequency().setUpdateEvent(event);
        }
        sim.println("[TMC] Native field means are enabled only during Action=4, constant dt required. Scalar statistics use actual elapsed time.");
    }

    private String bucket(String name,boolean parameters) {
        if(parameters)return name.contains("Duration")||name.contains("Block")||name.contains("Action")||name.contains("TimeStep")||name.contains("Statistics")||name.contains("Series")||name.contains("Ready")||name.contains("Schema")?"Control":"Physical";
        if(name.contains("Mean_")||name.contains("LastBlock_"))return "Statistics";
        if(name.contains("Area")||name.endsWith("Volume")||name.endsWith("Volume_All")||name.contains("Centroid")||name.contains("Wetted")||name.contains("Hydraulic"))return "Geometry";
        if(name.contains("Residual")||name.contains("Source")||name.contains("Exchange")||name.contains("HeatingPlus"))return "Balances";
        if(name.contains("Gap")||name.contains("DeltaT")||name.contains("MassFluxRef"))return "Mixing";
        if(name.contains("WallShear")||name.contains("Cf"))return "Wall";
        if(name.contains("Temperature")||name.contains("Sensible")||name.contains("Enthalpy")||name.contains("Heat"))return "Thermal";
        if(name.contains("CFL"))return "Numerics";
        return "Flow";
    }
    private void moveGroup(Object manager,String name,List<NamedObject> members) throws Exception {
        for(Method m:manager.getClass().getMethods())if(m.getName().equals("groupObjects")&&m.getParameterCount()==3) {
            Class<?> expected=m.getParameterTypes()[1];
            Object list=expected.isAssignableFrom(ArrayList.class)?new ArrayList<>(members):expected.isAssignableFrom(Vector.class)?new Vector<>(members):
                Class.forName("star.base.neo.NeoObjectVector").getConstructor(Object[].class).newInstance((Object)members.toArray());
            try {m.invoke(manager,name,list,true);return;}catch(IllegalArgumentException ignored){}
        }
        throw new IllegalStateException("Native grouping API unavailable");
    }
    private void groupManaged() {
        Object parameters=sim.get(GlobalParameterManager.class);
        for(Object manager:new Object[]{sim.getReportManager(),sim.getMonitorManager(),sim.getFieldFunctionManager(),parameters}) {
            try {
                List<NamedObject> all=new ArrayList<>();Map<String,List<NamedObject>> buckets=new TreeMap<>();
                for(Object o:objects(manager))if(o instanceof NamedObject&&tagged((NamedObject)o,OWNER)) {
                    NamedObject item=(NamedObject)o;all.add(item);
                    buckets.computeIfAbsent(bucket(item.getPresentationName(),manager==parameters),k->new ArrayList<>()).add(item);
                }
                if(all.isEmpty())continue;
                Object groups=call(manager,"getGroupsManager");moveGroup(groups,"TMC",all);
                Object folders=call(call(groups,"getObject","TMC"),"getGroupsManager");
                for(Map.Entry<String,List<NamedObject>> entry:buckets.entrySet())moveGroup(folders,entry.getKey(),entry.getValue());
            } catch(Exception ex) { sim.println("[TMC OPTIONAL] Grouping: "+ex.getMessage()); }
        }
    }

    private void setEnergyFrozen(boolean frozen) {
        List<Object> energy=new ArrayList<>();
        for(Object solver:objects(sim.getSolverManager())) {
            String name=solver.getClass().getSimpleName();
            if(name.equals("SegregatedEnergySolver")||name.equals("SegregatedFluidTemperatureSolver"))energy.add(solver);
        }
        if(energy.size()!=1)throw new IllegalStateException("Expected one segregated energy solver; found "+energy.size()+". No guessed solver was modified.");
        call(energy.get(0),"setFrozen",frozen);
    }
    private void setTimeStep() {
        sim.getSolverManager().getSolver(ImplicitUnsteadySolver.class).getTimeStep().setDefinition(ref("TimeStep"));
    }
    private void validateConstants() {
        for(String key:new String[]{"Rho","Mu","Cp","Lambda","Length","GapWidth","TimeStep","MassFlow","BlockDuration","MinDeltaT"})positive(value(key),key);
        if(Math.abs(value("Length")-.3)>1e-12||Math.abs(value("GapWidth")-.00254)>1e-12)
            throw new IllegalStateException("Reference geometry is fixed at L=.3 m and gap=.00254 m; regenerate geometry/macro for another case");
        integer("EquivalentGapCount",1,3);
        for(String key:new String[]{"CreateFieldMeans","EnableOptionalGapConduction","AllowStatistics"})integer(key,0,1);
        if(value("HeatFlux_Sub1")<0||value("HeatFlux_Sub2")<=value("HeatFlux_Sub1"))throw new IllegalStateException("Reference method requires Sub2 to be the hotter heated channel");
    }
    private double[] validateSample() {
        double[] result=new double[sampled.size()];int i=0;
        for(Map.Entry<String,Report> entry:sampled.entrySet()) {
            double v=entry.getValue().getReportMonitorValue();
            if(!Double.isFinite(v))throw new IllegalStateException("Nonfinite report: "+entry.getKey()+"; no valid statistics accepted");
            result[i++]=v;
        }
        return result;
    }
    private void status() {
        sim.println("[TMC] Physical time="+time()+", completed blocks="+value("CompletedBlocks")+", series="+(long)value("SeriesId"));
        sim.println("[TMC] Warmup durations="+value("HydroDuration")+" / "+value("ThermalDuration")+" s; block="+value("BlockDuration")+" s; next block count="+value("BlocksToRun"));
    }

    private void writeManifest() throws Exception {
        Path path=Paths.get(sim.getSessionDir()).resolve("TMC_setup_manifest.txt");
        Files.write(path,("TMC reference setup v1\n"+fingerprint()+"\nSampled reports:\n"+manifestReportNames()+"\n").getBytes(StandardCharsets.UTF_8));
    }
    private String fingerprint() {
        StringBuilder text=new StringBuilder("TMC-v1|L=.3|sections=11|axis=Z|gapNormal=+Y|hot=Sub2|bulk-temperature-length-average\n");
        for(String key:new String[]{"Rho","Mu","Cp","Lambda","TemperatureRef","HeatFlux_Sub1","HeatFlux_Sub2","MassFlow","Length","GapWidth","EquivalentGapCount","CreateFieldMeans","EnableOptionalGapConduction"}) text.append(key).append('=').append(value(key)).append('\n');
        if(value("CreateFieldMeans")==1)text.append("ConstantFieldMeanTimeStep=").append(value("TimeStep")).append('\n');
        text.append(manifestReportNames()).append('\n');
        TreeMap<String,String> defs=new TreeMap<>();
        for(Object o:objects(sim.getFieldFunctionManager()))if(o instanceof UserFieldFunction&&tagged((NamedObject)o,OWNER))defs.put(((NamedObject)o).getPresentationName(),((UserFieldFunction)o).getDefinition());
        for(Object o:objects(sim.getReportManager()))if(o instanceof ExpressionReport&&tagged((NamedObject)o,OWNER)&&!((NamedObject)o).getPresentationName().startsWith(P+"Mean_")&&!((NamedObject)o).getPresentationName().startsWith(P+"LastBlock_"))defs.put(((NamedObject)o).getPresentationName(),((ExpressionReport)o).getDefinition());
        text.append(defs.toString());return text.toString();
    }
    private Path seriesDirectory() {
        long id=(long)value("SeriesId");if(id<=0)throw new IllegalStateException("No statistics series");
        return Paths.get(sim.getSessionDir()).resolve("TMC_series_"+id);
    }
    private double time() { return ((Number)call(sim.getSolution(),"getPhysicalTime")).doubleValue(); }
    private void writeRow(BufferedWriter out,double time,double[] values) throws IOException {
        out.write(Double.toString(time));for(double v:values)out.write(","+Double.toString(v));out.newLine();out.flush();
    }

    private Dimensions dim(){return Dimensions.Builder().build();}
    private Dimensions dim(int m,int l,int t,int temperature){return Dimensions.Builder().mass(m).length(l).time(t).temperature(temperature).build();}
    private String ref(String name){return "${"+P+name+"}";}
    private String rr(String name){return "${"+P+name+"Report}";}
    private FieldFunction field(String name){FieldFunction f=sim.getFieldFunctionManager().getFunction(name);if(f==null)throw new IllegalStateException("Missing field "+name);return f;}
    private UserFieldFunction ff(String name,String definition,Dimensions units) {
        UserFieldFunction f=(UserFieldFunction)find(sim.getFieldFunctionManager(),P+name);
        if(f==null){f=sim.getFieldFunctionManager().createFieldFunction();f.setPresentationName(P+name);f.setFunctionName(P+name);own(f);}else requireOwned(f);
        f.getTypeOption().setSelected(FieldFunctionTypeOption.Type.SCALAR);f.setDimensions(units);f.setDefinition(definition);return f;
    }
    private <T extends Report>T report(String name,Class<T> type){return reportExact(P+name,type);}
    private <T extends Report>T reportExact(String name,Class<T> type) {
        Object found=find(sim.getReportManager(),name);
        if(found!=null){requireOwned((NamedObject)found);if(!type.isInstance(found))throw new IllegalStateException("Report type collision: "+name);return type.cast(found);}
        T r=sim.getReportManager().createReport(type);r.setPresentationName(name);own(r);return r;
    }
    private void sample(Report r){sampled.put(r.getPresentationName(),r);mark(r,OWNER+".Sample");}
    private void volume(String name,List<? extends NamedObject> parts,FieldFunction f,boolean monitor) {
        VolumeIntegralReport r=report(name,VolumeIntegralReport.class);r.setFieldFunction(f);r.getParts().setObjects(parts);if(monitor)sample(r);
    }
    private void surface(String name,List<? extends NamedObject> parts,FieldFunction f,boolean monitor) {
        if(parts==null)return;
        SurfaceIntegralReport r=report(name,SurfaceIntegralReport.class);r.setFieldFunction(f);r.getParts().setObjects(parts);if(monitor)sample(r);
    }
    private void average(String name,List<? extends NamedObject> parts,FieldFunction f,boolean volume,boolean monitor) {
        Report r;
        if(volume){VolumeAverageReport v=report(name,VolumeAverageReport.class);v.setFieldFunction(f);v.getParts().setObjects(parts);r=v;}
        else if(name.endsWith("TemperatureBulk")||name.endsWith("TotalEnthalpy")){MassFlowAverageReport v=report(name,MassFlowAverageReport.class);v.setFieldFunction(f);v.getParts().setObjects(parts);r=v;}
        else {AreaAverageReport v=report(name,AreaAverageReport.class);v.setFieldFunction(f);v.getParts().setObjects(parts);r=v;}
        if(monitor)sample(r);
    }
    private ExpressionReport expression(String name,String definition,Dimensions units,boolean monitor) {
        ExpressionReport r=report(name,ExpressionReport.class);r.setDimensions(units);r.setDefinition(definition);if(monitor)sample(r);return r;
    }
    private void createMonitors() {
        PhysicalTimeMonitor clock=null;
        for(Object candidate:objects(sim.getMonitorManager()))if(candidate instanceof PhysicalTimeMonitor)clock=(PhysicalTimeMonitor)candidate;
        if(clock==null)throw new IllegalStateException("Physical time monitor missing");
        FrequencyMonitorUpdateEvent event=(FrequencyMonitorUpdateEvent)find(sim.getUpdateEventManager(),P+"ReportSteps");
        if(event==null){event=sim.getUpdateEventManager().createUpdateEvent(FrequencyMonitorUpdateEvent.class);event.setPresentationName(P+"ReportSteps");own(event);}else requireOwned(event);
        event.setMonitor(clock);event.setSampleFrequency(1);event.setStartCount(1);
        for(Report r:sampled.values()) {
            ReportMonitor monitor=null;
            for(Object candidate:objects(sim.getMonitorManager()))if(candidate instanceof ReportMonitor && ((ReportMonitor)candidate).getReport()==r){monitor=(ReportMonitor)candidate;break;}
            if(monitor==null){monitor=r.createMonitor();monitor.setPresentationName(r.getPresentationName()+"_Monitor");own(monitor);}
            monitor.getStarUpdate().getUpdateModeOption().setSelected(StarUpdateModeOption.Type.EVENT);
            monitor.getStarUpdate().getEventUpdateFrequency().setUpdateEvent(event);
        }
    }
    private void param(String name,double initial,Dimensions units,String unitName) {
        GlobalParameterManager manager=sim.get(GlobalParameterManager.class);
        ScalarGlobalParameter p=(ScalarGlobalParameter)find(manager,P+name);
        if(p!=null){requireOwned(p);return;}
        p=(ScalarGlobalParameter)manager.createGlobalParameter(ScalarGlobalParameter.class,"Scalar");p.setPresentationName(P+name);own(p);
        p.setDimensions(units);p.getQuantity().setValueAndUnits(initial,sim.getUnitsManager().getObject(unitName));
    }
    private double parameterOr(String name,double fallback) {
        Object p=find(sim.get(GlobalParameterManager.class),P+name);
        if(p==null)return fallback;requireOwned((NamedObject)p);
        return ((Number)call(call(p,"getQuantity"),"getRawValue")).doubleValue();
    }
    private double value(String name){double v=parameterOr(name,Double.NaN);if(!Double.isFinite(v))throw new IllegalStateException("Missing/nonfinite parameter "+name);return v;}
    private void setValue(String name,double value){ScalarGlobalParameter p=(ScalarGlobalParameter)required(sim.get(GlobalParameterManager.class),P+name,ScalarGlobalParameter.class);requireOwned(p);p.getQuantity().setValue(value);}
    private int integer(String name,int lo,int hi){double v=value(name);if(v!=Math.rint(v)||v<lo||v>hi)throw new IllegalArgumentException(name+" must be integer "+lo+".."+hi);return (int)v;}
    private static void positive(double value,String name){if(!Double.isFinite(value)||value<=0)throw new IllegalArgumentException(name+" must be positive");}
    private Object required(Object manager,String name,Class<?> type){Object r=find(manager,name);if(r==null||!type.isInstance(r))throw new IllegalStateException("Missing/incorrect reference object: "+name);return r;}
    private Object find(Object manager,String name){Object found=null;for(Object o:objects(manager))if(o instanceof NamedObject && ((NamedObject)o).getPresentationName().equals(name)){if(found!=null)throw new IllegalStateException("Ambiguous name "+name);found=o;}return found;}
    private Collection<?> objects(Object manager){return (Collection<?>)call(manager,"getObjects");}
    private void own(NamedObject object){mark(object,OWNER);}
    private void requireOwned(NamedObject object){if(!tagged(object,OWNER))throw new IllegalStateException("Refusing to overwrite unowned object "+object.getPresentationName());}
    private boolean tagged(NamedObject object,String name){Object group=call(object,"getTagGroup");for(Object tag:(Collection<?>)call(group,"getObjects"))if(((NamedObject)tag).getPresentationName().equals(name))return true;return false;}
    private void unmark(NamedObject object,String name){
        List<Tag> tags=new ArrayList<>();for(Object tag:(Collection<?>)call(call(object,"getTagGroup"),"getObjects"))if(!((NamedObject)tag).getPresentationName().equals(name))tags.add((Tag)tag);
        sim.get(TagManager.class).setTags(object,tags);
    }
    private void mark(NamedObject object,String name){
        TagManager manager=sim.get(TagManager.class);Tag tag=(Tag)find(manager,name);if(tag==null)tag=manager.createNewUserTag(name);
        List<Tag> tags=new ArrayList<>();for(Object current:(Collection<?>)call(call(object,"getTagGroup"),"getObjects"))tags.add((Tag)current);
        if(!tags.contains(tag))tags.add(tag);manager.setTags(object,tags);
    }
    private Class<?> loadProperty(String name) {
        for(String pkg:new String[]{"star.material.","star.flow.","star.energy."})try{return Class.forName(pkg+name);}catch(ClassNotFoundException ignored){}
        throw new IllegalStateException("Missing material property API "+name);
    }
    private Dimensions sampleDimensions(String name) {
        if(name.contains("Temperature")||name.contains("DeltaT"))return dim(0,0,0,1);
        if(name.contains("MassFlux"))return dim(1,-2,-1,0);
        if(name.contains("MassFlow")||name.contains("MassResidual"))return dim(1,0,-1,0);
        if(name.contains("Velocity"))return dim(0,1,-1,0);
        if(name.contains("Pressure")||name.contains("WallShear"))return dim(1,-1,-2,0);
        if(name.contains("SensibleEnergy"))return dim(1,2,-2,0);
        if(name.contains("Enthalpy")&&!name.contains("Flow"))return dim(0,2,-2,0);
        if(name.contains("CFL")||name.contains("Reynolds"))return dim();
        return dim(1,2,-3,0);
    }
    private void auditGeometry() {
        double total=reportValue("Volume_All"),parts=reportValue("Sub1_Volume")+reportValue("Sub2_Volume");
        if(!Double.isFinite(total)||!Double.isFinite(parts)||total<=0||Math.abs(parts-total)>1e-6*total)throw new IllegalStateException("Subchannel volumes overlap or do not cover the region");
        if(Math.abs(reportValue("Sub1_CentroidY")-.006720357133367244)>1e-7||Math.abs(reportValue("Sub2_CentroidY")-.013440714266734488)>1e-7)
            throw new IllegalStateException("Reference subchannel orientation/position changed; +Y must point from Sub1 to Sub2");
        if(Math.abs(reportValue("Sub1_Volume")-7.8450223e-6)>1e-4*7.8450223e-6||Math.abs(reportValue("Sub2_Volume")-7.8450223e-6)>1e-4*7.8450223e-6)
            throw new IllegalStateException("Unexpected reference subchannel volume");
        if(Math.abs(reportValue("GapArea")-value("GapWidth")*value("Length"))>1e-5*value("GapWidth")*value("Length"))throw new IllegalStateException("Gap area does not match reference geometry");
    }
    private double reportValue(String name){return ((Report)required(sim.getReportManager(),P+name,Report.class)).getReportMonitorValue();}
    private void ensureContinuation(Path directory) throws IOException {
        int completed=integer("CompletedBlocks",0,1000000);if(completed==0)return;
        Path last=directory.resolve(String.format(Locale.ROOT,"block_%05d.csv",completed));
        String row=null;try(BufferedReader in=Files.newBufferedReader(last,StandardCharsets.UTF_8)){String line;while((line=in.readLine())!=null)row=line;}
        if(row==null||Math.abs(Double.parseDouble(row.split(",")[0])-time())>1e-9)
            throw new IllegalStateException("Time advanced outside statistics blocks; start a NEW series before running more statistics");
    }
    private void pauseFieldMeans() {
        for(Object candidate:objects(sim.getMonitorManager())) if(candidate instanceof FieldMeanMonitor && tagged((NamedObject)candidate,OWNER))
            call(((FieldMeanMonitor)candidate).getStarUpdate(),"setEnabled",false);
    }
    private void enableFieldMeans() {
        if(value("CreateFieldMeans")!=1)return;
        String prefix=P+"Series"+(long)value("SeriesId")+"_Mean_";
        int count=0;
        for(Object candidate:objects(sim.getMonitorManager())) if(candidate instanceof FieldMeanMonitor && ((NamedObject)candidate).getPresentationName().startsWith(prefix)) {
            requireOwned((NamedObject)candidate);call(((FieldMeanMonitor)candidate).getStarUpdate(),"setEnabled",true);count++;
        }
        if(count!=5)throw new IllegalStateException("Incomplete native field means for this series");
    }
    private static Class<?> load(String name){try{return Class.forName(name);}catch(Exception e){throw new IllegalStateException("Missing STAR API class "+name,e);}}
    private static Object call(Object target,String method,Object...args){
        for(Method m:target.getClass().getMethods())if(m.getName().equals(method)&&m.getParameterCount()==args.length){
            Class<?>[] types=m.getParameterTypes();boolean match=true;
            for(int i=0;i<types.length;i++)if(args[i]!=null&&!boxed(types[i]).isInstance(args[i]))match=false;
            if(!match)continue;
            try{return m.invoke(target,args);}catch(Exception e){throw new IllegalStateException(target.getClass().getSimpleName()+"."+method+": "+e.getMessage(),e);}
        }
        throw new IllegalStateException("Unsupported STAR API: "+target.getClass().getName()+"."+method);
    }
    private static Class<?> boxed(Class<?> c){if(c==boolean.class)return Boolean.class;if(c==int.class)return Integer.class;if(c==double.class)return Double.class;return c;}

    static double tmcCoefficient(double heat,double gaps,double area,double cp,double massFlux,double deltaT,double minimumDeltaT) {
        for(double v:new double[]{heat,gaps,area,cp,massFlux,deltaT,minimumDeltaT})if(!Double.isFinite(v)||v<=0)throw new IllegalArgumentException("Invalid TMC input");
        if(deltaT<minimumDeltaT)throw new IllegalArgumentException("Insufficient temperature contrast");
        return heat/(gaps*area*cp*massFlux*deltaT);
    }

    // Pure Java numerical kernel, compiled and executed independently in tests.
    static final class WeightedWindow {
        final List<String> names;final double[] integral,squares,firstValues,lastValues;
        double startTime,lastTime;int count;
        WeightedWindow(List<String> names){this.names=new ArrayList<>(names);int n=names.size();integral=new double[n];squares=new double[n];firstValues=new double[n];lastValues=new double[n];}
        void add(double t,double[] values){
            if(!Double.isFinite(t)||values.length!=names.size())throw new IllegalArgumentException("Invalid sample shape/time");
            for(double v:values)if(!Double.isFinite(v))throw new IllegalArgumentException("Nonfinite sample");
            if(count==0){startTime=t;System.arraycopy(values,0,firstValues,0,values.length);}
            else {
                double dt=t-lastTime;if(dt<=0)throw new IllegalArgumentException("Non-increasing sample time");
                for(int i=0;i<values.length;i++){
                    integral[i]+=.5*(lastValues[i]+values[i])*dt;
                    squares[i]+=.5*(lastValues[i]*lastValues[i]+values[i]*values[i])*dt;
                }
            }
            System.arraycopy(values,0,lastValues,0,values.length);lastTime=t;count++;
        }
        double duration(){double d=lastTime-startTime;if(count<2||d<=0)throw new IllegalStateException("Insufficient statistics");return d;}
        double mean(int i){return integral[i]/duration();}
        double sd(int i){return Math.sqrt(Math.max(0,squares[i]/duration()-mean(i)*mean(i)));}
        int index(String suffix){int i=names.indexOf("TMC_"+suffix);if(i<0)throw new IllegalArgumentException("Missing statistic "+suffix);return i;}
        double mean(String n){return mean(index(n));}double first(String n){return firstValues[index(n)];}double last(String n){return lastValues[index(n)];}
    }
}
