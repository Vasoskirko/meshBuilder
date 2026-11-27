"""Native Qt export window. Existing exporters remain the execution layer.

Unsupported STAR operations are disabled explicitly instead of exporting ignored
settings. Widgets retain their stable names for project/profile compatibility.
"""
from copy import deepcopy
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QGroupBox,
    QLabel,QCheckBox,QComboBox,QSpinBox,QScrollArea,QPlainTextEdit,QTableWidget,
    QTableWidgetItem,QPushButton)
from number_field import NumberField
from starccm_workflow import WORKFLOW_DEFAULTS,validate_workflow,estimate_plot3d_bytes
from starccm_tmc_export import TMC_DEFAULTS,reference_geometry


def note(layout,text):
    label=QLabel(text);label.setWordWrap(True);layout.addWidget(label);return label


def group(layout,title):
    box=QGroupBox(title);content=QVBoxLayout(box);layout.addWidget(box);return content


def unsupported(layout,text):
    cb=QCheckBox(text);cb.setEnabled(False);cb.setToolTip('Пока не поддержано генератором; настройка не экспортируется.');layout.addWidget(cb);return cb


def install(dialog,layout,header):
    d=dialog;d._unified_ready=False;d._workflow=deepcopy(WORKFLOW_DEFAULTS)
    # Keep the old containers alive until their controls have been reparented.
    d._legacy_pages=[]
    while d.tabs.count():
        old=d.tabs.widget(0);d.tabs.removeTab(0);old.setParent(d);old.hide();d._legacy_pages.append(old)
    d.grp_sources.hide();d.selection_hint.hide()
    pages=[]
    for name in ('1. Сетка','2. Физика','3. Геометрии и отчёты','4. Статистика','5. Качество','6. TDC','7. Итог'):
        page=QWidget();content=QVBoxLayout(page);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page)
        d.tabs.addTab(scroll,name);pages.append(content)
    header.setText('<b>Подготовка расчёта · STAR-CCM+ 2602</b><br>Сетка → физика → отчёты → статистика → качество → TDC → итог.')
    # Legacy mode is a backend compatibility switch, never a second visible form.
    d.export_mode=QComboBox(d);d.export_mode.addItem('Общий экспорт','general');d.export_mode.addItem('TDC','tdc');d.export_mode.hide()
    d._tmc_last_valid=deepcopy(TMC_DEFAULTS)
    d.tmc_tabs=QWidget(d);d.tmc_tabs.hide()  # Compatibility with existing callers.
    d.generate_button.setText('Проверить и сохранить комплект…')
    d.generate_button.clicked.disconnect()
    d.summary_tab=d.tabs.widget(6)
    def review_then_export():
        target=d.tabs.indexOf(d.summary_tab)
        if d.tabs.currentIndex()!=target:d.tabs.setCurrentIndex(target);return
        d.generate_and_save()
    d.generate_button.clicked.connect(review_then_export)
    mesh=pages[0]
    files=group(mesh,'Файл сетки и объём на диске');files.addWidget(d.edit_xyz);files.addWidget(d.chk_import)
    estimate=estimate_plot3d_bytes(d.mesh_result)
    size='Оценка недоступна до построения сетки' if estimate is None else f'Plot3D ASCII: ≈ {estimate[0]/1e6:,.1f}–{estimate[1]/1e6:,.1f} МБ'
    d.file_size_label=note(files,size+'\nЭто размер файла, не оперативной памяти. Повторные узлы блоков учтены.')
    joints=group(mesh,'Сопряжение блоков и подканалов')
    note(joints,'Внутри подканала: конформное объединение. Неконформные стыки пока блокируют CFD-экспорт; геометрия зазоров/перекрытий не исправляется интерфейсом.')
    unsupported(joints,'Создать неконформные интерфейсы внутри подканала — ожидает проверки импорта STAR 2602')
    joints.addWidget(d.rb_inter_intf);joints.addWidget(d.rb_inter_fuse)
    rods=group(mesh,'Поверхности ТВЭЛ / НК / ИК')
    d.rb_wall_60.setText('Сохранить исходные сектора 60°')
    d.rb_wall_by_rod.setText('Объединить по физическому стержню · только Fuse')
    d.rb_wall_rod.setText('Объединить по подканалу')
    for control in (d.rb_wall_60,d.rb_wall_by_rod,d.rb_wall_rod):rods.addWidget(control)
    unsupported(rods,'Объединить все rods — пока не поддержано')
    note(rods,'Отдельная группировка ТВЭЛ/НК/ИК ещё не поддержана. До её реализации используйте исходные сектора: классификацию нагреваемых стенок необходимо проверить в STAR.')
    d.boundary_hint=note(mesh,'');d.rb_io_split.hide();d.rb_io_single.hide()
    mesh.addWidget(d.chk_group_objects);d.chk_group_objects.setText('Папки объектов по назначению · без meshBuilder_')
    # Physics: one source for fluid values, also used by TDC.
    phys=pages[1];models=group(phys,'Режим и свойства')
    d.rb_turb_rst.setText('Стационарный · RST');d.rb_turb_srh.setText('Нестационарный · HYBRID · SRH / SST')
    for w in (d.rb_turb_rst,d.rb_turb_srh,d.rb_eos_const,d.rb_eos_iapws):models.addWidget(w)
    d.fluid_fields={};form=QFormLayout();models.addLayout(form)
    specs=(('density','Плотность ρ, кг/м³',725.553),('dyn_vis','Динамическая вязкость μ, Па·с',8.835e-5),('cp','Теплоёмкость Cp, Дж/(кг·К)',5476.),('lambda','Теплопроводность λ, Вт/(м·К)',.557),('t_ref_c','Опорная температура, °C',300.),('p_ref_mpa','Опорное абсолютное давление, МПа',15.))
    for key,label,default in specs:
        field=NumberField(float(d.fluid_props.get(key,default)),minimum=-273.149999 if key=='t_ref_c' else 1e-15)
        d.fluid_fields[key]=field;form.addRow(label,field)
    refresh_button=QPushButton('Обновить из калькулятора y+');models.addWidget(refresh_button)
    def refresh_fluid():
        for key,field in d.fluid_fields.items():
            if key in d.fluid_props:field.setValue(d.fluid_props[key])
    refresh_button.clicked.connect(refresh_fluid)
    transport=QFormLayout();models.addLayout(transport)
    d.viscosity_method=QComboBox();d.conductivity_method=QComboBox()
    for combo,label in ((d.viscosity_method,'Вязкость при IAPWS'),(d.conductivity_method,'Теплопроводность при IAPWS')):
        combo.addItem('Константа из y+','constant');combo.addItem('IAPWS · зависит от T и P','iapws');transport.addRow(label,combo)
    models.addWidget(d.chk_thermal)
    ref=group(phys,'Опорные значения и Initial Conditions')
    ref.addWidget(d.chk_gravity);ref.addWidget(d.combo_gravity)
    unsupported(ref,'Настраивать опорную плотность гравитации — API 2602 ещё не подтверждён')
    form=QFormLayout();ref.addLayout(form)
    d.initial_temperature=NumberField(float(d.fluid_props.get('t_ref_c',300.))+273.15,minimum=1e-15)
    d.initial_pressure=NumberField(0.,minimum=-1e12)
    d.initial_velocity=QComboBox();d.initial_velocity.addItem('Нулевая','zero');d.initial_velocity.addItem('Осевая · U_b','theory');d.initial_velocity.addItem('Возмущения VelocitySeed','seed');d.initial_velocity.setCurrentIndex(1)
    form.addRow('Начальная температура, K',d.initial_temperature);form.addRow('Давление относительно опорного, Па',d.initial_pressure);form.addRow('Начальная скорость',d.initial_velocity)
    d.initial_absolute=note(ref,'')
    unsupported(ref,'Назначить VelocitySeed начальным полем — после проверки выражения в STAR')
    conditions=group(phys,'Вход, выход, боковые пары и нагрев')
    note(conditions,'Общий экспорт сохраняет границы wall для ручной настройки. В TDC используются те же заданные пары, расход и нагрев; второй макрос добавляет компенсационный сток и статистику.')
    unsupported(conditions,'Массовый вход / давление на выходе для произвольной модели — ещё не поддержано')
    unsupported(conditions,'Выбрать произвольные боковые периодические пары на схеме — ещё не поддержано')
    # Reports: reuse native report controls, expose actual geometric source list.
    parts=pages[2];d.grp_sources.setTitle('Общая модель и исходные подканалы');parts.addWidget(d.grp_sources);d.grp_sources.show()
    parts.addWidget(d.chk_reports);d.chk_reports.setText('Общая модель — расходы на входе/выходе и балансы')
    note(parts,'Вход/выход не включают боковые периодические поверхности. Знак входного расхода обычно отрицательный. Общая модель не создаёт дополнительные плоскости.')
    for w in (d.chk_sub_planes,d.chk_sub_n_planes,d.spin_sub_n_planes,d.lbl_sub_dz_hint,d.chk_g_n_planes,d.spin_n_planes,d.lbl_dz_hint,d.chk_axis_probes):parts.addWidget(w)
    d.chk_sub_planes.setText('Измерительные сечения выбранных подканалов');d.chk_g_n_planes.setText('Дополнительные общие сечения всей модели')
    d.chk_g_key_planes.setChecked(False);d.chk_g_key_planes.hide()
    d.chk_g_n_planes.setChecked(False)
    parts.addWidget(d.chk_gap_sections)
    d.gap_table=QTableWidget(0,3);d.gap_table.setHorizontalHeaderLabels(['Зазор','Нормаль','Площадь, м²']);d.gap_table.setEditTriggers(QTableWidget.NoEditTriggers);d.gap_table.setMaximumHeight(160);parts.addWidget(d.gap_table)
    try:
        from starccm_export_geometry import export_geometry,shared_gap_sections
        _,domains=export_geometry(d.mesh_result,d.bundle_model)
        for gap in shared_gap_sections(domains):
            row=d.gap_table.rowCount();d.gap_table.insertRow(row)
            for col,value in enumerate((f"Gap_Sub{gap['a']}_Sub{gap['b']}",', '.join(f'{v:.5g}' for v in gap['normal']),'после импорта')):
                d.gap_table.setItem(row,col,QTableWidgetItem(value))
    except (AttributeError,ValueError,TypeError):pass
    note(parts,'Зазоры определяются по соседству всех исходных подканалов. После Fuse области подканалов создаются обязательно. Произвольные координаты сечений и выбор стороны периодического интерфейса пока требуют доработки; общий экспорт использует измерительные сечения.')
    reports=group(parts,'Какие отчёты создавать')
    for key,w in d.report_checkboxes.items():reports.addWidget(w)
    note(reports,'Трение: средний модуль напряжения, Cf и Darcy по стенкам. Отдельная осевая сила вязкого трения и учёт всех типов стенок ещё не реализованы — эти результаты не выдаются за КГС.')
    fields=group(parts,'Функции поля')
    d.chk_field_functions.setChecked(True);d.chk_field_functions.hide()
    for key,w in d.field_checkboxes.items():
        if key=='z_fraction':fields.addWidget(w);w.setChecked(True)
        else:w.setChecked(False);w.hide()
    d.seed_functions=QCheckBox('Подготовить функции начальных возмущений VelocitySeed');fields.addWidget(d.seed_functions)
    note(fields,'Служебные функции зазоров создаются вместе с нужными отчётами. Стандартные модуль и компоненты скорости не дублируются.')
    # Statistics and explicit stage settings.
    stats=pages[3];d.solver_hint=note(stats,'')
    stats.addWidget(d.field_time_step);d.field_time_step.setValue(2.5e-5)
    form=QFormLayout();stats.addLayout(form)
    d.inner_iterations=QSpinBox();d.inner_iterations.setRange(1,10000);d.inner_iterations.setValue(5)
    d.warmup_duration=NumberField(.45,minimum=1e-15);d.block_duration=NumberField(.45,minimum=1e-15)
    d.blocks_per_run=QSpinBox();d.blocks_per_run.setRange(1,10000);d.blocks_per_run.setValue(1)
    for label,w in (('Maximum Inner Iterations',d.inner_iterations),('Отрезок совместного разгона, с',d.warmup_duration),('Длительность блока, с',d.block_duration),('Блоков за запуск',d.blocks_per_run)):form.addRow(label,w)
    note(stats,'Автоматическое управление разгоном и блоками доступно в контроллере TDC. Для общего HYBRID параметры этапов сохраняются в проекте; решение запускается вручную. Совместный разгон идёт с энергией, без сбора итоговой статистики.')
    stats.addWidget(d.mean_group)
    note(stats,'Средние поля и средние скалярных отчётов — разные объекты. В общем экспорте задайте шаг начала средних вручную; пауза/блоки штатных средних проверяются контроллером TDC. Геометрическим отчётам мониторы не создаются.')
    # Quality is opt-in and completely gated at read_options.
    quality=pages[4];d.quality_enabled=QCheckBox('Создать средства оценки качества сетки');quality.addWidget(d.quality_enabled)
    d.quality_controls=QWidget();ql=QVBoxLayout(d.quality_controls);quality.addWidget(d.quality_controls)
    for w in (d.chk_scene,d.chk_histograms,d.spin_quality_bins,d.chk_bad_cells):ql.addWidget(w)
    d.quality_thresholds={};qform=QFormLayout();ql.addLayout(qform)
    for key,value in WORKFLOW_DEFAULTS['quality_thresholds'].items():
        field=NumberField(value,minimum=0,maximum=180 if key=='SkewnessAngle' else 1);d.quality_thresholds[key]=field;qform.addRow(key+(' >' if key=='SkewnessAngle' else ' <='),field)
    note(ql,'Пороги — настройки диагностики, не универсальные нормы. Неположительный объём проверяется всегда при включённом этапе.')
    check=QPushButton('Проверить текущую сетку в программе');check.clicked.connect(d.check_export_mesh);ql.addWidget(check)
    ql.addWidget(d.local_quality_text)
    note(quality,'Выключено по умолчанию. Проверки актуальности, полноты и конформности экспорта остаются обязательными.')
    # TDC owns only method-specific controls; properties and time are shared.
    tdc=pages[5];d.tdc_enabled=QCheckBox('Подготовить расчёт TDC');tdc.addWidget(d.tdc_enabled)
    d.tdc_status=note(tdc,'')
    d.tdc_equivalence=QCheckBox('Подтверждаю эквивалентность нескольких зазоров');tdc.addWidget(d.tdc_equivalence)
    d.tmc_fields={}
    for key,value in TMC_DEFAULTS.items():
        if type(value) is bool:w=QCheckBox();w.setChecked(value)
        elif type(value) is int:w=QSpinBox();w.setRange(1,100000000);w.setValue(value)
        else:w=NumberField(value,minimum=0 if key=='heat_flux_1' else 1e-15)
        d.tmc_fields[key]=w;w.setParent(d);w.hide()
    d.tmc_xyz=d.edit_xyz
    d.tdc_controls=QWidget();tdc.addWidget(d.tdc_controls)
    # Summary and initialization are the final step only.
    final=pages[6];d.summary_text=QPlainTextEdit();d.summary_text.setReadOnly(True);final.addWidget(d.summary_text)
    for w in (d.chk_summary,d.chk_evaluate_solution,d.chk_initialize):final.addWidget(w)
    d.chk_initialize.setChecked(False)
    d.chk_evaluate_solution.setChecked(False)
    note(final,'Повторный запуск не переинициализирует существующее решение. Создание объектов не запускает расчёт. API STAR-CCM+ 2602 нужно проверить на копии .sim.')
    for content in pages:content.addStretch()
    d.rb_wall_60.setChecked(True);d.quality_enabled.setChecked(False)
    d._unified_ready=True
    for control in (d.tdc_enabled,d.quality_enabled,d.rb_inter_fuse,d.rb_inter_intf,d.rb_turb_srh,d.rb_eos_iapws,d.chk_thermal):control.toggled.connect(lambda *_:refresh(d))
    for combo in (d.initial_velocity,d.viscosity_method,d.conductivity_method):combo.currentIndexChanged.connect(lambda *_:refresh(d))
    d.tabs.currentChanged.connect(lambda *_:refresh(d));d.export_mode.currentIndexChanged.connect(lambda i:d.tdc_enabled.setChecked(i==1))
    refresh(d)
    from starccm_compact_ui import install_compact
    install_compact(d)
    from starccm_parts_reports_ui import install as install_parts_reports
    install_parts_reports(d)
    from starccm_time_average_ui import install as install_time_average
    install_time_average(d)
    from starccm_tdc_ui import install as install_tdc
    install_tdc(d)
    header.setText('<b>Подготовка расчёта · STAR-CCM+ 2602</b><br>Сетка → физика → производные части → отчёты → среднее по времени → качество → TDC → итог.')


