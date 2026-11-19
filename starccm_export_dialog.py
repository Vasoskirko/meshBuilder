# -*- coding: utf-8 -*-
"""Диалог экспорта сетки Plot3D и генерации Java-макроса для Simcenter STAR-CCM+."""
from yplus_calculator import export_yplus_data
from pathlib import Path
from starccm_export_profile import save_profile, load_profile, validate_options, FIELD_CHOICES, REPORT_CHOICES, MEAN_CHOICES

try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLineEdit,
        QSpinBox, QCheckBox, QPushButton, QLabel, QFileDialog,
        QMessageBox, QRadioButton, QButtonGroup, QDialog, QTabWidget, QPlainTextEdit, QScrollArea, QGridLayout, QSizePolicy, QComboBox
    )
    HAS_QT = True
except ImportError:
    HAS_QT = False


class StarCcmExportDialog(QDialog if HAS_QT else object):
    def __init__(self, parent=None, mesh_result=None, bundle_model=None, fluid_props=None, yplus_data=None):
        if not HAS_QT:
            return
        super().__init__(parent)
        self.setWindowTitle("Экспорт для Simcenter STAR-CCM+ (Plot3D + Java Macro 2602)")
        self.resize(800, 840)

        self.mesh_result = mesh_result
        self.bundle_model = bundle_model
        self.fluid_props = fluid_props or {}
        self.yplus_data = export_yplus_data(yplus_data, default_h1=getattr(getattr(mesh_result, "params", None), "h1", 2.5e-6))

        # Высота готовой сетки важнее ещё не применённых значений UI.
        self.lz_m = 0.050
        p = getattr(mesh_result, "params", None)
        mesh_height = getattr(p, "z_len", None)
        if mesh_height is None:
            mesh_height = getattr(p, "L", None)
        if mesh_height is not None:
            self.lz_m = float(mesh_height)
        elif parent and hasattr(parent, "mesh_subpanel") and "z_len" in parent.mesh_subpanel.fields:
            self.lz_m = float(parent.mesh_subpanel.fields["z_len"].value())

        # Количество подканалов:
        self.sub_count = getattr(mesh_result, "subchannels_count", 3) if mesh_result else 3

        main_lay = QVBoxLayout(self)

        lbl_header = QLabel(
            "<b>Экспорт сетки и настройка STAR-CCM+ 2602</b><br>"
            "Настройте физику, выберите анализ и сохраните сетку вместе с макросом. "
            "Условия на границах задаются вручную в STAR-CCM+.",
            self
        )
        lbl_header.setStyleSheet("background: #f1f5f9; color: #1e3a5f; padding: 10px; border: 1px solid #cbd5e1; border-radius: 4px; font-size: 11px;")
        lbl_header.setWordWrap(True)
        main_lay.addWidget(lbl_header)

        self.tabs = QTabWidget(self)

        # ----------------- ВКЛАДКА 1: Сетка и топология -----------------
        tab_mesh = QWidget()
        l_tab1 = QVBoxLayout(tab_mesh)

        grp_import = QGroupBox("1. Файл сетки и импорт", tab_mesh)
        l_imp = QVBoxLayout(grp_import)
        self.chk_import = QCheckBox("Импортировать сетку Plot3D (.xyz) при запуске макроса", grp_import)
        self.chk_import.setChecked(True)
        l_imp.addWidget(self.chk_import)
        row_f = QHBoxLayout()
        row_f.addWidget(QLabel("Имя файла сетки:", grp_import))
        self.edit_xyz = QLineEdit("bundle_mesh.xyz", grp_import)
        row_f.addWidget(self.edit_xyz)
        l_imp.addLayout(row_f)
        l_tab1.addWidget(grp_import)

        grp_if = QGroupBox("2. Сопряжение многоблочной структуры", tab_mesh)
        l_if = QVBoxLayout(grp_if)
        lbl_inner_info = QLabel("• <i>Внутри каждого подканала 6 секторов всегда объединяются конформно (Fuse Conformal).</i>", grp_if)
        lbl_inner_info.setStyleSheet("color: #2e7d32; font-size: 11px;")
        l_if.addWidget(lbl_inner_info)

        l_if.addWidget(QLabel("<b>Межподканальные границы (стык ячеек):</b>", grp_if))
        self.bg_inter = QButtonGroup(self)
        self.rb_inter_intf = QRadioButton("Internal Interface — раздельные интерфейсы if_sA_sB (мониторинг перетока)", grp_if)
        self.rb_inter_intf.setChecked(True)
        self.rb_inter_fuse = QRadioButton("Fuse Conformal — слияние подканалов в единый монолит TVS_Assembly", grp_if)
        self.bg_inter.addButton(self.rb_inter_intf)
        self.bg_inter.addButton(self.rb_inter_fuse)
        self.rb_inter_intf.toggled.connect(self.on_topology_mode_changed)
        l_if.addWidget(self.rb_inter_intf)
        l_if.addWidget(self.rb_inter_fuse)
        l_tab1.addWidget(grp_if)

        grp_wall = QGroupBox("3. Именование и группировка стенок стержней", tab_mesh)
        l_wall = QVBoxLayout(grp_wall)
        self.bg_wall = QButtonGroup(self)
        self.rb_wall_by_rod = QRadioButton("По отдельным стержням: rod_1, rod_2, rod_3 (каждый ТВЭЛ — своя стенка)", grp_wall)
        self.rb_wall_by_rod.setChecked(True)
        self.rb_wall_60 = QRadioButton("Секторы по 60°: rod_{sub}_{sec} (для анализа азимутального профиля q'')", grp_wall)
        self.rb_wall_rod = QRadioButton("Монолитная стенка ячейки: rod_{sub} (все стержни ячейки в один контур)", grp_wall)
        self.bg_wall.addButton(self.rb_wall_by_rod)
        self.bg_wall.addButton(self.rb_wall_60)
        self.bg_wall.addButton(self.rb_wall_rod)
        l_wall.addWidget(self.rb_wall_by_rod)
        l_wall.addWidget(self.rb_wall_60)
        l_wall.addWidget(self.rb_wall_rod)
        l_tab1.addWidget(grp_wall)

        grp_io = QGroupBox("4. Границы потока (Inlet & Outlet)", tab_mesh)
        l_io = QVBoxLayout(grp_io)
        self.bg_io = QButtonGroup(self)
        self.rb_io_split = QRadioButton("Раздельные границы по подканалам: in_1, out_1, in_2, out_2...", grp_io)
        self.rb_io_split.setChecked(True)
        self.rb_io_single = QRadioButton("Единый общий вход (Inlet) и выход (Outlet)", grp_io)
        self.bg_io.addButton(self.rb_io_split)
        self.bg_io.addButton(self.rb_io_single)
        l_io.addWidget(self.rb_io_split)
        l_io.addWidget(self.rb_io_single)
        l_tab1.addWidget(grp_io)
        l_tab1.addStretch()
        self.tabs.addTab(tab_mesh, "1. Сетка")

        # ----------------- ВКЛАДКА 2: Физика и свойства среды -----------------
        tab_phys = QWidget()
        l_tab2 = QVBoxLayout(tab_phys)

        grp_turb = QGroupBox("1. Модель турбулентности", tab_phys)
        l_turb = QVBoxLayout(grp_turb)
        self.bg_turb = QButtonGroup(self)
        self.rb_turb_rst = QRadioButton("Reynolds Stress Turbulence (EB RS) + All y+ Wall Treatment (RST, Стационарный)", grp_turb)
        self.rb_turb_rst.setChecked(True)
        self.rb_turb_srh = QRadioButton("Scale-Resolving Hybrid (SRH) + SST k-omega + All y+ (Гибридный URANS/LES, Нестационарный)", grp_turb)
        self.bg_turb.addButton(self.rb_turb_rst)
        self.bg_turb.addButton(self.rb_turb_srh)
        l_turb.addWidget(self.rb_turb_rst)
        l_turb.addWidget(self.rb_turb_srh)
        l_tab2.addWidget(grp_turb)

        grp_eos = QGroupBox("2. Свойства среды (Equation of State)", tab_phys)
        l_eos = QVBoxLayout(grp_eos)
        self.bg_eos = QButtonGroup(self)
        self.rb_eos_const = QRadioButton("Постоянные свойства (Constant Density) — расчет по константам в Parameters", grp_eos)
        self.rb_eos_const.setChecked(True)
        self.rb_eos_iapws = QRadioButton("IAPWS-IF97 Liquid EOS — расчет теплофизических свойств воды от T и P", grp_eos)
        self.bg_eos.addButton(self.rb_eos_const)
        self.bg_eos.addButton(self.rb_eos_iapws)
        l_eos.addWidget(self.rb_eos_const)
        l_eos.addWidget(self.rb_eos_iapws)
        l_tab2.addWidget(grp_eos)

        grp_extra_phys = QGroupBox("3. Уравнение энергии и дополнительные модели", tab_phys)
        l_ep = QVBoxLayout(grp_extra_phys)
        self.chk_thermal = QCheckBox("Включить уравнение энергии (Segregated Fluid Temperature / Теплоперенос)", grp_extra_phys)
        self.chk_thermal.setChecked(True)
        l_ep.addWidget(self.chk_thermal)

        self.chk_gravity = QCheckBox("Учитывать гравитацию (|g| = 9.81 м/с²)", grp_extra_phys)
        self.chk_gravity.setChecked(False)
        l_ep.addWidget(self.chk_gravity)
        gravity_row = QHBoxLayout(); gravity_row.addWidget(QLabel("Направление в лабораторной системе:", grp_extra_phys))
        self.combo_gravity = QComboBox(grp_extra_phys)
        self.combo_gravity.addItems(["-X", "+X", "-Y", "+Y", "-Z", "+Z"])
        self.combo_gravity.setCurrentText("-Z"); self.combo_gravity.setEnabled(False)
        self.chk_gravity.toggled.connect(self.combo_gravity.setEnabled)
        gravity_row.addWidget(self.combo_gravity); l_ep.addLayout(gravity_row)
        l_tab2.addWidget(grp_extra_phys)
        init_info = QLabel(
            f"Reference Pressure (абсолютное): {self.fluid_props.get('p_ref_mpa', 15.0):g} МПа. "
            f"Initial Pressure (избыточное): 0 Па; температура: {self.fluid_props.get('t_ref_c', 300.0)+273.15:g} K; "
            f"скорость: (0, 0, {self.yplus_data.get('velocity', 5.62):g}) м/с. "
            "Свойства и начальные поля связаны с параметрами. Условия на границах задаются вручную.", tab_phys)
        init_info.setWordWrap(True); l_tab2.addWidget(init_info)
        self.chk_initialize = QCheckBox("Инициализировать начальные поля при первом запуске (без итераций решателя)", tab_phys)
        self.chk_initialize.setChecked(True)
        self.chk_initialize.setToolTip("Сначала настраиваются свойства, Reference Pressure и Initial Conditions. Повторный запуск не сбрасывает решение.")
        l_tab2.addWidget(self.chk_initialize)
        l_tab2.addStretch()
        self.tabs.addTab(tab_phys, "2. Физика")

        # ----------------- ВКЛАДКА 3: Мониторы и параметры -----------------
        tab_mon = QWidget()
        l_tab3 = QVBoxLayout(tab_mon)

        grp_param = QGroupBox("1. Переменные в Tools > Parameters", tab_mon)
        l_p = QVBoxLayout(grp_param)
        self.chk_params = QCheckBox("Создать переменные: rho, Cp, dynvis, kinvis, lambda, Pr, T_ref, P_ref, Re_in, D_hyd, Ub, G...", tab_mon)
        self.chk_params.setChecked(True)
        self.chk_params.setToolTip("Базовые параметры свойств и начальных условий обязательны и создаются независимо от этого флажка.")
        l_p.addWidget(self.chk_params)
        lbl_p_info = QLabel(
            f"Текущие значения: ρ = {self.fluid_props.get('density', 725.553):.2f} кг/м³, "
            f"μ = {self.fluid_props.get('dyn_vis', 8.835e-5):.2e} Па·с, "
            f"Ub = {self.yplus_data.get('velocity', 5.62):.2f} м/с, "
            f"h1 = {self.yplus_data.get('delta_y1_um', 2.5):.2f} мкм",
            grp_param
        )
        lbl_p_info.setStyleSheet("font-size: 11px; color: #1e3a5f; padding-left: 20px;")
        l_p.addWidget(lbl_p_info)
        l_tab3.addWidget(grp_param)

        grp_rep = QGroupBox("2. Отчеты расхода и энергии (сохраняются в дереве)", tab_mon)
        l_r = QVBoxLayout(grp_rep)
        self.chk_reports = QCheckBox("Создать отчеты расхода и невязки; при включенной энергии — тепловой баланс", grp_rep)
        self.chk_reports.setChecked(True)
        l_r.addWidget(self.chk_reports)
        l_tab3.addWidget(grp_rep)

        grp_qual = QGroupBox("Диагностика в STAR-CCM+", tab_mon)
        l_q = QVBoxLayout(grp_qual)
        self.chk_scene = QCheckBox("Создать скалярные сцены качества на среднем поперечном сечении", grp_qual)
        self.chk_scene.setChecked(True)
        l_q.addWidget(self.chk_scene)
        self.chk_histograms = QCheckBox("Гистограммы качества (число ячеек) и отчеты min/max", grp_qual)
        self.chk_histograms.setChecked(True)
        l_q.addWidget(self.chk_histograms)
        bins_row = QHBoxLayout()
        bins_row.addWidget(QLabel("Интервалов гистограммы:", grp_qual))
        self.spin_quality_bins = QSpinBox(grp_qual)
        self.spin_quality_bins.setRange(5, 500)
        self.spin_quality_bins.setValue(50)
        self.chk_histograms.toggled.connect(self.spin_quality_bins.setEnabled)
        bins_row.addWidget(self.spin_quality_bins)
        l_q.addLayout(bins_row)
        # Quality controls are placed on their own fifth tab below.
        l_tab3.addStretch()
        self.tabs.addTab(tab_mon, "3. Параметры")

        # ----------------- ВКЛАДКА 4: Derived Parts & Сечения -----------------
        tab_parts = QWidget()
        l_tab4 = QVBoxLayout(tab_parts)

        grp_g_sec = QGroupBox("1. Общие поперечные сечения сборки (Global Plane Sections по Z)", tab_parts)
        l_gs = QVBoxLayout(grp_g_sec)
        self.chk_g_key_planes = QCheckBox("Создать ключевые плоскости: на входе (Z=0), в середине (Z=L/2), на выходе (Z=L)", grp_g_sec)
        self.chk_g_key_planes.setChecked(True)
        l_gs.addWidget(self.chk_g_key_planes)

        row_n = QHBoxLayout()
        self.chk_g_n_planes = QCheckBox("Создать серию из N плоскостей вдоль оси Z:", grp_g_sec)
        self.chk_g_n_planes.setChecked(True)
        row_n.addWidget(self.chk_g_n_planes)

        self.spin_n_planes = QSpinBox(grp_g_sec)
        self.spin_n_planes.setRange(2, 100)
        self.spin_n_planes.setValue(11)
        self.spin_n_planes.valueChanged.connect(self.update_dz_hint)
        row_n.addWidget(self.spin_n_planes)
        l_gs.addLayout(row_n)

        self.lbl_dz_hint = QLabel(grp_g_sec)
        self.lbl_dz_hint.setStyleSheet("font-size: 11px; color: #1e3a5f; padding-left: 20px; font-weight: 500;")
        l_gs.addWidget(self.lbl_dz_hint)
        l_tab4.addWidget(grp_g_sec)

        grp_sub_sec = QGroupBox("2. Индивидуальные сечения по подканалам", tab_parts)
        l_ss = QVBoxLayout(grp_sub_sec)
        self.chk_sub_planes = QCheckBox("Создать сечения выбранных подканалов (общий выбор над вкладками)", grp_sub_sec)
        self.chk_sub_planes.setChecked(True)
        l_ss.addWidget(self.chk_sub_planes)

        # Выбор подканалов чекбоксами:
        self.sub_checkboxes = []
        self.grp_sources = QGroupBox("Подканалы для сечений, зондов и расчётных отчётов", self)
        self.grp_sources.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        sources_layout = QVBoxLayout(self.grp_sources)
        sources_scroll = QScrollArea(); sources_scroll.setWidgetResizable(True)
        sources_scroll.setFixedHeight(min(100, max(48, 28*((self.sub_count+3)//4)+12)))
        sources_content = QWidget(); grid_subs = QGridLayout(sources_content)
        sources_scroll.setWidget(sources_content); sources_layout.addWidget(sources_scroll)
        main_lay.addWidget(self.grp_sources)
        for s in range(1, self.sub_count + 1):
            cb = QCheckBox(f"Подканал {s}", sources_content)
            cb.setChecked(True)
            self.sub_checkboxes.append(cb)
            grid_subs.addWidget(cb, (s-1)//4, (s-1)%4)


        row_sel_btns = QHBoxLayout()
        btn_sel_all = QPushButton("Выбрать все", grp_sub_sec)
        btn_sel_all.setProperty("btnClass", "standard")
        btn_sel_all.clicked.connect(lambda: [cb.setChecked(True) for cb in self.sub_checkboxes])
        btn_clear_all = QPushButton("Снять выделение", grp_sub_sec)
        btn_clear_all.setProperty("btnClass", "standard")
        btn_clear_all.clicked.connect(lambda: [cb.setChecked(False) for cb in self.sub_checkboxes])
        row_sel_btns.addWidget(btn_sel_all)
        row_sel_btns.addWidget(btn_clear_all)
        row_sel_btns.addStretch()
        sources_layout.addLayout(row_sel_btns)

        row_sub_n = QHBoxLayout()
        self.chk_sub_n_planes = QCheckBox("Серия из M плоскостей по высоте ячейки:", grp_sub_sec)
        self.chk_sub_n_planes.setChecked(True)
        row_sub_n.addWidget(self.chk_sub_n_planes)

        self.spin_sub_n_planes = QSpinBox(grp_sub_sec)
        self.spin_sub_n_planes.setRange(2, 100)
        self.spin_sub_n_planes.setValue(11)
        self.spin_sub_n_planes.valueChanged.connect(self.update_dz_hint)
        row_sub_n.addWidget(self.spin_sub_n_planes)
        l_ss.addLayout(row_sub_n)

        self.lbl_sub_dz_hint = QLabel(grp_sub_sec)
        self.lbl_sub_dz_hint.setStyleSheet("font-size: 11px; color: #1e3a5f; padding-left: 20px; font-weight: 500;")
        l_ss.addWidget(self.lbl_sub_dz_hint)
        l_tab4.addWidget(grp_sub_sec)

        self.chk_gap_sections = QCheckBox("Продольные сечения зазоров между исходными подканалами (Fuse)", tab_parts)
        self.chk_gap_sections.setChecked(True)
        self.chk_gap_sections.setToolTip("Одна ориентированная поверхность на общий зазор; без создания стенки или интерфейса")
        l_tab4.addWidget(self.chk_gap_sections)

        grp_probes = QGroupBox("3. Линейные зонды (Line Sections)", tab_parts)
        l_pr = QVBoxLayout(grp_probes)
        self.chk_axis_probes = QCheckBox("Создать осевые зонды по центру живого сечения каждой ячейки (Probe_Axis_Sub_N)", grp_probes)
        self.chk_axis_probes.setChecked(True)
        l_pr.addWidget(self.chk_axis_probes)
        l_tab4.addWidget(grp_probes)
        l_tab4.addStretch()
        self.tabs.addTab(tab_parts, "4. Сечения")

        # Move workflow controls into their relevant tabs.
        self.chk_group_objects = QCheckBox("Группировать объекты meshBuilder", tab_mesh)
        self.chk_group_objects.setChecked(True)
        l_tab1.insertWidget(l_tab1.count()-1, self.chk_group_objects)
        fields_group = QGroupBox("3. Поля для сцен, графиков и анализа", tab_mon)
        fields_layout = QVBoxLayout(fields_group)
        self.chk_field_functions = QCheckBox("Создать выбранные вычисляемые величины в Field Functions", fields_group)
        self.chk_field_functions.setChecked(True)
        fields_layout.addWidget(self.chk_field_functions)
        fields_explanation = QLabel("Функции поля задают величину в каждой точке сетки. Их можно выбрать в сцене или графике. "
            "Это не отдельные отчёты и не мониторы; создание полей не запускает расчёт.", fields_group)
        fields_explanation.setWordWrap(True); fields_layout.addWidget(fields_explanation)
        self.field_checkboxes = {}
        for key, label in FIELD_CHOICES.items():
            cb = QCheckBox(label, fields_group); cb.setChecked(True)
            self.field_checkboxes[key] = cb; fields_layout.addWidget(cb)
            self.chk_field_functions.toggled.connect(cb.setEnabled)
        fields_layout.addWidget(QLabel("Служебные координаты и маски, необходимые макросу, создаются независимо от выбора.", fields_group))
        l_tab3.insertWidget(l_tab3.count()-1, fields_group)

        tab_quality = QWidget(); quality_layout = QVBoxLayout(tab_quality)
        quality_layout.addWidget(grp_qual)
        self.chk_bad_cells = QCheckBox("Выделять плохие ячейки (Threshold), считать количество и процент", tab_quality)
        self.chk_bad_cells.setChecked(True); quality_layout.addWidget(self.chk_bad_cells)
        self.chk_summary = QCheckBox("Итоговая сводка и CSV-отчёт рядом с симуляцией", tab_quality)
        self.chk_summary.setChecked(True); l_tab3.insertWidget(l_tab3.count()-1, self.chk_summary)
        self.chk_evaluate_solution = QCheckBox("Вычислять физические отчёты в сводке после настройки границ и расчёта", tab_mon)
        self.chk_evaluate_solution.setToolTip("По умолчанию сводка вычисляет только геометрию и качество. Нужны итерации решения; нулевой расход не допускает среднемассового усреднения.")
        l_tab3.insertWidget(l_tab3.count()-1,self.chk_evaluate_solution)
        self.chk_summary.toggled.connect(self.chk_evaluate_solution.setEnabled)
        check_button = QPushButton("Проверить текущую сетку в программе", tab_quality)
        check_button.clicked.connect(self.check_export_mesh)
        quality_layout.addWidget(check_button)
        self.local_quality_text = QPlainTextEdit(tab_quality); self.local_quality_text.setReadOnly(True)
        self.local_quality_text.setPlainText("Проверка выполняется по кнопке. Метрики meshBuilder и STAR различаются; результаты STAR проверяйте после импорта.")
        quality_layout.addWidget(self.local_quality_text)
        self.tabs.addTab(tab_quality, "5. Качество")

        tab_analysis = QWidget(); analysis_layout = QVBoxLayout(tab_analysis)
        info = QLabel("Отчёты по выбранным выше исходным подканалам, включая Fuse. "
            "Плотность и вязкость берутся из текущих полей STAR, в том числе при IAPWS. "
            "Другие группы также создают необходимые геометрические отчёты. "
            "Вычисления требуют инициализированного или рассчитанного решения.", tab_analysis)
        info.setWordWrap(True); analysis_layout.addWidget(info)
        self.report_checkboxes = {}
        for key, label in REPORT_CHOICES.items():
            cb = QCheckBox(label, tab_analysis); self.report_checkboxes[key] = cb
            analysis_layout.addWidget(cb)
        note = QLabel("Cf = τw / (ρin Ub²/2); Darcy по стенке = 4 Cf. Перепад давления включает ускорение и гравитацию: "
            "он не считается чистыми потерями трения. Re = |ṁ| Dh / (A μin), свойства усредняются по площади входа.", tab_analysis)
        note.setWordWrap(True); analysis_layout.addWidget(note)
        self.mean_group = QGroupBox("HYBRID: накопление средних полей по временным шагам", tab_analysis)
        means_layout = QVBoxLayout(self.mean_group); self.mean_checkboxes = {}
        for key, label in MEAN_CHOICES.items():
            cb = QCheckBox(label, self.mean_group); self.mean_checkboxes[key] = cb; means_layout.addWidget(cb)
        start_row = QHBoxLayout(); start_row.addWidget(QLabel("Начальный временной шаг:", self.mean_group))
        self.spin_mean_start = QSpinBox(self.mean_group); self.spin_mean_start.setRange(1, 1000000000)
        start_row.addWidget(self.spin_mean_start); means_layout.addLayout(start_row)
        mean_note = QLabel("Один отсчёт на временной шаг; используйте постоянный Δt. Начните после переходного процесса. "
            "Повторный запуск сохраняет накопленную статистику; настройка шага применяется только к новым мониторам. "
            "Решатель автоматически не запускается.", self.mean_group)
        mean_note.setWordWrap(True); means_layout.addWidget(mean_note)
        analysis_layout.addWidget(self.mean_group); analysis_layout.addStretch()
        self.rb_turb_srh.toggled.connect(self.mean_group.setEnabled)
        self.mean_group.setEnabled(self.rb_turb_srh.isChecked())
        self.tabs.addTab(tab_analysis, "6. Анализ")
        # Scroll long tabs rather than growing the dialog beyond the screen.
        for index in range(self.tabs.count()):
            widget = self.tabs.widget(index); title = self.tabs.tabText(index)
            self.tabs.removeTab(index)
            scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(widget)
            self.tabs.insertTab(index, scroll, title)
        self.tabs.setCurrentIndex(0)
        profile_row = QHBoxLayout()
        save_button = QPushButton("Сохранить профиль экспорта…", self)
        load_button = QPushButton("Загрузить профиль экспорта…", self)
        save_button.clicked.connect(self.save_export_profile)
        load_button.clicked.connect(self.load_export_profile)
        profile_row.addWidget(save_button); profile_row.addWidget(load_button)
        main_lay.addLayout(profile_row)
        main_lay.addWidget(self.tabs, 1)
        self.on_topology_mode_changed()
        self.update_dz_hint()
        self.selection_hint = QLabel(self); self.selection_hint.setWordWrap(True)
        main_lay.addWidget(self.selection_hint)
        for control in (self.chk_g_n_planes,self.chk_sub_n_planes,self.chk_sub_planes,self.chk_thermal,self.rb_eos_iapws,self.rb_turb_srh,*self.sub_checkboxes):
            control.toggled.connect(self.update_dependencies)
        self.update_dependencies()

        b_box = QHBoxLayout()
        btn_gen = QPushButton("🚀 Сгенерировать макрос (.java) и сетку Plot3D…", self)
        btn_gen.setProperty("btnClass", "primary")
        btn_gen.clicked.connect(self.generate_and_save)
        b_box.addWidget(btn_gen)

        btn_cancel = QPushButton("Отмена", self)
        btn_cancel.clicked.connect(self.reject)
        b_box.addWidget(btn_cancel)
        main_lay.addLayout(b_box)

    def update_dependencies(self):
        self.spin_n_planes.setEnabled(self.chk_g_n_planes.isChecked())
        self.lbl_dz_hint.setEnabled(self.chk_g_n_planes.isChecked())
        selected = sum(cb.isChecked() for cb in self.sub_checkboxes)
        sub_series = self.chk_sub_planes.isChecked() and self.chk_sub_n_planes.isChecked() and selected > 0
        self.spin_sub_n_planes.setEnabled(sub_series); self.lbl_sub_dz_hint.setEnabled(sub_series)
        self.chk_sub_n_planes.setEnabled(self.chk_sub_planes.isChecked() and selected > 0)
        thermal = self.chk_thermal.isChecked() or self.rb_eos_iapws.isChecked()
        self.chk_thermal.setEnabled(not self.rb_eos_iapws.isChecked())
        self.chk_thermal.setToolTip("IAPWS требует энергии независимо от сохранённого положения флажка.")
        self.report_checkboxes['thermal'].setEnabled(thermal)
        for key in ('temperature','wall_heat_flux'): self.mean_checkboxes[key].setEnabled(thermal)
        self.mean_group.setEnabled(self.rb_turb_srh.isChecked())
        text = f"Подканалы анализа: {selected}/{self.sub_count}. "
        if not selected: text += "Индивидуальные сечения, зонды и расчётные отчёты не создаются. "
        text += "Повторный запуск сохраняет физику, граничные условия и решение."
        self.selection_hint.setText(text)

    def check_export_mesh(self):
        from mesh_quality import analyse_result, format_report, DEFAULT_PROFILE
        self.local_quality_text.setPlainText("Проверка…")
        try:
            report = analyse_result(self.mesh_result, profile=DEFAULT_PROFILE)
            self.local_quality_text.setPlainText(format_report(report))
        except Exception as exc:
            self.local_quality_text.setPlainText(f"Проверка не завершена: {exc}")

    def on_topology_mode_changed(self):
        is_intf = self.rb_inter_intf.isChecked()
        self.chk_gap_sections.setEnabled(not is_intf)
        if is_intf:
            self.rb_io_split.setChecked(True)
            self.rb_io_split.setEnabled(True)
            self.rb_io_single.setEnabled(False)
            self.rb_wall_by_rod.setChecked(True)
            self.rb_wall_by_rod.setEnabled(True)
            self.rb_wall_60.setEnabled(True)
            self.rb_wall_60.setToolTip("")
            self.rb_wall_rod.setEnabled(False)
        else:
            self.rb_io_single.setChecked(True)
            self.rb_io_single.setEnabled(True)
            self.rb_io_split.setEnabled(False)
            self.rb_wall_by_rod.setChecked(True)
            self.rb_wall_by_rod.setEnabled(True)
            self.rb_wall_60.setEnabled(False)
            self.rb_wall_60.setToolTip("После Fuse исходные секторы 60° не сохраняются; доступна группировка по стержням.")
            self.rb_wall_rod.setEnabled(True)

    def update_dz_hint(self):
        n = self.spin_n_planes.value()
        if n > 1:
            dz_mm = (self.lz_m / (n - 1)) * 1000.0
            self.lbl_dz_hint.setText(f"• Длина канала L = {self.lz_m*1000:.1f} мм. При N = {n} шаг между общими сечениями Δz = {dz_mm:.2f} мм")
        m = self.spin_sub_n_planes.value()
        if m > 1:
            dz_sub_mm = (self.lz_m / (m - 1)) * 1000.0
            self.lbl_sub_dz_hint.setText(f"• Шаг между сечениями ячейки при M = {m}: Δz_sub = {dz_sub_mm:.2f} мм")

    def read_options(self):
        w_mode = "by_rod"
        if self.rb_wall_60.isChecked():
            w_mode = "sectors_60"
        elif self.rb_wall_rod.isChecked():
            w_mode = "monolithic"

        sel_subs = [idx + 1 for idx, cb in enumerate(self.sub_checkboxes) if cb.isChecked()]

        return {
            "import_mesh": self.chk_import.isChecked(),
            "inner_fuse": True,
            "inter_fuse": self.rb_inter_fuse.isChecked(),
            "region_mode": "by_subchannel" if not self.rb_inter_fuse.isChecked() else "monolithic",
            "inlet_outlet_mode": "single" if self.rb_io_single.isChecked() else "by_subchannel",
            "rename_boundaries": True,
            "rod_wall_mode": w_mode,
            "turbulence_model": "hybrid_srh" if self.rb_turb_srh.isChecked() else "rst",
            "use_iapws": self.rb_eos_iapws.isChecked(),
            "enable_thermal": self.chk_thermal.isChecked(),
            "enable_gravity": self.chk_gravity.isChecked(),
            "gravity_axis": self.combo_gravity.currentText(),
            "evaluate_solution_reports": self.chk_evaluate_solution.isChecked(),
            "create_parameters": self.chk_params.isChecked(),
            "create_physics": True,
            "initialize_solution": self.chk_initialize.isChecked(),
            "create_mass_reports": self.chk_reports.isChecked(),
            "create_quality_scene": self.chk_scene.isChecked(),
            "create_quality_histograms": self.chk_histograms.isChecked(),
            "quality_bins": self.spin_quality_bins.value(),
            "gap_sections": self.chk_gap_sections.isChecked() and self.chk_gap_sections.isEnabled(),
            "n_planes": self.spin_n_planes.value() if self.chk_g_n_planes.isChecked() else 0,
            "n_sub_planes": self.spin_sub_n_planes.value() if self.chk_sub_n_planes.isChecked() else 0,
            "key_planes": self.chk_g_key_planes.isChecked(),
            "sub_planes": self.chk_sub_planes.isChecked(),
            "axis_probes": self.chk_axis_probes.isChecked(),
            "create_bad_cells": self.chk_bad_cells.isChecked(),
            "group_objects": self.chk_group_objects.isChecked(),
            "create_summary": self.chk_summary.isChecked(),
            "create_field_functions": self.chk_field_functions.isChecked(),
            "field_functions": [k for k, cb in self.field_checkboxes.items() if cb.isChecked()],
            "subchannel_reports": [k for k, cb in self.report_checkboxes.items() if cb.isChecked()],
            "time_mean_fields": [k for k, cb in self.mean_checkboxes.items() if cb.isChecked()],
            "mean_start_step": self.spin_mean_start.value(),
            "selected_subchannels": sel_subs
        }

    def apply_options(self, options):
        values = validate_options(options, self.sub_count)
        # Validate everything before changing the GUI.
        self.rb_inter_fuse.setChecked(values['inter_fuse'])
        self.rb_inter_intf.setChecked(not values['inter_fuse'])
        self.on_topology_mode_changed()
        for key, attr in dict(initialize_solution='chk_initialize', import_mesh='chk_import', use_iapws='rb_eos_iapws',
            enable_thermal='chk_thermal', enable_gravity='chk_gravity', evaluate_solution_reports='chk_evaluate_solution', create_parameters='chk_params',
            create_mass_reports='chk_reports', create_quality_scene='chk_scene',
            create_quality_histograms='chk_histograms', gap_sections='chk_gap_sections',
            key_planes='chk_g_key_planes', sub_planes='chk_sub_planes', axis_probes='chk_axis_probes',
            create_bad_cells='chk_bad_cells', group_objects='chk_group_objects',
            create_summary='chk_summary', create_field_functions='chk_field_functions').items():
            getattr(self, attr).setChecked(values[key])
        self.rb_eos_const.setChecked(not values['use_iapws'])
        self.rb_turb_srh.setChecked(values['turbulence_model']=='hybrid_srh')
        self.rb_turb_rst.setChecked(values['turbulence_model']=='rst')
        self.rb_wall_by_rod.setChecked(values['rod_wall_mode']=='by_rod')
        self.rb_wall_60.setChecked(values['rod_wall_mode']=='sectors_60')
        self.rb_wall_rod.setChecked(values['rod_wall_mode']=='monolithic')
        self.combo_gravity.setCurrentText(values['gravity_axis'])
        self.spin_quality_bins.setValue(values['quality_bins'])
        self.chk_g_n_planes.setChecked(values['n_planes']!=0)
        self.chk_sub_n_planes.setChecked(values['n_sub_planes']!=0)
        if values['n_planes']:self.spin_n_planes.setValue(values['n_planes'])
        if values['n_sub_planes']:self.spin_sub_n_planes.setValue(values['n_sub_planes'])
        for i, checkbox in enumerate(self.sub_checkboxes,1):
            checkbox.setChecked(i in values['selected_subchannels'])
        for key, checkboxes in (('field_functions', self.field_checkboxes), ('subchannel_reports', self.report_checkboxes), ('time_mean_fields', self.mean_checkboxes)):
            for name, checkbox in checkboxes.items(): checkbox.setChecked(name in values[key])
        self.spin_mean_start.setValue(values['mean_start_step'])
        self.update_dz_hint()
        self.update_dependencies()

    def save_export_profile(self):
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить профиль экспорта", "star_export.json", "JSON (*.json)")
        if path:
            try:save_profile(self.read_options(), path)
            except (OSError, ValueError) as exc:QMessageBox.warning(self, "Профиль экспорта", str(exc))

    def load_export_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "Загрузить профиль экспорта", "", "JSON (*.json)")
        if path:
            try:self.apply_options(load_profile(path, self.sub_count))
            except (OSError, ValueError) as exc:QMessageBox.warning(self, "Профиль экспорта", str(exc))

    def generate_and_save(self):
        if getattr(self,'_export_job',None) is not None:return
        if not getattr(self.mesh_result,'complete',True):
            QMessageBox.warning(self,'Экспорт недоступен','Сначала заполните ядро сетки.');return
        import starccm_macro_generator as smg
        import mesh_subchannel as ms

        macro_path, _ = QFileDialog.getSaveFileName(self, "Сохранить Java-макрос STAR-CCM+", "setup_starccm_subchannels.java", "Java files (*.java)")
        if not macro_path:
            return

        p_macro = Path(macro_path)
        p_xyz = p_macro.parent / self.edit_xyz.text().strip()

        try:
            same_path = p_macro.resolve() == p_xyz.resolve()
            if not same_path and p_macro.exists() and p_xyz.exists():
                same_path = p_macro.samefile(p_xyz)
        except (OSError, RuntimeError) as exc:
            QMessageBox.critical(self, "Ошибка путей", f"Не удалось проверить пути файлов:\n{exc}")
            return
        if same_path:
            QMessageBox.critical(self, "Совпадение путей", "Файл сетки XYZ и Java-макрос должны иметь разные пути.")
            return

        # Read all widgets in GUI thread before starting file work.
        try:opts=self.read_options()
        except Exception as exc:
            QMessageBox.critical(self,'Проверьте параметры',str(exc));return
        parent=self.parent()
        if parent is not None and hasattr(parent,'can_export_mesh') and (not parent.can_export_mesh() or parent.current_mesh_result is not self.mesh_result):
            QMessageBox.warning(self,'Экспорт недоступен','Сетка устарела; перестройте её.');return
        from copy import deepcopy
        import os,tempfile
        from mesh_export_jobs import run_export,ExportCancelled
        result=self.mesh_result;model=deepcopy(self.bundle_model)
        fluid=deepcopy(self.fluid_props);yp=deepcopy(self.yplus_data)
        def log(text):
            if parent is not None and hasattr(parent,'append_mesh_message'):parent.append_mesh_message(text)
        def compute(progress):
            progress(2,'Генерация Java-макроса')
            java_code=smg.generate_starccm_java_macro(xyz_filename=p_xyz.name,
                mesh_result=result,bundle_model=model,fluid_props=fluid,yplus_data=yp,options=opts)
            # Stage in destination directories; cancellation never publishes a
            # partial file. The two final replacements are separate OS actions.
            temporary=[]
            try:
                for target in (p_xyz,p_macro):
                    fd,name=tempfile.mkstemp(prefix='.mesh_export_',suffix='.tmp',dir=target.parent)
                    os.close(fd);temporary.append(name)
                progress(10,'Сохранение сетки Plot3D')
                ms.export_subchannel_plot3d(result,temporary[0],
                    progress_callback=lambda value,text:progress(10+int(value*.8),text))
                progress(91,'Сохранение Java-макроса')
                Path(temporary[1]).write_text(java_code,encoding='utf-8')
                progress(97,'Публикация готовых файлов')
                os.replace(temporary[0],p_xyz)
                try:os.replace(temporary[1],p_macro)
                except OSError as exc:
                    raise OSError(f'Сетка сохранена: {p_xyz}. Макрос не заменён: {p_macro}. {exc}') from exc
            finally:
                for name in temporary:
                    if os.path.exists(name):os.unlink(name)
            return p_xyz,p_macro
        def success(paths):
            log(f'Экспорт STAR-CCM+ завершён: {paths[0]} и {paths[1]}')
            QMessageBox.information(self,'Успешно',
                f'Сетка и Java-макрос созданы!\n{paths[0]}\n{paths[1]}\nВ STAR-CCM+: File → Macro → Play Macro…')
            self.accept()
        def failure(exc):
            log(f'Экспорт STAR-CCM+: {exc or "отменён"}')
            if not isinstance(exc,ExportCancelled):
                QMessageBox.critical(self,'Ошибка экспорта',f'Не удалось завершить экспорт:\n{exc}')
        log('Экспорт STAR-CCM+: подготовка сетки и макроса')
        run_export(self,'Экспорт STAR-CCM+',compute,success,failure)

    def reject(self):
        from mesh_export_jobs import defer_export_close
        if not defer_export_close(self):super().reject()

    def closeEvent(self,event):
        from mesh_export_jobs import defer_export_close
        if defer_export_close(self):event.ignore();return
        super().closeEvent(event)
