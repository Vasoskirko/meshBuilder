import java.util.*;
class CheckAnalysis {
// HELPERS
    List<String> warnings=new ArrayList<>();
    void warn(Simulation s,String message) { warnings.add(message); }
    Collection<?> objects(Object manager) { return ((Manager)manager).entries.values(); }
    boolean tagged(NamedObject o,String label) { return o.owned; }
    void own(Simulation s,NamedObject o) { o.owned=true; }
    <T extends NamedObject> T findOwned(Simulation s,Object manager,String name,Class<T> type) {
        NamedObject o=((Manager)manager).entries.get(name);
        if (o!=null && !o.owned) throw new IllegalStateException("user collision");
        return o==null ? null : type.cast(o);
    }
    <T extends Report> T ownedReport(Simulation s,String name,Class<T> type) {
        T r=findOwned(s,s.reports,name,type);
        if (r==null) { r=s.reports.create(type);r.name=name;r.owned=true;s.reports.entries.put(name,r); }
        return r;
    }
    UserFieldFunction getOrCreateFF(Simulation s,String name,String definition) {
        UserFieldFunction ff=findOwned(s,s.fields,name,UserFieldFunction.class);
        if (ff==null) { ff=new UserFieldFunction();ff.name=name;ff.owned=true;s.fields.entries.put(name,ff); }
        ff.definition=definition;return ff;
    }
    void registerReport(Simulation s,Report r,int[] counts) { counts[0]++; }
    void createMassFlowReport(Simulation s,String n,List<? extends NamedObject> p,int[] c) { ownedReport(s,n,Report.class).parts.setObjects(p);c[0]++; }
    void createHeatReport(Simulation s,String n,List<? extends NamedObject> p,int[] c) { ownedReport(s,n,Report.class).parts.setObjects(p);c[0]++; }
    static class NamedObject {
        String name;boolean owned;
        void setPresentationName(String n) { name=n; }
    }
    static class Manager {
        Map<String,NamedObject> entries=new LinkedHashMap<>();
        <T extends NamedObject> T create(Class<T> type) {
            try { return type.getDeclaredConstructor().newInstance(); }
            catch(Exception e) { throw new IllegalStateException(e); }
        }
    }
    static class FieldFunction extends NamedObject { String getFunctionName() { return name; } }
    static class UserFieldFunction extends FieldFunction {
        String definition;Dimensions dims;
        void setDimensions(Dimensions d) { dims=d; }
    }
    static class FieldManager extends Manager {
        FieldFunction getFunction(String name) { return (FieldFunction)entries.get(name); }
    }
    static class Dimensions {
        static Dimensions Builder() { return new Dimensions(); }
        Dimensions length(int v) { return this; } Dimensions mass(int v) { return this; }
        Dimensions time(int v) { return this; } Dimensions build() { return this; }
    }
    static class Quantity { double value;String units;void setValueAndUnits(double v,String u) { value=v;units=u; } }
    static class ScalarGlobalParameter extends NamedObject {
        Quantity quantity=new Quantity();void setDimensions(Dimensions d) {}
        Quantity getQuantity() { return quantity; }
    }
    static class GlobalParameterManager extends Manager {
        NamedObject createGlobalParameter(Class<ScalarGlobalParameter> c,String type) {
            ScalarGlobalParameter p=new ScalarGlobalParameter() {
                @Override void setPresentationName(String n) { super.setPresentationName(n);entries.put(n,this); }
            };return p;
        }
    }
    static class Parts { List<? extends NamedObject> parts;void setObjects(List<? extends NamedObject> p) { parts=p; } }
    static class Report extends NamedObject {
        Parts parts=new Parts(); FieldFunction field;Dimensions dims;String definition;
        Parts getParts() { return parts; } void setFieldFunction(FieldFunction f) { field=f; }
        void setDimensions(Dimensions d) { dims=d; } void setDefinition(String d) { definition=d; }
    }
    static class ExpressionReport extends Report {}
    static class AreaAverageReport extends Report {}
    static class MassFlowAverageReport extends Report {}
    static class SurfaceIntegralReport extends Report {}
    static class VolumeIntegralReport extends Report {}
    static class PlaneSection extends NamedObject {}
    static class Boundary extends NamedObject {}
    static class BoundaryManager { List<Boundary> getBoundaries() { return List.of(); } }
    static class Region extends NamedObject { BoundaryManager getBoundaryManager() { return new BoundaryManager(); } }
    static class StarUpdateModeOption {
        enum Type { EVENT } Type selected;void setSelected(Type t) { selected=t; }
    }
    static class EventUpdate { FrequencyMonitorUpdateEvent event; void setUpdateEvent(FrequencyMonitorUpdateEvent e) { event=e; } }
    static class StarUpdate {
        StarUpdateModeOption mode=new StarUpdateModeOption();EventUpdate event=new EventUpdate();
        StarUpdateModeOption getUpdateModeOption() { return mode; } EventUpdate getEventUpdateFrequency() { return event; }
    }
    static class FieldMeanMonitor extends NamedObject {
        FieldFunction field;List<NamedObject> parts;StarUpdate update=new StarUpdate();
        void setObjects(ArrayList<NamedObject> p) { parts=p; } void setFieldFunction(FieldFunction f) { field=f; }
        StarUpdate getStarUpdate() { return update; }
    }
    static class PhysicalTimeMonitor extends NamedObject {}
    static class FrequencyMonitorUpdateEvent extends NamedObject {
        PhysicalTimeMonitor monitor;int frequency,start;
        void setMonitor(PhysicalTimeMonitor m) { monitor=m; } void setSampleFrequency(int f) { frequency=f; } void setStartCount(int s) { start=s; }
    }
    static class MonitorManager extends Manager {
        FieldMeanMonitor createMonitor(Class<FieldMeanMonitor> c) {
            return new FieldMeanMonitor() {
                @Override void setPresentationName(String n) { super.setPresentationName(n);entries.put(n,this); }
            };
        }
    }
    static class EventManager extends Manager {
        FrequencyMonitorUpdateEvent createUpdateEvent(Class<FrequencyMonitorUpdateEvent> c) {
            return new FrequencyMonitorUpdateEvent() {
                @Override void setPresentationName(String n) { super.setPresentationName(n);entries.put(n,this); }
            };
        }
    }
    static class ImplicitUnsteadySolver {}
    static class SolverManager { boolean unsteady=true;Object getSolver(Class<ImplicitUnsteadySolver> c) { return unsteady?new Object():null; } }
    static class UnitsManager { String getObject(String s) { return s; } }
    static class Simulation {
        Manager reports=new Manager();FieldManager fields=new FieldManager();MonitorManager monitors=new MonitorManager();
        GlobalParameterManager parameters=new GlobalParameterManager();EventManager events=new EventManager();SolverManager solvers=new SolverManager();
        Manager getReportManager() { return reports; } FieldManager getFieldFunctionManager() { return fields; }
        MonitorManager getMonitorManager() { return monitors; } EventManager getUpdateEventManager() { return events; }
        SolverManager getSolverManager() { return solvers; } UnitsManager getUnitsManager() { return new UnitsManager(); }
        <T> T get(Class<T> c) { return c.cast(parameters); } void println(String s) {}
    }
    static void require(boolean condition,String message) { if(!condition) throw new AssertionError(message); }
    public static void main(String[] args) {
        CheckAnalysis c=new CheckAnalysis();Simulation s=new Simulation();
        for(String key:List.of("Density","DynamicViscosity","Pressure","Temperature","BoundaryHeatFlux","WallShearStress","Velocity")) {
            FieldFunction field=new FieldFunction();field.name=key;s.fields.entries.put(key,field);
        }
        PlaneSection in=new PlaneSection(),out=new PlaneSection();Region region=new Region();Boundary wall=new Boundary();
        List<String> options=List.of("geometry","hydraulics","wall","thermal");int[] counts={0,0};
        c.createSubchannelAnalysis(s,2,List.of(region),List.of(wall),in,out,.05,options,true,counts);
        require(c.warnings.isEmpty(),c.warnings.toString());
        require(s.reports.entries.get("Sub2_Volume") instanceof VolumeIntegralReport,"volume report type");
        require(((Report)s.reports.entries.get("Sub2_RodArea")).parts.parts.equals(List.of(wall)),"source wall scope");
        Report density=(Report)s.reports.entries.get("Sub2_Density_In");
        require(density.field==s.fields.getFunction("Density") && density.parts.parts.equals(List.of(in)),"native density on inlet");
        Report viscosity=(Report)s.reports.entries.get("Sub2_Viscosity_In");
        require(viscosity.field==s.fields.getFunction("DynamicViscosity"),"native viscosity");
        Report temp=(Report)s.reports.entries.get("Sub2_BulkTemperature_In");
        require(temp instanceof MassFlowAverageReport && temp.field==s.fields.getFunction("Temperature"),"bulk temperature weighting");
        String re=((Report)s.reports.entries.get("Sub2_Reynolds_In")).definition;
        require(re.equals("abs(${Sub2_MassFlow_InReport}) * ${Sub2_HydraulicDiameterReport} / (${Sub2_Area_InReport} * ${Sub2_Viscosity_InReport})"),re);
        int n=s.reports.entries.size();
        c.createSubchannelAnalysis(s,2,List.of(region),List.of(wall),in,out,.05,options,true,counts);
        require(s.reports.entries.size()==n,"duplicate reports on rerun");
        ScalarGlobalParameter height=(ScalarGlobalParameter)s.parameters.entries.get("ExportHeight");
        require(height.quantity.value==.05 && height.quantity.units.equals("m"),"height must carry SI units");
        c.derivedReport(s,"MissingDependency","${DoesNotExistReport}",Dimensions.Builder(),counts);
        require(!s.reports.entries.containsKey("MissingDependency"),"invalid expression dependency accepted");
        PhysicalTimeMonitor clock=new PhysicalTimeMonitor();s.monitors.entries.put("clock",clock);
        c.createTimeMean(s,List.of(region),"Velocity",25);
        FieldMeanMonitor mean=(FieldMeanMonitor)s.monitors.entries.get("MB_TimeMean_Velocity");
        require(mean!=null && mean.field==s.fields.getFunction("Velocity") && mean.parts.equals(List.of(region)),"mean source");
        FrequencyMonitorUpdateEvent event=mean.update.event.event;
        require(event.monitor==clock && event.frequency==1 && event.start==25,"time step scheduling");
        c.createTimeMean(s,List.of(region),"Velocity",100);
        require(s.monitors.entries.get("MB_TimeMean_Velocity")==mean && event.start==25,"rerun changed existing statistics");
        require(s.events.entries.size()==1,"duplicate events");
        s.solvers.unsteady=false;c.createTimeMean(s,List.of(region),"Pressure",1);
        require(!s.monitors.entries.containsKey("MB_TimeMean_Pressure"),"mean created for steady solver");
        // Failure of one field must not claim a valid Reynolds report.
        Simulation missing=new Simulation();missing.fields.entries.putAll(s.fields.entries);missing.fields.entries.remove("DynamicViscosity");
        c.createSubchannelAnalysis(missing,1,List.of(region),List.of(wall),in,out,.05,List.of("hydraulics"),false,counts);
        require(!missing.reports.entries.containsKey("Sub1_Reynolds_In"),"Re created with missing viscosity");
    }
}
