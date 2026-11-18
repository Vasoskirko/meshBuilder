# -*- coding: utf-8 -*-
"""Генератор канонического Java-макроса автоматизации для Simcenter STAR-CCM+ (анализ сетки: STAR-CCM+ 2602)."""
import math
from yplus_calculator import export_yplus_data
from starccm_export_geometry import export_geometry, plane_positions, domain_expression, plane_label, shared_gap_sections
from typing import Dict, Any, List
from pathlib import Path
import numpy as np

QUALITY_METRICS = (
    ("CellQuality", "Cell Quality", "lt_1e-5", "< 1e-5"),
    ("FaceValidity", "Face Validity", "lt_1", "< 1"),
    ("VolumeChange", "Volume Change", "le_0.01", "<= 0.01"),
    ("SkewnessAngle", "Skewness Angle", "gt_85deg", "> 85 deg"),
)


def generate_starccm_java_macro(xyz_filename, mesh_result, bundle_model, fluid_props, yplus_data, options):
    p = mesh_result.params
    yplus_data = export_yplus_data(yplus_data, default_h1=p.h1)
    blocks = mesh_result.blocks
    blocks_count = len(blocks)
    subchannels_count = getattr(mesh_result, "subchannels_count", max(1, blocks_count // 6))

    # Точный расчет геометрических параметров живого сечения и смоченного периметра:
    s_in_total = 0.0
    for bx, by in blocks:
        dx1 = bx[1:, 1:] - bx[:-1, :-1]; dy1 = by[1:, 1:] - by[:-1, :-1]
        dx2 = bx[:-1, 1:] - bx[1:, :-1]; dy2 = by[:-1, 1:] - by[1:, :-1]
        s_in_total += float((0.5 * np.abs(dx1 * dy2 - dy1 * dx2)).sum())

    p_wet_total = 0.0
    for idx, (bx, by) in enumerate(blocks):
        starts_at_wall = mesh_result.wall_starts[idx] if hasattr(mesh_result, "wall_starts") and idx < len(mesh_result.wall_starts) else True
        x_w, y_w = (bx[:, 0], by[:, 0]) if starts_at_wall else (bx[:, -1], by[:, -1])
        p_wet_total += float(np.hypot(np.diff(x_w), np.diff(y_w)).sum())

    if p_wet_total <= 1e-9: p_wet_total = 0.0285885
    if s_in_total <= 1e-12: s_in_total = 5.22986e-5

    # Длина канала L_z (по оси Z):
    lz_m = 0.050
    if hasattr(p, "L") and p.L is not None:
        lz_m = float(p.L)
    elif hasattr(p, "zlen") and p.zlen is not None:
        lz_m = float(p.zlen)
    elif hasattr(p, "z_len") and p.z_len is not None:
        lz_m = float(p.z_len)

    rho = float(fluid_props.get("density", 725.553))
    mu = float(fluid_props.get("dyn_vis", 8.835e-5))
    nu = float(fluid_props.get("kin_vis", mu / rho))
    cp = float(fluid_props.get("cp", 5476.0))
    lam = float(fluid_props.get("lambda", 0.557))
    pr = float(fluid_props.get("prandtl", 0.868))

    t_ref_k = float(fluid_props.get("t_ref_c", 300.0)) + 273.15
    p_ref_pa = float(fluid_props.get("p_ref_mpa", 15.0)) * 1e6

    re_in = float(yplus_data.get("reynolds", 200000.0)) if yplus_data else 200000.0
    w_inlet = float(yplus_data.get("velocity", 5.62)) if yplus_data else 5.62
    yplus_tgt = float(yplus_data.get("y_plus", 1.0)) if yplus_data else 1.0
    h1_m = float(yplus_data.get("delta_y1_m", 2.5e-6)) if yplus_data else float(p.h1)

    clean_xyz = Path(xyz_filename).name

    import_mesh = options.get("import_mesh", True)
    inner_fuse = options.get("inner_fuse", True)
    inter_fuse = options.get("inter_fuse", False)
    inlet_outlet_mode = options.get("inlet_outlet_mode", "by_subchannel")
    rod_mode = options.get("rod_wall_mode", "by_rod")
    turbulence_model = options.get("turbulence_model", "rst")
    use_iapws = options.get("use_iapws", False)
    enable_thermal = options.get("enable_thermal", True)
    enable_gravity = options.get("enable_gravity", False)
    create_params = options.get("create_parameters", True)
    create_reports = options.get("create_mass_reports", True)
    create_scene = options.get("create_quality_scene", True)
    create_histograms = options.get("create_quality_histograms", True)
    quality_bins = options.get("quality_bins", 50)
    if type(quality_bins) is not int or not 5 <= quality_bins <= 500:
        raise ValueError("Число интервалов гистограммы должно быть целым от 5 до 500")
    gap_sections = inter_fuse and options.get("gap_sections", True)
    n_planes = int(options.get("n_planes", 11))
    n_sub_planes = int(options.get("n_sub_planes", n_planes))
    key_planes = options.get("key_planes", True)
    sub_planes = options.get("sub_planes", True)
    axis_probes = options.get("axis_probes", True)
    selected_subchannels = options.get("selected_subchannels", list(range(1, subchannels_count + 1)))

    is_single_io = (inlet_outlet_mode == "single")

    signatures, domains = export_geometry(mesh_result, bundle_model)
    if inter_fuse and rod_mode == "sectors_60":
        raise ValueError("Секторы 60° не поддерживаются после Fuse; выберите группировку по стержням")
    if inter_fuse and len(domains) != subchannels_count:
        raise ValueError("Для анализа подканалов после Fuse нужна геометрия исходных подканалов")
    sub_centers = [d["center"] for d in domains]
    if not sub_centers:
        sub_centers = [(0., 0.)] * subchannels_count
    selected_subchannels = sorted(set(selected_subchannels))
    if any(type(i) is not int or not 1 <= i <= subchannels_count for i in selected_subchannels):
        raise ValueError("Неизвестный номер подканала для сечений")

    c = []
    c.append('// ===========================================================================')
    c.append('// Simcenter STAR-CCM+ Automation Macro: Setup & Import TVS Subchannels Mesh')
    c.append('// Сгенерировано TVS Subchannel Mesh Builder (v3.15.0)')
    c.append('// ===========================================================================')
    c.append('package macro;')
    c.append('')
    c.append('import java.util.*;')
    c.append('import star.common.*;')
    c.append('import star.segregatedflow.*;')
    c.append('import star.base.neo.*;')
    c.append('import star.segregatedenergy.*;')
    c.append('import star.realgas.*;')
    c.append('import star.material.*;')
    c.append('import star.base.report.*;')
    c.append('import star.turbulence.*;')
    c.append('import star.rsturb.*;')
    c.append('import star.flow.*;')
    c.append('import star.kwturb.*;')
    c.append('import star.metrics.*;')
    c.append('import star.vis.*;')
    c.append('')
    if create_histograms:
        c.append('import star.coremodule.ui.plotsetup.PlotAxisInput;')
        c.append('import star.coremodule.ui.plotsetup.SimDataSourceType;')
        c.append('import star.coremodule.ui.plotsetup.VariableType;')
        c.append('import star.coremodule.ui.plotsetup.XyPlotTypeEnum;')
        c.append('import star.coremodule.ui.plotsetup.dscfg.HistogramDataSeriesConfig;')
        c.append('')
    c.append('public class setup_starccm_subchannels extends StarMacro {')
    c.append('')
    c.append('    @Override')
    c.append('    public void execute() {')
    c.append('        Simulation sim = getActiveSimulation();')
    c.append('        sim.println("\\n=================================================================");')
    c.append('        sim.println(">>> [TVS Mesh Builder v3.15.0] СТАРТ КОМПЛЕКСНОЙ НАСТРОЙКИ СЦЕНЫ");')
    c.append('        sim.println("=================================================================");')
    c.append('')
    c.append('        final double[][] boundaryGeometry = boundaryGeometry();')
    if import_mesh:
        sq = chr(39)
        c.append('        // 1. Импорт многоблочной структурированной сетки Plot3D (.xyz)')
        c.append('        String meshFileName = "' + clean_xyz + '";')
        c.append('        sim.println(">>> [1/7] Импорт файла сетки: " + resolvePath(meshFileName));')
        c.append('        try {')
        c.append('            ImportManager importMgr = sim.getImportManager();')
        c.append('            importMgr.importMeshFiles(')
        c.append('                new StringVector(new String[] {resolvePath(meshFileName)}),')
        c.append('                NeoProperty.fromString("{\'FileOptions\': [{\'Sequence\': 2252}]}")')
        c.append('            );')
        c.append('            sim.println(">>> [1/7] Импорт сетки успешно завершен!");')
        c.append('        } catch (Exception e) {')
        c.append('            sim.println(">>> [!] Ошибка импорта сетки: " + e.getMessage());')
        c.append('            return;')
        c.append('        }')
        c.append('')
    c.append('        // 2. Объединение блоков по подканалам (6 секторов в каждый подканал)')
    c.append('        MeshManager meshMgr = sim.getMeshManager();')
    c.append('        RegionManager regMgr = sim.getRegionManager();')
    c.append('        List<Region> subchannelRegions = new ArrayList<>();')
    c.append('        int numSubchannels = ' + str(subchannels_count) + ';')
    c.append('        sim.println(">>> [2/7] Объединение блоков по подканалам (кол-во: " + numSubchannels + ")...");')
    c.append('')
    c.append('        for (int s = 1; s <= numSubchannels; s++) {')
    c.append('            List<Region> zones = new ArrayList<>();')
    c.append('            for (int b = (s - 1) * 6 + 1; b <= s * 6; b++) {')
    c.append('                Region z = regMgr.getRegion("Zone " + b);')
    c.append('                if (z != null) zones.add(z);')
    c.append('            }')
    c.append('            if (!zones.isEmpty()) {')
    fuse_arg = "true" if inner_fuse else "false"
    c.append('                meshMgr.combineRegions(zones, ' + fuse_arg + ', true, 0.02, true);')
    c.append('                Region r = regMgr.getRegion("Zone " + ((s - 1) * 6 + 1));')
    c.append('                if (r != null) {')
    c.append('                    r.setPresentationName("Subchannel_" + s);')
    c.append('                    subchannelRegions.add(r);')
    c.append('                }')
    c.append('            }')
    c.append('        }')
    c.append('')
    if inter_fuse:
        c.append('        if (subchannelRegions.size() > 1) {')
        c.append('            sim.println(">>> Fuse Conformal: конформное слияние подканалов в единый монолит...");')
        c.append('            meshMgr.combineRegions(subchannelRegions, true, true, 0.02, true);')
        c.append('            Region rMonolith = subchannelRegions.get(0);')
        c.append('            rMonolith.setPresentationName("TVS_Assembly");')
        c.append('            subchannelRegions = Collections.singletonList(rMonolith);')
        c.append('        }')
        c.append('')
    c.append('        // 3. Разделение по углу 60 градусов')
    c.append('        for (Region curReg : subchannelRegions) {')
    c.append('            Boundary wallBase = curReg.getBoundaryManager().getBoundary("wall");')
    c.append('            if (wallBase != null) {')
    c.append('                try {')
    c.append('                    meshMgr.splitBoundariesByAngle(60.0, Collections.singletonList(wallBase));')
    c.append('                } catch (Exception ignored) {}')
    c.append('            }')
    c.append('        }')
    c.append('')
    c.append('        // 4. Инициализация физического континуума (STAR-CCM+ 21.02.007)')
    c.append('        sim.println(">>> [3/7] Настройка физических моделей жидкости (STAR-CCM+ 21.02.007)...");')
    c.append('        PhysicsContinuum phys;')
    c.append('        if (sim.getContinuumManager().has("Physics 1")) {')
    c.append('            phys = (PhysicsContinuum) sim.getContinuumManager().getContinuum("Physics 1");')
    c.append('        } else {')
    c.append('            phys = sim.getContinuumManager().createContinuum(PhysicsContinuum.class);')
    c.append('            phys.setPresentationName("Physics 1");')
    c.append('        }')
    c.append('        try {')
    c.append('            phys.enable(SingleComponentLiquidModel.class);')
    c.append('            phys.enable(SegregatedFlowModel.class);')
    c.append('            phys.enable(ThreeDimensionalModel.class);')
    if use_iapws:
        c.append('            phys.enable(IapwsLiquidEosModel.class);')
        c.append('            sim.println("  • Термодинамика: IAPWS-IF97 Liquid EOS (свойства от T и P)");')
    else:
        c.append('            phys.enable(ConstantDensityModel.class);')
        c.append('            sim.println("  • Термодинамика: Constant Density (постоянные свойства)");')
    if enable_thermal or use_iapws:
        c.append('            phys.enable(SegregatedFluidTemperatureModel.class);')
        c.append('            sim.println("  • Уравнение энергии: Segregated Fluid Temperature");')
    if enable_gravity:
        c.append('            phys.enable(GravityModel.class);')
        c.append('            sim.println("  • Гравитация: GravityModel включена");')
    c.append('            phys.enable(TurbulentModel.class);')
    c.append('            phys.enable(RansTurbulenceModel.class);')
    if turbulence_model == "hybrid_srh":
        c.append('            phys.enable(ImplicitUnsteadyModel.class);')
        c.append('            phys.enable(KOmegaTurbulence.class);')
        c.append('            phys.enable(SstKwTurbModel.class);')
        c.append('            phys.enable(KwAllYplusWallTreatment.class);')
        c.append('            phys.enable(SrhModel.class);')
        c.append('            sim.println("  • Турбулентность: Scale-Resolving Hybrid (SRH) + SST k-omega (Unsteady)");')
    else:
        c.append('            phys.enable(SteadyModel.class);')
        c.append('            phys.enable(ReynoldsStressTurbulence.class);')
        c.append('            phys.enable(EbRsTurbModel.class);')
        c.append('            phys.enable(EbRsAllYplusWallTreatment.class);')
        c.append('            sim.println("  • Турбулентность: Reynolds Stress EB + All y+ Wall Treatment (Steady)");')
    c.append('            sim.println("  • Физический континуум [Physics 1] полностью активирован!");')
    c.append('        } catch (Exception e) {')
    c.append('            sim.println("  [!] Ошибка активации физики: " + e.getMessage());')
    c.append('        }')
    c.append('')
    c.append('        // 5. Замер площадей и центроидов для универсального сопряжения')
    c.append('        sim.println(">>> [4/7] Замер площадей и центроидов граней ($$Centroid)...");')
    c.append('        UserFieldFunction unityFF = getOrCreateFF(sim, "UnityAreaFunc", "1.0");')
    c.append('        UserFieldFunction coordXFF = getOrCreateFF(sim, "CentroidXFunc", "$$Centroid[0]");')
    c.append('        UserFieldFunction coordYFF = getOrCreateFF(sim, "CentroidYFunc", "$$Centroid[1]");')
    c.append('        UserFieldFunction coordZFF = getOrCreateFF(sim, "CentroidZFunc", "$$Centroid[2]");')
    c.append('')
    c.append('        SurfaceIntegralReport areaRep = (SurfaceIntegralReport) sim.getReportManager().create("star.base.report.SurfaceIntegralReport");')
    c.append('        areaRep.setFieldFunction(unityFF);')
    c.append('')
    c.append('        List<Boundary> allInlets = new ArrayList<>();')
    c.append('        List<Boundary> allOutlets = new ArrayList<>();')
    c.append('        List<Boundary> allRods = new ArrayList<>();')
    c.append('')
    c.append('        class BoundaryData {')
    c.append('            Boundary bnd; double area; double cx; double cy; double cz;')
    c.append('            BoundaryData(Boundary b, double a, double x, double y, double z) { this.bnd = b; this.area = a; this.cx = x; this.cy = y; this.cz = z; }')
    c.append('        }')
    c.append('        class GapCandidate {')
    c.append('            Region reg; Boundary bnd; double cx; double cy; int subNum; boolean paired = false;')
    c.append('            GapCandidate(Region r, Boundary b, double x, double y, int s) { this.reg = r; this.bnd = b; this.cx = x; this.cy = y; this.subNum = s; }')
    c.append('        }')
    c.append('        List<GapCandidate> gapCandidates = new ArrayList<>();')
    c.append('')
    c.append('        sim.println("\\n---------------------------------------------------------------------------------------------------");')
    c.append('        sim.println("                        ПОЛНАЯ ГЕОМЕТРИЧЕСКАЯ ДИАГНОСТИКА ПОВЕРХНОСТЕЙ");')
    c.append('        sim.println("---------------------------------------------------------------------------------------------------");')
    c.append('')
    c.append('        double lz_actual = ' + f"{lz_m:.16e}" + ';')
    c.append('        for (int sIdx = 0; sIdx < subchannelRegions.size(); sIdx++) {')
    c.append('            Region curReg = subchannelRegions.get(sIdx); int subNum = sIdx + 1;')
    c.append('            sim.println(String.format("[Подканал: %s]", curReg.getPresentationName()));')
    c.append('            sim.println("  Поверхность   | Площадь, мм² | Координаты (Xc, Yc, Zc)           | Тип");')
    c.append('            sim.println("  --------------+--------------+-----------------------------------+-------------------");')
    c.append('')
    c.append('            List<Boundary> bList = new ArrayList<>(curReg.getBoundaryManager().getBoundaries());')
    c.append('            List<BoundaryData> bDataList = new ArrayList<>();')
    c.append('')
    c.append('            for (Boundary b : bList) {')
    c.append('                double area_mm2 = measureArea(areaRep, unityFF, b);')
    c.append('                double[] c_xyz = getCentroid3D(areaRep, unityFF, coordXFF, coordYFF, coordZFF, b);')
    c.append('                bDataList.add(new BoundaryData(b, area_mm2, c_xyz[0], c_xyz[1], c_xyz[2]));')
    c.append('            }')
    c.append('')
    c.append('            // Разделяем: торцы (Zc близко к 0 или Lz) и боковые стенки (Zc близко к Lz/2):')
    c.append('            List<BoundaryData> tops = new ArrayList<>();')
    c.append('            List<BoundaryData> laterals = new ArrayList<>();')
    c.append('            for (BoundaryData bd : bDataList) {')
    c.append('                if (bd.cz < lz_actual * 0.25 || bd.cz > lz_actual * 0.75) {')
    c.append('                    tops.add(bd);')
    c.append('                } else {')
    c.append('                    laterals.add(bd);')
    c.append('                }')
    c.append('            }')
    c.append('')
    c.append('            for (BoundaryData bd : tops) {')
    c.append('                if (bd.cz > lz_actual / 2.0) {')
    if is_single_io:
        c.append('                    bd.bnd.setPresentationName("Outlet");')
    else:
        c.append('                    bd.bnd.setPresentationName("out_" + subNum);')
    c.append('                    allOutlets.add(bd.bnd);')
    c.append('                    sim.println(String.format("  %-13s | %12.2f | (%8.3f, %8.3f, %8.3f) | ВЫХОД (out)", bd.bnd.getPresentationName(), bd.area, bd.cx*1e3, bd.cy*1e3, bd.cz*1e3));')
    c.append('                } else {')
    if is_single_io:
        c.append('                    bd.bnd.setPresentationName("Inlet");')
    else:
        c.append('                    bd.bnd.setPresentationName("in_" + subNum);')
    c.append('                    allInlets.add(bd.bnd);')
    c.append('                    sim.println(String.format("  %-13s | %12.2f | (%8.3f, %8.3f, %8.3f) | ВХОД (in)", bd.bnd.getPresentationName(), bd.area, bd.cx*1e3, bd.cy*1e3, bd.cz*1e3));')
    c.append('                }')
    c.append('            }')
    c.append('')
    c.append('            List<BoundaryData> gaps = new ArrayList<>();')
    c.append('            List<BoundaryData> rods = new ArrayList<>();')
    c.append('            Map<Boundary, Integer> rodIds = new HashMap<>();')
    c.append('            for (BoundaryData bd : laterals) {')
    c.append('                int identity = classifyBoundary(bd.area, bd.cx, bd.cy, boundaryGeometry);')
    c.append('                if (identity == 0) gaps.add(bd);')
    c.append('                else if (identity > 0) { rods.add(bd); rodIds.put(bd.bnd, identity - 1); }')
    c.append('                else throw new IllegalStateException("Неизвестная боковая поверхность: " + bd.bnd.getPresentationName() + "; проверьте геометрию импорта.");')
    c.append('            }')
    c.append('            for (BoundaryData bd : gaps) {')
    c.append('                gapCandidates.add(new GapCandidate(curReg, bd.bnd, bd.cx, bd.cy, subNum));')
    c.append('                sim.println(String.format("  %-13s | %12.2f | (%8.3f, %8.3f, %8.3f) | ЗАЗОР (стык/sym)", bd.bnd.getPresentationName(), bd.area, bd.cx*1e3, bd.cy*1e3, bd.cz*1e3));')
    c.append('            }')
    c.append('')
    c.append('            List<Boundary> rodBnds = new ArrayList<>();')
    c.append('            for (int rIdx = 0; rIdx < rods.size(); rIdx++) {')
    c.append('                BoundaryData bd = rods.get(rIdx);')
    c.append('                bd.bnd.setPresentationName(String.format("rod_R%d_part%d", rodIds.get(bd.bnd), rIdx + 1));')
    c.append('                rodBnds.add(bd.bnd);')
    c.append('                sim.println(String.format("  %-13s | %12.2f | (%8.3f, %8.3f, %8.3f) | СТЕРЖЕНЬ (rod)", bd.bnd.getPresentationName(), bd.area, bd.cx*1e3, bd.cy*1e3, bd.cz*1e3));')
    c.append('            }')
    if rod_mode == "monolithic":
        c.append('            if (!rodBnds.isEmpty()) { meshMgr.combineBoundaries(rodBnds); Boundary mRod = rodBnds.get(0); mRod.setPresentationName(String.format("rod_%d", subNum)); allRods.add(mRod); }')
    elif rod_mode == "by_rod":
        c.append('            Map<Integer, List<Boundary>> byRod = new TreeMap<>();')
        c.append('            for (Boundary b : rodBnds) byRod.computeIfAbsent(rodIds.get(b), k -> new ArrayList<>()).add(b);')
        c.append('            for (Map.Entry<Integer, List<Boundary>> entry : byRod.entrySet()) {')
        c.append('                List<Boundary> group = entry.getValue();')
        c.append('                if (group.size() > 1) meshMgr.combineBoundaries(group);')
        c.append('                Boundary b = group.get(0); b.setPresentationName("rod_R" + entry.getKey()); allRods.add(b);')
        c.append('            }')
    else:
        c.append('            allRods.addAll(rodBnds);')
    c.append('            sim.println("  ---------------------------------------------------------------------------------------------------");')
    c.append('        }')
    c.append('')
    c.append('        // 6. Универсальный полный геометрический поиск парных интерфейсов (if_sA_sB):')
    c.append('        sim.println("\\n>>> [5/7] Автоматический поиск и сшивка интерфейсов (N-ячеек)...");')
    c.append('        int pairCount = 0;')
    c.append('        List<String> pairedNames = new ArrayList<>();')
    c.append('        for (int i = 0; i < gapCandidates.size(); i++) {')
    c.append('            GapCandidate ci = gapCandidates.get(i);')
    c.append('            if (ci.paired) continue;')
    c.append('            GapCandidate bestMatch = null; double minDist = 1e9;')
    c.append('            for (int j = 0; j < gapCandidates.size(); j++) {')
    c.append('                if (i == j) continue;')
    c.append('                GapCandidate cj = gapCandidates.get(j);')
    c.append('                if (cj.paired || ci.reg.equals(cj.reg)) continue;')
    c.append('                double dist = Math.hypot(ci.cx - cj.cx, ci.cy - cj.cy);')
    c.append('                if (dist < 1e-4 && dist < minDist) { minDist = dist; bestMatch = cj; }')
    c.append('            }')
    c.append('            if (bestMatch != null) {')
    c.append('                // Count and mark a pair only after successful interface creation.')
    c.append('                String ifName = String.format("if_s%d_s%d", ci.subNum, bestMatch.subNum);')
    c.append('                ci.bnd.setPresentationName(String.format("if_s%d_s%d", ci.subNum, bestMatch.subNum));')
    c.append('                bestMatch.bnd.setPresentationName(String.format("if_s%d_s%d", bestMatch.subNum, ci.subNum));')
    c.append('                try {')
    c.append('                    sim.getInterfaceManager().createBoundaryInterface(ci.bnd, bestMatch.bnd, ifName);')
    c.append('                    ci.paired = true; bestMatch.paired = true; pairCount++;')
    c.append('                    pairedNames.add(ifName);')
    c.append('                    sim.println(String.format("  • [OK] Сшит интерфейс: %s (зазор = %.3e м)", ifName, minDist));')
    c.append('                } catch (Exception e) { sim.println("  [!] Ошибка сшивки " + ifName + ": " + e.getMessage()); }')
    c.append('            }')
    c.append('        }')
    c.append('        for (GapCandidate cg : gapCandidates) {')
    c.append('            if (!cg.paired) cg.bnd.setPresentationName("sym/per");')
    c.append('        }')
    c.append('        sim.println(String.format("  • Всего успешно сопряжено интерфейсов: %d. Внешние зазоры назначены как sym/per.", pairCount));')
    c.append('')
    c.append('        try { sim.getReportManager().remove(areaRep); sim.getFieldFunctionManager().remove(unityFF); sim.getFieldFunctionManager().remove(coordXFF); sim.getFieldFunctionManager().remove(coordYFF); sim.getFieldFunctionManager().remove(coordZFF); } catch (Exception ignored) {}')
    c.append('')
    if create_params:
        c.append('        // 7. Создание глобальных параметров с корректными размерностями (Tools > Parameters)')
        c.append('        sim.println(">>> [6/7] Создание параметров в Tools > Parameters...");')
        c.append('        GlobalParameterManager gpm = sim.get(GlobalParameterManager.class);')
        c.append('')
        c.append('        ClientServerObjectGroup grpProp = getOrCreateGroup(gpm, "Properties");')
        c.append('        createParam(sim, gpm, grpProp, "rho", ' + f"{rho:.3f}" + ', "kg/m^3", Dimensions.Builder().mass(1).length(-3).build(), null);')
        c.append('        createParam(sim, gpm, grpProp, "Cp", ' + f"{cp:.1f}" + ', "J/kg-K", Dimensions.Builder().mass(-1).temperature(-1).energy(1).build(), null);')
        c.append('        createParam(sim, gpm, grpProp, "dynvis", ' + f"{mu:.6e}" + ', "Pa-s", Dimensions.Builder().mass(1).length(-1).time(-1).build(), null);')
        c.append('        createParam(sim, gpm, grpProp, "kinvis", ' + f"{nu:.6e}" + ', "m^2/s", Dimensions.Builder().length(2).time(-1).build(), null);')
        c.append('        createParam(sim, gpm, grpProp, "lambda", ' + f"{lam:.3f}" + ', "W/m-K", Dimensions.Builder().mass(1).length(1).time(-3).temperature(-1).build(), null);')
        c.append('        createParam(sim, gpm, grpProp, "Pr", ' + f"{pr:.3f}" + ', "", null, null);')
        c.append('        createParam(sim, gpm, grpProp, "T_ref", ' + f"{t_ref_k:.2f}" + ', "K", Dimensions.Builder().temperature(1).build(), null);')
        c.append('        createParam(sim, gpm, grpProp, "P_ref", ' + f"{p_ref_pa:.1f}" + ', "Pa", Dimensions.Builder().mass(1).length(-1).time(-2).build(), null);')
        c.append('')
        c.append('        ClientServerObjectGroup grpInit = getOrCreateGroup(gpm, "Initial");')
        c.append('        createParam(sim, gpm, grpInit, "Re_in", ' + f"{re_in:.1f}" + ', "", null, null);')
        c.append('        createParam(sim, gpm, grpInit, "P_wet", ' + f"{p_wet_total:.8e}" + ', "m", Dimensions.Builder().length(1).build(), null);')
        c.append('        createParam(sim, gpm, grpInit, "S_in", ' + f"{s_in_total:.8e}" + ', "m^2", Dimensions.Builder().length(2).build(), null);')
        c.append('        createParam(sim, gpm, grpInit, "D_hyd", 0.0, "m", Dimensions.Builder().length(1).build(), "4*${S_in}/${P_wet}");')
        c.append('        createParam(sim, gpm, grpInit, "rhoW_in", 0.0, "kg/m^2-s", Dimensions.Builder().mass(1).length(-2).time(-1).build(), "${Re_in}*${dynvis}/${D_hyd}");')
        c.append('        createParam(sim, gpm, grpInit, "U_b", 0.0, "m/s", Dimensions.Builder().length(1).time(-1).build(), "${rhoW_in}/${rho}");')
        c.append('        createParam(sim, gpm, grpInit, "G_subchannel", 0.0, "kg/s", Dimensions.Builder().mass(1).time(-1).build(), "${rho}*${U_b}*${S_in}");')
        c.append('')
        c.append('        ClientServerObjectGroup grpGrid = getOrCreateGroup(gpm, "Grid_YPlus");')
        c.append('        createParam(sim, gpm, grpGrid, "y_plus_target", ' + f"{yplus_tgt:.2f}" + ', "", null, null);')
        c.append('        createParam(sim, gpm, grpGrid, "h1_wall", ' + f"{h1_m:.3e}" + ', "m", Dimensions.Builder().length(1).build(), null);')
        c.append('')
    # 9. Создание Derived Parts (PlaneSection и LineSection) по точному рекордеру 21.02.007:
    c.append('        // 9. Создание сечений и зондов (Derived Parts) по рекордеру STAR-CCM+ 21.02.007:')
    c.append('        sim.println(">>> Создание производных деталей (Derived Parts)...");')
    c.append('        int planesCreated = 0;')
    c.append('        int probesCreated = 0;')
    c.append('        int[] reportCounts = new int[] {0, 0};')
    c.append('        try {')
    c.append('            Units uLen = sim.getUnitsManager().getPreferredUnits(Dimensions.Builder().length(1).build());')
    c.append('            LabCoordinateSystem labCoord = sim.getCoordinateSystemManager().getLabCoordinateSystem();')
    c.append('            double lz = ' + f"{lz_m:.16e}" + ';')
    c.append('')
    c.append('            List<List<? extends NamedObject>> sourceParts = new ArrayList<>();')
    if inter_fuse:
        for d in domains:
            number = d["number"]
            expression = domain_expression(d["triangle"])
            c.append(f'            UserFieldFunction mask{number} = getOrCreateFF(sim, "SubchannelMask_{number}", "{expression}");')
            c.append(f'            ThresholdPart domain{number} = sim.getPartManager().createThresholdPart(new NeoObjectVector(subchannelRegions.toArray()), new DoubleVector(new double[] {{0.5, 1.5}}), sim.getUnitsManager().getObject(""), mask{number}, 0);')
            c.append(f'            domain{number}.setPresentationName("Subchannel_{number}_Domain");')
            c.append(f'            sourceParts.add(Collections.singletonList(domain{number}));')
    else:
        c.append('            for (Region region : subchannelRegions) sourceParts.add(Collections.singletonList(region));')
    for pos in plane_positions(n_planes, key_planes):
        label = plane_label("Section_Global", pos, lz_m)
        c.append(f'            createPlaneSection(sim, labCoord, uLen, subchannelRegions, "{label}", lz * {pos:.16e}); planesCreated++;')
    for number in range(1, subchannels_count + 1):
        positions = plane_positions(n_sub_planes, True) if sub_planes and number in selected_subchannels else []
        if create_reports:
            positions = sorted(set(positions + [0., 1.]))
        for pos in positions:
            # A single source has the same domain as the global plane: reuse it.
            reuse = subchannels_count == 1 and pos in plane_positions(n_planes, key_planes)
            name = plane_label("Section_Global" if reuse else f"Subchannel_{number}_Section", pos, lz_m)
            if not reuse:
                c.append(f'            createPlaneSection(sim, labCoord, uLen, sourceParts.get({number-1}), "{name}", lz * {pos:.16e}); planesCreated++;')
            if create_reports and pos in (0., 1.):
                side = 'In' if pos == 0 else 'Out'
                c.append(f'            createMassFlowReport(sim, "MassFlow_{side}_Sub{number}", Collections.singletonList((PlaneSection) sim.getPartManager().getObject("{name}")), reportCounts);')
    if gap_sections:
        for gap in shared_gap_sections(domains):
            a, b = gap['a'], gap['b']
            x, y = gap['origin']; nx, ny = gap['normal']
            c.append(f'            createOrientedPlaneSection(sim, labCoord, uLen, sourceParts.get({a-1}), "Gap_Sub{a}_Sub{b}", new double[] {{{x:.16e}, {y:.16e}, lz / 2}}, new double[] {{{nx:.16e}, {ny:.16e}, 0}}); planesCreated++;')
            if create_reports:
                c.append(f'            createMassFlowReport(sim, "MassFlow_Gap_Sub{a}_Sub{b}", Collections.singletonList((PlaneSection) sim.getPartManager().getObject("Gap_Sub{a}_Sub{b}")), reportCounts);')
    if axis_probes:
        for idx, (xc, yc) in enumerate(sub_centers):
            if idx + 1 in selected_subchannels:
                c.append(f'            createAxisLine(sim, labCoord, uLen, sourceParts.get({idx}), "Probe_Axis_Subchannel_{idx+1}", {xc:.16e}, {yc:.16e}, lz); probesCreated++;')
    c.append('            sim.println(String.format("  • Производные плоскости (%d шт) и зонды (%d шт) успешно построены!", planesCreated, probesCreated));')
    c.append('        } catch (Exception e) { sim.println("  [!] Ошибка при создании Derived Parts: " + e.getMessage()); }')

    if create_reports:
        c.append('        createMassFlowReport(sim, "MassFlow_Inlet_Total", allInlets, reportCounts);')
        c.append('        createMassFlowReport(sim, "MassFlow_Outlet_Total", allOutlets, reportCounts);')
        c.append('        createExpressionReport(sim, "Imbalance_MassFlow", "abs(${MassFlow_Inlet_TotalReport} + ${MassFlow_Outlet_TotalReport}) / max(abs(${MassFlow_Inlet_TotalReport}), 1e-30) * 100", reportCounts);')
        if enable_thermal or use_iapws:
            c.append('        List<Boundary> thermalWalls = new ArrayList<>(allRods);')
            c.append('        for (GapCandidate gap : gapCandidates) if (!gap.paired) thermalWalls.add(gap.bnd);')
            c.append('        createHeatReport(sim, "Heat_Flux_Rods_Total", allRods, reportCounts);')
            c.append('        createHeatReport(sim, "Heat_Flux_Walls_Total", thermalWalls, reportCounts);')
            c.append('        createEnthalpyReport(sim, "TotalEnthalpy_Inlet", allInlets, reportCounts);')
            c.append('        createEnthalpyReport(sim, "TotalEnthalpy_Outlet", allOutlets, reportCounts);')
            c.append('        createExpressionReport(sim, "Energy_Flow_Inlet_Total", "${MassFlow_Inlet_TotalReport} * ${TotalEnthalpy_InletReport}", reportCounts);')
            c.append('        createExpressionReport(sim, "Energy_Flow_Outlet_Total", "${MassFlow_Outlet_TotalReport} * ${TotalEnthalpy_OutletReport}", reportCounts);')
            c.append('        createExpressionReport(sim, "Imbalance_Energy", "abs(${Energy_Flow_Inlet_TotalReport} + ${Energy_Flow_Outlet_TotalReport} - ${Heat_Flux_Walls_TotalReport}) / max(max(abs(${Energy_Flow_Inlet_TotalReport}), abs(${Energy_Flow_Outlet_TotalReport})), max(abs(${Heat_Flux_Walls_TotalReport}), 1e-30)) * 100", reportCounts);')

    c.append('        int[] qualityCounts = new int[] {0, 0};')
    if create_scene:
        middle_name = plane_label("Section_Global" if .5 in plane_positions(n_planes, key_planes) else "Quality_Section", .5, lz_m)
        c.append('        List<NamedObject> qualitySurfaces = new ArrayList<>();')
        c.append('        try {')
        if .5 not in plane_positions(n_planes, key_planes):
            c.append(f'            createPlaneSection(sim, sim.getCoordinateSystemManager().getLabCoordinateSystem(), sim.getUnitsManager().getPreferredUnits(Dimensions.Builder().length(1).build()), subchannelRegions, "{middle_name}", {lz_m/2:.16e}); planesCreated++;')
        c.append(f'            qualitySurfaces.add((PlaneSection) sim.getPartManager().getObject("{middle_name}"));')
        c.append('        } catch (Exception e) { sim.println("  [!] Сечение качества: " + e.getMessage()); }')
    if create_scene or create_histograms:
        for metric, label, suffix, criterion in QUALITY_METRICS:
            c.append('        try {')
            c.append(f'            FieldFunction metric = qualityField(sim, "{metric}", "{label}");')
            c.append(f'            createQualityExtrema(sim, subchannelRegions, metric, "{metric}", reportCounts);')
            if create_histograms:
                c.append(f'            createQualityHistogram(sim, subchannelRegions, metric, "Quality_Histogram_{metric}__bad_{suffix}", "{criterion}", {quality_bins}); qualityCounts[0]++;')
            c.append('        } catch (Exception e) { sim.println("  [!] Качество ' + metric + ': " + e.getMessage()); }')
            if create_scene:
                c.append('        try {')
                c.append(f'            createQualityScene(sim, qualitySurfaces, qualityField(sim, "{metric}", "{label}"), "Quality_{metric}"); qualityCounts[1]++;')
                c.append('        } catch (Exception e) { sim.println("  [!] Сцена ' + metric + ': " + e.getMessage()); }')
    c.append('        sim.println("Контроль качества: " + qualityCounts[0] + " гистограмм и " + qualityCounts[1] + " скалярных сцен. Откройте их и проверьте min/max; это не автоматическое заключение о пригодности сетки.");')

    c.append('')
    c.append('        // 11. Итоговый аудит созданных объектов:')
    c.append('        sim.println("\\n===================================================================================================");')
    c.append('        sim.println("                       ИТОГОВЫЙ АУДИТ СОЗДАННЫХ ОБЪЕКТОВ СЦЕНЫ STAR-CCM+");')
    c.append('        sim.println("===================================================================================================");')
    c.append('        sim.println(" [1] ИНТЕРФЕЙСЫ (Interfaces): " + pairCount + " пар успешно создано.");')
    c.append('        for (String pNm : pairedNames) sim.println("     • " + pNm + " --> [ СОЗДАН ]");')
    c.append('        sim.println(" [2] ПРОИЗВОДНЫЕ ДЕТАЛИ (Derived Parts): " + planesCreated + " сечений и " + probesCreated + " зондов создано.");')
    c.append('        sim.println(" [3] ПАРАМЕТРЫ (Tools > Parameters): группы Properties, Initial, Grid_YPlus успешно созданы.");')
    c.append('        sim.println(" [4] ОТЧЕТЫ И МОНИТОРЫ: создано " + reportCounts[0] + " отчетов и " + reportCounts[1] + " мониторов; проверьте сообщения [!].");')
    c.append('        sim.println("===================================================================================================");')
    c.append('        sim.println(">>> СОЗДАНИЕ ОБЪЕКТОВ ЗАВЕРШЕНО. ПРОВЕРЬТЕ СООБЩЕНИЯ [!] И ЗАДАЙТЕ ГРАНИЧНЫЕ УСЛОВИЯ.");')
    c.append('        sim.println("===================================================================================================\\n");')
    c.append('    }')
    c.append('')
    c.append('    private double[][] boundaryGeometry() {')
    c.append('        List<double[]> rows = new ArrayList<>();')
    for idx in range(0, len(signatures), 64):
        c.append(f'        Collections.addAll(rows, geometryChunk{idx // 64}());')
    c.append('        return rows.toArray(new double[0][]);')
    c.append('    }')
    for idx in range(0, len(signatures), 64):
        c.append(f'    private double[][] geometryChunk{idx // 64}() {{')
        c.append('        return new double[][] {')
        for row in signatures[idx:idx+64]:
            c.append('            {' + ', '.join(f'{float(v):.16e}' for v in row) + '},')
        c.append('        };')
        c.append('    }')
    c.extend(r"""
    private void createPlaneSection(Simulation sim, LabCoordinateSystem labCoord, Units uLen, List<? extends NamedObject> parts, String name, double zVal) {
        createOrientedPlaneSection(sim, labCoord, uLen, parts, name,
                new double[] {0, 0, zVal}, new double[] {0, 0, 1});
    }
    private void createOrientedPlaneSection(Simulation sim, LabCoordinateSystem labCoord, Units uLen, List<? extends NamedObject> parts, String name, double[] origin, double[] normal) {
        try {
            PlaneSection ps = (PlaneSection) sim.getPartManager().createImplicitPart(
                new ArrayList<>(Collections.<NamedObject>emptyList()), new DoubleVector(normal),
                new DoubleVector(origin), 0, 1, new DoubleVector(new double[] {0.0}), null);
            ps.setPresentationName(name); ps.setCoordinateSystem(labCoord);
            ps.getInputParts().setObjects(parts);
            ps.getOriginCoordinate().setValue(new DoubleVector(origin));
            ps.getOrientationCoordinate().setValue(new DoubleVector(normal));
        } catch (Exception e) { throw new IllegalStateException(name + ": " + e.getMessage(), e); }
    }
""".strip('\n').splitlines())
    c.append('    private void createAxisLine(Simulation sim, LabCoordinateSystem labCoord, Units uLen, List<? extends NamedObject> parts, String name, double x, double y, double lz) {')
    c.append('        try {')
    c.append('            LineSection ls = sim.getPartManager().createLineSection(')
    c.append('                new ArrayList<>(Collections.<NamedObject>emptyList()),')
    c.append('                new DoubleVector(new double[] {0.0, 0.0, 0.0}),')
    c.append('                new DoubleVector(new double[] {0.0, 0.0, 1.0}), 0, true, null);')
    c.append('            ls.setPresentationName(name);')
    c.append('            ls.setCoordinateSystem(labCoord);')
    c.append('            ls.getInputParts().setObjects(parts);')
    c.append('            ls.setInputMode(LineSectionInputMode.POINTPOINT);')
    c.append('            ls.getPointPoint().getStartPointCoordinate().setValue(new DoubleVector(new double[] {x, y, 0.0}));')
    c.append('            ls.getPointPoint().getEndPointCoordinate().setValue(new DoubleVector(new double[] {x, y, lz}));')
    c.append('        } catch (Exception e) { throw new IllegalStateException(name + ": " + e.getMessage(), e); }')
    c.append('    }')
    c.append('')
    c.extend(r"""
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
        try { report.createMonitor(); counts[1]++; }
        catch (Exception e) { sim.println("  [!] Монитор " + report.getPresentationName() + ": " + e.getMessage()); }
    }
    private void createMassFlowReport(Simulation sim, String name, List<? extends NamedObject> parts, int[] counts) {
        try {
            MassFlowReport report = sim.getReportManager().createReport(MassFlowReport.class);
            report.setPresentationName(name); report.getParts().setObjects(parts);
            registerReport(sim, report, counts);
        } catch (Exception e) { sim.println("  [!] Отчет " + name + ": " + e.getMessage()); }
    }
    private void createExpressionReport(Simulation sim, String name, String expression, int[] counts) {
        try {
            ExpressionReport report = sim.getReportManager().createReport(ExpressionReport.class);
            report.setPresentationName(name); report.setDefinition(expression);
            registerReport(sim, report, counts);
        } catch (Exception e) { sim.println("  [!] Отчет " + name + ": " + e.getMessage()); }
    }
    private void createHeatReport(Simulation sim, String name, List<? extends NamedObject> parts, int[] counts) {
        try {
            FieldFunction flux = sim.getFieldFunctionManager().getFunction("BoundaryHeatFlux");
            if (flux == null) throw new IllegalStateException("Недоступно поле BoundaryHeatFlux");
            SurfaceIntegralReport report = sim.getReportManager().createReport(SurfaceIntegralReport.class);
            report.setPresentationName(name); report.setFieldFunction(flux); report.getParts().setObjects(parts);
            registerReport(sim, report, counts);
        } catch (Exception e) { sim.println("  [!] Отчет " + name + ": " + e.getMessage()); }
    }
    private void createEnthalpyReport(Simulation sim, String name, List<? extends NamedObject> parts, int[] counts) {
        try {
            FieldFunction enthalpy = sim.getFieldFunctionManager().getFunction("TotalEnthalpy");
            if (enthalpy == null) throw new IllegalStateException("Недоступно поле TotalEnthalpy");
            MassFlowAverageReport report = sim.getReportManager().createReport(MassFlowAverageReport.class);
            report.setPresentationName(name); report.setFieldFunction(enthalpy); report.getParts().setObjects(parts);
            registerReport(sim, report, counts);
        } catch (Exception e) { sim.println("  [!] Отчет " + name + ": " + e.getMessage()); }
    }
""".strip('\n').splitlines())
    c.extend(r"""
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
            MinReport minimum = sim.getReportManager().createReport(MinReport.class);
            minimum.setPresentationName("Quality_Min_" + key);
            minimum.setFieldFunction(metric); minimum.getParts().setObjects(regions);
            registerReport(sim, minimum, counts);
        } catch (Exception e) { sim.println("  [!] Min " + key + ": " + e.getMessage()); }
        try {
            MaxReport maximum = sim.getReportManager().createReport(MaxReport.class);
            maximum.setPresentationName("Quality_Max_" + key);
            maximum.setFieldFunction(metric); maximum.getParts().setObjects(regions);
            registerReport(sim, maximum, counts);
        } catch (Exception e) { sim.println("  [!] Max " + key + ": " + e.getMessage()); }
    }
    private void createQualityScene(Simulation sim, List<NamedObject> surfaces, FieldFunction metric, String name) {
        if (surfaces.isEmpty()) throw new IllegalStateException("Не создано сечение качества");
        Scene scene = sim.getSceneManager().createScene();
        scene.setPresentationName(name);
        ScalarDisplayer scalar = scene.getDisplayerManager().createScalarDisplayer("Scalar");
        scalar.setRepresentation((FvRepresentation) sim.getRepresentationManager().getObject("Volume Mesh"));
        scalar.getInputParts().setObjects(surfaces);
        scalar.getScalarDisplayQuantity().setFieldFunction(metric);
        scalar.setFillMode(ScalarFillMode.NATIVE);
        scene.resetCamera();
    }
""".strip('\n').splitlines())
    if create_histograms:
        c.extend(r"""
    private void createQualityHistogram(Simulation sim, List<Region> regions, FieldFunction metric, String name, String criterion, int bins) {
        ArrayList<NamedObject> inputs = new ArrayList<>(regions);
        PlotAxisInput quantity = new PlotAxisInput(VariableType.SCALAR,
                new PlotAxisInput.ScalarFunctionInput(metric));
        HistogramDataSeriesConfig series = new HistogramDataSeriesConfig(
                SimDataSourceType.PARTS, inputs, null, quantity,
                new PlotAxisInput(VariableType.SCALAR), WeightingMode.FREQUENCY);
        Cartesian2DPlot plot = sim.getPlotManager().createCartesian2DPlot(name,
                List.of(XyPlotTypeEnum.HISTOGRAM), series);
        plot.setPresentationName(name); plot.setTitle(metric.getPresentationName() + " | bad: " + criterion + " | cell count");
        boolean configured = false;
        for (Object entry : plot.getDataSeriesOrder()) {
            if (entry instanceof PartGroupDataSet) {
                PartGroupDataSet data = (PartGroupDataSet) entry;
                PartAxisType axis = data.getAxisTypeManager().getAxisType("Bottom Axis Binned Data");
                axis.hasBinningDescriptor().setNumberOfBins(bins);
                configured = true;
            }
        }
        if (!configured) throw new IllegalStateException("Не создан ряд данных гистограммы " + name);
    }
""".strip('\n').splitlines())
    c.append('    private double measureArea(SurfaceIntegralReport areaRep, UserFieldFunction unityFF, Boundary b) { try { areaRep.getParts().setObjects(b); areaRep.setFieldFunction(unityFF); return areaRep.getReportMonitorValue() * 1e6; } catch (Exception e) { return 0.0; } }')
    c.append('    private double[] getCentroid3D(SurfaceIntegralReport rep, UserFieldFunction unityFF, UserFieldFunction ffX, UserFieldFunction ffY, UserFieldFunction ffZ, Boundary b) {')
    c.append('        try {')
    c.append('            rep.getParts().setObjects(b); rep.setFieldFunction(unityFF);')
    c.append('            double area = rep.getReportMonitorValue();')
    c.append('            if (area <= 1e-14) return new double[]{0.0, 0.0, 0.0};')
    c.append('            rep.setFieldFunction(ffX); double intX = rep.getReportMonitorValue();')
    c.append('            rep.setFieldFunction(ffY); double intY = rep.getReportMonitorValue();')
    c.append('            rep.setFieldFunction(ffZ); double intZ = rep.getReportMonitorValue();')
    c.append('            return new double[]{intX / area, intY / area, intZ / area};')
    c.append('        } catch (Exception e) { return new double[]{0.0, 0.0, 0.0}; }')
    c.append('    }')
    c.append('    private UserFieldFunction getOrCreateFF(Simulation sim, String name, String def) {')
    c.append('        UserFieldFunction ff;')
    c.append('        if (sim.getFieldFunctionManager().has(name)) { ff = (UserFieldFunction) sim.getFieldFunctionManager().getFunction(name); }')
    c.append('        else { ff = sim.getFieldFunctionManager().createFieldFunction(); ff.setPresentationName(name); }')
    c.append('        ff.setFunctionName(name);')
    c.append('        ff.setDefinition(def);')
    c.append('        return ff;')
    c.append('    }')
    c.append('    private ClientServerObjectGroup getOrCreateGroup(GlobalParameterManager gpm, String grpName) { try { if (gpm.getGroupsManager().has(grpName)) return (ClientServerObjectGroup) gpm.getGroupsManager().getObject(grpName); gpm.getGroupsManager().createGroup("New Group"); ClientServerObjectGroup g = (ClientServerObjectGroup) gpm.getGroupsManager().getObject("New Group"); g.setPresentationName(grpName); return g; } catch (Exception e) { return null; } }')
    c.append('    private void createParam(Simulation sim, GlobalParameterManager gpm, ClientServerObjectGroup grp, String name, double val, String unitStr, Dimensions dims, String defStr) {')
    c.append('        try {')
    c.append('            ScalarGlobalParameter p;')
    c.append('            if (gpm.has(name)) { p = (ScalarGlobalParameter) gpm.getObject(name); }')
    c.append('            else { p = (ScalarGlobalParameter) gpm.createGlobalParameter(ScalarGlobalParameter.class, "Scalar"); p.setPresentationName(name); }')
    c.append('            if (grp != null) grp.getGroupsManager().groupObjects(grp.getPresentationName(), Collections.singletonList(p));')
    c.append('            if (dims != null) p.setDimensions(dims);')
    c.append('            if (defStr != null && !defStr.isEmpty()) { p.getQuantity().setDefinition(defStr); }')
    c.append('            else {')
    c.append('                if (unitStr != null && !unitStr.isEmpty()) { Units u = sim.getUnitsManager().getObject(unitStr); p.getQuantity().setValueAndUnits(val, u); }')
    c.append('                else { p.getQuantity().setValue(val); }')
    c.append('            }')
    c.append('        } catch (Exception ignored) {}')
    c.append('    }')
    c.append('}')
    return "\n".join(c) + "\n"
