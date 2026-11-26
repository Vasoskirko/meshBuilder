"""Additional settings for the native unified exporter (no STAR SDK dependency)."""
UNIFIED_SUPPORT = r'''
    private Object workflowCall(Object object,String name,Object... args) throws Exception {
        for(java.lang.reflect.Method method:object.getClass().getMethods()) {
            if(!method.getName().equals(name)||method.getParameterCount()!=args.length)continue;
            try{return method.invoke(object,args);}catch(IllegalArgumentException mismatch){}
        }
        throw new IllegalStateException("STAR API unavailable: "+object.getClass().getSimpleName()+"."+name);
    }
    private void workflowEnum(Object option,String selected) throws Exception {
        for(java.lang.reflect.Method method:option.getClass().getMethods()) {
            if(!method.getName().equals("setSelected")||method.getParameterCount()!=1)continue;
            Class<?> type=method.getParameterTypes()[0];
            if(type.isEnum()) {
                for(Object value:type.getEnumConstants())if(((Enum<?>)value).name().equals(selected)) {method.invoke(option,value);return;}
            } else try {
                Object value=type.getField(selected).get(null);method.invoke(option,value);return;
            } catch(NoSuchFieldException absent) { /* Try another setter overload. */ }
        }
        throw new IllegalStateException("STAR option unavailable: "+selected);
    }
    private void configureUnsteadyWorkflow(Simulation sim,int inner,double duration) throws Exception {
        ImplicitUnsteadySolver solver=sim.getSolverManager().getSolver(ImplicitUnsteadySolver.class);
        workflowEnum(workflowCall(solver,"getTimeDiscretization"),"SECOND_ORDER");
        Object flow=sim.getSolverManager().getSolver(SegregatedFlowSolver.class);
        workflowEnum(workflowCall(flow,"getPressureVelocityCouplingOption"),"SIMPLEC");
        Object criteria=workflowCall(sim,"getSolverStoppingCriterionManager");
        Object maxSteps=workflowCall(criteria,"getSolverStoppingCriterion","Maximum Steps");
        workflowCall(maxSteps,"setIsUsed",false);
        Object maxInner=workflowCall(criteria,"getSolverStoppingCriterion","Maximum Inner Iterations");
        workflowCall(workflowCall(maxInner,"getMaxIterations"),"setValue",inner);
        Object maxTime=workflowCall(criteria,"getSolverStoppingCriterion","Maximum Physical Time");
        double now=sim.getSolution().getPhysicalTime();
        workflowCall(workflowCall(maxTime,"getMaximumTime"),"setValue",now+duration);
        workflowCall(maxTime,"setIsUsed",true);
        sim.println("Implicit Unsteady: Second Order; SIMPLEC; Maximum Steps disabled; stop at physical time.");
    }
'''


def flat_groups(source):
    start=source.index('            // A nested group')
    end=source.index('        } catch (Exception e)',start)
    source=source[:start]+'''            for (Map.Entry<String,List<NamedObject>> entry : groups.entrySet())
                nativeGroupObjects(roots,entry.getKey(),entry.getValue());
'''+source[end:]
    return source.replace('"MeshQuality"','"Quality"').replace('"Coordinates"','"Geometry"').replace('"Transient"','"Time"')

HEAT_SUPPORT = r'''
    private void configureHeatInput(Simulation sim,String name,double value) {
        GlobalParameterManager manager=sim.get(GlobalParameterManager.class);
        ScalarGlobalParameter parameter=findOwned(sim,manager,name,ScalarGlobalParameter.class);
        String inputTag="meshBuilder.HeatInput."+name+"."+Double.toHexString(value);
        if(parameter==null) {
            createParam(sim,manager,null,name,value,"W/m^2",Dimensions.Builder().mass(1).time(-3).build(),null);
            parameter=findOwned(sim,manager,name,ScalarGlobalParameter.class);
        }
        if(parameter==null)throw new IllegalStateException("Missing heat parameter "+name);
        // Identical macro reruns preserve in-STAR edits. A newly exported q
        // explicitly changes the value, including a return to an earlier input.
        if(!tagged(parameter,inputTag)) {
            parameter.getQuantity().setValueAndUnits(value,sim.getUnitsManager().getObject("W/m^2"));
            List<Tag> current=tags(parameter);
            current.removeIf(t->t.getPresentationName().startsWith("meshBuilder.HeatInput."+name+"."));
            sim.get(TagManager.class).setTags(parameter,current);mark(sim,parameter,inputTag);
        }
    }
'''
