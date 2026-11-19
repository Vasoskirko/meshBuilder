import java.util.*;
class CheckAudit {
// HELPERS
    static class NamedObject { String name;boolean owned=true;String getPresentationName() { return name; } }
    static class Parts {
        List<NamedObject> parts=new ArrayList<>();Collection<NamedObject> getObjects() { return parts; }
        void setObjects(Collection<NamedObject> p) { parts=new ArrayList<>(p); }
    }
    static class Surface extends NamedObject { double mass;Surface(double m) { mass=m; } }
    static class Report extends NamedObject {
        int calls;double value;
        double getReportMonitorValue() { calls++;return value; }
    }
    static class ExpressionReport extends Report { String definition;String getDefinition() { return definition; } }
    // STAR 2602: base Report (and ExpressionReport) have no getParts().
    static class ScopedReport extends Report {
        Parts parts=new Parts();Parts getParts() { return parts; }
    }
    static class MassFlowAverageReport extends ScopedReport {}
    static class MassFlowReport extends ScopedReport {
        @Override double getReportMonitorValue() { return ((Surface)parts.parts.get(0)).mass; }
    }
    static class ReportManager {
        Map<String,Report> reports=new HashMap<>();List<Report> temporary=new ArrayList<>();
        <T extends Report> T createReport(Class<T> type) {
            try { T r=type.getDeclaredConstructor().newInstance();temporary.add(r);return r; }
            catch(Exception e) { throw new IllegalStateException(e); }
        }
        void remove(Report r) { temporary.remove(r); }
    }
    static class Simulation { ReportManager manager=new ReportManager();ReportManager getReportManager() { return manager; } }
    <T extends Report> T findOwned(Simulation s,ReportManager manager,String name,Class<T> c) {
        Report r=manager.reports.get(name);
        if(r!=null&&!r.owned)throw new IllegalStateException("Unowned dependency");return r==null?null:c.cast(r);
    }
    static void require(boolean b,String message) { if(!b)throw new AssertionError(message); }
    static ExpressionReport expression(Simulation s,String name,String definition) {
        ExpressionReport r=new ExpressionReport();r.name=name;r.definition=definition;r.value=123;s.manager.reports.put(name,r);return r;
    }
    public static void main(String[] args) {
        CheckAudit c=new CheckAudit();Simulation s=new Simulation();
        Map<String,Double> values=new HashMap<>();Map<String,String> blocked=new HashMap<>();
        MassFlowAverageReport average=new MassFlowAverageReport();average.name="TotalEnthalpy_Inlet";average.value=Double.NaN;
        average.parts.setObjects(List.of(new Surface(0)));s.manager.reports.put(average.name,average);
        ExpressionReport energy=expression(s,"Energy_Flow_Inlet_Total","${TotalEnthalpy_InletReport} * 2");
        ExpressionReport imbalance=expression(s,"Imbalance_Energy","${Energy_Flow_Inlet_TotalReport}");
        try { c.auditReportValue(s,imbalance,values,blocked,new HashSet<>());throw new AssertionError("zero flow accepted"); }
        catch(IllegalStateException expected) {}
        require(average.calls==0 && energy.calls==0 && imbalance.calls==0,"undefined average/expression was evaluated");
        require(s.manager.temporary.isEmpty(),"temporary mass report leaked");
        values.clear();blocked.clear();average.parts.setObjects(List.of(new Surface(-.15)));average.value=1000;
        require(c.auditReportValue(s,imbalance,values,blocked,new HashSet<>())==123,"valid graph failed");
        c.auditReportValue(s,energy,values,blocked,new HashSet<>());
        require(average.calls==1 && energy.calls==1,"dependencies evaluated repeatedly");
        Report heat=new Report();heat.name="Heat_Flux_Walls_Total";heat.value=Double.NaN;s.manager.reports.put(heat.name,heat);
        ExpressionReport thermal=expression(s,"Thermal","${Heat_Flux_Walls_TotalReport}");
        try { c.auditReportValue(s,thermal,values,blocked,new HashSet<>());throw new AssertionError("nonfinite heat accepted"); }
        catch(IllegalStateException expected) {}
        require(thermal.calls==0,"expression invoked after nonfinite dependency");
        ExpressionReport a=expression(s,"A","${BReport}"), b=expression(s,"B","${AReport}");
        try { c.auditReportValue(s,a,values,blocked,new HashSet<>());throw new AssertionError("cycle accepted"); }
        catch(IllegalStateException expected) {}
        require(a.calls==0&&b.calls==0,"cyclic native expressions invoked");
        require(c.auditDeferral("Sub1_Area_In",false,false,false)==null,"mesh report deferred");
        require(c.auditDeferral("Imbalance_Energy",false,true,true)!=null,"default physical evaluation allowed");
        require(c.auditDeferral("Imbalance_Energy",true,true,false)!=null,"initialized-only data treated as solved");
        require(c.auditDeferral("Imbalance_Energy",true,false,true)!=null,"cleared fields treated as initialized");
        require(c.auditDeferral("Sub1_PressureDrop",true,true,true)==null,"explicit solved evaluation blocked");
    }
}
