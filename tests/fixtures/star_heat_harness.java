import java.util.*;
class CheckHeat {
// HELPERS
public static class NamedObject {String name;List<Tag> tags=new ArrayList<>();}
public static class Tag {String name;Tag(String s){name=s;}public String getPresentationName(){return name;}}
public static class Units {}
public static class Quantity {double value;public void setValueAndUnits(double d,Units u){value=d;}}
public static class ScalarGlobalParameter extends NamedObject {boolean owned=true;Quantity q=new Quantity();public Quantity getQuantity(){return q;}}
public static class GlobalParameterManager {Map<String,ScalarGlobalParameter> values=new HashMap<>();}
public static class TagManager {public void setTags(NamedObject p,List<Tag> tags){p.tags=new ArrayList<>(tags);}}
public static class UnitsManager {public Units getObject(String s){return new Units();}}
public static class Simulation {
 GlobalParameterManager parameters=new GlobalParameterManager();TagManager tags=new TagManager();
 public <T>T get(Class<T> type){return type.cast(type==GlobalParameterManager.class?parameters:tags);}
 public UnitsManager getUnitsManager(){return new UnitsManager();}
}
public static class Dimensions {public static Builder Builder(){return new Builder();}public static class Builder {public Builder mass(int x){return this;}public Builder time(int x){return this;}public Dimensions build(){return new Dimensions();}}}
private <T>T findOwned(Simulation sim,Object manager,String name,Class<T> type){ScalarGlobalParameter p=((GlobalParameterManager)manager).values.get(name);if(p!=null&&!p.owned)throw new IllegalStateException("unowned");return type.cast(p);}
private void createParam(Simulation sim,GlobalParameterManager manager,Object group,String name,double value,String units,Dimensions dims,String def){ScalarGlobalParameter p=new ScalarGlobalParameter();p.name=name;p.q.value=value;manager.values.put(name,p);}
private List<Tag> tags(NamedObject p){return new ArrayList<>(p.tags);}
private boolean tagged(NamedObject p,String name){for(Tag t:p.tags)if(t.name.equals(name))return true;return false;}
private void mark(Simulation sim,NamedObject p,String name){p.tags.add(new Tag(name));}
public static void main(String[] args){
 CheckHeat check=new CheckHeat();Simulation sim=new Simulation();
 check.configureHeatInput(sim,"q1",100);ScalarGlobalParameter p=sim.parameters.values.get("q1");
 if(p.q.value!=100)throw new AssertionError("first input");
 p.q.value=900;check.configureHeatInput(sim,"q1",100);
 if(p.q.value!=900)throw new AssertionError("same macro erased STAR edit");
 check.configureHeatInput(sim,"q1",200);if(p.q.value!=200)throw new AssertionError("new export ignored");
 check.configureHeatInput(sim,"q1",100);if(p.q.value!=100)throw new AssertionError("return to earlier input ignored");
 if(p.tags.size()!=1)throw new AssertionError("stale configuration tags");
 p.owned=false;try{check.configureHeatInput(sim,"q1",300);throw new AssertionError("unowned modified");}catch(IllegalStateException expected){}
}
}
