# -*- coding: utf-8 -*-
"""Диалог экспорта сетки Plot3D и генерации Java-макроса для Simcenter STAR-CCM+."""
from pathlib import Path

try:
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLineEdit,
        QSpinBox, QCheckBox, QPushButton, QLabel, QFileDialog,
        QMessageBox, QRadioButton, QButtonGroup, QDialog, QTabWidget
    )
    HAS_QT = True
except ImportError:
    HAS_QT = False


class StarCcmExportDialog(QDialog if HAS_QT else object):
    def __init__(self, parent=None, mesh_result=None, bundle_model=None, fluid_props=None, yplus_data=None):
        if not HAS_QT:
            return
        super().__init__(parent)
        self.setWindowTitle("Экспорт для Simcenter STAR-CCM+ (Plot3D + Java Macro v21.02+)")
        self.resize(700, 840)

        self.mesh_result = mesh_result
        self.bundle_model = bundle_model
        self.fluid_props = fluid_props or {}
        self.yplus_data = yplus_data or {}

        # Точная актуальная высота модели L_z (считывается из поля ввода высоты сетки):
        self.lz_m = 0.050
        if parent and hasattr(parent, "mesh_subpanel") and "z_len" in parent.mesh_subpanel.fields:
            self.lz_m = float(parent.mesh_subpanel.fields["z_len"].value())
        elif mesh_result and hasattr(mesh_result, "params"):
            p = mesh_result.params
            if hasattr(p, "z_len") and p.z_len is not None:
                self.lz_m = float(p.z_len)
            elif hasattr(p, "L") and p.L is not None:
                self.lz_m = float(p.L)

        # Количество подканалов:
        self.sub_count = getattr(mesh_result, "subchannels_count", 3) if mesh_result else 3

        main_lay = QVBoxLayout(self)

        lbl_header = QLabel(
            "<b>Комплексный генератор расчетной сцены Simcenter STAR-CCM+ (v3.15.0)</b><br>"
            "Автоматический импорт Plot3D-сетки, сопряжение интерфейсов (Centroids), настройка физики "
            "(RST / Hybrid SRH + IAPWS-IF97), глобальные параметры и паспорт гидравлики ячеек.",
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
        self.tabs.addTab(tab_mesh, "1. Сетка и топология")

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

        self.chk_gravity = QCheckBox("Учитывать гравитацию (GravityModel: g = -9.81 м/с² по оси Z)", grp_extra_phys)
        self.chk_gravity.setChecked(False)
        l_ep.addWidget(self.chk_gravity)
        l_tab2.addWidget(grp_extra_phys)
        l_tab2.addStretch()
        self.tabs.addTab(tab_phys, "2. Физика и свойства среды")

        # ----------------- ВКЛАДКА 3: Мониторы и параметры -----------------
        tab_mon = QWidget()
        l_tab3 = QVBoxLayout(tab_mon)

        grp_param = QGroupBox("1. Переменные в Tools > Parameters", tab_mon)
        l_p = QVBoxLayout(grp_param)
        self.chk_params = QCheckBox("Создать переменные: rho, Cp, dynvis, kinvis, lambda, Pr, T_ref, P_ref, Re_in, D_hyd, Ub, G...", tab_mon)
        self.chk_params.setChecked(True)
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

        grp_rep = QGroupBox("2. Отчеты расхода и баланса (сохраняются в дереве)", tab_mon)
        l_r = QVBoxLayout(grp_rep)
        self.chk_reports = QCheckBox("Создать отчеты баланса расхода (MassFlow_Inlet/Outlet_Total, Imbalance_MassFlow %)", grp_rep)
        self.chk_reports.setChecked(True)
        l_r.addWidget(self.chk_reports)
        l_tab3.addWidget(grp_rep)

        grp_qual = QGroupBox("3. Контроль качества сетки", tab_mon)
        l_q = QVBoxLayout(grp_qual)
        self.chk_scene = QCheckBox("Создать 3D-сцену контроля качества сетки (Quality_VolumeChange_Scene)", grp_qual)
        self.chk_scene.setChecked(True)
        l_q.addWidget(self.chk_scene)
        l_tab3.addWidget(grp_qual)
        l_tab3.addStretch()
        self.tabs.addTab(tab_mon, "3. Мониторы и параметры")

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
        self.chk_sub_planes = QCheckBox("Генерировать сечения раздельно для выбранных подканалов:", grp_sub_sec)
        self.chk_sub_planes.setChecked(True)
        l_ss.addWidget(self.chk_sub_planes)

        # Выбор подканалов чекбоксами:
        self.sub_checkboxes = []
        grid_subs = QHBoxLayout()
        for s in range(1, self.sub_count + 1):
            cb = QCheckBox(f"Subchannel_{s}", grp_sub_sec)
            cb.setChecked(True)
            self.sub_checkboxes.append(cb)
            grid_subs.addWidget(cb)
        l_ss.addLayout(grid_subs)

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
        l_ss.addLayout(row_sel_btns)

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

        grp_probes = QGroupBox("3. Линейные зонды (Line Sections)", tab_parts)
        l_pr = QVBoxLayout(grp_probes)
        self.chk_axis_probes = QCheckBox("Создать осевые зонды по центру живого сечения каждой ячейки (Probe_Axis_Sub_N)", grp_probes)
        self.chk_axis_probes.setChecked(True)
        l_pr.addWidget(self.chk_axis_probes)
        l_tab4.addWidget(grp_probes)
        l_tab4.addStretch()
        self.tabs.addTab(tab_parts, "4. Derived Parts & Сечения")

        main_lay.addWidget(self.tabs)
        self.on_topology_mode_changed()
        self.update_dz_hint()

        b_box = QHBoxLayout()
        btn_gen = QPushButton("🚀 Сгенерировать макрос (.java) и сетку Plot3D…", self)
        btn_gen.setProperty("btnClass", "primary")
        btn_gen.clicked.connect(self.generate_and_save)
        b_box.addWidget(btn_gen)

        btn_cancel = QPushButton("Отмена", self)
        btn_cancel.clicked.connect(self.reject)
        b_box.addWidget(btn_cancel)
        main_lay.addLayout(b_box)

    def on_topology_mode_changed(self):
        is_intf = self.rb_inter_intf.isChecked()
        if is_intf:
            self.rb_io_split.setChecked(True)
            self.rb_io_split.setEnabled(True)
            self.rb_io_single.setEnabled(False)
            self.rb_wall_by_rod.setChecked(True)
            self.rb_wall_by_rod.setEnabled(True)
            self.rb_wall_60.setEnabled(True)
            self.rb_wall_rod.setEnabled(False)
        else:
            self.rb_io_single.setChecked(True)
            self.rb_io_single.setEnabled(True)
            self.rb_io_split.setEnabled(False)
            self.rb_wall_by_rod.setChecked(True)
            self.rb_wall_by_rod.setEnabled(True)
            self.rb_wall_60.setEnabled(True)
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

    def generate_and_save(self):
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

        try:
            ms.export_subchannel_plot3d(self.mesh_result, str(p_xyz))
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка сохранения сетки", f"Не удалось экспортировать файл сетки:\n{exc}")
            return

        w_mode = "by_rod"
        if self.rb_wall_60.isChecked():
            w_mode = "sectors_60"
        elif self.rb_wall_rod.isChecked():
            w_mode = "monolithic"

        sel_subs = [idx + 1 for idx, cb in enumerate(self.sub_checkboxes) if cb.isChecked()]

        opts = {
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
            "create_parameters": self.chk_params.isChecked(),
            "create_physics": True,
            "create_mass_reports": self.chk_reports.isChecked(),
            "create_quality_scene": self.chk_scene.isChecked(),
            "n_planes": self.spin_n_planes.value() if self.chk_g_n_planes.isChecked() else 0,
            "n_sub_planes": self.spin_sub_n_planes.value() if self.chk_sub_n_planes.isChecked() else 0,
            "key_planes": self.chk_g_key_planes.isChecked(),
            "sub_planes": self.chk_sub_planes.isChecked(),
            "axis_probes": self.chk_axis_probes.isChecked(),
            "selected_subchannels": sel_subs
        }

        try:
            java_code = smg.generate_starccm_java_macro(
                xyz_filename=p_xyz.name,
                mesh_result=self.mesh_result,
                bundle_model=self.bundle_model,
                fluid_props=self.fluid_props,
                yplus_data=self.yplus_data,
                options=opts
            )
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка генерации макроса", f"Не удалось сгенерировать Java-макрос:\n{exc}\nФайл сетки уже экспортирован: {p_xyz}")
            return

        try:
            p_macro.write_text(java_code, encoding="utf-8")
            QMessageBox.information(
                self, "Успешно",
                f"Сетка и Java-макрос успешно созданы!\n\n"
                f"• Файл сетки Plot3D: {p_xyz.name}\n"
                f"• Скрипт STAR-CCM+: {p_macro.name}\n\n"
                f"Для запуска в STAR-CCM+: File -> Macro -> Play Macro... -> выберите {p_macro.name}"
            )
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка сохранения макроса", f"Не удалось записать Java файл:\n{exc}")
