// Simcenter STAR-CCM+ macro: addition_macros1.java
// Written by Simcenter STAR-CCM+ 21.02.007
package macro;

import java.util.*;

import star.common.*;
import star.base.neo.*;
import star.base.report.*;
import star.energy.*;

public class addition_macros1 extends StarMacro {

  @Override
  public void execute() {
    execute0();
  }

  private void execute0() {

    Simulation simulation_0 = 
      getActiveSimulation();

    HeatTransferReport heatTransferReport_0 = 
      simulation_0.getReportManager().create("star.energy.HeatTransferReport");

    heatTransferReport_0.getParts().setQuery(null);

    Region region_0 = 
      simulation_0.getRegionManager().getRegion("TVS_Assembly");

    Boundary boundary_0 = 
      region_0.getBoundaryManager().getBoundary("rod_s1");

    Boundary boundary_3 = 
      region_0.getBoundaryManager().getBoundary("rod_s2");

    heatTransferReport_0.getParts().setObjects(boundary_0, boundary_3);

    heatTransferReport_0.setPresentationName("Q_W_all");

    VolumeIntegralReport volumeIntegralReport_0 = 
      simulation_0.getReportManager().create("star.base.report.VolumeIntegralReport");

    volumeIntegralReport_0.setPresentationName("Volume_all");

    UserFieldFunction userFieldFunction_2 = 
      ((UserFieldFunction) simulation_0.getFieldFunctionManager().getFunction("MB_One"));

    volumeIntegralReport_0.setFieldFunction(userFieldFunction_2);

    volumeIntegralReport_0.getParts().setQuery(null);

    volumeIntegralReport_0.getParts().setObjects(region_0);

    ExpressionReport expressionReport_0 = 
      simulation_0.getReportManager().create("star.base.report.ExpressionReport");

    expressionReport_0.setPresentationName("q_v_stock");

    Units units_3 = 
      simulation_0.getUnitsManager().getPreferredUnits(Dimensions.Builder().power(1).build());

    Units units_4 = 
      simulation_0.getUnitsManager().getPreferredUnits(Dimensions.Builder().length(3).build());

    expressionReport_0.setDefinition("${Q_W_all}/${Volume_all}");

    expressionReport_0.setDimensions(Dimensions.Builder().length(-3).power(1).build());

    simulation_0.getReportManager().getGroupsManager().createGroup("New Group");

    ((ClientServerObjectGroup) simulation_0.getReportManager().getGroupsManager().getObject("New Group")).setPresentationName("EnergySource");

    ((ClientServerObjectGroup) simulation_0.getReportManager().getGroupsManager().getObject("EnergySource")).getGroupsManager().groupObjects("EnergySource", new ArrayList<>(Arrays.<ClientServerObject>asList(expressionReport_0, heatTransferReport_0, volumeIntegralReport_0)));

    VolumeIntegralReport volumeIntegralReport_1 = 
      simulation_0.getReportManager().create("star.base.report.VolumeIntegralReport", ((ClientServerObjectGroup) simulation_0.getReportManager().getGroupsManager().getObject("EnergySource")));

    PrimitiveFieldFunction primitiveFieldFunction_0 = 
      ((PrimitiveFieldFunction) simulation_0.getFieldFunctionManager().getFunction("UserSpecifiedEnergySource"));

    volumeIntegralReport_1.setFieldFunction(primitiveFieldFunction_0);

    volumeIntegralReport_1.getParts().setQuery(null);

    volumeIntegralReport_1.getParts().setObjects(region_0);

    volumeIntegralReport_1.setPresentationName("EnergySource_W_calc");
  }
}