def refresh(d):
    if not getattr(d,'_unified_ready',False) or getattr(d,'_refreshing_unified',False):return
    d._refreshing_unified=True
    try:
        fuse=d.rb_inter_fuse.isChecked();hybrid=d.rb_turb_srh.isChecked();iapws=d.rb_eos_iapws.isChecked()
        unsteady=hybrid or (hasattr(d,'simulation_mode') and d.simulation_mode.currentData()=='unsteady')
        if not fuse and d.rb_wall_by_rod.isChecked():d.rb_wall_60.setChecked(True)
        d.rb_wall_by_rod.setEnabled(fuse);d.rb_wall_rod.setEnabled(True)
        d.boundary_hint.setText('Fuse: общий Inlet/Outlet. Threshold-области подканалов обязательны.' if fuse else 'Отдельные регионы: собственные вход/выход каждого подканала.')
        d.quality_controls.setEnabled(d.quality_enabled.isChecked());d.tdc_controls.setEnabled(d.tdc_enabled.isChecked())
        if iapws:d.chk_thermal.setChecked(True)
        d.chk_thermal.setEnabled(not iapws)
        for combo in (d.viscosity_method,d.conductivity_method):combo.setEnabled(iapws)
        for key in ('density','cp'):d.fluid_fields[key].setEnabled(not iapws)
        d.fluid_fields['dyn_vis'].setEnabled(not iapws or d.viscosity_method.currentData()=='constant')
        d.fluid_fields['lambda'].setEnabled(not iapws or d.conductivity_method.currentData()=='constant')
        d.initial_temperature.setEnabled(d.chk_thermal.isChecked())
        for w in (d.inner_iterations,d.warmup_duration,d.block_duration,d.blocks_per_run,d.field_time_step):w.setEnabled(unsteady)
        d.mean_group.setEnabled(unsteady)
        d.solver_hint.setText('Implicit Unsteady · Second Order · SIMPLEC; постоянный Δt через ${timeStep}. Maximum Steps выключен; остановка по физическому времени.' if unsteady else 'Стационарный RST. Временные этапы и средние поля недоступны.')
        tdc=d.tdc_enabled.isChecked();d.export_mode.setCurrentIndex(1 if tdc else 0)
        compat='Общие настройки; проверка пары и баланса при экспорте.'
        if hasattr(d,'_tdc_refresh'):d._tdc_refresh()
        # Current generic export deliberately keeps wall conditions manual.
        d.chk_initialize.setEnabled(False)
        d.chk_initialize.setChecked(False)
        try:
            pressure=d.fluid_fields['p_ref_mpa'].value()+d.initial_pressure.value()/1e6
            d.initial_absolute.setText(f'Начальное абсолютное давление: {pressure:g} МПа')
        except ValueError:d.initial_absolute.setText('Проверьте начальное/опорное давление')
        d.summary_text.setPlainText('\n'.join((d.boundary_hint.text(),d.file_size_label.text(),d.solver_hint.text(),
            'Качество: '+('включено' if d.quality_enabled.isChecked() else 'выключено; объекты качества не создаются'),
            'TDC: '+('включён; '+compat if tdc else 'выключен'),
            'Обычный экспорт: setup_starccm_subchannels.java + XYZ. TDC: дополнительно TDC_Hybrid.java, JSON и инструкция; результаты в CSV, без BMBC.',
            'Проверьте свойства, условия и сообщения [!] перед инициализацией. Неподдержанные настройки показаны неактивными.')))
        if hasattr(d,'_compact_refresh'):d._compact_refresh()
        if hasattr(d,'_time_mean_refresh'):d._time_mean_refresh()
    finally:d._refreshing_unified=False


