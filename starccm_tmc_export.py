"""Reference-case TMC export contract and staged multi-file publication (no Qt)."""
from copy import deepcopy
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import numpy as np

TMC_DEFAULTS=dict(rho=747.3390805476422,mu=9.271750031043231e-5,cp=5225.098000687438,
    conductivity=.5753275671409854,temperature_ref=563.15,heat_flux_1=10000.,heat_flux_2=300000.,
    mass_flow=.1325444593154614,time_step=2.5e-5,hydro_duration=.45,thermal_duration=.45,
    block_duration=.45,blocks_to_run=1,max_steps=1000000,min_delta_t=.01,
    create_field_means=False,gap_conduction=False)
JAVA_KEYS=dict(rho='Rho',mu='Mu',cp='Cp',conductivity='Lambda',temperature_ref='TemperatureRef',
    heat_flux_1='HeatFlux_Sub1',heat_flux_2='HeatFlux_Sub2',mass_flow='MassFlow',time_step='TimeStep',
    hydro_duration='HydroDuration',thermal_duration='ThermalDuration',block_duration='BlockDuration',
    blocks_to_run='BlocksToRun',max_steps='MaxStepsPerAction',min_delta_t='MinDeltaT',
    create_field_means='CreateFieldMeans',gap_conduction='EnableOptionalGapConduction')
ROOT=Path(__file__).resolve().parent
FIXED_FILES=('setup_starccm_subchannels.java','TMC_Hybrid.java','TMC_export.json','TMC_START.txt','TMC_analyse_series.py')


def validate_tmc_settings(settings):
    if not isinstance(settings,dict) or set(settings)-set(TMC_DEFAULTS):raise ValueError('Неизвестные настройки TMC')
    result=deepcopy(TMC_DEFAULTS);result.update(settings)
    for key,default in TMC_DEFAULTS.items():
        value=result[key]
        if type(default) is bool:
            if type(value) is not bool:raise ValueError(f'{key}: требуется флажок')
        elif type(default) is int:
            hi=10000 if key=='blocks_to_run' else 100000000
            if type(value) is not int or not 1<=value<=hi:raise ValueError(f'{key}: требуется целое 1…{hi}')
        else:
            if type(value) not in (float,int) or not math.isfinite(value) or value<0 or (value==0 and key!='heat_flux_1'):
                raise ValueError(f'{key}: требуется конечное положительное число')
            result[key]=float(value)
    if result['heat_flux_2']<=result['heat_flux_1']:raise ValueError('В эталоне Sub2 должен нагреваться сильнее Sub1')
    return result


def canonical_tmc_options(settings):
    return dict(import_mesh=True,inner_fuse=True,inter_fuse=True,region_mode='monolithic',
        inlet_outlet_mode='single',rename_boundaries=True,rod_wall_mode='sectors_60',turbulence_model='hybrid_srh',
        use_iapws=False,enable_thermal=True,enable_gravity=False,create_parameters=True,create_physics=True,
        initialize_solution=False,evaluate_solution_reports=False,create_mass_reports=False,
        create_quality_scene=False,create_quality_histograms=False,create_bad_cells=False,
        create_field_functions=False,field_functions=[],subchannel_reports=[],time_mean_fields=[],
        n_planes=0,n_sub_planes=11,key_planes=False,sub_planes=True,axis_probes=False,
        selected_subchannels=[1,2],gap_sections=True,group_objects=True,create_summary=True,
        time_step=settings['time_step'])


