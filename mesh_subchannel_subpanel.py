# -*- coding: utf-8 -*-
"""Подпанель параметров сеточной модели на базе ядра 0.6.6 (Версия 3.13.2) с IAPWS-97, Ideal Gas и строгой точкой."""
import math, sys, traceback
from pathlib import Path
import numpy as np

try:
    from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
    from PySide6.QtWidgets import (
        QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QLineEdit,
        QSpinBox, QComboBox, QCheckBox, QPushButton, QLabel, QFileDialog,
        QMessageBox, QSplitter, QScrollArea, QPlainTextEdit, QTreeWidget,
        QTreeWidgetItem, QRadioButton, QButtonGroup, QDialog, QDoubleSpinBox,
        QTabWidget
    )
    from PySide6.QtGui import QFontDatabase
    HAS_QT = True
except ImportError:
    HAS_QT = False

import mesh_core as mc
import mesh_quality as mq
from mesh_core import (
    CoreParams, GeometryParams, WallLayerParams, MeshWorkflow, MeshParams,
    UNITS, LAWS, MODES, available_modes, shape_bounds,
    generate_mesh, save_mesh, fill_core
)
from mesh_ui import NumberValue, compact, length_text
from mesh_advisor import evaluate_mesh_hints, evaluate_azimuth_hint_for_assembly, format_friendly_error
from yplus_calculator import calculate_yplus_and_step, FLUID_MODES
from fluid_properties import water_iapws97, gas_properties, GAS_PRESETS
from starccm_export_dialog import StarCcmExportDialog
from yplus_dialog import YPlusDialog
from number_field import NumberField

FILTERED_UI_LAWS = {
    "geometric": "Геометрическое",
    "hyperbolic": "Гиперболическое (tanh/sinh)",
    "power": "Степенное",
    "uniform": "Равномерное",
    "wall_core": "Пристеночный слой"
}


