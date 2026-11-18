# -*- coding: utf-8 -*-
import os

os.environ["QT_API"] = "pyside6"

import math
import sys
import traceback

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure
from PySide6.QtCore import QObject, Qt, QThread, Signal, Slot
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from mesh_core import (
    CoreParams,
    MeshParams,
    MeshWorkflow,
    UI_LAWS,
    UNITS,
    available_modes,
    generate_mesh,
    load_configuration,
    save_configuration,
    save_mesh,
    shape_bounds,
)
from mesh_help_dialog import HelpDialog
from mesh_project import (
    FORMAT,
    MeshProject,
    ProjectCore,
    load_project_info,
    merge_project_inputs,
    save_project as write_project,
)
from mesh_quality import (
    DEFAULT_PROFILE,
    analyse_result,
    save_report as write_quality_report,
)
from mesh_quality_dialog import QualityDialog
from mesh_ui import NumberValue, compact, context_topic, length_text


class NumberField(QLineEdit):
    edited = Signal()

    def __init__(self, value, factor=1.0, minimum=0.0, maximum=1e12):
        super().__init__()
        self.model = NumberValue(value, factor, minimum, maximum)
        self.setText(self.model.display())
        self.textEdited.connect(self._edited)
        self.editingFinished.connect(self._finish)
        self.setToolTip(
            "Допустимы запятая, точка и научная запись: 5,7; 5.7; 5.7e-6. Отображение не округляет хранимое значение."
        )

    def _edited(self, *_):
        self.setStyleSheet("")
        self.edited.emit()

    def _finish(self):
        try:
            self.value()
        except ValueError:
            self.setStyleSheet("border:1px solid #c33;")

    def value(self):
        value = self.model.commit(self.text())
        self.setText(self.model.display())
        self.setStyleSheet("")
        return value

    def setValue(self, value):
        self.setText(self.model.set_value(value))
        self.setStyleSheet("")

    def setFactor(self, factor):
        self.value()
        self.setText(self.model.change_factor(factor))

    def setLimits(self, minimum, maximum):
        self.model.minimum, self.model.maximum = minimum, maximum


class Worker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, task):
        super().__init__()
        self.task = task

    @Slot()
    def run(self):
        try:
            value = self.task()
        except Exception:
            self.failed.emit(traceback.format_exc())
        else:
            self.succeeded.emit(value)


class MeshWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Генератор сетки — 0.6.6-quality")
        self.resize(1330, 900)
        self.fields = {}
        self.workflow = MeshWorkflow()
        self.busy = False
        self.updating = True
        self.thread = self.worker = None
        self.geometry_unit = "мм"
        self.cell_unit = "мкм"
        self.project_base_params = None
        self.project_loaded_core = None
        self.project_core_missing = False
        self.project_path = None
        self.project_import_source = None
        self.project_modified = False
        self.project_tracking_ready = False
        self.project_modified_callback = self.mark_project_modified
        self.make_ui()
        self.apply_params(MeshParams(), "мм", "мкм")
        self.updating = False
        self.help_dialog = None
        self.install_help()
        self.install_project_tracking()
        self.project_tracking_ready = True
        self.update_project_title()
        self.statusBar().showMessage("Задайте первый шаг и число ячеек либо максимальный размер")

    @property
    def result(self):
        return self.workflow.result

    @result.setter
    def result(self, value):
        self.workflow.result = value

    @property
    def stale(self):
        return self.workflow.stale

    @stale.setter
    def stale(self, value):
        self.workflow.stale = value

    def install_help(self):
        menu = self.menuBar().addMenu("Справка")
        self.help_action = QAction("Руководство пользователя…", self)
        self.help_action.setObjectName("helpAction")
        self.help_action.setShortcut("F1")
        self.help_action.triggered.connect(lambda checked=False: self.open_help(False))
        menu.addAction(self.help_action)
        self.context_help_action = QAction("Справка по выбранному способу…", self)
        self.context_help_action.setShortcut("Shift+F1")
        self.context_help_action.triggered.connect(lambda checked=False: self.open_help(True))
        menu.addAction(self.context_help_action)

    def open_help(self, context=False):
        if self.help_dialog is None:
            self.help_dialog = HelpDialog(self)
        self.help_dialog.show_topic(context_topic(self.current_law(), self.goal.currentData() if context else None))
        self.help_dialog.show()
        self.help_dialog.raise_()
        self.help_dialog.activateWindow()

    def number(self, key, value, factor=1.0, minimum=0.0, maximum=1e12, on_change=None):
        w = NumberField(value, factor, minimum, maximum)
        w.edited.connect(self.invalidate if on_change is None else on_change)
        self.fields[key] = w
        return w

    def integer(self, key, value, minimum=0, maximum=5000, on_change=None):
        w = QSpinBox()
        w.setRange(minimum, maximum)
        w.setValue(value)
        w.setKeyboardTracking(False)
        w.valueChanged.connect(self.invalidate if on_change is None else on_change)
        self.fields[key] = w
        return w

    def row(self, layout, label, widget):
        container = QWidget()
        row = QHBoxLayout(container)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel(label), 1)
        row.addWidget(widget, 1)
        layout.addWidget(container)
        return container

    def make_ui(self):
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.setCentralWidget(splitter)
        self.left = QWidget()
        left = QVBoxLayout(self.left)

        group = QGroupBox("Геометрия")
        box = QVBoxLayout(group)
        self.geometry_box = box
        self.gu = QComboBox()
        self.gu.addItems(list(UNITS))
        self.gu.setCurrentText("мм")
        self.gu.currentTextChanged.connect(self.change_geometry_unit)
        self.row(box, "Единицы геометрии", self.gu)
        for key, label, value in (
            ("d_rod", "Диаметр стержня", 0.0091),
            ("pitch", "Шаг решётки", 0.01275),
            ("z_len", "Высота области", 0.05),
        ):
            self.row(box, label, self.number(key, value, 1e-3, 1e-18, 1000))
        left.addWidget(group)

        group = QGroupBox("Разрешение")
        box = QVBoxLayout(group)
        self.row(box, "Узлы по азимуту", self.integer("ni", 120, 2))
        self.row(box, "Ячейки по высоте", self.integer("nz", 10, 1, 1000000))
        left.addWidget(group)

        group = QGroupBox("Сетка от стенки")
        box = QVBoxLayout(group)
        self.cu = QComboBox()
        self.cu.addItems(list(UNITS))
        self.cu.setCurrentText("мкм")
        self.cu.currentTextChanged.connect(self.change_cell_unit)
        self.row(box, "Единицы размеров ячеек", self.cu)
        self.law = QComboBox()
        for key, label in UI_LAWS.items():
            self.law.addItem(label, key)
        self.law.currentIndexChanged.connect(self.law_changed)
        self.row(box, "Распределение", self.law)
        self.hyper_function = QComboBox()
        self.hyper_function.addItem("Гиперболический тангенс (tanh)", "tanh")
        self.hyper_function.addItem("Гиперболический синус (sinh)", "sinh")
        self.hyper_function.currentIndexChanged.connect(self.hyperbolic_changed)
        self.hyperrow = self.row(box, "Функция", self.hyper_function)
        self.goal = QComboBox()
        self.goal.currentIndexChanged.connect(self.goal_changed)
        self.goal_row = self.row(box, "Что задаём", self.goal)
        self.help_button = QPushButton("?")
        self.help_button.setFixedWidth(30)
        self.help_button.setToolTip("Справка по выбранной функции и способу задания")
        self.help_button.clicked.connect(lambda: self.open_help(True))
        self.goal_row.layout().addWidget(self.help_button)
        self.h1row = self.row(box, "Первый шаг от стенки", self.number("h1", 5.7e-6, 1e-6, 1e-18, 1000))
        self.countrow = self.row(box, "Число ячеек от стенки", self.integer("layers", 199, 2))
        self.maxrow = self.row(box, "Максимальный размер", self.number("hmax", 30e-6, 1e-6, 1e-18, 1000))
        self.growthrow = self.row(box, "Предел коэффициента роста q", self.number("growth_limit", 1.02, minimum=1.0, maximum=100.0))
        self.fields["growth_limit"].setToolTip("Верхний предел q. 1,02 соответствует росту не более 2%.")
        self.smoothing = QComboBox()
        for key, label in (("auto", "Автоматически"), ("none", "Без сглаживания"), ("manual", "Вручную")):
            self.smoothing.addItem(label, key)
        self.smoothing.currentIndexChanged.connect(self.smoothing_changed)
        self.smoothrow = self.row(box, "Переход к постоянному шагу", self.smoothing)
        self.layer_countrow = self.row(box, "Ячеек пристеночного слоя", self.integer("layer_cells", 40, 2, 5000))
        self.layer_thicknessrow = self.row(
            box, "Общая толщина слоя", self.number("layer_thickness", 0.35e-3, 1e-6, 1e-18, 1000)
        )
        self.layer_growthrow = self.row(
            box, "Коэффициент роста слоя q", self.number("layer_growth", 1.05, minimum=1.0, maximum=100.0)
        )
        self.fields["h1"].setToolTip(
            "В режиме отдельного слоя это нормальная высота первой ячейки, а не расстояние до её центра и не y+. "
            "В прежних законах — длина первого отрезка вдоль линии."
        )
        self.fields["hmax"].setToolTip(
            "Предел размера вдоль линии при построении полной сетки. Для отдельного пристеночного слоя не используется."
        )
        self.recipe = QLabel()
        self.recipe.setWordWrap(True)
        box.addWidget(self.recipe)
        left.addWidget(group)

        self.advanced_toggle = QCheckBox("Расширенные настройки")
        left.addWidget(self.advanced_toggle)
        self.advanced = QGroupBox("Ручное управление")
        adv = QVBoxLayout(self.advanced)
        self.mode = QComboBox()
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.row(adv, "Режим расчёта", self.mode)
        self.parameter_label = QLabel("Рост соседних ячеек, %")
        self.shape_row = QWidget()
        r = QHBoxLayout(self.shape_row)
        r.setContentsMargins(0, 0, 0, 0)
        r.addWidget(self.parameter_label, 1)
        r.addWidget(self.number("shape", 2.0, minimum=0, maximum=9900), 1)
        adv.addWidget(self.shape_row)
        self.wallrow = self.row(adv, "Ячеек пристеночной прогрессии", self.integer("wall_layers", 40, 2, 4999))
        self.transitionrow = self.row(adv, "Ячеек перехода (вручную)", self.integer("transition_layers", 12, 0, 4998))
        self.epsrow = self.row(adv, "Изменение коэффициента за шаг, %", self.number("smoothing_percent", 0.5, minimum=1e-9, maximum=100))
        self.scanrow = self.row(adv, "Лимит поиска переходных ячеек", self.integer("max_transition_layers", 64, 0, 4998))
        self.row(adv, "Лимит автоматического числа ячеек", self.integer("max_auto_cells", 5000, 2, 5000))
        self.full = QCheckBox("Оба канала полностью (12 блоков)")
        self.full.setChecked(True)
        self.full.toggled.connect(self.invalidate)
        self.geometry_box.addWidget(self.full)
        self.advanced_note = QLabel()
        self.advanced_note.setWordWrap(True)
        adv.addWidget(self.advanced_note)
        left.addWidget(self.advanced)
        self.advanced_toggle.toggled.connect(
            lambda checked: self.advanced.setVisible(
                checked and self.current_law() not in ("geometric", "tanh", "sinh", "power", "uniform")
            )
        )
        self.advanced.setVisible(False)

        self.build_button = QPushButton("Построить сетку")
        self.build_button.clicked.connect(self.build_mesh)
        left.addWidget(self.build_button)

        self.core_group = QGroupBox("Ядро после независимого слоя")
        core_box = QVBoxLayout(self.core_group)
        self.row(core_box, "Номинальный рост ядра q", self.number("core_growth", 1.1, minimum=1.0, maximum=100.0, on_change=self.invalidate_core))
        self.row(core_box, "Предельный шаг ядра вдоль линии", self.number("core_max_size", 30e-6, 1e-6, 1e-18, 1000, on_change=self.invalidate_core))
        self.row(core_box, "Лимит ячеек ядра на линии", self.integer("core_max_cells", 5000, 1, 100000, on_change=self.invalidate_core))
        self.fields["core_growth"].setToolTip("Номинальный рост. При согласовании длины фактический рост может быть меньше. Размеры не убывают.")
        self.fields["core_max_size"].setToolTip("Верхний предел вдоль линий ядра; не ограничивает азимут и высоту. Не меняет пристеночный слой.")
        note = QLabel(
            "Сначала постройте слой. Изменение параметров ядра сохраняет слой. "
            "Используйте «Сохранить проект…» и «Открыть проект…» для полного набора параметров."
        )
        note.setWordWrap(True)
        core_box.addWidget(note)
        self.project_target = QComboBox()
        self.project_target.addItem("Слой + ядро", "layer_and_core")
        self.project_target.addItem("Только слой", "layer_only")
        self.project_target.setToolTip("Сохраняемая цель; не запускает расчёт и не меняет готовую сетку.")
        self.row(core_box, "Цель проекта", self.project_target)
        self.core_button = QPushButton("Заполнить ядро")
        self.core_button.setEnabled(False)
        self.core_button.clicked.connect(self.build_core)
        core_box.addWidget(self.core_button)
        self.core_help = QPushButton("Как работает заполнение?")
        self.core_help.clicked.connect(self.open_core_help)
        core_box.addWidget(self.core_help)
        left.addWidget(self.core_group)

        self.save_button = QPushButton("Сохранить сетку XYZ…")
        self.save_button.clicked.connect(self.export_mesh)
        self.save_button.setEnabled(False)
        left.addWidget(self.save_button)
        self.quality_button = QPushButton("Проверить метрики сетки…")
        self.quality_button.setEnabled(False)
        self.quality_button.setToolTip(
            "Рассчитать метрики качества текущей сетки (слой или полная сетка). Не меняет сетку и не помечает проект изменённым."
        )
        self.quality_button.clicked.connect(self.check_quality)
        left.addWidget(self.quality_button)
        self.project_save_button = QPushButton("Сохранить проект…")
        self.project_save_button.clicked.connect(self.save_project_file)
        left.addWidget(self.project_save_button)
        self.project_open_button = QPushButton("Открыть проект…")
        self.project_open_button.setToolTip("Восстановить параметры без запуска расчёта. Старый результат станет неактуальным.")
        self.project_open_button.clicked.connect(self.open_project_file)
        left.addWidget(self.project_open_button)
        row = QHBoxLayout()
        for title, slot in (("Сохранить настройки…", self.save_settings), ("Загрузить…", self.load_settings)):
            b = QPushButton(title)
            b.clicked.connect(slot)
            row.addWidget(b)
        left.addLayout(row)
        left.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.left)
        splitter.addWidget(scroll)

        right = QWidget()
        layout = QVBoxLayout(right)
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Блок:"))
        self.block = QComboBox()
        self.block.addItem("Все", -1)
        self.block.currentIndexChanged.connect(self.redraw)
        controls.addWidget(self.block)
        controls.addWidget(QLabel("Детальность:"))
        self.detail = QComboBox()
        for label, stride in (("Все линии", 1), ("Средняя", 4), ("Обзорная", 10)):
            self.detail.addItem(label, stride)
        self.detail.setCurrentIndex(1)
        self.detail.currentIndexChanged.connect(self.redraw)
        self.detail.setToolTip("Меняется только изображение, не число ячеек и не экспорт")
        controls.addWidget(self.detail)
        self.nodes = QCheckBox("Узлы")
        self.nodes.toggled.connect(self.redraw)
        controls.addWidget(self.nodes)
        self.zones = QCheckBox("Границы зон")
        self.zones.setChecked(True)
        self.zones.toggled.connect(self.redraw)
        controls.addWidget(self.zones)
        layout.addLayout(controls)

        tabs = QTabWidget()
        self.canvases = []
        self.axes = []
        for label in ("Сетка", "Размеры ячеек от стенки"):
            page = QWidget()
            pl = QVBoxLayout(page)
            fig = Figure(constrained_layout=True)
            canvas = FigureCanvasQTAgg(fig)
            ax = fig.add_subplot(111)
            pl.addWidget(NavigationToolbar2QT(canvas, self))
            pl.addWidget(canvas)
            tabs.addTab(page, label)
            self.canvases.append(canvas)
            self.axes.append(ax)
        layout.addWidget(tabs, 1)

        self.summary = QLabel("Сетка ещё не построена")
        self.summary.setWordWrap(True)
        self.summary.setStyleSheet("QLabel {background:#edf3f7; padding:12px; border-radius:5px;}")
        layout.addWidget(self.summary)
        self.details_toggle = QCheckBox("Подробности расчёта")
        layout.addWidget(self.details_toggle)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(190)
        self.details.setVisible(False)
        self.details_toggle.toggled.connect(self.details.setVisible)
        layout.addWidget(self.details)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 910])

    def current_law(self):
        key = self.law.currentData()
        return (self.hyper_function.currentData() or "tanh") if key == "hyperbolic" else key

    def hyperbolic_changed(self, *_):
        if not self.updating:
            self.law_changed()

    def set_modes(self, preferred):
        law = self.current_law()
        self.mode.blockSignals(True)
        self.mode.clear()
        for key, label in available_modes(law).items():
            self.mode.addItem(label, key)
        self.mode.setCurrentIndex(max(0, self.mode.findData(preferred)))
        self.mode.blockSignals(False)
        self.refresh_controls()

    def refresh_controls(self):
        law, mode = self.current_law(), self.mode.currentData()
        if mode is None:
            return
        geometric = law == "geometric"
        hyper = law in ("tanh", "sinh")
        power = law == "power"
        uniform = law == "uniform"
        layer = law == "wall_core"
        simple = geometric or hyper or power or uniform or layer
        self.core_group.setVisible(layer)
        self.hyperrow.setVisible(hyper)
        self.goal.blockSignals(True)
        self.goal.clear()
        if simple:
            for key, label in available_modes(law).items():
                self.goal.addItem(label, key)
        else:
            self.goal.addItem("Первый шаг + число ячеек", "first_count")
            self.goal.addItem("Первый шаг + максимальный размер", "first_max")
            if mode not in ("first_count", "first_max"):
                self.goal.addItem("Ручная конфигурация (расширенные)", mode)
        self.goal.setCurrentIndex(max(0, self.goal.findData(mode)))
        self.goal.blockSignals(False)
        self.h1row.setVisible(not uniform and mode != "shape_count" and not (layer and mode == "layer_growth"))
        self.countrow.setVisible(mode in ("first_count", "shape_count"))
        self.maxrow.setVisible(mode == "first_max")
        self.growthrow.setVisible(geometric and mode == "first_growth")
        self.h1row.layout().itemAt(0).widget().setText("Первый нормальный размер" if layer else "Первый размер вдоль линии")
        self.maxrow.layout().itemAt(0).widget().setText("Предельный размер вдоль линии")
        self.advanced_toggle.setVisible(not simple)
        self.advanced.setVisible(not simple and self.advanced_toggle.isChecked())
        self.layer_countrow.setVisible(layer)
        self.layer_thicknessrow.setVisible(layer and mode != "layer_first_growth")
        self.layer_growthrow.setVisible(layer and mode in ("layer_growth", "layer_first_growth"))
        self.build_button.setText("Построить пристеночный слой" if layer else "Построить сетку")
        self.full.setText("Оба канала (12 участков слоя)" if layer else "Оба канала полностью (12 блоков)")
        self.zones.setText("Внешняя граница слоя" if layer else "Границы зон")
        two = law == "two_zone"
        sm = self.smoothing.currentData()
        self.smoothrow.setVisible(two)
        self.wallrow.setVisible(two)
        self.transitionrow.setVisible(two and sm == "manual")
        self.epsrow.setVisible(two and sm == "auto")
        self.scanrow.setVisible(two and sm == "auto")
        self.shape_row.setVisible(not simple and mode in ("shape_count", "first_growth") and law != "uniform")
        self.parameter_label.setText(
            ("Предел роста, %" if mode == "first_growth" else "Рост соседних ячеек, %")
            if law in ("geometric", "two_zone")
            else ("Параметр β" if hyper else "Показатель p")
        )
        if layer:
            text = (
                "Строится только независимый радиальный слой. Толщина и количество фиксированы. "
                "При вводе первого размера подбирается q; при вводе q рассчитывается первый размер. "
                "Ядро и переход не строятся и не ограничивают слой."
            )
        elif geometric:
            text = {
                "first_count": "Первый размер и число ячеек фиксированы. Коэффициенты роста подбираются по линиям и выводятся в результатах.",
                "first_max": "Подбираются общее число ячеек и коэффициенты роста. Заданный размер — верхний предел, не требование точного равенства.",
                "first_growth": "Подбирается общее число ячеек. Фактический q каждой линии не превышает предел. 1,02 соответствует росту не более 2%.",
            }[mode]
        elif hyper:
            text = (
                "Первый размер и число ячеек фиксированы. Параметр β подбирается по каждой линии."
                if mode == "first_count"
                else "Подбираются общее число ячеек и параметры β. Предельный размер — верхняя граница, не точное равенство."
            )
            text += " β не является коэффициентом роста соседних ячеек; его значения доступны в подробностях расчёта."
        elif power:
            text = (
                "Первый размер и число ячеек фиксированы. Показатель p подбирается по каждой линии."
                if mode == "first_count"
                else "Подбираются общее число ячеек и показатели p. Предельный размер — верхняя граница, не точное равенство."
            )
            text += " p не является коэффициентом роста; смотрите фактический рост соседних ячеек в результате."
        elif uniform:
            text = (
                "Задано число ячеек. Постоянный шаг рассчитывается отдельно для каждой линии."
                if mode == "shape_count"
                else "Число ячеек вычисляется по самой длинной линии. Шаг нигде не превышает заданный предел."
            )
            text += " Вдоль каждой линии шаг постоянный, между линиями он может различаться."
        else:
            text = (
                (
                    "Переход «Авто» подбирается по критерию изменения роста. Число пристеночных ячеек и допуск доступны в расширенных настройках."
                    if sm == "auto"
                    else "Числа ячеек участков одинаковы по линиям; физические расстояния до границ зон могут различаться."
                )
                if two
                else (
                    "Шаг вычисляется из длины каждой линии."
                    if law == "uniform"
                    else "Параметр распределения подбирается автоматически."
                    if mode in ("first_count", "first_max")
                    else "Активна ручная конфигурация. Параметры находятся в расширенных настройках."
                )
            )
        self.recipe.setText(text)
        self.advanced_note.setText(
            "Допуск сглаживания — математический критерий изменения роста, не гарантия качества CFD-сетки. "
            "Максимальный размер и рост — верхние пределы, не точные равенства."
        )

    def law_changed(self, *_):
        if self.updating:
            return
        law = self.current_law()
        a, b = shape_bounds(law)
        self.fields["shape"].setLimits(
            (a - 1) * 100 if law in ("geometric", "two_zone") else a,
            (b - 1) * 100 if law in ("geometric", "two_zone") else b,
        )
        self.fields["shape"].setValue(2 if law != "uniform" else 1)
        if law == "geometric":
            self.fields["growth_limit"].setValue(1.02)
        self.set_modes(self.mode.currentData())
        self.invalidate()

    def mode_changed(self, *_):
        if not self.updating:
            self.refresh_controls()
            self.invalidate()

    def goal_changed(self, *_):
        if self.updating:
            return
        mode = self.goal.currentData()
        index = self.mode.findData(mode)
        if index >= 0:
            self.mode.setCurrentIndex(index)

    def smoothing_changed(self, *_):
        if not self.updating:
            if self.smoothing.currentData() == "manual":
                self.advanced_toggle.setChecked(True)
            self.refresh_controls()
            self.invalidate()

    def invalidate(self, *_):
        if self.updating:
            return
        self.workflow.invalidate_layer()
        self.update_actions()
        if self.result is not None:
            self.show_summary()
            self.statusBar().showMessage(
                "Параметры слоя/геометрии изменены — постройте слой заново. На графике предыдущий результат."
            )

    def update_actions(self):
        self.save_button.setEnabled(not self.busy and self.workflow.can_export)
        self.core_button.setEnabled(not self.busy and self.current_law() == "wall_core" and self.workflow.can_fill)
        self.build_button.setEnabled(not self.busy)
        quality = getattr(self, "quality_button", None)
        if quality is not None:
            quality.setEnabled(not self.busy and self.result is not None and not self.stale)

    def invalidate_core(self, *_):
        if self.updating:
            return
        self.project_core_missing = False
        self.workflow.invalidate_core()
        self.update_actions()
        if self.workflow.can_fill:
            self.display_result()
            self.statusBar().showMessage("Параметры ядра изменены. Слой сохранён; заполните ядро заново.")

    def read_core_params(self):
        f = self.fields
        params = CoreParams(
            growth=f["core_growth"].value(),
            max_size=f["core_max_size"].value(),
            max_cells=f["core_max_cells"].value(),
        )
        params.validate()
        return params

    def build_core(self):
        if self.busy or self.current_law() != "wall_core":
            return
        self.workflow.invalidate_core()
        self.update_actions()
        if self.workflow.can_fill:
            self.display_result()
        try:
            p = self.read_params()
            p.validate()
            if not self.workflow.matches_layer(p):
                self.invalidate()
                raise ValueError("Слой не построен или его параметры изменены. Сначала постройте пристеночный слой.")
            core = self.read_core_params()
            layer = self.workflow.layer
            estimate = 16 * p.ni * (p.wall_layers + core.max_cells + 1) * ((12 if p.full else 2) + 12) / 1e6
            if estimate > 500:
                answer = QMessageBox.question(
                    self,
                    "Большая сетка",
                    f"Верхняя оценка памяти при лимите ядра: {compact(estimate, 4)} МБ или больше. Продолжить?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
        except Exception as exc:
            QMessageBox.warning(self, "Параметры ядра", str(exc))
            return
        self.start_task(lambda: core.fill(layer), self.core_ready, "Заполнение и проверка ядра…")

    @Slot(object)
    def core_ready(self, result):
        self.workflow.accept_core(result)
        self.display_result()
        self.statusBar().showMessage("Ядро построено. Исходный слой сохранён. Полная сетка готова к экспорту.")

    def display_result(self):
        result = self.result
        if result is None:
            return
        self.block.blockSignals(True)
        self.block.clear()
        self.block.addItem("Все", -1)
        for k in range(len(result.blocks)):
            self.block.addItem(str(k + 1), k)
        self.block.blockSignals(False)
        self.save_button.setToolTip(
            "Экспорт полной сетки" if result.complete else "Ядро не построено: экспорт полной сетки заблокирован"
        )
        self.update_actions()
        self.redraw()

    def open_core_help(self):
        if self.help_dialog is None:
            self.help_dialog = HelpDialog(self)
        self.help_dialog.show_topic("core_fill")
        self.help_dialog.show()
        self.help_dialog.raise_()
        self.help_dialog.activateWindow()

    def change_units(self, group, new):
        if self.updating:
            return
        selector = self.gu if group == "geometry" else self.cu
        old = self.geometry_unit if group == "geometry" else self.cell_unit
        allkeys = ("d_rod", "pitch", "z_len") if group == "geometry" else ("h1", "hmax", "layer_thickness", "core_max_size")
        law, mode = self.current_law(), self.mode.currentData()
        if group == "geometry":
            active = allkeys
        elif law == "wall_core":
            active = ("h1", "layer_thickness") if mode == "layer_thickness" else ("layer_thickness",)
        else:
            active = tuple(
                k
                for k in ("h1", "hmax")
                if (k == "h1" and law != "uniform" and mode != "shape_count") or (k == "hmax" and mode == "first_max")
            )
        if group == "cell" and law == "wall_core":
            active = active + ("core_max_size",)
        try:
            for key in active:
                self.fields[key].value()
        except ValueError as exc:
            selector.blockSignals(True)
            selector.setCurrentText(old)
            selector.blockSignals(False)
            QMessageBox.warning(self, "Число", str(exc))
            return
        for key in allkeys:
            field = self.fields[key]
            field.model.factor = UNITS[new]
            field.setText(field.model.display())
        if group == "geometry":
            self.geometry_unit = new
        else:
            self.cell_unit = new
        modified = getattr(self, "project_modified_callback", None)
        if callable(modified):
            modified()
        self.redraw()

    def change_geometry_unit(self, new):
        self.change_units("geometry", new)

    def change_cell_unit(self, new):
        self.change_units("cell", new)

    def read_params(self):
        f = self.fields
        law = self.current_law()
        mode = self.mode.currentData()
        sm = self.smoothing.currentData()
        if law == "wall_core":
            return MeshParams(
                d_rod=f["d_rod"].value(),
                pitch=f["pitch"].value(),
                z_len=f["z_len"].value(),
                ni=f["ni"].value(),
                nz=f["nz"].value(),
                full=self.full.isChecked(),
                law=law,
                mode=mode,
                wall_layers=f["layer_cells"].value(),
                layer_thickness=f["layer_thickness"].value(),
                h1=f["h1"].value() if mode in ("layer_thickness", "layer_first_growth") else f["h1"].model.raw,
                layer_growth=f["layer_growth"].value() if mode in ("layer_growth", "layer_first_growth") else f["layer_growth"].model.raw,
            )

        if law == "geometric":
            shape = f["growth_limit"].value() if mode == "first_growth" else 1.02
        elif law in ("tanh", "sinh", "power"):
            shape = 2.0
        else:
            manual = mode in ("shape_count", "first_growth") and law != "uniform"
            shape = f["shape"].value() if manual else 2.0
            if law == "two_zone":
                shape = 1 + shape / 100
            if law == "uniform":
                shape = 1.0
        return MeshParams(
            d_rod=f["d_rod"].value(),
            pitch=f["pitch"].value(),
            z_len=f["z_len"].value(),
            ni=f["ni"].value(),
            nj=f["layers"].value() + 1,
            nz=f["nz"].value(),
            h1=f["h1"].value() if law != "uniform" and mode != "shape_count" else f["h1"].model.raw,
            hmax=f["hmax"].value() if mode == "first_max" else f["hmax"].model.raw,
            full=self.full.isChecked(),
            law=law,
            mode=mode,
            shape=shape,
            wall_layers=f["wall_layers"].value(),
            transition_layers=f["transition_layers"].value(),
            smoothing=sm,
            smoothing_percent=(
                f["smoothing_percent"].value() if law == "two_zone" and sm == "auto" else f["smoothing_percent"].model.raw
            ),
            max_transition_layers=f["max_transition_layers"].value(),
            max_auto_cells=f["max_auto_cells"].value(),
        )

    def capture_state(self):
        numbers = {
            k: (w.model.raw, w.model.factor, w.model.minimum, w.model.maximum, w.model.last_text, w.text(), w.styleSheet())
            for k, w in self.fields.items()
            if isinstance(w, NumberField)
        }
        integers = {k: w.value() for k, w in self.fields.items() if isinstance(w, QSpinBox)}
        return dict(
            gu=self.geometry_unit,
            cu=self.cell_unit,
            law=self.law.currentData(),
            hyper=self.hyper_function.currentData(),
            smoothing=self.smoothing.currentData(),
            mode=self.mode.currentData(),
            full=self.full.isChecked(),
            advanced=self.advanced_toggle.isChecked(),
            numbers=numbers,
            integers=integers,
        )

    def restore_state(self, s):
        self.geometry_unit, self.cell_unit = s["gu"], s["cu"]
        self.gu.setCurrentText(s["gu"])
        self.cu.setCurrentText(s["cu"])
        self.law.setCurrentIndex(self.law.findData(s["law"]))
        self.hyper_function.setCurrentIndex(self.hyper_function.findData(s["hyper"]))
        self.smoothing.setCurrentIndex(self.smoothing.findData(s["smoothing"]))
        for key, (raw, factor, minimum, maximum, last_text, text, style) in s["numbers"].items():
            field = self.fields[key]
            model = field.model
            model.raw, model.factor, model.minimum, model.maximum, model.last_text = raw, factor, minimum, maximum, last_text
            QLineEdit.setText(field, text)
            field.setStyleSheet(style)
        for key, value in s["integers"].items():
            QSpinBox.setValue(self.fields[key], value)
        self.full.setChecked(s["full"])
        self.set_modes(s["mode"])
        self.advanced_toggle.setChecked(s["advanced"])

    def check_numbers(self, p):
        a, b = shape_bounds(p.law)
        scaled = p.law in ("geometric", "two_zone")
        bounds = ((a - 1) * 100, (b - 1) * 100) if scaled else (a, b)
        shape = (p.shape - 1) * 100 if scaled else (1.0 if p.law == "uniform" else p.shape)
        growth = p.shape if p.law == "geometric" and p.mode == "first_growth" else 1.02
        items = {key: (getattr(p, key), None) for key in ("d_rod", "pitch", "z_len", "h1", "hmax", "smoothing_percent")}
        items.update(shape=(shape, bounds), growth_limit=(growth, None))
        for key, (value, limits) in items.items():
            model = self.fields[key].model
            low, high = limits if limits is not None else (model.minimum, model.maximum)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{key}: значение вне диапазона интерфейса")

    def apply_layer_params(self, p, gu, cu):
        p.validate()
        if gu not in UNITS or cu not in UNITS:
            raise ValueError("Неизвестная единица")
        integers = dict(ni=p.ni, nz=p.nz, layer_cells=p.wall_layers)
        numbers = dict(d_rod=p.d_rod, pitch=p.pitch, z_len=p.z_len, layer_thickness=p.layer_thickness)
        if p.mode in ("layer_thickness", "layer_first_growth"):
            numbers["h1"] = p.h1
        if p.mode in ("layer_growth", "layer_first_growth"):
            numbers["layer_growth"] = p.layer_growth
        for key, value in integers.items():
            if not self.fields[key].minimum() <= value <= self.fields[key].maximum():
                raise ValueError(f"{key}: значение вне диапазона интерфейса")
        for key, value in numbers.items():
            model = self.fields[key].model
            if not math.isfinite(value) or not model.minimum <= value <= model.maximum:
                raise ValueError(f"{key}: значение вне диапазона интерфейса")
        previous = self.capture_state()
        was_updating = self.updating
        self.updating = True
        try:
            self.geometry_unit, self.cell_unit = gu, cu
            self.gu.setCurrentText(gu)
            self.cu.setCurrentText(cu)
            for keys, unit in ((("d_rod", "pitch", "z_len"), gu), (("h1", "hmax", "layer_thickness", "core_max_size"), cu)):
                for key in keys:
                    field = self.fields[key]
                    field.model.factor = UNITS[unit]
                    field.setText(field.model.display())
            for key, value in numbers.items():
                self.fields[key].setValue(value)
            for key, value in integers.items():
                self.fields[key].setValue(value)
            self.law.setCurrentIndex(self.law.findData("wall_core"))
            self.full.setChecked(p.full)
            self.set_modes(p.mode)
        except Exception:
            self.restore_state(previous)
            raise
        finally:
            self.updating = was_updating
        self.invalidate()

    def apply_params(self, p, gu, cu):
        if p.law == "wall_core":
            self.apply_layer_params(p, gu, cu)
            return
        p.validate()
        if max(p.ni, p.nj - 1, p.max_auto_cells, p.wall_layers + p.transition_layers) > 5000 or p.nz > 1000000 or p.max_transition_layers > 4998:
            raise ValueError("Настройки превышают ограничения интерфейса")
        for key, value in dict(
            ni=p.ni,
            layers=p.nj - 1,
            nz=p.nz,
            wall_layers=p.wall_layers,
            transition_layers=p.transition_layers,
            max_transition_layers=p.max_transition_layers,
            max_auto_cells=p.max_auto_cells,
        ).items():
            if not self.fields[key].minimum() <= value <= self.fields[key].maximum():
                raise ValueError(f"{key}: значение вне диапазона интерфейса")
        if gu not in UNITS or cu not in UNITS:
            raise ValueError("Неизвестная единица")
        self.check_numbers(p)
        previous = self.capture_state()
        was_updating = self.updating
        self.updating = True
        try:
            self.geometry_unit, self.cell_unit = gu, cu
            self.gu.setCurrentText(gu)
            self.cu.setCurrentText(cu)
            self.law.setCurrentIndex(self.law.findData("hyperbolic" if p.law in ("tanh", "sinh") else p.law))
            self.smoothing.setCurrentIndex(self.smoothing.findData(p.smoothing))
            if p.law in ("tanh", "sinh"):
                self.hyper_function.setCurrentIndex(self.hyper_function.findData(p.law))
            a, b = shape_bounds(p.law)
            self.fields["shape"].setLimits(
                (a - 1) * 100 if p.law in ("geometric", "two_zone") else a,
                (b - 1) * 100 if p.law in ("geometric", "two_zone") else b,
            )
            shape = (p.shape - 1) * 100 if p.law in ("geometric", "two_zone") else (1.0 if p.law == "uniform" else p.shape)
            for key in ("d_rod", "pitch", "z_len"):
                self.fields[key].model.factor = UNITS[gu]
                self.fields[key].setValue(getattr(p, key))
            for key in ("h1", "hmax"):
                self.fields[key].model.factor = UNITS[cu]
                self.fields[key].setValue(getattr(p, key))
            field = self.fields["core_max_size"]
            field.model.factor = UNITS[cu]
            field.setText(field.model.display())
            self.fields["shape"].setValue(shape)
            self.fields["smoothing_percent"].setValue(p.smoothing_percent)
            self.fields["growth_limit"].setValue(p.shape if p.law == "geometric" and p.mode == "first_growth" else 1.02)
            values = dict(
                ni=p.ni,
                layers=p.nj - 1,
                nz=p.nz,
                wall_layers=p.wall_layers,
                transition_layers=p.transition_layers,
                max_transition_layers=p.max_transition_layers,
                max_auto_cells=p.max_auto_cells,
            )
            for key, value in values.items():
                self.fields[key].setValue(value)
            self.full.setChecked(p.full)
            self.set_modes(p.mode)
            if p.mode in ("shape_count", "first_growth") and p.law not in ("uniform", "geometric", "tanh", "sinh", "power"):
                self.advanced_toggle.setChecked(True)
        except Exception:
            self.restore_state(previous)
            raise
        finally:
            self.updating = was_updating
        self.invalidate()

    def start_task(self, task, success, message):
        self.busy = True
        self.left.setEnabled(False)
        self.update_actions()
        self.statusBar().showMessage(message)
        self.thread = QThread(self)
        self.worker = Worker(task)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.succeeded.connect(success)
        self.worker.failed.connect(self.failed)
        self.worker.succeeded.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.worker.succeeded.connect(self.worker.deleteLater)
        self.worker.failed.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.finished)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    @Slot()
    def finished(self):
        self.busy = False
        self.left.setEnabled(True)
        self.worker = self.thread = None
        self.update_actions()

    @Slot(str)
    def failed(self, text):
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Critical)
        box.setWindowTitle("Ошибка")
        box.setText(text.strip().splitlines()[-1])
        box.setDetailedText(text)
        box.exec()
        self.statusBar().showMessage("Операция не выполнена")

    def build_mesh(self):
        if self.busy:
            return
        try:
            p = self.read_params()
            p.validate()
            n = p.wall_layers if p.law == "wall_core" else p.max_auto_cells if p.mode in ("first_max", "first_growth") else p.nj - 1
            estimate = 16 * p.ni * (n + 1) * ((12 if p.full else 2) + 12) / 1e6
            if estimate > 500:
                answer = QMessageBox.question(
                    self,
                    "Большая сетка",
                    f"Оценка памяти: {compact(estimate, 4)} МБ или больше. Продолжить?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
        except Exception as exc:
            QMessageBox.warning(self, "Параметры", str(exc))
            return
        self.invalidate()
        self.start_task(lambda: generate_mesh(p), self.ready, "Построение и проверка…")

    @Slot(object)
    def ready(self, result):
        self.workflow.accept_mesh(result)
        self.display_result()
        self.statusBar().showMessage(
            "Сетка построена и проверена"
            if result.complete
            else "Пристеночный слой построен. Теперь можно заполнить ядро."
        )

    def show_summary(self):
        if self.result is None:
            return
        r = self.result
        d = r.diagnostics
        p = r.params
        if r.complete and p.law == "wall_core" and d.get("core_built"):
            text = "Параметры изменены — ниже предыдущий результат.\n" if self.stale else "Полная сетка: слой + ядро.\n"
            text += f"Слой: {d['wall_layers']} ячеек · толщина {length_text(d['layer_thickness_actual'])} · первый размер {length_text(d['first_min'])}\n"
            text += f"Ядро: {d['core_layers']} ячеек на линии · шаг {length_text(d['core_step_min'])} … {length_text(d['core_step_max'])}\n"
            text += f"Максимальные размеры: вдоль линии {length_text(d['max_wall'])} · по азимуту {length_text(d['max_azimuth'])} · по высоте {length_text(d['max_height'])}\n"
            text += f"Всего ячеек: {d['cells']:,} · блоков: {d['blocks']} · стыков: {d['interfaces']}\n"
            text += (
                "Экспорт заблокирован: параметры изменены."
                if self.stale
                else "Слой сохранён без изменения координат. Экспорт полной сетки доступен после завершения операции."
            )
            self.summary.setText(text)
            self.details.setPlainText(
                "\n".join(
                    [
                        f"Номинальный рост ядра: {compact(d['core_growth_requested'])}",
                        f"Предел шага ядра: {length_text(d['core_max_requested'])}",
                        f"Фактическое плато по линиям: {length_text(d['core_plateau_min'])} … {length_text(d['core_plateau_max'])}",
                        f"Максимальное уменьшение плато относительно номинального: {compact(d['core_plateau_reduction_max_percent'])} %",
                        f"Максимальный рост размеров слоя и ядра: {compact(d['growth_max'])}",
                        f"Угол изменения направления при стыковке: {compact(d['core_join_angle_max_deg'])}°",
                        f"Минимальный угловой якобиан: {compact(d['min_jacobian'])} м²",
                        f"Стыков: {d['interfaces']}; максимальная ошибка {length_text(d['interface_error'])}",
                        "Положительность якобиана и совпадение стыков не заменяют полную оценку CFD-качества.",
                    ]
                )
            )
            return
        if not r.complete:
            text = "Параметры изменены — ниже предыдущий слой.\n" if self.stale else "Пристеночный слой построен.\n"
            text += f"Первый нормальный размер: {length_text(d['first_min'])}\n"
            text += f"Ячеек слоя: {d['layers']} · Толщина: {length_text(d['layer_thickness_actual'])} · q: {compact(d['layer_growth_actual'])}\n"
            text += f"Последний размер: {length_text(d['layer_last'])} · Ячеек только в слое: {d['cells']:,}\n"
            text += "Ядро: не построено. Для достройки нажмите «Заполнить ядро». Экспорт полной сетки заблокирован."
            self.summary.setText(text)
            self.details.setPlainText(
                "\n".join(
                    [
                        f"Участков слоя: {d['blocks']}; проверенных стыков: {d['interfaces']}",
                        f"Минимальный угловой якобиан: {compact(d['min_jacobian'])} м²",
                        f"Максимальное отклонение от нормали окружности: {compact(d['wall_normal_angle_max_deg'])}°",
                        f"Максимальный соседний рост в слое: {compact((d['growth_max'] - 1) * 100)} %",
                        "Размер ядра, переход, сглаживание и лимит поиска ядра не участвуют в построении слоя.",
                        "Нормальность относится к окружности. Это не полная оценка качества CFD-сетки и не y+.",
                    ]
                )
            )
            return

        text = "Параметры изменены — ниже предыдущий результат.\n" if self.stale else ""
        text += (
            f"Максимальный размер ячейки:\n  от стенки — {length_text(d['max_wall'])}    "
            f"по азимуту — {length_text(d['max_azimuth'])}    по высоте — {length_text(d['max_height'])}\n"
        )
        count = f"{d['cells']:,}".replace(",", " ")
        text += f"Ячеек от стенки: {d['layers']}   ·   Всего ячеек: {count}   ·   Блоков: {d['blocks']}"
        if p.law == "geometric":
            text += f"\nПервый размер: {length_text(d['first_min'])}"
            text += f"\nКоэффициент роста q: {compact(d['parameter_min'])} … {compact(d['parameter_max'])}"
            text += f" · рост {compact((d['parameter_min'] - 1) * 100)} … {compact((d['parameter_max'] - 1) * 100)} %"
        if p.law == "power":
            text += f"\nПервый размер: {length_text(d['first_min'])}"
        if p.law != "uniform":
            text += f"\nМаксимальный рост соседних размеров: {compact((d['growth_max'] - 1) * 100)} %"
        if p.law == "uniform":
            text += f"\nШаг вдоль линий: {length_text(d['first_min'])} … {length_text(d['first_max'])}"
            text += " (постоянный на каждой линии)"
        if p.law == "two_zone":
            text += f"\nЗоны: прогрессия {d['wall_layers']} + переход {d['transition_layers']} + ядро {d['core_layers']}"
        if not self.stale:
            text += "\nОриентация и стыки проверены; это не полная оценка CFD-сетки."
        self.summary.setText(text)
        if p.law in ("tanh", "sinh"):
            text += f"\nФункция: {p.law}; первый размер: {length_text(d['first_min'])}"
            self.summary.setText(text)
        lines = [
            f"Первый шаг: {length_text(d['first_min'])} … {length_text(d['first_max'])}",
            f"{'Подобранный параметр β' if p.law in ('tanh', 'sinh') else 'Подобранный показатель p' if p.law == 'power' else 'Параметр распределения'}: {compact(d['parameter_min'])} … {compact(d['parameter_max'])}",
            f"Максимальный рост соседних размеров: {compact((d['growth_max'] - 1) * 100)} %",
            f"Поворот поперечной линии: {compact(d['max_turning_deg'])}°",
            f"Стыков: {d['interfaces']}; max ошибка: {length_text(d['interface_error'])}",
            f"Минимальный угловой якобиан: {compact(d['min_jacobian'])} м²",
        ]
        if p.law == "uniform":
            lines[0] = f"Шаг вдоль линий: {length_text(d['first_min'])} … {length_text(d['first_max'])}"
            del lines[1:3]
        if p.law == "two_zone":
            lines += [
                f"Сглаживание: {p.smoothing}; фактическое изменение роста: {compact(d['smoothing_change_percent'])} % за шаг",
                f"Допуск Авто: {compact(p.smoothing_percent)} %; лимит поиска перехода: {p.max_transition_layers}",
                f"Начало ядра: {length_text(d['core_start_min'])} … {length_text(d['core_start_max'])} от стенки",
                f"Шаг ядра: {length_text(d['core_step_min'])} … {length_text(d['core_step_max'])}",
            ]
        lines += [
            f"Отклонение линии от нормали окружности: {compact(d['wall_normal_angle_max_deg'])}°",
            f"Расстояние первого внутреннего узла до окружности: {length_text(d['first_wall_distance_min'])} … {length_text(d['first_wall_distance_max'])}",
            "Это расстояние до узла, не до центра ячейки и не y+.",
        ]
        self.details.setPlainText("\n".join(lines))

    def redraw(self, *_):
        if self.result is None:
            return
        r = self.result
        p = r.params
        ax = self.axes[0]
        ax.clear()
        scale = UNITS[self.geometry_unit]
        selected = self.block.currentData()
        stride = self.detail.currentData()
        labelled = False
        if not r.complete:
            for line in r.domain_outline:
                ax.plot(line[:, 0] / scale, line[:, 1] / scale, color="#a0a0a0", linewidth=0.8, linestyle=":")

        colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
        for k, (x, y) in enumerate(r.blocks):
            if selected not in (-1, k):
                continue
            v = np.stack((x, y), axis=-1) / scale
            ii = np.unique(np.r_[np.arange(0, p.ni, stride), p.ni - 1])
            jj = np.unique(np.r_[np.arange(0, p.nj, stride), p.nj - 1])
            lines = [v[i] for i in ii] + [v[:, j] for j in jj]
            ax.add_collection(LineCollection(lines, colors=colors[k % 6], linewidths=0.45))
            ax.add_collection(LineCollection([v[0], v[-1], v[:, 0], v[:, -1]], colors="black", linewidths=0.8))
            if self.nodes.isChecked():
                points = np.concatenate(lines)
                ax.scatter(points[:, 0], points[:, 1], s=2, c=colors[k % 6], linewidths=0)
            if p.law == "wall_core" and self.zones.isChecked():
                frontier = r.outer_boundaries[k] / scale
                ax.plot(
                    frontier[:, 0],
                    frontier[:, 1],
                    "--",
                    color="#008000",
                    linewidth=1.2,
                    label="Внешняя граница слоя" if not labelled else "_nolegend_",
                )
                labelled = True
            if self.zones.isChecked() and p.law == "two_zone":
                zones = [(p.wall_layers + p.transition_layers, "#008000", "Начало ядра")]
                if p.transition_layers:
                    zones.insert(0, (p.wall_layers, "#e07000", "Конец прогрессии"))
                for j, color, label in zones:
                    idx = j if r.wall_start[k] else p.nj - 1 - j
                    ax.plot(
                        v[:, idx, 0],
                        v[:, idx, 1],
                        "--",
                        color=color,
                        linewidth=1.3,
                        label=label if not labelled else "_nolegend_",
                    )
                labelled = True
        ax.autoscale_view()
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlabel(f"x, {self.geometry_unit}")
        ax.set_ylabel(f"y, {self.geometry_unit}")
        ax.set_title(
            "Предыдущий результат"
            if self.stale
            else "Пристеночный слой — ядро не построено"
            if not r.complete
            else "Поперечное сечение"
        )
        if labelled:
            ax.legend(fontsize=8)
        self.canvases[0].draw_idle()

        ax = self.axes[1]
        ax.clear()
        if not r.complete:
            ax.plot(
                np.arange(1, p.nj),
                r.layer_widths[0] / UNITS[self.cell_unit],
                label="Пристеночный слой (одинаков на всех линиях)",
            )
        else:
            for index, label in ((0, "Длинная линия"), (p.ni // 2, "Промежуточная"), (p.ni - 1, "Короткая линия")):
                ax.plot(np.arange(1, p.nj), r.layer_widths[index] / UNITS[self.cell_unit], label=label)
        if p.law == "two_zone":
            ax.axvspan(0.5, p.wall_layers + 0.5, color="#e07000", alpha=0.1)
            ax.axvspan(p.wall_layers + 0.5, p.wall_layers + p.transition_layers + 0.5, color="#d4b000", alpha=0.13)
            ax.axvspan(p.wall_layers + p.transition_layers + 0.5, p.nj - 0.5, color="#008000", alpha=0.08)
        if r.complete and p.law == "wall_core":
            nwall = r.diagnostics["wall_layers"]
            ax.axvspan(0.5, nwall + 0.5, color="#e07000", alpha=0.1)
            ax.axvspan(nwall + 0.5, p.nj - 0.5, color="#008000", alpha=0.08)
            ax.axvline(nwall + 0.5, color="#008000", linestyle="--", linewidth=1.0, label="Граница слоя и ядра")
        ax.set_xlabel("Номер ячейки от стенки")
        ax.set_ylabel(f"Размер, {self.cell_unit}")
        ax.grid(alpha=0.25)
        ax.legend()
        self.canvases[1].draw_idle()
        self.show_summary()

    def pick_save(self, title, default, extension):
        name, _ = QFileDialog.getSaveFileName(self, title, default, f"Файлы (*.{extension});;Все файлы (*)")
        if name and not os.path.splitext(name)[1]:
            name += "." + extension
            if os.path.exists(name):
                answer = QMessageBox.question(
                    self,
                    "Заменить файл?",
                    name,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return ""
        return name

    def export_mesh(self):
        if self.busy or self.result is None or self.stale or not self.result.complete:
            return
        name = self.pick_save("Сохранить сетку", "two_channels.xyz", "xyz")
        if name:
            result = self.result
            self.start_task(lambda: save_mesh(result, name), self.saved, "Запись сетки…")

    @Slot(object)
    def saved(self, name):
        self.statusBar().showMessage(f"Сохранено: {name}")

    def install_project_tracking(self):
        for field in self.fields.values():
            if isinstance(field, NumberField):
                field.edited.connect(self.mark_project_modified)
            elif isinstance(field, QSpinBox):
                field.valueChanged.connect(self.mark_project_modified)
        for control in (self.law, self.hyper_function, self.goal, self.mode, self.smoothing, self.project_target):
            control.currentIndexChanged.connect(self.mark_project_modified)
        self.full.toggled.connect(self.mark_project_modified)

    def mark_project_modified(self, *_):
        if self.updating or not self.project_tracking_ready:
            return
        self.project_modified = True
        self.update_project_title()

    def update_project_title(self):
        if self.project_path:
            name = os.path.basename(self.project_path)
        elif self.project_import_source:
            name = "Импорт: " + os.path.basename(self.project_import_source)
        else:
            name = "Новый проект"
        marker = " *" if self.project_modified else ""
        self.setWindowTitle(f"Генератор сетки — 0.6.6-quality — {name}{marker}")

    def set_project_clean(self, name):
        self.project_path = str(name)
        self.project_import_source = None
        self.project_modified = False
        self.update_project_title()

    def confirm_project_replacement(self, operation):
        if self.busy:
            return False
        if not self.project_modified:
            return True
        buttons = QMessageBox.StandardButton
        answer = QMessageBox.question(
            self,
            "Несохранённые изменения",
            f"В проекте есть несохранённые изменения. Сохранить их перед {operation}?",
            buttons.Save | buttons.Discard | buttons.Cancel,
            buttons.Cancel,
        )
        if answer == buttons.Save:
            return bool(self.save_project_file())
        if answer == buttons.Discard:
            return True
        return False

    def read_project(self):
        current = self.read_params()
        current.validate()
        params = merge_project_inputs(getattr(self, "project_base_params", None), current)
        if params.law == "wall_core":
            core = ProjectCore.from_runtime(self.read_core_params())
            target = self.project_target.currentData()
            if getattr(self, "project_core_missing", False) and target == "layer_only":
                core = None
        else:
            target = "full_distribution"
            base = getattr(self, "project_base_params", None)
            core = getattr(self, "project_loaded_core", None) if base is not None else None
        project = MeshProject(params, core, target, self.geometry_unit, self.cell_unit)
        project.validate()
        return project

    def save_project_file(self):
        if self.busy:
            return False
        try:
            project = self.read_project()
            default = self.project_path
            if not default and self.project_import_source:
                default = os.path.splitext(self.project_import_source)[0] + ".project.json"
            name = self.pick_save("Сохранить проект", default or "mesh_project.json", "json")
            if not name:
                return False
            write_project(project, name)
            self.set_project_clean(name)
            self.statusBar().showMessage(f"Проект сохранён: {name}. Это параметры, не готовая сетка.")
            return True
        except Exception as exc:
            QMessageBox.warning(self, "Проект", str(exc))
            return False

    def prepare_project(self, project):
        project.validate()
        p = project.params
        if p.law == "wall_core":
            integers = dict(ni=p.ni, nz=p.nz, layer_cells=p.wall_layers)
            numbers = dict(d_rod=p.d_rod, pitch=p.pitch, z_len=p.z_len, layer_thickness=p.layer_thickness)
            if p.mode == "layer_thickness":
                numbers["h1"] = p.h1
            else:
                numbers["layer_growth"] = p.layer_growth
        else:
            integers = dict(
                ni=p.ni,
                nz=p.nz,
                layers=p.nj - 1,
                wall_layers=p.wall_layers,
                transition_layers=p.transition_layers,
                max_transition_layers=p.max_transition_layers,
                max_auto_cells=p.max_auto_cells,
            )
            numbers = {key: getattr(p, key) for key in ("d_rod", "pitch", "z_len", "h1", "hmax", "smoothing_percent")}
            self.check_numbers(p)
            if p.wall_layers + p.transition_layers > 5000:
                raise ValueError("Количество ячеек превышает ограничения интерфейса")
        numbers.update(
            h1=p.h1,
            hmax=p.hmax,
            layer_growth=p.layer_growth,
            layer_thickness=p.layer_thickness,
            smoothing_percent=p.smoothing_percent,
        )
        core = project.core or ProjectCore()
        numbers.update(core_growth=core.growth, core_max_size=core.max_size)
        integers["core_max_cells"] = core.max_cells
        for key, value in integers.items():
            control = self.fields[key]
            if not control.minimum() <= value <= control.maximum():
                raise ValueError(f"{key}: значение вне диапазона интерфейса")
        for key, value in numbers.items():
            model = self.fields[key].model
            if not math.isfinite(value) or not model.minimum <= value <= model.maximum:
                raise ValueError(f"{key}: значение вне диапазона интерфейса")
        target = project.build_target if p.law == "wall_core" else "layer_and_core"
        index = self.project_target.findData(target)
        if index < 0:
            raise ValueError("Цель проекта не поддерживается интерфейсом")
        return core, index

    def apply_project(self, project):
        if self.busy:
            raise ValueError("Дождитесь завершения расчёта")
        core, index = self.prepare_project(project)
        snapshot = self.capture_state()
        target = self.project_target.currentIndex()
        metadata = {
            key: getattr(self, key, None)
            for key in ("project_base_params", "project_loaded_core", "project_core_missing", "project_path")
        }
        was_updating = self.updating
        self.updating = True
        try:
            self.apply_params(project.params, project.geometry_unit, project.cell_unit)
            for key in ("h1", "hmax", "layer_growth", "layer_thickness", "smoothing_percent"):
                field = self.fields[key]
                if key == "layer_thickness":
                    field.model.factor = UNITS[project.cell_unit]
                field.setValue(getattr(project.params, key))
            self.fields["core_growth"].setValue(core.growth)
            self.fields["core_max_size"].setValue(core.max_size)
            self.fields["core_max_cells"].setValue(core.max_cells)
            self.project_target.setCurrentIndex(index)
            self.project_base_params = project.params
            self.project_loaded_core = project.core
            self.project_core_missing = project.core is None
            self.project_path = None
        except Exception:
            self.restore_state(snapshot)
            QComboBox.setCurrentIndex(self.project_target, target)
            for key, value in metadata.items():
                setattr(self, key, value)
            raise
        finally:
            self.updating = was_updating
        self.workflow.invalidate_layer()
        self.update_actions()
        notes = []
        if self.result is not None:
            try:
                self.redraw()
            except Exception as exc:
                notes.append(
                    f"Параметры загружены, но предыдущий график не удалось обновить: {exc}. "
                    "Экспорт старого результата заблокирован."
                )
        if project.params.law == "wall_core" and project.core is None:
            notes.append(
                "Параметры ядра в файле отсутствуют. В полях показаны значения по умолчанию; "
                "ядро не задано, цель — только слой. Изменение параметров ядра сделает их явными."
            )
        return tuple(notes)

    def open_project_file(self):
        if self.busy:
            return
        name, _ = QFileDialog.getOpenFileName(self, "Открыть проект или старые настройки", "", "JSON (*.json)")
        if not name:
            return
        try:
            info = load_project_info(name)
            self.prepare_project(info.project)
        except Exception as exc:
            QMessageBox.warning(self, "Проект не открыт", str(exc))
            return
        if not self.confirm_project_replacement("открытием другого проекта"):
            return
        try:
            info = load_project_info(name)
            notes = info.notes + self.apply_project(info.project)
        except Exception as exc:
            QMessageBox.warning(self, "Проект не открыт", str(exc))
            return
        if info.source_format == FORMAT:
            self.set_project_clean(name)
        else:
            self.project_path = None
            self.project_import_source = name
            self.project_modified = True
            self.update_project_title()
        self.statusBar().showMessage(f"Проект открыт: {name}. Постройте сетку заново; расчёт автоматически не запускался.")
        if notes:
            QMessageBox.information(self, "Импорт проекта", "\n\n".join(notes))

    def check_quality(self):
        """Отдельная функция: метрики качества актуальной сетки; результат не изменяется."""
        if self.busy or self.result is None or self.stale:
            return
        result = self.result
        profile = getattr(self, "quality_profile", None) or DEFAULT_PROFILE
        self.start_task(
            lambda: (analyse_result(result, profile=profile), bool(result.complete), result),
            self.quality_ready,
            "Расчёт метрик качества…",
        )

    @Slot(object)
    def quality_ready(self, payload):
        report, complete, result = payload
        kind = "Полная сетка" if complete else "Только пристеночный слой (ядро не построено)"
        self.quality_report = report
        bad = report["invalid"]
        cells = f"{report['totals']['cells']:,}".replace(",", " ")
        if bad["non_positive_volume_cells"] or bad["non_positive_scaled_jacobian_cells"]:
            self.statusBar().showMessage("Метрики рассчитаны: найдены вывернутые или вырожденные ячейки!")
        else:
            self.statusBar().showMessage(f"Метрики рассчитаны: {cells} ячеек, вывернутых и вырожденных ячеек нет")
        profile = getattr(self, "quality_profile", None) or DEFAULT_PROFILE
        self.quality_dialog = QualityDialog(self, report, kind, profile=profile, result=result)
        self.quality_dialog.show()
        self.quality_dialog.raise_()
        self.quality_dialog.activateWindow()

    def save_quality_report(self, report):
        name = self.pick_save("Сохранить отчёт о метриках", "mesh_quality.json", "json")
        if not name:
            return False
        try:
            write_quality_report(report, name)
        except Exception as exc:
            QMessageBox.warning(self, "Отчёт", str(exc))
            return False
        self.statusBar().showMessage(f"Отчёт о метриках сохранён: {name}")
        return True

    def save_settings(self):
        if self.busy:
            return
        try:
            p = self.read_params()
            p.validate()
            name = self.pick_save("Сохранить настройки", "mesh_settings.json", "json")
            if name:
                resolved = self.result.params if self.result is not None and not self.stale else None
                save_configuration(p, self.geometry_unit, self.cell_unit, name, resolved)
                self.statusBar().showMessage(
                    f"Настройки сохранены: {name}"
                    + (". Параметры ядра в этот JSON не входят." if p.law == "wall_core" else "")
                )
        except Exception as exc:
            QMessageBox.warning(self, "Настройки", str(exc))

    def load_settings(self):
        if self.busy:
            return
        name, _ = QFileDialog.getOpenFileName(self, "Загрузить настройки", "", "JSON (*.json)")
        if not name:
            return
        try:
            parameters = load_configuration(name)
        except Exception as exc:
            QMessageBox.warning(self, "Настройки", str(exc))
            return
        if not self.confirm_project_replacement("загрузкой старых настроек"):
            return
        try:
            parameters = load_configuration(name)
            self.apply_params(*parameters)
            self.project_base_params = None
            self.project_loaded_core = None
            self.project_core_missing = False
            self.project_path = None
            self.project_import_source = name
            self.project_modified = True
            self.update_project_title()
        except Exception as exc:
            QMessageBox.warning(self, "Настройки", str(exc))

    def closeEvent(self, event):
        if self.busy:
            QMessageBox.information(self, "Операция выполняется", "Дождитесь завершения операции")
            event.ignore()
            return
        if self.confirm_project_replacement("закрытием окна"):
            event.accept()
        else:
            event.ignore()


def main():
    app = QApplication(sys.argv)
    window = MeshWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
