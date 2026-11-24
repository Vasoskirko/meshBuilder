"""Focused reference TMC form; general export controls remain independent."""
from copy import deepcopy
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QLabel,QComboBox,QTabWidget,QScrollArea,QSpinBox,QCheckBox,QLineEdit,QFileDialog,QMessageBox
from number_field import NumberField
from starccm_tmc_export import TMC_DEFAULTS,validate_tmc_settings,reference_geometry,canonical_tmc_options,bundle_names,write_tmc_bundle
from starccm_export_profile import DEFAULTS,validate_options

LABELS=dict(rho='Плотность ρ, кг/м³',mu='Динамическая вязкость μ, Па·с',cp='Теплоёмкость Cp, Дж/(кг·К)',
    conductivity='Теплопроводность λ, Вт/(м·К)',temperature_ref='Опорная температура, K',
    heat_flux_1='Тепловой поток Sub1, Вт/м²',heat_flux_2='Тепловой поток Sub2, Вт/м²',mass_flow='Расход всего сечения, кг/с',
    time_step='Шаг времени Δt, с',hydro_duration='Отрезок гидродинамического разгона, с',thermal_duration='Отрезок теплового разгона, с',
    block_duration='Длительность блока статистики, с',blocks_to_run='Блоков за один запуск Action=4',max_steps='Максимум шагов за одно действие',min_delta_t='Минимальная разность температур TMC, K')


def add_tmc_ui(dialog,layout,header):
    dialog._tmc_last_valid=deepcopy(TMC_DEFAULTS)
    row=QHBoxLayout();row.addWidget(QLabel('Режим экспорта:',dialog))
    dialog.export_mode=QComboBox(dialog)
    dialog.export_mode.addItem('Обычный STAR-CCM+ — общие настройки','general')
    dialog.export_mode.addItem('HYBRID / TMC — эталон двух подканалов, 300 мм','tmc_reference')
    row.addWidget(dialog.export_mode,1);layout.insertLayout(1,row)
    dialog.tmc_tabs=QTabWidget(dialog);dialog.tmc_fields={}
    pages=[]
    for title in ('1. Комплект и сетка','2. Свойства и нагрев','3. Этапы расчёта','4. Отчёты и статистика'):
        page=QWidget();v=QVBoxLayout(page);pages.append(v)
        scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(page);dialog.tmc_tabs.addTab(scroll,title)
    note=QLabel('Создаются XYZ, setup_starccm_subchannels.java, TMC_Hybrid.java, настройки JSON, инструкция и проверка CSV.\n'
        'Сначала импортный макрос, затем TMC Action=0. В новом расчёте инициализация выполняется в STAR после настройки. Экспорт сам не запускает расчёт.',dialog)
    note.setWordWrap(True);pages[0].addWidget(note)
    dialog.tmc_compat=QLabel(dialog);dialog.tmc_compat.setWordWrap(True);pages[0].addWidget(dialog.tmc_compat)
    form=QFormLayout();dialog.tmc_xyz=QLineEdit(dialog.edit_xyz.text(),dialog)
    dialog.tmc_xyz.textChanged.connect(dialog.edit_xyz.setText);dialog.edit_xyz.textChanged.connect(dialog.tmc_xyz.setText)
    form.addRow('Имя файла сетки XYZ:',dialog.tmc_xyz);pages[0].addLayout(form)
    locked=QLabel('Фиксировано для эталона: Fuse / один регион; исходные rod-секторы; общий вход/выход; SRH/SST; постоянные свойства; энергия включена; гравитация выключена; 11 сечений на подканал.\n'
        'Другие геометрии и неконформные стыки этот режим не поддерживает. Значения формы задают начальные параметры нового расчёта; существующие TMC_ параметры меняются в STAR.',dialog)
    locked.setWordWrap(True);pages[0].addWidget(locked);pages[0].addStretch()
    for page,keys in ((pages[1],('rho','mu','cp','conductivity','temperature_ref','mass_flow','heat_flux_1','heat_flux_2')),
                      (pages[2],('time_step','hydro_duration','thermal_duration','block_duration','blocks_to_run','max_steps','min_delta_t'))):
        form=QFormLayout()
        for key in keys:
            value=TMC_DEFAULTS[key]
            if type(value) is int:
                widget=QSpinBox(dialog);widget.setRange(1,10000 if key=='blocks_to_run' else 100000000);widget.setValue(value)
                widget.setKeyboardTracking(False)
            else:widget=NumberField(value,minimum=0 if key=='heat_flux_1' else 1e-15,maximum=1e12)
            dialog.tmc_fields[key]=widget;form.addRow(LABELS[key],widget)
        page.addLayout(form);page.addStretch()
    control=QLabel('В STAR параметры TMC_Action:\n0 — настройка; 1 — гидродинамика (Frozen Energy); 2 — тепловой разгон;\n'
        '3 — новая серия после проверки установления; 4 — добавить блоки; 5 — выгрузить; 6 — статус.\n'
        'Длительности считаются от текущего физического времени. Начальные 0,45 с не гарантируют установление.',dialog)
    control.setWordWrap(True);pages[2].insertWidget(0,control)
    reports=QLabel('Обязательный набор создаётся автоматически:\n'
        '• Геометрия: площади, объёмы, смоченные периметры, гидравлические диаметры, площадь зазора.\n'
        '• Мгновенные расходы, температуры, источники и потоки энергии, трение, CFL и балансы.\n'
        '• Средние скалярных отчётов с фактическим dt, блоковые CSV, TMC по отношению средних с поправкой на накопление.\n'
        'Мониторов геометрии и постоянных свойств нет. TMC — эффективный обмен; эквивалентность трёх зазоров нужно подтвердить расчётом.',dialog)
    reports.setWordWrap(True);pages[3].addWidget(reports)
    for key,text in (('create_field_means','Дополнительные средние поля (Velocity, Pressure, Temperature, WallShearStress, TotalEnthalpy)'),
                     ('gap_conduction','Диагностика молекулярного переноса через зазор и поправленный TMC')):
        box=QCheckBox(text,dialog);dialog.tmc_fields[key]=box;pages[3].addWidget(box)
    warning=QLabel('Полевые средние требуют постоянного dt на всю серию и проверки API паузы в 2602.\n'
        'Молекулярная поправка использует grad(Temperature) и не отделяет среднюю конвекцию.\n'
        'Новый макрос ещё требует пробного запуска в STAR на копии .sim; Siemens SDK в среде разработки недоступен.',dialog)
    warning.setWordWrap(True);pages[3].addWidget(warning);pages[3].addStretch()
    layout.insertWidget(layout.indexOf(dialog.tabs)+1,dialog.tmc_tabs,1)
    def changed():
        tmc=dialog.export_mode.currentData()=='tmc_reference'
        if not tmc:
            try:read_tmc_settings(dialog)
            except ValueError:pass  # An invalid inactive draft must not block general export.
        dialog.grp_sources.setVisible(not tmc)
        dialog.tabs.setVisible(not tmc);dialog.tmc_tabs.setVisible(tmc);dialog.selection_hint.setVisible(not tmc)
        header.setText('<b>HYBRID / TMC: эталон двух подканалов</b><br>Настройка периодичности, нагрева/стока и управляемых временных блоков.' if tmc else dialog._general_header)
        dialog.generate_button.setText('Сохранить комплект HYBRID / TMC…' if tmc else '🚀 Сгенерировать макрос (.java) и сетку Plot3D…')
        if tmc:
            try:reference_geometry(dialog.mesh_result,dialog.bundle_model);message='Сетка совместима с эталоном TMC.';color='#176b34'
            except ValueError as exc:message=str(exc);color='#a52323'
            dialog.tmc_compat.setText(message);dialog.tmc_compat.setStyleSheet(f'padding:8px;color:{color};')
    dialog._general_header=header.text();dialog.export_mode.currentIndexChanged.connect(changed);changed()


