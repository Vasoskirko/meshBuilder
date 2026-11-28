import java.util.*;
class CheckReportSetup {
// HELPERS
static class NamedObject {String name;boolean owned;String getPresentationName(){return name;}void setPresentationName(String n){name=n;}}
static class Boundary extends NamedObject {Boundary(String n){name=n;}}
static class InterfaceBoundary extends Boundary {InterfaceBoundary(String n){super(n);}}
static class BoundaryManager {List<Boundary> values=new ArrayList<>();List<Boundary> getBoundaries(){return values;}}
static class Region {BoundaryManager manager=new BoundaryManager();BoundaryManager getBoundaryManager(){return manager;}}
static class Units {}
static class DoubleVector {double[] values;DoubleVector(double[] v){values=v;}}
static class Coordinate {double[] value;Units units;void setCoordinate(Units a,Units b,Units c,DoubleVector v){value=v.values;units=a;}}
static class Basis {double[] value;void setComponents(double a,double b,double c){value=new double[]{a,b,c};}}
static class Manager {List<NamedObject> values=new ArrayList<>();}
static class CartesianCoordinateSystem extends NamedObject {
 Coordinate origin=new Coordinate();Basis x=new Basis(),y=new Basis();
 Coordinate getOrigin(){return origin;}Basis getXVector(){return x;}Basis getXyPlane(){return y;}
}
static class CoordinateManager extends Manager {CartesianCoordinateSystem createLocalCoordinateSystem(Class<CartesianCoordinateSystem> t,String s){CartesianCoordinateSystem c=new CartesianCoordinateSystem();values.add(c);return c;}}
static class LabCoordinateSystem extends NamedObject {CoordinateManager manager=new CoordinateManager();CoordinateManager getLocalCoordinateSystemManager(){return manager;}}
static class UserFieldFunction extends NamedObject {
 String functionName,definition;boolean sync;
 void setSyncName(boolean b){sync=b;}void setFunctionName(String s){functionName=s;}void setDefinition(String s){definition=s;}
}
static class FieldManager extends Manager {UserFieldFunction createFieldFunction(){UserFieldFunction f=new UserFieldFunction();values.add(f);return f;}}
static class Simulation {FieldManager fields=new FieldManager();FieldManager getFieldFunctionManager(){return fields;}}
String displayName(String name){return name.startsWith("MB_")?name.substring(3):name;}
void own(Simulation s,NamedObject o){o.owned=true;o.setPresentationName(displayName(o.name));}
<T>T findOwned(Simulation s,Object manager,String name,Class<T> type){
 for(NamedObject o:((Manager)manager).values)if(displayName(name).equals(displayName(o.name))){if(!o.owned)throw new IllegalStateException("unowned");return type.cast(o);}return null;
}
static void require(boolean b,String msg){if(!b)throw new AssertionError(msg);}
public static void main(String[] args) {
 CheckReportSetup c=new CheckReportSetup();Region region=new Region();Boundary parent=new Boundary("Inlet");
 InterfaceBoundary in=new InterfaceBoundary("Inlet [SelectedInterface_1 1]"),out=new InterfaceBoundary("Outlet [SelectedInterface_1 1]");
 region.manager.values.addAll(List.of(parent,new InterfaceBoundary("Inlet [SelectedInterface_10 1]"),in,out));
 require(c.periodicReportSide(region,"Inlet","SelectedInterface_1")==in,"plain Inlet selected");
 require(c.periodicReportSide(region,"Outlet","SelectedInterface_1")==out,"wrong outlet side");
 try{c.periodicReportSide(region,"Inlet","Missing");throw new AssertionError("fallback to wall");}catch(IllegalStateException expected){}
 for(String name:List.of("Sub1_WallShearMean","Sub1_Cf_Wall","Sub1_Density_In","Sub1_Viscosity_Out","Sub1_Pressure_In","MassFlow_Inlet_Total","Energy_Flow_Outlet_Total","Gap_Sub1_Sub2_Area"))require(!c.reportNeedsMonitor(name),"unneeded monitor: "+name);
 for(String name:List.of("Sub1_Darcy_Wall","Sub1_PressureDrop","Sub1_Reynolds_In","Imbalance_Energy","Imbalance_MassFlow","MassFlow_Gap_Sub1_Sub2","Gap_Sub1_Sub2_MassFluxMean","Gap_Sub1_Sub2_AbsMassFluxMean"))require(c.reportNeedsMonitor(name),"missing monitor: "+name);
 Simulation sim=new Simulation();LabCoordinateSystem labCoord=new LabCoordinateSystem();labCoord.name="Laboratory";Units metres=new Units();
 CartesianCoordinateSystem gapFrame1_2=c.gapCoordinateSystem(sim,labCoord,metres,"Normal_Gap_Sub1_to_Sub2",new double[]{1,2,3},.6,.8);
 require(gapFrame1_2.x.value[0]==.8&&gapFrame1_2.x.value[1]==-.6&&gapFrame1_2.y.value[0]==.6&&gapFrame1_2.y.value[1]==.8,"basis");
 require(gapFrame1_2.origin.value[1]==2&&gapFrame1_2.origin.units==metres,"origin in metres");
 require(c.gapCoordinateSystem(sim,labCoord,metres,"Normal_Gap_Sub1_to_Sub2",new double[]{1,2,3},.6,.8)==gapFrame1_2&&labCoord.manager.values.size()==1,"frame duplicated");
 // GAP_DEFINITION
 // GAP_ASSERTION
 UserFieldFunction f=c.getOrCreateFF(sim,"MB_ZFraction","$${Position}[2]/${ExportHeight}");
 require(f.sync&&f.name.equals("ZFraction")&&f.functionName.equals(f.name),"names not synchronized");
 require(c.getOrCreateFF(sim,"MB_ZFraction","1")==f,"duplicate synchronized field");
}
}
