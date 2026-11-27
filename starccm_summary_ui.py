"""Readable final review; does not start solvers or change export options."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QLabel,QPushButton,QCheckBox,QSizePolicy
from starccm_compact_ui import box,label_help


def text_label():
    label=QLabel();label.setTextFormat(Qt.PlainText);label.setWordWrap(True)
    label.setTextInteractionFlags(Qt.TextSelectableByMouse);label.setAlignment(Qt.AlignTop|Qt.AlignLeft);return label


def install(d):
    page=d.summary_tab.widget();layout=page.layout();stash=QWidget(d);stash.hide();d._summary_stash=stash
    while layout.count():
        item=layout.takeAt(0)
        if item.widget():item.widget().setParent(stash)
    d.summary_status=text_label();layout.addWidget(d.summary_status)
    grid=QGridLayout();grid.setSpacing(12);layout.addLayout(grid);d.summary_cards={};d.summary_edit_buttons={}
    specs=(('mesh','Сетка и границы',0),('physics','Физика',1),('parts','Производные части',2),('reports','Отчёты',3),('time','Среднее по времени',4),('quality','Качество сетки',5),('tdc','TDC',6))
    for i,(key,title,tab) in enumerate(specs):
        card,body=box(title);card.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Preferred);body.setAlignment(Qt.AlignTop);card.setStyleSheet('QLabel {background:transparent;}');header=QHBoxLayout();header.addStretch();button=QPushButton('Изменить');button.setMaximumWidth(100)
        button.clicked.connect(lambda _,n=tab:d.tabs.setCurrentIndex(n));header.addWidget(button);body.addLayout(header)
        label=text_label();body.addWidget(label);grid.addWidget(card,i//2,i%2);d.summary_cards[key]=label;d.summary_edit_buttons[key]=button
    files,body=box('Комплект экспорта');files.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Preferred);body.setAlignment(Qt.AlignTop);files.setStyleSheet('QLabel {background:transparent;}');grid.addWidget(files,3,1);d.summary_files=text_label();body.addWidget(d.summary_files)
    actions,body=box('Действия макроса после импорта');layout.addWidget(actions)
    d.chk_summary.setText('Создать сводку и CSV-аудит');body.addWidget(d.chk_summary)
    d.chk_evaluate_solution.setText('Включить вычисление физических отчётов в аудит');body.addWidget(d.chk_evaluate_solution)
    body.addWidget(label_help('Когда включать физические отчёты','Требуются корректные граничные условия и пригодные поля решения. По умолчанию аудит оценивает геометрию и выбранное качество; неинициализированные поля могут дать ошибки. Это не запускает итерации решателя.'))
    d.chk_initialize.setParent(page);d.chk_initialize.hide()  # Preserved disabled option, represented by a clear instruction below.
    d.summary_steps=text_label();body.addWidget(d.summary_steps)
    d.summary_details_toggle=QCheckBox('Техническая сводка');layout.addWidget(d.summary_details_toggle)
    layout.addWidget(d.summary_text);d.summary_text.setMaximumHeight(200);d.summary_text.hide();d.summary_details_toggle.toggled.connect(d.summary_text.setVisible)
    layout.addStretch()
    d._summary_refresh=lambda:refresh(d)
    for control in (d.chk_summary,d.chk_evaluate_solution):control.toggled.connect(lambda *_:refresh(d))
    refresh(d)


def refresh(d):
    if not hasattr(d,'summary_cards') or d.tabs.currentWidget()!=d.summary_tab:return
    cards=d.summary_cards;fuse=d.rb_inter_fuse.isChecked();unsteady=d.simulation_mode.currentData()=='unsteady';tdc=d.tdc_enabled.isChecked()
    on=lambda value:'включено' if value else 'выключено'
    cards['mesh'].setText(f'{d.sub_count} подканалов · '+('Fuse · один регион' if fuse else 'отдельные регионы')+'\nСтенки: '+d.rod_choice.currentText()+f'\nНазначено пар границ: {len(d._pairs)}; одиночных условий: {len(d._conditions)}')
    cards['physics'].setText(d.simulation_mode.currentText()+' · '+d.turbulence_choice.currentText()+'\nСвойства: '+d.property_choice.currentText()+'\nУравнение энергии: '+on(d.chk_thermal.isChecked())+'\nНагрев ТВЭЛ: '+on(d.heat_enabled.isChecked() and d.chk_thermal.isChecked())+'\nГравитация: '+(d.combo_gravity.currentText() if d.chk_gravity.isChecked() else 'выключена'))
    if d.rb_eos_iapws.isChecked():
        cards['physics'].setText(cards['physics'].text()+'\nμ: '+d.viscosity_method.currentText()+' · λ: '+d.conductivity_method.currentText())
    else:
        f=d.fluid_fields
        cards['physics'].setText(cards['physics'].text()+f'\nρ = {f["density"].text()} кг/м³ · μ = {f["dyn_vis"].text()} Па·с\nCp = {f["cp"].text()} Дж/(кг·К) · λ = {f["lambda"].text()} Вт/(м·К)')
    selected=[d.parts_targets.item(i).text() for i in range(d.parts_targets.count()) if d.parts_targets.item(i).checkState()==Qt.Checked]
    cards['parts'].setText('Области: '+(', '.join(selected) or 'не выбраны')+'\nПлоскости: '+d.plane_scheme.currentText()+(f' · N = {d.plane_count.value()}' if d.plane_scheme.currentData()=='uniform' else '')+'\nПлоскости зазоров: '+on(d.chk_gap_sections.isChecked() and d.chk_gap_sections.isEnabled())+'\nОсевые зонды: '+on(d.chk_axis_probes.isChecked()))
    if tdc:cards['parts'].setText(cards['parts'].text()+'\nTDC: сечения A/B создаются обязательно.')
    chosen=[cb.text() for cb in d.report_checkboxes.values() if cb.isChecked()]
    report_count=sum(d.report_targets.item(i).checkState()==Qt.Checked for i in range(d.report_targets.count()))
    cards['reports'].setText('Общие балансы: '+on(d.chk_reports.isChecked())+f'\nВыбрано подканалов: {report_count}\n'+('; '.join(chosen) or 'Дополнительные отчёты по подканалам не выбраны')+'\nИспользуются мгновенные поля решения.')
    if tdc:cards['reports'].setText(cards['reports'].text()+'\nTDC: обязательные балансы и температуры создаются.')
    mean_count=sum(cb.isChecked() for key,cb in d.mean_checkboxes.items() if key not in ('velocity','wall_shear'))
    runup=(f'{d.runup_passes.value()} пролётов '+d.runup_seconds_hint.text()) if d.time_input_mode.currentData()=='passes' else d.warmup_duration.text()+' с'
    block=(f'{d.block_passes.value()} пролётов '+d.block_seconds_hint.text()) if d.time_input_mode.currentData()=='passes' else d.block_duration.text()+' с'
    timing=f'Δt = {d.field_time_step.text()} с · внутренних итераций: {d.inner_iterations.value()}\nРазгон: {runup}\n'
    timing+=(f'Блок: {block} · блоков: {d.blocks_per_run.value()}\n' if tdc else 'Одно общее окно усреднения\n')
    timing+=f'Окончание: {d.end_time.text()} с · средних полей: {mean_count}'
    cards['time'].setText(timing if unsteady else 'Стационарный расчёт\nУсреднение по времени не создаётся.')
    cards['quality'].setText('Этап включён\nГистограммы: '+on(d.chk_histograms.isChecked())+'\nСкалярные сцены: '+on(d.chk_scene.isChecked())+'\nНаборы плохих ячеек: '+on(d.chk_bad_cells.isChecked()) if d.quality_enabled.isChecked() else 'Этап выключен\nОбъекты оценки качества не создаются.\nПроверки сетки при экспорте остаются обязательными.')
    cards['tdc'].setText(f'A = Подканал {d.tdc_a.currentData()} · B = Подканал {d.tdc_b.currentData()}\n'+d.tdc_target.currentText()+'\nМолекулярная и адвективная диагностика: '+on(d.tdc_components.isChecked())+'\nЭффективный обмен; чисто турбулентный TDC пока не выделяется.' if tdc else 'Не создаётся\nПри необходимости настройте пару подканалов на вкладке 7.')
    files=[d.edit_xyz.text(),'setup_starccm_subchannels.java']
    if tdc:files+=['TDC_Hybrid.java','TDC_export.json','TDC_START.txt']
    d.summary_files.setText('\n'.join(files)+'\n\n'+d.file_size_label.text())
    d.summary_steps.setText('Порядок: импорт → TDC_Action=0 → проверить условия → Initialize вручную → разгон → сбор статистики.\nСоздание объектов само по себе не запускает расчёт.' if tdc else 'После импорта проверьте свойства и граничные условия. Инициализация выполняется вручную в STAR-CCM+.\nСоздание объектов не запускает расчёт.')
    try:
        if tdc and (d.mesh_result is None or d.bundle_model is None):raise ValueError('Для проверки TDC нужна построенная сетка пучка.')
        d.read_options()
        message='Сводка настроек перед экспортом\nПолная проверка сетки и сохранение — по кнопке внизу окна.';color='#eaf2f8';border='#b8cde0'
    except ValueError as error:
        message='Требует внимания\n'+str(error);color='#fff4dc';border='#d8b46a'
    d.summary_status.setText(message);d.summary_status.setStyleSheet(f'QLabel {{background:{color};border:1px solid {border};border-radius:6px;padding:12px;}}')
