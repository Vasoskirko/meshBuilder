# -*- coding: utf-8 -*-
"""UI construction mixin; mechanically extracted without behaviour changes."""
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QGroupBox, QHBoxLayout, QHeaderView, QLabel, QPushButton, QScrollArea, QSplitter, QStackedWidget, QTableWidget, QTabWidget, QVBoxLayout, QWidget
from mesh_subchannel_subpanel import MeshSubpanel


class BundleBuilderUiMixin:
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

        hint = QLabel(
            "<b>Управление кликом мыши:</b><br>"
            "&bull; <b>Клик по стержню</b> — выбор (повторный клик снимает выбор)<br>"
            "&bull; <b>Клик по зазору / знакам (+) / (−)</b> — выбор подканала<br>"
            "&bull; <b>Клик по пустому фону</b> — снять выбор со стержня<br>"
            "&bull; <b>Колёсико</b> — зум к курсору<br>"
            "&bull; <b>Правая/средняя кнопка</b> — панорамирование"
        )
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
        self.btn_goto_mesh.setStyleSheet(
            "font-weight: bold; background-color: #2e7d32; color: white; padding: 8px; font-size: 13px; border-radius: 4px;"
        )
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

        self.chk_compare_core=QCheckBox('До сглаживания — серый пунктир',self)
        self.chk_compare_core.setChecked(True);self.chk_compare_core.setEnabled(False)
        self.chk_compare_core.toggled.connect(self.redraw_mesh_views)
        bar_mesh.addWidget(self.chk_compare_core)

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
            "№ Блока и сектор",
            "Закон сгущения",
            "Опорный стержень",
            "Шаг у стенки h1 (мкм)",
            "Слоёв по нормали",
            "Ячеек по дуге",
            "Шаг по дуге Δs (мкм)",
            "Параметр закона",
            "Шаг в ядре (мкм)",
            "Вытянутость AR",
        ])
        self.table_blocks.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table_blocks.setSelectionBehavior(QTableWidget.SelectRows)
        self.table_blocks.setAlternatingRowColors(True)
        self.table_blocks.itemSelectionChanged.connect(self.on_table_block_selected)
        lay_tbl.addWidget(self.table_blocks, 1)

        # Block table belongs with the normal-step plots on tab 3.
        self.mesh_splitter.setStretchFactor(0, 6)
        self.mesh_splitter.setStretchFactor(1, 4)
        self.mesh_splitter.setSizes([600, 420])

        lay_mesh.addWidget(self.mesh_splitter, 1)
        self.tabs.addTab(tab_mesh, "2. Сетка в сечении")

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
        layer_plot_widget = QWidget()
        layer_plot_layout = QVBoxLayout(layer_plot_widget)
        layer_plot_layout.setContentsMargins(0,0,0,0)
        layer_plot_layout.addWidget(self.toolbar_layers)
        layer_plot_layout.addWidget(self.canvas_layers, 1)
        self.layers_splitter = QSplitter(Qt.Horizontal, self)
        self.layers_splitter.addWidget(right_table_widget)
        self.layers_splitter.addWidget(layer_plot_widget)
        self.layers_splitter.setSizes([450,650])
        lay_layers.addWidget(self.layers_splitter,1)
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