class MeshSubpanel(QWidget if HAS_QT else object):
    def __init__(self, parent_window):
        if not HAS_QT:
            return
        super().__init__()
        self.parent_window = parent_window
        self.fields = {}
        self.workflow = MeshWorkflow()
        self.geometry_unit = "мм"
        self.cell_unit = "мкм"
        self.updating = True

        self.scope_mode = "all"
        self.selected_target_id = None
        self.yplus_saved_state = {}

        self.init_ui()
        self.apply_params(MeshParams(law="geometric", mode="first_count", h1=2.5e-6, nj=100))
        self.updating = False

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        top_bar = QHBoxLayout()
        self.btn_back = QPushButton("← Назад к сечению ТВС", self)
        self.btn_back.clicked.connect(self.parent_window.switch_to_geometry_mode)
        top_bar.addWidget(self.btn_back)
        layout.addLayout(top_bar)

        # -------------------------------------------------------------
        # ГРУППА 1: Область применения параметров
        # -------------------------------------------------------------
        grp_scope = QGroupBox("1. Область применения параметров", self)
        b_scope = QVBoxLayout(grp_scope)
        b_scope.setSpacing(6)

        lay_scope_radios = QHBoxLayout()
        self.radio_all = QRadioButton("Ко всем блокам", self)
        self.radio_all.setChecked(True)
        self.radio_all.toggled.connect(self.on_scope_changed)
        lay_scope_radios.addWidget(self.radio_all)

        self.radio_template = QRadioButton("По шаблону", self)
        self.radio_template.toggled.connect(self.on_scope_changed)
        lay_scope_radios.addWidget(self.radio_template)

        self.radio_block = QRadioButton("Для блока", self)
        self.radio_block.toggled.connect(self.on_scope_changed)
        lay_scope_radios.addWidget(self.radio_block)
        b_scope.addLayout(lay_scope_radios)

        self.combo_templates = QComboBox(self)
        self.combo_templates.currentIndexChanged.connect(self.on_template_combo_changed)
        b_scope.addWidget(self.combo_templates)

        self.combo_blocks = QComboBox(self)
        self.combo_blocks.currentIndexChanged.connect(self.on_block_combo_changed)
        b_scope.addWidget(self.combo_blocks)

        row_reset = QHBoxLayout()
        self.btn_reset_override = QPushButton("Сбросить переопределения в «По умолчанию»", self)
        self.btn_reset_override.clicked.connect(self.on_reset_override)
        row_reset.addWidget(self.btn_reset_override)
        b_scope.addLayout(row_reset)

        layout.addWidget(grp_scope)

        # Состав сетки
        grp_tree = QGroupBox("Состав сетки и статус назначения", self)
        b_tree = QVBoxLayout(grp_tree)

        self.tree_blocks = QTreeWidget(self)
        self.tree_blocks.setHeaderLabels(["Элемент сетки", "Статус назначения"])
        self.tree_blocks.itemClicked.connect(self.on_tree_item_clicked)
        b_tree.addWidget(self.tree_blocks)

        layout.addWidget(grp_tree)

        # -------------------------------------------------------------
        # ГРУППА 2: Параметры сетки по высоте (Z) и узлы
        # -------------------------------------------------------------
        grp_geom = QGroupBox("2. Параметры сетки по высоте (Z) и узлы", self)
        b_geom = QVBoxLayout(grp_geom)
        b_geom.setSpacing(6)

        self.lbl_assembly_info = QLabel("Геометрия пучка берётся автоматически из сечения ТВС.", self)
        self.lbl_assembly_info.setWordWrap(True)
        b_geom.addWidget(self.lbl_assembly_info)

        row_z = QHBoxLayout()
        lbl_z = QLabel("Z (мм):")
        w_z = self.number("z_len", 0.05, 1e-3, 1e-18, 1000.0, onchange=self.on_field_changed)
        lbl_nz = QLabel("nz (слоёв):")
        w_nz = self.integer("nz", 10, 1, 1000000, onchange=self.on_field_changed)
        row_z.addWidget(lbl_z)
        row_z.addWidget(w_z, 1)
        row_z.addWidget(lbl_nz)
        row_z.addWidget(w_nz, 1)
        b_geom.addLayout(row_z)

        self.lbl_z_step = QLabel(self)
        b_geom.addWidget(self.lbl_z_step)

        row_ni = QHBoxLayout()
        lbl_ni = QLabel("Узлов по дуге (ni):")
        w_ni = self.integer("ni", 120, 2, onchange=self.on_field_changed)
        row_ni.addWidget(lbl_ni)
        row_ni.addWidget(w_ni, 1)
        b_geom.addLayout(row_ni)

        self.lbl_azimuth_step = QLabel(self)
        b_geom.addWidget(self.lbl_azimuth_step)

        layout.addWidget(grp_geom)

        # -------------------------------------------------------------
        # ГРУППА 3: Распределение ячеек по нормали
        # -------------------------------------------------------------
        grp_dist = QGroupBox("3. Распределение ячеек по нормали", self)
        b_dist = QVBoxLayout(grp_dist)
        b_dist.setSpacing(6)

        row_unit_law = QHBoxLayout()
        lbl_cu = QLabel("Единицы:")
        self.cu = QComboBox(self)
        self.cu.addItems(list(UNITS))
        self.cu.setCurrentText("мкм")
        self.cu.currentTextChanged.connect(self.change_cell_unit)
        row_unit_law.addWidget(lbl_cu)
        row_unit_law.addWidget(self.cu, 1)

        lbl_law = QLabel("Закон:")
        self.law = QComboBox(self)
        for key, label in FILTERED_UI_LAWS.items():
            self.law.addItem(label, key)
        self.law.currentIndexChanged.connect(self.law_changed)
        row_unit_law.addWidget(lbl_law)
        row_unit_law.addWidget(self.law, 2)
        b_dist.addLayout(row_unit_law)

        self.hyper_func = QComboBox(self)
        self.hyper_func.addItem("tanh (двусторонний)", "tanh")
        self.hyper_func.addItem("sinh (от стенки)", "sinh")
        self.hyper_func.currentIndexChanged.connect(self.hyperbolic_changed)
        self.hyper_row = self.row(b_dist, "Функция гиперболы:", self.hyper_func)

        self.goal = QComboBox(self)
        self.goal.currentIndexChanged.connect(self.goal_changed)
        self.goal_row = self.row(b_dist, "Способ задания:", self.goal)

        row_h1_container = QWidget()
        lay_h1 = QHBoxLayout(row_h1_container)
        lay_h1.setContentsMargins(0, 0, 0, 0)
        lbl_h1 = QLabel("Размер h1:")
        lay_h1.addWidget(lbl_h1)

        self.w_h1 = self.number("h1", 2.5e-6, 1e-6, 1e-18, 1000.0, onchange=self.on_field_changed)
        lay_h1.addWidget(self.w_h1, 1)

        self.btn_yplus = QPushButton("🧮 y⁺…", self)
        self.btn_yplus.setToolTip("Рассчитать необходимый h1 из термодинамики IAPWS-97 / газа и числа Re")
        self.btn_yplus.clicked.connect(self.open_yplus_calculator)
        lay_h1.addWidget(self.btn_yplus)
        b_dist.addWidget(row_h1_container)
        self.h1_row = row_h1_container

        self.count_row = self.row(b_dist, "Число слоёв (nj):", self.integer("layers", 99, 2, onchange=self.on_field_changed))
        self.max_row = self.row(b_dist, "Предельный размер:", self.number("hmax", 30e-6, 1e-6, 1e-18, 1000.0, onchange=self.on_field_changed))
        self.growth_row = self.row(b_dist, "Коэффициент q:", self.number("growth_limit", 1.02, minimum=1.0, maximum=100.0, onchange=self.on_field_changed))

        self.layer_count_row = self.row(b_dist, "Слоёв в слое:", self.integer("layer_cells", 40, 2, 5000, onchange=self.on_field_changed))
        self.layer_thick_row = self.row(b_dist, "Толщина слоя:", self.number("layer_thickness", 0.35e-3, 1e-6, 1e-18, 1000.0, onchange=self.on_field_changed))
        self.layer_growth_row = self.row(b_dist, "Рост в слое q:", self.number("layer_growth", 1.05, minimum=1.0, maximum=100.0, onchange=self.on_field_changed))

        self.lbl_advisor_hint = QLabel(self)
        self.lbl_advisor_hint.setWordWrap(True)
        b_dist.addWidget(self.lbl_advisor_hint)

        self.btn_build_layer = QPushButton("Построить пристеночный слой", self)
        self.btn_build_layer.clicked.connect(self.parent_window.on_build_layer_only)
        self.btn_build_layer.setVisible(False)
        b_dist.addWidget(self.btn_build_layer)

        layout.addWidget(grp_dist)

        # -------------------------------------------------------------
        # ГРУППА 4: Выбор метода центрального узла в подканале
        # -------------------------------------------------------------
        grp_center = QGroupBox("4. Выбор метода центрального узла в подканале", self)
        b_center = QVBoxLayout(grp_center)
        b_center.setSpacing(6)

        row_cm = QHBoxLayout()
        lbl_cm = QLabel("Центральная точка:")
        lbl_cm.setStyleSheet("font-weight: 500;")
        self.combo_center_method = QComboBox(self)
        self.combo_center_method.addItem("Точка равного зазора", "equi_clearance")
        self.combo_center_method.addItem("Центроид треугольника", "centroid")
        self.combo_center_method.currentIndexChanged.connect(self.on_field_changed)
        row_cm.addWidget(lbl_cm)
        row_cm.addWidget(self.combo_center_method, 1)
        b_center.addLayout(row_cm)

        self.lbl_center_desc = QLabel(
            "✓ <b>Точка равного зазора (Аполлоний):</b> выравнивает толщину секторов у разнокалиберных стержней (НК/ИК и ТВЭЛ), устраняя сплющивание ячеек и скачки Volume Change в STAR-CCM+.",
            self
        )
        self.lbl_center_desc.setWordWrap(True)
        self.chk_hermite_tfi = QCheckBox("Ортогонализация к центру (Hermite TFI)", self)
        self.chk_hermite_tfi.setChecked(True)
        self.chk_hermite_tfi.setToolTip("Кубическое сглаживание по Эрмиту: выпрямляет лучи к центру подканала и ребру стыка секторов (O -> M) под углом ~90°.")
        self.chk_hermite_tfi.toggled.connect(self.on_field_changed)
        b_center.addWidget(self.chk_hermite_tfi)
        b_center.addWidget(self.lbl_center_desc)

        layout.addWidget(grp_center)

        # -------------------------------------------------------------
        # ГРУППА 5: Заполнение ядра подканала
        # -------------------------------------------------------------
        self.core_group = QGroupBox("5. Заполнение ядра подканала", self)
        b_core = QVBoxLayout(self.core_group); b_core.setSpacing(6)

        self.combo_core_mode = QComboBox(self)
        self.combo_core_mode.addItem("Плавный рост от призмы (CFD)", "cfd_growth")
        self.combo_core_mode.addItem("Изотропное ядро (Аспект ≈ 1.0)", "isotropic")
        self.combo_core_mode.addItem("Фиксированное число слоёв", "fixed_count")
        self.combo_core_mode.currentIndexChanged.connect(self.on_core_mode_changed)
        self.row(b_core, "Режим ядра:", self.combo_core_mode)

        self.core_transition_row = self.row(
            b_core, "Коэф. перехода (ядро / призма):",
            self.number("core_transition", 1.1, minimum=0.1, maximum=10.0, onchange=self.on_field_changed)
        )
        self.core_growth_row = self.row(
            b_core, "Коэф. роста в ядре (q):",
            self.number("core_growth", 1.1, minimum=1.0, maximum=100.0, onchange=self.on_field_changed)
        )

        core_size_w = QWidget(self)
        core_size_l = QHBoxLayout(core_size_w); core_size_l.setContentsMargins(0, 0, 0, 0)
        self.w_core_max_size = self.number("core_max_size", 120e-6, 1e-6, 1e-18, 1000.0, onchange=self.on_field_changed)
        self.lbl_core_size_unit = QLabel(self.cell_unit, self)
        self.lbl_core_size_unit.setStyleSheet("color: #37474f; font-weight: bold;")
        core_size_l.addWidget(self.w_core_max_size, 1)
        core_size_l.addWidget(self.lbl_core_size_unit)
        self.core_maxsize_row = self.row(b_core, "Целевой размер в ядре:", core_size_w)

        self.core_layers_row = self.row(
            b_core, "Число слоёв ядра (слои):",
            self.integer("core_layers", 20, 1, 500, onchange=self.on_field_changed)
        )
        self.integer("core_max_cells", 5000, 1, 100000, onchange=self.on_field_changed).setVisible(False)

        self.lbl_core_preview = QLabel(self)
        self.lbl_core_preview.setWordWrap(True)
        self.lbl_core_preview.setStyleSheet("padding: 6px; border-radius: 4px; font-size: 11px; background: #e8f5e9; color: #1b5e20; border: 1px solid #c8e6c9;")
        b_core.addWidget(self.lbl_core_preview)

        self.btn_fill_core = QPushButton("Заполнить ядро сетки", self)
        self.btn_fill_core.setEnabled(False)
        self.btn_fill_core.clicked.connect(self.parent_window.on_fill_core_clicked)
        b_core.addWidget(self.btn_fill_core)
        self.core_group.setVisible(False)
        layout.addWidget(self.core_group)

        # -------------------------------------------------------------
        # Кнопки действия и статус
        # -------------------------------------------------------------
        self.btn_build = QPushButton("Собрать полную 3D сетку", self)
        self.btn_build.setProperty("btnClass", "primary")
        self.btn_build.setMinimumHeight(32)
        self.btn_build.clicked.connect(self.parent_window.on_build_multiblock_mesh)
        layout.addWidget(self.btn_build)

        row_act = QHBoxLayout()
        self.btn_quality = QPushButton("Контроль качества", self)
        self.btn_quality.setEnabled(False)
        self.btn_quality.clicked.connect(self.parent_window.on_check_quality)
        row_act.addWidget(self.btn_quality)

        self.btn_export = QPushButton("Экспорт Plot3D (XYZ)…", self)
        self.btn_export.setProperty("btnClass", "export")
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.parent_window.on_export_plot3d)
        row_act.addWidget(self.btn_export)

        self.btn_export_star = QPushButton("Экспорт STAR-CCM+…", self)
        self.btn_export_star.setEnabled(False)
        self.btn_export_star.setProperty("btnClass", "export")
        self.btn_export_star.clicked.connect(self.parent_window.on_export_starccm_dialog)
        row_act.addWidget(self.btn_export_star)
        layout.addLayout(row_act)

        self.lbl_status = QLabel("Настройте параметры и нажмите кнопку построения.")
        self.lbl_status.setWordWrap(True)
        layout.addWidget(self.lbl_status)

        layout.addStretch()

    def number(self, key, val, factor=1.0, minimum=0.0, maximum=1e12, onchange=None):
        w = NumberField(val, factor, minimum, maximum)
        w.edited.connect(self.on_field_changed if onchange is None else onchange)
        self.fields[key] = w
        return w

    def integer(self, key, val, minimum=0, maximum=5000, onchange=None):
        w = QSpinBox()
        w.setRange(minimum, maximum)
        w.setValue(val)
        w.setKeyboardTracking(False)
        w.valueChanged.connect(self.on_field_changed if onchange is None else onchange)
        self.fields[key] = w
        return w

    def row(self, layout, label, widget):
        container = QWidget()
        r = QHBoxLayout(container)
        r.setContentsMargins(0, 0, 0, 0)
        lbl = QLabel(label)
        r.addWidget(lbl, 1)
        r.addWidget(widget, 1)
        layout.addWidget(container)
        return container

    def current_law(self):
        k = self.law.currentData()
        return self.hyper_func.currentData() or "tanh" if k == "hyperbolic" else k

    def hyperbolic_changed(self):
        if not self.updating:
            self.law_changed()

    def set_modes(self, preferred):
        law = self.current_law()
        self.goal.blockSignals(True)
        self.goal.clear()
        for k, lbl in available_modes(law).items():
            self.goal.addItem(lbl, k)
        self.goal.setCurrentIndex(max(0, self.goal.findData(preferred)))
        self.goal.blockSignals(False)
        self.refresh_controls()

    def refresh_controls(self):
        law, mode = self.current_law(), self.goal.currentData()
        if mode is None:
            return
        geometric = (law == "geometric")
        hyper = law in ("tanh", "sinh")
        power = (law == "power")
        uniform = (law == "uniform")
        layer = (law == "wall_core")

        self.core_group.setVisible(layer)
        self.hyper_row.setVisible(hyper)
        self.btn_build_layer.setVisible(layer)

        self.h1_row.setVisible(not uniform and mode != "shape_count" and not (layer and mode == "layer_growth"))
        self.count_row.setVisible(mode in ("first_count", "shape_count"))
        self.max_row.setVisible(mode == "first_max")
        self.growth_row.setVisible(geometric and mode == "first_growth")

        self.layer_count_row.setVisible(layer)
        self.layer_thick_row.setVisible(layer and mode in ("layer_thickness", "layer_growth"))
        self.layer_growth_row.setVisible(layer and mode in ("layer_growth", "layer_first_growth"))
        if hasattr(self, "combo_core_mode"):
            cmode = self.combo_core_mode.currentData()
            self.core_growth_row.setVisible(cmode in ("cfd_growth", "isotropic"))
            self.core_maxsize_row.setVisible(cmode == "cfd_growth")
            self.core_layers_row.setVisible(cmode == "fixed_count")
            self.update_core_preview()
        self.update_live_advisor_hint()

    def law_changed(self):
        if self.updating:
            return
        law = self.current_law()
        if law == "geometric":
            self.fields["growth_limit"].setValue(1.02)
        self.set_modes(self.goal.currentData())
        self.on_field_changed()

    def goal_changed(self):
        if not self.updating:
            self.refresh_controls()
            self.on_field_changed()

    def on_core_mode_changed(self):
        if not self.updating:
            self.refresh_controls()
            self.on_field_changed()

    def update_core_preview(self):
        if not hasattr(self, "lbl_core_preview"): return
        try:
            q_trans = self.fields["core_transition"].value()
            q_core = self.fields["core_growth"].value()
            h_target = self.fields["core_max_size"].value()
            n_layers = self.fields["core_layers"].value()
            max_cells = self.fields["core_max_cells"].value()
            cmode = self.combo_core_mode.currentData()
            p_curr = self.read_params()

            if p_curr.law == "wall_core":
                w_wall, _ = mc.layer_distribution(p_curr)
                h_last = float(w_wall[-1])
                delta_new = float(np.sum(w_wall))
            else:
                h_last = float(self.fields["h1"].value())
                delta_new = None

            h_core1 = h_last * q_trans
            vol_change = max(q_trans, 1.0 / max(q_trans, 1e-9))
            unit_lbl = self.cell_unit
            scale = 1.0 / UNITS[unit_lbl]
            nd = {"мкм": 2, "мм": 4, "м": 6}.get(unit_lbl, 3)

            est_lines = []
            warn = None
            pw = self.parent_window
            layer_res = getattr(pw, "current_layer_result", None)
            if layer_res is None:
                cmr = getattr(pw, "current_mesh_result", None)
                if cmr is not None and not getattr(cmr, "complete", True):
                    layer_res = cmr
            if layer_res is not None and getattr(layer_res, "geom_data", None) and delta_new is not None:
                try:
                    rems = []
                    for g in layer_res.geom_data:
                        rems.append(g["lengths"] - g["layer_thickness"])
                    rem = np.concatenate(rems)
                    delta_built = float(np.sum(layer_res.layer_widths[0])) if getattr(layer_res, "layer_widths", None) is not None else delta_new
                    rem = rem + (delta_built - delta_new)
                    h0v = np.full(rem.shape, h_last, dtype=float)
                    eff_max = max(h_target, h_core1 * 1.01)
                    if cmode == "fixed_count":
                        dist = mc.fixed_count_distribution(rem, h0v, n_layers, transition_ratio=q_trans)
                    else:
                        dist = mc.capped_distribution(rem, h0v, q_core, eff_max, max_cells, transition_ratio=q_trans)
                    plat_min = float(dist.plateau.min())
                    plat_max = float(dist.plateau.max())
                    lmin_disp = float(rem.min()) * scale
                    est_lines.append(f"N = ⌊{lmin_disp:.{nd}f} / {h_core1*scale:.{nd}f}⌋ = {dist.count} "
                                     f"(узкий луч ÷ h₁ ядра)")
                    est_lines.append(f"последняя ячейка: зазор ≈ {plat_min*scale:.{nd}f} … центр ≈ {plat_max*scale:.{nd}f} {unit_lbl}")
                    if q_core <= 1.0 + 1e-12:
                        est_lines.append("режим: равномерное ядро (все ячейки ≈ h₁)")
                    opp_steps = [float(g["ds_opp"]) for g in layer_res.geom_data if "ds_opp" in g]
                    if opp_steps:
                        ds_min = min(opp_steps)
                        ar_center = plat_max / max(ds_min, 1e-12)
                        est_lines.append(f"аспект ячейки в центре ≈ {ar_center:.1f} : 1 "
                                         f"(шаг по лучу {plat_max*scale:.{nd}f} / поперёк {ds_min*scale:.{nd}f} {unit_lbl})")
                        if ar_center > 1.6:
                            warn = (f"ячейки в центре вытянуты (≈{ar_center:.1f}:1). Чтобы приблизить к 1:1 — "
                                    f"уменьшите целевой размер, увеличьте N (меньше коэф. перехода / тоньше призма) "
                                    f"или уменьшите ni.")
                except Exception:
                    pass

            hl = h_last * scale
            hc = h_core1 * scale
            ht = h_target * scale
            lines = []
            lines.append(f"▪ Призма (посл. слой): h_призм = {hl:.{nd}f} {unit_lbl}")
            if cmode == "cfd_growth" and q_core <= 1.0 + 1e-12:
                lines.append(f"▪ Ядро: h₁ = q_пер × h_призм = {q_trans:.2f} × {hl:.{nd}f} = {hc:.{nd}f} {unit_lbl}")
                lines.append(f"▪ Режим: равномерное ядро, все ячейки ≈ h₁")
            elif cmode == "cfd_growth":
                lines.append(f"▪ Ядро: h₁ = q_пер × h_призм = {q_trans:.2f} × {hl:.{nd}f} = {hc:.{nd}f} {unit_lbl}")
                lines.append(f"▪ Рост: q = {q_core:.2f} → плато h_t = {ht:.{nd}f} {unit_lbl}")
            elif cmode == "isotropic":
                lines.append(f"▪ Ядро: h₁ = q_пер × h_призм = {q_trans:.2f} × {hl:.{nd}f} = {hc:.{nd}f} {unit_lbl}")
                lines.append(f"▪ Рост: q = {q_core:.2f}, цель ≈ шаг поперёк лучей")
            else:
                lines.append(f"▪ Ядро: h₁ = q_пер × h_призм = {q_trans:.2f} × {hl:.{nd}f} = {hc:.{nd}f} {unit_lbl}")
                lines.append(f"▪ Задано слоёв: {n_layers}")
            lines.append(f"▪ Перепад на стыке призма→ядро: {vol_change:.2f} ×")
            lines.extend(est_lines)
            txt = "\n".join(lines)
            if warn:
                txt += f"\n⚠ {warn}"
                self.lbl_core_preview.setStyleSheet("padding: 6px; border-radius: 4px; font-size: 11px; background: #fffde7; color: #f57f17; border: 1px solid #ffe082;")
            elif est_lines and cmode != "fixed_count" and q_core > 1.0 + 1e-12 and plat_max > eff_max * 1.02:
                txt += (f"\n⚠ узкий зазор ограничил N: в центре ячейки крупнее цели ({eff_max*scale:.0f} {unit_lbl})")
                self.lbl_core_preview.setStyleSheet("padding: 6px; border-radius: 4px; font-size: 11px; background: #fffde7; color: #f57f17; border: 1px solid #ffe082;")
            else:
                self.lbl_core_preview.setStyleSheet("padding: 6px; border-radius: 4px; font-size: 11px; background: #e8f5e9; color: #1b5e20; border: 1px solid #c8e6c9;")
            self.lbl_core_preview.setText(txt)
        except Exception:
            pass

    def on_field_changed(self):
        if self.updating:
            return
        self.update_live_advisor_hint()
        self.update_core_preview()
        self.save_current_ui_to_active_scope()
        self.update_tree_status()

    def update_live_advisor_hint(self):
        try:
            z_val = self.fields["z_len"].value()
            nz_val = max(1, self.fields["nz"].value())
            dz_mm = (z_val * 1e3) / nz_val
            self.lbl_z_step.setText(f"💡 Шаг по высоте: Δz = {dz_mm:.2f} мм ({nz_val} слоёв)")
        except Exception:
            pass

        try:
            ni_val = self.fields["ni"].value()
            m = getattr(self.parent_window, "model", None)
            rods_d = m.rods if m else None
            self.lbl_azimuth_step.setText(
                evaluate_azimuth_hint_for_assembly(ni_val, rods_d, unit=self.cell_unit, uscale=1.0 / UNITS[self.cell_unit])
            )
        except Exception:
            pass

        law = self.current_law()
        mode = self.goal.currentData() or "first_count"

        if law == "wall_core" and mode == "layer_first_growth":
            h1_val = self.fields["h1"].value()
            n_val = self.fields["layer_cells"].value()
            q_val = self.fields["layer_growth"].value()
            if abs(q_val - 1.0) < 1e-12:
                delta_m = h1_val * n_val
                h_last_m = h1_val
            else:
                delta_m = h1_val * (q_val ** n_val - 1.0) / (q_val - 1.0)
                h_last_m = h1_val * (q_val ** (n_val - 1))
            u = self.cell_unit
            sc = 1.0 / UNITS[u]
            txt = (f"✓ Слой CFD: толщина δ = {delta_m*1e3:.3f} мм, "
                   f"последняя ячейка h_призм = {h_last_m*sc:.2f} {u} (q = {q_val:.2f})")
            self.lbl_advisor_hint.setVisible(True)
            self.lbl_advisor_hint.setText(txt)
            self.lbl_advisor_hint.setStyleSheet("padding: 6px; border-radius: 4px; font-size: 11px; background: #e8f5e9; color: #1b5e20; border: 1px solid #c8e6c9;")
            return

        min_gap = 0.95
        if hasattr(self.parent_window, "instances_lookup") and self.parent_window.instances_lookup:
            min_gap = min(inst.length_gap_mm * 2.0 for inst in self.parent_window.instances_lookup.values())

        status, text = evaluate_mesh_hints(law, mode, self.fields, min_gap_mm=min_gap,
                                           unit=self.cell_unit, uscale=1.0 / UNITS[self.cell_unit])
        if not text:
            self.lbl_advisor_hint.setVisible(False)
            return

        self.lbl_advisor_hint.setVisible(True)
        self.lbl_advisor_hint.setText(text)
        if status == "ok":
            self.lbl_advisor_hint.setStyleSheet("padding: 6px; border-radius: 4px; font-size: 11px; background: #e8f5e9; color: #1b5e20;")
        elif status == "warning":
            self.lbl_advisor_hint.setStyleSheet("padding: 6px; border-radius: 4px; font-size: 11px; background: #fffde7; color: #f57f17; border: 1px solid #ffe082;")
        else:
            self.lbl_advisor_hint.setStyleSheet("padding: 6px; border-radius: 4px; font-size: 11px; background: #ffebee; color: #b71c1c; border: 1px solid #ffcdd2;")

    def open_yplus_calculator(self):
        m = getattr(self.parent_window, "model", None)
        dh = 14.0
        af = 100.0
        if m:
            s = None
            if m.selected_subchannels and hasattr(m, "get_selection_summary"):
                s = m.get_selection_summary()
            elif hasattr(m, "get_total_assembly_summary"):
                s = m.get_total_assembly_summary()
            if s:
                dh = s.get("total_d_h_mm", s.get("total_dh_mm", 14.0))
                af = s.get("total_a_fluid_mm2", 100.0)

        dlg = YPlusDialog(self, d_hyd_mm=dh, a_fluid_mm2=af, target_field=self.fields["h1"], state_dict=self.yplus_saved_state)
        dlg.exec()
        for _attr in ("current_fluid_props", "last_yplus_result"):
            _val = getattr(dlg, _attr, None)
            if _val: setattr(self, _attr, _val)
        self.on_field_changed()

    def change_cell_unit(self, u):
        if self.updating:
            return
        keys = ("h1", "hmax", "layer_thickness", "core_max_size")
        try:
            for k in keys:
                if k in self.fields:
                    self.fields[k].setFactor(UNITS[u])
            self.cell_unit = u
            if hasattr(self, "lbl_core_size_unit"):
                self.lbl_core_size_unit.setText(u)
        except Exception:
            pass

    def read_params(self):
        f = self.fields
        law = self.current_law()
        mode = self.goal.currentData() or "first_count"

        pitch_val = self.parent_window.model.pitch * 1e-3 if hasattr(self.parent_window, "model") else 0.01275
        dfuel_val = getattr(self.parent_window.model, "d_fuel", getattr(self.parent_window.model, "dfuel", 9.1)) * 1e-3 if hasattr(self.parent_window, "model") else 0.0091

        if law == "wall_core":
            h1_val = f["h1"].value() if mode in ("layer_thickness", "layer_first_growth") else f["h1"].model.raw
            growth_val = f["layer_growth"].value() if mode in ("layer_growth", "layer_first_growth") else f["layer_growth"].model.raw
            if mode == "layer_first_growth":
                n_cells = f["layer_cells"].value()
                q_val = growth_val
                if abs(q_val - 1.0) < 1e-12:
                    thick_val = float(h1_val * n_cells)
                else:
                    thick_val = float(h1_val * (q_val ** n_cells - 1.0) / (q_val - 1.0))
            else:
                thick_val = f["layer_thickness"].value()

            return MeshParams(
                d_rod=dfuel_val, pitch=pitch_val, z_len=f["z_len"].value(),
                ni=f["ni"].value(), nz=f["nz"].value(), full=True, law=law, mode=mode,
                wall_layers=f["layer_cells"].value(), layer_thickness=thick_val,
                h1=h1_val,
                layer_growth=growth_val
            )

        if law == "geometric":
            shape = f["growth_limit"].value() if mode == "first_growth" else 1.02
        elif law in ("tanh", "sinh", "power"):
            shape = 2.0
        else:
            shape = 1.0

        return MeshParams(
            d_rod=dfuel_val, pitch=pitch_val, z_len=f["z_len"].value(),
            ni=f["ni"].value(), nj=f["layers"].value() + 1, nz=f["nz"].value(),
            h1=f["h1"].value() if law != "uniform" and mode != "shape_count" else f["h1"].model.raw,
            hmax=f["hmax"].value() if mode == "first_max" else f["hmax"].model.raw,
            full=True, law=law, mode=mode, shape=shape,
            wall_layers=f["layer_cells"].value(),
            transition_layers=0,
            smoothing="none",
            smoothing_percent=0.5,
            max_transition_layers=64,
            max_auto_cells=5000
        )

    def apply_params(self, p):
        self.updating = True
        try:
            self.fields["z_len"].setValue(p.z_len)
            self.fields["ni"].setValue(p.ni)
            self.fields["nz"].setValue(p.nz)
            if "layers" in self.fields:
                self.fields["layers"].setValue(p.nj - 1)
            self.law.setCurrentIndex(max(0, self.law.findData("hyperbolic" if p.law in ("tanh", "sinh") else p.law)))
            if p.law in ("tanh", "sinh"):
                self.hyper_func.setCurrentIndex(max(0, self.hyper_func.findData(p.law)))
            self.set_modes(p.mode)
            if p.law != "uniform" and p.mode != "shape_count":
                self.fields["h1"].setValue(p.h1)
            if p.mode == "first_max":
                self.fields["hmax"].setValue(p.hmax)
            if p.law == "geometric" and p.mode == "first_growth":
                self.fields["growth_limit"].setValue(p.shape)
        finally:
            self.updating = False
        self.refresh_controls()

    def save_current_ui_to_active_scope(self):
        p = self.read_params()
        if self.scope_mode == "all":
            self.parent_window.base_params = p
        elif self.scope_mode == "template":
            tid = self.combo_templates.currentData()
            if tid is not None:
                self.parent_window.template_configs[tid] = p
        elif self.scope_mode == "block":
            gid = self.combo_blocks.currentData()
            if gid is not None:
                self.parent_window.block_custom_configs[gid] = p

    def load_active_scope_to_ui(self):
        if self.scope_mode == "all":
            p = self.parent_window.base_params
        elif self.scope_mode == "template":
            tid = self.combo_templates.currentData()
            p = self.parent_window.template_configs.get(tid, self.parent_window.base_params)
        elif self.scope_mode == "block":
            gid = self.combo_blocks.currentData()
            tid = self.parent_window.get_template_for_block(gid)
            fallback = self.parent_window.template_configs.get(tid, self.parent_window.base_params)
            p = self.parent_window.block_custom_configs.get(gid, fallback)
        else:
            p = self.parent_window.base_params

        self.apply_params(p)

    def on_scope_changed(self):
        if self.radio_all.isChecked():
            self.scope_mode = "all"
        elif self.radio_template.isChecked():
            self.scope_mode = "template"
        elif self.radio_block.isChecked():
            self.scope_mode = "block"
        self.load_active_scope_to_ui()

    def on_template_combo_changed(self, idx):
        if self.radio_template.isChecked():
            self.load_active_scope_to_ui()

    def on_block_combo_changed(self, idx):
        if self.radio_block.isChecked():
            gid = self.combo_blocks.currentData()
            if gid is not None:
                self.load_active_scope_to_ui()
                self.parent_window.highlight_mesh_block(gid)

    def on_reset_override(self):
        if self.scope_mode == "template":
            tid = self.combo_templates.currentData()
            self.parent_window.template_configs.pop(tid, None)
        elif self.scope_mode == "block":
            gid = self.combo_blocks.currentData()
            self.parent_window.block_custom_configs.pop(gid, None)
        self.load_active_scope_to_ui()
        self.update_tree_status()
        self.parent_window.redraw_mesh_views()

    def populate_scope_and_tree(self, templates, instances):
        self.tree_blocks.clear()
        self.combo_templates.clear()
        self.combo_blocks.clear()

        if hasattr(self.parent_window, "model"):
            m = self.parent_window.model
            df_val = getattr(m, "d_fuel", getattr(m, "dfuel", 9.1))
            dg_val = getattr(m, "d_guide", getattr(m, "dguide", 12.0))
            txt = f"Геометрия ТВС: Шаг P = {m.pitch:.2f} мм | ТВЭЛ D = {df_val:.2f} мм | НК D = {dg_val:.2f} мм"
            self.lbl_assembly_info.setText(txt)

        for tid, tmpl in templates.items():
            self.combo_templates.addItem(f"Шаблон {tid}: {tmpl.name} ({tmpl.blocks_count} бл.)", tid)

        for inst in instances:
            lbl = f"Блок {inst.global_block_id} (Подканал S{inst.subchannel_id}, сектор {inst.block_index+1})"
            self.combo_blocks.addItem(lbl, inst.global_block_id)

        tmpl_items = {}
        for tid, tmpl in templates.items():
            t_item = QTreeWidgetItem(self.tree_blocks, [f"Шаблон {tid}: {tmpl.name}", f"{tmpl.blocks_count} бл."])
            t_item.setData(0, Qt.UserRole, ("template", tid))
            tmpl_items[tid] = t_item

        for inst in instances:
            t_item = tmpl_items.get(inst.template_id)
            if t_item:
                b_name = f"Блок {inst.global_block_id} (Подканал S{inst.subchannel_id}, сектор {inst.block_index+1})"
                b_item = QTreeWidgetItem(t_item, [b_name, "[По умолчанию]"])
                b_item.setData(0, Qt.UserRole, ("block", inst.global_block_id))

        self.tree_blocks.expandAll()
        self.update_tree_status()
        self.update_live_advisor_hint()

    def update_tree_status(self):
        for i in range(self.tree_blocks.topLevelItemCount()):
            t_item = self.tree_blocks.topLevelItem(i)
            tid = t_item.data(0, Qt.UserRole)[1]
            has_tmpl = (tid in self.parent_window.template_configs)
            tmpl_p = self.parent_window.template_configs.get(tid, self.parent_window.base_params)
            law_name = FILTERED_UI_LAWS.get(tmpl_p.law, tmpl_p.law)
            t_item.setText(1, f"[{law_name}]" if has_tmpl else "[По умолчанию]")

            for j in range(t_item.childCount()):
                b_item = t_item.child(j)
                gid = b_item.data(0, Qt.UserRole)[1]
                if gid in self.parent_window.block_custom_configs:
                    bp = self.parent_window.block_custom_configs[gid]
                    b_law = FILTERED_UI_LAWS.get(bp.law, bp.law)
                    b_item.setText(1, f"★ [{b_law}]")
                elif has_tmpl:
                    b_item.setText(1, f"[{law_name}]")
                else:
                    b_item.setText(1, "[По умолчанию]")

    def on_tree_item_clicked(self, item, col):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind, id_val = data
        if kind == "template":
            self.radio_template.setChecked(True)
            idx = self.combo_templates.findData(id_val)
            if idx >= 0:
                self.combo_templates.setCurrentIndex(idx)
        elif kind == "block":
            self.radio_block.setChecked(True)
            idx = self.combo_blocks.findData(id_val)
            if idx >= 0:
                self.combo_blocks.setCurrentIndex(idx)
            self.parent_window.highlight_mesh_block(id_val)
