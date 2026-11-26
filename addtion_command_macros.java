// Simcenter STAR-CCM+ macro: setup_starccm_subchannels.java
// Written by Simcenter STAR-CCM+ 21.02.007
package macro;

import java.util.*;

import star.common.*;
import star.base.neo.*;
import star.segregatedflow.*;
import star.segregatedenergy.*;
import star.realgas.*;
import star.material.*;
import star.turbulence.*;
import star.rsturb.*;
import star.flow.*;
import star.energy.*;
import star.kwturb.*;
import star.walldistance.*;

public class setup_starccm_subchannels extends StarMacro {

  @Override
  public void execute() {
    execute0();
  }

  private void execute0() {

    Simulation simulation_0 = 
      getActiveSimulation();

    ImportManager importManager_0 = 
      simulation_0.getImportManager();

    importManager_0.importMeshFiles(new StringVector(new String[] {resolvePath("D:\\Oskirko\\09.26 TMC ТВС-600+\\sim\\tvs_mesh_v3_16\\mesh_test2\\bundle_subchannels.xyz")}), NeoProperty.fromString("{\'FileOptions\': [{\'Sequence\': 802}]}"));

    FvRepresentation fvRepresentation_0 = 
      ((FvRepresentation) simulation_0.getRepresentationManager().getObject("Volume Mesh"));

    Region region_12 = 
      simulation_0.getRegionManager().getRegion("Zone 1");

    Region region_13 = 
      simulation_0.getRegionManager().getRegion("Zone 10");

    Region region_14 = 
      simulation_0.getRegionManager().getRegion("Zone 11");

    Region region_15 = 
      simulation_0.getRegionManager().getRegion("Zone 12");

    Region region_16 = 
      simulation_0.getRegionManager().getRegion("Zone 2");

    Region region_17 = 
      simulation_0.getRegionManager().getRegion("Zone 3");

    Region region_18 = 
      simulation_0.getRegionManager().getRegion("Zone 4");

    Region region_19 = 
      simulation_0.getRegionManager().getRegion("Zone 5");

    Region region_20 = 
      simulation_0.getRegionManager().getRegion("Zone 6");

    Region region_21 = 
      simulation_0.getRegionManager().getRegion("Zone 7");

    Region region_22 = 
      simulation_0.getRegionManager().getRegion("Zone 8");

    Region region_23 = 
      simulation_0.getRegionManager().getRegion("Zone 9");

    fvRepresentation_0.generateCompactMeshReport(new ArrayList<>(Arrays.<Region>asList(region_12, region_13, region_14, region_15, region_16, region_17, region_18, region_19, region_20, region_21, region_22, region_23)));

    MeshManager meshManager_0 = 
      simulation_0.getMeshManager();

    meshManager_0.combineRegions(new ArrayList<>(Arrays.<Region>asList(region_12, region_16, region_17, region_18, region_19, region_20, region_21, region_22, region_23, region_13, region_14, region_15)), true, true, 0.02, true);

    Boundary boundary_2 = 
      region_12.getBoundaryManager().getBoundary("wall");

    meshManager_0.splitBoundariesByAngle(30.0, new ArrayList<>(Arrays.<Boundary>asList(boundary_2)));

    Boundary boundary_3 = 
      region_12.getBoundaryManager().getBoundary("wall 10");

    boundary_3.setPresentationName("inlet");

    boundary_2.setPresentationName("outlet");

    boundary_3.setPresentationName("Inlet");

    boundary_2.setPresentationName("Outlet");

    Boundary boundary_4 = 
      region_12.getBoundaryManager().getBoundary("wall 2");

    Boundary boundary_5 = 
      region_12.getBoundaryManager().getBoundary("wall 8");

    Boundary boundary_6 = 
      region_12.getBoundaryManager().getBoundary("wall 9");

    Boundary boundary_7 = 
      region_12.getBoundaryManager().getBoundary("wall 3");

    meshManager_0.combineBoundaries(new ArrayList<>(Arrays.<Boundary>asList(boundary_4, boundary_5, boundary_6, boundary_7)));

    boundary_4.setPresentationName("rods");

    Boundary boundary_8 = 
      region_12.getBoundaryManager().getBoundary("wall 4");

    boundary_8.setPresentationName("sym/per1");

    Boundary boundary_9 = 
      region_12.getBoundaryManager().getBoundary("wall 5");

    boundary_9.setPresentationName("sym/per2");

    Boundary boundary_10 = 
      region_12.getBoundaryManager().getBoundary("wall 6");

    boundary_10.setPresentationName("sym/per3");

    Boundary boundary_11 = 
      region_12.getBoundaryManager().getBoundary("wall 7");

    boundary_11.setPresentationName("sym/per4");

    BoundaryInterface boundaryInterface_0 = 
      simulation_0.getInterfaceManager().createBoundaryInterface(boundary_3, boundary_2, "Interface");

    FullyDevelopedInterface fullyDevelopedInterface_0 = 
      ((FullyDevelopedInterface) simulation_0.get(ConditionTypeManager.class).get(FullyDevelopedInterface.class));

    boundaryInterface_0.setInterfaceType(fullyDevelopedInterface_0);

    boundaryInterface_0.getTopology().setSelected(InterfaceConfigurationOption.Type.PERIODIC);

    PhysicsContinuum physicsContinuum_0 = 
      ((PhysicsContinuum) simulation_0.getContinuumManager().getContinuum("Physics 1"));

    physicsContinuum_0.enable(SingleComponentLiquidModel.class);

    physicsContinuum_0.enable(SegregatedFlowModel.class);

    physicsContinuum_0.enable(ConstantDensityModel.class);

    physicsContinuum_0.enable(SteadyModel.class);

    physicsContinuum_0.enable(TurbulentModel.class);

    physicsContinuum_0.enable(RansTurbulenceModel.class);

    physicsContinuum_0.enable(ReynoldsStressTurbulence.class);

    physicsContinuum_0.enable(EbRsTurbModel.class);

    physicsContinuum_0.enable(EbRsAllYplusWallTreatment.class);

    physicsContinuum_0.enable(SegregatedFluidTemperatureModel.class);

    boundaryInterface_0.getConditions().get(FullyDevelopedFlowOption.class).setSelected(FullyDevelopedFlowOption.Type.MASS_FLOW_RATE);

    Units units_0 = 
      simulation_0.getUnitsManager().getInternalUnits(new IntVector(new int[] {1, 0, -1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}));

    FullyDevelopedMassFlowRate fullyDevelopedMassFlowRate_0 = 
      boundaryInterface_0.getValues().get(FullyDevelopedMassFlowRate.class);

    fullyDevelopedMassFlowRate_0.getFullyDevelopedMassFlowRate().setDefinition("${G_subchannel}");

    BoundaryInterface boundaryInterface_1 = 
      simulation_0.getInterfaceManager().createBoundaryInterface(boundary_8, boundary_11, "Interface");

    BoundaryInterface boundaryInterface_2 = 
      simulation_0.getInterfaceManager().createBoundaryInterface(boundary_9, boundary_10, "Interface");

    boundaryInterface_1.getTopology().setSelected(InterfaceConfigurationOption.Type.PERIODIC);

    boundaryInterface_2.getTopology().setSelected(InterfaceConfigurationOption.Type.PERIODIC);

    ScalarGlobalParameter scalarGlobalParameter_0 = 
      (ScalarGlobalParameter) simulation_0.get(GlobalParameterManager.class).createGlobalParameter(ScalarGlobalParameter.class, "Scalar");

    scalarGlobalParameter_0.setPresentationName("pi");

    Units units_1 = 
      ((Units) simulation_0.getUnitsManager().getObject(""));

    scalarGlobalParameter_0.getQuantity().setValueAndUnits(3.14159265358979, units_1);

    ScalarGlobalParameter scalarGlobalParameter_1 = 
      (ScalarGlobalParameter) simulation_0.get(GlobalParameterManager.class).createGlobalParameter(ScalarGlobalParameter.class, "Scalar");

    scalarGlobalParameter_1.setPresentationName("Apert");

    scalarGlobalParameter_1.getQuantity().setDefinition("0.01*${U_b}");

    scalarGlobalParameter_1.setDimensions(Dimensions.Builder().length(1).time(-1).build());

    physicsContinuum_0.enable(GravityModel.class);

    ConstantDensityModel constantDensityModel_0 = 
      physicsContinuum_0.getModelManager().getModel(ConstantDensityModel.class);

    physicsContinuum_0.disableModel(constantDensityModel_0);

    physicsContinuum_0.enable(IapwsLiquidEosModel.class);

    Units units_2 = 
      simulation_0.getUnitsManager().getInternalUnits(new IntVector(new int[] {0, 1, -2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}));

    physicsContinuum_0.getReferenceValues().get(Gravity.class).setDefinition("[0.0, 0.0, -${g}]");

    ScalarGlobalParameter scalarGlobalParameter_2 = 
      (ScalarGlobalParameter) simulation_0.get(GlobalParameterManager.class).createGlobalParameter(ScalarGlobalParameter.class, "Scalar");

    scalarGlobalParameter_2.setPresentationName("g");

    scalarGlobalParameter_2.getQuantity().setValueAndUnits(-9.81, units_1);

    scalarGlobalParameter_2.getQuantity().setValueAndUnits(9.81, units_1);

    Units units_3 = 
      ((Units) simulation_0.getUnitsManager().getObject("m"));

    physicsContinuum_0.getReferenceValues().get(MinimumAllowableWallDistance.class).setValueAndUnits(1.0E-7, units_3);

    Units units_4 = 
      simulation_0.getUnitsManager().getInternalUnits(new IntVector(new int[] {1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, -1, 0, 0, 0, 0, 0, 0, 0, 0}));

    physicsContinuum_0.getReferenceValues().get(ReferenceDensity.class).setDefinition("${rho_ref}");

    Units units_5 = 
      simulation_0.getUnitsManager().getInternalUnits(new IntVector(new int[] {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}));

    physicsContinuum_0.getReferenceValues().get(ReferencePressure.class).setDefinition("${p_ref}");

    Units units_6 = 
      simulation_0.getUnitsManager().getInternalUnits(new IntVector(new int[] {0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}));

    StaticTemperatureProfile staticTemperatureProfile_0 = 
      physicsContinuum_0.getInitialConditions().get(StaticTemperatureProfile.class);

    staticTemperatureProfile_0.getMethod(ConstantScalarProfileMethod.class).getQuantity().setDefinition("${T_in}");

    VelocityProfile velocityProfile_0 = 
      physicsContinuum_0.getInitialConditions().get(VelocityProfile.class);

    velocityProfile_0.setMethod(CompositeVectorProfileMethod.class);

    Units units_7 = 
      simulation_0.getUnitsManager().getInternalUnits(new IntVector(new int[] {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}));

    ScalarProfile scalarProfile_0 = 
      velocityProfile_0.getMethod(CompositeVectorProfileMethod.class).getProfile(2);

    scalarProfile_0.getMethod(ConstantScalarProfileMethod.class).getQuantity().setDefinition("${U_b}");

    velocityProfile_0.setMethod(FunctionVectorProfileMethod.class);

    UserFieldFunction userFieldFunction_0 = 
      simulation_0.getFieldFunctionManager().createFieldFunction();

    userFieldFunction_0.getTypeOption().setSelected(FieldFunctionTypeOption.Type.SCALAR);

    userFieldFunction_0.setSyncName(true);

    userFieldFunction_0.setPresentationName("thetaZ");

    userFieldFunction_0.setDefinition("2*${pi}*$${Position}[2]/${ExportHeight}");

    ScalarGlobalParameter scalarGlobalParameter_3 = 
      (ScalarGlobalParameter) simulation_0.get(GlobalParameterManager.class).createGlobalParameter(ScalarGlobalParameter.class, "Scalar");

    scalarGlobalParameter_3.setPresentationName("ExportHeight");

    scalarGlobalParameter_3.getQuantity().setValueAndUnits(0.3, units_1);

    scalarGlobalParameter_3.setDimensions(Dimensions.Builder().length(1).build());

    UserFieldFunction userFieldFunction_1 = 
      simulation_0.getFieldFunctionManager().createFieldFunction();

    userFieldFunction_1.getTypeOption().setSelected(FieldFunctionTypeOption.Type.SCALAR);

    userFieldFunction_1.setSyncName(true);

    userFieldFunction_1.setPresentationName("seedX");

    userFieldFunction_1.setDefinition("sin(${thetaZ})+0.5*sin(3*${thetaZ}+0.7)+0.25*sin(7*${thetaZ}+1.9)");

    UserFieldFunction userFieldFunction_2 = 
      simulation_0.getFieldFunctionManager().createFieldFunction();

    userFieldFunction_2.getTypeOption().setSelected(FieldFunctionTypeOption.Type.SCALAR);

    userFieldFunction_2.setSyncName(true);

    userFieldFunction_2.setPresentationName("seedY");

    userFieldFunction_2.setDefinition("sin(2*${thetaZ}+0.4)+0.5*sin(5*${thetaZ}+1.3)+0.25*sin*(9*${thetaZ}+2.2)");

    userFieldFunction_2.setDefinition("sin(2*${thetaZ}+0.4) + 0.5*sin(5*${thetaZ}+1.3)+0.25*sin(9*${thetaZ}+2.2)");

    UserFieldFunction userFieldFunction_3 = 
      simulation_0.getFieldFunctionManager().createFieldFunction();

    userFieldFunction_3.getTypeOption().setSelected(FieldFunctionTypeOption.Type.VECTOR);

    userFieldFunction_3.setSyncName(true);

    userFieldFunction_3.setPresentationName("VelocitySeed");

    userFieldFunction_3.setDefinition("[${Apert}*${seedX}, ${Apert}*${seedY}, ${U_b}]");

    boundary_4.getConditions().get(WallThermalOption.class).setSelected(WallThermalOption.Type.HEAT_FLUX);

    HeatFluxProfile heatFluxProfile_0 = 
      boundary_4.getValues().get(HeatFluxProfile.class);

    heatFluxProfile_0.setMethod(FunctionScalarProfileMethod.class);

    UserFieldFunction userFieldFunction_4 = 
      simulation_0.getFieldFunctionManager().createFieldFunction();

    userFieldFunction_4.getTypeOption().setSelected(FieldFunctionTypeOption.Type.SCALAR);

    userFieldFunction_4.setSyncName(true);

    userFieldFunction_4.setPresentationName("q1");

    UserFieldFunction userFieldFunction_5 = 
      simulation_0.getFieldFunctionManager().createFieldFunction();

    userFieldFunction_5.getTypeOption().setSelected(FieldFunctionTypeOption.Type.SCALAR);

    userFieldFunction_5.setSyncName(true);

    userFieldFunction_5.setPresentationName("q2");

    userFieldFunction_4.setDefinition("10000");

    userFieldFunction_5.setDefinition("30000");

    heatFluxProfile_0.getMethod(FunctionScalarProfileMethod.class).setFieldFunction(userFieldFunction_4);

    velocityProfile_0.getMethod(FunctionVectorProfileMethod.class).setFieldFunction(userFieldFunction_3);

    ScalarGlobalParameter scalarGlobalParameter_4 = 
      (ScalarGlobalParameter) simulation_0.get(GlobalParameterManager.class).createGlobalParameter(ScalarGlobalParameter.class, "Scalar");

    scalarGlobalParameter_4.setPresentationName("U_b");

    SingleComponentLiquidModel singleComponentLiquidModel_0 = 
      physicsContinuum_0.getModelManager().getModel(SingleComponentLiquidModel.class);

    Liquid liquid_0 = 
      ((Liquid) singleComponentLiquidModel_0.getMaterial());

    liquid_0.getMaterialProperties().getMaterialProperty(ThermalConductivityProperty.class).setMethod(ConstantMaterialPropertyMethod.class);

    liquid_0.getMaterialProperties().getMaterialProperty(ThermalConductivityProperty.class).setMethod(IapwsThermalConductivityMethod.class);

    liquid_0.getMaterialProperties().getMaterialProperty(DynamicViscosityProperty.class).setMethod(ConstantMaterialPropertyMethod.class);

    liquid_0.getMaterialProperties().getMaterialProperty(DynamicViscosityProperty.class).setMethod(IapwsDynamicViscosityMethod.class);

    ScalarGlobalParameter scalarGlobalParameter_5 = 
      (ScalarGlobalParameter) simulation_0.get(GlobalParameterManager.class).createGlobalParameter(ScalarGlobalParameter.class, "Scalar");

    scalarGlobalParameter_5.setPresentationName("t_start");

    ScalarGlobalParameter scalarGlobalParameter_6 = 
      (ScalarGlobalParameter) simulation_0.get(GlobalParameterManager.class).createGlobalParameter(ScalarGlobalParameter.class, "Scalar");

    scalarGlobalParameter_6.setPresentationName("t_char");

    EbRsAllYplusWallTreatment ebRsAllYplusWallTreatment_0 = 
      physicsContinuum_0.getModelManager().getModel(EbRsAllYplusWallTreatment.class);

    physicsContinuum_0.disableModel(ebRsAllYplusWallTreatment_0);

    WallDistanceModel wallDistanceModel_0 = 
      physicsContinuum_0.getModelManager().getModel(WallDistanceModel.class);

    physicsContinuum_0.disableModel(wallDistanceModel_0);

    EbRsTurbModel ebRsTurbModel_0 = 
      physicsContinuum_0.getModelManager().getModel(EbRsTurbModel.class);

    physicsContinuum_0.disableModel(ebRsTurbModel_0);

    ReynoldsStressTurbulence reynoldsStressTurbulence_0 = 
      physicsContinuum_0.getModelManager().getModel(ReynoldsStressTurbulence.class);

    physicsContinuum_0.disableModel(reynoldsStressTurbulence_0);

    RansTurbulenceModel ransTurbulenceModel_0 = 
      physicsContinuum_0.getModelManager().getModel(RansTurbulenceModel.class);

    physicsContinuum_0.disableModel(ransTurbulenceModel_0);

    TurbulentModel turbulentModel_0 = 
      physicsContinuum_0.getModelManager().getModel(TurbulentModel.class);

    physicsContinuum_0.disableModel(turbulentModel_0);

    SteadyModel steadyModel_0 = 
      physicsContinuum_0.getModelManager().getModel(SteadyModel.class);

    physicsContinuum_0.disableModel(steadyModel_0);

    physicsContinuum_0.enable(ImplicitUnsteadyModel.class);

    physicsContinuum_0.enable(TurbulentModel.class);

    physicsContinuum_0.enable(RansTurbulenceModel.class);

    physicsContinuum_0.enable(KOmegaTurbulence.class);

    physicsContinuum_0.enable(SstKwTurbModel.class);

    physicsContinuum_0.enable(KwAllYplusWallTreatment.class);

    physicsContinuum_0.enable(SrhModel.class);

    ImplicitUnsteadySolver implicitUnsteadySolver_0 = 
      ((ImplicitUnsteadySolver) simulation_0.getSolverManager().getSolver(ImplicitUnsteadySolver.class));

    implicitUnsteadySolver_0.getTimeDiscretizationOption().setSelected(TimeDiscretizationOption.Type.SECOND_ORDER);

    ScalarGlobalParameter scalarGlobalParameter_7 = 
      (ScalarGlobalParameter) simulation_0.get(GlobalParameterManager.class).createGlobalParameter(ScalarGlobalParameter.class, "Scalar");

    scalarGlobalParameter_7.setPresentationName("timeStep");

    scalarGlobalParameter_7.getQuantity().setValueAndUnits(2.5E-4, units_1);

    Units units_8 = 
      simulation_0.getUnitsManager().getInternalUnits(new IntVector(new int[] {0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0}));

    implicitUnsteadySolver_0.getTimeStep().setDefinition("${timeStep}");

    SegregatedFlowSolver segregatedFlowSolver_0 = 
      ((SegregatedFlowSolver) simulation_0.getSolverManager().getSolver(SegregatedFlowSolver.class));

    segregatedFlowSolver_0.getSchemeOption().setSelected(ImplicitSchemeOption.Type.SIMPLEC);

    StepStoppingCriterion stepStoppingCriterion_0 = 
      ((StepStoppingCriterion) simulation_0.getSolverStoppingCriterionManager().getSolverStoppingCriterion("Maximum Steps"));

    stepStoppingCriterion_0.setIsUsed(false);

    ScalarGlobalParameter scalarGlobalParameter_8 = 
      (ScalarGlobalParameter) simulation_0.get(GlobalParameterManager.class).createGlobalParameter(ScalarGlobalParameter.class, "Scalar");

    scalarGlobalParameter_8.setPresentationName("t_end");

    PhysicalTimeStoppingCriterion physicalTimeStoppingCriterion_0 = 
      ((PhysicalTimeStoppingCriterion) simulation_0.getSolverStoppingCriterionManager().getSolverStoppingCriterion("Maximum Physical Time"));

    physicalTimeStoppingCriterion_0.getMaximumTime().setDefinition("$t_end}");

    physicalTimeStoppingCriterion_0.getMaximumTime().setDefinition("${t_end}");

    InnerIterationStoppingCriterion innerIterationStoppingCriterion_0 = 
      ((InnerIterationStoppingCriterion) simulation_0.getSolverStoppingCriterionManager().getSolverStoppingCriterion("Maximum Inner Iterations"));

    IntegerValue integerValue_0 = 
      innerIterationStoppingCriterion_0.getMaxIterations();

    integerValue_0.getQuantity().setValue(3.0);

    integerValue_0.getQuantity().setValue(5.0);
  }
}
