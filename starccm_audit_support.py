"""Guarded, dependency-aware optional evaluation of solution reports."""
AUDIT_SUPPORT = r'''
    private String auditDeferral(String name, boolean requested, boolean initialized, boolean progressed) {
        if (meshOnlyReport(name)) return null;
        if (!requested) return "physical evaluation disabled";
        if (!initialized) return "solution not initialized";
        if (!progressed) return "no solver iterations yet";
        return null;
    }
    private double auditReportValue(Simulation sim, Report report, Map<String,Double> values,
            Map<String,String> blocked, Set<String> visiting) {
        String name=report.getPresentationName();
        if (values.containsKey(name)) return values.get(name);
        if (blocked.containsKey(name)) throw new IllegalStateException(blocked.get(name));
        if (!visiting.add(name)) throw new IllegalStateException("Cyclic report dependency: " + name);
        try {
            if (report instanceof ExpressionReport) {
                String definition=((ExpressionReport)report).getDefinition();
                java.util.regex.Matcher refs=java.util.regex.Pattern.compile("\\$\\{([^}]+)Report\\}").matcher(definition);
                while (refs.find()) {
                    Report dependency=findOwned(sim,sim.getReportManager(),refs.group(1),Report.class);
                    if (dependency==null) throw new IllegalStateException("Missing dependency " + refs.group(1));
                    auditReportValue(sim,dependency,values,blocked,visiting);
                }
            }
            if (report instanceof MassFlowAverageReport) {
                // A zero-flow boundary/section has no defined mass-flow average.
                MassFlowReport flow=sim.getReportManager().createReport(MassFlowReport.class);
                try {
                    flow.getParts().setObjects(report.getParts().getObjects());
                    double mass=flow.getReportMonitorValue();
                    if (!Double.isFinite(mass) || Math.abs(mass)<=1e-30)
                        throw new IllegalStateException("Zero/unavailable net mass flow; average undefined");
                } finally { sim.getReportManager().remove(flow); }
            }
            double value=report.getReportMonitorValue();
            if (!Double.isFinite(value)) throw new IllegalStateException("Field/report value not available or finite");
            values.put(name,value);return value;
        } catch (Exception e) {
            String reason=e.getMessage()==null?e.getClass().getSimpleName():e.getMessage();
            blocked.put(name,reason);throw new IllegalStateException(reason,e);
        } finally { visiting.remove(name); }
    }
'''
