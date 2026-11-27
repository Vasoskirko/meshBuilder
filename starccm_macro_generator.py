# -*- coding: utf-8 -*-
"""Генератор канонического Java-макроса автоматизации для Simcenter STAR-CCM+ (анализ сетки: STAR-CCM+ 2602)."""
import math
import hashlib
import json
import re
from starccm_macro_support import JAVA_SUPPORT
from starccm_analysis import ANALYSIS_SUPPORT
from starccm_physics_support import PHYSICS_SUPPORT
from starccm_group_support import GROUP_SUPPORT
from starccm_audit_support import AUDIT_SUPPORT
from starccm_export_profile import FIELD_CHOICES, REPORT_CHOICES, MEAN_CHOICES
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
    workflow=None
    if 'workflow' in options:
        from copy import deepcopy
        from starccm_workflow import validate_workflow
        workflow=validate_workflow(options['workflow']);options=deepcopy(options)
        fluid_props=dict(fluid_props,**workflow['fluid'])
        if not workflow['quality_enabled']:
            options.update(create_quality_scene=False,create_quality_histograms=False,create_bad_cells=False)
            if 'field_functions' in options:options['field_functions']=[key for key in options['field_functions'] if key!='quality']
        if options.get('use_iapws'):
            options['enable_thermal']=True
    from starccm_surface_catalog import validate_surface_settings
    catalog=validate_surface_settings(mesh_result,bundle_model,options) if workflow else None
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

    required_values = dict(density=rho, viscosity=mu, temperature=t_ref_k, pressure=p_ref_pa)
    if options.get("enable_thermal", True):
        required_values.update(cp=cp, conductivity=lam)
    if any(not math.isfinite(value) or value <= 0 for value in required_values.values()):
        raise ValueError("Физические свойства, абсолютные температура и давление должны быть конечными и положительными")
    re_in = float(yplus_data.get("reynolds", 200000.0)) if yplus_data else 200000.0
    w_inlet = float(yplus_data.get("velocity", 5.62)) if yplus_data else 5.62
    if workflow and workflow["initial_velocity"]=="zero":w_inlet=0.
    if workflow and p_ref_pa+workflow["initial_pressure"]<=0:raise ValueError("Начальное абсолютное давление должно быть положительным")
    if not math.isfinite(w_inlet):
        raise ValueError("Начальная скорость должна быть конечным числом")
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
    gravity_axis = options.get("gravity_axis", "-Z")
    if gravity_axis not in ("-X","+X","-Y","+Y","-Z","+Z"):
        raise ValueError("Неизвестное направление гравитации")
    gravity_vector=[0.,0.,0.]
    gravity_vector["XYZ".index(gravity_axis[1])]=9.81 if gravity_axis[0]=="+" else -9.81
    evaluate_solution = options.get("evaluate_solution_reports", False)
    initialize_solution = options.get("initialize_solution", True)
    create_params = options.get("create_parameters", True)
    create_reports = options.get("create_mass_reports", True)
    create_scene = options.get("create_quality_scene", True)
    create_histograms = options.get("create_quality_histograms", True)
    quality_bins = options.get("quality_bins", 50)
    if type(quality_bins) is not int or not 5 <= quality_bins <= 500:
        raise ValueError("Число интервалов гистограммы должно быть целым от 5 до 500")
    create_bad_cells = options.get("create_bad_cells", True)
    group_objects = options.get("group_objects", True)
    create_summary = options.get("create_summary", True)
    create_field_functions = options.get("create_field_functions", True)
    field_choices = options.get("field_functions", list(FIELD_CHOICES)) if create_field_functions else []
    analysis_choices = options.get("subchannel_reports", [])
    is_unsteady=turbulence_model=="hybrid_srh" or (workflow is not None and workflow["run_mode"]=="unsteady")
    if workflow and workflow["run_mode"]=="steady" and turbulence_model=="hybrid_srh":raise ValueError("Hybrid SRH–SST требует нестационарного режима")
    mean_choices = options.get("time_mean_fields", []) if is_unsteady else []
    for selected, choices in ((field_choices, FIELD_CHOICES), (analysis_choices, REPORT_CHOICES), (mean_choices, MEAN_CHOICES)):
        if not isinstance(selected, list) or any(type(v) is not str or v not in choices for v in selected) or len(set(selected)) != len(selected):
            raise ValueError("Неизвестный или повторяющийся выбор полей/отчётов")
    time_step=options.get('time_step',1e-4)
    if isinstance(time_step,bool) or not isinstance(time_step,(int,float)) or not math.isfinite(time_step) or time_step<=0:
        raise ValueError('Шаг времени Δt должен быть положительным конечным числом')
    custom_surfaces=bool(workflow and catalog and catalog['domains'] and not workflow['tdc_enabled'])
    preserve_sectors=(inter_fuse and rod_mode=='sectors_60') or custom_surfaces
    mean_start = options.get("mean_start_step", 1)
    if workflow and workflow['mean_start_auto'] and is_unsteady:mean_start=math.ceil(workflow['warmup_duration']/float(options.get('time_step',1e-4))-1e-12)+1
    if type(mean_start) is not int or not 1 <= mean_start <= 1000000000:
        raise ValueError("Неверный начальный шаг усреднения")
    gap_sections = inter_fuse and options.get("gap_sections", True)
    n_planes = int(options.get("n_planes", 11))
    n_sub_planes = int(options.get("n_sub_planes", n_planes))
    key_planes = options.get("key_planes", True)
    sub_planes = options.get("sub_planes", True)
    axis_probes = options.get("axis_probes", True)
    selected_subchannels = options.get("selected_subchannels", list(range(1, subchannels_count + 1)))

    is_single_io = (inlet_outlet_mode == "single")

    signatures, domains = export_geometry(mesh_result, bundle_model)
    if inter_fuse and len(domains) != subchannels_count:
        raise ValueError("Для анализа подканалов после Fuse нужна геометрия исходных подканалов")
    sub_centers = [d["center"] for d in domains]
    if not sub_centers:
        sub_centers = [(0., 0.)] * subchannels_count
    selected_subchannels = sorted(set(selected_subchannels))
    if any(type(i) is not int or not 1 <= i <= subchannels_count for i in selected_subchannels):
        raise ValueError("Неизвестный номер подканала для сечений")

    report_selected=selected_subchannels if not workflow or workflow['report_subchannels']==[-1] else workflow['report_subchannels']
    if any(n>subchannels_count for n in report_selected):raise ValueError('Неизвестный подканал для отчётов')
    if workflow:
        from starccm_flow_defaults import calculator_mass_flow
        for pair in workflow['boundary_pairs']:
            if pair.get('mass_flow_auto'):pair['mass_flow']=calculator_mass_flow(catalog,fluid_props,yplus_data,pair['first'])
    digest = hashlib.sha256()
    topology_settings=dict(schema=2 if custom_surfaces else 1,inter_fuse=inter_fuse,rod_mode=rod_mode,io=inlet_outlet_mode,nz=p.nz,height=lz_m)
    if custom_surfaces:topology_settings.update(disabled_internal_pairs=workflow['disabled_internal_pairs'],pairs=workflow['boundary_pairs'],conditions=workflow['boundary_conditions'],rod_kinds={str(rid):bundle_model.rods[rid].rod_type for row in catalog['rods'] for rid in row['rod_ids']})
    digest.update(json.dumps(topology_settings,sort_keys=True).encode())
    for block in blocks:
        for coordinate in block:
            values=np.asarray(coordinate,dtype='<f8')
            digest.update(str(values.shape).encode());digest.update(values.tobytes())
    digest.update(json.dumps(dict(sources=[str(d["source_id"]) for d in domains],
        physical_rods=sorted({int(row[1]) for row in signatures if row[0]==1}), inner_fuse=inner_fuse),sort_keys=True).encode())
    fingerprint=digest.hexdigest()
    expected_cells=sum((x.shape[0]-1)*(x.shape[1]-1)*p.nz for x,y in blocks)

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
    c.append('import star.energy.*;')
    c.append('import star.base.report.*;')
    c.append('import star.turbulence.*;')
    c.append('import star.rsturb.*;')
    c.append('import star.flow.*;')
    c.append('import star.kwturb.*;')
    c.append('import star.walldistance.*;')
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
    metadata=json.dumps(dict(options=options,subchannels=subchannels_count,expected_cells=expected_cells,
        height_m=lz_m,fluid_density=rho,fluid_dynamic_viscosity=mu),ensure_ascii=True,sort_keys=True)
    c.append('    private final String exportSettings = ' + json.dumps(metadata) + ';')
    c.append('')
    c.append('    @Override')
    c.append('    public void execute() {')
    c.append('        Simulation sim = getActiveSimulation();')
    c.append('        issues.clear();')
    c.append('        sim.println("\\n=================================================================");')
    c.append('        sim.println(">>> [TVS Mesh Builder v3.15.0] СТАРТ КОМПЛЕКСНОЙ НАСТРОЙКИ СЦЕНЫ");')
    c.append('        sim.println("=================================================================");')
    c.append('')
    c.append('        final String exportFingerprint = "' + fingerprint + '";')
    c.append('        final long expectedCells = ' + str(expected_cells) + 'L;')
    c.append('        MeshManager meshMgr = sim.getMeshManager();')
    c.append('        RegionManager regMgr = sim.getRegionManager();')
    c.append('        List<Region> subchannelRegions = preparedRegions(sim,exportFingerprint,' + str(1 if inter_fuse else subchannels_count) + ');')
    c.append('        boolean reuse = !subchannelRegions.isEmpty();')
    c.append('        PhysicsContinuum setupPhysics = null;')
    c.append('        boolean physicalValuesConfigured = false;')
    c.append('        List<Boundary> allInlets = new ArrayList<>(), allOutlets = new ArrayList<>(), allRods = new ArrayList<>();')
    c.append('        class GapCandidate {')
    c.append('            Region reg; Boundary bnd; double cx; double cy; int subNum; boolean paired = false;')
    c.append('            GapCandidate(Region r, Boundary b, double x, double y, int n) { reg=r;bnd=b;cx=x;cy=y;subNum=n; }')
    c.append('        }')
    c.append('        List<GapCandidate> gapCandidates = new ArrayList<>();')
    c.append('        int pairCount = 0; List<String> pairedNames = new ArrayList<>();')
    c.append('        if (!reuse) {')
    if import_mesh:
        c.append('        if (!regMgr.getRegions().isEmpty()) throw new IllegalStateException("Use an empty simulation for first import; existing regions are not replaced.");')
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
    if preserve_sectors:
        c.append('        // Preserve source-sector boundaries BEFORE inter-subchannel Fuse.')
        c.append('        for (int source=0;source<subchannelRegions.size();source++) {')
        c.append('            Region original=subchannelRegions.get(source);')
        c.append('            Boundary originalWall=original.getBoundaryManager().getBoundary("wall");')
        c.append('            if (originalWall!=null) meshMgr.splitBoundariesByAngle(60.0,Collections.singletonList(originalWall));')
        c.append('            int part=0; for (Boundary boundary : original.getBoundaryManager().getBoundaries())')
        c.append('                boundary.setPresentationName("SRC_s"+(source+1)+"_part"+(++part));')
        c.append('        }')
    if inter_fuse:
        c.append('        if (subchannelRegions.size() > 1) {')
        c.append('            sim.println(">>> Fuse Conformal: конформное слияние подканалов в единый монолит...");')
        c.append('            meshMgr.combineRegions(subchannelRegions, true, true, 0.02, true);')
        c.append('            Region rMonolith = subchannelRegions.get(0);')
        c.append('            rMonolith.setPresentationName("TVS_Assembly");')
        c.append('            subchannelRegions = Collections.singletonList(rMonolith);')
        c.append('        }')
        c.append('')
    if not preserve_sectors:
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
        c.append('            phys.getReferenceValues().get(Gravity.class).setConstant(new double[] {' + ','.join(str(v) for v in gravity_vector) + '});')
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
        c.append('            phys.enable(ImplicitUnsteadyModel.class);' if is_unsteady else '            phys.enable(SteadyModel.class);')
        c.append('            phys.enable(ReynoldsStressTurbulence.class);')
        c.append('            phys.enable(EbRsTurbModel.class);')
        c.append('            phys.enable(EbRsAllYplusWallTreatment.class);')
        c.append('            sim.println("  • Турбулентность: Reynolds Stress EB + All y+ Wall Treatment (Steady)");')
    c.append('            setupPhysics = phys; own(sim,phys);')
    c.append('            sim.println("  • Физический континуум [Physics 1] полностью активирован!");')
    c.append('        } catch (Exception e) {')
    c.append('            sim.println("  [!] Ошибка активации физики: " + e.getMessage());')
    c.append('        }')
    c.append('')
    c.append('        // 5. Замер площадей и центроидов для универсального сопряжения')
    c.append('        sim.println(">>> [4/7] Замер площадей и центроидов граней ($$Centroid)...");')
    c.append('        UserFieldFunction unityFF = getOrCreateFF(sim, "MB_One", "1.0");')
    c.append('        UserFieldFunction coordXFF = getOrCreateFF(sim, "MB_X", "$$Centroid[0]");')
    c.append('        UserFieldFunction coordYFF = getOrCreateFF(sim, "MB_Y", "$$Centroid[1]");')
    c.append('        UserFieldFunction coordZFF = getOrCreateFF(sim, "MB_Z", "$$Centroid[2]");')
    c.append('        unityFF.setDimensions(Dimensions.Builder().build());')
    c.append('        coordXFF.setDimensions(Dimensions.Builder().length(1).build());')
    c.append('        coordYFF.setDimensions(Dimensions.Builder().length(1).build());')
    c.append('        coordZFF.setDimensions(Dimensions.Builder().length(1).build());')
    c.append('')
    c.append('        SurfaceIntegralReport areaRep = (SurfaceIntegralReport) sim.getReportManager().create("star.base.report.SurfaceIntegralReport");')
    c.append('        areaRep.setFieldFunction(unityFF);')
    c.append('')
    c.append('')
    c.append('        class BoundaryData {')
    c.append('            Boundary bnd; double area; double cx; double cy; double cz;')
    c.append('            BoundaryData(Boundary b, double a, double x, double y, double z) { this.bnd = b; this.area = a; this.cx = x; this.cy = y; this.cz = z; }')
    c.append('        }')
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
    if preserve_sectors:
        c.append('                String source=bd.bnd.getPresentationName().split("_",3)[1];')
        c.append('                bd.bnd.setPresentationName("rod_"+source+"_R"+rodIds.get(bd.bnd)+"_part"+(rIdx+1));')
    else:
        c.append('                bd.bnd.setPresentationName(String.format("rod_R%d_part%d", rodIds.get(bd.bnd), rIdx + 1));')
    c.append('                rodBnds.add(bd.bnd);')
    c.append('                sim.println(String.format("  %-13s | %12.2f | (%8.3f, %8.3f, %8.3f) | СТЕРЖЕНЬ (rod)", bd.bnd.getPresentationName(), bd.area, bd.cx*1e3, bd.cy*1e3, bd.cz*1e3));')
    c.append('            }')
    if custom_surfaces:
        kinds={rid:('rod' if rod.rod_type=='fuel' else 'guide' if rod.rod_type=='guide' else 'instrument') for rid,rod in bundle_model.rods.items()}
        c.append('            Map<Integer,String> rodKinds=new HashMap<>();')
        for rid,kind in kinds.items():c.append(f'            rodKinds.put({rid},"{kind}");')
        c.append('            Map<String,List<Boundary>> surfaceGroups=new TreeMap<>();')
        c.append('            for (Boundary b : rodBnds) {')
        c.append('                java.util.regex.Matcher source=java.util.regex.Pattern.compile("rod_s([0-9]+)_.*").matcher(b.getPresentationName());')
        c.append('                if (!source.matches()) throw new IllegalStateException("Source identity lost before wall grouping");')
        c.append('                int n=Integer.parseInt(source.group(1)), r=rodIds.get(b);')
        key_expr='"s"+n+"_R"+r' if rod_mode=='sectors_60' else ('"R"+r' if rod_mode=='by_rod' else '"s"+n')
        c.append('                String key=rodKinds.get(r)+"_"+('+key_expr+');')
        c.append('                surfaceGroups.computeIfAbsent(key,k->new ArrayList<>()).add(b);')
        c.append('            }')
        c.append('            for (Map.Entry<String,List<Boundary>> entry : surfaceGroups.entrySet()) {')
        c.append('                List<Boundary> members=entry.getValue(); if (members.size()>1) meshMgr.combineBoundaries(members);')
        c.append('                Boundary boundary=members.get(0); boundary.setPresentationName(entry.getKey());')
        c.append('                if (entry.getKey().startsWith("rod_")) mark(sim,boundary,"meshBuilder.HeatGroup."+entry.getKey());')
        c.append('                allRods.add(boundary);')
        c.append('            }')
    elif rod_mode == "monolithic":
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
    c.append('        for (int i = 0; i < gapCandidates.size(); i++) {')
    c.append('            GapCandidate ci = gapCandidates.get(i);')
    c.append('            if (ci.paired) continue;')
    manual_shared=[]
    if custom_surfaces:
        pair_keys={p[k] for p in workflow['boundary_pairs'] for k in ('first','second')}|{bc['surface'] for bc in workflow['boundary_conditions']}
        manual_shared=[r for r in catalog['sides'] if r['shared'] and r['id'] in pair_keys]
        for row in manual_shared:
            cx,cy=row['center'];source=row['source']
            c.append(f'            if(ci.subNum=={source} && Math.hypot(ci.cx-({cx:.16e}),ci.cy-({cy:.16e}))<1e-8)continue;')

    c.append('            GapCandidate bestMatch = null; double minDist = 1e9;')
    c.append('            for (int j = 0; j < gapCandidates.size(); j++) {')
    c.append('                if (i == j) continue;')
    c.append('                GapCandidate cj = gapCandidates.get(j);')
    c.append('                if (cj.paired || ci.reg.equals(cj.reg)) continue;')
    for row in manual_shared:
        cx,cy=row['center'];source=row['source']
        c.append(f'                if(cj.subNum=={source} && Math.hypot(cj.cx-({cx:.16e}),cj.cy-({cy:.16e}))<1e-8)continue;')

    if custom_surfaces:
        seen=set()
        for row in catalog['sides']:
            if row['pair_id'] not in workflow['disabled_internal_pairs'] or row['pair_id'] in seen:continue
            seen.add(row['pair_id']);a,b=row['source'],row['neighbor']
            c.append(f'                if ((ci.subNum=={a} && cj.subNum=={b}) || (ci.subNum=={b} && cj.subNum=={a})) continue;')
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
    if custom_surfaces:
        c.append('            if (!cg.paired) {')
        c.append('                double area=measureArea(areaRep,unityFF,cg.bnd); String side=null;')
        for row in catalog['sides']:
            if row['shared'] and inter_fuse:continue
            area=row['area']*1e6;cx,cy=row['center']
            source_check='' if inter_fuse else f'cg.subNum=={row["source"]} && '
            c.append(f'                if ({source_check}Math.abs(area-{area:.16e})<=Math.max(area,{area:.16e})*1e-5 && Math.hypot(cg.cx-({cx:.16e}),cg.cy-({cy:.16e}))<1e-8) {{ if(side!=null)throw new IllegalStateException("Ambiguous side"); side="{row["id"]}"; }}')
        c.append('                if(side==null)throw new IllegalStateException("Unmatched external surface"); cg.bnd.setPresentationName(side);')
        c.append('            }')
    else:
        c.append('            if (!cg.paired) cg.bnd.setPresentationName("sym/per");')
    c.append('        }')
    if custom_surfaces:
        c.append('        sim.println(String.format("Interfaces created: %d. Unpaired Side_* boundaries remain walls. Verify periodic orientation before solving.", pairCount));')
    else:
        c.append('        sim.println(String.format("  • Всего успешно сопряжено интерфейсов: %d. Внешние зазоры назначены как sym/per.", pairCount));')
    c.append('')
    c.append('        try { sim.getReportManager().remove(areaRep);  } catch (Exception ignored) {}')
    c.append('')
    c.append('        List<Boundary> externalGaps = new ArrayList<>();')
    c.append('        for (GapCandidate gap : gapCandidates) if (!gap.paired) externalGaps.add(gap.bnd);')
    if inter_fuse and (preserve_sectors or custom_surfaces):
        c.append('        // Merge only end caps; retain the separate source rod sectors.')
        c.append('        if (allInlets.size()>1) { Boundary inlet=allInlets.get(0); meshMgr.combineBoundaries(new ArrayList<>(allInlets)); allInlets.clear(); allInlets.add(inlet); inlet.setPresentationName("Inlet"); }')
        c.append('        if (allOutlets.size()>1) { Boundary outlet=allOutlets.get(0); meshMgr.combineBoundaries(new ArrayList<>(allOutlets)); allOutlets.clear(); allOutlets.add(outlet); outlet.setPresentationName("Outlet"); }')
    if custom_surfaces:
        if not inter_fuse:
            for collection in ('allInlets','allOutlets'):
                c.append(f'        for(Region region:subchannelRegions) {{ List<Boundary> caps=new ArrayList<>(); for(Boundary b:{collection})if(b.getRegion()==region)caps.add(b); if(caps.size()>1) {{ Boundary first=caps.get(0);meshMgr.combineBoundaries(caps);{collection}.removeAll(caps);{collection}.add(first); }} }}')
        for cap in catalog['endcaps']:
            collection='allInlets' if cap['role']=='Inlet' else 'allOutlets'
            condition='true' if inter_fuse else f'b.getRegion()==subchannelRegions.get({cap["sources"][0]-1})'
            c.append(f'        for(Boundary b:{collection}) if({condition}) b.setPresentationName("{cap["id"]}");')
    c.append('        markBoundaryRoles(sim,allInlets,allOutlets,allRods,externalGaps);')
    c.append('        for (int i=0;i<subchannelRegions.size();i++) {')
    c.append('            Region region=subchannelRegions.get(i); own(sim,region);')
    c.append('            mark(sim,region,"meshBuilder.Mesh." + exportFingerprint); mark(sim,region,"meshBuilder.Source." + (i+1));')
    c.append('        }')
    c.append('        for (Object object : objects(sim.getInterfaceManager())) if (object instanceof NamedObject && pairedNames.contains(((NamedObject)object).getPresentationName())) own(sim,(NamedObject)object);')
    c.append('        } else {')
    c.append('            ElementCountReport check = sim.getReportManager().createReport(ElementCountReport.class);')
    c.append('            try { check.getParts().setObjects(subchannelRegions); double cells=check.getReportMonitorValue(); if (!Double.isFinite(cells) || Math.abs(cells-expectedCells)>.5) throw new IllegalStateException("Managed mesh cell count changed; use a new simulation."); }')
    c.append('            finally { sim.getReportManager().remove(check); }')
    c.append('            sim.println("Same export detected: update managed analysis only; mesh, physics and boundary conditions retained.");')
    c.append('            for (Region region : subchannelRegions) for (Boundary b : region.getBoundaryManager().getBoundaries()) {')
    c.append('                if (tagged(b,"meshBuilder.Role.Inlet")) allInlets.add(b);')
    c.append('                if (tagged(b,"meshBuilder.Role.Outlet")) allOutlets.add(b);')
    c.append('                if (tagged(b,"meshBuilder.Role.Rod")) allRods.add(b);')
    c.append('                if (tagged(b,"meshBuilder.Role.Gap")) gapCandidates.add(new GapCandidate(region,b,0,0,0));')
    c.append('            }')
    c.append('            for (Object object : objects(sim.getInterfaceManager())) if (object instanceof NamedObject && tagged((NamedObject)object,OWNER)) { pairCount++; pairedNames.add(((NamedObject)object).getPresentationName()); }')
    c.append('        }')
    c.append('        cleanManagedDisplayNames(sim);')
    c.append('        if (!reuse) {')
    c.append('        // 7. Создание глобальных параметров с корректными размерностями (Tools > Parameters)')
    c.append('        sim.println(">>> [6/7] Создание параметров в Tools > Parameters...");')
    c.append('        GlobalParameterManager gpm = sim.get(GlobalParameterManager.class);')
    c.append('')
    c.append('        createParam(sim, gpm, null, "rho", ' + f"{rho:.16e}" + ', "kg/m^3", Dimensions.Builder().mass(1).length(-3).build(), null);')
    c.append('        createParam(sim, gpm, null, "Cp", ' + f"{cp:.16e}" + ', "J/kg-K", Dimensions.Builder().mass(-1).temperature(-1).energy(1).build(), null);')
    c.append('        createParam(sim, gpm, null, "dynvis", ' + f"{mu:.16e}" + ', "Pa-s", Dimensions.Builder().mass(1).length(-1).time(-1).build(), null);')
    c.append('        createParam(sim, gpm, null, "kinvis", ' + f"{nu:.6e}" + ', "m^2/s", Dimensions.Builder().length(2).time(-1).build(), null);')
    c.append('        createParam(sim, gpm, null, "lambda", ' + f"{lam:.16e}" + ', "W/m-K", Dimensions.Builder().mass(1).length(1).time(-3).temperature(-1).build(), null);')
    c.append('        createParam(sim, gpm, null, "Pr", ' + f"{pr:.16e}" + ', "", null, null);')
    c.append('        createParam(sim, gpm, null, "T_ref", ' + f"{t_ref_k:.16e}" + ', "K", Dimensions.Builder().temperature(1).build(), null);')
    c.append('        createParam(sim, gpm, null, "P_ref", ' + f"{p_ref_pa:.16e}" + ', "Pa", Dimensions.Builder().mass(1).length(-1).time(-2).build(), null);')
    c.append('')
    c.append('        createParam(sim,gpm,null,"P_init",'+str(workflow['initial_pressure'] if workflow else 0.)+',"Pa",Dimensions.Builder().mass(1).length(-1).time(-2).build(),null);')
    if workflow:
        c.append('        createParam(sim,gpm,null,"T_init",'+str(workflow['initial_temperature'])+',"K",Dimensions.Builder().temperature(1).build(),null);')
    else:
        c.append('        createParam(sim,gpm,null,"T_init",0.0,"K",Dimensions.Builder().temperature(1).build(),"${T_ref}");')
    c.append('        createParam(sim,gpm,null,"U_init",' + f'{w_inlet:.16e}' + ',"m/s",Dimensions.Builder().length(1).time(-1).build(),null);')
    c.append('        if (' + str(create_params).lower() + ') {')
    c.append('        createParam(sim, gpm, null, "Re_in", ' + f"{re_in:.1f}" + ', "", null, null);')
    c.append('        createParam(sim, gpm, null, "P_wet", ' + f"{p_wet_total:.8e}" + ', "m", Dimensions.Builder().length(1).build(), null);')
    c.append('        createParam(sim, gpm, null, "S_in", ' + f"{s_in_total:.8e}" + ', "m^2", Dimensions.Builder().length(2).build(), null);')
    c.append('        createParam(sim, gpm, null, "D_hyd", 0.0, "m", Dimensions.Builder().length(1).build(), "4*${S_in}/${P_wet}");')
    c.append('        createParam(sim, gpm, null, "rhoW_in", 0.0, "kg/m^2-s", Dimensions.Builder().mass(1).length(-2).time(-1).build(), "${Re_in}*${dynvis}/${D_hyd}");')
    c.append('        createParam(sim, gpm, null, "U_b", 0.0, "m/s", Dimensions.Builder().length(1).time(-1).build(), "${rhoW_in}/${rho}");')
    c.append('        createParam(sim, gpm, null, "G_subchannel", 0.0, "kg/s", Dimensions.Builder().mass(1).time(-1).build(), "${rho}*${U_b}*${S_in}");')
    c.append('')
    c.append('        createParam(sim, gpm, null, "y_plus_target", ' + f"{yplus_tgt:.2f}" + ', "", null, null);')
    c.append('        createParam(sim, gpm, null, "h1_wall", ' + f"{h1_m:.3e}" + ', "m", Dimensions.Builder().length(1).build(), null);')
    c.append('')
    c.append('        }')
    transport_flags='' if workflow is None else ','+str(workflow['viscosity_method']=='constant').lower()+','+str(workflow['conductivity_method']=='constant').lower()
    if workflow:
        c.append('        createParam(sim,gpm,null,"MinimumWallDistance",'+str(workflow['minimum_wall_distance'])+',"m",Dimensions.Builder().length(1).build(),null);')
        c.append('        setupPhysics.getReferenceValues().get(MinimumAllowableWallDistance.class).setDefinition("${MinimumWallDistance}");')
        if enable_gravity:
            ref_rho=workflow['reference_density'] or rho
            c.append('        createParam(sim,gpm,null,"ReferenceDensity",'+str(ref_rho)+',"kg/m^3",Dimensions.Builder().mass(1).length(-3).build(),null);')
            c.append('        setupPhysics.getReferenceValues().get(ReferenceDensity.class).setDefinition("${ReferenceDensity}");')
    if workflow and use_iapws:
        c.append('        Material transportMaterial=setupPhysics.getModelManager().getModel(SingleComponentLiquidModel.class).getMaterial();')
        for key,prop,method in (('viscosity_method','DynamicViscosityProperty','IapwsDynamicViscosityMethod'),('conductivity_method','ThermalConductivityProperty','IapwsThermalConductivityMethod')):
            if workflow[key]=='iapws':
                c.append(f'        transportMaterial.getMaterialProperties().getMaterialProperty({prop}.class).setMethod({method}.class);')
    c.append('        physicalValuesConfigured = configurePhysicalValues(sim,setupPhysics,subchannelRegions,' + str(use_iapws).lower() + ',' + str(enable_thermal or use_iapws).lower() + transport_flags + ');')
    c.append('        }')
    if custom_surfaces and (workflow['boundary_pairs'] or workflow['boundary_conditions']):
        c.append('        if (!reuse) {')
        c.append('        if (!physicalValuesConfigured) throw new IllegalStateException("Boundary setup requires configured physics");')
        c.append('        Map<String,Boundary> selectedSurfaces=new HashMap<>();')
        c.append('        for(GapCandidate candidate:gapCandidates) if(!candidate.paired) selectedSurfaces.put(candidate.bnd.getPresentationName(),candidate.bnd);')
        c.append('        for(Boundary wall:allRods) selectedSurfaces.put(wall.getPresentationName(),wall);')
        for cap in catalog['endcaps']:
            role=cap['role'];collection='allInlets' if role=='Inlet' else 'allOutlets';key=json.dumps(cap['id'])
            condition='true' if inter_fuse else f'b.getRegion()==subchannelRegions.get({cap["sources"][0]-1})'
            c.append(f'        for(Boundary b:{collection}) if({condition}) {{ if(selectedSurfaces.put({key},b)!=null)throw new IllegalStateException("Ambiguous end cap; merge end caps before assigning conditions"); }}')
        for i,pair in enumerate(workflow['boundary_pairs'],1):
            a=json.dumps(pair['first']);b=json.dumps(pair['second'])
            c.append(f'        Boundary pairA{i}=selectedSurfaces.get({a}),pairB{i}=selectedSurfaces.get({b});')
            c.append(f'        if(pairA{i}==null||pairB{i}==null)throw new IllegalStateException("Interface surface missing");')
            c.append(f'        BoundaryInterface selectedPair{i}=sim.getInterfaceManager().createBoundaryInterface(pairA{i},pairB{i},"SelectedInterface_{i}"); own(sim,selectedPair{i});')
            if pair['kind']=='fully_developed':
                c.append(f'        selectedPair{i}.setInterfaceType((FullyDevelopedInterface)sim.get(ConditionTypeManager.class).get(FullyDevelopedInterface.class));')
            if pair['kind']!='internal':
                c.append(f'        selectedPair{i}.getTopology().setSelected(InterfaceConfigurationOption.Type.PERIODIC);')
            if pair['kind']=='fully_developed':
                c.append(f'        selectedPair{i}.getConditions().get(FullyDevelopedFlowOption.class).setSelected(FullyDevelopedFlowOption.Type.MASS_FLOW_RATE);')
                c.append(f'        createParam(sim,sim.get(GlobalParameterManager.class),null,"PeriodicMassFlow_{i}",{pair["mass_flow"]:.16e},"kg/s",Dimensions.Builder().mass(1).time(-1).build(),null);')
                c.append(f'        selectedPair{i}.getValues().get(FullyDevelopedMassFlowRate.class).getFullyDevelopedMassFlowRate().setDefinition("${{PeriodicMassFlow_{i}}}");')
            c.append(f'        for(GapCandidate candidate:gapCandidates) if(candidate.bnd==pairA{i}||candidate.bnd==pairB{i})candidate.paired=true;')
            c.append(f'        pairCount++; pairedNames.add("SelectedInterface_{i}");')
        for i,bc in enumerate(workflow['boundary_conditions'],1):
            kind=bc['kind'];key=json.dumps(bc['surface']);value=bc['value']
            c.append(f'        Boundary assignedBoundary{i}=selectedSurfaces.get({key}); if(assignedBoundary{i}==null)throw new IllegalStateException("Boundary missing: "+{key});')
            boundary_type={'wall':'WallBoundary','symmetry':'SymmetryBoundary','mass_flow_inlet':'MassFlowBoundary','pressure_outlet':'PressureBoundary'}[kind]
            c.append(f'        assignedBoundary{i}.setBoundaryType({boundary_type}.class);')
            if kind in ('mass_flow_inlet','pressure_outlet'):
                profile='MassFlowRateProfile' if kind=='mass_flow_inlet' else 'StaticPressureProfile'
                c.append(f'        assignedBoundary{i}.getValues().get({profile}.class).setMethod(ConstantScalarProfileMethod.class);')
                c.append(f'        assignedBoundary{i}.getValues().get({profile}.class).getMethod(ConstantScalarProfileMethod.class).getQuantity().setDefinition("{value:.16e}");')
                if kind=='mass_flow_inlet' and (enable_thermal or use_iapws):
                    c.append(f'        assignedBoundary{i}.getValues().get(StaticTemperatureProfile.class).getMethod(ConstantScalarProfileMethod.class).getQuantity().setDefinition("${{T_init}}");')
        c.append('        }')
    if custom_surfaces and workflow['heat_enabled']:
        c.append('        if (!physicalValuesConfigured && !reuse) throw new IllegalStateException("Heat setup requires configured physics");')
        for i,row in enumerate((r for r in catalog['rods'] if r['kind']=='fuel'),1):
            key=row['id'];value=workflow['heat_values'][key]
            c.append(f'        configureHeatInput(sim,"q{i}",{value:.16e});')
            c.append(f'        UserFieldFunction heatQ{i}=getOrCreateFF(sim,"HeatFlux_q{i}","${{q{i}}}");heatQ{i}.setDimensions(Dimensions.Builder().mass(1).time(-3).build());')
            c.append(f'        int heated{i}=0; for(Boundary boundary:allRods) if(tagged(boundary,"meshBuilder.HeatGroup.{key}")) {{')
            c.append(f'            boundary.getConditions().get(WallThermalOption.class).setSelected(WallThermalOption.Type.HEAT_FLUX);HeatFluxProfile profile=boundary.getValues().get(HeatFluxProfile.class);profile.setMethod(FunctionScalarProfileMethod.class);profile.getMethod(FunctionScalarProfileMethod.class).setFieldFunction(heatQ{i});heated{i}++; }}')
            c.append(f'        if(heated{i}==0)throw new IllegalStateException("Missing heat group {key}");')
    if is_unsteady:
        c.append('        try {')
        c.append('            GlobalParameterManager timeManager=sim.get(GlobalParameterManager.class);')
        c.append('            ScalarGlobalParameter timeParameter=findOwned(sim,timeManager,"TimeStep",ScalarGlobalParameter.class);')
        c.append('            if (!reuse || timeParameter==null) {')
        c.append('                createParam(sim,timeManager,null,"TimeStep",'+f'{float(time_step):.16e}'+',"s",Dimensions.Builder().time(1).build(),null);')
        c.append('                if (findOwned(sim,timeManager,"TimeStep",ScalarGlobalParameter.class)==null) throw new IllegalStateException("TimeStep parameter unavailable");')
        c.append('                sim.getSolverManager().getSolver(ImplicitUnsteadySolver.class).getTimeStep().setDefinition("${TimeStep}");')
        c.append('                if (reuse) sim.println("  • Added TimeStep parameter and solver binding to existing simulation; no reinitialization.");')
        c.append('            }')
        c.append('        } catch (Exception e) { warn(sim,"  [!] TimeStep binding: "+e.getMessage()); }')

    if workflow and is_unsteady:
        planned_end=workflow['warmup_duration'] if workflow['tdc_enabled'] else workflow['warmup_duration']+workflow['block_duration']*workflow['blocks_per_run']
        c.append('        if (!reuse) try { configureUnsteadyWorkflow(sim,'+str(workflow['inner_iterations'])+','+str(planned_end)+'); } catch (Exception e) { throw new IllegalStateException("Unsteady settings incomplete; verify STAR 2602 solver options before running: "+e.getMessage(),e); }')
    if create_field_functions:
        c.append('        supportFunctions(sim,' + f'{lz_m:.16e}' + ', Arrays.asList(' + ','.join(json.dumps(v) for v in field_choices) + '));')
    if workflow and workflow['velocity_seed']:
        if not create_params:c.append('        createParam(sim,sim.get(GlobalParameterManager.class),null,"U_b",'+str(float(yplus_data.get('velocity',5.62)))+',"m/s",Dimensions.Builder().length(1).time(-1).build(),null);')
        c.append('        createParam(sim,sim.get(GlobalParameterManager.class),null,"pi",Math.PI,"",null,null);')
        c.append('        createParam(sim,sim.get(GlobalParameterManager.class),null,"Apert",0.,"m/s",Dimensions.Builder().length(1).time(-1).build(),"0.01*${U_b}");')
        c.append('        exportHeight(sim,'+str(lz_m)+');')
        c.append('        getOrCreateFF(sim,"MB_ZFraction","$${Position}[2]/${ExportHeight}").setDimensions(Dimensions.Builder().build());')
        c.append('        UserFieldFunction theta=getOrCreateFF(sim,"thetaZ","2*${pi}*$${Position}[2]/${ExportHeight}");')
        c.append('        theta.setDimensions(Dimensions.Builder().build());')
        c.append('        getOrCreateFF(sim,"seedX","sin(${thetaZ})+0.5*sin(3*${thetaZ}+0.7)+0.25*sin(7*${thetaZ}+1.9)");')
        c.append('        getOrCreateFF(sim,"seedY","sin(2*${thetaZ}+0.4)+0.5*sin(5*${thetaZ}+1.3)+0.25*sin(9*${thetaZ}+2.2)");')
        c.append('        UserFieldFunction seed=getOrCreateFF(sim,"VelocitySeed","0");')
        c.append('        seed.setDimensions(Dimensions.Builder().length(1).time(-1).build());')
        c.append('        try { workflowEnum(workflowCall(seed,"getTypeOption"),"VECTOR"); } catch (Exception e) { throw new IllegalStateException("VelocitySeed vector type unavailable: "+e.getMessage(),e); }')
        c.append('        seed.setDefinition("[${Apert}*${seedX},${Apert}*${seedY},${U_b}]");')
        if workflow['initial_velocity']=='seed':
            c.append('        if (!reuse) {')
            c.append('            if (!physicalValuesConfigured) throw new IllegalStateException("VelocitySeed requires configured initial fields");')
            c.append('            VelocityProfile initialVelocity=setupPhysics.getInitialConditions().get(VelocityProfile.class);')
            c.append('            initialVelocity.setMethod(FunctionVectorProfileMethod.class);')
            c.append('            initialVelocity.getMethod(FunctionVectorProfileMethod.class).setFieldFunction(seed);')
            c.append('        }')
    c.append('        initializeFirstSolution(sim,reuse,' + str(initialize_solution).lower() + ',physicalValuesConfigured);')
    # 9. Создание Derived Parts (PlaneSection и LineSection) по точному рекордеру 21.02.007:
    c.append('        // 9. Создание сечений и зондов (Derived Parts) по рекордеру STAR-CCM+ 21.02.007:')
    c.append('        sim.println(">>> Создание производных деталей (Derived Parts)...");')
    c.append('        int planesCreated = 0;')
    c.append('        int probesCreated = 0;')
    c.append('        int[] reportCounts = new int[] {0, 0};')
    if create_bad_cells or (create_summary and workflow is None) or (workflow and workflow["quality_enabled"]):
        c.append('        try { countReport(sim,"Quality_TotalCellCount",subchannelRegions,reportCounts); }')
        c.append('        catch (Exception e) { warn(sim,"  [!] Total cell count: " + e.getMessage()); }')
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
            c.append(f'            UserFieldFunction mask{number} = getOrCreateFF(sim, "MB_SubchannelMask_{number}", "{expression}");')
            c.append(f'            ThresholdPart domain{number} = threshold(sim, subchannelRegions, mask{number}, "Subchannel_{number}_Domain");')
            c.append(f'            sourceParts.add(Collections.singletonList(domain{number}));')
    else:
        c.append('            for (Region region : subchannelRegions) sourceParts.add(Collections.singletonList(region));')
    for pos in plane_positions(n_planes, key_planes):
        label = plane_label("Section_Global", pos, lz_m)
        c.append(f'            createPlaneSection(sim, labCoord, uLen, subchannelRegions, "{label}", lz * {pos:.16e}); planesCreated++;')
    for number in range(1, subchannels_count + 1):
        positions = plane_positions(n_sub_planes, not workflow or workflow['plane_scheme']=='legacy') if sub_planes and number in selected_subchannels else []
        if (create_reports or analysis_choices) and (not workflow or number in report_selected):
            positions = sorted(set(positions + [0., 1.]))
        for pos in positions:
            # A single source has the same domain as the global plane: reuse it.
            reuse = subchannels_count == 1 and pos in plane_positions(n_planes, key_planes)
            name = plane_label("Section_Global" if reuse else f"Subchannel_{number}_Section", pos, lz_m)
            if not reuse:
                c.append(f'            createPlaneSection(sim, labCoord, uLen, sourceParts.get({number-1}), "{name}", lz * {pos:.16e}); planesCreated++;')
            if create_reports and (not workflow or number in report_selected) and pos in (0., 1.) and not (number in report_selected and any(k in analysis_choices for k in ('hydraulics','wall'))):
                side = 'In' if pos == 0 else 'Out'
                c.append(f'            createMassFlowReport(sim, "MassFlow_{side}_Sub{number}", Collections.singletonList((PlaneSection) sim.getPartManager().getObject("{name}")), reportCounts);')
        if analysis_choices and number in report_selected:
            in_name = plane_label("Section_Global" if subchannels_count == 1 and 0. in plane_positions(n_planes,key_planes) else f"Subchannel_{number}_Section", 0., lz_m)
            out_name = plane_label("Section_Global" if subchannels_count == 1 and 1. in plane_positions(n_planes,key_planes) else f"Subchannel_{number}_Section", 1., lz_m)
            # Wall Threshold uses the original triangle, including shared rods after Fuse.
            if domains:
                expression = domain_expression(domains[number-1]["triangle"])
                c.append(f'            UserFieldFunction wallMask{number}=getOrCreateFF(sim,"MB_WallMask_Sub{number}","{expression}");')
                walls = f'Collections.singletonList(threshold(sim,allRods,wallMask{number},"Subchannel_{number}_RodWalls"))'
            else:
                walls = f'rodBoundaries(subchannelRegions.get({number-1}))'
            categories = ','.join(json.dumps(v) for v in analysis_choices)
            c.append(f'            createSubchannelAnalysis(sim,{number},sourceParts.get({number-1}),{walls},(PlaneSection)sim.getPartManager().getObject("{in_name}"),(PlaneSection)sim.getPartManager().getObject("{out_name}"),lz,Arrays.asList({categories}),{str(enable_thermal or use_iapws).lower()},reportCounts);')
    if gap_sections:
        for gap in shared_gap_sections(domains):
            a, b = gap['a'], gap['b']
            x, y = gap['origin']; nx, ny = gap['normal']
            c.append(f'            createOrientedPlaneSection(sim, labCoord, uLen, sourceParts.get({a-1}), "Gap_Sub{a}_Sub{b}", new double[] {{{x:.16e}, {y:.16e}, lz / 2}}, new double[] {{{nx:.16e}, {ny:.16e}, 0}}); planesCreated++;')
            if create_reports:
                c.append(f'            createMassFlowReport(sim, "MassFlow_Gap_Sub{a}_Sub{b}", Collections.singletonList((PlaneSection) sim.getPartManager().getObject("Gap_Sub{a}_Sub{b}")), reportCounts);')
            if workflow and (create_reports or analysis_choices):
                prefix=f'Gap_Sub{a}_Sub{b}'
                parts=f'Collections.singletonList((PlaneSection)sim.getPartManager().getObject("{prefix}"))'
                definition=f'$$Velocity[0]*({nx:.16e})+$$Velocity[1]*({ny:.16e})'
                c.append(f'            UserFieldFunction gapVelocity{a}_{b}=getOrCreateFF(sim,"{prefix}_NormalVelocity",'+json.dumps(definition)+');')
                c.append(f'            gapVelocity{a}_{b}.setDimensions(Dimensions.Builder().length(1).time(-1).build());')
                c.append(f'            scalarReport(sim,"area","{prefix}_NormalVelocityMean",{parts},gapVelocity{a}_{b},reportCounts);')
                c.append(f'            scalarReport(sim,"surface","{prefix}_Area",{parts},getOrCreateFF(sim,"MB_One","1.0"),reportCounts);')
                if enable_thermal or use_iapws:
                    c.append(f'            scalarReport(sim,"area","{prefix}_TemperatureMean",{parts},analysisField(sim,"Temperature"),reportCounts);')
                    c.append(f'            UserFieldFunction gapEnergy{a}_{b}=getOrCreateFF(sim,"{prefix}_EnthalpyFlux","${{Density}} * ${{TotalEnthalpy}} * ${{{prefix}_NormalVelocity}}");')
                    c.append(f'            gapEnergy{a}_{b}.setDimensions(Dimensions.Builder().mass(1).time(-3).build());')
                    c.append(f'            scalarReport(sim,"surface","{prefix}_EnthalpyFlow",{parts},gapEnergy{a}_{b},reportCounts);')
    if axis_probes:
        for idx, (xc, yc) in enumerate(sub_centers):
            if idx + 1 in selected_subchannels:
                c.append(f'            createAxisLine(sim, labCoord, uLen, sourceParts.get({idx}), "Probe_Axis_Subchannel_{idx+1}", {xc:.16e}, {yc:.16e}, lz); probesCreated++;')
    c.append('            sim.println(String.format("  • Производные плоскости (%d шт) и зонды (%d шт) успешно построены!", planesCreated, probesCreated));')
    c.append('        } catch (Exception e) { sim.println("  [!] Ошибка при создании Derived Parts: " + e.getMessage()); }')

    if create_reports:
        if turbulence_model == "hybrid_srh":
            c.append('        warn(sim,"  [!] HYBRID: flux balances exclude dM/dt and dE/dt; they are not full transient conservation residuals.");')
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

    if "balances" in field_choices and create_reports:
        c.append('        try { UserFieldFunction ff=getOrCreateFF(sim,"MB_MassBalanceSigned","${MassFlow_Inlet_TotalReport} + ${MassFlow_Outlet_TotalReport}"); ff.setDimensions(Dimensions.Builder().mass(1).time(-1).build()); }')
        c.append('        catch (Exception e) { warn(sim,"  [!] Mass balance field: " + e.getMessage()); }')
        if enable_thermal or use_iapws:
            c.append('        try { UserFieldFunction ff=getOrCreateFF(sim,"MB_EnergyBalanceSigned","${Energy_Flow_Inlet_TotalReport} + ${Energy_Flow_Outlet_TotalReport} - ${Heat_Flux_Walls_TotalReport}"); ff.setDimensions(Dimensions.Builder().mass(1).length(2).time(-3).build()); }')
            c.append('        catch (Exception e) { warn(sim,"  [!] Energy balance field: " + e.getMessage()); }')
    for key in mean_choices:
        if key in ('temperature','wall_heat_flux','enthalpy') and not (enable_thermal or use_iapws):
            continue
        component=next(((base,axis,index) for base in ('velocity','wall_shear') for index,axis in enumerate(('i','j','k')) if key==base+'_'+axis),None)
        if workflow and key in ('density','viscosity') and not use_iapws:continue
        if component:
            base,axis,index=component;source='Velocity' if base=='velocity' else 'WallShearStress';native=source+'_'+axis
            dims='Dimensions.Builder().length(1).time(-1).build()' if base=='velocity' else 'Dimensions.Builder().mass(1).length(-1).time(-2).build()'
            c.append(f'        getOrCreateFF(sim,"{native}","$${{{source}}}[{index}]").setDimensions({dims});')
            parts='allRods' if base=='wall_shear' else 'subchannelRegions'
        else:
            native = dict(enthalpy='TotalEnthalpy',velocity='Velocity',pressure='Pressure',temperature='Temperature',density='Density',viscosity='DynamicViscosity',wall_shear='WallShearStress',wall_heat_flux='BoundaryHeatFlux')[key]
            parts = 'allRods' if key in ('wall_shear','wall_heat_flux') else 'subchannelRegions'
        c.append(f'        createTimeMean(sim,{parts},"{native}",{mean_start});')
    c.append('        int[] qualityCounts = new int[] {0, 0};')
    c.append('        List<UserFieldFunction> badMasks = new ArrayList<>();')
    if create_scene:
        middle_name = plane_label("Section_Global" if .5 in plane_positions(n_planes, key_planes) else "Quality_Section", .5, lz_m)
        c.append('        List<NamedObject> qualitySurfaces = new ArrayList<>();')
        c.append('        try {')
        if .5 not in plane_positions(n_planes, key_planes):
            c.append(f'            createPlaneSection(sim, sim.getCoordinateSystemManager().getLabCoordinateSystem(), sim.getUnitsManager().getPreferredUnits(Dimensions.Builder().length(1).build()), subchannelRegions, "{middle_name}", {lz_m/2:.16e}); planesCreated++;')
        c.append(f'            qualitySurfaces.add((PlaneSection) sim.getPartManager().getObject("{middle_name}"));')
        c.append('        } catch (Exception e) { sim.println("  [!] Сечение качества: " + e.getMessage()); }')
    if create_scene or create_histograms or create_bad_cells or "quality" in field_choices:
        metrics=QUALITY_METRICS if workflow is None else tuple((key, label, ("gt_" if key=="SkewnessAngle" else "le_")+format(workflow["quality_thresholds"][key],"g"), ("> " if key=="SkewnessAngle" else "<= ")+format(workflow["quality_thresholds"][key],"g")) for key,label,_,_ in QUALITY_METRICS)
        for metric, label, suffix, criterion in metrics:
            c.append('        try {')
            c.append(f'            FieldFunction metric = qualityField(sim, "{metric}", "{label}");')
            if "quality" in field_choices:
                c.append(f'            UserFieldFunction alias = getOrCreateFF(sim,"MB_{metric}","${{" + metric.getFunctionName() + "}}"); alias.setDimensions(metric.getDimensions());')
            if create_scene or create_histograms or create_bad_cells:
                c.append(f'            createQualityExtrema(sim, subchannelRegions, metric, "{metric}", reportCounts);')
            if create_bad_cells:
                c.append(f'            UserFieldFunction bad = createBadCells(sim, subchannelRegions, metric, "{metric}", "{criterion.replace(" deg", "")}", reportCounts); if (bad != null) badMasks.add(bad);')
            if create_histograms:
                c.append(f'            createQualityHistogram(sim, subchannelRegions, metric, "Quality_Histogram_{metric}__bad_{suffix}", "{criterion}", {quality_bins}); qualityCounts[0]++;')
            c.append('        } catch (Exception e) { sim.println("  [!] Качество ' + metric + ': " + e.getMessage()); }')
            if create_scene:
                c.append('        try {')
                c.append(f'            createQualityScene(sim, qualitySurfaces, qualityField(sim, "{metric}", "{label}"), "Quality_{metric}"); qualityCounts[1]++;')
                c.append('        } catch (Exception e) { sim.println("  [!] Сцена ' + metric + ': " + e.getMessage()); }')
    if create_bad_cells:
        c.append('        badUnion(sim,subchannelRegions,badMasks,reportCounts);')
    if create_bad_cells or (workflow and workflow['quality_enabled']):
        c.append('        try { createBadCells(sim,subchannelRegions,qualityField(sim,"Volume","Volume"),"NonPositiveVolume","<= 0",reportCounts); }')
        c.append('        catch (Exception e) { warn(sim,"  [!] Nonpositive volume check: "+e.getMessage()); }')
    c.append('        sim.println("Контроль качества: " + qualityCounts[0] + " гистограмм и " + qualityCounts[1] + " скалярных сцен. Откройте их и проверьте min/max; это не автоматическое заключение о пригодности сетки.");')

    c.append('')
    if group_objects:
        for manager, category in [('sim.getPartManager()','DerivedParts'),('sim.getReportManager()','Reports'),
                ('sim.getMonitorManager()','Monitors'),('sim.getPlotManager()','Plots'),
                ('sim.getSceneManager()','Scenes'),('sim.getFieldFunctionManager()','FieldFunctions'),('sim.get(GlobalParameterManager.class)','Parameters')]:
            c.append(f'        try {{ groupManaged(sim,{manager},"{category}"); }} catch (Exception e) {{ warn(sim,"  [!] Grouping {category}: " + e.getMessage()); }}')
    if create_summary:
        c.append('        writeSummary(sim,subchannelRegions,exportFingerprint,expectedCells,' + str(evaluate_solution).lower() + ');')
    c.append('        // 11. Итоговый аудит созданных объектов:')
    c.append('        sim.println("\\n===================================================================================================");')
    c.append('        sim.println("                       ИТОГОВЫЙ АУДИТ СОЗДАННЫХ ОБЪЕКТОВ СЦЕНЫ STAR-CCM+");')
    c.append('        sim.println("===================================================================================================");')
    c.append('        sim.println(" [1] ИНТЕРФЕЙСЫ (Interfaces): " + pairCount + " пар успешно создано.");')
    c.append('        for (String pNm : pairedNames) sim.println("     • " + pNm + " --> [ СОЗДАН ]");')
    c.append('        sim.println(" [2] ПРОИЗВОДНЫЕ ДЕТАЛИ (Derived Parts): " + planesCreated + " сечений и " + probesCreated + " зондов создано.");')
    c.append('        sim.println(" [3] ПАРАМЕТРЫ (Tools > Parameters): параметры назначаются только при первом импорте; проверьте сообщения [!].");')
    c.append('        sim.println(" [4] ОТЧЕТЫ И МОНИТОРЫ: настроено/переиспользовано " + reportCounts[0] + " отчетов и " + reportCounts[1] + " мониторов; проверьте сообщения [!].");')
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
""".strip('\n').splitlines())
    c.append('    private void createAxisLine(Simulation sim, LabCoordinateSystem labCoord, Units uLen, List<? extends NamedObject> parts, String name, double x, double y, double lz) {')
    c.append('        try {')
    c.append('            LineSection ls = findOwned(sim,sim.getPartManager(),name,LineSection.class);')
    c.append('            if (ls == null) { ls = sim.getPartManager().createLineSection(')
    c.append('                new ArrayList<>(Collections.<NamedObject>emptyList()),')
    c.append('                new DoubleVector(new double[] {0.0, 0.0, 0.0}),')
    c.append('                new DoubleVector(new double[] {0.0, 0.0, 1.0}), 0, true, null);')
    c.append('            ls.setPresentationName(name); own(sim,ls); }')
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
        if (meshOnlyReport(report.getPresentationName())) return;
        try {
            boolean found=false;
            for (ReportMonitor monitor : sim.getMonitorManager().getObjectsOf(ReportMonitor.class))
                if (monitor.getReport()==report) { found=true; break; }
            if (!found) own(sim,report.createMonitor());
            counts[1]++;
        }
        catch (Exception e) { sim.println("  [!] Монитор " + report.getPresentationName() + ": " + e.getMessage()); }
    }
    private void createMassFlowReport(Simulation sim, String name, List<? extends NamedObject> parts, int[] counts) {
        try {
            MassFlowReport report = ownedReport(sim,name,MassFlowReport.class);
            report.setPresentationName(name); report.getParts().setObjects(parts);
            registerReport(sim, report, counts);
        } catch (Exception e) { sim.println("  [!] Отчет " + name + ": " + e.getMessage()); }
    }
    private void createExpressionReport(Simulation sim, String name, String expression, int[] counts) {
        try {
            ExpressionReport report = ownedReport(sim,name,ExpressionReport.class);
            report.setPresentationName(name); report.setDefinition(expression);
            registerReport(sim, report, counts);
        } catch (Exception e) { sim.println("  [!] Отчет " + name + ": " + e.getMessage()); }
    }
    private void createHeatReport(Simulation sim, String name, List<? extends NamedObject> parts, int[] counts) {
        try {
            FieldFunction flux = sim.getFieldFunctionManager().getFunction("BoundaryHeatFlux");
            if (flux == null) throw new IllegalStateException("Недоступно поле BoundaryHeatFlux");
            SurfaceIntegralReport report = ownedReport(sim,name,SurfaceIntegralReport.class);
            report.setPresentationName(name); report.setFieldFunction(flux); report.getParts().setObjects(parts);
            registerReport(sim, report, counts);
        } catch (Exception e) { sim.println("  [!] Отчет " + name + ": " + e.getMessage()); }
    }
    private void createEnthalpyReport(Simulation sim, String name, List<? extends NamedObject> parts, int[] counts) {
        try {
            FieldFunction enthalpy = sim.getFieldFunctionManager().getFunction("TotalEnthalpy");
            if (enthalpy == null) throw new IllegalStateException("Недоступно поле TotalEnthalpy");
            MassFlowAverageReport report = ownedReport(sim,name,MassFlowAverageReport.class);
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
            MinReport minimum = ownedReport(sim,"Quality_Min_" + key,MinReport.class);
            minimum.setPresentationName("Quality_Min_" + key);
            minimum.setFieldFunction(metric); minimum.getParts().setObjects(regions);
            registerReport(sim, minimum, counts);
        } catch (Exception e) { sim.println("  [!] Min " + key + ": " + e.getMessage()); }
        try {
            MaxReport maximum = ownedReport(sim,"Quality_Max_" + key,MaxReport.class);
            maximum.setPresentationName("Quality_Max_" + key);
            maximum.setFieldFunction(metric); maximum.getParts().setObjects(regions);
            registerReport(sim, maximum, counts);
        } catch (Exception e) { sim.println("  [!] Max " + key + ": " + e.getMessage()); }
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
        Cartesian2DPlot plot = findOwned(sim,sim.getPlotManager(),name,Cartesian2DPlot.class);
        if (plot == null) {
            plot = sim.getPlotManager().createCartesian2DPlot(name,List.of(XyPlotTypeEnum.HISTOGRAM),series);
            plot.setPresentationName(name); own(sim,plot);
        }
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
    c.extend(r"""
    private UserFieldFunction getOrCreateFF(Simulation sim, String name, String definition) {
        UserFieldFunction ff=findOwned(sim,sim.getFieldFunctionManager(),name,UserFieldFunction.class);
        if (ff==null) {
            ff=sim.getFieldFunctionManager().createFieldFunction(); ff.setPresentationName(name); own(sim,ff);
        }
        ff.setPresentationName(displayName(name));
        ff.setFunctionName(name); ff.setDefinition(definition); return ff;
    }
