"""Compact transient averaging controls, with physical-time based default start."""
import math
from PySide6.QtWidgets import QWidget,QVBoxLayout,QFormLayout,QCheckBox,QLabel,QGridLayout
from starccm_compact_ui import box,label_help
from starccm_flow_defaults import calculator_mass_flow


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
    form.addRow(label_help('Отрезок разгона, с','Пролёт: t_f=L/U_b. Для предварительного планирования можно взять 10–20 пролётов совместного гидродинамического/теплового разгона; это не критерий стационарности. Продолжайте до отсутствия дрейфа расхода, перепада давления, температур и балансов. При медленной тепловой релаксации понадобится больше времени.'),d.warmup_duration)
    form.addRow(label_help('Длительность блока усреднения, с','Начальная оценка: 5–10 пролётов на блок. Блок должен быть существенно длиннее времени корреляции измеряемой величины. Сравнивайте последовательные блочные средние и проверяйте увеличение окна; число пролётов само по себе не доказывает сходимость. Сейчас средние поля накапливаются одним общим окном, без автоматического сброса между блоками.'),d.block_duration)
    form.addRow(label_help('Число блоков','Задаёт планируемую длительность сбора: T_avg=N_blocks·T_block. В общем экспорте остановка задаётся на T_runup+T_avg. Независимые блочные скалярные статистики создаёт контроллер TDC; их общий состав обсудим отдельно.'),d.blocks_per_run)
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
    layout.addStretch()
    def refresh():
        unsteady=d.simulation_mode.currentData()=='unsteady';iapws=d.rb_eos_iapws.isChecked();thermal=d.chk_thermal.isChecked()
        d.tabs.setTabEnabled(d.tabs.indexOf(d.averaging_tab),unsteady)
        d.averaging_tab.setEnabled(unsteady)
        d.mean_group.setEnabled(unsteady and not d.tdc_enabled.isChecked())
        for key,cb in d.mean_checkboxes.items():
            if key in ('density','viscosity'):cb.setEnabled(iapws);cb.setVisible(iapws)
            if key in ('enthalpy','temperature','wall_heat_flux'):cb.setEnabled(thermal)
        d.manual_mean_start_row.setVisible(not d.mean_start_auto.isChecked())
        try:
            cap=next(r for r in d._surface_catalog.get('endcaps',[]) if r['role']=='Inlet')
            props=d.read_fluid();flow=calculator_mass_flow(d._surface_catalog,props,d.yplus_data,cap['id']);velocity=flow/(props['density']*cap['area'])
            flight=d.lz_m/velocity
            d.flight_time_hint.setText(f'Один пролёт L/U_b = {flight:.4g} с')
        except (ValueError,KeyError,StopIteration):d.flight_time_hint.setText('Пролёт L/U_b: проверьте Re, свойства и геометрию')
    def read():
        automatic=d.mean_start_auto.isChecked()
        if automatic and d.simulation_mode.currentData()=='unsteady':
            step=math.ceil(d.warmup_duration.value()/d.field_time_step.value()-1e-12)+1
            if not 1<=step<=1000000000:raise ValueError('Начало усреднения вне допустимого диапазона шагов')
            d.spin_mean_start.setValue(step)
        return dict(mean_start_auto=automatic)
    def apply(values):
        d.mean_start_auto.setChecked(values.get('mean_start_auto',False));refresh()
    d.mean_start_auto.toggled.connect(refresh)
    for field in (d.field_time_step,d.warmup_duration):field.editingFinished.connect(refresh)
    for field in d.fluid_fields.values():field.editingFinished.connect(refresh)
    d._time_mean_refresh=refresh;d._time_mean_read=read;d._time_mean_apply=apply
    refresh()