def read_workflow(d):
    result=dict(d._workflow,quality_thresholds={key:field.value() if d.quality_enabled.isChecked() else field.model.raw for key,field in d.quality_thresholds.items()},fluid={key:field.value() if field.isEnabled() else field.model.raw for key,field in d.fluid_fields.items()},quality_enabled=d.quality_enabled.isChecked(),tdc_enabled=d.tdc_enabled.isChecked(),tdc_equivalence=d.tdc_equivalence.isChecked(),
        viscosity_method=d.viscosity_method.currentData(),conductivity_method=d.conductivity_method.currentData(),
        initial_velocity=d.initial_velocity.currentData(),initial_temperature=d.initial_temperature.value() if d.chk_thermal.isChecked() else d.initial_temperature.model.raw,
        initial_pressure=d.initial_pressure.value(),inner_iterations=d.inner_iterations.value(),
        warmup_duration=d.warmup_duration.value() if d.rb_turb_srh.isChecked() or (hasattr(d,'simulation_mode') and d.simulation_mode.currentData()=='unsteady') else d.warmup_duration.model.raw,block_duration=d.block_duration.value() if d.rb_turb_srh.isChecked() or (hasattr(d,'simulation_mode') and d.simulation_mode.currentData()=='unsteady') else d.block_duration.model.raw,
        blocks_per_run=d.blocks_per_run.value(),velocity_seed=d.seed_functions.isChecked())
    if hasattr(d,'_compact_workflow'):result.update(d._compact_workflow())
    if hasattr(d,'_parts_workflow'):result.update(d._parts_workflow())
    if result['tdc_enabled'] and hasattr(d,'_tdc_read'):result['tdc_settings']=d._tdc_read()
    if hasattr(d,'_time_mean_read'):result.update(d._time_mean_read())
    return validate_workflow(result)


def apply_workflow(d,values):
    values=validate_workflow(values);d._workflow=values
    for key,value in values['fluid'].items():d.fluid_fields[key].setValue(value)
    for key,value in values['quality_thresholds'].items():d.quality_thresholds[key].setValue(value)
    for key,attr in (('quality_enabled','quality_enabled'),('tdc_enabled','tdc_enabled'),('tdc_equivalence','tdc_equivalence'),('velocity_seed','seed_functions')):getattr(d,attr).setChecked(values[key])
    for key in ('viscosity_method','conductivity_method','initial_velocity'):
        w=getattr(d,key);w.setCurrentIndex(w.findData(values[key]))
    for key in ('initial_temperature','initial_pressure','inner_iterations','warmup_duration','block_duration','blocks_per_run'):getattr(d,key).setValue(values[key])
    refresh(d)
    if hasattr(d,'_compact_apply'):d._compact_apply(values)
    if hasattr(d,'_apply_parts_workflow'):d._apply_parts_workflow(values)
    if hasattr(d,'_time_mean_apply'):d._time_mean_apply(values)
    if hasattr(d,'_tdc_apply'):d._tdc_apply(values['tdc_settings'])
