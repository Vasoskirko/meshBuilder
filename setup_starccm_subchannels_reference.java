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
import star.energy.*;
import star.base.report.*;
import star.turbulence.*;
import star.rsturb.*;
import star.flow.*;
import star.kwturb.*;
import star.metrics.*;
import star.vis.*;

public class setup_starccm_subchannels extends StarMacro {
    private final String exportSettings = "{\"expected_cells\": 26400000, \"fluid_density\": 747.3390805476422, \"fluid_dynamic_viscosity\": 9.271750031043231e-05, \"height_m\": 0.3, \"options\": {\"axis_probes\": true, \"create_bad_cells\": false, \"create_field_functions\": true, \"create_mass_reports\": true, \"create_parameters\": true, \"create_physics\": true, \"create_quality_histograms\": false, \"create_quality_scene\": false, \"create_summary\": true, \"enable_gravity\": false, \"enable_thermal\": true, \"evaluate_solution_reports\": false, \"field_functions\": [\"z_fraction\", \"speed\", \"mass_flux\", \"quality\", \"balances\"], \"gap_sections\": true, \"gravity_axis\": \"-Z\", \"group_objects\": true, \"import_mesh\": true, \"initialize_solution\": true, \"inlet_outlet_mode\": \"single\", \"inner_fuse\": true, \"inter_fuse\": true, \"key_planes\": true, \"mean_start_step\": 1, \"n_planes\": 11, \"n_sub_planes\": 11, \"quality_bins\": 50, \"region_mode\": \"monolithic\", \"rename_boundaries\": true, \"rod_wall_mode\": \"sectors_60\", \"selected_subchannels\": [1, 2], \"sub_planes\": true, \"subchannel_reports\": [\"geometry\", \"hydraulics\", \"wall\", \"thermal\"], \"time_mean_fields\": [\"velocity\", \"pressure\", \"temperature\", \"density\", \"viscosity\", \"wall_shear\", \"wall_heat_flux\"], \"time_step\": 0.0001, \"turbulence_model\": \"hybrid_srh\", \"use_iapws\": false}, \"subchannels\": 2}";

