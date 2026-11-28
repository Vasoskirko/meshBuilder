import java.util.*;
class CheckWorkflow {
// HELPERS
public static class TimeDiscretizationOption {
 public enum Type { FIRST_ORDER, SECOND_ORDER } Type value;
 public void setSelected(Type value){this.value=value;}
}
public static class ImplicitSchemeOption {
 public enum Type { SIMPLE, SIMPLEC } Type value;
 public void setSelected(Type value){this.value=value;}
}
public static class ImplicitUnsteadySolver {TimeDiscretizationOption option=new TimeDiscretizationOption();public TimeDiscretizationOption getTimeDiscretizationOption(){return option;}}
public static class SegregatedFlowSolver {ImplicitSchemeOption option=new ImplicitSchemeOption();public ImplicitSchemeOption getSchemeOption(){return option;}}
public static class SolverManager {
 ImplicitUnsteadySolver unsteady=new ImplicitUnsteadySolver();SegregatedFlowSolver flow=new SegregatedFlowSolver();
 public <T> T getSolver(Class<T> type){return type.cast(type==ImplicitUnsteadySolver.class?unsteady:flow);}
}
public static class Units {}
public static class UnitsManager {public Units getObject(String name){if(!name.equals("s"))throw new AssertionError("unexpected units");return new Units();}}
public static class Quantity {double value;Units units;public void setValue(double x){value=x;}public void setValueAndUnits(double x,Units u){value=x;units=u;}}
public static class IntegerValue {Quantity quantity=new Quantity();public Quantity getQuantity(){return quantity;}}
public static class Criterion {boolean used=true;public void setIsUsed(boolean b){used=b;}}
public static class StepStoppingCriterion extends Criterion {}
public static class InnerIterationStoppingCriterion extends Criterion {IntegerValue iterations=new IntegerValue();public IntegerValue getMaxIterations(){return iterations;}}
public static class PhysicalTimeStoppingCriterion extends Criterion {Quantity q=new Quantity();public Quantity getMaximumTime(){return q;}}
public static class Criteria {
 StepStoppingCriterion steps=new StepStoppingCriterion();InnerIterationStoppingCriterion inner=new InnerIterationStoppingCriterion();PhysicalTimeStoppingCriterion time=new PhysicalTimeStoppingCriterion();
 public Criterion getSolverStoppingCriterion(String name){
  if(name.equals("Maximum Steps"))return steps;
  if(name.equals("Maximum Inner Iterations"))return inner;
  if(name.equals("Maximum Physical Time"))return time;
  throw new AssertionError("unexpected criterion");
 }
}
public static class Solution {public double getPhysicalTime(){return 1.;}}
public static class Simulation {
 SolverManager solvers=new SolverManager();Criteria criteria=new Criteria();UnitsManager units=new UnitsManager();
 public SolverManager getSolverManager(){return solvers;}public Criteria getSolverStoppingCriterionManager(){return criteria;}
 public UnitsManager getUnitsManager(){return units;}public Solution getSolution(){return new Solution();}public void println(String s){}
}
public static void main(String[] args)throws Exception {
 CheckWorkflow check=new CheckWorkflow();Simulation sim=new Simulation();sim.criteria.inner.used=false;sim.criteria.time.used=false;
 check.configureUnsteadyWorkflow(sim,7,.45);
 if(sim.solvers.unsteady.option.value!=TimeDiscretizationOption.Type.SECOND_ORDER||sim.solvers.flow.option.value!=ImplicitSchemeOption.Type.SIMPLEC)throw new AssertionError("options");
 if(sim.criteria.steps.used)throw new AssertionError("step stopping remains enabled");
 if(!sim.criteria.inner.used||sim.criteria.inner.iterations.quantity.value!=7)throw new AssertionError("inner iterations");
 if(!sim.criteria.time.used||Math.abs(sim.criteria.time.q.value-1.45)>1e-12||sim.criteria.time.q.units==null)throw new AssertionError("target time or seconds");
 try{check.configureUnsteadyWorkflow(sim,0,.1);throw new AssertionError("invalid iterations accepted");}catch(IllegalArgumentException expected){}
 try{check.configureUnsteadyWorkflow(sim,1,Double.NaN);throw new AssertionError("NaN interval accepted");}catch(IllegalArgumentException expected){}
 sim.solvers.unsteady=null;
 try{check.configureUnsteadyWorkflow(sim,5,.1);throw new AssertionError("missing solver accepted");}catch(IllegalStateException expected){}
}
}
