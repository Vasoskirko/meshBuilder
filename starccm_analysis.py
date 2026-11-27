"""Native STAR helpers for selected subchannel diagnostics and transient sampling."""
ANALYSIS_SUPPORT = r'''
    private void exportHeight(Simulation sim, double length) {
        if (!Double.isFinite(length) || length<=0) throw new IllegalArgumentException("Invalid export height");
        GlobalParameterManager manager=sim.get(GlobalParameterManager.class);
        ScalarGlobalParameter height=findOwned(sim,manager,"ExportHeight",ScalarGlobalParameter.class);
        if (height==null) {
            height=(ScalarGlobalParameter)manager.createGlobalParameter(ScalarGlobalParameter.class,"Scalar");
            height.setPresentationName("ExportHeight"); own(sim,height);
        }
        height.setDimensions(Dimensions.Builder().length(1).build());
        height.getQuantity().setValueAndUnits(length,sim.getUnitsManager().getObject("m"));
    }
    private List<Boundary> rodBoundaries(Region region) {
        List<Boundary> result=new ArrayList<>();
        for (Boundary b : region.getBoundaryManager().getBoundaries())
            if (tagged(b,"meshBuilder.Role.Rod")) result.add(b);
        return result;
    }
    private FieldFunction analysisField(Simulation sim, String key) {
        FieldFunction ff=sim.getFieldFunctionManager().getFunction(key);
        if (ff==null) throw new IllegalStateException("Missing solution field " + key);
        return ff;
    }
    private void scalarReport(Simulation sim, String kind, String name, List<? extends NamedObject> parts,
            FieldFunction field, int[] counts) {
        try {
            if (parts.isEmpty()) throw new IllegalStateException("No input parts");
            if (kind.equals("area")) {
                AreaAverageReport r=ownedReport(sim,name,AreaAverageReport.class);
                r.setFieldFunction(field); r.getParts().setQuery(null); r.getParts().setObjects(parts); registerReport(sim,r,counts);
            } else if (kind.equals("massflow")) {
                MassFlowAverageReport r=ownedReport(sim,name,MassFlowAverageReport.class);
                r.setFieldFunction(field); r.getParts().setQuery(null); r.getParts().setObjects(parts); registerReport(sim,r,counts);
            } else if (kind.equals("surface")) {
                SurfaceIntegralReport r=ownedReport(sim,name,SurfaceIntegralReport.class);
                r.setFieldFunction(field); r.getParts().setQuery(null); r.getParts().setObjects(parts); registerReport(sim,r,counts);
            } else if (kind.equals("volume")) {
                VolumeIntegralReport r=ownedReport(sim,name,VolumeIntegralReport.class);
                r.setFieldFunction(field); r.getParts().setQuery(null); r.getParts().setObjects(parts); registerReport(sim,r,counts);
            } else throw new IllegalArgumentException("Unknown report kind " + kind);
        } catch (Exception e) { warn(sim,"  [!] Report " + name + ": " + e.getMessage()); }
    }
    private void derivedReport(Simulation sim, String name, String expression, Dimensions dims, int[] counts) {
        try {
            java.util.regex.Matcher refs=java.util.regex.Pattern.compile("\\$\\{([^}]+)Report\\}").matcher(expression);
            while (refs.find()) if (findOwned(sim,sim.getReportManager(),refs.group(1),Report.class)==null)
                throw new IllegalStateException("Missing managed dependency " + refs.group(1));
            ExpressionReport r=ownedReport(sim,name,ExpressionReport.class);
            r.setDimensions(dims); r.setDefinition(expression); registerReport(sim,r,counts);
        } catch (Exception e) { warn(sim,"  [!] Report " + name + ": " + e.getMessage()); }
    }
    private String reportRef(String name) { return "${" + name + "Report}"; }
    private void createSubchannelAnalysis(Simulation sim, int number, List<? extends NamedObject> domain,
            List<? extends NamedObject> walls, NamedObject inlet, NamedObject outlet, double length,
            List<String> choices, boolean thermal, int[] counts) {
        String prefix="Sub"+number+"_";
        List<NamedObject> in=Collections.singletonList(inlet), out=Collections.singletonList(outlet);
        Dimensions dimless=Dimensions.Builder().build(), len=Dimensions.Builder().length(1).build();
        Dimensions pressure=Dimensions.Builder().mass(1).length(-1).time(-2).build();
        FieldFunction one=getOrCreateFF(sim,"MB_One","1.0");
        // Geometry and hydraulic dependencies are explicit; no exported constant rho/mu is used.
        try {
            scalarReport(sim,"surface",prefix+"Area_In",in,one,counts);
            scalarReport(sim,"surface",prefix+"Area_Out",out,one,counts);
            scalarReport(sim,"volume",prefix+"Volume",domain,one,counts);
            scalarReport(sim,"surface",prefix+"RodArea",walls,one,counts);
            exportHeight(sim,length);
            derivedReport(sim,prefix+"WettedPerimeter",reportRef(prefix+"RodArea")+" / ${ExportHeight}",len,counts);
            derivedReport(sim,prefix+"HydraulicDiameter","4 * "+reportRef(prefix+"Area_In")+" / "+reportRef(prefix+"WettedPerimeter"),len,counts);
        } catch (Exception e) { warn(sim,"  [!] Subchannel geometry " + number + ": " + e.getMessage()); }
        if (choices.contains("hydraulics") || choices.contains("wall")) try {
            createMassFlowReport(sim,prefix+"MassFlow_In",in,counts);
            createMassFlowReport(sim,prefix+"MassFlow_Out",out,counts);
            scalarReport(sim,"area",prefix+"Density_In",in,analysisField(sim,"Density"),counts);
            scalarReport(sim,"area",prefix+"Viscosity_In",in,analysisField(sim,"DynamicViscosity"),counts);
            scalarReport(sim,"area",prefix+"Density_Out",out,analysisField(sim,"Density"),counts);
            scalarReport(sim,"area",prefix+"Viscosity_Out",out,analysisField(sim,"DynamicViscosity"),counts);
            UserFieldFunction axial=getOrCreateFF(sim,"Velocity_k","$${Velocity}[2]");
            axial.setDimensions(Dimensions.Builder().length(1).time(-1).build());
            scalarReport(sim,"area",prefix+"BulkAxialVelocity_In",in,axial,counts);
            scalarReport(sim,"area",prefix+"BulkAxialVelocity_Out",out,axial,counts);
            scalarReport(sim,"area",prefix+"Pressure_In",in,analysisField(sim,"Pressure"),counts);
            scalarReport(sim,"area",prefix+"Pressure_Out",out,analysisField(sim,"Pressure"),counts);
            derivedReport(sim,prefix+"PressureDrop",reportRef(prefix+"Pressure_In")+" - "+reportRef(prefix+"Pressure_Out"),pressure,counts);
            derivedReport(sim,prefix+"Reynolds_In","abs("+reportRef(prefix+"MassFlow_In")+") * "+reportRef(prefix+"HydraulicDiameter")+
                " / ("+reportRef(prefix+"Area_In")+" * "+reportRef(prefix+"Viscosity_In")+")",dimless,counts);
            derivedReport(sim,prefix+"Reynolds_Out","abs("+reportRef(prefix+"MassFlow_Out")+") * "+reportRef(prefix+"HydraulicDiameter")+
                " / ("+reportRef(prefix+"Area_Out")+" * "+reportRef(prefix+"Viscosity_Out")+")",dimless,counts);
            UserFieldFunction localRe=getOrCreateFF(sim,"MB_Reynolds_Sub"+number,
                "${Density} * mag($$Velocity) * "+reportRef(prefix+"HydraulicDiameter")+" / ${DynamicViscosity}");
            localRe.setDimensions(dimless);
            derivedReport(sim,prefix+"DynamicPressure_In","0.5 * "+reportRef(prefix+"Density_In")+" * pow("+reportRef(prefix+"BulkAxialVelocity_In")+", 2)",pressure,counts);
        } catch (Exception e) { warn(sim,"  [!] Subchannel hydraulics " + number + ": " + e.getMessage()); }
        if (choices.contains("wall")) try {
            FieldFunction shear=analysisField(sim,"WallShearStress");
            UserFieldFunction magnitude=getOrCreateFF(sim,"MB_WallShearMagnitude","mag($$"+shear.getFunctionName()+")");
            magnitude.setDimensions(pressure);
            scalarReport(sim,"area",prefix+"WallShearMean",walls,magnitude,counts);
            derivedReport(sim,prefix+"Cf_Wall",reportRef(prefix+"WallShearMean")+" / "+reportRef(prefix+"DynamicPressure_In"),dimless,counts);
            derivedReport(sim,prefix+"Darcy_Wall","4 * "+reportRef(prefix+"Cf_Wall"),dimless,counts);
        } catch (Exception e) { warn(sim,"  [!] Subchannel wall friction " + number + ": " + e.getMessage()); }
        if (choices.contains("thermal") && thermal) try {
            FieldFunction temperature=analysisField(sim,"Temperature");
            scalarReport(sim,"massflow",prefix+"BulkTemperature_In",in,temperature,counts);
            scalarReport(sim,"massflow",prefix+"BulkTemperature_Out",out,temperature,counts);
            scalarReport(sim,"area",prefix+"WallTemperature",walls,temperature,counts);
            scalarReport(sim,"area",prefix+"WallHeatFluxMean",walls,analysisField(sim,"BoundaryHeatFlux"),counts);
            createHeatReport(sim,prefix+"RodHeatPower",walls,counts);
        } catch (Exception e) { warn(sim,"  [!] Subchannel thermal " + number + ": " + e.getMessage()); }
        if (choices.contains("thermal") && !thermal) warn(sim,"  [!] Thermal reports require energy: Sub"+number);
    }
    private void createTimeMean(Simulation sim, List<? extends NamedObject> parts, String fieldName, int start) {
        String name="MB_TimeMean_"+fieldName;
        try {
            if (sim.getSolverManager().getSolver(ImplicitUnsteadySolver.class)==null)
                throw new IllegalStateException("Field means require an implicit unsteady solver");
            FieldFunction field=analysisField(sim,fieldName);
            FieldMeanMonitor monitor=findOwned(sim,sim.getMonitorManager(),name,FieldMeanMonitor.class);
            if (monitor!=null) {
                sim.println("  • Preserve accumulated field statistics: "+name.substring(3)); return;
            }
            PhysicalTimeMonitor clock=null;
            for (Object candidate : objects(sim.getMonitorManager()))
                if (candidate instanceof PhysicalTimeMonitor) { clock=(PhysicalTimeMonitor)candidate; break; }
            if (clock==null) throw new IllegalStateException("Physical time monitor unavailable");
            String eventName=name+"_Steps";
            FrequencyMonitorUpdateEvent event=findOwned(sim,sim.getUpdateEventManager(),eventName,FrequencyMonitorUpdateEvent.class);
            if (event==null) {
                event=sim.getUpdateEventManager().createUpdateEvent(FrequencyMonitorUpdateEvent.class);
                event.setPresentationName(eventName); own(sim,event);
            }
            event.setMonitor(clock); event.setSampleFrequency(1); event.setStartCount(start);
            monitor=sim.getMonitorManager().createMonitor(FieldMeanMonitor.class);
            monitor.setPresentationName(name); own(sim,monitor);
            monitor.setObjects(new ArrayList<NamedObject>(parts)); monitor.setFieldFunction(field);
            monitor.getStarUpdate().getUpdateModeOption().setSelected(StarUpdateModeOption.Type.EVENT);
            monitor.getStarUpdate().getEventUpdateFrequency().setUpdateEvent(event);
            sim.println("  • Field mean "+name.substring(3)+": one sample per time step, constant dt required, start="+start);
        } catch (Exception e) { warn(sim,"  [!] Field mean " + name + ": " + e.getMessage()); }
    }
'''