    @Override
    public void execute() {
        Simulation sim = getActiveSimulation();
        issues.clear();
        sim.println("\n=================================================================");
        sim.println(">>> [TVS Mesh Builder v3.15.0] СТАРТ КОМПЛЕКСНОЙ НАСТРОЙКИ СЦЕНЫ");
        sim.println("=================================================================");

        final String exportFingerprint = "3533d14d276cf710439335d115414c2b5bedfcd82eab18b0d44b5283bf25a3c0";
        final long expectedCells = 26400000L;
        MeshManager meshMgr = sim.getMeshManager();
        RegionManager regMgr = sim.getRegionManager();
        List<Region> subchannelRegions = preparedRegions(sim,exportFingerprint,1);
        boolean reuse = !subchannelRegions.isEmpty();
        PhysicsContinuum setupPhysics = null;
        boolean physicalValuesConfigured = false;
        List<Boundary> allInlets = new ArrayList<>(), allOutlets = new ArrayList<>(), allRods = new ArrayList<>();
        class GapCandidate {
            Region reg; Boundary bnd; double cx; double cy; int subNum; boolean paired = false;
            GapCandidate(Region r, Boundary b, double x, double y, int n) { reg=r;bnd=b;cx=x;cy=y;subNum=n; }
        }
        List<GapCandidate> gapCandidates = new ArrayList<>();
        int pairCount = 0; List<String> pairedNames = new ArrayList<>();
        if (!reuse) {
        if (!regMgr.getRegions().isEmpty()) throw new IllegalStateException("Use an empty simulation for first import; existing regions are not replaced.");
        final double[][] boundaryGeometry = boundaryGeometry();
        // 1. Импорт многоблочной структурированной сетки Plot3D (.xyz)
        String meshFileName = "bundle_mesh_200k.xyz";
        sim.println(">>> [1/7] Импорт файла сетки: " + resolvePath(meshFileName));
        try {
            ImportManager importMgr = sim.getImportManager();
            importMgr.importMeshFiles(
                new StringVector(new String[] {resolvePath(meshFileName)}),
                NeoProperty.fromString("{'FileOptions': [{'Sequence': 2252}]}")
            );
            sim.println(">>> [1/7] Импорт сетки успешно завершен!");
        } catch (Exception e) {
            warn(sim, ">>> [!] Ошибка импорта сетки: " + e.getMessage());
            return;
        }

        // 2. Объединение блоков по подканалам (6 секторов в каждый подканал)
        int numSubchannels = 2;
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

        // Preserve source-sector boundaries BEFORE inter-subchannel Fuse.
        for (int source=0;source<subchannelRegions.size();source++) {
            Region original=subchannelRegions.get(source);
            Boundary originalWall=original.getBoundaryManager().getBoundary("wall");
            if (originalWall!=null) meshMgr.splitBoundariesByAngle(60.0,Collections.singletonList(originalWall));
            int part=0; for (Boundary boundary : original.getBoundaryManager().getBoundaries())
                boundary.setPresentationName("SRC_s"+(source+1)+"_part"+(++part));
        }
        if (subchannelRegions.size() > 1) {
            sim.println(">>> Fuse Conformal: конформное слияние подканалов в единый монолит...");
            meshMgr.combineRegions(subchannelRegions, true, true, 0.02, true);
            Region rMonolith = subchannelRegions.get(0);
            rMonolith.setPresentationName("TVS_Assembly");
            subchannelRegions = Collections.singletonList(rMonolith);
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
            phys.enable(TurbulentModel.class);
            phys.enable(RansTurbulenceModel.class);
            phys.enable(ImplicitUnsteadyModel.class);
            phys.enable(KOmegaTurbulence.class);
            phys.enable(SstKwTurbModel.class);
            phys.enable(KwAllYplusWallTreatment.class);
            phys.enable(SrhModel.class);
            sim.println("  • Турбулентность: Scale-Resolving Hybrid (SRH) + SST k-omega (Unsteady)");
            setupPhysics = phys; own(sim,phys);
            sim.println("  • Физический континуум [Physics 1] полностью активирован!");
        } catch (Exception e) {
            warn(sim, "  [!] Ошибка активации физики: " + e.getMessage());
        }

        // 5. Замер площадей и центроидов для универсального сопряжения
        sim.println(">>> [4/7] Замер площадей и центроидов граней ($$Centroid)...");
        UserFieldFunction unityFF = getOrCreateFF(sim, "MB_One", "1.0");
        UserFieldFunction coordXFF = getOrCreateFF(sim, "MB_X", "$$Centroid[0]");
        UserFieldFunction coordYFF = getOrCreateFF(sim, "MB_Y", "$$Centroid[1]");
        UserFieldFunction coordZFF = getOrCreateFF(sim, "MB_Z", "$$Centroid[2]");
        unityFF.setDimensions(Dimensions.Builder().build());
        coordXFF.setDimensions(Dimensions.Builder().length(1).build());
        coordYFF.setDimensions(Dimensions.Builder().length(1).build());
        coordZFF.setDimensions(Dimensions.Builder().length(1).build());

        SurfaceIntegralReport areaRep = (SurfaceIntegralReport) sim.getReportManager().create("star.base.report.SurfaceIntegralReport");
        areaRep.setFieldFunction(unityFF);


        class BoundaryData {
            Boundary bnd; double area; double cx; double cy; double cz;
            BoundaryData(Boundary b, double a, double x, double y, double z) { this.bnd = b; this.area = a; this.cx = x; this.cy = y; this.cz = z; }
        }

        sim.println("\n---------------------------------------------------------------------------------------------------");
        sim.println("                        ПОЛНАЯ ГЕОМЕТРИЧЕСКАЯ ДИАГНОСТИКА ПОВЕРХНОСТЕЙ");
        sim.println("---------------------------------------------------------------------------------------------------");

        double lz_actual = 2.9999999999999999e-01;
        for (int sIdx = 0; sIdx < subchannelRegions.size(); sIdx++) {
            Region curReg = subchannelRegions.get(sIdx); int subNum = sIdx + 1;
            sim.println(String.format("[Подканал: %s]", curReg.getPresentationName()));
            sim.println("  Поверхность   | Площадь, мм² | Координаты (Xc, Yc, Zc)           | Тип");
            sim.println("  --------------+--------------+-----------------------------------+-------------------");

            List<Boundary> bList = new ArrayList<>(curReg.getBoundaryManager().getBoundaries());
            List<BoundaryData> bDataList = new ArrayList<>();

            for (Boundary b : bList) {
                double area_mm2 = measureArea(areaRep, unityFF, b);
                double[] c_xyz = getCentroid3D(areaRep, unityFF, coordXFF, coordYFF, coordZFF, b);
                bDataList.add(new BoundaryData(b, area_mm2, c_xyz[0], c_xyz[1], c_xyz[2]));
            }

            // Разделяем: торцы (Zc близко к 0 или Lz) и боковые стенки (Zc близко к Lz/2):
            List<BoundaryData> tops = new ArrayList<>();
            List<BoundaryData> laterals = new ArrayList<>();
            for (BoundaryData bd : bDataList) {
                if (bd.cz < lz_actual * 0.25 || bd.cz > lz_actual * 0.75) {
                    tops.add(bd);
                } else {
                    laterals.add(bd);
                }
            }

            for (BoundaryData bd : tops) {
                if (bd.cz > lz_actual / 2.0) {
                    bd.bnd.setPresentationName("Outlet");
                    allOutlets.add(bd.bnd);
                    sim.println(String.format("  %-13s | %12.2f | (%8.3f, %8.3f, %8.3f) | ВЫХОД (out)", bd.bnd.getPresentationName(), bd.area, bd.cx*1e3, bd.cy*1e3, bd.cz*1e3));
                } else {
                    bd.bnd.setPresentationName("Inlet");
                    allInlets.add(bd.bnd);
                    sim.println(String.format("  %-13s | %12.2f | (%8.3f, %8.3f, %8.3f) | ВХОД (in)", bd.bnd.getPresentationName(), bd.area, bd.cx*1e3, bd.cy*1e3, bd.cz*1e3));
                }
            }

            List<BoundaryData> gaps = new ArrayList<>();
            List<BoundaryData> rods = new ArrayList<>();
            Map<Boundary, Integer> rodIds = new HashMap<>();
            for (BoundaryData bd : laterals) {
                int identity = classifyBoundary(bd.area, bd.cx, bd.cy, boundaryGeometry);
                if (identity == 0) gaps.add(bd);
                else if (identity > 0) { rods.add(bd); rodIds.put(bd.bnd, identity - 1); }
                else throw new IllegalStateException("Неизвестная боковая поверхность: " + bd.bnd.getPresentationName() + "; проверьте геометрию импорта.");
            }
            for (BoundaryData bd : gaps) {
                gapCandidates.add(new GapCandidate(curReg, bd.bnd, bd.cx, bd.cy, subNum));
                sim.println(String.format("  %-13s | %12.2f | (%8.3f, %8.3f, %8.3f) | ЗАЗОР (стык/sym)", bd.bnd.getPresentationName(), bd.area, bd.cx*1e3, bd.cy*1e3, bd.cz*1e3));
            }

            List<Boundary> rodBnds = new ArrayList<>();
            for (int rIdx = 0; rIdx < rods.size(); rIdx++) {
                BoundaryData bd = rods.get(rIdx);
                String source=bd.bnd.getPresentationName().split("_",3)[1];
                bd.bnd.setPresentationName("rod_"+source+"_R"+rodIds.get(bd.bnd)+"_part"+(rIdx+1));
                rodBnds.add(bd.bnd);
                sim.println(String.format("  %-13s | %12.2f | (%8.3f, %8.3f, %8.3f) | СТЕРЖЕНЬ (rod)", bd.bnd.getPresentationName(), bd.area, bd.cx*1e3, bd.cy*1e3, bd.cz*1e3));
            }
            allRods.addAll(rodBnds);
            sim.println("  ---------------------------------------------------------------------------------------------------");
        }

        // 6. Универсальный полный геометрический поиск парных интерфейсов (if_sA_sB):
        sim.println("\n>>> [5/7] Автоматический поиск и сшивка интерфейсов (N-ячеек)...");
        for (int i = 0; i < gapCandidates.size(); i++) {
            GapCandidate ci = gapCandidates.get(i);
            if (ci.paired) continue;
            GapCandidate bestMatch = null; double minDist = 1e9;
            for (int j = 0; j < gapCandidates.size(); j++) {
                if (i == j) continue;
                GapCandidate cj = gapCandidates.get(j);
                if (cj.paired || ci.reg.equals(cj.reg)) continue;
                double dist = Math.hypot(ci.cx - cj.cx, ci.cy - cj.cy);
                if (dist < 1e-4 && dist < minDist) { minDist = dist; bestMatch = cj; }
            }
            if (bestMatch != null) {
                // Count and mark a pair only after successful interface creation.
                String ifName = String.format("if_s%d_s%d", ci.subNum, bestMatch.subNum);
                ci.bnd.setPresentationName(String.format("if_s%d_s%d", ci.subNum, bestMatch.subNum));
                bestMatch.bnd.setPresentationName(String.format("if_s%d_s%d", bestMatch.subNum, ci.subNum));
                try {
                    sim.getInterfaceManager().createBoundaryInterface(ci.bnd, bestMatch.bnd, ifName);
                    ci.paired = true; bestMatch.paired = true; pairCount++;
                    pairedNames.add(ifName);
                    sim.println(String.format("  • [OK] Сшит интерфейс: %s (зазор = %.3e м)", ifName, minDist));
                } catch (Exception e) { warn(sim, "  [!] Ошибка сшивки " + ifName + ": " + e.getMessage()); }
            }
        }
        for (GapCandidate cg : gapCandidates) {
            if (!cg.paired) cg.bnd.setPresentationName("sym/per");
        }
        sim.println(String.format("  • Всего успешно сопряжено интерфейсов: %d. Внешние зазоры назначены как sym/per.", pairCount));

        try { sim.getReportManager().remove(areaRep);  } catch (Exception ignored) {}

        List<Boundary> externalGaps = new ArrayList<>();
        for (GapCandidate gap : gapCandidates) if (!gap.paired) externalGaps.add(gap.bnd);
        // Merge only end caps; retain the separate source rod sectors.
        if (allInlets.size()>1) { Boundary inlet=allInlets.get(0); meshMgr.combineBoundaries(new ArrayList<>(allInlets)); allInlets.clear(); allInlets.add(inlet); inlet.setPresentationName("Inlet"); }
        if (allOutlets.size()>1) { Boundary outlet=allOutlets.get(0); meshMgr.combineBoundaries(new ArrayList<>(allOutlets)); allOutlets.clear(); allOutlets.add(outlet); outlet.setPresentationName("Outlet"); }
        markBoundaryRoles(sim,allInlets,allOutlets,allRods,externalGaps);
        for (int i=0;i<subchannelRegions.size();i++) {
            Region region=subchannelRegions.get(i); own(sim,region);
            mark(sim,region,"meshBuilder.Mesh." + exportFingerprint); mark(sim,region,"meshBuilder.Source." + (i+1));
        }
        for (Object object : objects(sim.getInterfaceManager())) if (object instanceof NamedObject && pairedNames.contains(((NamedObject)object).getPresentationName())) own(sim,(NamedObject)object);
        } else {
            ElementCountReport check = sim.getReportManager().createReport(ElementCountReport.class);
            try { check.getParts().setObjects(subchannelRegions); double cells=check.getReportMonitorValue(); if (!Double.isFinite(cells) || Math.abs(cells-expectedCells)>.5) throw new IllegalStateException("Managed mesh cell count changed; use a new simulation."); }
            finally { sim.getReportManager().remove(check); }
            sim.println("Same export detected: update managed analysis only; mesh, physics and boundary conditions retained.");
            for (Region region : subchannelRegions) for (Boundary b : region.getBoundaryManager().getBoundaries()) {
                if (tagged(b,"meshBuilder.Role.Inlet")) allInlets.add(b);
                if (tagged(b,"meshBuilder.Role.Outlet")) allOutlets.add(b);
                if (tagged(b,"meshBuilder.Role.Rod")) allRods.add(b);
                if (tagged(b,"meshBuilder.Role.Gap")) gapCandidates.add(new GapCandidate(region,b,0,0,0));
            }
            for (Object object : objects(sim.getInterfaceManager())) if (object instanceof NamedObject && tagged((NamedObject)object,OWNER)) { pairCount++; pairedNames.add(((NamedObject)object).getPresentationName()); }
        }
        cleanManagedDisplayNames(sim);
        if (!reuse) {
        // 7. Создание глобальных параметров с корректными размерностями (Tools > Parameters)
        sim.println(">>> [6/7] Создание параметров в Tools > Parameters...");
        GlobalParameterManager gpm = sim.get(GlobalParameterManager.class);

        createParam(sim, gpm, null, "rho", 7.4733908054764220e+02, "kg/m^3", Dimensions.Builder().mass(1).length(-3).build(), null);
        createParam(sim, gpm, null, "Cp", 5.2250980006874379e+03, "J/kg-K", Dimensions.Builder().mass(-1).temperature(-1).energy(1).build(), null);
        createParam(sim, gpm, null, "dynvis", 9.2717500310432311e-05, "Pa-s", Dimensions.Builder().mass(1).length(-1).time(-1).build(), null);
        createParam(sim, gpm, null, "kinvis", 1.240635e-07, "m^2/s", Dimensions.Builder().length(2).time(-1).build(), null);
        createParam(sim, gpm, null, "lambda", 5.7532756714098543e-01, "W/m-K", Dimensions.Builder().mass(1).length(1).time(-3).temperature(-1).build(), null);
        createParam(sim, gpm, null, "Pr", 8.4205599239443218e-01, "", null, null);
        createParam(sim, gpm, null, "T_ref", 5.6314999999999998e+02, "K", Dimensions.Builder().temperature(1).build(), null);
        createParam(sim, gpm, null, "P_ref", 1.6200000000000000e+07, "Pa", Dimensions.Builder().mass(1).length(-1).time(-2).build(), null);

        createParam(sim,gpm,null,"P_init",0.0,"Pa",Dimensions.Builder().mass(1).length(-1).time(-2).build(),null);
        createParam(sim,gpm,null,"T_init",0.0,"K",Dimensions.Builder().temperature(1).build(),"${T_ref}");
        createParam(sim,gpm,null,"U_init",3.3911028485198722e+00,"m/s",Dimensions.Builder().length(1).time(-1).build(),null);
        if (true) {
        createParam(sim, gpm, null, "Re_in", 200000.0, "", null, null);
        createParam(sim, gpm, null, "P_wet", 2.85883245e-02, "m", Dimensions.Builder().length(1).build(), null);
        createParam(sim, gpm, null, "S_in", 5.23001486e-05, "m^2", Dimensions.Builder().length(2).build(), null);
        createParam(sim, gpm, null, "D_hyd", 0.0, "m", Dimensions.Builder().length(1).build(), "4*${S_in}/${P_wet}");
        createParam(sim, gpm, null, "rhoW_in", 0.0, "kg/m^2-s", Dimensions.Builder().mass(1).length(-2).time(-1).build(), "${Re_in}*${dynvis}/${D_hyd}");
        createParam(sim, gpm, null, "U_b", 0.0, "m/s", Dimensions.Builder().length(1).time(-1).build(), "${rhoW_in}/${rho}");
        createParam(sim, gpm, null, "G_subchannel", 0.0, "kg/s", Dimensions.Builder().mass(1).time(-1).build(), "${rho}*${U_b}*${S_in}");

        createParam(sim, gpm, null, "y_plus_target", 0.80, "", null, null);
        createParam(sim, gpm, null, "h1_wall", 1.163e-06, "m", Dimensions.Builder().length(1).build(), null);

        }
        physicalValuesConfigured = configurePhysicalValues(sim,setupPhysics,subchannelRegions,false,true);
        }
        initializeFirstSolution(sim,reuse,true,physicalValuesConfigured);
        try {
            GlobalParameterManager timeManager=sim.get(GlobalParameterManager.class);
            ScalarGlobalParameter timeParameter=findOwned(sim,timeManager,"TimeStep",ScalarGlobalParameter.class);
            if (!reuse || timeParameter==null) {
                createParam(sim,timeManager,null,"TimeStep",1.0000000000000000e-04,"s",Dimensions.Builder().time(1).build(),null);
                if (findOwned(sim,timeManager,"TimeStep",ScalarGlobalParameter.class)==null) throw new IllegalStateException("TimeStep parameter unavailable");
                sim.getSolverManager().getSolver(ImplicitUnsteadySolver.class).getTimeStep().setDefinition("${TimeStep}");
                if (reuse) sim.println("  • Added TimeStep parameter and solver binding to existing simulation; no reinitialization.");
            }
        } catch (Exception e) { warn(sim,"  [!] TimeStep binding: "+e.getMessage()); }
        supportFunctions(sim,2.9999999999999999e-01, Arrays.asList("z_fraction","speed","mass_flux","quality","balances"));
        // 9. Создание сечений и зондов (Derived Parts) по рекордеру STAR-CCM+ 21.02.007:
        sim.println(">>> Создание производных деталей (Derived Parts)...");
        int planesCreated = 0;
        int probesCreated = 0;
        int[] reportCounts = new int[] {0, 0};
        try { countReport(sim,"Quality_TotalCellCount",subchannelRegions,reportCounts); }
        catch (Exception e) { warn(sim,"  [!] Total cell count: " + e.getMessage()); }
        try {
            Units uLen = sim.getUnitsManager().getPreferredUnits(Dimensions.Builder().length(1).build());
            LabCoordinateSystem labCoord = sim.getCoordinateSystemManager().getLabCoordinateSystem();
            double lz = 2.9999999999999999e-01;

            List<List<? extends NamedObject>> sourceParts = new ArrayList<>();
            UserFieldFunction mask1 = getOrCreateFF(sim, "MB_SubchannelMask_1", "(((-1.1640000000000001e-02)*($$Centroid[1]-(1.0080535700050866e-02))-(0.0000000000000000e+00)*($$Centroid[0]-(5.8200000000000005e-03)))>=-1e-16 && ((5.8200000000000005e-03)*($$Centroid[1]-(1.0080535700050866e-02))-(-1.0080535700050866e-02)*($$Centroid[0]-(-5.8200000000000005e-03)))>=-1e-16 && ((5.8200000000000005e-03)*($$Centroid[1]-(0.0000000000000000e+00))-(1.0080535700050866e-02)*($$Centroid[0]-(0.0000000000000000e+00)))>=-1e-16) ? 1.0 : 0.0");
            ThresholdPart domain1 = threshold(sim, subchannelRegions, mask1, "Subchannel_1_Domain");
            sourceParts.add(Collections.singletonList(domain1));
            UserFieldFunction mask2 = getOrCreateFF(sim, "MB_SubchannelMask_2", "(((-5.8200000000000005e-03)*($$Centroid[1]-(1.0080535700050866e-02))-(1.0080535700050866e-02)*($$Centroid[0]-(5.8200000000000005e-03)))>=-1e-16 && ((-5.8200000000000005e-03)*($$Centroid[1]-(2.0161071400101732e-02))-(-1.0080535700050866e-02)*($$Centroid[0]-(0.0000000000000000e+00)))>=-1e-16 && ((1.1640000000000001e-02)*($$Centroid[1]-(1.0080535700050866e-02))-(0.0000000000000000e+00)*($$Centroid[0]-(-5.8200000000000005e-03)))>=-1e-16) ? 1.0 : 0.0");
            ThresholdPart domain2 = threshold(sim, subchannelRegions, mask2, "Subchannel_2_Domain");
            sourceParts.add(Collections.singletonList(domain2));
            createPlaneSection(sim, labCoord, uLen, subchannelRegions, "Section_Global_Z_0mm", lz * 0.0000000000000000e+00); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, subchannelRegions, "Section_Global_Z_30mm", lz * 1.0000000000000001e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, subchannelRegions, "Section_Global_Z_60mm", lz * 2.0000000000000001e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, subchannelRegions, "Section_Global_Z_90mm", lz * 2.9999999999999999e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, subchannelRegions, "Section_Global_Z_120mm", lz * 4.0000000000000002e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, subchannelRegions, "Section_Global_Z_150mm", lz * 5.0000000000000000e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, subchannelRegions, "Section_Global_Z_180mm", lz * 5.9999999999999998e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, subchannelRegions, "Section_Global_Z_210mm", lz * 6.9999999999999996e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, subchannelRegions, "Section_Global_Z_240mm", lz * 8.0000000000000004e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, subchannelRegions, "Section_Global_Z_270mm", lz * 9.0000000000000002e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, subchannelRegions, "Section_Global_Z_300mm", lz * 1.0000000000000000e+00); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(0), "Subchannel_1_Section_Z_0mm", lz * 0.0000000000000000e+00); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(0), "Subchannel_1_Section_Z_30mm", lz * 1.0000000000000001e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(0), "Subchannel_1_Section_Z_60mm", lz * 2.0000000000000001e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(0), "Subchannel_1_Section_Z_90mm", lz * 2.9999999999999999e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(0), "Subchannel_1_Section_Z_120mm", lz * 4.0000000000000002e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(0), "Subchannel_1_Section_Z_150mm", lz * 5.0000000000000000e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(0), "Subchannel_1_Section_Z_180mm", lz * 5.9999999999999998e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(0), "Subchannel_1_Section_Z_210mm", lz * 6.9999999999999996e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(0), "Subchannel_1_Section_Z_240mm", lz * 8.0000000000000004e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(0), "Subchannel_1_Section_Z_270mm", lz * 9.0000000000000002e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(0), "Subchannel_1_Section_Z_300mm", lz * 1.0000000000000000e+00); planesCreated++;
            UserFieldFunction wallMask1=getOrCreateFF(sim,"MB_WallMask_Sub1","(((-1.1640000000000001e-02)*($$Centroid[1]-(1.0080535700050866e-02))-(0.0000000000000000e+00)*($$Centroid[0]-(5.8200000000000005e-03)))>=-1e-16 && ((5.8200000000000005e-03)*($$Centroid[1]-(1.0080535700050866e-02))-(-1.0080535700050866e-02)*($$Centroid[0]-(-5.8200000000000005e-03)))>=-1e-16 && ((5.8200000000000005e-03)*($$Centroid[1]-(0.0000000000000000e+00))-(1.0080535700050866e-02)*($$Centroid[0]-(0.0000000000000000e+00)))>=-1e-16) ? 1.0 : 0.0");
            createSubchannelAnalysis(sim,1,sourceParts.get(0),Collections.singletonList(threshold(sim,allRods,wallMask1,"Subchannel_1_RodWalls")),(PlaneSection)sim.getPartManager().getObject("Subchannel_1_Section_Z_0mm"),(PlaneSection)sim.getPartManager().getObject("Subchannel_1_Section_Z_300mm"),lz,Arrays.asList("geometry","hydraulics","wall","thermal"),true,reportCounts);
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(1), "Subchannel_2_Section_Z_0mm", lz * 0.0000000000000000e+00); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(1), "Subchannel_2_Section_Z_30mm", lz * 1.0000000000000001e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(1), "Subchannel_2_Section_Z_60mm", lz * 2.0000000000000001e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(1), "Subchannel_2_Section_Z_90mm", lz * 2.9999999999999999e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(1), "Subchannel_2_Section_Z_120mm", lz * 4.0000000000000002e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(1), "Subchannel_2_Section_Z_150mm", lz * 5.0000000000000000e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(1), "Subchannel_2_Section_Z_180mm", lz * 5.9999999999999998e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(1), "Subchannel_2_Section_Z_210mm", lz * 6.9999999999999996e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(1), "Subchannel_2_Section_Z_240mm", lz * 8.0000000000000004e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(1), "Subchannel_2_Section_Z_270mm", lz * 9.0000000000000002e-01); planesCreated++;
            createPlaneSection(sim, labCoord, uLen, sourceParts.get(1), "Subchannel_2_Section_Z_300mm", lz * 1.0000000000000000e+00); planesCreated++;
            UserFieldFunction wallMask2=getOrCreateFF(sim,"MB_WallMask_Sub2","(((-5.8200000000000005e-03)*($$Centroid[1]-(1.0080535700050866e-02))-(1.0080535700050866e-02)*($$Centroid[0]-(5.8200000000000005e-03)))>=-1e-16 && ((-5.8200000000000005e-03)*($$Centroid[1]-(2.0161071400101732e-02))-(-1.0080535700050866e-02)*($$Centroid[0]-(0.0000000000000000e+00)))>=-1e-16 && ((1.1640000000000001e-02)*($$Centroid[1]-(1.0080535700050866e-02))-(0.0000000000000000e+00)*($$Centroid[0]-(-5.8200000000000005e-03)))>=-1e-16) ? 1.0 : 0.0");
            createSubchannelAnalysis(sim,2,sourceParts.get(1),Collections.singletonList(threshold(sim,allRods,wallMask2,"Subchannel_2_RodWalls")),(PlaneSection)sim.getPartManager().getObject("Subchannel_2_Section_Z_0mm"),(PlaneSection)sim.getPartManager().getObject("Subchannel_2_Section_Z_300mm"),lz,Arrays.asList("geometry","hydraulics","wall","thermal"),true,reportCounts);
            createOrientedPlaneSection(sim, labCoord, uLen, sourceParts.get(0), "Gap_Sub1_Sub2", new double[] {0.0000000000000000e+00, 1.0080535700050866e-02, lz / 2}, new double[] {0.0000000000000000e+00, 1.0000000000000000e+00, 0}); planesCreated++;
            createMassFlowReport(sim, "MassFlow_Gap_Sub1_Sub2", Collections.singletonList((PlaneSection) sim.getPartManager().getObject("Gap_Sub1_Sub2")), reportCounts);
            createAxisLine(sim, labCoord, uLen, sourceParts.get(0), "Probe_Axis_Subchannel_1", 0.0000000000000000e+00, 6.7203571333672441e-03, lz); probesCreated++;
            createAxisLine(sim, labCoord, uLen, sourceParts.get(1), "Probe_Axis_Subchannel_2", 0.0000000000000000e+00, 1.3440714266734488e-02, lz); probesCreated++;
            sim.println(String.format("  • Производные плоскости (%d шт) и зонды (%d шт) успешно построены!", planesCreated, probesCreated));
        } catch (Exception e) { warn(sim, "  [!] Ошибка при создании Derived Parts: " + e.getMessage()); }
        warn(sim,"  [!] HYBRID: flux balances exclude dM/dt and dE/dt; they are not full transient conservation residuals.");
        createMassFlowReport(sim, "MassFlow_Inlet_Total", allInlets, reportCounts);
        createMassFlowReport(sim, "MassFlow_Outlet_Total", allOutlets, reportCounts);
        createExpressionReport(sim, "Imbalance_MassFlow", "abs(${MassFlow_Inlet_TotalReport} + ${MassFlow_Outlet_TotalReport}) / max(abs(${MassFlow_Inlet_TotalReport}), 1e-30) * 100", reportCounts);
        List<Boundary> thermalWalls = new ArrayList<>(allRods);
        for (GapCandidate gap : gapCandidates) if (!gap.paired) thermalWalls.add(gap.bnd);
        createHeatReport(sim, "Heat_Flux_Rods_Total", allRods, reportCounts);
        createHeatReport(sim, "Heat_Flux_Walls_Total", thermalWalls, reportCounts);
        createEnthalpyReport(sim, "TotalEnthalpy_Inlet", allInlets, reportCounts);
        createEnthalpyReport(sim, "TotalEnthalpy_Outlet", allOutlets, reportCounts);
        createExpressionReport(sim, "Energy_Flow_Inlet_Total", "${MassFlow_Inlet_TotalReport} * ${TotalEnthalpy_InletReport}", reportCounts);
        createExpressionReport(sim, "Energy_Flow_Outlet_Total", "${MassFlow_Outlet_TotalReport} * ${TotalEnthalpy_OutletReport}", reportCounts);
        createExpressionReport(sim, "Imbalance_Energy", "abs(${Energy_Flow_Inlet_TotalReport} + ${Energy_Flow_Outlet_TotalReport} - ${Heat_Flux_Walls_TotalReport}) / max(max(abs(${Energy_Flow_Inlet_TotalReport}), abs(${Energy_Flow_Outlet_TotalReport})), max(abs(${Heat_Flux_Walls_TotalReport}), 1e-30)) * 100", reportCounts);
        try { UserFieldFunction ff=getOrCreateFF(sim,"MB_MassBalanceSigned","${MassFlow_Inlet_TotalReport} + ${MassFlow_Outlet_TotalReport}"); ff.setDimensions(Dimensions.Builder().mass(1).time(-1).build()); }
        catch (Exception e) { warn(sim,"  [!] Mass balance field: " + e.getMessage()); }
        try { UserFieldFunction ff=getOrCreateFF(sim,"MB_EnergyBalanceSigned","${Energy_Flow_Inlet_TotalReport} + ${Energy_Flow_Outlet_TotalReport} - ${Heat_Flux_Walls_TotalReport}"); ff.setDimensions(Dimensions.Builder().mass(1).length(2).time(-3).build()); }
        catch (Exception e) { warn(sim,"  [!] Energy balance field: " + e.getMessage()); }
        createTimeMean(sim,subchannelRegions,"Velocity",1);
        createTimeMean(sim,subchannelRegions,"Pressure",1);
        createTimeMean(sim,subchannelRegions,"Temperature",1);
        createTimeMean(sim,subchannelRegions,"Density",1);
        createTimeMean(sim,subchannelRegions,"DynamicViscosity",1);
        createTimeMean(sim,allRods,"WallShearStress",1);
        createTimeMean(sim,allRods,"BoundaryHeatFlux",1);
        int[] qualityCounts = new int[] {0, 0};
        List<UserFieldFunction> badMasks = new ArrayList<>();
        try {
            FieldFunction metric = qualityField(sim, "CellQuality", "Cell Quality");
            UserFieldFunction alias = getOrCreateFF(sim,"MB_CellQuality","${" + metric.getFunctionName() + "}"); alias.setDimensions(metric.getDimensions());
        } catch (Exception e) { warn(sim, "  [!] Качество CellQuality: " + e.getMessage()); }
        try {
            FieldFunction metric = qualityField(sim, "FaceValidity", "Face Validity");
            UserFieldFunction alias = getOrCreateFF(sim,"MB_FaceValidity","${" + metric.getFunctionName() + "}"); alias.setDimensions(metric.getDimensions());
        } catch (Exception e) { warn(sim, "  [!] Качество FaceValidity: " + e.getMessage()); }
        try {
            FieldFunction metric = qualityField(sim, "VolumeChange", "Volume Change");
            UserFieldFunction alias = getOrCreateFF(sim,"MB_VolumeChange","${" + metric.getFunctionName() + "}"); alias.setDimensions(metric.getDimensions());
        } catch (Exception e) { warn(sim, "  [!] Качество VolumeChange: " + e.getMessage()); }
        try {
            FieldFunction metric = qualityField(sim, "SkewnessAngle", "Skewness Angle");
            UserFieldFunction alias = getOrCreateFF(sim,"MB_SkewnessAngle","${" + metric.getFunctionName() + "}"); alias.setDimensions(metric.getDimensions());
        } catch (Exception e) { warn(sim, "  [!] Качество SkewnessAngle: " + e.getMessage()); }
        sim.println("Контроль качества: " + qualityCounts[0] + " гистограмм и " + qualityCounts[1] + " скалярных сцен. Откройте их и проверьте min/max; это не автоматическое заключение о пригодности сетки.");

        try { groupManaged(sim,sim.getPartManager(),"DerivedParts"); } catch (Exception e) { warn(sim,"  [!] Grouping DerivedParts: " + e.getMessage()); }
        try { groupManaged(sim,sim.getReportManager(),"Reports"); } catch (Exception e) { warn(sim,"  [!] Grouping Reports: " + e.getMessage()); }
        try { groupManaged(sim,sim.getMonitorManager(),"Monitors"); } catch (Exception e) { warn(sim,"  [!] Grouping Monitors: " + e.getMessage()); }
        try { groupManaged(sim,sim.getPlotManager(),"Plots"); } catch (Exception e) { warn(sim,"  [!] Grouping Plots: " + e.getMessage()); }
        try { groupManaged(sim,sim.getSceneManager(),"Scenes"); } catch (Exception e) { warn(sim,"  [!] Grouping Scenes: " + e.getMessage()); }
        try { groupManaged(sim,sim.getFieldFunctionManager(),"FieldFunctions"); } catch (Exception e) { warn(sim,"  [!] Grouping FieldFunctions: " + e.getMessage()); }
        try { groupManaged(sim,sim.get(GlobalParameterManager.class),"Parameters"); } catch (Exception e) { warn(sim,"  [!] Grouping Parameters: " + e.getMessage()); }
        writeSummary(sim,subchannelRegions,exportFingerprint,expectedCells,false);
        // 11. Итоговый аудит созданных объектов:
        sim.println("\n===================================================================================================");
        sim.println("                       ИТОГОВЫЙ АУДИТ СОЗДАННЫХ ОБЪЕКТОВ СЦЕНЫ STAR-CCM+");
        sim.println("===================================================================================================");
        sim.println(" [1] ИНТЕРФЕЙСЫ (Interfaces): " + pairCount + " пар успешно создано.");
        for (String pNm : pairedNames) sim.println("     • " + pNm + " --> [ СОЗДАН ]");
        sim.println(" [2] ПРОИЗВОДНЫЕ ДЕТАЛИ (Derived Parts): " + planesCreated + " сечений и " + probesCreated + " зондов создано.");
        sim.println(" [3] ПАРАМЕТРЫ (Tools > Parameters): параметры назначаются только при первом импорте; проверьте сообщения [!].");
        sim.println(" [4] ОТЧЕТЫ И МОНИТОРЫ: настроено/переиспользовано " + reportCounts[0] + " отчетов и " + reportCounts[1] + " мониторов; проверьте сообщения [!].");
        sim.println("===================================================================================================");
        sim.println(">>> СОЗДАНИЕ ОБЪЕКТОВ ЗАВЕРШЕНО. ПРОВЕРЬТЕ СООБЩЕНИЯ [!] И ЗАДАЙТЕ ГРАНИЧНЫЕ УСЛОВИЯ.");
        sim.println("===================================================================================================\n");
    }

    private double[][] boundaryGeometry() {
        List<double[]> rows = new ArrayList<>();
        Collections.addAll(rows, geometryChunk0());
        return rows.toArray(new double[0][]);
    }
    private double[][] geometryChunk0() {
        return new double[][] {
            {1.0000000000000000e+00, 1.4000000000000000e+01, 7.1470811161832876e+02, 1.4751213272666144e-03, 8.9163289684807464e-03},
            {0.0000000000000000e+00, -1.0000000000000000e+00, 3.8100000000000006e+02, 6.3500000000000004e-04, 1.0080535700050868e-02},
            {1.0000000000000000e+00, 1.3000000000000000e+01, 7.1470811161832910e+02, -1.4751213272666149e-03, 8.9163289684807481e-03},
            {0.0000000000000000e+00, -1.0000000000000000e+00, 3.8100000000000006e+02, -6.3500000000000026e-04, 1.0080535700050868e-02},
            {1.0000000000000000e+00, 1.3000000000000000e+01, 7.1470811161832910e+02, -2.6393280588367330e-03, 6.8998637588875986e-03},
            {0.0000000000000000e+00, -1.0000000000000000e+00, 3.8100000000000000e+02, -3.2274999999999995e-03, 5.5901939814285515e-03},
            {1.0000000000000000e+00, 9.0000000000000000e+00, 7.1470811161832967e+02, -1.1642067315701190e-03, 4.3448786727333863e-03},
            {0.0000000000000000e+00, -1.0000000000000000e+00, 3.8099999999999983e+02, -2.5925000000000002e-03, 4.4903417186223154e-03},
            {1.0000000000000000e+00, 9.0000000000000000e+00, 7.1470811161832978e+02, 1.1642067315701199e-03, 4.3448786727333854e-03},
            {0.0000000000000000e+00, -1.0000000000000000e+00, 3.8100000000000000e+02, 2.5925000000000015e-03, 4.4903417186223154e-03},
            {1.0000000000000000e+00, 1.4000000000000000e+01, 7.1470811161832921e+02, 2.6393280588367335e-03, 6.8998637588875986e-03},
            {0.0000000000000000e+00, -1.0000000000000000e+00, 3.8099999999999983e+02, 3.2274999999999999e-03, 5.5901939814285481e-03},
            {1.0000000000000000e+00, 1.4000000000000000e+01, 1.4294162232366582e+03, 2.0572246930516741e-03, 7.9080963636841712e-03},
            {1.0000000000000000e+00, 1.3000000000000000e+01, 1.4294162232366582e+03, -2.0572246930516741e-03, 7.9080963636841729e-03},
            {1.0000000000000000e+00, 9.0000000000000000e+00, 1.4294162232366593e+03, 5.1850106134188222e-19, 4.3448786727333863e-03},
            {0.0000000000000000e+00, -1.0000000000000000e+00, 7.6200000000000011e+02, -1.3894897428712275e-19, 1.0080535700050868e-02},
            {0.0000000000000000e+00, -1.0000000000000000e+00, 7.6199999999999989e+02, -2.9099999999999998e-03, 5.0402678500254330e-03},
            {0.0000000000000000e+00, -1.0000000000000000e+00, 7.6199999999999989e+02, 2.9100000000000003e-03, 5.0402678500254304e-03},
            {1.0000000000000000e+00, 1.4000000000000000e+01, 7.1470811161832921e+02, 2.6393280588367330e-03, 1.3261207641214140e-02},
            {0.0000000000000000e+00, -1.0000000000000000e+00, 3.8099999999999983e+02, 3.2274999999999990e-03, 1.4570877418673177e-02},
            {1.0000000000000000e+00, 1.7000000000000000e+01, 7.1470811161832955e+02, 1.1642067315701201e-03, 1.5816192727368342e-02},
            {0.0000000000000000e+00, -1.0000000000000000e+00, 3.8099999999999977e+02, 2.5925000000000006e-03, 1.5670729681479412e-02},
            {1.0000000000000000e+00, 1.7000000000000000e+01, 7.1470811161832978e+02, -1.1642067315701192e-03, 1.5816192727368342e-02},
            {0.0000000000000000e+00, -1.0000000000000000e+00, 3.8099999999999983e+02, -2.5925000000000011e-03, 1.5670729681479419e-02},
            {1.0000000000000000e+00, 1.3000000000000000e+01, 7.1470811161832910e+02, -2.6393280588367339e-03, 1.3261207641214140e-02},
            {0.0000000000000000e+00, -1.0000000000000000e+00, 3.8099999999999972e+02, -3.2275000000000008e-03, 1.4570877418673177e-02},
            {1.0000000000000000e+00, 1.3000000000000000e+01, 7.1470811161832910e+02, -1.4751213272666149e-03, 1.1244742431620986e-02},
            {0.0000000000000000e+00, -1.0000000000000000e+00, 3.8100000000000006e+02, -6.3500000000000004e-04, 1.0080535700050870e-02},
            {1.0000000000000000e+00, 1.4000000000000000e+01, 7.1470811161832910e+02, 1.4751213272666142e-03, 1.1244742431620984e-02},
            {0.0000000000000000e+00, -1.0000000000000000e+00, 3.8100000000000006e+02, 6.3500000000000026e-04, 1.0080535700050868e-02},
            {1.0000000000000000e+00, 1.4000000000000000e+01, 1.4294162232366584e+03, 2.0572246930516736e-03, 1.2252975036417559e-02},
            {1.0000000000000000e+00, 1.7000000000000000e+01, 1.4294162232366593e+03, 2.2221474057509241e-19, 1.5816192727368342e-02},
            {1.0000000000000000e+00, 1.3000000000000000e+01, 1.4294162232366582e+03, -2.0572246930516745e-03, 1.2252975036417564e-02},
            {0.0000000000000000e+00, -1.0000000000000000e+00, 7.6199999999999966e+02, 2.9099999999999998e-03, 1.5120803550076296e-02},
            {0.0000000000000000e+00, -1.0000000000000000e+00, 7.6199999999999955e+02, -2.9100000000000003e-03, 1.5120803550076297e-02},
            {0.0000000000000000e+00, -1.0000000000000000e+00, 7.6200000000000011e+02, 1.3894897428712275e-19, 1.0080535700050870e-02},
            {1.0000000000000000e+00, 1.4000000000000000e+01, 2.8588324464733164e+03, 2.0572246930516736e-03, 1.0080535700050866e-02},
            {1.0000000000000000e+00, 1.3000000000000000e+01, 2.8588324464733164e+03, -2.0572246930516741e-03, 1.0080535700050868e-02},
            {1.0000000000000000e+00, 9.0000000000000000e+00, 1.4294162232366593e+03, 5.1850106134188222e-19, 4.3448786727333863e-03},
            {1.0000000000000000e+00, 1.7000000000000000e+01, 1.4294162232366593e+03, 2.2221474057509241e-19, 1.5816192727368342e-02},
        };
    }
    private void createPlaneSection(Simulation sim, LabCoordinateSystem labCoord, Units uLen, List<? extends NamedObject> parts, String name, double zVal) {
        createOrientedPlaneSection(sim, labCoord, uLen, parts, name,
                new double[] {0, 0, zVal}, new double[] {0, 0, 1});
    }
    private void createOrientedPlaneSection(Simulation sim, LabCoordinateSystem labCoord, Units uLen, List<? extends NamedObject> parts, String name, double[] origin, double[] normal) {
        try {
            PlaneSection ps = findOwned(sim,sim.getPartManager(),name,PlaneSection.class);
            if (ps == null) { ps = (PlaneSection) sim.getPartManager().createImplicitPart(
                new ArrayList<>(Collections.<NamedObject>emptyList()), new DoubleVector(normal),
                new DoubleVector(origin), 0, 1, new DoubleVector(new double[] {0.0}), null);
                ps.setPresentationName(name); own(sim,ps); }
            ps.setPresentationName(name); ps.setCoordinateSystem(labCoord);
            ps.getInputParts().setObjects(parts);
            ps.getOriginCoordinate().setValue(new DoubleVector(origin));
            ps.getOrientationCoordinate().setValue(new DoubleVector(normal));
        } catch (Exception e) { throw new IllegalStateException(name + ": " + e.getMessage(), e); }
    }
    private void createAxisLine(Simulation sim, LabCoordinateSystem labCoord, Units uLen, List<? extends NamedObject> parts, String name, double x, double y, double lz) {
        try {
            LineSection ls = findOwned(sim,sim.getPartManager(),name,LineSection.class);
            if (ls == null) { ls = sim.getPartManager().createLineSection(
                new ArrayList<>(Collections.<NamedObject>emptyList()),
                new DoubleVector(new double[] {0.0, 0.0, 0.0}),
                new DoubleVector(new double[] {0.0, 0.0, 1.0}), 0, true, null);
            ls.setPresentationName(name); own(sim,ls); }
            ls.setCoordinateSystem(labCoord);
            ls.getInputParts().setObjects(parts);
            ls.setInputMode(LineSectionInputMode.POINTPOINT);
            ls.getPointPoint().getStartPointCoordinate().setValue(new DoubleVector(new double[] {x, y, 0.0}));
            ls.getPointPoint().getEndPointCoordinate().setValue(new DoubleVector(new double[] {x, y, lz}));
        } catch (Exception e) { throw new IllegalStateException(name + ": " + e.getMessage(), e); }
    }

    private int classifyBoundary(double area, double x, double y, double[][] signatures) {
        int identity = -1;
        for (double[] row : signatures) {
            if (Math.abs(area - row[2]) <= Math.max(1e-5, row[2] * 2e-4)
                    && Math.hypot(x - row[3], y - row[4]) <= 1e-7) {
                int candidate = row[0] == 0 ? 0 : 1 + (int) row[1];
                if (identity >= 0 && identity != candidate) throw new IllegalStateException("Неоднозначная геометрия поверхности");
                identity = candidate;
            }
        }
        return identity;
    }
    private void registerReport(Simulation sim, Report report, int[] counts) {
        counts[0]++;
        if (meshOnlyReport(report.getPresentationName())) return;
        try {
            boolean found=false;
            for (ReportMonitor monitor : sim.getMonitorManager().getObjectsOf(ReportMonitor.class))
                if (monitor.getReport()==report) { found=true; break; }
            if (!found) own(sim,report.createMonitor());
            counts[1]++;
        }
        catch (Exception e) { warn(sim, "  [!] Монитор " + report.getPresentationName() + ": " + e.getMessage()); }
    }
    private void createMassFlowReport(Simulation sim, String name, List<? extends NamedObject> parts, int[] counts) {
        try {
            MassFlowReport report = ownedReport(sim,name,MassFlowReport.class);
            report.setPresentationName(name); report.getParts().setObjects(parts);
            registerReport(sim, report, counts);
        } catch (Exception e) { warn(sim, "  [!] Отчет " + name + ": " + e.getMessage()); }
    }
    private void createExpressionReport(Simulation sim, String name, String expression, int[] counts) {
        try {
            ExpressionReport report = ownedReport(sim,name,ExpressionReport.class);
            report.setPresentationName(name); report.setDefinition(expression);
            registerReport(sim, report, counts);
        } catch (Exception e) { warn(sim, "  [!] Отчет " + name + ": " + e.getMessage()); }
    }
    private void createHeatReport(Simulation sim, String name, List<? extends NamedObject> parts, int[] counts) {
        try {
            FieldFunction flux = sim.getFieldFunctionManager().getFunction("BoundaryHeatFlux");
            if (flux == null) throw new IllegalStateException("Недоступно поле BoundaryHeatFlux");
            SurfaceIntegralReport report = ownedReport(sim,name,SurfaceIntegralReport.class);
            report.setPresentationName(name); report.setFieldFunction(flux); report.getParts().setObjects(parts);
            registerReport(sim, report, counts);
        } catch (Exception e) { warn(sim, "  [!] Отчет " + name + ": " + e.getMessage()); }
    }
    private void createEnthalpyReport(Simulation sim, String name, List<? extends NamedObject> parts, int[] counts) {
        try {
            FieldFunction enthalpy = sim.getFieldFunctionManager().getFunction("TotalEnthalpy");
            if (enthalpy == null) throw new IllegalStateException("Недоступно поле TotalEnthalpy");
            MassFlowAverageReport report = ownedReport(sim,name,MassFlowAverageReport.class);
            report.setPresentationName(name); report.setFieldFunction(enthalpy); report.getParts().setObjects(parts);
            registerReport(sim, report, counts);
        } catch (Exception e) { warn(sim, "  [!] Отчет " + name + ": " + e.getMessage()); }
    }
    private FieldFunction qualityField(Simulation sim, String key, String label) {
        try {
            FieldFunction direct = sim.getFieldFunctionManager().getFunction(key);
            if (direct != null) return direct;
        } catch (Exception notFound) { /* Try the presentation name below. */ }
        for (FieldFunction candidate : sim.getFieldFunctionManager().getObjects()) {
            if (key.equals(candidate.getFunctionName()) || label.equals(candidate.getPresentationName())) return candidate;
        }
        throw new IllegalStateException("Недоступна метрика " + key);
    }
    private void createQualityExtrema(Simulation sim, List<Region> regions, FieldFunction metric, String key, int[] counts) {
        try {
            MinReport minimum = ownedReport(sim,"Quality_Min_" + key,MinReport.class);
            minimum.setPresentationName("Quality_Min_" + key);
            minimum.setFieldFunction(metric); minimum.getParts().setObjects(regions);
            registerReport(sim, minimum, counts);
        } catch (Exception e) { warn(sim, "  [!] Min " + key + ": " + e.getMessage()); }
        try {
            MaxReport maximum = ownedReport(sim,"Quality_Max_" + key,MaxReport.class);
            maximum.setPresentationName("Quality_Max_" + key);
            maximum.setFieldFunction(metric); maximum.getParts().setObjects(regions);
            registerReport(sim, maximum, counts);
        } catch (Exception e) { warn(sim, "  [!] Max " + key + ": " + e.getMessage()); }
    }
    private void createQualityScene(Simulation sim, List<NamedObject> surfaces, FieldFunction metric, String name) {
        if (surfaces.isEmpty()) throw new IllegalStateException("Не создано сечение качества");
        Scene scene = findOwned(sim,sim.getSceneManager(),name,Scene.class);
        if (scene == null) { scene=sim.getSceneManager().createScene(); scene.setPresentationName(name); own(sim,scene); }
        ScalarDisplayer scalar = findOwned(sim,scene.getDisplayerManager(),"meshBuilder_Scalar",ScalarDisplayer.class);
        if (scalar == null) { scalar=scene.getDisplayerManager().createScalarDisplayer("Scalar"); scalar.setPresentationName("meshBuilder_Scalar"); own(sim,scalar); }
        scalar.setRepresentation((FvRepresentation) sim.getRepresentationManager().getObject("Volume Mesh"));
        scalar.getInputParts().setObjects(surfaces);
        scalar.getScalarDisplayQuantity().setFieldFunction(metric);
        scalar.setFillMode(ScalarFillMode.NATIVE);
        scene.resetCamera();
    }
    private double measureArea(SurfaceIntegralReport areaRep, UserFieldFunction unityFF, Boundary b) { try { areaRep.getParts().setObjects(b); areaRep.setFieldFunction(unityFF); return areaRep.getReportMonitorValue() * 1e6; } catch (Exception e) { return 0.0; } }
    private double[] getCentroid3D(SurfaceIntegralReport rep, UserFieldFunction unityFF, UserFieldFunction ffX, UserFieldFunction ffY, UserFieldFunction ffZ, Boundary b) {
        try {
            rep.getParts().setObjects(b); rep.setFieldFunction(unityFF);
            double area = rep.getReportMonitorValue();
            if (area <= 1e-14) return new double[]{0.0, 0.0, 0.0};
            rep.setFieldFunction(ffX); double intX = rep.getReportMonitorValue();
            rep.setFieldFunction(ffY); double intY = rep.getReportMonitorValue();
            rep.setFieldFunction(ffZ); double intZ = rep.getReportMonitorValue();
            return new double[]{intX / area, intY / area, intZ / area};
        } catch (Exception e) { return new double[]{0.0, 0.0, 0.0}; }
    }
    private UserFieldFunction getOrCreateFF(Simulation sim, String name, String definition) {
        UserFieldFunction ff=findOwned(sim,sim.getFieldFunctionManager(),name,UserFieldFunction.class);
        if (ff==null) {
            ff=sim.getFieldFunctionManager().createFieldFunction(); ff.setPresentationName(name); own(sim,ff);
        }
        ff.setPresentationName(displayName(name));
        ff.setFunctionName(name); ff.setDefinition(definition); return ff;
    }
    private void createParam(Simulation sim, GlobalParameterManager gpm, ClientServerObjectGroup grp, String name, double val, String unitStr, Dimensions dims, String defStr) {
        try {
            ScalarGlobalParameter p = findOwned(sim,gpm,name,ScalarGlobalParameter.class);
            if (p == null) { p = (ScalarGlobalParameter) gpm.createGlobalParameter(ScalarGlobalParameter.class, "Scalar"); p.setPresentationName(name); own(sim,p); }
            if (dims != null) p.setDimensions(dims);
            if (defStr != null && !defStr.isEmpty()) { p.getQuantity().setDefinition(defStr); }
            else {
                if (unitStr != null && !unitStr.isEmpty()) { Units u = sim.getUnitsManager().getObject(unitStr); p.getQuantity().setValueAndUnits(val, u); }
                else { p.getQuantity().setValue(val); }
            }
        } catch (Exception e) { warn(sim,"  [!] Parameter " + name + ": " + e.getMessage()); }
    }
    private String managedBucket(NamedObject object, String category) {
        String name=object.getPresentationName();
        if (category.equals("Parameters")) {
            if (name.equals("TimeStep")) return "Transient";
            if (Arrays.asList("rho","dynvis","kinvis","Cp","lambda","Pr").contains(name)) return "Properties";
            if (Arrays.asList("P_ref","T_ref").contains(name)) return "Reference";
            if (Arrays.asList("P_init","T_init","U_init").contains(name)) return "Initial";
            if (Arrays.asList("P_wet","S_in","D_hyd","ExportHeight","MB_ExportHeight").contains(name)) return "Geometry";
            if (Arrays.asList("y_plus_target","h1_wall").contains(name)) return "Grid_YPlus";
            return "FlowReference";
        }
        if (category.equals("FieldFunctions")) {
            if (name.startsWith("Bad") || Arrays.asList("CellQuality","FaceValidity","VolumeChange","SkewnessAngle").contains(name)) return "MeshQuality";
            if (Arrays.asList("One","X","Y","Z","ZFraction").contains(name)) return "Coordinates";
            if (name.contains("Mask")) return "SubchannelMasks";
            if (name.contains("Balance")) return "Balances";
            if (name.contains("WallShear")) return "Wall";
            return "Flow";
        }
        if (category.equals("Monitors")) {
            if (name.startsWith("TimeMean_") || name.startsWith("MB_TimeMean_")) return "MeanFields";
            try {
                Object report=object.getClass().getMethod("getReport").invoke(object);
                if (report instanceof NamedObject) name=((NamedObject)report).getPresentationName();
            } catch (Exception notReportMonitor) { /* Other native monitors keep their name. */ }
            if (meshOnlyReport(name)) return "LegacyStatic";
        }
        if (name.startsWith("Quality_")) return "MeshQuality";
        if (meshOnlyReport(name)) return "Geometry";
        if (name.contains("Imbalance") || name.contains("Balance") || name.startsWith("Energy_Flow_")) return "Balances";
        if (name.contains("Temperature") || name.contains("Heat") || name.contains("Enthalpy")) return "Thermal";
        if (name.contains("Shear") || name.contains("Cf_") || name.contains("Darcy")) return "Wall";
        if (name.startsWith("Gap_") || name.contains("_Gap_")) return "Gaps";
        if (name.startsWith("Subchannel_")) return "Subchannels";
        if (name.startsWith("Section_") || name.startsWith("Probe_") || name.contains("_Section_")) return "Sections";
        return "Flow";
    }
    private void nativeGroupObjects(Object manager, String name, List<NamedObject> members) throws Exception {
        for (java.lang.reflect.Method method : manager.getClass().getMethods()) {
            if (!method.getName().equals("groupObjects") || method.getParameterCount()!=3) continue;
            Class<?> expected=method.getParameterTypes()[1];
            Object collection=expected.isAssignableFrom(ArrayList.class) ? new ArrayList<>(members)
                : expected.isAssignableFrom(Vector.class) ? new Vector<>(members) : new NeoObjectVector(members.toArray());
            try { method.invoke(manager,name,collection,true); return; }
            catch (IllegalArgumentException mismatch) { /* Try compatible overload. */ }
        }
        throw new IllegalStateException("groupObjects API unavailable");
    }
    private Object managedRootGroup(Object manager, String name) throws Exception {
        Object group=null;
        try { group=manager.getClass().getMethod("getObject",String.class).invoke(manager,name); }
        catch (java.lang.reflect.InvocationTargetException notFound) { /* Create the missing folder. */ }
        if (group==null) {
            manager.getClass().getMethod("createGroup",String.class).invoke(manager,name);
            group=manager.getClass().getMethod("getObject",String.class).invoke(manager,name);
        }
        return group;
    }
    private void groupManaged(Simulation sim, Object manager, String category) {
        Map<String,List<NamedObject>> groups=new TreeMap<>();
        for (Object candidate : objects(manager)) {
            if (!(candidate instanceof NamedObject)) continue;
            NamedObject object=(NamedObject)candidate;
            if (!tagged(object,OWNER)) continue;
            groups.computeIfAbsent(managedBucket(object,category),k -> new ArrayList<>()).add(object);
        }
        if (groups.isEmpty()) return;
        try {
            Object roots=manager.getClass().getMethod("getGroupsManager").invoke(manager);
            // A nested group may only regroup members of its parent. Populate
            // the root first, then move its members into category subfolders.
            List<NamedObject> all=new ArrayList<>();
            for (List<NamedObject> members : groups.values()) all.addAll(members);
            nativeGroupObjects(roots,"meshBuilder_"+category,all);
            Object root=managedRootGroup(roots,"meshBuilder_"+category);
            Object folders=root.getClass().getMethod("getGroupsManager").invoke(root);
            for (Map.Entry<String,List<NamedObject>> entry : groups.entrySet()) {
                nativeGroupObjects(folders,entry.getKey(),entry.getValue());
                Object leaf=managedRootGroup(folders,entry.getKey());
                try {
                    Object actual=leaf.getClass().getMethod("getObjects").invoke(leaf);
                    if (actual instanceof Collection && !((Collection<?>)actual).containsAll(entry.getValue()))
                        throw new IllegalStateException("Folder "+entry.getKey()+" missing members; expected "+entry.getValue().size());
                } catch (NoSuchMethodException noMembershipAccessor) { /* Older API: native grouping succeeded. */ }
            }
        } catch (Exception e) { warn(sim,"  [!] Nested grouping " + category + ": " + e.getMessage()); }
    }
    private String auditDeferral(String name, boolean requested, boolean initialized, boolean progressed) {
        if (meshOnlyReport(name)) return null;
        if (!requested) return "physical evaluation disabled";
        if (!initialized) return "solution not initialized";
        if (!progressed) return "no solver iterations yet";
        return null;
    }
    private double auditReportValue(Simulation sim, Report report, Map<String,Double> values,
            Map<String,String> blocked, Set<String> visiting) {
        String name=report.getPresentationName();
        if (values.containsKey(name)) return values.get(name);
        if (blocked.containsKey(name)) throw new IllegalStateException(blocked.get(name));
        if (!visiting.add(name)) throw new IllegalStateException("Cyclic report dependency: " + name);
        try {
            if (report instanceof ExpressionReport) {
                String definition=((ExpressionReport)report).getDefinition();
                java.util.regex.Matcher refs=java.util.regex.Pattern.compile("\\$\\{([^}]+)Report\\}").matcher(definition);
                while (refs.find()) {
                    Report dependency=findOwned(sim,sim.getReportManager(),refs.group(1),Report.class);
                    if (dependency==null) throw new IllegalStateException("Missing dependency " + refs.group(1));
                    auditReportValue(sim,dependency,values,blocked,visiting);
                }
            }
            if (report instanceof MassFlowAverageReport) {
                // A zero-flow boundary/section has no defined mass-flow average.
                MassFlowReport flow=sim.getReportManager().createReport(MassFlowReport.class);
                try {
                    flow.getParts().setObjects(((MassFlowAverageReport)report).getParts().getObjects());
                    double mass=flow.getReportMonitorValue();
                    if (!Double.isFinite(mass) || Math.abs(mass)<=1e-30)
                        throw new IllegalStateException("Zero/unavailable net mass flow; average undefined");
                } finally { sim.getReportManager().remove(flow); }
            }
            double value=report.getReportMonitorValue();
            if (!Double.isFinite(value)) throw new IllegalStateException("Field/report value not available or finite");
            values.put(name,value);return value;
        } catch (Exception e) {
            String reason=e.getMessage()==null?e.getClass().getSimpleName():e.getMessage();
            blocked.put(name,reason);throw new IllegalStateException(reason,e);
        } finally { visiting.remove(name); }
    }
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
            if (iapws) {
                Material material=physics.getModelManager().getModel(SingleComponentLiquidModel.class).getMaterial();
                MaterialPropertyMethod viscosity=material.getMaterialProperties().getMaterialProperty(DynamicViscosityProperty.class).getMethod();
                MaterialPropertyMethod conductivity=material.getMaterialProperties().getMaterialProperty(ThermalConductivityProperty.class).getMethod();
                sim.println("  • IAPWS transport methods: viscosity="+viscosity.getClass().getSimpleName()+", conductivity="+conductivity.getClass().getSimpleName());
                if (viscosity instanceof ConstantMaterialPropertyMethod || conductivity instanceof ConstantMaterialPropertyMethod)
                    throw new IllegalStateException("IAPWS EOS does not configure transport properties: select variable water viscosity/conductivity methods in Material Properties, then initialize manually. Constant defaults are not accepted.");
            }
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
    private void exportHeight(Simulation sim, double length) {
        if (!Double.isFinite(length) || length<=0) throw new IllegalArgumentException("Invalid export height");
        GlobalParameterManager manager=sim.get(GlobalParameterManager.class);
        ScalarGlobalParameter height=findOwned(sim,manager,"ExportHeight",ScalarGlobalParameter.class);
        if (height==null) {
            height=(ScalarGlobalParameter)manager.createGlobalParameter(ScalarGlobalParameter.class,"Scalar");
            height.setPresentationName("ExportHeight"); own(sim,height);
        }
        height.setDimensions(Dimensions.Builder().length(1).build());
        height.getQuantity().setValueAndUnits(length,sim.getUnitsManager().getObject("m"));
    }
    private List<Boundary> rodBoundaries(Region region) {
        List<Boundary> result=new ArrayList<>();
        for (Boundary b : region.getBoundaryManager().getBoundaries())
            if (tagged(b,"meshBuilder.Role.Rod")) result.add(b);
        return result;
    }
    private FieldFunction analysisField(Simulation sim, String key) {
        FieldFunction ff=sim.getFieldFunctionManager().getFunction(key);
        if (ff==null) throw new IllegalStateException("Missing solution field " + key);
        return ff;
    }
    private void scalarReport(Simulation sim, String kind, String name, List<? extends NamedObject> parts,
            FieldFunction field, int[] counts) {
        try {
            if (parts.isEmpty()) throw new IllegalStateException("No input parts");
            if (kind.equals("area")) {
                AreaAverageReport r=ownedReport(sim,name,AreaAverageReport.class);
                r.setFieldFunction(field); r.getParts().setObjects(parts); registerReport(sim,r,counts);
            } else if (kind.equals("massflow")) {
                MassFlowAverageReport r=ownedReport(sim,name,MassFlowAverageReport.class);
                r.setFieldFunction(field); r.getParts().setObjects(parts); registerReport(sim,r,counts);
            } else if (kind.equals("surface")) {
                SurfaceIntegralReport r=ownedReport(sim,name,SurfaceIntegralReport.class);
                r.setFieldFunction(field); r.getParts().setObjects(parts); registerReport(sim,r,counts);
            } else if (kind.equals("volume")) {
                VolumeIntegralReport r=ownedReport(sim,name,VolumeIntegralReport.class);
                r.setFieldFunction(field); r.getParts().setObjects(parts); registerReport(sim,r,counts);
            } else throw new IllegalArgumentException("Unknown report kind " + kind);
        } catch (Exception e) { warn(sim,"  [!] Report " + name + ": " + e.getMessage()); }
    }
    private void derivedReport(Simulation sim, String name, String expression, Dimensions dims, int[] counts) {
        try {
            java.util.regex.Matcher refs=java.util.regex.Pattern.compile("\\$\\{([^}]+)Report\\}").matcher(expression);
            while (refs.find()) if (findOwned(sim,sim.getReportManager(),refs.group(1),Report.class)==null)
                throw new IllegalStateException("Missing managed dependency " + refs.group(1));
            ExpressionReport r=ownedReport(sim,name,ExpressionReport.class);
            r.setDimensions(dims); r.setDefinition(expression); registerReport(sim,r,counts);
        } catch (Exception e) { warn(sim,"  [!] Report " + name + ": " + e.getMessage()); }
    }
    private String reportRef(String name) { return "${" + name + "Report}"; }
    private void createSubchannelAnalysis(Simulation sim, int number, List<? extends NamedObject> domain,
            List<? extends NamedObject> walls, PlaneSection inlet, PlaneSection outlet, double length,
            List<String> choices, boolean thermal, int[] counts) {
        String prefix="Sub"+number+"_";
        List<NamedObject> in=Collections.singletonList(inlet), out=Collections.singletonList(outlet);
        Dimensions dimless=Dimensions.Builder().build(), len=Dimensions.Builder().length(1).build();
        Dimensions pressure=Dimensions.Builder().mass(1).length(-1).time(-2).build();
        FieldFunction one=getOrCreateFF(sim,"MB_One","1.0");
        // Geometry and hydraulic dependencies are explicit; no exported constant rho/mu is used.
        try {
            scalarReport(sim,"surface",prefix+"Area_In",in,one,counts);
            scalarReport(sim,"surface",prefix+"Area_Out",out,one,counts);
            scalarReport(sim,"volume",prefix+"Volume",domain,one,counts);
            scalarReport(sim,"surface",prefix+"RodArea",walls,one,counts);
            exportHeight(sim,length);
            derivedReport(sim,prefix+"WettedPerimeter",reportRef(prefix+"RodArea")+" / ${ExportHeight}",len,counts);
            derivedReport(sim,prefix+"HydraulicDiameter","4 * "+reportRef(prefix+"Area_In")+" / "+reportRef(prefix+"WettedPerimeter"),len,counts);
        } catch (Exception e) { warn(sim,"  [!] Subchannel geometry " + number + ": " + e.getMessage()); }
        if (choices.contains("hydraulics") || choices.contains("wall")) try {
            createMassFlowReport(sim,prefix+"MassFlow_In",in,counts);
            createMassFlowReport(sim,prefix+"MassFlow_Out",out,counts);
            scalarReport(sim,"area",prefix+"Density_In",in,analysisField(sim,"Density"),counts);
            scalarReport(sim,"area",prefix+"Viscosity_In",in,analysisField(sim,"DynamicViscosity"),counts);
            scalarReport(sim,"area",prefix+"Density_Out",out,analysisField(sim,"Density"),counts);
            scalarReport(sim,"area",prefix+"Viscosity_Out",out,analysisField(sim,"DynamicViscosity"),counts);
            UserFieldFunction axial=getOrCreateFF(sim,"MB_AxialVelocity","$$Velocity[2]");
            axial.setDimensions(Dimensions.Builder().length(1).time(-1).build());
            scalarReport(sim,"area",prefix+"BulkAxialVelocity_In",in,axial,counts);
            scalarReport(sim,"area",prefix+"BulkAxialVelocity_Out",out,axial,counts);
            scalarReport(sim,"area",prefix+"Pressure_In",in,analysisField(sim,"Pressure"),counts);
            scalarReport(sim,"area",prefix+"Pressure_Out",out,analysisField(sim,"Pressure"),counts);
            derivedReport(sim,prefix+"PressureDrop",reportRef(prefix+"Pressure_In")+" - "+reportRef(prefix+"Pressure_Out"),pressure,counts);
            derivedReport(sim,prefix+"Reynolds_In","abs("+reportRef(prefix+"MassFlow_In")+") * "+reportRef(prefix+"HydraulicDiameter")+
                " / ("+reportRef(prefix+"Area_In")+" * "+reportRef(prefix+"Viscosity_In")+")",dimless,counts);
            derivedReport(sim,prefix+"Reynolds_Out","abs("+reportRef(prefix+"MassFlow_Out")+") * "+reportRef(prefix+"HydraulicDiameter")+
                " / ("+reportRef(prefix+"Area_Out")+" * "+reportRef(prefix+"Viscosity_Out")+")",dimless,counts);
            UserFieldFunction localRe=getOrCreateFF(sim,"MB_Reynolds_Sub"+number,
                "${Density} * mag($$Velocity) * "+reportRef(prefix+"HydraulicDiameter")+" / ${DynamicViscosity}");
            localRe.setDimensions(dimless);
            derivedReport(sim,prefix+"DynamicPressure_In","0.5 * "+reportRef(prefix+"Density_In")+" * pow("+reportRef(prefix+"BulkAxialVelocity_In")+", 2)",pressure,counts);
        } catch (Exception e) { warn(sim,"  [!] Subchannel hydraulics " + number + ": " + e.getMessage()); }
        if (choices.contains("wall")) try {
            FieldFunction shear=analysisField(sim,"WallShearStress");
            UserFieldFunction magnitude=getOrCreateFF(sim,"MB_WallShearMagnitude","mag($$"+shear.getFunctionName()+")");
            magnitude.setDimensions(pressure);
            scalarReport(sim,"area",prefix+"WallShearMean",walls,magnitude,counts);
            derivedReport(sim,prefix+"Cf_Wall",reportRef(prefix+"WallShearMean")+" / "+reportRef(prefix+"DynamicPressure_In"),dimless,counts);
            derivedReport(sim,prefix+"Darcy_Wall","4 * "+reportRef(prefix+"Cf_Wall"),dimless,counts);
        } catch (Exception e) { warn(sim,"  [!] Subchannel wall friction " + number + ": " + e.getMessage()); }
        if (choices.contains("thermal") && thermal) try {
            FieldFunction temperature=analysisField(sim,"Temperature");
            scalarReport(sim,"massflow",prefix+"BulkTemperature_In",in,temperature,counts);
            scalarReport(sim,"massflow",prefix+"BulkTemperature_Out",out,temperature,counts);
            scalarReport(sim,"area",prefix+"WallTemperature",walls,temperature,counts);
            scalarReport(sim,"area",prefix+"WallHeatFluxMean",walls,analysisField(sim,"BoundaryHeatFlux"),counts);
            createHeatReport(sim,prefix+"RodHeatPower",walls,counts);
        } catch (Exception e) { warn(sim,"  [!] Subchannel thermal " + number + ": " + e.getMessage()); }
        if (choices.contains("thermal") && !thermal) warn(sim,"  [!] Thermal reports require energy: Sub"+number);
    }
    private void createTimeMean(Simulation sim, List<? extends NamedObject> parts, String fieldName, int start) {
        String name="MB_TimeMean_"+fieldName;
        try {
            if (sim.getSolverManager().getSolver(ImplicitUnsteadySolver.class)==null)
                throw new IllegalStateException("Field means require an implicit unsteady solver");
            FieldFunction field=analysisField(sim,fieldName);
            FieldMeanMonitor monitor=findOwned(sim,sim.getMonitorManager(),name,FieldMeanMonitor.class);
            if (monitor!=null) {
                sim.println("  • Preserve accumulated field statistics: "+name.substring(3)); return;
            }
            PhysicalTimeMonitor clock=null;
            for (Object candidate : objects(sim.getMonitorManager()))
                if (candidate instanceof PhysicalTimeMonitor) { clock=(PhysicalTimeMonitor)candidate; break; }
            if (clock==null) throw new IllegalStateException("Physical time monitor unavailable");
            String eventName=name+"_Steps";
            FrequencyMonitorUpdateEvent event=findOwned(sim,sim.getUpdateEventManager(),eventName,FrequencyMonitorUpdateEvent.class);
            if (event==null) {
                event=sim.getUpdateEventManager().createUpdateEvent(FrequencyMonitorUpdateEvent.class);
                event.setPresentationName(eventName); own(sim,event);
            }
            event.setMonitor(clock); event.setSampleFrequency(1); event.setStartCount(start);
            monitor=sim.getMonitorManager().createMonitor(FieldMeanMonitor.class);
            monitor.setPresentationName(name); own(sim,monitor);
            monitor.setObjects(new ArrayList<NamedObject>(parts)); monitor.setFieldFunction(field);
            monitor.getStarUpdate().getUpdateModeOption().setSelected(StarUpdateModeOption.Type.EVENT);
            monitor.getStarUpdate().getEventUpdateFrequency().setUpdateEvent(event);
            sim.println("  • Field mean "+name.substring(3)+": one sample per time step, constant dt required, start="+start);
        } catch (Exception e) { warn(sim,"  [!] Field mean " + name + ": " + e.getMessage()); }
    }
    private final List<String> issues = new ArrayList<>();
    private static final String OWNER = "meshBuilder.Managed";
    private String displayName(String name) { return name.startsWith("MB_") ? name.substring(3) : name; }
    private void warn(Simulation sim, String message) {
        issues.add(message); sim.println(message);
    }
    private Collection<?> objects(Object manager) {
        try { return (Collection<?>) manager.getClass().getMethod("getObjects").invoke(manager); }
        catch (Exception e) { throw new IllegalStateException("Cannot enumerate " + manager.getClass().getName(), e); }
    }
    private List<Tag> tags(NamedObject object) {
        try {
            Object group = object.getClass().getMethod("getTagGroup").invoke(object);
            Collection<?> current = (Collection<?>) group.getClass().getMethod("getObjects").invoke(group);
            List<Tag> result = new ArrayList<>();
            for (Object tag : current) result.add((Tag) tag);
            return result;
        } catch (Exception e) { throw new IllegalStateException("Cannot inspect ownership of " + object.getPresentationName(), e); }
    }
    private Tag tag(Simulation sim, String name) {
        for (Tag current : sim.get(TagManager.class).getObjects())
            if (current.getPresentationName().equals(name)) return current;
        return sim.get(TagManager.class).createNewUserTag(name);
    }
    private boolean tagged(NamedObject object, String name) {
        for (Tag t : tags(object)) if (t.getPresentationName().equals(name)) return true;
        return false;
    }
    private void mark(Simulation sim, NamedObject object, String label) {
        List<Tag> current = tags(object);
        Tag t = tag(sim, label);
        if (!current.contains(t)) current.add(t);
        sim.get(TagManager.class).setTags(object, current);
    }
    private void own(Simulation sim, NamedObject object) { mark(sim, object, OWNER); object.setPresentationName(displayName(object.getPresentationName())); }
    private <T extends NamedObject> T findOwned(Simulation sim, Object manager, String name, Class<T> type) {
        T found=null;
        for (Object candidate : objects(manager)) {
            if (!(candidate instanceof NamedObject)) continue;
            NamedObject object = (NamedObject) candidate;
            String actual=object.getPresentationName();
            if (!name.equals(actual) && !(name.startsWith("MB_") && displayName(name).equals(displayName(actual)))) continue;
            if (!tagged(object, OWNER)) throw new IllegalStateException("Name belongs to a user object: " + actual);
            if (!type.isInstance(object)) throw new IllegalStateException("Incompatible object type: " + actual);
            if (found!=null) throw new IllegalStateException("Ambiguous managed name: " + name);
            found=type.cast(object);
        }
        if (found!=null && name.startsWith("MB_")) found.setPresentationName(displayName(name));
        return found;
    }
    private <T extends Report> T ownedReport(Simulation sim, String name, Class<T> type) {
        T report = findOwned(sim, sim.getReportManager(), name, type);
        if (report == null) {
            report = sim.getReportManager().createReport(type);
            report.setPresentationName(name); own(sim, report);
        }
        return report;
    }
    private ThresholdPart threshold(Simulation sim, List<? extends NamedObject> input, FieldFunction ff, String name) {
        ThresholdPart part = findOwned(sim, sim.getPartManager(), name, ThresholdPart.class);
        if (part == null) {
            part = sim.getPartManager().createThresholdPart(new NeoObjectVector(input.toArray()),
                    new DoubleVector(new double[] {0.5,1.5}), sim.getUnitsManager().getObject(""), ff, 0);
            part.setPresentationName(name); own(sim, part);
        }
        part.getInputParts().setObjects(input); part.setFieldFunction(ff);
        part.setMode(ThresholdMode.BETWEEN_TAG);
        part.setRange(new DoubleVector(new double[] {0.5,1.5}));
        return part;
    }
    private List<Region> preparedRegions(Simulation sim, String fingerprint, int expected) {
        List<Region> result = new ArrayList<>();
        for (Region region : sim.getRegionManager().getRegions()) {
            for (Tag t : tags(region)) {
                if (t.getPresentationName().startsWith("meshBuilder.Mesh.")
                        && !t.getPresentationName().equals("meshBuilder.Mesh." + fingerprint))
                    throw new IllegalStateException("Mesh/topology differs from this export. Use a new simulation.");
            }
            if (tagged(region, "meshBuilder.Mesh." + fingerprint)) result.add(region);
        }
        if (!result.isEmpty()) {
            if (result.size()!=expected) throw new IllegalStateException("Managed region count changed; use a new simulation.");
            result.sort(Comparator.comparingInt(r -> {
                for (Tag t : tags(r)) if (t.getPresentationName().startsWith("meshBuilder.Source."))
                    return Integer.parseInt(t.getPresentationName().substring("meshBuilder.Source.".length()));
                throw new IllegalStateException("Source region tag missing");
            }));
        }
        return result;
    }
    private void markBoundaryRoles(Simulation sim, List<Boundary> inlets, List<Boundary> outlets, List<Boundary> rods, List<Boundary> gaps) {
        for (Boundary b : inlets) mark(sim,b,"meshBuilder.Role.Inlet");
        for (Boundary b : outlets) mark(sim,b,"meshBuilder.Role.Outlet");
        for (Boundary b : rods) mark(sim,b,"meshBuilder.Role.Rod");
        for (Boundary b : gaps) mark(sim,b,"meshBuilder.Role.Gap");
    }
    private ElementCountReport countReport(Simulation sim, String name, List<? extends NamedObject> parts, int[] counts) {
        ElementCountReport report = ownedReport(sim,name,ElementCountReport.class);
        report.getParts().setObjects(parts); registerReport(sim,report,counts); return report;
    }
    private UserFieldFunction createBadCells(Simulation sim, List<Region> regions, FieldFunction metric, String key,
            String condition, int[] counts) {
        try {
            String expression = "(${" + metric.getFunctionName() + "} " + condition + ") ? 1.0 : 0.0";
            UserFieldFunction mask = getOrCreateFF(sim,"MB_Bad_" + key,expression);
            mask.setDimensions(Dimensions.Builder().build());
            ThresholdPart bad = threshold(sim,regions,mask,"Quality_BadCells_" + key);
            countReport(sim,"Quality_BadCount_" + key,Collections.singletonList(bad),counts);
            createExpressionReport(sim,"Quality_BadPercent_" + key,
                    "100 * ${Quality_BadCount_" + key + "Report} / max(${Quality_TotalCellCountReport},1)",counts);
            return mask;
        } catch (Exception e) { warn(sim,"  [!] Bad cells " + key + ": " + e.getMessage()); return null; }
    }
    private void badUnion(Simulation sim,List<Region> regions,List<UserFieldFunction> masks,int[] counts) {
        if (masks.size()!=4) { warn(sim,"  [!] Combined bad-cell mask unavailable: one or more criteria failed");return; }
        try {
            List<String> tests=new ArrayList<>();
            for (UserFieldFunction mask : masks) tests.add("${" + mask.getFunctionName() + "} > 0.5");
            UserFieldFunction mask=getOrCreateFF(sim,"MB_BadAnyQuality","("+String.join(" || ",tests)+") ? 1.0 : 0.0");
            mask.setDimensions(Dimensions.Builder().build());
            ThresholdPart part=threshold(sim,regions,mask,"Quality_BadCells_Any");
            countReport(sim,"Quality_BadCount_Any",Collections.singletonList(part),counts);
            createExpressionReport(sim,"Quality_BadPercent_Any","100 * ${Quality_BadCount_AnyReport} / max(${Quality_TotalCellCountReport},1)",counts);
        } catch (Exception e) { warn(sim,"  [!] Combined bad cells: "+e.getMessage()); }
    }
    private void supportFunctions(Simulation sim, double height, List<String> selected) {
        if (selected.contains("z_fraction")) try {
            // A dimensioned global parameter is valid STAR syntax; inline [m] literals are not.
            exportHeight(sim,height);
            getOrCreateFF(sim,"MB_Z","$$Centroid[2]").setDimensions(Dimensions.Builder().length(1).build());
            UserFieldFunction ff=getOrCreateFF(sim,"MB_ZFraction","${MB_Z} / ${ExportHeight}");
            ff.setDimensions(Dimensions.Builder().build());
        } catch (Exception e) { warn(sim,"  [!] Relative height: " + e.getMessage()); }
        if (selected.contains("speed")) try {
            UserFieldFunction ff=getOrCreateFF(sim,"MB_Speed","mag($$Velocity)");
            ff.setDimensions(Dimensions.Builder().length(1).time(-1).build());
        } catch (Exception e) { warn(sim,"  [!] Speed: " + e.getMessage()); }
        if (selected.contains("mass_flux")) try {
            UserFieldFunction ff=getOrCreateFF(sim,"MB_MassFluxMagnitude","${Density} * mag($$Velocity)");
            ff.setDimensions(Dimensions.Builder().mass(1).length(-2).time(-1).build());
        } catch (Exception e) { warn(sim,"  [!] Mass flux: " + e.getMessage()); }
    }
    private String csv(String value) { return "\"" + value.replace("\"","\"\"") + "\""; }
    private void writeSummary(Simulation sim, List<Region> regions, String fingerprint, long expectedCells, boolean evaluateSolution) {
        List<String[]> rows=new ArrayList<>();
        rows.add(new String[]{"export","signature",fingerprint,"","info"});
        rows.add(new String[]{"export","settings",exportSettings,"JSON","requested"});
        try { rows.add(new String[]{"export","star_version",sim.getStarVersion().getString("ReleaseNumber"),"","info"}); }
        catch (Exception e) { warn(sim,"  [!] STAR version unavailable: "+e.getMessage()); }
        rows.add(new String[]{"mesh","expected_cells",Long.toString(expectedCells),"cells","info"});
        rows.add(new String[]{"mesh","regions",Integer.toString(regions.size()),"","info"});
        sim.println("=== meshBuilder audit: expected " + expectedCells + " cells, " + regions.size() + " regions ===");
        boolean initialized=sim.getSolution().isInitialized();
        boolean progressed=sim.getSimulationIterator().getCurrentIteration()>0;
        Map<String,Double> evaluated=new HashMap<>();Map<String,String> unavailable=new HashMap<>();
        int deferred=0;
        for (Report report : new ArrayList<Report>(sim.getReportManager().getObjects())) if (tagged(report,OWNER)) {
            String name=report.getPresentationName();
            String reason=auditDeferral(name,evaluateSolution,initialized,progressed);
            if (reason!=null) {
                rows.add(new String[]{"report",name,"","","deferred: "+reason});deferred++;continue;
            }
            try {
                double value=auditReportValue(sim,report,evaluated,unavailable,new HashSet<String>());
                rows.add(new String[]{"report",name,Double.toString(value),report.getUnits()==null?"":report.getUnits().getPresentationName(),"evaluated"});
                sim.println(name+" = "+value);
                if (name.equals("Quality_TotalCellCount") && Math.abs(value-expectedCells)>.5)
                    warn(sim,"  [!] Imported cell count differs from the exported mesh");
            } catch (Exception e) {
                rows.add(new String[]{"report",name,"","","unavailable: "+e.getMessage()});
                warn(sim,"  [!] Audit report " + name + ": " + e.getMessage());
            }
        }
        if (deferred>0) sim.println("Deferred physical reports: "+deferred+". Set BCs and solve before evaluating; see CSV status.");
        Object[] managers={sim.getPartManager(),sim.getReportManager(),sim.getMonitorManager(),
            sim.getPlotManager(),sim.getSceneManager(),sim.getFieldFunctionManager()};
        String[] categories={"parts","reports","monitors","plots","scenes","field_functions"};
        for (int i=0;i<managers.length;i++) {
            int count=0;
            for (Object candidate : objects(managers[i])) if (candidate instanceof NamedObject && tagged((NamedObject)candidate,OWNER)) count++;
            rows.add(new String[]{"objects",categories[i],Integer.toString(count),"objects","managed"});
            sim.println("Managed "+categories[i]+": "+count);
        }
        for (String issue : issues) rows.add(new String[]{"issue","warning",issue,"","check"});
        try {
            java.nio.file.Path output=java.nio.file.Files.createTempFile(java.nio.file.Paths.get(resolvePath(".")),"meshBuilder_audit_",".csv");
            try (java.io.BufferedWriter writer=java.nio.file.Files.newBufferedWriter(output,java.nio.charset.StandardCharsets.UTF_8)) {
                writer.write("category,name,value,units,status\n");
                for (String[] row : rows) {
                    for (int i=0;i<row.length;i++) { if (i>0)writer.write(",");writer.write(csv(row[i])); }
                    writer.write("\n");
                }
            }
            sim.println("Audit CSV: "+output);
        } catch (Exception e) { warn(sim,"  [!] Audit CSV: "+e.getMessage()); }
        sim.println("Audit warnings: "+issues.size()+". Inspect boundary conditions and initialize/evaluate diagnostics before accepting results.");
    }
    private void cleanManagedDisplayNames(Simulation sim) {
        Object[] managers={sim.getFieldFunctionManager(),sim.getMonitorManager()};
        for (Object manager : managers) for (Object candidate : objects(manager)) {
            if (!(candidate instanceof NamedObject)) continue;
            NamedObject object=(NamedObject)candidate;
            String name=object.getPresentationName();
            if (!name.startsWith("MB_") || !tagged(object,OWNER)) continue;
            try { findOwned(sim,manager,name,NamedObject.class); }
            catch (Exception e) { warn(sim,"  [!] Display name " + name + ": " + e.getMessage()); }
        }
    }
}
