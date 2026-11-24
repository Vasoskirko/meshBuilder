"""Minimal compile contracts only. These are NOT a Siemens SDK or runtime."""
from pathlib import Path

def write_stubs(root):
    common={
    'NamedObject':'public String getPresentationName(){return "";} public void setPresentationName(String s){}',
    'StarMacro':'public void execute(){} public Simulation getActiveSimulation(){return null;}',
    'Simulation':'''public void println(String s){} public <T>T get(Class<T> c){return null;}
    public RegionManager getRegionManager(){return null;} public PartManager getPartManager(){return null;}
    public FieldFunctionManager getFieldFunctionManager(){return null;} public ReportManager getReportManager(){return null;}
    public MonitorManager getMonitorManager(){return null;} public SolverManager getSolverManager(){return null;}
    public InterfaceManager getInterfaceManager(){return null;} public UpdateEventManager getUpdateEventManager(){return null;}
    public UnitsManager getUnitsManager(){return null;} public IteratorApi getSimulationIterator(){return null;}
    public Object getSolution(){return null;} public String getSessionDir(){return ".";}''',
    'RegionManager':'', 'PartManager':'',
    'Dimensions':'public static Builder Builder(){return new Builder();} public static class Builder {public Builder mass(int n){return this;} public Builder length(int n){return this;} public Builder time(int n){return this;} public Builder temperature(int n){return this;} public Dimensions build(){return null;}}',
    'Quantity':'public void setDefinition(String s){} public void setValue(double d){} public void setValueAndUnits(double d,Units u){}',
    'Units':'','UnitsManager':'public Units getObject(String s){return null;}',
    'ScalarGlobalParameter':'public void setDimensions(Dimensions d){} public Quantity getQuantity(){return null;}',
    'GlobalParameterManager':'public <T>T createGlobalParameter(Class<T> c,String s){return null;}',
    'ModelValues':'public <T>T get(Class<T> c){return null;}',
    'Region':'public BoundaryManager getBoundaryManager(){return null;} public ModelValues getConditions(){return null;} public ModelValues getValues(){return null;}',
    'BoundaryManager':'',
    'Boundary':'public ModelValues getConditions(){return null;} public ModelValues getValues(){return null;}',
    'BoundaryInterface':'public ModelValues getConditions(){return null;} public ModelValues getValues(){return null;} public Topology getTopology(){return null;} public void setInterfaceType(star.flow.FullyDevelopedInterface o){}',
    'Topology':'public void setSelected(InterfaceConfigurationOption.Type t){}',
    'InterfaceConfigurationOption':'public enum Type {PERIODIC}',
    'InterfaceManager':'public BoundaryInterface createBoundaryInterface(Boundary a,Boundary b,String s){return null;}',
    'ConditionTypeManager':'public <T>T get(Class<T> c){return null;}',
    'FieldFunction':'public String getFunctionName(){return "";}',
    'UserFieldFunction':'public FieldFunctionTypeOption getTypeOption(){return null;} public void setFunctionName(String s){} public void setDimensions(Dimensions d){} public void setDefinition(String s){} public String getDefinition(){return "";}',
    'FieldFunctionTypeOption':'public enum Type{SCALAR} public void setSelected(Type t){}',
    'FieldFunctionManager':'public FieldFunction getFunction(String s){return null;} public UserFieldFunction createFieldFunction(){return null;}',
    'ReportManager':'public <T extends star.base.report.Report>T createReport(Class<T> c){return null;}',
    'Parts':'public void setObjects(Object... o){}',
    'Monitor':'public StarUpdate getStarUpdate(){return null;}',
    'PhysicalTimeMonitor':'',
    'ReportMonitor':'public star.base.report.Report getReport(){return null;}',
    'MonitorManager':'public <T>T createMonitor(Class<T> c){return null;} public void remove(Object o){}',
    'FieldMeanMonitor':'public void setObjects(java.util.List<NamedObject> l){} public void setFieldFunction(FieldFunction f){}',
    'FrequencyMonitorUpdateEvent':'public void setMonitor(PhysicalTimeMonitor m){} public void setSampleFrequency(int n){} public void setStartCount(int n){}',
    'UpdateEventManager':'public <T>T createUpdateEvent(Class<T> c){return null;}',
    'StarUpdate':'public UpdateOption getUpdateModeOption(){return null;} public EventFrequency getEventUpdateFrequency(){return null;}',
    'UpdateOption':'public void setSelected(StarUpdateModeOption.Type t){}',
    'StarUpdateModeOption':'public enum Type{EVENT}',
    'EventFrequency':'public void setUpdateEvent(FrequencyMonitorUpdateEvent e){}',
    'SolverManager':'public <T>T getSolver(Class<T> c){return null;}',
    'ImplicitUnsteadySolver':'public Quantity getTimeStep(){return null;}',
    'IteratorApi':'public void step(int n){}',
    'ConstantScalarProfileMethod':'public Quantity getQuantity(){return null;}',
    'Tag':'','TagManager':'public Tag createNewUserTag(String n){return null;} public void setTags(NamedObject o,java.util.List<Tag> l){}',
    }
    extends={n:'NamedObject' for n in common if n not in ('NamedObject','StarMacro','Dimensions')}
    for n in ('PhysicalTimeMonitor','ReportMonitor','FieldMeanMonitor'):extends[n]='Monitor'
    extends['UserFieldFunction']='FieldFunction'
    def put(pkg,name,body,base=None):
        path=Path(root)/pkg.replace('.','/');path.mkdir(parents=True,exist_ok=True)
        (path/(name+'.java')).write_text('package '+pkg+';\npublic class '+name+(' extends '+base if base else '')+' {\n'+body+'\n}\n')
    for n,body in common.items():put('star.common',n,body,extends.get(n))
    put('star.base.report','Report','public double getReportMonitorValue(){return 0;} public star.common.ReportMonitor createMonitor(){return null;}','star.common.NamedObject')
    for n in ('SurfaceIntegralReport','VolumeIntegralReport','VolumeAverageReport','AreaAverageReport','MassFlowAverageReport','MaxReport'):
        put('star.base.report',n,'public void setFieldFunction(star.common.FieldFunction f){} public star.common.Parts getParts(){return null;}','Report')
    put('star.base.report','ExpressionReport','public void setDimensions(star.common.Dimensions d){} public void setDefinition(String s){} public String getDefinition(){return "";}','Report')
    put('star.energy','HeatTransferReport','public star.common.Parts getParts(){return null;}','star.base.report.Report')
    for n,types in [('WallThermalOption','HEAT_FLUX'),('EnergyUserVolumeSourceOption','VOLUMETRIC_HEAT_SOURCE')]:
        put('star.energy',n,'public enum Type{'+types+'} public void setSelected(Type t){}')
    for n in ('HeatFluxProfile','VolumetricHeatSourceProfile'):
        put('star.energy',n,'public void setMethod(Class<?> c){} public <T>T getMethod(Class<T> c){return null;}')
    put('star.flow','FullyDevelopedInterface','')
    put('star.flow','FullyDevelopedFlowOption','public enum Type{MASS_FLOW_RATE} public void setSelected(Type t){}')
    put('star.flow','FullyDevelopedMassFlowRate','public star.common.Quantity getFullyDevelopedMassFlowRate(){return null;}')
    put('star.segregatedflow','PackageMarker','')
