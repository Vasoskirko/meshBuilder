"""Method-only TDC tab; geometry, heat and field selection stay in shared tabs."""
from copy import deepcopy
from PySide6.QtWidgets import QWidget,QVBoxLayout,QFormLayout,QComboBox,QLabel,QCheckBox,QPushButton,QListWidget,QListWidgetItem,QHBoxLayout
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from starccm_compact_ui import box,label_help
from starccm_tdc_plan import TDC_DEFAULTS,validate_tdc
from number_field import NumberField


def install(d):
    page=d.tabs.widget(6).widget();layout=page.layout();stash=QWidget(d);stash.hide();d._tdc_stash=stash
    while layout.count():
        item=layout.takeAt(0)
        if item.widget():item.widget().setParent(stash)
        elif item.layout():
            while item.layout().count():
                sub=item.layout().takeAt(0)
                if sub.widget():sub.widget().setParent(stash)
    d.tdc_parts_required=QLabel('TDC: сечения выбранных A/B обязательны; внутренние плоскости переиспользуются, вход/выход берутся на интерфейсах.')
    d.tdc_parts_required.setWordWrap(True);d.tabs.widget(2).widget().layout().insertWidget(0,d.tdc_parts_required)
    d.tdc_reports_required=QLabel('TDC: температуры, мощность нагрева/стока, осевые потоки и запас энергии создаются обязательно. Дополнительные отчёты выбираются ниже.')
    d.tdc_reports_required.setWordWrap(True);d.tabs.widget(3).widget().layout().insertWidget(0,d.tdc_reports_required)
    layout.addWidget(d.tdc_enabled)
    d.tdc_enabled.setText('Создавать расчёт TDC эффективного обмена')
    d.tdc_controls=QWidget();body=QVBoxLayout(d.tdc_controls);body.setContentsMargins(0,0,0,0);layout.addWidget(d.tdc_controls)
    group,gl=box('Подканалы и обмен');body.addWidget(group);form=QFormLayout();gl.addLayout(form)
    d.tdc_a=QComboBox();d.tdc_b=QComboBox()
    for n in range(1,d.sub_count+1):
        for combo in (d.tdc_a,d.tdc_b):combo.addItem(f'Подканал {n}',n)
    for combo in (d.tdc_a,d.tdc_b):combo.setMaximumWidth(260)
    d.tdc_b.setCurrentIndex(min(1,d.sub_count-1));form.addRow('Подканал A',d.tdc_a);form.addRow('Подканал B',d.tdc_b)
    d.tdc_gaps=QListWidget();d.tdc_gaps.setMaximumHeight(80);gl.addWidget(d.tdc_gaps)
    d.tdc_gaps.setToolTip('Баланс определяет суммарный обмен. Включаются все соединения A–B; третьи соседи блокируют расчёт.')
    d.tdc_equivalence.setText('Подтверждаю эквивалентность нескольких зазоров A–B');gl.addWidget(d.tdc_equivalence)
    def show_exchange():
        d.tabs.setCurrentIndex(0);view=d.surface_preview;cat=d._surface_catalog
        view.set_view_mode('sides');view.draw_catalog(cat,d.rb_inter_fuse.isChecked());ids=[]
        for row in cat.get('sides',[]):
            if row['source']==d.tdc_a.currentData() and row.get('neighbor')==d.tdc_b.currentData():
                if row['id'] not in view.items_by_id:view.add_surface(row,QColor('#d62728'),3.)
                ids.append(row['id'])
        for pair in getattr(d,'_pairs',[]):
            rows={r['id']:r for r in cat.get('sides',[])}
            if pair['first'] in rows and pair['second'] in rows and {rows[pair['first']]['source'],rows[pair['second']]['source']}=={d.tdc_a.currentData(),d.tdc_b.currentData()}:ids.extend((pair['first'],pair['second']))
        view.highlight(ids);d.preview_selection.setText('Обмен TDC: '+', '.join(ids))
    preview=QPushButton('Показать поверхности во вкладке «Сетка»');preview.clicked.connect(show_exchange);gl.addWidget(preview)
    d._show_tdc_exchange=show_exchange
    method,ml=box('Определение коэффициента');body.addWidget(method);mf=QFormLayout();ml.addLayout(mf)
    mf.addRow('Метод',QLabel('Энергетический баланс каждого подканала'))
    mf.addRow(label_help('Температурная разность','На каждом шаге: потоковая T=∫ρu_zT dS/∫ρu_z dS; затем среднее по длине по равноотстоящим сечениям с трапецеидальными весами. Итог: среднее по времени этой скалярной разности. Не отчёт по Mean of Temperature.'),QLabel('ΔT = T_A − T_B; потоковые, средние по длине'))
    d.tdc_sections_hint=QLabel();mf.addRow('Сечения по длине',d.tdc_sections_hint)
    parts=QPushButton('Настроить сечения');parts.clicked.connect(lambda:d.tabs.setCurrentIndex(2));mf.addRow('',parts)
    d.tdc_g_ref=QLabel()
    mf.addRow(label_help('Опорный массовый поток','Используется общий аналитический G=ρU_b из калькулятора y+. Физический массовый расход периодических пар должен быть согласован с ним.'),d.tdc_g_ref)
    correction=QLabel('Эффективный: молекулярный + конвективный')
    mf.addRow(label_help('Теплоперенос','Чисто турбулентный коэффициент не выделяется. Молекулярная поправка требует проверки полного потока на всех границах и пока недоступна.'),correction)
    mf.addRow(label_help('Минимальная |ΔT|, K','При недостаточном контрасте отношение не публикуется; исходные средние и балансы сохраняются.'),d.tmc_fields['min_delta_t']);d.tmc_fields['min_delta_t'].show()
    d.tdc_balance_tol=NumberField(.05,minimum=1e-12,maximum=1.);d.tdc_balance_tol.setMaximumWidth(120)
    mf.addRow(label_help('Допуск баланса, доля','|Q_A−Q_B| / max(|Q_A|,|Q_B|). Это проверка согласованности балансов, не оценка статистической погрешности.'),d.tdc_balance_tol)
    source=QLabel('Нагрев берётся из «Физики». Создаётся равномерный компенсационный сток по всему объёму модели. Настройка не запускает решатель.');source.setWordWrap(True);ml.addWidget(source)
    stats,sl=box('Усреднение и результаты');body.addWidget(stats)
    d.tdc_blocks=QCheckBox('Сохранять отдельные блочные результаты TDC');d.tdc_blocks.setChecked(True);sl.addWidget(d.tdc_blocks)
    d.tdc_time_hint=QLabel();d.tdc_time_hint.setWordWrap(True);sl.addWidget(d.tdc_time_hint)
    timing=QPushButton('Настроить средние поля и время');timing.clicked.connect(lambda:d.tabs.setCurrentIndex(4));sl.addWidget(timing)
    desc=QLabel('Обязательные результаты: общий TDC, накопленный TDC на каждом шаге, средние скалярные отчёты, ΔT, запас энергии и согласованность двух балансов. Мгновенные истории и результаты сохраняются в CSV; BMBC не применяется.');desc.setWordWrap(True);sl.addWidget(desc)
    formula=QLabel('TDC = Q̄_A / (A_обмена · Cp · ρU_b · ΔT̄)\nQ̄_A = Q̄_нагрев,A + Q̄_сток,A − Q̄_осевой,A − ΔH_A/Δt\nБезразмерный эффективный обмен; знак Q и ΔT: A → B.');formula.setWordWrap(True);sl.addWidget(formula)
    d.tdc_status.setParent(None);body.addWidget(d.tdc_status);d.tdc_status.show();body.addStretch()
    def refresh():
        d.tdc_parts_required.setVisible(d.tdc_enabled.isChecked());d.tdc_reports_required.setVisible(d.tdc_enabled.isChecked())
        if not hasattr(d,'_surface_catalog'):return
        a,b=d.tdc_a.currentData(),d.tdc_b.currentData();cat=d._surface_catalog
        d.tdc_gaps.clear();seen=set()
        for r in cat.get('sides',[]):
            if r['source']==a and r.get('neighbor')==b:
                key=f'Gap_Sub{min(a,b)}_Sub{max(a,b)}'
                if key not in seen:d.tdc_gaps.addItem(f'✓ {key} · {r["area"]:.6g} м² · нормаль A → B');seen.add(key)
        for pair in getattr(d,'_pairs',[]):
            rows={r['id']:r for r in cat.get('sides',[])}
            if pair['first'] in rows and pair['second'] in rows and {rows[pair['first']]['source'],rows[pair['second']]['source']}=={a,b}:
                d.tdc_gaps.addItem('✓ '+pair['first']+' ↔ '+pair['second']);seen.add(pair['first']+'__'+pair['second'])
        d.tdc_equivalence.setEnabled(len(seen)>1)
        try:
            from starccm_flow_defaults import calculator_mass_flow
            cap=next(r for r in cat.get('endcaps',[]) if r['role']=='Inlet')
            g=calculator_mass_flow(cat,d.read_fluid(),d.yplus_data,cap['id'])/cap['area']
            d.tdc_g_ref.setText(f'G = ρU_b = {g:.6g} кг/(м²·с), из калькулятора y+')
        except (ValueError,KeyError,StopIteration):d.tdc_g_ref.setText('Проверьте геометрию, Re и свойства')
        d.tdc_sections_hint.setText(f'{d.spin_sub_n_planes.value()} сечений на подканал; вход/выход — стороны интерфейса, внутренние плоскости общие')
        d.tdc_time_hint.setText('Общее окно и выбранные поля — из вкладки 5. Блоки отдельные; общий результат считается по всей истории, без среднего блочных отношений.')
        d.tdc_status.setText('Готовится эффективный обмен выбранной пары. Условия, периодичность и полнота баланса проверяются перед экспортом.' if a!=b and seen else 'Выберите разные соседние подканалы; для боковых обменов задайте пары в «Сетке».')
    def read():
        return validate_tdc(dict(TDC_DEFAULTS,a=d.tdc_a.currentData(),b=d.tdc_b.currentData(),equivalent=d.tdc_equivalence.isChecked(),sections=d.spin_sub_n_planes.value(),blocks=d.tdc_blocks.isChecked(),min_delta_t=d.tmc_fields['min_delta_t'].value(),balance_tolerance=d.tdc_balance_tol.value()))
    def apply(v):
        v=validate_tdc(v)
        for key,combo in (('a',d.tdc_a),('b',d.tdc_b)):combo.setCurrentIndex(combo.findData(v[key]))
        d.tdc_equivalence.setChecked(v['equivalent']);d.tdc_blocks.setChecked(v['blocks']);d.tdc_balance_tol.setValue(v['balance_tolerance']);d.tmc_fields['min_delta_t'].setValue(v['min_delta_t'])
        if d.tdc_enabled.isChecked():d.spin_sub_n_planes.setValue(v['sections'])
        refresh()
    d._tdc_read=read;d._tdc_apply=apply;d._tdc_refresh=refresh
    for combo in (d.tdc_a,d.tdc_b):combo.currentIndexChanged.connect(refresh)
    d.spin_sub_n_planes.valueChanged.connect(refresh);refresh()
