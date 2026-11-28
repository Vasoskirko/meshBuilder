"""Compact transient averaging controls, with physical-time based default start."""
import math
from PySide6.QtWidgets import QWidget,QVBoxLayout,QFormLayout,QCheckBox,QLabel,QGridLayout,QSpinBox,QComboBox,QHBoxLayout
from starccm_compact_ui import box,label_help
from starccm_time_schedule import schedule
from number_field import NumberField


def install(d):
    page=d.tabs.widget(4).widget();layout=page.layout();d._mean_stash=QWidget(d);d._mean_stash.hide()
    def stash(content):
        while content.count():
            item=content.takeAt(0)
            if item.widget():item.widget().setParent(d._mean_stash)
            elif item.layout():stash(item.layout())
    stash(layout)
    d.tabs.setTabText(4,'5. Среднее по времени');d.tabs.setTabText(5,'6. Качество сетки')
    d.averaging_tab=d.tabs.widget(4)
    settings,sl=box('Время и итерации');layout.addWidget(settings);form=QFormLayout();sl.addLayout(form)
    form.addRow(label_help('Δt, с','Постоянный шаг времени; параметр ${timeStep}. Выбирайте по разрешению характерных временных масштабов и контролю CFL, затем проверьте независимость результата от Δt.'),d.field_time_step)
    d.inner_iterations.setMaximumWidth(145);d.blocks_per_run.setMaximumWidth(145)
    form.addRow('Число внутренних итераций',d.inner_iterations)
    d.time_input_mode=QComboBox();d.time_input_mode.addItem('Числом пролётов','passes');d.time_input_mode.addItem('Секундами · совместимость профиля','seconds');form.addRow('Задание времени',d.time_input_mode)
    d.runup_passes=QSpinBox();d.block_passes=QSpinBox()
    for spin,value in ((d.runup_passes,10),(d.block_passes,5)):spin.setRange(1,1000000000);spin.setValue(value);spin.setMaximumWidth(145)
    d.runup_seconds_hint=QLabel();d.block_seconds_hint=QLabel()
    d.runup_time_row=QWidget();runup=QHBoxLayout(d.runup_time_row);runup.setContentsMargins(0,0,0,0);runup.addWidget(d.runup_passes);runup.addWidget(d.warmup_duration);runup.addWidget(d.runup_seconds_hint);runup.addStretch()
    d.block_time_row=QWidget();block=QHBoxLayout(d.block_time_row);block.setContentsMargins(0,0,0,0);block.addWidget(d.block_passes);block.addWidget(d.block_duration);block.addWidget(d.block_seconds_hint);block.addStretch()
    form.addRow(label_help('Разгон · пролёты','t_f=L/U_b, T_runup=N_runup·t_f. Для начального планирования можно взять 10–20 пролётов. Продолжайте до отсутствия дрейфа расхода, перепада давления, температур и балансов; число пролётов не доказывает стационарность.'),d.runup_time_row)
    form.addRow(label_help('Блок · пролёты','T_block=N_block·t_f. Предварительный ориентир — 5–10 пролётов. Блок должен быть длиннее времени корреляции; длительность нужно проверять увеличением окна и сравнением статистики.'),d.block_time_row)
    form.addRow(label_help('Планируемых блоков','В TDC контроллер сохраняет отдельные скалярные результаты блоков и общее среднее за весь сбор. Поля накапливаются общим окном. Без TDC — одно общее окно, без блочных скалярных результатов.'),d.blocks_per_run)
    d.end_time_auto=QCheckBox('По разгону и сбору');d.end_time_auto.setChecked(True)
    d.end_time=NumberField(1.,minimum=1e-15);d.end_time.setMaximumWidth(145)
    end_row=QWidget();el=QHBoxLayout(end_row);el.setContentsMargins(0,0,0,0);el.addWidget(d.end_time);el.addWidget(d.end_time_auto);el.addStretch()
    form.addRow(label_help('Окончание, с','T_min=T_runup+N_blocks·T_block, округлённое вверх до шага Δt. Время окончания нельзя задать ниже T_min. Поля продолжают накапливаться до остановки, включая дополнительное время при ручном увеличении.'),end_row)
    d.time_minimum_hint=QLabel();sl.addWidget(d.time_minimum_hint)
    d.flight_time_hint=QLabel();sl.addWidget(d.flight_time_hint)
    d.mean_group.setTitle('Функции для усреднения по времени');layout.addWidget(d.mean_group)
    # Reparent fields to remove the old start-step row and all legacy explanations.
    old=d.mean_group.layout()
    stash(old)
    fields=QGridLayout();old.addLayout(fields);fields.addWidget(QLabel('<b>В объёме</b>'),0,0);fields.addWidget(QLabel('<b>На стенках</b>'),0,1)
    rows=[1,1]
    for key,cb in d.mean_checkboxes.items():
        if key in ('velocity','wall_shear'):cb.hide();continue
        column=1 if key.startswith('wall_') else 0
        fields.addWidget(cb,rows[column],column);rows[column]+=1;cb.show()
    advanced,al=box('Начало усреднения');layout.addWidget(advanced)
    d.mean_start_auto=QCheckBox('После отрезка разгона');d.mean_start_auto.setChecked(True);al.addWidget(d.mean_start_auto)
    al.addWidget(label_help('Начало по времени','Для нового расчёта N_start=ceil(T_runup/Δt)+1: первый отсчёт после разгона. При продолжении существующей симуляции выберите абсолютный шаг вручную. Повторный импорт сохраняет уже накопленные средние.'))
    d.manual_mean_start_row=QWidget();manual=QFormLayout(d.manual_mean_start_row);manual.setContentsMargins(0,0,0,0);manual.addRow('Абсолютный номер шага',d.spin_mean_start);d.spin_mean_start.setMaximumWidth(145);al.addWidget(d.manual_mean_start_row)
    d.spin_mean_start.setToolTip('Ручной абсолютный номер отсчёта Physical Time Monitor. Требуется только для продолжения расчёта или специального окна.')
    d._workflow['mean_start_auto']=True
    initial_mode='passes' if d._surface_catalog.get('endcaps') else 'seconds'
    d._workflow['time_input_mode']=initial_mode;d.time_input_mode.setCurrentIndex(d.time_input_mode.findData(initial_mode))
    layout.addStretch()
    def refresh():
        unsteady=d.simulation_mode.currentData()=='unsteady';iapws=d.rb_eos_iapws.isChecked();thermal=d.chk_thermal.isChecked()
        d.tabs.setTabEnabled(d.tabs.indexOf(d.averaging_tab),unsteady)
        d.averaging_tab.setEnabled(unsteady)
        d.mean_group.setEnabled(unsteady)
        for key,cb in d.mean_checkboxes.items():
            if key in ('density','viscosity'):cb.setEnabled(iapws);cb.setVisible(iapws)
            if key in ('enthalpy','temperature','wall_heat_flux'):cb.setEnabled(thermal)
        tdc=d.tdc_enabled.isChecked()
        d.mean_start_auto.setEnabled(not tdc)
        d.mean_start_auto.setText('TDC: с начала новой серии после разгона (Action=3)' if tdc else 'После отрезка разгона')
        d.manual_mean_start_row.setVisible(not d.mean_start_auto.isChecked() and not tdc)
        passes=d.time_input_mode.currentData()=='passes'
        for w in (d.runup_passes,d.block_passes):w.setVisible(passes)
        for w in (d.warmup_duration,d.block_duration):w.setVisible(not passes)
        try:
            values=current_values(parse_end=False)
            plan=schedule(values,d._surface_catalog,d.read_fluid(),d.yplus_data,d.lz_m,d.field_time_step.value())
            d.flight_time_hint.setText('Один пролёт L/U_b = '+(f'{plan["flight"]:.6g} с' if plan['flight'] else 'нет геометрии'))
            d.runup_seconds_hint.setText(f'≈ {plan["warmup"]:.6g} с' if passes else '')
            d.block_seconds_hint.setText(f'≈ {plan["block"]:.6g} с' if passes else '')
            d.time_minimum_hint.setText(f'Минимальное окончание: {plan["minimum"]:.6g} с')
            d.end_time.setLimits(plan['minimum'],1e12)
            if d.end_time_auto.isChecked():d.end_time.setValue(plan['minimum'])
        except (ValueError,KeyError,StopIteration):d.time_minimum_hint.setText('Проверьте время, Re, свойства и геометрию')
        tdc=d.tdc_enabled.isChecked()
        d.end_time_auto.setEnabled(True)
        d.end_time.setEnabled(not d.end_time_auto.isChecked())
        d.end_time.setToolTip('Окончание не меньше разгона и планируемого сбора.')
    def current_values(parse_end=True):
        return dict(d._workflow,tdc_enabled=d.tdc_enabled.isChecked(),time_input_mode=d.time_input_mode.currentData(),runup_passes=d.runup_passes.value(),block_passes=d.block_passes.value(),warmup_duration=d.warmup_duration.value(),block_duration=d.block_duration.value(),blocks_per_run=d.blocks_per_run.value(),end_time=0. if d.end_time_auto.isChecked() or not parse_end else d.end_time.value())
    def read():
        automatic=d.mean_start_auto.isChecked()
        active=d.simulation_mode.currentData()=='unsteady'
        result=dict(mean_start_auto=automatic,time_input_mode=d.time_input_mode.currentData(),runup_passes=d.runup_passes.value(),block_passes=d.block_passes.value(),end_time=0. if d.end_time_auto.isChecked() else d.end_time.model.raw)
        if active:
            values=current_values();plan=schedule(values,d._surface_catalog,d.read_fluid(),d.yplus_data,d.lz_m,d.field_time_step.value())
            result.update(warmup_duration=plan['warmup'],block_duration=plan['block'],end_time=values['end_time'])
            if automatic:
                step=math.ceil(plan['warmup']/d.field_time_step.value()-1e-12)+1
                if not 1<=step<=1000000000:raise ValueError('Начало усреднения вне допустимого диапазона шагов')
                d.spin_mean_start.setValue(step)
        return result
    def apply(values):
        d.end_time.setLimits(1e-15,1e12)
        d.time_input_mode.setCurrentIndex(d.time_input_mode.findData(values.get('time_input_mode','seconds')))
        d.runup_passes.setValue(values.get('runup_passes',10));d.block_passes.setValue(values.get('block_passes',5));d.end_time_auto.setChecked(values.get('end_time',0.)==0)
        if values.get('end_time',0.):d.end_time.setValue(values['end_time'])
        d.mean_start_auto.setChecked(values.get('mean_start_auto',False));refresh()
    d.mean_start_auto.toggled.connect(refresh)
    d.time_input_mode.currentIndexChanged.connect(refresh);d.end_time_auto.toggled.connect(refresh)
    for spin in (d.runup_passes,d.block_passes,d.blocks_per_run):spin.valueChanged.connect(refresh)
    for field in (d.field_time_step,d.warmup_duration):field.editingFinished.connect(refresh)
    for field in d.fluid_fields.values():field.editingFinished.connect(refresh)
    d._time_mean_refresh=refresh;d._time_mean_read=read;d._time_mean_apply=apply
    refresh()
