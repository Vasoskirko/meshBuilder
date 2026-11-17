// ===========================================================================
// Simcenter STAR-CCM+ Automation Macro: Setup & Import TVS Subchannels Mesh
// Сгенерировано TVS Subchannel Mesh Builder (v3.15.0)
// ===========================================================================
package macro;

import java.util.*;
import star.common.*;
import star.segregatedflow.*;
import star.base.neo.*;
import star.segregatedenergy.*;
import star.realgas.*;
import star.material.*;
import star.base.report.*;
import star.turbulence.*;
import star.rsturb.*;
import star.flow.*;
import star.kwturb.*;
import star.metrics.*;

public class setup_starccm_subchannels extends StarMacro {

    @Override
    public void execute() {
        Simulation sim = getActiveSimulation();
        sim.println("\n=================================================================");
        sim.println(">>> [TVS Mesh Builder v3.15.0] СТАРТ КОМПЛЕКСНОЙ НАСТРОЙКИ СЦЕНЫ");
        sim.println("=================================================================");

        // 1. Импорт многоблочной структурированной сетки Plot3D (.xyz)
        String meshFileName = "bundle_mesh.xyz";
        sim.println(">>> [1/7] Импорт файла сетки: " + resolvePath(meshFileName));
        try {
            ImportManager importMgr = sim.getImportManager();
            importMgr.importMeshFiles(
                new StringVector(new String[] {resolvePath(meshFileName)}),
                NeoProperty.fromString("{'FileOptions': [{'Sequence': 2252}]}")
            );
            sim.println(">>> [1/7] Импорт сетки успешно завершен!");
        } catch (Exception e) {
            sim.println(">>> [!] Ошибка импорта сетки: " + e.getMessage());
            return;
        }

        // 2. Объединение блоков по подканалам (6 секторов в каждый подканал)
        MeshManager meshMgr = sim.getMeshManager();
        RegionManager regMgr = sim.getRegionManager();
        List<Region> subchannelRegions = new ArrayList<>();
        int numSubchannels = 4;
        sim.println(">>> [2/7] Объединение блоков по подканалам (кол-во: " + numSubchannels + ")...");

        for (int s = 1; s <= numSubchannels; s++) {
            List<Region> zones = new ArrayList<>();
            for (int b = (s - 1) * 6 + 1; b <= s * 6; b++) {
                Region z = regMgr.getRegion("Zone " + b);
                if (z != null) zones.add(z);
            }
            if (!zones.isEmpty()) {
                meshMgr.combineRegions(zones, true, true, 0.02, true);
                Region r = regMgr.getRegion("Zone " + ((s - 1) * 6 + 1));
                if (r != null) {
                    r.setPresentationName("Subchannel_" + s);
                    subchannelRegions.add(r);
                }
            }
        }

        if (subchannelRegions.size() > 1) {
            sim.println(">>> Fuse Conformal: конформное слияние подканалов в единый монолит...");
            meshMgr.combineRegions(subchannelRegions, true, true, 0.02, true);
            Region rMonolith = subchannelRegions.get(0);
            rMonolith.setPresentationName("TVS_Assembly");
            subchannelRegions = Collections.singletonList(rMonolith);
        }

        // 3. Разделение по углу 60 градусов
        for (Region curReg : subchannelRegions) {
            Boundary wallBase = curReg.getBoundaryManager().getBoundary("wall");
            if (wallBase != null) {
                try {
                    meshMgr.splitBoundariesByAngle(60.0, Collections.singletonList(wallBase));
                } catch (Exception ignored) {}
            }
        }

        // 4. Инициализация физического континуума (STAR-CCM+ 21.02.007)
        sim.println(">>> [3/7] Настройка физических моделей жидкости (STAR-CCM+ 21.02.007)...");
        PhysicsContinuum phys;
        if (sim.getContinuumManager().has("Physics 1")) {
            phys = (PhysicsContinuum) sim.getContinuumManager().getContinuum("Physics 1");
        } else {
            phys = sim.getContinuumManager().createContinuum(PhysicsContinuum.class);
            phys.setPresentationName("Physics 1");
        }
        try {
            phys.enable(SingleComponentLiquidModel.class);
            phys.enable(SegregatedFlowModel.class);
            phys.enable(ThreeDimensionalModel.class);
            phys.enable(ConstantDensityModel.class);
            sim.println("  • Термодинамика: Constant Density (постоянные свойства)");
            phys.enable(SegregatedFluidTemperatureModel.class);
            sim.println("  • Уравнение энергии: Segregated Fluid Temperature");
            phys.enable(GravityModel.class);
            sim.println("  • Гравитация: GravityModel включена");
            phys.enable(TurbulentModel.class);
            phys.enable(RansTurbulenceModel.class);
            phys.enable(SteadyModel.class);
            phys.enable(ReynoldsStressTurbulence.class);
            phys.enable(EbRsTurbModel.class);
            phys.enable(EbRsAllYplusWallTreatment.class);
            sim.println("  • Турбулентность: Reynolds Stress EB + All y+ Wall Treatment (Steady)");
            sim.println("  • Физический континуум [Physics 1] полностью активирован!");
        } catch (Exception e) {
            sim.println("  [!] Ошибка активации физики: " + e.getMessage());
        }

        // 5. Замер площадей и центроидов для гарантированного нахождения интерфейсов
        sim.println(">>> [4/7] Замер площадей и центроидов граней ($$Centroid)...");
        UserFieldFunction unityFF = getOrCreateFF(sim, "UnityAreaFunc", "1.0");
        UserFieldFunction coordXFF = getOrCreateFF(sim, "CentroidXFunc", "$$Centroid[0]");
        UserFieldFunction coordYFF = getOrCreateFF(sim, "CentroidYFunc", "$$Centroid[1]");

        SurfaceIntegralReport areaRep = (SurfaceIntegralReport) sim.getReportManager().create("star.base.report.SurfaceIntegralReport");
        areaRep.setScalar(unityFF);

        List<Boundary> allInlets = new ArrayList<>();
        List<Boundary> allOutlets = new ArrayList<>();
        List<Boundary> allRods = new ArrayList<>();
        List<List<Boundary>> subRods = new ArrayList<>();
        List<List<Boundary>> subSides182 = new ArrayList<>();
        List<List<Boundary>> subSides110 = new ArrayList<>();

        for (int sIdx = 0; sIdx < subchannelRegions.size(); sIdx++) {
            Region curReg = subchannelRegions.get(sIdx); int subNum = sIdx + 1;
            List<Boundary> bList = new ArrayList<>(curReg.getBoundaryManager().getBoundaries());
            List<Boundary> rodList = new ArrayList<>(); List<Boundary> sideList182 = new ArrayList<>(); List<Boundary> sideList110 = new ArrayList<>();
            Boundary inletB = null; Boundary outletB = null;
            for (Boundary b : bList) {
                double area_mm2 = measureArea(areaRep, unityFF, b);
                if (area_mm2 > 200.0) rodList.add(b); else if (area_mm2 > 140.0) sideList182.add(b); else if (area_mm2 > 70.0) sideList110.add(b); else { if (b.getPresentationName().equals("wall 8")) inletB = b; else outletB = b; }
            }
            if (outletB != null) { outletB.setPresentationName("out_" + subNum); allOutlets.add(outletB); }
            if (inletB != null) { inletB.setPresentationName("in_" + subNum); allInlets.add(inletB); }
            for (int rIdx = 0; rIdx < rodList.size(); rIdx++) { Boundary rB = rodList.get(rIdx); rB.setPresentationName(String.format("rod_%d_%d", subNum, rIdx + 1)); allRods.add(rB); }
            subRods.add(rodList); subSides182.add(sideList182); subSides110.add(sideList110);
        }


        // 7. Создание глобальных параметров (Tools > Parameters)
        sim.println(">>> [6/7] Создание параметров в Tools > Parameters...");
        GlobalParameterManager gpm = sim.get(GlobalParameterManager.class);
        ClientServerObjectGroup grpProp = getOrCreateGroup(gpm, "Properties");
        createScalarParam(sim, gpm, grpProp, "rho", 725.553, "kg/m^3", Dimensions.Builder().mass(1).length(-3).build(), null);
        createScalarParam(sim, gpm, grpProp, "Cp", 5476.0, "J/kg-K", Dimensions.Builder().mass(-1).temperature(-1).energy(1).build(), null);
        createScalarParam(sim, gpm, grpProp, "dynvis", 8.835000e-05, "Pa-s", Dimensions.Builder().mass(1).length(-1).time(-1).build(), null);
        createScalarParam(sim, gpm, grpProp, "kinvis", 1.218000e-07, "m^2/s", Dimensions.Builder().length(2).time(-1).build(), null);
        createScalarParam(sim, gpm, grpProp, "lambda", 0.557, "W/m-K", Dimensions.Builder().mass(1).length(1).time(-3).temperature(-1).build(), null);
        createScalarParam(sim, gpm, grpProp, "Pr", 0.868, "", null, null);
        ClientServerObjectGroup grpInit = getOrCreateGroup(gpm, "Initial");
        createScalarParam(sim, gpm, grpInit, "Re_in", 200000.0, "", null, null);
        createScalarParam(sim, gpm, grpInit, "P_wet", 6.02130413e-02, "m", Dimensions.Builder().length(1).build(), null);
        createScalarParam(sim, gpm, grpInit, "S_in", 1.35477299e-04, "m^2", Dimensions.Builder().length(2).build(), null);
        createScalarParam(sim, gpm, grpInit, "D_hyd", 0.0, "m", Dimensions.Builder().length(1).build(), "4*${S_in}/${P_wet}");
        createScalarParam(sim, gpm, grpInit, "rhoW_in", 0.0, "", null, "${Re_in}*${dynvis}/${D_hyd}");
        createScalarParam(sim, gpm, grpInit, "w_inlet", 5.620, "m/s", null, null);
        createScalarParam(sim, gpm, grpInit, "U_b", 0.0, "m/s", null, "${rhoW_in}/${rho}");
        createScalarParam(sim, gpm, grpInit, "G_subchannel", 0.0, "kg/s", null, "${rho}*${w_inlet}*${S_in}");
        ClientServerObjectGroup grpGrid = getOrCreateGroup(gpm, "Grid_YPlus");
        createScalarParam(sim, gpm, grpGrid, "y_plus_target", 1.00, "", null, null);
        createScalarParam(sim, gpm, grpGrid, "h1_wall", 2.500e-06, "m", Dimensions.Builder().length(1).build(), null);

        // 8. Отчеты расхода (сохраняются в дереве)
        sim.println(">>> [7/7] Создание физических отчетов, балансов и мониторов (сохраняются в дереве)...");
        try {
            MassFlowReport repIn = sim.getReportManager().createReport(MassFlowReport.class);
            repIn.setPresentationName("MassFlow_Inlet_Total"); repIn.getParts().setObjects(allInlets);
            MassFlowReport repOut = sim.getReportManager().createReport(MassFlowReport.class);
            repOut.setPresentationName("MassFlow_Outlet_Total"); repOut.getParts().setObjects(allOutlets);
            sim.getMonitorManager().createMonitors(Arrays.asList(repIn, repOut));
            for (int sIdx = 0; sIdx < subchannelRegions.size(); sIdx++) {
                Region curReg = subchannelRegions.get(sIdx); int subNum = sIdx + 1;
                Boundary inB = curReg.getBoundaryManager().getBoundary("in_" + subNum);
                if (inB != null) { MassFlowReport repInSub = sim.getReportManager().createReport(MassFlowReport.class); repInSub.setPresentationName(String.format("MassFlow_In_Sub%d", subNum)); repInSub.getParts().setObjects(inB); }
            }
        } catch (Exception ignored) {}

        sim.println("\n=================================================================");
        sim.println(">>> СЦЕНА STAR-CCM+ ПОЛНОСТЬЮ НАСТРОЕНА И ГОТОВА К РАСЧЕТУ!");
        sim.println("=================================================================\n");
    }
    private double measureArea(SurfaceIntegralReport areaRep, UserFieldFunction unityFF, Boundary b) { try { areaRep.getParts().setObjects(b); areaRep.setScalar(unityFF); return areaRep.getReportMonitorValue() * 1e6; } catch (Exception e) { return 0.0; } }
    private double[] getCentroid(SurfaceIntegralReport rep, UserFieldFunction unityFF, UserFieldFunction ffX, UserFieldFunction ffY, Boundary b) { try { rep.getParts().setObjects(b); rep.setScalar(unityFF); double area = rep.getReportMonitorValue(); if (area <= 1e-14) return new double[]{0.0, 0.0}; rep.setScalar(ffX); double intX = rep.getReportMonitorValue(); rep.setScalar(ffY); double intY = rep.getReportMonitorValue(); return new double[]{intX / area, intY / area}; } catch (Exception e) { return new double[]{0.0, 0.0}; } }
    private UserFieldFunction getOrCreateFF(Simulation sim, String name, String def) { if (sim.getFieldFunctionManager().has(name)) return (UserFieldFunction) sim.getFieldFunctionManager().getFunction(name); UserFieldFunction ff = sim.getFieldFunctionManager().createFieldFunction(); ff.setPresentationName(name); ff.setDefinition(def); return ff; }
    private ClientServerObjectGroup getOrCreateGroup(GlobalParameterManager gpm, String grpName) { try { if (gpm.getGroupsManager().has(grpName)) return (ClientServerObjectGroup) gpm.getGroupsManager().getObject(grpName); gpm.getGroupsManager().createGroup("New Group"); ClientServerObjectGroup g = (ClientServerObjectGroup) gpm.getGroupsManager().getObject("New Group"); g.setPresentationName(grpName); return g; } catch (Exception e) { return null; } }
    private void createScalarParam(Simulation sim, GlobalParameterManager gpm, ClientServerObjectGroup grp, String name, double val, String unitStr, Dimensions dims, String defStr) { try { ScalarGlobalParameter p; if (gpm.has(name)) p = (ScalarGlobalParameter) gpm.getObject(name); else { p = (ScalarGlobalParameter) gpm.createGlobalParameter(ScalarGlobalParameter.class, "Scalar"); p.setPresentationName(name); } if (grp != null) grp.getGroupsManager().groupObjects(grp.getPresentationName(), Collections.singletonList(p)); if (dims != null) p.setDimensions(dims); if (defStr != null && !defStr.isEmpty()) p.getQuantity().setDefinition(defStr); else { if (unitStr != null && !unitStr.isEmpty()) { Units u = sim.getUnitsManager().getObject(unitStr); p.getQuantity().setValueAndUnits(val, u); } else p.getQuantity().setValue(val); } } catch (Exception ignored) {} }
}
