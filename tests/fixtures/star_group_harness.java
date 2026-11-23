import java.util.*;
class CheckGroups {
// HELPERS
    static final String OWNER="managed";
    public static class NamedObject {
        String name;boolean owned=true;
        NamedObject(String n){name=n;}
        public String getPresentationName(){return name;}
    }
    public static class NeoObjectVector { NeoObjectVector(Object[] objects){} }
    public static class Group {
        List<NamedObject> members=new ArrayList<>();Groups groups=new Groups(this);
        public Groups getGroupsManager(){return groups;}
        public Collection<NamedObject> getObjects(){return members;}
    }
    public static class Groups {
        Group parent;Map<String,Group> groups=new HashMap<>();
        Groups(Group p){parent=p;}
        public Group getObject(String name){return groups.get(name);}
        public void createGroup(String name){groups.put(name,new Group());}
        // A Vector overload and parent-scoped regrouping model the two bugs.
        public void groupObjects(String name,Vector<NamedObject> objects,boolean move){
            Group group=groups.computeIfAbsent(name,k->new Group());group.members.clear();
            for(NamedObject object:objects)
                if(parent==null||parent.members.contains(object))group.members.add(object);
        }
    }
    public static class Manager {
        List<NamedObject> members=new ArrayList<>();Groups groups=new Groups(null);
        public Groups getGroupsManager(){return groups;}
    }
    public static class Simulation {List<String> warnings=new ArrayList<>();}
    Collection<?> objects(Object manager){return ((Manager)manager).members;}
    boolean tagged(NamedObject object,String tag){return object.owned;}
    boolean meshOnlyReport(String name){return name.startsWith("Quality_");}
    void warn(Simulation sim,String text){sim.warnings.add(text);}
    static void require(boolean result,String text){if(!result)throw new AssertionError(text);}
    public static void main(String[] args){
        CheckGroups check=new CheckGroups();Simulation sim=new Simulation();Manager manager=new Manager();
        NamedObject rho=new NamedObject("rho"),init=new NamedObject("T_init"),dt=new NamedObject("TimeStep"),user=new NamedObject("user");
        user.owned=false;manager.members.addAll(List.of(rho,init,dt,user));
        for(int repeat=0;repeat<2;repeat++){
            check.groupManaged(sim,manager,"Parameters");
            require(sim.warnings.isEmpty(),"grouping warning: "+sim.warnings);
            Group root=manager.groups.getObject("meshBuilder_Parameters");require(root!=null,"root missing");
            require(root.groups.getObject("Properties").members.equals(List.of(rho)),"Properties empty/wrong");
            require(root.groups.getObject("Initial").members.equals(List.of(init)),"Initial empty/wrong");
            require(root.groups.getObject("Transient").members.equals(List.of(dt)),"Transient empty/wrong");
            require(root.groups.groups.size()==3,"duplicate/foreign subgroups");
            require(!root.members.contains(user),"unowned object grouped");
        }
    }
}
