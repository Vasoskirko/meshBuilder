"""Select one target and explicitly account for every other lateral energy path."""
from copy import deepcopy
import re
from PySide6.QtWidgets import QWidget,QVBoxLayout,QFormLayout,QComboBox,QLabel,QCheckBox,QPushButton,QTableWidget,QTableWidgetItem,QLineEdit,QHeaderView,QAbstractItemView
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from starccm_compact_ui import box,label_help
from starccm_tdc_plan import TDC_DEFAULTS,validate_tdc
from starccm_tdc_paths import side_paths,target_connections,channel_labels
from number_field import NumberField
from starccm_tdc_connections_ui import KINDS,fill_overview

CHOICES=dict(boundary='Измерить на границе',reconstruct='Реконструкция · приближённо',report='Готовый отчёт мощности',unmeasured='Не измерено',zero='Нулевой поток',target='Остаток баланса · целевой')


def install(d):
    page=d.tabs.widget(6).widget();layout=page.layout();stash=QWidget(d);stash.hide();d._tdc_stash=stash
    while layout.count():
        item=layout.takeAt(0)
        if item.widget():item.widget().setParent(stash)
    d.tdc_parts_required=QLabel('TDC: сечения выбранных A/B обязательны; внутренние плоскости общие, вход/выход — стороны интерфейса.')
    d.tdc_parts_required.setWordWrap(True);d.tabs.widget(2).widget().layout().insertWidget(0,d.tdc_parts_required)
    d.tdc_reports_required=QLabel('TDC: нагрев, сток, запас энергии, осевые и боковые потоки создаются обязательно. Средние выбранных дополнительных отчётов сохраняются вместе с ними.')
    d.tdc_reports_required.setWordWrap(True);d.tabs.widget(3).widget().layout().insertWidget(0,d.tdc_reports_required)
    layout.addWidget(d.tdc_enabled);d.tdc_enabled.setText('Создавать TDC выбранного соединения')
    d.tdc_equivalence.hide()  # Legacy profile key only; never a physical assumption.
    d.tdc_controls=QWidget();body=QVBoxLayout(d.tdc_controls);body.setContentsMargins(0,0,0,0);layout.addWidget(d.tdc_controls)
    group,gl=box('Контрольные подканалы и целевой зазор');body.addWidget(group);form=QFormLayout();gl.addLayout(form)
    d.tdc_a=QComboBox();d.tdc_b=QComboBox()
    for n in range(1,d.sub_count+1):
        for combo in (d.tdc_a,d.tdc_b):combo.addItem(f'Подканал {n}',n)
    for combo in (d.tdc_a,d.tdc_b):combo.setMaximumWidth(480)
    d.tdc_b.setCurrentIndex(min(1,d.sub_count-1));form.addRow('Подканал A · выбери горячий',d.tdc_a);form.addRow('Подканал B',d.tdc_b)
    d.tdc_composition=QLabel();d.tdc_composition.setWordWrap(True);gl.addWidget(d.tdc_composition)
    d.tdc_target=QComboBox();form.addRow(label_help('Целевое соединение','Для него определяется остаток баланса. При нескольких соединениях A–B выбирается одно; остальные измеряются отдельно. Эквивалентность зазоров не предполагается.'),d.tdc_target)
    d.tdc_area_hint=QLabel();gl.addWidget(d.tdc_area_hint)
    preview=QPushButton('Показать целевой зазор в «Сетке»');gl.addWidget(preview)
    paths,pl=box('Теплообмен через боковые стороны');body.addWidget(paths)
    d.tdc_mapping=QLabel();d.tdc_mapping.setWordWrap(True);pl.addWidget(d.tdc_mapping)
    d.tdc_connections=QTableWidget(0,4);d.tdc_connections.setHorizontalHeaderLabels(['Что учитываем','Подканалы','Условие','Роль в балансе'])
    d.tdc_connections.setSelectionBehavior(QAbstractItemView.SelectRows);d.tdc_connections.setSelectionMode(QAbstractItemView.SingleSelection);d.tdc_connections.setMaximumHeight(280);pl.addWidget(d.tdc_connections)
    d.tdc_connection_details=QLabel();d.tdc_connection_details.setWordWrap(True);d.tdc_connection_details.setTextFormat(Qt.PlainText)
    show_side=QPushButton('Показать выбранное соединение в «Сетке»');pl.addWidget(show_side)
    d.tdc_details_toggle=QCheckBox('Подробности: поверхности и способы измерения');pl.addWidget(d.tdc_details_toggle)
    d.tdc_details_panel=QWidget();details_layout=QVBoxLayout(d.tdc_details_panel);details_layout.setContentsMargins(0,0,0,0);pl.addWidget(d.tdc_details_panel);d.tdc_details_panel.hide()
    details_layout.addWidget(d.tdc_connection_details)
    explanation=QLabel('Настройки ниже относятся к отдельным сторонам. Положительная мощность направлена наружу из указанного подканала. Поле отчёта нужно только для способа «Готовый отчёт мощности».');explanation.setWordWrap(True);details_layout.addWidget(explanation)
    d.tdc_details_toggle.toggled.connect(d.tdc_details_panel.setVisible)
    d.tdc_paths_table=QTableWidget(0,5);d.tdc_paths_table.setHorizontalHeaderLabels(['Объём','Поверхность / сосед','Условие','Учёт','Отчёт, Вт'])
    d.tdc_paths_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch);d.tdc_paths_table.setMinimumHeight(220);d.tdc_paths_table.setMaximumHeight(255);details_layout.addWidget(d.tdc_paths_table)
    d.tdc_paths_table.setToolTip('Знак каждой мощности — наружу из указанного подканала. На каждый контрольный объём допускается один неизвестный перенос: целевой.')
    d.tdc_reconstruction=QCheckBox('Для реконструкции: подтверждаю скалярное замыкание диффузии и проверку баланса')
    d.tdc_reconstruction.setToolTip('Используется EffectiveConductivity·grad(T), не Boundary Heat Flux на сечении. Это постобработочная реконструкция, а не точный численный поток по граням.');details_layout.addWidget(d.tdc_reconstruction)
    d.tdc_components=QCheckBox('Молекулярный и полный адвективный перенос через целевой зазор');d.tdc_components.setChecked(True)
    d.tdc_components.setToolTip('Молекулярный: −λ∫grad(T)·n dS. Адвективный: ρCp∫(T−T_init)u_n dS, включая разрешённые пульсации. Его среднее не равно переносу средним течением. Остаток после вычитания молекулярного переноса не объявляется чисто турбулентным.');pl.addWidget(d.tdc_components)
    method,ml=box('Определение и усреднение');body.addWidget(method);mf=QFormLayout();ml.addLayout(mf)
    mf.addRow(label_help('Температурная разность','На шаге: T_b=∫ρu_zT/∫ρu_z, затем трапецеидальное усреднение по длине и среднее по времени. Более высокий q не гарантирует, что A горячее: проверь фактическую ΔT после разгона.'),QLabel('ΔT = T_A − T_B; потоковые, средние по длине'))
    d.tdc_sections_hint=QLabel();mf.addRow('Сечения',d.tdc_sections_hint)
    parts=QPushButton('Настроить сечения');parts.clicked.connect(lambda:d.tabs.setCurrentIndex(2));mf.addRow('',parts)
    d.tdc_g_ref=QLabel();mf.addRow(label_help('Опорный массовый поток','Общий аналитический G=ρU_b из калькулятора y+. Определение G сохраняется; это не равенство фактических скоростей разных подканалов.'),d.tdc_g_ref)
    mf.addRow(label_help('Минимальная |ΔT|, K','Ниже порога коэффициент не публикуется; средние и исходные данные сохраняются.'),d.tmc_fields['min_delta_t']);d.tmc_fields['min_delta_t'].show()
    d.tdc_balance_tol=NumberField(.05,minimum=1e-12,maximum=1.);d.tdc_balance_tol.setMaximumWidth(120)
    mf.addRow(label_help('Допуск баланса, доля','Проверяются два остатка для целевого соединения и согласованность измеренных парных интерфейсов. Это не статистическая погрешность.'),d.tdc_balance_tol)
    d.tdc_blocks=QCheckBox('Сохранять отдельные блочные результаты');d.tdc_blocks.setChecked(True);ml.addWidget(d.tdc_blocks)
    d.tdc_time_hint=QLabel('Поля и время — из вкладки 5. Общий TDC — отношение средних по общей истории; не среднее блочных отношений.');d.tdc_time_hint.setWordWrap(True);ml.addWidget(d.tdc_time_hint)
    timing=QPushButton('Настроить средние поля и время');timing.clicked.connect(lambda:d.tabs.setCurrentIndex(4));ml.addWidget(timing)
    explanation=QLabel('Q_целевой = Q_нагрев + Q_сток − Q_осевой − ΔH/Δt − ΣQ_прочих\nTDC = Q̄_целевой / (A_целевой · Cp · G · ΔT̄)\nНагрев и компенсационный сток — общие настройки. Результат безразмерный, эффективный; BMBC и выделения чисто турбулентной составляющей нет.');explanation.setWordWrap(True);ml.addWidget(explanation)
    d.tdc_status.setParent(None);body.addWidget(d.tdc_status);d.tdc_status.show();body.addStretch()
    d._tdc_rows=[];d._tdc_methods={};d._tdc_reports={};d._tdc_target_id='';d._tdc_busy=False
    def stash_paths():
        for i,p in enumerate(d._tdc_rows):
            if p['connection']==d._tdc_target_id:continue
            combo=d.tdc_paths_table.cellWidget(i,3);text=d.tdc_paths_table.cellWidget(i,4)
            if combo is None or combo.currentData()=='target':continue
            choice=combo.currentData()
            if choice==p['default']:d._tdc_methods.pop(p['id'],None)
            else:d._tdc_methods[p['id']]=choice
            if text.text().strip():d._tdc_reports[p['id']]=text.text().strip()
            else:d._tdc_reports.pop(p['id'],None)
    def update_status():
        unresolved=[p['id'] for i,p in enumerate(d._tdc_rows) if d.tdc_paths_table.cellWidget(i,3) is not None and d.tdc_paths_table.cellWidget(i,3).currentData()=='unmeasured']
        if d._tdc_rows:
            stash_paths();fill_overview(d,d._tdc_rows,d.tdc_a.currentData(),d.tdc_b.currentData(),d._tdc_target_id)
        d.tdc_status.setText(f'Не задано измерение для {len(unresolved)} сторон. Откройте «Подробности» и выберите способ учёта.' if unresolved else 'Целевой поток определяется отдельно. Перед сбором проверь доступность боковых потоков и фактическую ΔT.')
    def refresh():
        if d._tdc_busy:return
        d._tdc_busy=True
        try:
            stash_paths();d.tdc_parts_required.setVisible(d.tdc_enabled.isChecked());d.tdc_reports_required.setVisible(d.tdc_enabled.isChecked())
            if not hasattr(d,'_surface_catalog'):return
            cat=d._surface_catalog;a,b=d.tdc_a.currentData(),d.tdc_b.currentData()
            d.tdc_mapping.setText(f'A = Подканал {a}; B = Подканал {b}. Один открытый обмен — одна строка. Вход/выход учитываются отдельно в осевом балансе.')
            heat={k:f.model.raw for k,f in getattr(d,'_heat_fields',{}).items()}
            if d.mesh_result is not None and d.bundle_model is not None and hasattr(d.mesh_result,'instances_map'):
                info=channel_labels(d.mesh_result,d.bundle_model,cat,heat)
                for n,data in info.items():
                    for combo in (d.tdc_a,d.tdc_b):combo.setItemText(combo.findData(n),data['title'])
                d.tdc_composition.setText('A: '+info.get(a,{}).get('details','')+'\nB: '+info.get(b,{}).get('details',''))
            workflow=dict(d._workflow,boundary_pairs=getattr(d,'_pairs',[]),boundary_conditions=getattr(d,'_conditions',[]),disabled_internal_pairs=[k for k,c in getattr(d,'_internal_combos',{}).items() if c.currentData()=='wall'])
            allpaths=side_paths(cat,workflow);candidates=target_connections(allpaths,a,b)
            d.tdc_target.clear()
            for p in candidates:
                rods='–'.join('R'+n for n in re.findall(r'R(\d+)',p['id']))
                d.tdc_target.addItem(f'{KINDS[p["kind"]]} · Подканал {a} ↔ Подканал {b} · {rods}',p['connection'])
                d.tdc_target.setItemData(d.tdc_target.count()-1,p['connection'],Qt.ToolTipRole)
            index=d.tdc_target.findData(d._tdc_target_id);d.tdc_target.setCurrentIndex(index if index>=0 else (0 if candidates else -1));d._tdc_target_id=d.tdc_target.currentData() or ''
            chosen=next((p for p in candidates if p['connection']==d._tdc_target_id),None)
            d.tdc_area_hint.setText(f'Площадь целевого соединения: {chosen["area"]:.6g} м² · нормаль из A' if chosen else 'Нет открытого соединения между выбранными A и B')
            for i in range(d.tdc_paths_table.rowCount()):
                for j in (3,4):
                    old=d.tdc_paths_table.cellWidget(i,j)
                    if old is not None:old.hide()
            d.tdc_paths_table.clearContents()
            d._tdc_rows=[p for p in allpaths if p['source'] in (a,b)];d.tdc_paths_table.setRowCount(len(d._tdc_rows))
            unresolved=[]
            for i,p in enumerate(d._tdc_rows):
                for j,text in enumerate(('A' if p['source']==a else 'B',p['id']+(f' → Sub{p["neighbor"]}' if p['neighbor'] else ''),KINDS.get(p['kind'],p['kind']))):
                    item=QTableWidgetItem(text);item.setFlags(item.flags()&~Qt.ItemIsEditable);d.tdc_paths_table.setItem(i,j,item)
                combo=QComboBox();target=p['connection']==d._tdc_target_id
                allowed=('target',) if target else ('zero',) if p['default']=='zero' else ('unmeasured','reconstruct','report') if p['kind']=='fuse' else ('boundary','report','unmeasured')
                for key in allowed:combo.addItem(CHOICES[key],key)
                mode='target' if target else d._tdc_methods.get(p['id'],p['default']);idx=combo.findData(mode);combo.setCurrentIndex(idx if idx>=0 else 0)
                combo.setEnabled(len(allowed)>1);d.tdc_paths_table.setCellWidget(i,3,combo)
                entry=QLineEdit(d._tdc_reports.get(p['id'],''));entry.setEnabled(combo.currentData()=='report');entry.setPlaceholderText('Имя отчёта');d.tdc_paths_table.setCellWidget(i,4,entry)
                combo.currentIndexChanged.connect(lambda _,c=combo,e=entry:(e.setEnabled(c.currentData()=='report'),update_status()))
                if combo.currentData()=='unmeasured':unresolved.append(p['id'])
            d.tdc_paths_table.resizeColumnsToContents();d.tdc_paths_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
            update_status()
            d.tdc_sections_hint.setText(f'{d.spin_sub_n_planes.value()} общих сечений на подканал; вход/выход — стороны интерфейса')
            try:
                from starccm_flow_defaults import calculator_mass_flow
                cap=next(r for r in cat.get('endcaps',[]) if r['role']=='Inlet');g=calculator_mass_flow(cat,d.read_fluid(),d.yplus_data,cap['id'])/cap['area'];d.tdc_g_ref.setText(f'ρU_b = {g:.6g} кг/(м²·с)')
            except (ValueError,KeyError,StopIteration):d.tdc_g_ref.setText('Проверь геометрию, Re и свойства')
        finally:d._tdc_busy=False
    def target_changed():
        if d._tdc_busy:return
        stash_paths();d._tdc_target_id=d.tdc_target.currentData() or '';refresh()
    def show_surfaces(selected):
        d.tabs.setCurrentIndex(0);view=d.surface_preview;cat=d._surface_catalog;view.set_view_mode('sides');view.draw_catalog(cat,d.rb_inter_fuse.isChecked())
        for r in cat['sides']:
            if r['id'] in selected and r['id'] not in view.items_by_id:view.add_surface(r,QColor('#d62728'),3.)
        view.highlight(selected);d.preview_selection.setText('Боковой обмен TDC: '+', '.join(selected))
    def show_exchange():
        show_surfaces([p['id'] for p in d._tdc_rows if p['connection']==d._tdc_target_id])
    def selected_details():
        row=d.tdc_connections.currentRow()
        item=d.tdc_connections.item(row,0)
        d.tdc_connection_details.setText(item.toolTip() if item else '')
    def show_selected():
        item=d.tdc_connections.item(d.tdc_connections.currentRow(),0)
        if item:show_surfaces(item.data(Qt.UserRole))
    d.tdc_connections.itemSelectionChanged.connect(selected_details);show_side.clicked.connect(show_selected)
    def read():
        stash_paths()
        return validate_tdc(dict(TDC_DEFAULTS,target_components=d.tdc_components.isChecked(),a=d.tdc_a.currentData(),b=d.tdc_b.currentData(),target=d._tdc_target_id,path_methods=deepcopy(d._tdc_methods),path_reports=deepcopy(d._tdc_reports),scalar_diffusion_confirmed=d.tdc_reconstruction.isChecked(),sections=d.spin_sub_n_planes.value(),blocks=d.tdc_blocks.isChecked(),min_delta_t=d.tmc_fields['min_delta_t'].value(),balance_tolerance=d.tdc_balance_tol.value()))
    def apply(v):
        v=validate_tdc(v);d._tdc_busy=True
        try:
            d._tdc_rows=[];d._tdc_methods=deepcopy(v['path_methods']);d._tdc_reports=deepcopy(v['path_reports']);d._tdc_target_id=v['target'] or (v['gaps'][0] if v['gaps'] else '')
            for key,c in (('a',d.tdc_a),('b',d.tdc_b)):c.setCurrentIndex(c.findData(v[key]))
            d.tdc_components.setChecked(v['target_components']);d.tdc_reconstruction.setChecked(v['scalar_diffusion_confirmed']);d.tdc_blocks.setChecked(v['blocks']);d.tdc_balance_tol.setValue(v['balance_tolerance']);d.tmc_fields['min_delta_t'].setValue(v['min_delta_t'])
            if d.tdc_enabled.isChecked():d.spin_sub_n_planes.setValue(v['sections'])
        finally:d._tdc_busy=False
        refresh()
    d._tdc_read=read;d._tdc_apply=apply;d._tdc_refresh=refresh;d._show_tdc_exchange=show_exchange
    for combo in (d.tdc_a,d.tdc_b):combo.currentIndexChanged.connect(refresh)
    d.tdc_target.currentIndexChanged.connect(target_changed);d.spin_sub_n_planes.valueChanged.connect(refresh);preview.clicked.connect(show_exchange);refresh()