def reference_geometry(result,model):
    from mesh_interface_diagnostics import require_star_conformity
    if result is None or model is None or not getattr(result,'complete',False):raise ValueError('TMC требует актуальную полную сетку и геометрию пучка')
    require_star_conformity(result)
    if len(result.blocks)!=12 or result.subchannels_count!=2 or abs(result.params.z_len-.3)>1e-12:
        raise ValueError('Эталон TMC: два подканала (12 блоков), длина ровно 300 мм')
    expected={18:{(-1,1),(0,0),(0,1)},22:{(-1,1),(-1,2),(0,1)}}
    ids=[row[0] for row in getattr(result,'instances_map',[])]
    if ids!=[18]*6+[22]*6 or set(model.selected_subchannels)!={18,22}:
        raise ValueError('Эталон TMC требует исходные подканалы S18 и S22 в эталонном положении')
    if abs(model.pitch-11.64)>1e-9:raise ValueError('Шаг пучка для этого макроса должен быть 11,64 мм')
    for sid,coords in expected.items():
        rods=[model.rods[i] for i in model.subchannels[sid].rod_ids]
        if {(r.q,r.r) for r in rods}!=coords or any(abs(r.diameter-9.1)>1e-9 for r in rods):
            raise ValueError('Положение/диаметры стержней не соответствуют эталону TMC')
    area={18:0.,22:0.};wet=0.
    for i,(x,y) in enumerate(result.blocks):
        if x.shape!=y.shape or min(x.shape)<2 or not np.isfinite(x).all() or not np.isfinite(y).all():raise ValueError('Неверные координаты сетки')
        # Signed polygon area, preserving detection of reversed cells.
        corners=[(x[:-1,:-1],y[:-1,:-1]),(x[1:,:-1],y[1:,:-1]),(x[1:,1:],y[1:,1:]),(x[:-1,1:],y[:-1,1:])]
        a=sum(corners[k][0]*corners[(k+1)%4][1]-corners[k][1]*corners[(k+1)%4][0] for k in range(4))/2
        if np.any(a<=0):raise ValueError('Сетка содержит вырожденные или перевёрнутые ячейки')
        area[ids[i]]+=float(a.sum())
        j=0 if result.wall_starts[i] else -1
        wet+=float(np.hypot(np.diff(x[:,j]),np.diff(y[:,j])).sum())
    for value in area.values():
        if abs(value*.3-7.8450223e-6)>1e-4*7.8450223e-6:
            raise ValueError('Объём сетки отличается от допуска эталонного TMC-макроса; проверьте геометрию и её разрешение по дуге')
    return dict(area=sum(area.values()),hydraulic_diameter=4*sum(area.values())/wet)


def render_tmc_macro(settings):
    settings=validate_tmc_settings(settings)
    source=(ROOT/'tmc'/'TMC_Hybrid.java').read_text(encoding='utf-8')
    for key,java in JAVA_KEYS.items():
        value=settings[key];literal=str(int(value)) if type(value) in (bool,int) else format(value,'.17g')
        pattern=r'(param\("'+re.escape(java)+r'",)[^,]+(,)'
        source,count=re.subn(pattern,lambda match:match[1]+literal+match[2],source)
        if count!=1:raise ValueError(f'Шаблон TMC не содержит единственный параметр {java}')
    return source


def bundle_names(xyz):
    if not isinstance(xyz,str) or not xyz.strip() or Path(xyz).name!=xyz or '/' in xyz or '\\' in xyz or not xyz.lower().endswith('.xyz') or any(ord(c)<32 for c in xyz):
        raise ValueError('Имя сетки должно быть простым именем файла .xyz без пути')
    names=(xyz,*FIXED_FILES)
    if len({name.casefold() for name in names})!=len(names):raise ValueError('Имена файлов комплекта совпадают')
    return names


def _publish(staged):
    backups={};published=[];preserved=set()
    try:
        for target in staged:
            if target.exists():
                fd,path=tempfile.mkstemp(prefix='.tmc_backup_',dir=target.parent);os.close(fd)
                backups[target]=Path(path);shutil.copy2(target,path)
        for target,temp in staged.items():os.replace(temp,target);published.append(target)
    except OSError as failure:
        errors=[]
        for target in reversed(published):
            try:
                if target in backups:os.replace(backups[target],target)
                else:target.unlink(missing_ok=True)
            except OSError as exc:
                if target in backups:preserved.add(backups[target])
                errors.append(f"{exc}; резервная копия: {backups.get(target)}")
        if errors:raise OSError(f'Ошибка публикации; часть восстановления не удалась: {errors}; исходная ошибка: {failure}') from failure
        raise
    finally:
        for backup in backups.values():
            if backup not in preserved:backup.unlink(missing_ok=True)


