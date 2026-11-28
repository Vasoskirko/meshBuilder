"""Additional settings for the native unified exporter (no STAR SDK dependency)."""
UNIFIED_SUPPORT = r'''
    private void configureUnsteadyWorkflow(Simulation sim,int inner,double duration) throws Exception {
        if(inner<1 || !Double.isFinite(duration) || duration<=0)
            throw new IllegalArgumentException("Invalid inner iterations or physical-time interval");
        ImplicitUnsteadySolver solver=sim.getSolverManager().getSolver(ImplicitUnsteadySolver.class);
        SegregatedFlowSolver flow=sim.getSolverManager().getSolver(SegregatedFlowSolver.class);
        if(solver==null || flow==null)throw new IllegalStateException("Implicit unsteady and segregated flow solvers are required");
        solver.getTimeDiscretizationOption().setSelected(TimeDiscretizationOption.Type.SECOND_ORDER);
        flow.getSchemeOption().setSelected(ImplicitSchemeOption.Type.SIMPLEC);
        StepStoppingCriterion maxSteps=(StepStoppingCriterion)sim.getSolverStoppingCriterionManager().getSolverStoppingCriterion("Maximum Steps");
        InnerIterationStoppingCriterion maxInner=(InnerIterationStoppingCriterion)sim.getSolverStoppingCriterionManager().getSolverStoppingCriterion("Maximum Inner Iterations");
        PhysicalTimeStoppingCriterion maxTime=(PhysicalTimeStoppingCriterion)sim.getSolverStoppingCriterionManager().getSolverStoppingCriterion("Maximum Physical Time");
        maxSteps.setIsUsed(false);
        maxInner.getMaxIterations().getQuantity().setValue((double)inner);
        maxInner.setIsUsed(true);
        double now=sim.getSolution().getPhysicalTime();
        maxTime.getMaximumTime().setValueAndUnits(now+duration,sim.getUnitsManager().getObject("s"));
        maxTime.setIsUsed(true);
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
    private UserFieldFunction configureHeatInput(Simulation sim,String name,double value) {
        if(!Double.isFinite(value) || value<0)throw new IllegalArgumentException("Invalid heat flux "+name);
        UserFieldFunction field=findOwned(sim,sim.getFieldFunctionManager(),name,UserFieldFunction.class);
        String inputTag="meshBuilder.HeatInput."+name+"."+Double.toHexString(value);
        if(field==null) {
            field=sim.getFieldFunctionManager().createFieldFunction();
            field.setPresentationName(name);own(sim,field);field.setFunctionName(name);
        }
        field.setSyncName(true);
        field.getTypeOption().setSelected(FieldFunctionTypeOption.Type.SCALAR);
        // W/m^2 = kg/s^3; set physical dimensions, never look up a unit by text.
        field.setDimensions(Dimensions.Builder().mass(1).time(-3).build());
        // Keep manual STAR expressions on an identical macro rerun.
        if(!tagged(field,inputTag)) {
            field.setDefinition(Double.toString(value));
            List<Tag> current=tags(field);
            current.removeIf(t->t.getPresentationName().startsWith("meshBuilder.HeatInput."+name+"."));
            sim.get(TagManager.class).setTags(field,current);mark(sim,field,inputTag);
        }
        return field;
    }
'''
