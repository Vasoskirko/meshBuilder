import java.util.*;
class CheckHeat {
// HELPERS
public static class NamedObject {String name;boolean owned=true;List<Tag> tags=new ArrayList<>();public void setPresentationName(String n){name=n;}}
public static class Tag {String name;Tag(String s){name=s;}public String getPresentationName(){return name;}}
public static class FieldFunctionTypeOption {
 enum Type { SCALAR, VECTOR } Type selected;
 public void setSelected(Type type){selected=type;}
}
public static class UserFieldFunction extends NamedObject {
 String functionName,definition;Dimensions dimensions;FieldFunctionTypeOption type=new FieldFunctionTypeOption();
 public void setFunctionName(String s){functionName=s;}
 public void setDefinition(String s){definition=s;}
 public void setDimensions(Dimensions d){dimensions=d;}
 public FieldFunctionTypeOption getTypeOption(){return type;}
}
public static class FieldFunctionManager {
 List<UserFieldFunction> values=new ArrayList<>();
 public UserFieldFunction createFieldFunction(){UserFieldFunction f=new UserFieldFunction();values.add(f);return f;}
}
public static class TagManager {public void setTags(NamedObject p,List<Tag> tags){p.tags=new ArrayList<>(tags);}}
public static class Simulation {
 FieldFunctionManager fields=new FieldFunctionManager();TagManager tags=new TagManager();
 public <T>T get(Class<T> type){return type.cast(tags);}
 public FieldFunctionManager getFieldFunctionManager(){return fields;}
 // No unit-name lookup and no global parameter creation API in this contract.
}
public static class Dimensions {
 int mass,length,time;
 public static Builder Builder(){return new Builder();}
 public static class Builder {
  Dimensions d=new Dimensions();
  public Builder mass(int x){d.mass=x;return this;}
  public Builder time(int x){d.time=x;return this;}
  public Dimensions build(){return d;}
 }
}
private <T>T findOwned(Simulation sim,FieldFunctionManager manager,String name,Class<T> type){
 for(UserFieldFunction f:manager.values)if(name.equals(f.name)){
  if(!f.owned)throw new IllegalStateException("unowned");return type.cast(f);
 }return null;
}
private void own(Simulation sim,NamedObject f){f.owned=true;}
private List<Tag> tags(NamedObject p){return new ArrayList<>(p.tags);}
private boolean tagged(NamedObject p,String name){for(Tag t:p.tags)if(t.name.equals(name))return true;return false;}
private void mark(Simulation sim,NamedObject p,String name){p.tags.add(new Tag(name));}
public static void main(String[] args){
 CheckHeat check=new CheckHeat();Simulation sim=new Simulation();
 UserFieldFunction f=check.configureHeatInput(sim,"q1",100);
 if(!f.definition.equals("100.0")||!f.functionName.equals("q1"))throw new AssertionError("first input");
 if(f.type.selected!=FieldFunctionTypeOption.Type.SCALAR)throw new AssertionError("not scalar");
 if(f.dimensions.mass!=1||f.dimensions.length!=0||f.dimensions.time!=-3)throw new AssertionError("W/m^2 dimensions");
 f.setDefinition("100 * (1 + 0.05*sin($${Position}[2]/${ExportHeight}))");
 if(check.configureHeatInput(sim,"q1",100)!=f||!f.definition.startsWith("100 *"))throw new AssertionError("same macro erased STAR expression");
 check.configureHeatInput(sim,"q1",200);if(!f.definition.equals("200.0"))throw new AssertionError("new export ignored");
 check.configureHeatInput(sim,"q1",100);if(!f.definition.equals("100.0"))throw new AssertionError("return to earlier input ignored");
 if(f.tags.size()!=1||sim.fields.values.size()!=1)throw new AssertionError("duplicate objects or stale tags");
 f.owned=false;try{check.configureHeatInput(sim,"q1",300);throw new AssertionError("unowned modified");}catch(IllegalStateException expected){}
 try{check.configureHeatInput(sim,"q2",Double.NaN);throw new AssertionError("NaN accepted");}catch(IllegalArgumentException expected){}
}
}
