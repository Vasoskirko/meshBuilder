"""Compact presentation and surface editor for the native STAR export dialog."""
from copy import deepcopy
from PySide6.QtCore import Qt,QTimer
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QGridLayout,QFormLayout,
    QGroupBox,QLabel,QComboBox,QToolButton,QPushButton,QCheckBox,QTableWidget,
    QTableWidgetItem,QHeaderView,QSplitter,QMessageBox)
from number_field import NumberField
from starccm_surface_catalog import surface_catalog,validate_pairs
from starccm_surface_preview import SurfacePreview


def help_button(text):
    button=QToolButton();button.setText('?');button.setToolTip(text);button.setAccessibleName('Пояснение')
    button.setFixedSize(23,23)
    button.clicked.connect(lambda:QMessageBox.information(button,'Пояснение',text));return button


def label_help(text,explanation=''):
    widget=QWidget();row=QHBoxLayout(widget);row.setContentsMargins(0,0,0,0);row.setSpacing(5)
    row.addWidget(QLabel(text))
    if explanation:row.addWidget(help_button(explanation))
    row.addStretch();return widget


def compact_field(widget):
    widget.setMaximumWidth(145);widget.setMinimumWidth(95);widget.show();return widget


def box(title):
    widget=QGroupBox(title);layout=QVBoxLayout(widget);layout.setSpacing(8);return widget,layout