def read_tmc_settings(dialog):
    values={}
    for key,widget in dialog.tmc_fields.items():
        if type(TMC_DEFAULTS[key]) is bool:values[key]=widget.isChecked()
        else:
            if type(TMC_DEFAULTS[key]) is int:
                if not widget.hasAcceptableInput():raise ValueError(f'{LABELS[key]}: проверьте целое число')
                widget.interpretText()
            values[key]=widget.value()
    result=validate_tmc_settings(values);dialog._tmc_last_valid=deepcopy(result);return result


def apply_tmc_settings(dialog,values):
    values=validate_tmc_settings(values)
    for key,value in values.items():
        widget=dialog.tmc_fields[key]
        if type(value) is bool:widget.setChecked(value)
        else:widget.setValue(value)
    dialog._tmc_last_valid=deepcopy(values)


def tmc_options(dialog):
    settings=read_tmc_settings(dialog)
    values=deepcopy(DEFAULTS);values.update(canonical_tmc_options(settings))
    values.update(export_mode='tmc_reference',tmc_settings=settings)
    return validate_options(values,dialog.sub_count)


def export_tmc(dialog):
    try:
        options=tmc_options(dialog);reference_geometry(dialog.mesh_result,dialog.bundle_model)
        xyz=dialog.tmc_xyz.text().strip();names=bundle_names(xyz)
    except ValueError as exc:QMessageBox.warning(dialog,'Проверьте TMC',str(exc));return
    parent=dialog.parent()
    if parent is not None and hasattr(parent,'can_export_mesh') and (not parent.can_export_mesh() or parent.current_mesh_result is not dialog.mesh_result):
        QMessageBox.warning(dialog,'Экспорт недоступен','Сетка устарела. Перестройте её.');return
    directory=QFileDialog.getExistingDirectory(dialog,'Папка комплекта HYBRID / TMC')
    if not directory:return
    from pathlib import Path
    existing=[name for name in names if (Path(directory)/name).exists()]
    if existing and QMessageBox.question(dialog,'Заменить файлы комплекта?', '\n'.join(existing)+'\nБудут заменены готовым комплектом.',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
    from mesh_export_jobs import run_export,ExportCancelled
    result=dialog.mesh_result;model=deepcopy(dialog.bundle_model);settings=deepcopy(options['tmc_settings'])
    def compute(progress):return write_tmc_bundle(directory,xyz,result,model,settings,progress)
    def success(paths):
        QMessageBox.information(dialog,'Комплект TMC создан','\n'.join(str(path) for path in paths)+'\n\nПорядок запуска описан в TMC_START.txt.');dialog.accept()
    def failure(exc):
        if not isinstance(exc,ExportCancelled):QMessageBox.critical(dialog,'Ошибка экспорта TMC',str(exc))
    run_export(dialog,'Экспорт HYBRID / TMC',compute,success,failure)