def write_tmc_bundle(directory,xyz,result,model,settings,progress,unified_options=None):
    from starccm_macro_generator import generate_starccm_java_macro
    from mesh_subchannel import export_subchannel_plot3d
    settings=validate_tmc_settings(settings);geometry=reference_geometry(result,model)
    if unified_options is not None:
        from starccm_export_profile import validate_options
        unified_options=validate_options(unified_options,result.subchannels_count)
        if not unified_options['workflow']['tdc_enabled'] or not unified_options['workflow']['tdc_equivalence']:
            raise ValueError('Комплект TDC требует включённую методику и подтверждение эквивалентности зазоров')
        if unified_options['tmc_settings']!=settings:raise ValueError('Настройки контроллера TDC не согласованы с общим окном')
    directory=Path(directory);names=bundle_names(xyz)
    if unified_options is not None:names=tuple(name.replace("TMC", "TDC") for name in names)
    if not directory.is_dir():raise ValueError('Папка экспорта не существует')
    targets=[directory/name for name in names]
    if any(p.is_symlink() or (p.exists() and not p.is_file()) for p in targets):raise ValueError('Целевой путь не является обычным файлом')
    options=canonical_tmc_options(settings)
    if unified_options is not None:options.update(deepcopy(unified_options))
    velocity=settings['mass_flow']/(settings['rho']*geometry['area'])
    fluid=dict(density=settings['rho'],dyn_vis=settings['mu'],cp=settings['cp'],**{'lambda':settings['conductivity']},
        kin_vis=settings['mu']/settings['rho'],prandtl=settings['mu']*settings['cp']/settings['conductivity'],
        t_ref_c=settings['temperature_ref']-273.15,p_ref_mpa=16.2)
    yp=dict(velocity=velocity,reynolds=settings['rho']*velocity*geometry['hydraulic_diameter']/settings['mu'],delta_y1_m=result.params.h1,y_plus=1.)
    progress(2,'Генерация комплекта HYBRID/TMC')
    base=generate_starccm_java_macro(xyz,result,model,fluid,yp,options)
    control=render_tmc_macro(settings)
    if unified_options is not None:
        control=control.replace("TMC", "TDC").replace("case 1: phase(true,", "case 1: phase(false,")
        control=control.replace("Action: 1 hydro, 2 thermal", "Action: 1 joint warmup, 2 joint warmup")
        control=control.replace('new String[]{"Velocity","Pressure","Temperature","WallShearStress","TotalEnthalpy"}', 'new String[]{"Velocity","Pressure","Temperature","BoundaryHeatFlux","WallShearStress","TotalEnthalpy"}')
        control=control.replace('if(key.equals("WallShearStress"))', 'if(key.equals("WallShearStress")||key.equals("BoundaryHeatFlux"))')
        control=control.replace('(frozen?"Hydrodynamic":"Thermal")', '(frozen?"Hydrodynamic":"Joint flow/thermal")')
        control=control.replace('private void runUntil(double target,WeightedWindow window,BufferedWriter out) throws Exception {',
            'private void runUntil(double target,WeightedWindow window,BufferedWriter out) throws Exception {\n'
            '        Object criteria=call(sim,"getSolverStoppingCriterionManager");\n'
            '        Object stop=call(criteria,"getSolverStoppingCriterion","Maximum Physical Time");\n'
            '        call(call(stop,"getMaximumTime"),"setValue",target); call(stop,"setIsUsed",true);\n'
            '        call(call(criteria,"getSolverStoppingCriterion","Maximum Steps"),"setIsUsed",false);')
        # The user controls one shared timeStep, not two unrelated parameters.
        control=control.replace('sim.getSolverManager().getSolver(ImplicitUnsteadySolver.class).getTimeStep().setDefinition(ref("TimeStep"));',
            'Object shared=find(sim.get(GlobalParameterManager.class),"timeStep");\n'
            '        if(shared==null) throw new IllegalStateException("Missing shared timeStep; run setup macro first");\n'
            '        ((ScalarGlobalParameter)find(sim.get(GlobalParameterManager.class),P+"TimeStep")).getQuantity().setDefinition("${timeStep}");\n'
            '        sim.getSolverManager().getSolver(ImplicitUnsteadySolver.class).getTimeStep().setDefinition("${timeStep}");')
    manifest=json.dumps(dict(format='meshBuilder-tmc-export',version=1,settings=settings,files=list(names),
        geometry='reference S18/S22; P=11.64mm, D=9.1mm, L=300mm',initialize_solution=False),ensure_ascii=False,indent=2)+'\n'
    guide='''HYBRID/TMC — первый запуск на КОПИИ симуляции STAR-CCM+ 2602.
1. Выполнить setup_starccm_subchannels.java: импорт, Fuse, физика и Derived Parts. Расчёт не инициализируется.
2. Выполнить TMC_Hybrid.java с Action=0: периодичность, нагрев/сток, отчёты и мониторы. Временные шаги не запускаются.
3. Проверить консоль, знаки источника и интерфейсы. На НОВОМ расчёте выполнить Initialize в STAR после настройки. Существующее решение без необходимости не переинициализировать.
4. Менять TMC_Action в Automation > Parameters и повторно запускать TMC_Hybrid.java:
   1 — гидродинамический разгон с Frozen Energy; 2 — тепловой разгон;
   3 — новая статистическая серия (сначала вручную подтвердить установление TMC_AllowStatistics=1);
   4 — добавить TMC_BlocksToRun блоков по TMC_BlockDuration; 5 — выгрузить; 6 — статус.
Значения формы задают начальные параметры: существующие TMC_ параметры макрос не перезаписывает; меняйте их в STAR.
Средние скалярных отчётов учитывают фактический dt. Полевые средние — отдельная опция с постоянным dt и проверкой API паузы.
Siemens SDK/симуляция не проверялись в среде разработки. Макрос ограничен эталоном двух подканалов; TMC — эффективный обмен, не чистая турбулентная корреляция.
Подробная инструкция: https://github.com/Vasoskirko/meshBuilder/blob/feat/tmc-hybrid-setup/tmc/README.md
CSV можно перепроверить: python TMC_analyse_series.py "папка/TMC_series_ID" --output result.json
'''
    if unified_options is not None:
        guide=guide.replace('TMC','TDC').replace('Frozen Energy','энергия включена')
        guide=guide.replace('1 — гидродинамический разгон', '1 — совместный гидродинамический и тепловой разгон').replace('2 — тепловой разгон','2 — продолжение совместного разгона')
        manifest=manifest.replace('TMC','TDC')
    analyser=(ROOT/'tmc'/'analyse_series.py').read_text(encoding='utf-8')
    if unified_options is not None:analyser=analyser.replace('TMC','TDC')
    texts={targets[1]:base,targets[2]:control,targets[3]:manifest,targets[4]:guide,targets[5]:analyser}
    staged={}
    try:
        for target in targets:
            fd,path=tempfile.mkstemp(prefix='.tmc_stage_',dir=directory);os.close(fd);staged[target]=Path(path)
        export_subchannel_plot3d(result,staged[targets[0]],progress_callback=lambda v,t:progress(10+int(.75*v),t))
        for target,text in texts.items():staged[target].write_text(text,encoding='utf-8')
        progress(95,'Публикация готового комплекта TMC') # cancellation point before replacements
        _publish(staged)
    finally:
        for path in staged.values():path.unlink(missing_ok=True)
    return targets