def install_compact(d):
    d._compact_busy=True;d._surface_catalog=dict(domains=[],rods=[],sides=[]);d._heat_cache={};d._pairs=[];d._internal_choices={};d._heat_signature=None;d._heat_drafts={}
    d._compact_stash=QWidget(d);d._compact_stash.hide()
    for index in (0,1):
        layout=d.tabs.widget(index).widget().layout()
        while layout.count():
            item=layout.takeAt(0)
            if item.widget():item.widget().setParent(d._compact_stash)
    mesh=d.tabs.widget(0).widget().layout();physics=d.tabs.widget(1).widget().layout()
    d.setWindowTitle('Подготовка расчёта · STAR-CCM+');d.resize(1080,850)
    d.chk_group_objects.setText('Папки объектов');d.chk_group_objects.show()
    files=QHBoxLayout();files.addWidget(QLabel('Plot3D'));d.edit_xyz.setMaximumWidth(250);files.addWidget(d.edit_xyz)
    files.addWidget(d.file_size_label);files.addStretch();files.addWidget(d.chk_group_objects);mesh.addLayout(files)
    d.file_size_label.setText(d.file_size_label.text().split('\n')[0]);d.file_size_label.setWordWrap(False);d.file_size_label.setToolTip('Оценка объёма ASCII-файла на диске, не оперативной памяти. Общие узлы записываются для каждого блока отдельно.')
    d.chk_import.show();mesh.addWidget(d.chk_import)
    splitter=QSplitter(Qt.Horizontal);mesh.addWidget(splitter,1)
    controls=QWidget();cl=QVBoxLayout(controls);cl.setContentsMargins(0,0,6,0);splitter.addWidget(controls)
    topology,tl=box('Топология');cl.addWidget(topology)
    form=QFormLayout();tl.addLayout(form)
    d.topology_choice=QComboBox();d.topology_choice.addItem('Отдельные регионы · интерфейсы','interfaces');d.topology_choice.addItem('Fuse · один регион','fuse')
    d.rod_choice=QComboBox();d.rod_choice.addItem('Сектора 60°','sectors_60');d.rod_choice.addItem('По физическому стержню','by_rod');d.rod_choice.addItem('По подканалу','monolithic')
    form.addRow(label_help('Подканалы','Внутри подканала конформные блоки объединяются. Неконформный импорт пока запрещён.'),d.topology_choice)
    form.addRow(label_help('Стенки','Цвета и имена на схеме соответствуют группам стенок. ТВЭЛ, НК и ИК не смешиваются при группировке.'),d.rod_choice)
    for w in (d.rb_inter_intf,d.rb_inter_fuse,d.rb_wall_60,d.rb_wall_by_rod,d.rb_wall_rod):w.hide()
    d.boundary_hint.show();d.boundary_hint.setWordWrap(True);tl.addWidget(d.boundary_hint)
    pairs,pl=box('Граничные поверхности');cl.addWidget(pairs)
    d.surface_a=QComboBox();d.surface_b=QComboBox();d.surface_condition=QComboBox()
    d.surface_condition.addItem('Periodic · перенос','periodic_translation');d.surface_condition.addItem('Internal · соседние подканалы ниже','internal');d.surface_condition.model().item(1).setEnabled(False)
    form=QFormLayout();pl.addLayout(form)
    form.addRow('Первая',d.surface_a);form.addRow('Вторая',d.surface_b);form.addRow(label_help('Условие','Это физические границы, не измерительные сечения. Для Periodic проверяется совпадение формы после переноса. Вращательная периодичность пока не поддерживается.'),d.surface_condition)
    add=QPushButton('Добавить пару');pl.addWidget(add)
    d.surface_pairs_table=QTableWidget(0,3);d.surface_pairs_table.setHorizontalHeaderLabels(['Первая','Вторая','Условие']);d.surface_pairs_table.setEditTriggers(QTableWidget.NoEditTriggers)
    d.surface_pairs_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);d.surface_pairs_table.setMaximumHeight(170);pl.addWidget(d.surface_pairs_table)
    remove=QPushButton('Удалить выбранную пару');pl.addWidget(remove)
    d.internal_table=QTableWidget(0,2);d.internal_table.setHorizontalHeaderLabels(['Соседние подканалы','Условие']);d.internal_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch);d.internal_table.setMaximumHeight(130);pl.addWidget(d.internal_table)
    d.surface_status=QLabel();d.surface_status.setWordWrap(True);pl.addWidget(d.surface_status);cl.addStretch()
    preview=QWidget();pv=QVBoxLayout(preview);pv.setContentsMargins(0,0,0,0);splitter.addWidget(preview)
    pv.addWidget(label_help('Разбиение модели · вид вдоль Z','Нажмите на стенку: её группа выделится в таблице нагрева. Нажмите на внешнюю сторону: она станет первой/второй поверхностью пары. Пунктир после Fuse — исходный стык, не граничная поверхность.'))
    d.surface_preview=SurfacePreview();pv.addWidget(d.surface_preview,1)
    d.preview_selection=QLabel('Выберите поверхность на схеме');d.preview_selection.setWordWrap(True);pv.addWidget(d.preview_selection)
    splitter.setSizes([420,620])
    # Physics in two compact columns; long text is available through ?.
    columns=QHBoxLayout();physics.addLayout(columns)
    left=QWidget();ll=QVBoxLayout(left);ll.setContentsMargins(0,0,0,0);columns.addWidget(left,1)
    right=QWidget();rl=QVBoxLayout(right);rl.setContentsMargins(0,0,0,0);columns.addWidget(right,1)
    mode,ml=box('Режим расчёта');ll.addWidget(mode);form=QFormLayout();ml.addLayout(form)
    d.simulation_mode=QComboBox();d.simulation_mode.addItem('Стационарный','steady');d.simulation_mode.addItem('Нестационарный','unsteady')
    d.turbulence_choice=QComboBox();d.turbulence_choice.addItem('RST','rst');d.turbulence_choice.addItem('Hybrid SRH–SST','hybrid_srh')
    form.addRow('Режим',d.simulation_mode);form.addRow(label_help('Турбулентность','Hybrid SRH–SST требует нестационарного режима. RST доступен в стационарном и нестационарном режиме.'),d.turbulence_choice)
    for w in (d.rb_turb_rst,d.rb_turb_srh):w.hide()
    material,fl=box('Свойства жидкости');ll.addWidget(material);form=QFormLayout();fl.addLayout(form)
    d.property_choice=QComboBox();d.property_choice.addItem('Постоянные · из y+','constant');d.property_choice.addItem('IAPWS','iapws');form.addRow('Свойства',d.property_choice)
    d.constant_properties=QWidget();pg=QGridLayout(d.constant_properties);pg.setContentsMargins(0,0,0,0);fl.addWidget(d.constant_properties)
    specs=(('density','ρ','кг/м³'),('dyn_vis','μ','Па·с'),('cp','Cp','Дж/(кг·К)'),('lambda','λ','Вт/(м·К)'))
    for i,(key,symbol,unit) in enumerate(specs):
        row=i//2;col=(i%2)*3;pg.addWidget(QLabel(symbol),row,col);pg.addWidget(compact_field(d.fluid_fields[key]),row,col+1);pg.addWidget(QLabel(unit),row,col+2)
    d.iapws_transport=QWidget();it=QFormLayout(d.iapws_transport);it.setContentsMargins(0,0,0,0);fl.addWidget(d.iapws_transport)
    it.addRow(label_help('Вязкость','При константе используется μ из калькулятора y+. Метод IAPWS зависит от локального состояния воды.'),d.viscosity_method)
    it.addRow(label_help('Теплопроводность','При константе используется λ из калькулятора y+.'),d.conductivity_method)
    d.viscosity_method.show();d.conductivity_method.show()
    d.sync_fluid_button=QPushButton('Обновить из y+');fl.addWidget(d.sync_fluid_button)
    d.chk_thermal.setText('Уравнение энергии');d.chk_thermal.show();energy_row=QHBoxLayout();energy_row.addWidget(d.chk_thermal);energy_row.addWidget(help_button('Segregated Fluid Temperature. При IAPWS энергия обязательна. Для задания ненулевого теплового потока включите энергию.'));energy_row.addStretch();fl.addLayout(energy_row)
    for w in (d.rb_eos_const,d.rb_eos_iapws):w.hide()
    ref,rfl=box('Опорные значения');rl.addWidget(ref);form=QFormLayout();rfl.addLayout(form)
    form.addRow('Давление, МПа',compact_field(d.fluid_fields['p_ref_mpa']));form.addRow('Температура, °C',compact_field(d.fluid_fields['t_ref_c']))
    gravity=QHBoxLayout();d.chk_gravity.setText('Гравитация');gravity.addWidget(d.chk_gravity);gravity.addWidget(d.combo_gravity);gravity.addWidget(help_button('Ось и направление в лабораторной системе. Модуль ускорения 9,81 м/с².'));gravity.addStretch();rfl.addLayout(gravity);d.chk_gravity.show();d.combo_gravity.show()
    initial,il=box('Начальные условия');rl.addWidget(initial);form=QFormLayout();il.addLayout(form)
    form.addRow('Температура, K',compact_field(d.initial_temperature));form.addRow(label_help('Давление, Па','Избыточное относительно опорного. Абсолютное давление — их сумма.'),compact_field(d.initial_pressure));form.addRow('Скорость',d.initial_velocity);d.initial_velocity.show();d.initial_absolute.show();il.addWidget(d.initial_absolute)
    il.addWidget(label_help('Начальные функции · автоматически','Создаются pi, Apert, thetaZ, seedX, seedY, VelocitySeed и относительная высота. Назначение выбирается в поле «Скорость»: нулевая, осевая или VelocitySeed.'))
    d.seed_functions.setChecked(True);d.seed_functions.hide();d.field_checkboxes['z_fraction'].setChecked(True)
    if isinstance(d.field_checkboxes['z_fraction'].parentWidget(),QGroupBox):d.field_checkboxes['z_fraction'].parentWidget().hide()
    ll.addStretch();rl.addStretch()
    heat,hl=box('Тепловой поток на ТВЭЛ');physics.addWidget(heat)
    d.heat_enabled=QCheckBox('Задать тепловой поток');hl.addWidget(d.heat_enabled)
    d.heat_table=QTableWidget(0,3);d.heat_table.setHorizontalHeaderLabels(['Параметр','Группа стенок','q, Вт/м²']);d.heat_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch);d.heat_table.setMaximumHeight(240);hl.addWidget(d.heat_table)
    hl.addWidget(label_help('Соответствие q и стенок','Список следует группировке на вкладке «Сетка». Создаются параметры qN и функции HeatFlux_qN. В нагрев входят только ТВЭЛ, НК и ИК исключены. Положительный q нагревает жидкость. Для TDC все сектора одного подканала должны иметь одинаковый q.'))
    d.heat_status=QLabel();d.heat_status.setWordWrap(True);hl.addWidget(d.heat_status)
    physics.addStretch()
    # Existing reference controls remain aliases for old profile imports, not a second input form.
    for key in ('heat_flux_1','heat_flux_2'):d.tmc_fields[key].hide()
    d._compact_sync_props_signature=None
    def source_properties():
        parent=d.parent();panel=getattr(parent,'mesh_subpanel',None)
        values=getattr(panel,'current_fluid_props',None)
        return values if values else d.fluid_props
    def sync_fluid(force=False):
        source=source_properties();panel=getattr(d.parent(),'mesh_subpanel',None);yp=getattr(panel,'last_yplus_result',None)
        signature=(tuple((key,source.get(key)) for key in d.fluid_fields),repr(yp))
        if not force and signature==d._compact_sync_props_signature:return
        from starccm_workflow import validate_workflow
        values={key:source[key] for key in d.fluid_fields if key in source}
        try:validate_workflow({'fluid':values})
        except ValueError:return
        for key,value in values.items():d.fluid_fields[key].setValue(value)
        if yp:
            from yplus_calculator import export_yplus_data
            d.yplus_data=export_yplus_data(yp,default_h1=getattr(getattr(d.mesh_result,'params',None),'h1',2.5e-6))
        d._compact_sync_props_signature=signature
    d.sync_fluid_properties=sync_fluid;d.sync_fluid_button.clicked.connect(lambda:sync_fluid(True))
    d.fluid_sync_timer=QTimer(d);d.fluid_sync_timer.setInterval(500);d.fluid_sync_timer.timeout.connect(lambda:sync_fluid() if d.isVisible() else None);d.fluid_sync_timer.start();d.finished.connect(d.fluid_sync_timer.stop)
    # Surface and heat data are rebuilt only when grouping/topology changes.
    def rebuild_catalog():
        try:d._surface_catalog=surface_catalog(d.mesh_result,d.bundle_model,d.rod_choice.currentData())
        except (ValueError,TypeError,AttributeError):d._surface_catalog=dict(domains=[],rods=[],sides=[])
        d.surface_preview.draw_catalog(d._surface_catalog,d.rb_inter_fuse.isChecked())
        old={key:combo.currentData() for key,combo in getattr(d,'_internal_combos',{}).items()};d._internal_choices.update(old);d._internal_combos={}
        d.internal_table.setRowCount(0);seen=set()
        for row in d._surface_catalog['sides']:
            key=row['pair_id']
            if not key or key in seen:continue
            seen.add(key);i=d.internal_table.rowCount();d.internal_table.insertRow(i)
            item=QTableWidgetItem(f"Sub{row['source']} ↔ Sub{row['neighbor']}");item.setFlags(item.flags()&~Qt.ItemIsEditable);item.setToolTip(key);d.internal_table.setItem(i,0,item)
            choice=QComboBox();choice.addItem('Internal','internal');choice.addItem('Wall · не соединять','wall');choice.setCurrentIndex(1 if d._internal_choices.get(key)=='wall' else 0);d.internal_table.setCellWidget(i,1,choice);d._internal_combos[key]=choice
        d.internal_table.setVisible(not d.rb_inter_fuse.isChecked())
        previous=(d.surface_a.currentData(),d.surface_b.currentData())
        for combo in (d.surface_a,d.surface_b):
            combo.clear()
            for row in d._surface_catalog['sides']:
                if not row['shared']:combo.addItem(row['id'],row['id'])
        for combo,key in zip((d.surface_a,d.surface_b),previous):
            if key is not None:combo.setCurrentIndex(max(0,combo.findData(key)))
        if previous[1] is None and d.surface_b.count()>1:d.surface_b.setCurrentIndex(1)
        rebuild_heat()
    def rebuild_heat():
        d._heat_drafts.update({key:field.text() for key,field in getattr(d,'_heat_fields',{}).items()})
        current={key:field.model.raw for key,field in getattr(d,'_heat_fields',{}).items()}
        d._heat_cache.update(current);d._heat_fields={};d.heat_table.setRowCount(0)
        for i,row in enumerate(r for r in d._surface_catalog['rods'] if r['kind']=='fuel'):
            key=row['id'];default=d.tmc_fields['heat_flux_2'].model.raw if d.tdc_enabled.isChecked() and row['sources']==[2] else (d.tmc_fields['heat_flux_1'].model.raw if d.tdc_enabled.isChecked() else 10000.)
            value=d._heat_cache.get(key,default)
            if d.tdc_enabled.isChecked() and key not in d._edited_heat_keys:value=default
            field=NumberField(value,minimum=0)
            if key in d._heat_drafts and (not d.tdc_enabled.isChecked() or key in d._edited_heat_keys):field.setText(d._heat_drafts[key])
            field.setMaximumWidth(145);field.edited.connect(lambda k=key:d._edited_heat_keys.add(k));d._heat_fields[key]=field
            d.heat_table.insertRow(i);name=QTableWidgetItem(f'q{i+1}');name.setFlags(name.flags()&~Qt.ItemIsEditable);target=QTableWidgetItem(key);target.setFlags(target.flags()&~Qt.ItemIsEditable)
            d.heat_table.setItem(i,0,name);d.heat_table.setItem(i,1,target);d.heat_table.setCellWidget(i,2,field)
        d.heat_table.setFixedHeight(min(240,35+32*d.heat_table.rowCount()));d.heat_table.setEnabled(d.heat_enabled.isChecked());d.heat_table.setVisible(d.heat_enabled.isChecked());d.heat_status.setText(f'Групп ТВЭЛ: {len(d._heat_fields)}. НК и ИК не нагреваются.')
    d._edited_heat_keys=set()
    def refresh_pairs():
        remove.setEnabled(bool(d._pairs))
        d.surface_pairs_table.setRowCount(len(d._pairs))
        for i,row in enumerate(d._pairs):
            for j,key in enumerate(('first','second','kind')):d.surface_pairs_table.setItem(i,j,QTableWidgetItem(row[key]))
    def add_pair():
        pair=dict(first=d.surface_a.currentData(),second=d.surface_b.currentData(),kind=d.surface_condition.currentData())
        try:validate_pairs(d._pairs+[pair],d._surface_catalog)
        except (ValueError,TypeError) as exc:d.surface_status.setText(str(exc));return
        d._pairs.append(pair);refresh_pairs();d.surface_status.setText('Пара добавлена. После импорта проверьте ориентацию и преобразование Periodic в STAR.')
    def remove_pair():
        i=d.surface_pairs_table.currentRow()
        if 0<=i<len(d._pairs):d._pairs.pop(i);refresh_pairs()
    add.clicked.connect(add_pair);remove.clicked.connect(remove_pair)
    d.add_surface_pair=add_pair
    def picked(key):
        d.surface_preview.highlight(key);d.preview_selection.setText(key)
        if key in d._heat_fields:
            rows=list(d._heat_fields);d.heat_table.selectRow(rows.index(key));return
        if d.surface_a.findData(key)>=0:
            combo=d.surface_b if getattr(d,'_pick_second',False) else d.surface_a;combo.setCurrentIndex(combo.findData(key));d._pick_second=not getattr(d,'_pick_second',False)
    d.surface_preview.surfacePicked.connect(picked)
    for combo in (d.surface_a,d.surface_b):combo.currentIndexChanged.connect(lambda _=0,c=combo:d.surface_preview.highlight(c.currentData()) if not d._compact_busy else None)
    d.heat_table.itemSelectionChanged.connect(lambda:d.surface_preview.highlight(list(d._heat_fields)[d.heat_table.currentRow()]) if 0<=d.heat_table.currentRow()<len(d._heat_fields) else None)
    def choices_changed():
        if d._compact_busy:return
        d._compact_busy=True
        try:
            if d.simulation_mode.currentData()=='steady' and d.turbulence_choice.currentData()=='hybrid_srh':
                d.turbulence_choice.setCurrentIndex(0)
            hybrid=d.turbulence_choice.currentData()=='hybrid_srh'
            (d.rb_turb_srh if hybrid else d.rb_turb_rst).setChecked(True)
            (d.rb_inter_fuse if d.topology_choice.currentData()=='fuse' else d.rb_inter_intf).setChecked(True)
            {'sectors_60':d.rb_wall_60,'by_rod':d.rb_wall_by_rod,'monolithic':d.rb_wall_rod}[d.rod_choice.currentData()].setChecked(True)
            (d.rb_eos_iapws if d.property_choice.currentData()=='iapws' else d.rb_eos_const).setChecked(True)
            d._workflow['run_mode']=d.simulation_mode.currentData()
        finally:d._compact_busy=False
        from starccm_unified_ui import refresh
        refresh(d)
    for combo in (d.topology_choice,d.rod_choice,d.simulation_mode,d.turbulence_choice,d.property_choice):combo.currentIndexChanged.connect(choices_changed)
    d.heat_enabled.toggled.connect(lambda checked:(d.heat_table.setEnabled(checked),d.heat_table.setVisible(checked)))
    def compact_refresh():
        if d._compact_busy:return
        d._compact_busy=True
        try:
            hybrid=d.rb_turb_srh.isChecked();mode=d._workflow.get('run_mode','auto')
            if mode=='auto':mode='unsteady' if hybrid else 'steady'
            if hybrid:mode='unsteady'
            d.simulation_mode.setCurrentIndex(d.simulation_mode.findData(mode));d.turbulence_choice.setCurrentIndex(1 if hybrid else 0)
            d.turbulence_choice.model().item(1).setEnabled(mode=='unsteady')
            d.topology_choice.setCurrentIndex(1 if d.rb_inter_fuse.isChecked() else 0)
            rod='sectors_60' if d.rb_wall_60.isChecked() else 'by_rod' if d.rb_wall_by_rod.isChecked() else 'monolithic'
            d.rod_choice.model().item(1).setEnabled(d.rb_inter_fuse.isChecked());d.rod_choice.setCurrentIndex(d.rod_choice.findData(rod))
            iapws=d.rb_eos_iapws.isChecked();d.property_choice.setCurrentIndex(1 if iapws else 0)
            d.constant_properties.setVisible(not iapws);d.iapws_transport.setVisible(iapws)
            d.heat_table.setEnabled(d.heat_enabled.isChecked());d.heat_table.setVisible(d.heat_enabled.isChecked())
            for w in (d.surface_a,d.surface_b,d.surface_condition,add):w.setEnabled(not d.tdc_enabled.isChecked())
            remove.setEnabled(bool(d._pairs))
            if d.tdc_enabled.isChecked():d.surface_status.setText('Боковые пары эталона TDC назначаются контроллером.')
            signature=(rod,d.rb_inter_fuse.isChecked(),d.tdc_enabled.isChecked())
            if signature!=d._heat_signature:
                changed_grouping=d._heat_signature is not None and d._heat_signature[0]!=signature[0]
                d._heat_signature=signature;rebuild_catalog()
                if changed_grouping:d.heat_status.setText(d.heat_status.text()+' Группировка изменена — проверьте значения q.')
            for w in (d.inner_iterations,d.field_time_step,d.warmup_duration,d.block_duration,d.blocks_per_run,d.mean_group):w.setEnabled(mode=='unsteady')
            d.summary_text.appendPlainText('Нагрев ТВЭЛ: '+('включён' if d.heat_enabled.isChecked() else 'не назначается'))
            if d.heat_enabled.isChecked():
                for i,(key,field) in enumerate(d._heat_fields.items(),1):d.summary_text.appendPlainText(f'q{i}: {key} = {field.text()} Вт/м²')
            d.summary_text.appendPlainText(f'Дополнительных внешних пар: {len(d._pairs)}')
        finally:d._compact_busy=False
    def compact_workflow():
        values={key:field.value() if d.heat_enabled.isChecked() else field.model.raw for key,field in d._heat_fields.items()}
        return dict(run_mode=d.simulation_mode.currentData(),heat_enabled=d.heat_enabled.isChecked(),heat_values=values,boundary_pairs=deepcopy(d._pairs),disabled_internal_pairs=[key for key,combo in d._internal_combos.items() if combo.currentData()=='wall'] if not d.rb_inter_fuse.isChecked() else [],velocity_seed=True)
    def apply_compact(values):
        d._heat_fields={};d._heat_cache=dict(values.get('heat_values',{}));d._heat_drafts={};d._edited_heat_keys=set(d._heat_cache)
        d._internal_choices={key:'wall' for key in values.get('disabled_internal_pairs',[])};d._internal_combos={}
        d._pairs=deepcopy(values.get('boundary_pairs',[]));d.heat_enabled.setChecked(values.get('heat_enabled',False))
        d._heat_signature=None;compact_refresh();refresh_pairs()
    d._compact_workflow=compact_workflow;d._compact_apply=apply_compact;d._compact_refresh=compact_refresh
    d._compact_busy=False;compact_refresh();sync_fluid()
    d.setStyleSheet(d.styleSheet()+'''
        QGroupBox { border: 1px solid palette(mid); border-radius: 6px; margin-top: 10px; padding: 9px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
        QComboBox, QLineEdit, QSpinBox { min-height: 23px; padding: 2px 5px; }
        QTabBar::tab { padding: 7px 12px; }
        QToolButton { border: 1px solid palette(mid); border-radius: 10px; color: palette(highlight); }
        QHeaderView::section { padding: 5px; }
    ''')
    # Keep all numeric controls compact, including the remaining tabs.
    for field in d.findChildren(NumberField):field.setMaximumWidth(145)
