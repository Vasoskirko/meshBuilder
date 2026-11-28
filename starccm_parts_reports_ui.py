"""Separate derived geometry from instantaneous report configuration."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QFormLayout,QGroupBox,
    QListWidget,QListWidgetItem,QComboBox,QSpinBox,QScrollArea,QLabel,QAbstractItemView)
from starccm_compact_ui import label_help,box


def fit_list(widget,maximum):
    # Native styles, font size and display scaling determine the actual row height.
    widget.ensurePolished()
    row=max(widget.fontMetrics().height()+6,widget.sizeHintForRow(0))
    widget.setFixedHeight(min(maximum,2*widget.frameWidth()+row*widget.count()+4))


def install(d):
    d._parts_stash=QWidget(d);d._parts_stash.hide()
    page=d.tabs.widget(2).widget();layout=page.layout()
    while layout.count():
        item=layout.takeAt(0)
        if item.widget():item.widget().setParent(d._parts_stash)
    d.grp_sources.setParent(page);d.grp_sources.hide()
    d.tabs.setTabText(2,'3. Производные части')
    report_page=QWidget();reports=QVBoxLayout(report_page);scroll=QScrollArea();scroll.setWidgetResizable(True);scroll.setWidget(report_page)
    d.tabs.insertTab(3,scroll,'4. Отчёты (Репорты)')
    for index,name in enumerate(('Статистика','Качество','TDC','Итог'),4):d.tabs.setTabText(index,f'{index+1}. {name}')
    targets,tl=box('Области построения');layout.addWidget(targets)
    tl.addWidget(label_help('Для чего создавать плоскости','Отметьте нужные области. Вся модель — единое сечение всех подканалов; выбранные подканалы — отдельные сечения. После Fuse их исходные области выделяются автоматически.'))
    d.parts_targets=QListWidget();d.parts_targets.setSelectionMode(QAbstractItemView.NoSelection);d.parts_targets.setMaximumHeight(200);tl.addWidget(d.parts_targets)
    for number,name in [(0,'Вся модель')]+[(n,f'Подканал {n}') for n in range(1,d.sub_count+1)]:
        item=QListWidgetItem(name,d.parts_targets);item.setData(Qt.UserRole,number);item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(Qt.Unchecked)
    fit_list(d.parts_targets,200)
    planes,pl=box('Поперечные плоскости');layout.addWidget(planes);form=QFormLayout();pl.addLayout(form)
    d.plane_scheme=QComboBox()
    for text,key in (('Не создавать','none'),('Вход и выход · 2 плоскости','ends'),('Вход, середина, выход · 3 плоскости','three'),('Равномерно по высоте · N плоскостей','uniform')):d.plane_scheme.addItem(text,key)
    d.plane_count=QSpinBox();d.plane_count.setRange(2,100);d.plane_count.setMaximumWidth(145)
    form.addRow(label_help('Расположение','Плоскости перпендикулярны Z. Равномерная серия включает Z=0 и Z=L; число N — точное количество, без дополнительных плоскостей в середине. Технические сечения входа/выхода могут понадобиться выбранным отчётам независимо от этого списка.'),d.plane_scheme)
    count_label=QLabel('Количество N');form.addRow(count_label,d.plane_count)
    d.plane_spacing=QLabel();pl.addWidget(d.plane_spacing)
    other,ol=box('Зазоры и зонды');layout.addWidget(other)
    d.chk_gap_sections.setText('Плоскости зазоров между подканалами');ol.addWidget(d.chk_gap_sections)
    ol.addWidget(label_help('Доступные зазоры','Одна продольная измерительная поверхность на каждую соседнюю пару. Она не создаёт стенку или интерфейс. В этом экспорте доступны для Fuse. Площадь измеряется отчётом в STAR, а не задаётся здесь.'))
    d.gap_list=QListWidget();d.gap_list.setSelectionMode(QAbstractItemView.NoSelection);d.gap_list.setMaximumHeight(100);ol.addWidget(d.gap_list)
    for i in range(d.gap_table.rowCount()):
        name=d.gap_table.item(i,0).text();item=QListWidgetItem(name.replace('Gap_Sub','Подканал ').replace('_Sub',' ↔ Подканал '),d.gap_list);item.setToolTip(name)
    if not d.gap_list.count():QListWidgetItem('Соседних зазоров нет',d.gap_list)
    fit_list(d.gap_list,120)
    d.chk_axis_probes.setText('Осевые зонды выбранных подканалов');ol.addWidget(d.chk_axis_probes)
    ol.addWidget(label_help('Осевой зонд','Линия вдоль Z в центре живого сечения каждого выбранного подканала. Вся модель отдельно не создаёт дополнительный осевой зонд.'))
    reports.addWidget(label_help('Отчёты по мгновенным значениям · не средним по времени','Все отчёты этой вкладки используют текущие поля решения. В Hybrid это мгновенные значения; в стационарном расчёте — значения текущей итерации. Средние поля по времени включаются во вкладке «Статистика» и не подставляются в мгновенные балансы.'))
    general,gl=box('Вся модель');reports.addWidget(general);d.chk_reports.setText('Расходы входа/выхода и балансы');gl.addWidget(d.chk_reports)
    gl.addWidget(label_help('Состав общих отчётов','Массовые расходы на входе и выходе и их невязка. При включённой энергии — также тепловые мощности и баланс энергии. Входной расход ориентирован наружной нормалью и обычно отрицательный. Это потоковые балансы; в нестационарном расчёте они не включают накопление массы/энергии.'))
    sources,sl=box('Отчёты по подканалам');reports.addWidget(sources)
    d.report_targets=QListWidget();d.report_targets.setSelectionMode(QAbstractItemView.NoSelection);d.report_targets.setMaximumHeight(150);sl.addWidget(d.report_targets)
    for n in range(1,d.sub_count+1):
        item=QListWidgetItem(f'Подканал {n}',d.report_targets);item.setData(Qt.UserRole,n);item.setFlags(item.flags()|Qt.ItemIsUserCheckable);item.setCheckState(Qt.Checked)
    fit_list(d.report_targets,180)
    for key,checkbox in d.report_checkboxes.items():sl.addWidget(checkbox)
    sl.addWidget(label_help('Что измеряется','Геометрия: площадь, объём, смоченный периметр, гидравлический диаметр. Гидравлика: расход, среднемассовая осевая скорость, давление, перепад, Re. Трение: средний модуль напряжения стенки, Cf и Darcy; это ещё не полный КГС. Тепло: среднемассовая температура, температура стенки и тепловая мощность. Здесь «среднее» означает усреднение по поверхности, не по времени.'))
    layout.addStretch();reports.addStretch();busy=[False]
    def checked(widget):return [widget.item(i).data(Qt.UserRole) for i in range(widget.count()) if widget.item(i).checkState()==Qt.Checked]
    def update():
        if busy[0]:return
        busy[0]=True
        try:
            targets=checked(d.parts_targets);scheme=d.plane_scheme.currentData();d._parts_saved_scheme=scheme;active=scheme!='none'
            n=2 if scheme=='ends' else 3 if scheme=='three' else d.plane_count.value()
            for i,cb in enumerate(d.sub_checkboxes,1):cb.setChecked(i in targets)
            d.chk_sub_planes.setChecked(active and any(n>0 for n in targets));d.chk_sub_n_planes.setChecked(active)
            d.chk_g_n_planes.setChecked(active and 0 in targets);d.chk_g_key_planes.setChecked(False)
            d.spin_n_planes.setValue(n);d.spin_sub_n_planes.setValue(n)
            d.plane_count.setEnabled(scheme=='uniform');d.plane_count.setVisible(scheme=='uniform');count_label.setVisible(scheme=='uniform');d.plane_spacing.setText('' if not active else f'Шаг по Z: {d.lz_m/(n-1)*1000:g} мм')
        finally:busy[0]=False
    def apply(values):
        busy[0]=True
        try:
            scheme=values.get('plane_scheme','legacy');d._parts_saved_scheme=scheme
            if scheme=='legacy':
                scheme='uniform' if d.chk_sub_planes.isChecked() or d.chk_g_n_planes.isChecked() or d.chk_g_key_planes.isChecked() else 'none'
                if (d.chk_sub_planes.isChecked() and not d.chk_sub_n_planes.isChecked()) or (d.chk_g_key_planes.isChecked() and not d.chk_g_n_planes.isChecked()):scheme='three'
            d.plane_scheme.setCurrentIndex(d.plane_scheme.findData(scheme));d.plane_count.setValue(d.spin_sub_n_planes.value())
            for i in range(d.parts_targets.count()):
                item=d.parts_targets.item(i);n=item.data(Qt.UserRole)
                selected=(d.chk_g_n_planes.isChecked() or d.chk_g_key_planes.isChecked()) if n==0 else d.sub_checkboxes[n-1].isChecked()
                item.setCheckState(Qt.Checked if selected else Qt.Unchecked)
            report_ids=values.get('report_subchannels',[-1]);report_ids=checked(d.parts_targets) if report_ids==[-1] else report_ids
            for i in range(d.report_targets.count()):d.report_targets.item(i).setCheckState(Qt.Checked if i+1 in report_ids else Qt.Unchecked)
            d.plane_count.setEnabled(scheme=='uniform');d.plane_count.setVisible(scheme=='uniform');count_label.setVisible(scheme=='uniform');d.plane_spacing.setText('')
        finally:busy[0]=False
    d.parts_targets.itemChanged.connect(lambda *_:update());d.plane_scheme.currentIndexChanged.connect(lambda *_:update());d.plane_count.valueChanged.connect(lambda *_:update())
    d._parts_workflow=lambda:dict(report_subchannels=checked(d.report_targets),plane_scheme=d._parts_saved_scheme)
    d._apply_parts_workflow=apply
    apply(d._workflow)
