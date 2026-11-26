import java.util.*;
class CheckWorkflow {
// HELPERS
public static class Choice {
 public static final Choice SECOND_ORDER=new Choice(),SIMPLEC=new Choice();
}
public static class Option { Choice value;public void setSelected(Choice value){this.value=value;} }
public static class ImplicitUnsteadySolver { Option option=new Option();public Option getTimeDiscretization(){return option;} }
public static class SegregatedFlowSolver { Option option=new Option();public Option getPressureVelocityCouplingOption(){return option;} }
public static class SolverManager {
 ImplicitUnsteadySolver unsteady=new ImplicitUnsteadySolver();SegregatedFlowSolver flow=new SegregatedFlowSolver();
 public <T> T getSolver(Class<T> type){return type.cast(type==ImplicitUnsteadySolver.class?unsteady:flow);}
}
public static class Quantity {double value;public void setValue(int x){value=x;}public void setValue(double x){value=x;} }
public static class Criterion {
 boolean used=true;Quantity q=new Quantity();public void setIsUsed(boolean b){used=b;}
 public Quantity getMaxIterations(){return q;}public Quantity getMaximumTime(){return q;}
}
public static class Criteria {
 Map<String,Criterion> all=new HashMap<>();
 public Criterion getSolverStoppingCriterion(String name){return all.computeIfAbsent(name,k->new Criterion());}
}
public static class Solution {public double getPhysicalTime(){return 1.;} }
public static class Simulation {
 SolverManager solvers=new SolverManager();Criteria criteria=new Criteria();
 public SolverManager getSolverManager(){return solvers;}public Criteria getSolverStoppingCriterionManager(){return criteria;}
 public Solution getSolution(){return new Solution();}public void println(String s){}
}
public static void main(String[] args)throws Exception {
 CheckWorkflow check=new CheckWorkflow();Simulation sim=new Simulation();check.configureUnsteadyWorkflow(sim,7,.45);
 if(sim.solvers.unsteady.option.value!=Choice.SECOND_ORDER||sim.solvers.flow.option.value!=Choice.SIMPLEC)throw new AssertionError("options");
 if(sim.criteria.all.get("Maximum Steps").used)throw new AssertionError("step stopping remains enabled");
 if(sim.criteria.all.get("Maximum Inner Iterations").q.value!=7)throw new AssertionError("inner iterations");
 if(Math.abs(sim.criteria.all.get("Maximum Physical Time").q.value-1.45)>1e-12)throw new AssertionError("target time");
 try{check.workflowEnum(new Option(),"MISSING");throw new AssertionError("unknown enum accepted");}catch(IllegalStateException expected){}
}
}
