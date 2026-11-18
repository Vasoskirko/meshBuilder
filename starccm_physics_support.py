"""First-run material/reference/initial-field configuration for native STAR models."""
PHYSICS_SUPPORT = r'''
    private void constantProperty(Material material, Class<? extends MaterialProperty> type, String definition) {
        MaterialProperty property=material.getMaterialProperties().getMaterialProperty(type);
        property.setMethod(ConstantMaterialPropertyMethod.class);
        ((ConstantMaterialPropertyMethod)property.getMethod()).getQuantity().setDefinition(definition);
    }
    private boolean configurePhysicalValues(Simulation sim, PhysicsContinuum physics, List<Region> regions,
            boolean iapws, boolean thermal) {
        try {
            if (physics==null) throw new IllegalStateException("Physical model setup failed");
            // Refuse to bind a property/profile to an unrelated user parameter.
            GlobalParameterManager manager=sim.get(GlobalParameterManager.class);
            for (String name : new String[]{"rho","dynvis","Cp","lambda","P_ref","T_ref","P_init","T_init","U_init"})
                if (findOwned(sim,manager,name,ScalarGlobalParameter.class)==null)
                    throw new IllegalStateException("Missing physical parameter " + name);
            for (Region region : regions) region.setPhysicsContinuum(physics);
            if (!iapws) {
                Material material=physics.getModelManager().getModel(SingleComponentLiquidModel.class).getMaterial();
                constantProperty(material,ConstantDensityProperty.class,"${rho}");
                constantProperty(material,DynamicViscosityProperty.class,"${dynvis}");
                if (thermal) {
                    constantProperty(material,SpecificHeatProperty.class,"${Cp}");
                    constantProperty(material,ThermalConductivityProperty.class,"${lambda}");
                }
            }
            // Reference pressure is absolute; initial pressure is gauge (absolute = reference + gauge).
            physics.getReferenceValues().get(ReferencePressure.class).setDefinition("${P_ref}");
            InitialPressureProfile pressure=physics.getInitialConditions().get(InitialPressureProfile.class);
            pressure.setMethod(ConstantScalarProfileMethod.class);
            pressure.getMethod(ConstantScalarProfileMethod.class).getQuantity().setDefinition("${P_init}");
            if (thermal || iapws) {
                StaticTemperatureProfile temperature=physics.getInitialConditions().get(StaticTemperatureProfile.class);
                temperature.setMethod(ConstantScalarProfileMethod.class);
                temperature.getMethod(ConstantScalarProfileMethod.class).getQuantity().setDefinition("${T_init}");
            }
            VelocityProfile velocity=physics.getInitialConditions().get(VelocityProfile.class);
            velocity.setMethod(ConstantVectorProfileMethod.class);
            velocity.getMethod(ConstantVectorProfileMethod.class).getQuantity().setDefinition("[0, 0, ${U_init}]");
            sim.println("  • Material, absolute reference pressure and initial gauge pressure/temperature/axial velocity configured.");
            return true;
        } catch (Exception e) { warn(sim,"  [!] Physical values: " + e.getMessage()); return false; }
    }
    private void initializeFirstSolution(Simulation sim, boolean reuse, boolean requested, boolean configured) {
        if (reuse) { sim.println("  • Existing solution and initial conditions preserved; no reinitialization."); return; }
        if (!requested) { sim.println("  • Automatic initialization disabled; initialize manually before solution reports."); return; }
        if (!configured) { warn(sim,"  [!] Initialization skipped: physical values were not configured successfully."); return; }
        try {
            sim.getSolution().initializeSolution();
            sim.println("  • Initial fields initialized; no solver iterations were run. Set boundary conditions before solving.");
        } catch (Exception e) { warn(sim,"  [!] Initialization failed: " + e.getMessage()); }
    }
    private boolean meshOnlyReport(String name) {
        return name.startsWith("Quality_") || name.matches("Sub[0-9]+_(Area_In|Area_Out|Volume|RodArea|WettedPerimeter|HydraulicDiameter)");
    }
'''
