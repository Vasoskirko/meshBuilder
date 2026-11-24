// Simcenter STAR-CCM+ macro: setup_starccm_subchannels.java
// Written by Simcenter STAR-CCM+ 21.02.007
package macro;

import java.util.*;

import star.common.*;
import star.base.neo.*;
import star.vis.*;
import star.energy.*;
import star.flow.*;

public class setup_starccm_subchannels extends StarMacro {

  @Override
  public void execute() {
    execute0();
  }

  private void execute0() {

    Simulation simulation_0 = 
      getActiveSimulation();

    simulation_0.getSceneManager().createGeometryScene("Geometry Scene", "Outline", "Surface", 1, null);

    Scene scene_0 = 
      simulation_0.getSceneManager().getScene("Geometry Scene 1");

    scene_0.resetCamera();

    CurrentView currentView_0 = 
      scene_0.getCurrentView();

    currentView_0.setInput(new DoubleVector(new double[] {-5.625240025910749E-4, 0.010267270443095746, 0.43807911795471655}), new DoubleVector(new double[] {-5.625240025910749E-4, 0.010267270443095746, 0.4517849836348215}), new DoubleVector(new double[] {0.0, 1.0, 0.0}), 0.15016747279271436, 0, 30.0);

    scene_0.setPresentationName("Geometry");

    currentView_0.setInput(new DoubleVector(new double[] {-6.756629250991696E-4, 0.009081604276000932, 0.3054236981495598}), new DoubleVector(new double[] {-0.006718802157178724, -0.05424890631823482, 0.44323078210210937}), new DoubleVector(new double[] {-0.008707008450467428, 0.9087528402474574, 0.41724388952508923}), 0.15016747279271436, 0, 30.0);

    currentView_0.setInput(new DoubleVector(new double[] {0.013217282123532646, 0.026796762026963183, 0.30294187810824275}), new DoubleVector(new double[] {7.40463129192278E-4, -0.10395702125655135, 0.5874618894107381}), new DoubleVector(new double[] {-0.008707008450467428, 0.9087528402474574, 0.41724388952508923}), 0.15016747279271436, 0, 30.0);

    currentView_0.setInput(new DoubleVector(new double[] {0.008122223025997402, -0.009959987756356831, 0.2881691842225904}), new DoubleVector(new double[] {-0.004269913561936635, -0.13982632168116868, 0.5707581072213461}), new DoubleVector(new double[] {-0.008707008450467428, 0.9087528402474574, 0.41724388952508923}), 0.15016747279271436, 0, 30.0);

    currentView_0.setInput(new DoubleVector(new double[] {0.009781694955685144, 0.009693842795321456, 0.2788801655960947}), new DoubleVector(new double[] {0.005174230078804233, -0.038591177951662864, 0.38394828908499484}), new DoubleVector(new double[] {-0.008707008450467428, 0.9087528402474574, 0.41724388952508923}), 0.15016747279271436, 0, 30.0);

    MeshManager meshManager_0 = 
      simulation_0.getMeshManager();

    Region region_0 = 
      simulation_0.getRegionManager().getRegion("TVS_Assembly");

    Boundary boundary_0 = 
      region_0.getBoundaryManager().getBoundary("rod_s1_R9_part2");

    Boundary boundary_1 = 
      region_0.getBoundaryManager().getBoundary("rod_s1_R13_part1");

    Boundary boundary_2 = 
      region_0.getBoundaryManager().getBoundary("rod_s1_R14_part3");

    meshManager_0.combineBoundaries(new ArrayList<>(Arrays.<Boundary>asList(boundary_0, boundary_1, boundary_2)));

    Boundary boundary_3 = 
      region_0.getBoundaryManager().getBoundary("rod_s2_R13_part4");

    Boundary boundary_4 = 
      region_0.getBoundaryManager().getBoundary("rod_s2_R14_part6");

    Boundary boundary_5 = 
      region_0.getBoundaryManager().getBoundary("rod_s2_R17_part5");

    meshManager_0.combineBoundaries(new ArrayList<>(Arrays.<Boundary>asList(boundary_3, boundary_4, boundary_5)));

    boundary_0.setPresentationName("rod_s1");

    boundary_3.setPresentationName("rod_s2");

    Boundary boundary_6 = 
      region_0.getBoundaryManager().getBoundary("sym/per");

    Boundary boundary_7 = 
      region_0.getBoundaryManager().getBoundary("sym/per 4");

    BoundaryInterface boundaryInterface_0 = 
      simulation_0.getInterfaceManager().createBoundaryInterface(boundary_6, boundary_7, "Interface");

    Boundary boundary_8 = 
      region_0.getBoundaryManager().getBoundary("sym/per 2");

    Boundary boundary_9 = 
      region_0.getBoundaryManager().getBoundary("sym/per 3");

    BoundaryInterface boundaryInterface_1 = 
      simulation_0.getInterfaceManager().createBoundaryInterface(boundary_8, boundary_9, "Interface");

    Boundary boundary_10 = 
      region_0.getBoundaryManager().getBoundary("Inlet");

    Boundary boundary_11 = 
      region_0.getBoundaryManager().getBoundary("Outlet");

    BoundaryInterface boundaryInterface_2 = 
      simulation_0.getInterfaceManager().createBoundaryInterface(boundary_10, boundary_11, "Interface");

    boundary_0.getConditions().get(WallThermalOption.class).setSelected(WallThermalOption.Type.HEAT_FLUX);

    boundary_3.getConditions().get(WallThermalOption.class).setSelected(WallThermalOption.Type.HEAT_FLUX);

    boundaryInterface_0.getTopology().setSelected(InterfaceConfigurationOption.Type.PERIODIC);

    boundaryInterface_1.getTopology().setSelected(InterfaceConfigurationOption.Type.PERIODIC);

    FullyDevelopedInterface fullyDevelopedInterface_0 = 
      ((FullyDevelopedInterface) simulation_0.get(ConditionTypeManager.class).get(FullyDevelopedInterface.class));

    boundaryInterface_2.setInterfaceType(fullyDevelopedInterface_0);

    boundaryInterface_2.getTopology().setSelected(InterfaceConfigurationOption.Type.PERIODIC);

    boundaryInterface_2.getConditions().get(FullyDevelopedFlowOption.class).setSelected(FullyDevelopedFlowOption.Type.MASS_FLOW_RATE);

    Units units_0 = 
      simulation_0.getUnitsManager().getPreferredUnits(Dimensions.Builder().mass(1).time(-1).build());

    FullyDevelopedMassFlowRate fullyDevelopedMassFlowRate_0 = 
      boundaryInterface_2.getValues().get(FullyDevelopedMassFlowRate.class);

    fullyDevelopedMassFlowRate_0.getFullyDevelopedMassFlowRate().setDefinition("${G_subchannel}");

    UserFieldFunction userFieldFunction_0 = 
      simulation_0.getFieldFunctionManager().createFieldFunction();

    userFieldFunction_0.getTypeOption().setSelected(FieldFunctionTypeOption.Type.SCALAR);

    userFieldFunction_0.setSyncName(true);

    userFieldFunction_0.setPresentationName("Sub1_HeatFlux");

    userFieldFunction_0.setDefinition("10000");

    userFieldFunction_0.setDimensions(Dimensions.Builder().length(-2).power(1).build());

    UserFieldFunction userFieldFunction_1 = 
      simulation_0.getFieldFunctionManager().createFieldFunction();

    userFieldFunction_1.setPresentationName("Sub1_HeatFlux copy");

    userFieldFunction_1.copyProperties(userFieldFunction_0);

    simulation_0.getFieldFunctionManager().getGroupsManager().groupObjects("", new ArrayList<>(Arrays.<ClientServerObject>asList(userFieldFunction_1)));

    userFieldFunction_1.setPresentationName("Sub2_HeatFlux");

    userFieldFunction_1.setDefinition("300000");

    HeatFluxProfile heatFluxProfile_0 = 
      boundary_0.getValues().get(HeatFluxProfile.class);

    heatFluxProfile_0.setMethod(FunctionScalarProfileMethod.class);

    heatFluxProfile_0.getMethod(FunctionScalarProfileMethod.class).setFieldFunction(userFieldFunction_0);

    HeatFluxProfile heatFluxProfile_1 = 
      boundary_3.getValues().get(HeatFluxProfile.class);

    heatFluxProfile_1.setMethod(FunctionScalarProfileMethod.class);

    heatFluxProfile_1.getMethod(FunctionScalarProfileMethod.class).setFieldFunction(userFieldFunction_1);

    region_0.getConditions().get(EnergyUserVolumeSourceOption.class).setSelected(EnergyUserVolumeSourceOption.Type.VOLUMETRIC_HEAT_SOURCE);

    Units units_1 = 
      simulation_0.getUnitsManager().getPreferredUnits(Dimensions.Builder().build());

    Units units_2 = 
      simulation_0.getUnitsManager().getInternalUnits(new IntVector(new int[] {0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, -1, 0, 0, 0, 0, 0, 0, 0, 0}));

    VolumetricHeatSourceProfile volumetricHeatSourceProfile_0 = 
      region_0.getValues().get(VolumetricHeatSourceProfile.class);

    volumetricHeatSourceProfile_0.getMethod(ConstantScalarProfileMethod.class).getQuantity().setDefinition("${q_v_stock}");
  }
}