""".strip('\n').splitlines())
    c.append('    private void createParam(Simulation sim, GlobalParameterManager gpm, ClientServerObjectGroup grp, String name, double val, String unitStr, Dimensions dims, String defStr) {')
    c.append('        try {')
    c.append('            ScalarGlobalParameter p = findOwned(sim,gpm,name,ScalarGlobalParameter.class);')
    c.append('            if (p == null) { p = (ScalarGlobalParameter) gpm.createGlobalParameter(ScalarGlobalParameter.class, "Scalar"); p.setPresentationName(name); own(sim,p); }')
    c.append('            if (dims != null) p.setDimensions(dims);')
    c.append('            if (defStr != null && !defStr.isEmpty()) { p.getQuantity().setDefinition(defStr); }')
    c.append('            else {')
    c.append('                if (unitStr != null && !unitStr.isEmpty()) { Units u = sim.getUnitsManager().getObject(unitStr); p.getQuantity().setValueAndUnits(val, u); }')
    c.append('                else { p.getQuantity().setValue(val); }')
    c.append('            }')
    c.append('        } catch (Exception e) { warn(sim,"  [!] Parameter " + name + ": " + e.getMessage()); }')
    c.append('    }')
    from starccm_unified_support import UNIFIED_SUPPORT, HEAT_SUPPORT, flat_groups
    c.extend((flat_groups(GROUP_SUPPORT) if workflow else GROUP_SUPPORT).strip('\n').splitlines())
    if workflow:c.extend(UNIFIED_SUPPORT.strip('\n').splitlines())
    if custom_surfaces and workflow['heat_enabled']:c.extend(HEAT_SUPPORT.strip('\n').splitlines())
    c.extend(AUDIT_SUPPORT.strip('\n').splitlines())
    c.extend(PHYSICS_SUPPORT.strip('\n').splitlines())
    c.extend(ANALYSIS_SUPPORT.strip('\n').splitlines())
    c.extend(JAVA_SUPPORT.strip('\n').splitlines())
    c.append('}')
    code = "\n".join(c) + "\n"
    if workflow:
        code=code.replace('"TimeStep"','"timeStep"').replace('${TimeStep}','${timeStep}')
        lookup='            ScalarGlobalParameter timeParameter=findOwned(sim,timeManager,"timeStep",ScalarGlobalParameter.class);'
        code=code.replace(lookup,lookup+'\n'
            '            if (reuse && timeParameter==null) {\n'
            '                ScalarGlobalParameter legacyStep=findOwned(sim,timeManager,"TimeStep",ScalarGlobalParameter.class);\n'
            '                if (legacyStep!=null) { createParam(sim,timeManager,null,"timeStep",0.,"s",Dimensions.Builder().time(1).build(),"${TimeStep}"); timeParameter=findOwned(sim,timeManager,"timeStep",ScalarGlobalParameter.class); }\n'
            '            }')
    return re.sub(r'sim\.println\((?="(?:  |>>> )?\[!\])', 'warn(sim, ', code)
