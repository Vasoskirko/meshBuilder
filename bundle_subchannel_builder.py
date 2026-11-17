# -*- coding: utf-8 -*-
"""Интерактивный конструктор подканалов и сечения ТВС (версия 2.8).

Способы снятия выбора со стержня:
1. Клик по пустому месту холста (снаружи стержней и подканалов).
2. Повторный клик по уже выбранному стержню.
3. Кнопка «Снять выбор со стержня» в панели свойств.
4. Кнопка «Сбросить выбор» очищает как выбранные подканалы, так и стержень.
"""
import os
os.environ["QT_API"] = "pyside6"
import sys, math, json, csv
from pathlib import Path
import numpy as np

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QDialog, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QDoubleSpinBox, QComboBox, QPushButton, QLabel,
    QFileDialog, QMessageBox, QSplitter, QScrollArea,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from matplotlib.figure import Figure
from matplotlib.patches import Polygon, Circle
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT

from bundle_geometry import RodData, Subchannel, BundleModel
from PySide6.QtWidgets import (
    QStackedWidget, QTabWidget, QTreeWidget, QTreeWidgetItem, QRadioButton,
    QPlainTextEdit, QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtGui import QColor, QBrush
from matplotlib.collections import LineCollection
from mesh_subchannel_subpanel import MeshSubpanel
from block_classifier import classify_subchannel_blocks
from mesh_advisor import format_friendly_error
from mesh_gui import QualityDialog
from mesh_quality import DEFAULT_PROFILE
import mesh_core as mc
import mesh_quality as mq
import mesh_subchannel as ms


SCIENTIFIC_QSS = """
QWidget {
    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, "Roboto", "Helvetica Neue", sans-serif;
    font-size: 12px;
    color: #1e293b;
    background-color: #f8fafc;
}
QGroupBox {
    font-weight: 600;
    font-size: 12px;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    margin-top: 10px;
    padding-top: 12px;
    background-color: #ffffff;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 8px;
    padding: 0 4px;
    background-color: #ffffff;
}
QPushButton {
    background-color: #ffffff;
    color: #1e293b;
    border: 1px solid #94a3b8;
    border-radius: 3px;
    padding: 5px 12px;
    font-weight: 500;
    min-height: 22px;
}
QPushButton:hover {
    background-color: #f1f5f9;
    border-color: #64748b;
}
QPushButton:pressed {
    background-color: #e2e8f0;
    border-color: #475569;
}
QPushButton:disabled {
    background-color: #f1f5f9;
    color: #94a3b8;
    border-color: #cbd5e1;
}
QPushButton[btnClass="primary"] {
    background-color: #1e3a5f;
    color: #ffffff;
    border: 1px solid #142841;
    font-weight: 600;
}
QPushButton[btnClass="primary"]:hover {
    background-color: #2a4d7d;
    border-color: #1e3a5f;
}
QPushButton[btnClass="export"] {
    background-color: #2b4c7e;
    color: #ffffff;
    border: 1px solid #1d3557;
    font-weight: 600;
}
QPushButton[btnClass="export"]:hover {
    background-color: #3b629b;
    border-color: #2b4c7e;
}
QPushButton[btnClass="danger"] {
    background-color: #ffffff;
    color: #991b1b;
    border: 1px solid #f87171;
}
QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 3px;
    padding: 3px 6px;
    color: #0f172a;
    min-height: 22px;
}
QTabWidget::pane {
    border: 1px solid #cbd5e1;
    background-color: #ffffff;
    border-radius: 3px;
}
QTabBar::tab {
    background-color: #f1f5f9;
    border: 1px solid #cbd5e1;
    padding: 6px 12px;
    margin-right: 2px;
    border-top-left-radius: 3px;
    border-top-right-radius: 3px;
    font-weight: 500;
}
QTabBar::tab:selected {
    background-color: #ffffff;
    border-bottom-color: #ffffff;
    font-weight: 600;
    color: #1e3a5f;
}
QTableWidget, QTreeWidget {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    gridline-color: #f1f5f9;
    alternate-background-color: #f8fafc;
    font-size: 11px;
}
QHeaderView::section {
    background-color: #f1f5f9;
    color: #334155;
    font-weight: 600;
    padding: 4px 6px;
    border: none;
    border-right: 1px solid #e2e8f0;
    border-bottom: 1px solid #cbd5e1;
}
"""

class HydraulicsTableDialog(QDialog):
    def __init__(self, parent, model):
        super().__init__(parent)
        self.model = model
        self.setWindowTitle("Гидравлические характеристики подканалов ТВС")
        self.resize(960, 640)

        layout = QVBoxLayout(self)

        summary_group = QGroupBox("Сводные характеристики сборки ТВС")
        s_layout = QVBoxLayout(summary_group)
        self.summary_label = QLabel()
        self.summary_label.setTextFormat(Qt.RichText)
        self.summary_label.setWordWrap(True)
        s_layout.addWidget(self.summary_label)
        layout.addWidget(summary_group)

        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "ID подканала", "Тип", "Стержни", "Площадь A (мм²)",
            "Периметр P (мм)", "D_h (мм)", "Входит в расчёт"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table, 1)

        btn_layout = QHBoxLayout()
        btn_export = QPushButton("Экспорт таблицы в CSV…")
        btn_export.clicked.connect(self.export_csv)
        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(self.close)
        btn_layout.addWidget(btn_export)
        btn_layout.addStretch()
        btn_layout.addWidget(btn_close)
        layout.addLayout(btn_layout)

        self.populate_data()

    def populate_data(self):
        types_ru = {
            "interior": "Регулярные (ТВЭЛ)",
            "guide_sub": "С Направляющим Каналом (НК)",
            "instrument_sub": "С Инструментальным Каналом (ИК)",
            "peripheral": "Периферийные",
            "corner": "Угловые"
        }

        all_summary = self.model.get_total_assembly_summary()
        lines = ["<table border='0' cellpadding='4'><tr><th>Категория подканалов</th><th>Число</th><th>Ср. площадь A (мм²)</th><th>Ср. периметр P (мм)</th><th>Ср. D_h (мм)</th></tr>"]

        if all_summary:
            for st, data in all_summary["by_type"].items():
                cnt = data["count"]
                mean_a = data["a_fluid"] / cnt
                mean_p = data["p_wet"] / cnt
                dh = (4.0 * mean_a / mean_p) if mean_p > 0 else 0.0
                name = types_ru.get(st, st)
                lines.append(f"<tr><td><b>{name}</b></td><td>{cnt}</td><td>{mean_a:.2f}</td><td>{mean_p:.2f}</td><td><b>{dh:.2f}</b></td></tr>")

            lines.append(f"<tr style='background-color:#eaf2f8;'><td><b>ВСЯ СБОРКА ТВС (суммарно)</b></td><td><b>{all_summary['total_subchannels']}</b></td><td><b>{all_summary['total_a_fluid_mm2']:.2f}</b></td><td><b>{all_summary['total_p_wet_mm']:.2f}</b></td><td><b>{all_summary['total_d_h_mm']:.2f}</b></td></tr>")

        sel_summary = self.model.get_selection_summary()
        if sel_summary and sel_summary["total_subchannels"] != len(self.model.subchannels):
            lines.append(f"<tr style='background-color:#e8f8f5;'><td><b>ВЫБРАННАЯ ОБЛАСТЬ (суммарно)</b></td><td><b>{sel_summary['total_subchannels']}</b></td><td><b>{sel_summary['total_a_fluid_mm2']:.2f}</b></td><td><b>{sel_summary['total_p_wet_mm']:.2f}</b></td><td><b>{sel_summary['total_d_h_mm']:.2f}</b></td></tr>")

        lines.append("</table>")
        self.summary_label.setText("".join(lines))

        subs = sorted(self.model.subchannels.values(), key=lambda s: s.sub_id)
        self.table.setRowCount(len(subs))
        for row, s in enumerate(subs):
            rods_str = ", ".join(f"R{rid}" for rid in s.rod_ids)
            is_sel = "Да (выбран)" if s.sub_id in self.model.selected_subchannels else "Нет"

            self.table.setItem(row, 0, QTableWidgetItem(f"S{s.sub_id}"))
            self.table.setItem(row, 1, QTableWidgetItem(types_ru.get(s.sub_type, s.sub_type)))
            self.table.setItem(row, 2, QTableWidgetItem(rods_str))
            self.table.setItem(row, 3, QTableWidgetItem(f"{s.a_fluid_mm2:.2f}"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{s.p_wet_mm:.2f}"))
            self.table.setItem(row, 5, QTableWidgetItem(f"{s.d_h_mm:.2f}"))
            self.table.setItem(row, 6, QTableWidgetItem(is_sel))

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Экспорт характеристик подканалов", "subchannels_hydraulics.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["ID подканала", "Тип", "Стержни", "Площадь A (мм2)", "Смоченный периметр P (мм)", "Гидравлический диаметр Dh (мм)", "Выбран в расчет"])
                for row in range(self.table.rowCount()):
                    writer.writerow([self.table.item(row, col).text() for col in range(self.table.columnCount())])
            QMessageBox.information(self, "Экспорт завершён", f"Таблица успешно сохранена в:\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка записи", f"Не удалось записать CSV: {exc}")


class BundleBuilderWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Конструктор сечения ТВС и генератор сетки подканалов (CFD)")
        self.resize(1440, 880)
        self.model = BundleModel(s_flat=65.0, pitch=12.75, d_fuel=9.1, d_guide=12.0, d_instrument=10.3)

        self._pan_start = None
        self._custom_limits = None
        self.current_mesh_result = None
        self.current_layer_result = None
        self.current_quality_report = None
        self.base_params = mc.MeshParams(law="geometric", mode="first_count", h1=2.5e-6, nj=100)
        self.template_configs = {}
        self.block_custom_configs = {}
        self._mesh_drawn = False
        self.highlighted_block_id = None
        self.instances_lookup = {}
        self.active_plot_block_idx = 0

        self.ruler_active = False
        self.ruler_p1 = None
        self.ruler_line = None
        self.ruler_text = None

        self.setStyleSheet(SCIENTIFIC_QSS)
        self.init_ui()
        self.on_rebuild_geometry(silent=True)

    def init_ui(self):
        splitter = QSplitter(Qt.Horizontal, self)
        self.setCentralWidget(splitter)

        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(10, 10, 10, 10)

        # 1. Параметры геометрии пучка
        geom_group = QGroupBox("Параметры пучка и оболочки")
        gbox = QVBoxLayout(geom_group)

        row_lat = QHBoxLayout()
        row_lat.addWidget(QLabel("Тип решётки:"))
        self.lattice_combo = QComboBox()
        self.lattice_combo.addItem("Треугольная решётка", "triangular")
        self.lattice_combo.addItem("Квадратная решётка (в разработке)", "square")
        self.lattice_combo.model().item(1).setEnabled(False)
        row_lat.addWidget(self.lattice_combo)
        gbox.addLayout(row_lat)

        self.s_flat_spin = self.add_double_spin(gbox, "Размер под ключ S (шестигранник), мм:", 65.0, 15.0, 300.0, 0.5)
        self.pitch_spin = self.add_double_spin(gbox, "Шаг между стержнями P, мм:", 12.75, 5.0, 50.0, 0.05)
        self.d_fuel_spin = self.add_double_spin(gbox, "Базовый диаметр ТВЭЛ D_твэл, мм:", 9.1, 2.0, 40.0, 0.05)
        self.d_guide_spin = self.add_double_spin(gbox, "Диаметр НК D_нк (внешний), мм:", 12.0, 2.0, 40.0, 0.05)
        self.d_inst_spin = self.add_double_spin(gbox, "Диаметр ИК D_ик (внешний), мм:", 10.3, 2.0, 40.0, 0.05)

        rebuild_btn = QPushButton("Сбросить и перестроить пучок стержней")
        rebuild_btn.setStyleSheet("font-weight: bold; background-color: #e3edf7; padding: 6px;")
        rebuild_btn.clicked.connect(lambda: self.on_rebuild_geometry(silent=False))
        gbox.addWidget(rebuild_btn)

        left_layout.addWidget(geom_group)

        # 2. Подсказка по навигации
        nav_group = QGroupBox("Интеллектуальное управление")
        nbox = QVBoxLayout(nav_group)

        hint = QLabel("<b>Управление кликом мыши:</b><br>"
                      "&bull; <b>Клик по стержню</b> — выбор (повторный клик снимает выбор)<br>"
                      "&bull; <b>Клик по зазору / знакам (+) / (−)</b> — выбор подканала<br>"
                      "&bull; <b>Клик по пустому фону</b> — снять выбор со стержня<br>"
                      "&bull; <b>Колёсико</b> — зум к курсору<br>"
                      "&bull; <b>Правая/средняя кнопка</b> — панорамирование")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #2c3e50; background: #eaf2f8; padding: 7px; border-radius: 4px;")
        nbox.addWidget(hint)

        btn_fit = QPushButton("Вписать сечение в окно (1:1)")
        btn_fit.clicked.connect(self.on_fit_view)
        nbox.addWidget(btn_fit)

        left_layout.addWidget(nav_group)

        # 3. Инспектор элемента
        self.inspect_group = QGroupBox("Свойства выбранного элемента")
        ibox = QVBoxLayout(self.inspect_group)
        self.inspect_label = QLabel("Кликните на подканал (+) или на стержень для настройки.")
        self.inspect_label.setWordWrap(True)
        ibox.addWidget(self.inspect_label)

        self.rod_controls = QWidget()
        r_layout = QVBoxLayout(self.rod_controls)
        r_layout.setContentsMargins(0, 0, 0, 0)

        row_type = QHBoxLayout()
        row_type.addWidget(QLabel("Тип стержня:"))
        self.rod_type_combo = QComboBox()
        self.rod_type_combo.addItem("ТВЭЛ (базовый стержень)", "fuel")
        self.rod_type_combo.addItem("Направляющий Канал (НК)", "guide")
        self.rod_type_combo.addItem("Инструментальный Канал (ИК)", "instrument")
        self.rod_type_combo.currentIndexChanged.connect(self.on_rod_type_changed)
        row_type.addWidget(self.rod_type_combo)
        r_layout.addLayout(row_type)

        row_diam = QHBoxLayout()
        row_diam.addWidget(QLabel("Диаметр, мм:"))
        self.rod_diam_spin = QDoubleSpinBox()
        self.rod_diam_spin.setRange(2.0, 80.0)
        self.rod_diam_spin.setValue(9.1)
        self.rod_diam_spin.editingFinished.connect(self.apply_custom_rod_diameter)
        row_diam.addWidget(self.rod_diam_spin)

        btn_apply_diam = QPushButton("Применить")
        btn_apply_diam.clicked.connect(self.apply_custom_rod_diameter)
        row_diam.addWidget(btn_apply_diam)
        r_layout.addLayout(row_diam)

        # Кнопки снятия выбора и удаления стержня
        row_rod_actions = QHBoxLayout()
        btn_deselect_rod = QPushButton("Снять выбор со стержня")
        btn_deselect_rod.clicked.connect(self.on_deselect_rod)
        row_rod_actions.addWidget(btn_deselect_rod)

        self.btn_del_rod = QPushButton("Удалить стержень")
        self.btn_del_rod.setStyleSheet("color: #900C3F; font-weight: bold;")
        self.btn_del_rod.clicked.connect(self.on_delete_rod_manually)
        row_rod_actions.addWidget(self.btn_del_rod)
        r_layout.addLayout(row_rod_actions)

        self.btn_restore_rods = QPushButton("Восстановить удалённые стержни")
        self.btn_restore_rods.clicked.connect(self.on_restore_deleted_rods)
        r_layout.addWidget(self.btn_restore_rods)

        ibox.addWidget(self.rod_controls)
        self.rod_controls.setVisible(False)

        left_layout.addWidget(self.inspect_group)

        # 4. Сводка расчётной области
        summary_group = QGroupBox("Состав расчётной области и гидравлика")
        sbox = QVBoxLayout(summary_group)
        self.summary_text = QLabel("Подканалы не выбраны.")
        self.summary_text.setWordWrap(True)
        sbox.addWidget(self.summary_text)

        row_sel_btns = QHBoxLayout()
        btn_select_all = QPushButton("Выбрать ВСЕ подканалы")
        btn_select_all.setStyleSheet("background-color: #d4efdf; font-weight: bold;")
        btn_select_all.clicked.connect(self.on_select_all_subchannels)
        row_sel_btns.addWidget(btn_select_all)

        btn_clear = QPushButton("Сбросить выбор")
        btn_clear.clicked.connect(self.on_clear_selection)
        row_sel_btns.addWidget(btn_clear)
        sbox.addLayout(row_sel_btns)

        btn_table = QPushButton("Таблица характеристик подканалов…")
        btn_table.setStyleSheet("font-weight: bold; background-color: #eafaf1; padding: 5px;")
        btn_table.clicked.connect(self.open_hydraulics_table)
        sbox.addWidget(btn_table)

        self.btn_goto_mesh = QPushButton("Перейти к сеточной модели (CFD) →")
        self.btn_goto_mesh.setStyleSheet("font-weight: bold; background-color: #2e7d32; color: white; padding: 8px; font-size: 13px; border-radius: 4px;")
        self.btn_goto_mesh.clicked.connect(self.switch_to_mesh_mode)
        sbox.addWidget(self.btn_goto_mesh)

        left_layout.addWidget(summary_group)

        # 5. Экспорт / импорт
        io_row = QHBoxLayout()
        btn_save = QPushButton("Сохранить JSON…")
        btn_save.clicked.connect(self.on_save_json)
        btn_load = QPushButton("Загрузить JSON…")
        btn_load.clicked.connect(self.on_load_json)
        io_row.addWidget(btn_save)
        io_row.addWidget(btn_load)
        left_layout.addLayout(io_row)

        left_layout.addStretch()

        self.left_stack = QStackedWidget(self)

        self.scroll_geom = QScrollArea()
        self.scroll_geom.setWidgetResizable(True)
        self.scroll_geom.setWidget(left_widget)
        self.left_stack.addWidget(self.scroll_geom)

        self.mesh_subpanel = MeshSubpanel(self)
        self.scroll_mesh = QScrollArea()
        self.scroll_mesh.setWidgetResizable(True)
        self.scroll_mesh.setWidget(self.mesh_subpanel)
        self.left_stack.addWidget(self.scroll_mesh)

        splitter.addWidget(self.left_stack)

        self.tabs = QTabWidget(self)

        tab_geom = QWidget()
        lay_geom = QVBoxLayout(tab_geom)
        lay_geom.setContentsMargins(2, 2, 2, 2)
        self.fig = Figure(facecolor="#fcfcfc")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.ax = self.fig.add_axes([0.005, 0.005, 0.99, 0.99])
        self.ax.set_aspect("equal", adjustable="datalim")
        self.toolbar = NavigationToolbar2QT(self.canvas, self)
        lay_geom.addWidget(self.toolbar)
        lay_geom.addWidget(self.canvas, 1)
        self.tabs.addTab(tab_geom, "1. Геометрия сечения и выборка")

        tab_mesh = QWidget()
        lay_mesh = QVBoxLayout(tab_mesh)
        lay_mesh.setContentsMargins(2, 2, 2, 2)

        self.mesh_splitter = QSplitter(Qt.Horizontal, self)

        left_canvas_widget = QWidget()
        lay_canvas = QVBoxLayout(left_canvas_widget)
        lay_canvas.setContentsMargins(0, 0, 0, 0)

        bar_mesh = QHBoxLayout()
        self.fig_mesh = Figure(facecolor="#fcfcfc")
        self.canvas_mesh = FigureCanvasQTAgg(self.fig_mesh)
        self.ax_mesh = self.fig_mesh.add_subplot(111)
        self.ax_mesh.set_aspect("equal", adjustable="box")
        self.toolbar_mesh = NavigationToolbar2QT(self.canvas_mesh, self)
        bar_mesh.addWidget(self.toolbar_mesh, 1)

        bar_mesh.addWidget(QLabel("Детализация:"))
        self.combo_detail = QComboBox(self)
        self.combo_detail.addItem("1:1 (все линии)", 1)
        self.combo_detail.addItem("1:2 (через одну)", 2)
        self.combo_detail.addItem("1:4 (разреженная)", 4)
        self.combo_detail.addItem("1:10 (только контуры)", 10)
        self.combo_detail.currentIndexChanged.connect(self.redraw_mesh_views)
        bar_mesh.addWidget(self.combo_detail)

        self.btn_ruler = QPushButton("📏 Линейка ячеек", self)
        self.btn_ruler.setCheckable(True)
        self.btn_ruler.setStyleSheet("QPushButton:checked { background-color: #ffcc80; font-weight: bold; }")
        self.btn_ruler.toggled.connect(self.on_toggle_ruler)
        bar_mesh.addWidget(self.btn_ruler)
        lay_canvas.addLayout(bar_mesh)

        lay_canvas.addWidget(self.canvas_mesh, 1)
        self.mesh_splitter.addWidget(left_canvas_widget)

        right_table_widget = QWidget()
        lay_tbl = QVBoxLayout(right_table_widget)
        lay_tbl.setContentsMargins(0, 0, 0, 0)

        lbl_tbl_hdr = QLabel("Параметры построенных блоков сетки (кликните строку для подсветки и графика):", self)
        lbl_tbl_hdr.setStyleSheet("font-weight: bold; padding: 4px; font-size: 11px; color: #1a237e;")
        lay_tbl.addWidget(lbl_tbl_hdr)

        self.table_blocks = QTableWidget(self)
        self.table_blocks.setColumnCount(10)
        self.table_blocks.setHorizontalHeaderLabels([
            "№ Блока и сектор", "Закон сгущения", "Опорный стержень", "Шаг у стенки h1 (мкм)",
            "Слоёв по нормали", "Ячеек по дуге", "Шаг по дуге Δs (мкм)", "Параметр закона",
            "Шаг в ядре (мкм)", "Вытянутость AR"
        ])
        self.table_blocks.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table_blocks.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_blocks.setAlternatingRowColors(True)
        self.table_blocks.itemSelectionChanged.connect(self.on_table_block_selected)
        lay_tbl.addWidget(self.table_blocks, 1)

        self.mesh_splitter.addWidget(right_table_widget)
        self.mesh_splitter.setStretchFactor(0, 6)
        self.mesh_splitter.setStretchFactor(1, 4)
        self.mesh_splitter.setSizes([600, 420])

        lay_mesh.addWidget(self.mesh_splitter, 1)
        self.tabs.addTab(tab_mesh, "2. Сетка в сечении и таблица блоков")

        self.canvas_mesh.mpl_connect("button_press_event", self.on_ruler_click)
        self.canvas_mesh.mpl_connect("motion_notify_event", self.on_ruler_motion)
        self.canvas_mesh.mpl_connect("scroll_event", self.on_mesh_scroll)

        tab_layers = QWidget()
        lay_layers = QVBoxLayout(tab_layers)
        lay_layers.setContentsMargins(2, 2, 2, 2)
        self.fig_layers = Figure(facecolor="#fcfcfc")
        self.canvas_layers = FigureCanvasQTAgg(self.fig_layers)
        self.ax_layers = self.fig_layers.add_subplot(111)
        self.toolbar_layers = NavigationToolbar2QT(self.canvas_layers, self)
        lay_layers.addWidget(self.toolbar_layers)
        lay_layers.addWidget(self.canvas_layers, 1)
        self.tabs.addTab(tab_layers, "3. Шаги по нормали к стенке")

        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([470, 950])

        self.canvas.mpl_connect("button_press_event", self.on_mouse_press)
        self.canvas.mpl_connect("button_release_event", self.on_mouse_release)
        self.canvas.mpl_connect("motion_notify_event", self.on_mouse_motion)
        self.canvas.mpl_connect("scroll_event", self.on_mouse_scroll)
        self.canvas.mpl_connect("resize_event", self.on_canvas_resize)

    def add_double_spin(self, layout, label, val, min_val, max_val, step):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        spin = QDoubleSpinBox()
        spin.setRange(min_val, max_val)
        spin.setSingleStep(step)
        spin.setValue(val)
        row.addWidget(spin)
        layout.addLayout(row)
        return spin

    def on_canvas_resize(self, event):
        if self._custom_limits is None:
            self.on_fit_view()

    def on_fit_view(self):
        bbox = self.ax.get_window_extent()
        w_pixels = max(bbox.width, 10.0)
        h_pixels = max(bbox.height, 10.0)
        aspect = w_pixels / h_pixels

        r_base = (self.model.s_flat / 2.0) / math.cos(math.radians(30)) * 1.08

        if aspect >= 1.0:
            half_x = r_base * aspect
            half_y = r_base
        else:
            half_x = r_base
            half_y = r_base / aspect

        self._custom_limits = (-half_x, half_x, -half_y, half_y)
        self.ax.set_xlim(-half_x, half_x)
        self.ax.set_ylim(-half_y, half_y)
        self.canvas.draw_idle()

    def on_mouse_scroll(self, event):
        if event.inaxes != self.ax or event.xdata is None or event.ydata is None:
            return

        base_scale = 1.2
        scale = (1.0 / base_scale) if event.button == "up" else base_scale

        cur_xlim = self.ax.get_xlim()
        cur_ylim = self.ax.get_ylim()
        xdata = event.xdata
        ydata = event.ydata

        w_old = cur_xlim[1] - cur_xlim[0]
        h_old = cur_ylim[1] - cur_ylim[0]

        w_new = w_old * scale
        h_new = h_old * scale

        relx = (cur_xlim[1] - xdata) / w_old
        rely = (cur_ylim[1] - ydata) / h_old

        new_xlim = (xdata - w_new * (1.0 - relx), xdata + w_new * relx)
        new_ylim = (ydata - h_new * (1.0 - rely), ydata + h_new * rely)

        self.ax.set_xlim(new_xlim)
        self.ax.set_ylim(new_ylim)
        self._custom_limits = (new_xlim[0], new_xlim[1], new_ylim[0], new_ylim[1])
        self.canvas.draw_idle()

    def on_mouse_press(self, event):
        if event.inaxes != self.ax:
            return

        toolbar_mode = getattr(self.toolbar, "mode", "")
        if toolbar_mode:
            return

        if event.button in (2, 3):
            self._pan_start = (event.x, event.y, self.ax.get_xlim(), self.ax.get_ylim())
            return

        if event.button == 1 and event.xdata is not None and event.ydata is not None:
            self.handle_unified_click(event.xdata, event.ydata)

    def on_mouse_motion(self, event):
        if self._pan_start is None or event.x is None or event.y is None:
            return

        start_x, start_y, xlim_orig, ylim_orig = self._pan_start
        dx_pixels = event.x - start_x
        dy_pixels = event.y - start_y

        inv = self.ax.transData.inverted()
        p0 = inv.transform((0, 0))
        p1 = inv.transform((dx_pixels, dy_pixels))
        dx_data = p1[0] - p0[0]
        dy_data = p1[1] - p0[1]

        new_xlim = (xlim_orig[0] - dx_data, xlim_orig[1] - dx_data)
        new_ylim = (ylim_orig[0] - dy_data, ylim_orig[1] - dy_data)

        self.ax.set_xlim(new_xlim)
        self.ax.set_ylim(new_ylim)
        self._custom_limits = (new_xlim[0], new_xlim[1], new_ylim[0], new_ylim[1])
        self.canvas.draw_idle()

    def on_mouse_release(self, event):
        if event.button in (2, 3):
            self._pan_start = None

    def handle_unified_click(self, xdata, ydata):
        click_pt = np.array([xdata, ydata])

        # 1. Проверяем попадание внутрь круглого стержня
        for r_id, rod in self.model.rods.items():
            dist = np.linalg.norm(click_pt - np.array([rod.x, rod.y]))
            if dist <= (rod.diameter / 2.0):
                coord = (rod.q, rod.r)
                # Если кликнули по УЖЕ выбранному стержню — снимаем выбор!
                if self.model.active_rod_coord == coord:
                    self.model.active_rod_coord = None
                else:
                    self.model.active_rod_coord = coord
                self.update_inspector()
                self.rebuild_view()
                return

        # 2. Клик по кнопкам "+" кандидатов
        candidates = self.model.get_candidate_neighbors()
        for c_id in candidates:
            sub = self.model.subchannels[c_id]
            dist = np.linalg.norm(click_pt - np.array(sub.fluid_center))
            if dist <= self.model.pitch * 0.45:
                self.model.add_subchannel(c_id)
                self.update_inspector()
                self.rebuild_view()
                return

        # 3. Клик по кнопкам "−" уже выбранных подканалов
        for s_id in self.model.selected_subchannels:
            sub = self.model.subchannels[s_id]
            dist = np.linalg.norm(click_pt - np.array(sub.fluid_center))
            if dist <= self.model.pitch * 0.45:
                self.model.remove_subchannel(s_id)
                self.update_inspector()
                self.rebuild_view()
                return

        # 4. Клик по любому свободному подканалу в зазоре
        best_id = None
        min_d = float("inf")
        for s_id, sub in self.model.subchannels.items():
            dist = np.linalg.norm(click_pt - np.array(sub.fluid_center))
            if dist < min_d and dist <= self.model.pitch * 0.65:
                min_d = dist
                best_id = s_id

        if best_id is not None:
            self.model.select_subchannel(best_id)
            self.update_inspector()
            self.rebuild_view()
            return

        # 5. Клик по пустому пространству (вне стержней и подканалов) -> снимает выбор со стержня!
        if self.model.active_rod_coord is not None:
            self.model.active_rod_coord = None
            self.update_inspector()
            self.rebuild_view()

    def on_deselect_rod(self):
        """Снятие выбора со стержня по кнопке в инспекторе."""
        self.model.deselect_rod()
        self.update_inspector()
        self.rebuild_view()

    def on_rebuild_geometry(self, silent=False):
        if not silent:
            self.model.reset_custom_overrides()

        self.model.s_flat = self.s_flat_spin.value()
        self.model.pitch = self.pitch_spin.value()
        self.model.d_fuel = self.d_fuel_spin.value()
        self.model.d_guide = self.d_guide_spin.value()
        self.model.d_instrument = self.d_inst_spin.value()
        self.model.update_geometry()

        self.update_inspector()
        self.on_fit_view()
        self.rebuild_view()

    def on_select_all_subchannels(self):
        self.model.select_all_subchannels()
        self.update_inspector()
        self.rebuild_view()

    def on_clear_selection(self):
        """Сбрасывает выбор подканалов И снимает выделение со стержня."""
        self.model.clear_all_selection()
        self.update_inspector()
        self.rebuild_view()

    def on_delete_rod_manually(self):
        self.model.delete_active_rod_manually()
        self.update_inspector()
        self.rebuild_view()

    def on_restore_deleted_rods(self):
        self.model.restore_deleted_rods()
        self.update_inspector()
        self.rebuild_view()

    def on_rod_type_changed(self, index):
        if self.model.active_rod_coord is None:
            return
        coord = self.model.active_rod_coord
        rod_id = self.model.coord_to_rod_id.get(coord)
        if rod_id is None or rod_id not in self.model.rods:
            return

        rod = self.model.rods[rod_id]
        new_type = self.rod_type_combo.currentData()
        if new_type == rod.rod_type:
            return

        if new_type == "guide":
            target_diam = self.d_guide_spin.value()
        elif new_type == "instrument":
            target_diam = self.d_inst_spin.value()
        else:
            target_diam = self.d_fuel_spin.value()

        self.rod_diam_spin.blockSignals(True)
        self.rod_diam_spin.setValue(target_diam)
        self.rod_diam_spin.blockSignals(False)

        clashes = self.model.check_clashes_for_coord(coord, target_diam)
        delete_clashes = False

        if clashes and new_type in ("guide", "instrument"):
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Question)
            msg.setWindowTitle("Контроль пересечений")
            msg.setText(f"Стержень перекрывает {len(clashes)} соседних ТВЭЛ(ов).\nУдалить пересекающиеся ТВЭЛы автоматически?")
            btn_yes = msg.addButton("Да, удалить автоматически", QMessageBox.YesRole)
            btn_no = msg.addButton("Нет, оставить (удалю вручную)", QMessageBox.NoRole)
            btn_cancel = msg.addButton("Отмена", QMessageBox.RejectRole)
            msg.exec()

            clicked = msg.clickedButton()
            if clicked == btn_cancel:
                self.rod_type_combo.blockSignals(True)
                self.rod_type_combo.setCurrentIndex(self.rod_type_combo.findData(rod.rod_type))
                self.rod_type_combo.blockSignals(False)
                return
            elif clicked == btn_yes:
                delete_clashes = True

        self.model.apply_rod_change(coord, new_type, target_diam, delete_clashes=delete_clashes)
        self.update_inspector()
        self.rebuild_view()

    def apply_custom_rod_diameter(self):
        if self.model.active_rod_coord is None:
            return
        coord = self.model.active_rod_coord
        rod_id = self.model.coord_to_rod_id.get(coord)
        if rod_id is None or rod_id not in self.model.rods:
            return

        rod = self.model.rods[rod_id]
        new_val = self.rod_diam_spin.value()
        if math.isclose(new_val, rod.diameter, abs_tol=1e-3):
            return

        clashes = self.model.check_clashes_for_coord(coord, new_val)
        delete_clashes = False

        if clashes:
            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Question)
            msg.setWindowTitle("Контроль пересечений")
            msg.setText(f"Заданный диаметр {new_val:.2f} мм перекрывает {len(clashes)} соседних ТВЭЛ(ов).\nУдалить пересекающиеся ТВЭЛы автоматически?")
            btn_yes = msg.addButton("Да, удалить автоматически", QMessageBox.YesRole)
            btn_no = msg.addButton("Нет, оставить (удалю вручную)", QMessageBox.NoRole)
            btn_cancel = msg.addButton("Отмена", QMessageBox.RejectRole)
            msg.exec()

            clicked = msg.clickedButton()
            if clicked == btn_cancel:
                self.rod_diam_spin.blockSignals(True)
                self.rod_diam_spin.setValue(rod.diameter)
                self.rod_diam_spin.blockSignals(False)
                return
            elif clicked == btn_yes:
                delete_clashes = True

        self.model.apply_rod_change(coord, rod.rod_type, new_val, delete_clashes=delete_clashes)
        self.update_inspector()
        self.rebuild_view()

    def update_inspector(self):
        if self.model.active_rod_coord is not None:
            rod_id = self.model.coord_to_rod_id.get(self.model.active_rod_coord)
            if rod_id is not None and rod_id in self.model.rods:
                rod = self.model.rods[rod_id]
                type_names = {"fuel": "Обычный ТВЭЛ", "guide": "Направляющий Канал (НК)", "instrument": "Инструментальный Канал (ИК)"}
                self.inspect_label.setText(
                    f"<b>Выбран стержень R{rod.rod_id}</b><br>"
                    f"Позиция (q, r): ({rod.q}, {rod.r})<br>"
                    f"Координаты: X = {rod.x:.2f} мм, Y = {rod.y:.2f} мм<br>"
                    f"Тип: <b>{type_names.get(rod.rod_type, rod.rod_type)}</b><br>"
                    f"Диаметр: <b>{rod.diameter:.2f} мм</b>"
                )
                self.rod_controls.setVisible(True)
                self.rod_type_combo.blockSignals(True)
                self.rod_type_combo.setCurrentIndex(self.rod_type_combo.findData(rod.rod_type))
                self.rod_type_combo.blockSignals(False)

                self.rod_diam_spin.blockSignals(True)
                self.rod_diam_spin.setValue(rod.diameter)
                self.rod_diam_spin.blockSignals(False)

                has_deleted = len(self.model.user_deleted_coords) > 0 or len(self.model.auto_deleted_clash_coords) > 0
                self.btn_restore_rods.setVisible(has_deleted)
                return

        self.rod_controls.setVisible(False)

        if self.model.active_sub_id is not None and self.model.active_sub_id in self.model.subchannels:
            sub = self.model.subchannels[self.model.active_sub_id]
            type_names = {
                "interior": "Регулярный (3 ТВЭЛа)",
                "guide_sub": "НК (подканал у направляющего канала)",
                "instrument_sub": "ИК (подканал у инструментального канала)",
                "peripheral": "Периф (между стержнями и гранью)",
                "corner": "Угловой (грань проходит в вершину угла)"
            }
            rods_str = ", ".join(f"R{rid}" for rid in sub.rod_ids)
            self.inspect_label.setText(
                f"<b>Выбран подканал S{sub.sub_id}</b><br>"
                f"Тип: <b>{type_names.get(sub.sub_type, sub.sub_type)}</b><br>"
                f"Стержни: {rods_str}<br>"
                f"&bull; <b>Площадь A:</b> {sub.a_fluid_mm2:.2f} мм²<br>"
                f"&bull; <b>Периметр P:</b> {sub.p_wet_mm:.2f} мм<br>"
                f"&bull; <b>D_h:</b> {sub.d_h_mm:.2f} мм"
            )
            return

        self.inspect_label.setText("Кликните на подканал (+) или на стержень для настройки.")

    def rebuild_view(self):
        if self._custom_limits is None and hasattr(self, "ax"):
            r_base = (self.model.s_flat / 2.0) / math.cos(math.radians(30)) * 1.08
            self._custom_limits = (-r_base, r_base, -r_base, r_base)

        self.ax.clear()

        # 1. Шестигранная оболочка
        hex_poly = Polygon(self.model.hex_vertices, closed=True, fill=False,
                           edgecolor="#2c3e50", linewidth=2.5, zorder=2)
        self.ax.add_patch(hex_poly)

        for i in range(6):
            mid = (self.model.hex_vertices[i] + self.model.hex_vertices[(i + 1) % 6]) / 2.0
            self.ax.text(mid[0] * 1.07, mid[1] * 1.07, f"S{i+1}",
                         ha="center", va="center", color="#2c3e50", fontsize=9, fontweight="bold")

        # 2. Отрисовка подканалов
        color_map = {
            "interior": "#2ecc71",       # Зелёный
            "guide_sub": "#f39c12",       # Янтарный (НК)
            "instrument_sub": "#1abc9c",  # Бирюзовый (ИК)
            "peripheral": "#3498db",      # Синий (Периф)
            "corner": "#9b59b6"           # Фиолетовый (Угловой)
        }
        edge_map = {
            "interior": "#27ae60",
            "guide_sub": "#d35400",
            "instrument_sub": "#16a085",
            "peripheral": "#2980b9",
            "corner": "#8e44ad"
        }

        bbox_style = dict(boxstyle="round,pad=0.25", facecolor="#ffffff", alpha=0.88, edgecolor="none")

        for sub_id in self.model.selected_subchannels:
            sub = self.model.subchannels[sub_id]
            c = color_map.get(sub.sub_type, "#2ecc71")
            ec = edge_map.get(sub.sub_type, "#27ae60")

            poly = Polygon(sub.polygon_points, closed=True, facecolor=c,
                           edgecolor=ec, alpha=0.45, linewidth=1.5, zorder=3)
            self.ax.add_patch(poly)
            self.ax.text(sub.fluid_center[0], sub.fluid_center[1], "−",
                         ha="center", va="center", color="#900C3F", fontsize=15, fontweight="bold",
                         bbox=bbox_style, zorder=6)

        candidates = self.model.get_candidate_neighbors()
        for sub_id in candidates:
            sub = self.model.subchannels[sub_id]
            poly = Polygon(sub.polygon_points, closed=True, facecolor="#f1c40f",
                           edgecolor="#f39c12", alpha=0.25, linewidth=1.2, linestyle="--", zorder=3)
            self.ax.add_patch(poly)
            self.ax.text(sub.fluid_center[0], sub.fluid_center[1], "+",
                         ha="center", va="center", color="#d35400", fontsize=14, fontweight="bold",
                         bbox=bbox_style, zorder=6)

        if not self.model.selected_subchannels:
            for sub in self.model.subchannels.values():
                poly = Polygon(sub.polygon_points, closed=True, facecolor="#f8f9fa",
                               edgecolor="#bdc3c7", alpha=0.3, linewidth=0.7, linestyle="-.", zorder=1)
                self.ax.add_patch(poly)
                lbl = {"interior": "Регул.", "guide_sub": "НК", "instrument_sub": "ИК",
                       "peripheral": "Периф", "corner": "Углов."}.get(sub.sub_type, "+")
                self.ax.text(sub.fluid_center[0], sub.fluid_center[1], lbl,
                             ha="center", va="center", color="#5d6d7e", fontsize=7.5, fontweight="bold",
                             bbox=bbox_style, zorder=6)

        # 3. Стержни (ТВЭЛ / НК / ИК)
        active_id = self.model.active_rod_id
        for r_id, rod in self.model.rods.items():
            is_active = (r_id == active_id)

            if rod.rod_type == "guide":
                facecolor, edgecolor = "#f9e79f", "#b7950b"
                badge = "\nНК"
            elif rod.rod_type == "instrument":
                facecolor, edgecolor = "#a3e4d7", "#117864"
                badge = "\nИК"
            else:
                facecolor, edgecolor = "#d4e6f1", "#2980b9"
                badge = ""

            if is_active:
                edgecolor = "#e74c3c"
            elif rod.is_clashing:
                edgecolor = "#c0392b"
                facecolor = "#f2d7d5"

            circle = Circle((rod.x, rod.y), rod.diameter / 2.0,
                            facecolor=facecolor, edgecolor=edgecolor,
                            linewidth=2.4 if is_active else (2.0 if rod.is_clashing else 1.5),
                            linestyle="--" if rod.is_clashing else "-", zorder=5)
            self.ax.add_patch(circle)

            label = f"R{rod.rod_id}" + badge
            self.ax.text(rod.x, rod.y, label,
                         ha="center", va="center", color="#1a252f",
                         fontsize=7.5 if badge else 8, fontweight="bold", zorder=7)

        # 4. Сводка и гидравлика
        all_summary = self.model.get_total_assembly_summary()
        all_text = ""
        if all_summary:
            all_text = (f"<br><b>Гидравлика ВСЕЙ сборки ТВС ({all_summary['total_subchannels']} подканалов):</b><br>"
                        f"&bull; <b>Полная площадь A:</b> {all_summary['total_a_fluid_mm2']:.2f} мм²<br>"
                        f"&bull; <b>Полный периметр P:</b> {all_summary['total_p_wet_mm']:.2f} мм<br>"
                        f"&bull; <b>D_h всей ТВС:</b> <b>{all_summary['total_d_h_mm']:.2f} мм</b>")

        num_selected = len(self.model.selected_subchannels)
        num_rods = len({rid for sid in self.model.selected_subchannels for rid in self.model.subchannels[sid].rod_ids})

        sel_summary = self.model.get_selection_summary()
        if sel_summary:
            tot_a = sel_summary["total_a_fluid_mm2"]
            tot_p = sel_summary["total_p_wet_mm"]
            tot_dh = sel_summary["total_d_h_mm"]
            sel_text = (f"<hr><b>Гидравлика ВЫБРАННОЙ области ({num_selected} подканалов, {num_rods} стержней):</b><br>"
                        f"&bull; <b>Площадь A:</b> {tot_a:.2f} мм²<br>"
                        f"&bull; <b>Периметр P:</b> {tot_p:.2f} мм<br>"
                        f"&bull; <b>D_h эквив.:</b> <b>{tot_dh:.2f} мм</b>")
        else:
            sel_text = "<hr><i>Подканалы не выбраны (кликните '+' или 'Выбрать ВСЕ').</i>"

        self.summary_text.setText(f"{all_text}{sel_text}")

        if self._custom_limits is not None:
            xmin, xmax, ymin, ymax = self._custom_limits
            self.ax.set_xlim(xmin, xmax)
            self.ax.set_ylim(ymin, ymax)

        self.ax.axis("off")
        self.canvas.draw_idle()

    def open_hydraulics_table(self):
        dialog = HydraulicsTableDialog(self, self.model)
        dialog.exec()

    def on_save_json(self):
        name, _ = QFileDialog.getSaveFileName(self, "Сохранить конфигурацию сечения", "bundle_selection.json", "JSON (*.json)")
        if name:
            data = self.model.export_dict()
            Path(name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            QMessageBox.information(self, "Успех", f"Конфигурация сечения сохранена в:\n{name}")

    def on_load_json(self):
        name, _ = QFileDialog.getOpenFileName(self, "Открыть конфигурацию сечения", "", "JSON (*.json)")
        if name:
            try:
                data = json.loads(Path(name).read_text(encoding="utf-8"))
                lat = data["lattice"]
                self.s_flat_spin.setValue(lat["s_across_flats_mm"])
                self.pitch_spin.setValue(lat["pitch_mm"])
                self.d_fuel_spin.setValue(lat["default_d_fuel_mm"])
                self.d_guide_spin.setValue(lat["default_d_guide_mm"])
                self.d_inst_spin.setValue(lat.get("default_d_instrument_mm", 10.3))

                self.model.s_flat = lat["s_across_flats_mm"]
                self.model.pitch = lat["pitch_mm"]
                self.model.d_fuel = lat["default_d_fuel_mm"]
                self.model.d_guide = lat["default_d_guide_mm"]
                self.model.d_instrument = lat.get("default_d_instrument_mm", 10.3)

                self.model.user_rod_types.clear()
                self.model.user_custom_diameters.clear()
                self.model.user_deleted_coords = set(tuple(c) for c in data.get("user_deleted_coords", []))
                self.model.auto_deleted_clash_coords = set()

                for r_info in data.get("rods", []):
                    coord = (r_info["q"], r_info["r"])
                    rtype = r_info.get("type", "fuel")
                    if rtype != "fuel":
                        self.model.user_rod_types[coord] = rtype
                    if r_info.get("custom_diameter"):
                        self.model.user_custom_diameters[coord] = r_info["diameter_mm"]

                self.model.update_geometry()
                self.model.selected_subchannels = {s["subchannel_id"] for s in data.get("subchannels", [])}
                self.update_inspector()
                self.on_fit_view()
                self.rebuild_view()
                QMessageBox.information(self, "Успех", f"Конфигурация сечения загружена из:\n{name}")
            except Exception as exc:
                QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить файл: {exc}")


    def switch_to_mesh_mode(self):
        if not self.model.selected_subchannels:
            QMessageBox.warning(self, "Предупреждение", "Сначала выберите хотя бы один подканал на сечении ТВС.")
            return

        templates, instances = classify_subchannel_blocks(self.model)
        self.instances_lookup = {inst.global_block_id: inst for inst in instances}
        self.mesh_subpanel.populate_scope_and_tree(templates, instances)

        if instances:
            min_gap_len = min(inst.length_gap_mm * 1e-3 for inst in instances)
            nj_cells = self.mesh_subpanel.fields["layers"].value()
            avg_step = min_gap_len / max(1, nj_cells)
            curr_h1 = self.mesh_subpanel.fields["h1"].value()
            if curr_h1 >= avg_step * 0.95:
                safe_h1 = avg_step * 0.45
                self.mesh_subpanel.fields["h1"].setValue(safe_h1)

        self.left_stack.setCurrentIndex(1)
        self.tabs.setCurrentIndex(1)
        self.mesh_subpanel.lbl_status.setText("Режим сеточной модели активен. Настройте параметры и нажмите кнопку построения.")
        self.mesh_subpanel.update_live_advisor_hint()

    def switch_to_geometry_mode(self):
        self.left_stack.setCurrentIndex(0)
        self.tabs.setCurrentIndex(0)

    def get_template_for_block(self, gid):
        inst = self.instances_lookup.get(gid)
        return inst.template_id if inst else 1

    def on_build_layer_only(self):
        if not self.model.selected_subchannels: return
        self.mesh_subpanel.save_current_ui_to_active_scope()
        self.mesh_subpanel.update_tree_status()
        base_p = self.base_params

        try:
            cm_method = self.mesh_subpanel.combo_center_method.currentData() if hasattr(self.mesh_subpanel, "combo_center_method") else "equi_clearance"
            res = ms.build_mesh_from_bundle_model(
                self.model, base_params=base_p,
                template_overrides=self.template_configs,
                block_custom_overrides=self.block_custom_configs,
                auto_fill_core=False,
                center_method=cm_method, hermite_tfi=(self.mesh_subpanel.chk_hermite_tfi.isChecked() if hasattr(self.mesh_subpanel, "chk_hermite_tfi") else False)
            )
            z_len, nz = base_p.z_len, base_p.nz
            z_nodes = np.linspace(0, z_len, nz + 1)
            b3d = mq.extrude_blocks(res.blocks, z_nodes)
            rep = mq.analyse_blocks(b3d)

            self.current_layer_result = res
            self.current_layer_result = res if not res.complete else None
            self.current_mesh_result = res
            self.current_quality_report = rep
            self.mesh_subpanel.btn_quality.setEnabled(True)
            self.mesh_subpanel.btn_export.setEnabled(False)
            self.mesh_subpanel.btn_export_star.setEnabled(False)
            self.mesh_subpanel.btn_fill_core.setEnabled(True)

            d = res.diagnostics
            skipped = d.get("skipped_peripheral", 0)
            skip_txt = f" (пропущено пристеночных: {skipped})" if skipped else ""
            txt = (
                f"Построен пристеночный слой: {d['blocks']} блоков.\n"
                f"Ядро не заполнено. Настройте блок «5. Заполнение ядра» и нажмите «Заполнить ядро сетки».{skip_txt}"
            )
            self.mesh_subpanel.lbl_status.setText(txt)
            self.mesh_subpanel.update_core_preview()
            self.redraw_mesh_views()
            self.populate_blocks_table()
        except Exception as exc:
            user_msg = format_friendly_error(exc)
            QMessageBox.critical(self, "Ошибка построения слоя", user_msg)

    def on_build_multiblock_mesh(self):
        if not self.model.selected_subchannels: return
        self.mesh_subpanel.save_current_ui_to_active_scope()
        self.mesh_subpanel.update_tree_status()
        base_p = self.base_params
        is_layer_mode = (base_p.law == "wall_core")

        try:
            cm_method = self.mesh_subpanel.combo_center_method.currentData() if hasattr(self.mesh_subpanel, "combo_center_method") else "equi_clearance"
            res = ms.build_mesh_from_bundle_model(
                self.model, base_params=base_p,
                template_overrides=self.template_configs,
                block_custom_overrides=self.block_custom_configs,
                auto_fill_core=False if is_layer_mode else True,
                center_method=cm_method, hermite_tfi=(self.mesh_subpanel.chk_hermite_tfi.isChecked() if hasattr(self.mesh_subpanel, "chk_hermite_tfi") else False)
            )
            z_len, nz = base_p.z_len, base_p.nz
            z_nodes = np.linspace(0, z_len, nz + 1)
            b3d = mq.extrude_blocks(res.blocks, z_nodes)
            rep = mq.analyse_blocks(b3d)

            self.current_mesh_result = res
            self.current_quality_report = rep
            self.mesh_subpanel.btn_quality.setEnabled(True)
            self.mesh_subpanel.btn_export.setEnabled(res.complete)
            self.mesh_subpanel.btn_export_star.setEnabled(res.complete)
            self.mesh_subpanel.btn_fill_core.setEnabled(base_p.law == "wall_core" and not res.complete)

            d = res.diagnostics
            skipped = d.get("skipped_peripheral", 0)
            skip_txt = f" (пропущено пристеночных: {skipped})" if skipped else ""
            txt = (
                f"Сетка построена: {d['blocks']} блоков, {d['cells_3d']:,} ячеек (3D).\n"
                f"Интерфейсов: {d.get('matched_interfaces', 0)}, Min Jacobian: {rep['metrics']['scaled_jacobian']['min']:.3f}.{skip_txt}"
            )
            self.mesh_subpanel.lbl_status.setText(txt)
            self.redraw_mesh_views()
            self.populate_blocks_table()
        except Exception as exc:
            user_msg = format_friendly_error(exc)
            QMessageBox.critical(self, "Ошибка построения сетки", user_msg)

    def on_fill_core_clicked(self):
        layer_src = getattr(self, "current_layer_result", None)
        if layer_src is None and self.current_mesh_result is not None and not self.current_mesh_result.complete:
            layer_src = self.current_mesh_result
        if layer_src is None: return
        try:
            f = self.mesh_subpanel.fields
            growth = f["core_growth"].value()
            maxsize = f["core_max_size"].value()
            maxcells = f["core_max_cells"].value()

            q_trans = f["core_transition"].value() if "core_transition" in f else 1.0
            cmode = self.mesh_subpanel.combo_core_mode.currentData() if hasattr(self.mesh_subpanel, "combo_core_mode") else "cfd_growth"
            clayers = f["core_layers"].value() if "core_layers" in f else 20
            h_tfi = self.mesh_subpanel.chk_hermite_tfi.isChecked() if hasattr(self.mesh_subpanel, "chk_hermite_tfi") else False

            full_res = ms.fill_subchannel_core(
                layer_src, self.model,
                growth=growth, max_size=maxsize, max_cells=maxcells,
                transition_ratio=q_trans, core_mode=cmode, core_layers=clayers, hermite_tfi=h_tfi
            )
            z_len, nz = full_res.params.z_len, full_res.params.nz
            z_nodes = np.linspace(0, z_len, nz + 1)
            b3d = mq.extrude_blocks(full_res.blocks, z_nodes)
            rep = mq.analyse_blocks(b3d)

            self.current_mesh_result = full_res
            self.current_quality_report = rep
            self.mesh_subpanel.btn_fill_core.setEnabled(True)
            self.mesh_subpanel.btn_export.setEnabled(True)
            self.mesh_subpanel.btn_export_star.setEnabled(True)

            d = full_res.diagnostics
            extra = ""
            if d.get("core_target_exceeded"):
                extra = (f"\n⚠ Узкий зазор ограничил число слоёв: в центре ячейки крупнее целевого "
                         f"({d.get('core_target_m', 0)*1e6:.0f} мкм) — до {d.get('core_plateau_max_m', 0)*1e6:.0f} мкм.")
            self.mesh_subpanel.lbl_status.setText(
                f"Ядро заполнено: {d['blocks']} блоков, {d['cells_3d']:,} ячеек (3D). "
                f"Слоёв ядра: {d.get('core_layers_count', '?')}; ячейка на конце ядра: "
                f"зазор ≈ {d.get('core_plateau_min_m', 0)*1e6:.0f} … центр ≈ {d.get('core_plateau_max_m', 0)*1e6:.0f} мкм.\n"
                f"Min Jacobian: {rep['metrics']['scaled_jacobian']['min']:.3f}.{extra}\n"
                f"Можно менять параметры Блока 5 и нажимать «Заполнить ядро сетки» повторно — призма не пересоздаётся."
            )
            self.mesh_subpanel.update_core_preview()
            self.redraw_mesh_views()
            self.populate_blocks_table()
            QMessageBox.information(self, "Ядро заполнено", f"Сетка успешно заполнена до центра подканалов! Всего ячеек: {d['cells_3d']:,}")
        except Exception as exc:
            user_msg = format_friendly_error(exc)
            QMessageBox.critical(self, "Не удалось заполнить ядро", user_msg)

    def populate_blocks_table(self):
        if self.current_mesh_result is None: return
        metrics = getattr(self.current_mesh_result, "block_metrics", [])
        self.table_blocks.setRowCount(len(metrics))

        for row_idx, m in enumerate(metrics):
            b_label = f"Блок {m.global_id} (S{m.subchannel_id}, сектор {m.sector_idx})"
            it_id = QTableWidgetItem(b_label)
            it_id.setData(Qt.UserRole, m.global_id)
            self.table_blocks.setItem(row_idx, 0, it_id)

            self.table_blocks.setItem(row_idx, 1, QTableWidgetItem(m.law_display))
            self.table_blocks.setItem(row_idx, 2, QTableWidgetItem(f"{m.rod_name} (D={m.rod_diameter_mm:.1f})"))
            self.table_blocks.setItem(row_idx, 3, QTableWidgetItem(f"{m.h1_um:.3f}"))
            self.table_blocks.setItem(row_idx, 4, QTableWidgetItem(str(m.nj - 1)))
            self.table_blocks.setItem(row_idx, 5, QTableWidgetItem(str(m.ni - 1)))
            self.table_blocks.setItem(row_idx, 6, QTableWidgetItem(f"{m.azimuth_step_wall_um:.1f}"))

            it_param = QTableWidgetItem(m.special_param_str)
            if m.law == "geometric":
                if m.growth_q <= 1.20: it_param.setBackground(QBrush(QColor("#e8f5e9")))
                elif m.growth_q <= 1.35: it_param.setBackground(QBrush(QColor("#fffde7")))
                else: it_param.setBackground(QBrush(QColor("#ffebee")))
            elif "tanh" in m.law or "sinh" in m.law:
                if m.growth_q <= 3.5: it_param.setBackground(QBrush(QColor("#e8f5e9")))
                else: it_param.setBackground(QBrush(QColor("#fffde7")))
            elif m.law == "power":
                if m.growth_q <= 2.2: it_param.setBackground(QBrush(QColor("#e8f5e9")))
                else: it_param.setBackground(QBrush(QColor("#fffde7")))

            self.table_blocks.setItem(row_idx, 7, it_param)
            self.table_blocks.setItem(row_idx, 8, QTableWidgetItem(f"{m.h_last_um:.1f}"))

            it_ar = QTableWidgetItem(f"{m.aspect_ratio_wall:.1f}")
            if m.aspect_ratio_wall > 200.0: it_ar.setBackground(QBrush(QColor("#fffde7")))
            self.table_blocks.setItem(row_idx, 9, it_ar)

    def on_table_block_selected(self):
        items = self.table_blocks.selectedItems()
        if not items: return
        row = self.table_blocks.currentRow()
        gid_item = self.table_blocks.item(row, 0)
        if gid_item:
            gid = gid_item.data(Qt.UserRole)
            if gid is not None:
                self.highlight_mesh_block(gid)
                self.active_plot_block_idx = max(0, gid - 1)
                self.redraw_layer_plot_for_block(self.active_plot_block_idx)

    def redraw_layer_plot_for_block(self, block_idx):
        if self.current_mesh_result is None: return
        res = self.current_mesh_result
        all_w = getattr(res, "all_block_widths", [])
        widths_m = all_w[block_idx] if (all_w and block_idx < len(all_w)) else res.layer_widths
        if widths_m is None: return

        self.ax_layers.clear()
        widths_um = widths_m * 1e6
        nodes_idx = np.arange(1, widths_um.shape[1] + 1)

        metrics = getattr(res, "block_metrics", [])
        b_info = f"Блок {block_idx + 1}"
        if block_idx < len(metrics):
            m = metrics[block_idx]
            b_info = f"Блок {m.global_id} ({m.rod_name}, D={m.rod_diameter_mm:.1f} мм, закон: {m.law_display})"

        self.ax_layers.plot(nodes_idx, widths_um[0], "b.-", label="Сечение 1 (к центру O)")
        if widths_um.shape[0] > 1:
            mid_idx = widths_um.shape[0] // 2
            self.ax_layers.plot(nodes_idx, widths_um[mid_idx], "g.-", label=f"Сечение {mid_idx+1}")
            self.ax_layers.plot(nodes_idx, widths_um[-1], "r.-", label="Сечение N (к зазору M)")

        self.ax_layers.set_xlabel("Номер ячейки по нормали (j)")
        self.ax_layers.set_ylabel("Толщина ячейки (мкм)")
        self.ax_layers.set_title(f"Распределение толщин ячеек по нормали: {b_info}")
        self.ax_layers.grid(True, alpha=0.3)
        self.ax_layers.legend(fontsize=9)
        self.canvas_layers.draw_idle()

    def on_mesh_scroll(self, event):
        if event.inaxes != self.ax_mesh or event.xdata is None or event.ydata is None: return
        base_scale = 1.2
        scale = 1.0 / base_scale if event.button == "up" else base_scale
        cur_xlim = self.ax_mesh.get_xlim(); cur_ylim = self.ax_mesh.get_ylim()
        xdata, ydata = event.xdata, event.ydata
        w_old = cur_xlim[1] - cur_xlim[0]; h_old = cur_ylim[1] - cur_ylim[0]
        w_new = w_old * scale; h_new = h_old * scale
        rel_x = (cur_xlim[1] - xdata) / w_old; rel_y = (cur_ylim[1] - ydata) / h_old
        self.ax_mesh.set_xlim(xdata - w_new * (1.0 - rel_x), xdata + w_new * rel_x)
        self.ax_mesh.set_ylim(ydata - h_new * (1.0 - rel_y), ydata + h_new * rel_y)
        self.canvas_mesh.draw_idle()

    def on_toggle_ruler(self, checked):
        self.ruler_active = checked
        if not checked: self.clear_ruler()

    def clear_ruler(self):
        self.ruler_p1 = None
        if self.ruler_line is not None:
            try: self.ruler_line.remove()
            except Exception: pass
            self.ruler_line = None
        if self.ruler_text is not None:
            try: self.ruler_text.remove()
            except Exception: pass
            self.ruler_text = None
        self.canvas_mesh.draw_idle()

    def on_ruler_click(self, event):
        if not self.ruler_active or event.inaxes != self.ax_mesh or event.button != 1 or event.xdata is None or event.ydata is None: return
        x, y = event.xdata, event.ydata
        if self.ruler_p1 is None:
            self.ruler_p1 = (x, y)
        else:
            p1, p2 = self.ruler_p1, (x, y)
            dist_mm = float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))
            badge = f"ΔL = {dist_mm*1e3:.3f} мкм ({dist_mm:.4f} мм)"

            if self.ruler_line is not None: self.ruler_line.set_data([p1[0], p2[0]], [p1[1], p2[1]])
            else: self.ruler_line, = self.ax_mesh.plot([p1[0], p2[0]], [p1[1], p2[1]], "r-o", linewidth=1.5, markersize=4, zorder=10)

            mid_x, mid_y = (p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0
            if self.ruler_text is not None:
                self.ruler_text.set_position((mid_x, mid_y)); self.ruler_text.set_text(badge)
            else:
                self.ruler_text = self.ax_mesh.text(
                    mid_x, mid_y, badge, color="red", fontsize=8.5, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.25", facecolor="#fff9c4", edgecolor="red", linewidth=1.0),
                    zorder=11
                )
            self.canvas_mesh.draw_idle()
            self.ruler_p1 = None

    def on_ruler_motion(self, event):
        if not self.ruler_active or self.ruler_p1 is None or event.inaxes != self.ax_mesh or event.xdata is None or event.ydata is None: return
        p1, p2 = self.ruler_p1, (event.xdata, event.ydata)
        dist_mm = float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))
        badge = f"{dist_mm*1e3:.1f} мкм"
        if self.ruler_line is not None: self.ruler_line.set_data([p1[0], p2[0]], [p1[1], p2[1]])
        else: self.ruler_line, = self.ax_mesh.plot([p1[0], p2[0]], [p1[1], p2[1]], "r--", linewidth=1.2, zorder=10)

        mid_x, mid_y = (p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0
        if self.ruler_text is not None:
            self.ruler_text.set_position((mid_x, mid_y)); self.ruler_text.set_text(badge)
        else:
            self.ruler_text = self.ax_mesh.text(
                mid_x, mid_y, badge, color="red", fontsize=8,
                bbox=dict(boxstyle="round,pad=0.2", facecolor="#ffffff", edgecolor="red", alpha=0.8),
                zorder=11
            )
        self.canvas_mesh.draw_idle()

    def redraw_mesh_views(self):
        if self.current_mesh_result is None: return
        res = self.current_mesh_result; p = res.params
        prev_xlim = self.ax_mesh.get_xlim() if self._mesh_drawn else None
        prev_ylim = self.ax_mesh.get_ylim() if self._mesh_drawn else None

        self.ax_mesh.clear()
        colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
        stride = self.combo_detail.currentData() if hasattr(self, "combo_detail") and self.combo_detail.currentData() else 1

        for k, (bx, by) in enumerate(res.blocks):
            v = np.stack((bx * 1e3, by * 1e3), axis=-1)
            ii = np.unique(np.r_[np.arange(0, bx.shape[0], stride), bx.shape[0] - 1])
            jj = np.unique(np.r_[np.arange(0, bx.shape[1], stride), bx.shape[1] - 1])
            lines = [v[i] for i in ii] + [v[:, j] for j in jj]
            c = colors[k % len(colors)]
            self.ax_mesh.add_collection(LineCollection(lines, colors=c, linewidths=0.5, alpha=0.85))

            gid = k + 1
            is_active = (self.highlighted_block_id == gid)
            is_custom = (gid in self.block_custom_configs)
            tid = self.get_template_for_block(gid)
            has_tmpl = (tid in self.template_configs)

            if is_active: border_col, border_lw = "red", 2.4
            elif is_custom: border_col, border_lw = "#e67e22", 2.0
            elif has_tmpl: border_col, border_lw = "#2980b9", 1.6
            else: border_col, border_lw = "black", 0.8

            border = [v[0], v[-1], v[:, 0], v[:, -1]]
            self.ax_mesh.add_collection(LineCollection(border, colors=border_col, linewidths=border_lw))

            cx, cy = float(np.mean(bx * 1e3)), float(np.mean(by * 1e3))
            badge_lbl = f"Б{gid} ★" if is_custom else (f"Б{gid} [T{tid}]" if has_tmpl else f"Б{gid}")
            badge_col = "#ffe0b2" if is_custom else ("#d4e6f1" if has_tmpl else "#ffffff")

            self.ax_mesh.text(
                cx, cy, badge_lbl, fontsize=7.5, fontweight="bold", color="#111", ha="center", va="center",
                bbox=dict(boxstyle="round,pad=0.2", facecolor=badge_col, alpha=0.9, edgecolor=border_col, linewidth=0.8)
            )

        if prev_xlim is not None and prev_ylim is not None:
            self.ax_mesh.set_xlim(prev_xlim); self.ax_mesh.set_ylim(prev_ylim)
        else:
            self.ax_mesh.autoscale_view(); self._mesh_drawn = True

        self.ax_mesh.set_aspect("equal", adjustable="box")
        self.ax_mesh.set_xlabel("X (мм)"); self.ax_mesh.set_ylabel("Y (мм)")
        self.ax_mesh.set_title(f"Сетка выбранной области: {len(res.blocks)} блоков")
        self.canvas_mesh.draw_idle()
        self.redraw_layer_plot_for_block(self.active_plot_block_idx)

    def highlight_mesh_block(self, global_block_id):
        self.highlighted_block_id = global_block_id
        self.redraw_mesh_views()

    def on_check_quality(self):
        if self.current_quality_report is None: return
        try:
            from mesh_gui import QualityDialog
            from mesh_quality import DEFAULT_PROFILE
            dlg = QualityDialog(
                self, report=self.current_quality_report,
                kind="3D сетка выбранных подканалов ТВС", profile=DEFAULT_PROFILE,
                result=self.current_mesh_result
            )
            dlg.exec()
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка контроля качества", f"Не удалось открыть окно контроля качества:\n{exc}")

    def on_export_starccm_dialog(self):
        if self.current_mesh_result is None or not self.current_mesh_result.complete:
            QMessageBox.warning(self, "Предупреждение", "Сетка не заполнена! Сначала заполните ядро подканала.")
            return
        try:
            from mesh_subchannel_subpanel import StarCcmExportDialog
            f_props = getattr(self.mesh_subpanel, "current_fluid_props", {})
            yp_data = getattr(self.mesh_subpanel, "last_yplus_result", {})
            dlg = StarCcmExportDialog(
                self, mesh_result=self.current_mesh_result,
                bundle_model=self.model, fluid_props=f_props, yplus_data=yp_data
            )
            dlg.exec()
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть окно экспорта STAR-CCM+:\n{exc}")

    def on_export_plot3d(self):
        if self.current_mesh_result is None or not self.current_mesh_result.complete:
            QMessageBox.warning(self, "Предупреждение", "Нельзя экспортировать неполную сетку! Сначала заполните ядро сетки.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить сетку Plot3D", "bundle_subchannels.xyz", "Plot3D (*.xyz)")
        if path:
            try:
                ms.export_subchannel_plot3d(self.current_mesh_result, path)
                QMessageBox.information(self, "Успешно", f"Сетка успешно сохранена в файл:\n{path}")
            except Exception as exc:
                QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить сетку:\n{exc}")

def main():
    app = QApplication(sys.argv)
    window = BundleBuilderWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
