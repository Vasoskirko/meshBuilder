import java.util.*;
class CheckPhysics {
// HELPERS
    List<String> warnings=new ArrayList<>();
    void warn(Simulation s,String message) { warnings.add(message); }
    <T> T findOwned(Simulation s,GlobalParameterManager m,String name,Class<T> type) {
        Object value=m.parameters.get(name);return value==null?null:type.cast(value);
    }
    static class ScalarGlobalParameter {}
    static class GlobalParameterManager { Map<String,Object> parameters=new HashMap<>(); }
    static class Quantity { String definition;void setDefinition(String d) { definition=d; } }
    static class MaterialPropertyMethod {}
    static class VariableWaterMethod extends MaterialPropertyMethod {}
    static class ConstantMaterialPropertyMethod extends MaterialPropertyMethod { Quantity quantity=new Quantity();Quantity getQuantity() { return quantity; } }
    static class ConstantSpecificHeat extends MaterialPropertyMethod { Quantity quantity=new Quantity();Quantity getQuantity() { return quantity; } }
    static class MaterialProperty {
        MaterialPropertyMethod method=new ConstantMaterialPropertyMethod();int writes;
        Quantity methodQuantity() { return method instanceof ConstantSpecificHeat ? ((ConstantSpecificHeat)method).quantity : ((ConstantMaterialPropertyMethod)method).quantity; }
        void setMethod(Class<?> c) {
            if(this instanceof SpecificHeatProperty && c!=ConstantSpecificHeat.class)
                throw new IllegalArgumentException("MaterialPropertyMethod not found in SpecificHeatProperty");
            try { method=(MaterialPropertyMethod)c.getDeclaredConstructor().newInstance();writes++; }
            catch(Exception e) { throw new IllegalStateException(e); }
        } MaterialPropertyMethod getMethod() { return method; }
    }
    static class ConstantDensityProperty extends MaterialProperty {}
    static class DynamicViscosityProperty extends MaterialProperty {}
    static class SpecificHeatProperty extends MaterialProperty { SpecificHeatProperty() { method=new ConstantSpecificHeat(); } }
    static class ThermalConductivityProperty extends MaterialProperty {}
    static class Properties {
        Map<Class<?>,MaterialProperty> properties=new HashMap<>();
        MaterialProperty getMaterialProperty(Class<? extends MaterialProperty> c) {
            return properties.computeIfAbsent(c,key->{
                try { return (MaterialProperty)key.getDeclaredConstructor().newInstance(); }
                catch(Exception e) { throw new IllegalStateException(e); }
            });
        }
    }
    static class Material { Properties properties=new Properties();Properties getMaterialProperties() { return properties; } }
    static class SingleComponentLiquidModel { Material material=new Material();Material getMaterial() { return material; } }
    static class Models {
        SingleComponentLiquidModel liquid=new SingleComponentLiquidModel();
        <T> T getModel(Class<T> c) { return c.cast(liquid); }
    }
    static class ReferencePressure extends Quantity {}
    static class ReferenceValues {
        ReferencePressure pressure=new ReferencePressure();<T> T get(Class<T> c) { return c.cast(pressure); }
    }
    static class ConstantScalarProfileMethod { Quantity quantity=new Quantity();Quantity getQuantity() { return quantity; } }
    static class ConstantVectorProfileMethod extends ConstantScalarProfileMethod {}
    static class ScalarProfile {
        ConstantScalarProfileMethod method;
        void setMethod(Class<? extends ConstantScalarProfileMethod> c) {
            try { method=c.getDeclaredConstructor().newInstance(); } catch(Exception e) { throw new IllegalStateException(e); }
        }
        <T> T getMethod(Class<T> c) { return c.cast(method); }
    }
    static class InitialPressureProfile extends ScalarProfile {}
    static class StaticTemperatureProfile extends ScalarProfile {}
    static class VelocityProfile extends ScalarProfile {}
    static class InitialConditions {
        Map<Class<?>,ScalarProfile> profiles=new HashMap<>();
        InitialConditions() {
            profiles.put(InitialPressureProfile.class,new InitialPressureProfile());
            profiles.put(StaticTemperatureProfile.class,new StaticTemperatureProfile());
            profiles.put(VelocityProfile.class,new VelocityProfile());
        }
        <T> T get(Class<T> c) { return c.cast(profiles.get(c)); }
    }
    static class PhysicsContinuum {
        Models models=new Models();ReferenceValues references=new ReferenceValues();InitialConditions initial=new InitialConditions();
        Models getModelManager() { return models; } ReferenceValues getReferenceValues() { return references; }
        InitialConditions getInitialConditions() { return initial; }
    }
    static class Region { PhysicsContinuum physics;void setPhysicsContinuum(PhysicsContinuum p) { physics=p; } }
    static class Solution { int initializationCount;void initializeSolution() { initializationCount++; } }
    static class Simulation {
        GlobalParameterManager parameters=new GlobalParameterManager();Solution solution=new Solution();
        <T> T get(Class<T> c) { return c.cast(parameters); } Solution getSolution() { return solution; }
        void println(String message) {}
    }
    static void require(boolean b,String m) { if(!b) throw new AssertionError(m); }
    public static void main(String[] args) {
        CheckPhysics c=new CheckPhysics();Simulation s=new Simulation();
        for(String name:List.of("rho","dynvis","Cp","lambda","P_ref","T_ref","P_init","T_init","U_init"))
            s.parameters.parameters.put(name,new ScalarGlobalParameter());
        SpecificHeatProperty cpContract=new SpecificHeatProperty();boolean rejected=false;
        try { cpContract.setMethod(ConstantMaterialPropertyMethod.class); } catch(IllegalArgumentException expected) { rejected=true; }
        require(rejected,"SpecificHeatProperty accepted the unsupported generic constant method");
        PhysicsContinuum physics=new PhysicsContinuum();Region region=new Region();
        require(c.configurePhysicalValues(s,physics,List.of(region),false,true),"configuration failed");
        require(region.physics==physics,"continuum not assigned");
        Properties properties=physics.models.liquid.material.properties;
        require(properties.getMaterialProperty(ConstantDensityProperty.class).methodQuantity().definition.equals("${rho}"),"density not linked");
        require(properties.getMaterialProperty(DynamicViscosityProperty.class).methodQuantity().definition.equals("${dynvis}"),"viscosity not linked");
        require(properties.getMaterialProperty(SpecificHeatProperty.class).methodQuantity().definition.equals("${Cp}"),"Cp not linked");
        require(properties.getMaterialProperty(ThermalConductivityProperty.class).methodQuantity().definition.equals("${lambda}"),"conductivity not linked");
        require(properties.getMaterialProperty(SpecificHeatProperty.class).method instanceof ConstantSpecificHeat,"Cp must use ConstantSpecificHeat");
        require(physics.references.pressure.definition.equals("${P_ref}"),"absolute reference pressure");
        require(physics.initial.get(InitialPressureProfile.class).method.quantity.definition.equals("${P_init}"),"gauge initial pressure");
        require(physics.initial.get(StaticTemperatureProfile.class).method.quantity.definition.equals("${T_init}"),"initial temperature");
        require(physics.initial.get(VelocityProfile.class).method.quantity.definition.equals("[0, 0, ${U_init}]"),"initial axial velocity");
        c.initializeFirstSolution(s,false,true,true);require(s.solution.initializationCount==1,"first initialization");
        c.initializeFirstSolution(s,true,true,true);require(s.solution.initializationCount==1,"rerun reset solution");
        c.initializeFirstSolution(s,false,false,true);require(s.solution.initializationCount==1,"disabled initialization ran");
        c.initializeFirstSolution(s,false,true,false);require(s.solution.initializationCount==1,"initialized after setup failure");
        PhysicsContinuum isothermal=new PhysicsContinuum();
        require(c.configurePhysicalValues(s,isothermal,List.of(region),false,false),"isothermal configuration failed");
        require(isothermal.models.liquid.material.properties.getMaterialProperty(SpecificHeatProperty.class).writes==0,"isothermal setup changed Cp");
        PhysicsContinuum iapws=new PhysicsContinuum();
        Properties ip=iapws.models.liquid.material.properties;
        ip.getMaterialProperty(DynamicViscosityProperty.class).method=new VariableWaterMethod();
        ip.getMaterialProperty(ThermalConductivityProperty.class).method=new VariableWaterMethod();
        require(c.configurePhysicalValues(s,iapws,List.of(region),true,true),"iapws initial values failed");
        require(ip.getMaterialProperty(DynamicViscosityProperty.class).writes==0,"IAPWS overwritten with constants");
        require(!c.configurePhysicalValues(s,new PhysicsContinuum(),List.of(region),true,true),"IAPWS accepted default constant transport");
        require(ip.getMaterialProperty(SpecificHeatProperty.class).writes==0,"IAPWS EOS Cp was overwritten");
        s.parameters.parameters.remove("dynvis");
        require(!c.configurePhysicalValues(s,new PhysicsContinuum(),List.of(region),false,true),"missing dependency accepted");
        require(c.meshOnlyReport("Sub2_Volume") && c.meshOnlyReport("Quality_Min_CellQuality"),"geometry report deferred");
        for(String name:List.of("Sub2_Reynolds_In","Imbalance_Energy","MassFlow_Inlet_Total","Sub1_WallTemperature"))
            require(!c.meshOnlyReport(name),"solution report allowed before initialization: "+name);
    }
}
