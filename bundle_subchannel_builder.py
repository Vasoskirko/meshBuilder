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

import json
import math
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure
from matplotlib.patches import Circle, Polygon
from PySide6.QtCore import Qt, QSignalBlocker
from PySide6.QtGui import QBrush, QColor, QAction, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import mesh_core as mc
import mesh_quality as mq
import mesh_subchannel as ms
from block_classifier import classify_subchannel_blocks
from bundle_geometry import BundleModel
from bundle_hydraulics_dialog import HydraulicsTableDialog
from bundle_styles import SCIENTIFIC_QSS
from mesh_advisor import format_friendly_error
from mesh_quality import DEFAULT_PROFILE
from mesh_quality_dialog import QualityDialog
from mesh_subchannel_subpanel import MeshSubpanel


from bundle_builder_ui import BundleBuilderUiMixin
from bundle_diagnostics_ui import BundleDiagnosticsMixin
from bundle_mesh_jobs import BundleMeshJobsMixin, analyse_subchannel_result


class BundleBuilderWindow(BundleMeshJobsMixin, BundleDiagnosticsMixin, BundleBuilderUiMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Конструктор сечения ТВС и генератор сетки подканалов (CFD)")
        self.resize(1440, 880)
        self.project_path=None
        self.star_export_options=None
        self.model = BundleModel(s_flat=65.0, pitch=12.75, d_fuel=9.1, d_guide=12.0, d_instrument=10.3)

        self._pan_start = None
        self._custom_limits = None
        self.current_mesh_result = None
        self.current_layer_result = None
        self.current_quality_report = None
        self._layer_inputs = None
        self._mesh_inputs = None
        self.base_params = mc.MeshParams(law="geometric", mode="first_count", h1=2.5e-6, nj=100)
        self.template_configs = {}
        self.block_custom_configs = {}
        self._mesh_variant_a=None
        self._mesh_diagnostic=None
        self._selected_diagnostic=None
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
        project_menu=self.menuBar().addMenu('Проект')
        for title,shortcut,callback in (
                ('Сохранить проект','Ctrl+S',lambda:self.on_save_json()),
                ('Сохранить проект как…','Ctrl+Shift+S',lambda:self.on_save_json(save_as=True)),
                ('Открыть проект…','Ctrl+O',self.on_load_json),
                ('Экспортировать только сечение JSON…',None,self.on_export_cross_section_json)):
            action=QAction(title,self)
            if shortcut:action.setShortcut(QKeySequence(shortcut))
            action.triggered.connect(callback);project_menu.addAction(action)
        self.on_rebuild_geometry(silent=True)
        for spin in self.geometry_controls():
            spin.valueChanged.connect(self.validate_mesh_inputs)

    def append_mesh_message(self, text):
        from datetime import datetime
        self.mesh_console.appendPlainText(f'[{datetime.now():%H:%M:%S}] {text}')

    def report_viscous_units(self):
        result=self.current_mesh_result
        if result is None:
            self.append_mesh_message('Нет актуальной сетки для оценки вязких размеров.')
            return
        ranges=result.diagnostics.get('edge_ranges_m')
        if ranges is None:
            self.append_mesh_message('Размеры рёбер ещё не измерены; выполните построение.')
            return
        from mesh_viscous_units import format_wall_units
        try:
            message=format_wall_units(ranges,getattr(self.mesh_subpanel,'last_yplus_result',None))
        except (ValueError,TypeError,KeyError) as exc:
            message=f'Вязкие размеры недоступны: {exc}. Откройте калькулятор y+ и выполните корректный расчёт.'
        state='Полная сетка' if result.complete else 'Только пристеночный слой (ядро не заполнено)'
        self.append_mesh_message(state+'\n'+message)

    def geometry_controls(self):
        return (self.s_flat_spin, self.pitch_spin, self.d_fuel_spin,
                self.d_guide_spin, self.d_inst_spin)

    def mesh_inputs(self):
        """Snapshot build inputs, excluding selection/highlight of the editor target."""
        panel = self.mesh_subpanel
        from bundle_local_core import wall_params,DEFAULTS
        layer = deepcopy((
            tuple(w.value() for w in self.geometry_controls()),
            (self.model.s_flat, self.model.pitch, self.model.d_fuel,
             self.model.d_guide, self.model.d_instrument),
            sorted((rid, r.x, r.y, r.diameter, r.rod_type)
                   for rid, r in self.model.rods.items()),
            set(self.model.selected_subchannels), wall_params(self.base_params),
            [(gid,wall_params(self.block_custom_configs.get(gid,self.template_configs.get(inst.template_id,self.base_params)))) for gid,inst in sorted(self.instances_lookup.items())],
            panel.combo_center_method.currentData(),
            panel.combo_mesh_lines.currentData() if any(p.law != "wall_core" for p in [self.base_params,*self.template_configs.values(),*self.block_custom_configs.values()]) else False,
        ))
        from bundle_block_editor import core_state,pending_mixed_fields,CORE_WIDGETS
        if not any(p.law=='wall_core' for p in [self.base_params,*self.template_configs.values(),*self.block_custom_configs.values()]):return layer,None
        try:
            visible=core_state(panel) if panel.current_law()=='wall_core' else None
        except ValueError:
            return layer,('invalid_core_draft',)
        data=visible if panel.scope_mode=='all' and visible is not None else getattr(panel,'_global_core_state',visible)
        if data is None:data=core_state(panel)
        def active_core(d):
            keys=('local_core_mode','local_core_transition','local_core_layers','local_core_hermite') if d['local_core_mode']=='fixed_count' else ('local_core_mode','local_core_transition','local_core_growth','local_core_size','local_core_limit')
            return {k:d[k] for k in keys}
        core=(active_core(data),[{k:active_core({n:getattr(v,n) for n in DEFAULTS}) for k,v in mapping.items() if v.local_core_mode!='inherit'} for mapping in (self.template_configs,self.block_custom_configs)]) if any(p.law=='wall_core' for p in [self.base_params,*self.template_configs.values(),*self.block_custom_configs.values()]) else None
        if core is not None and panel.scope_mode!='all' and visible is not None and (active_core(visible)!=active_core(getattr(panel,'_display_core',visible)) or pending_mixed_fields(panel).intersection(CORE_WIDGETS[k] for k in active_core(visible) if k in CORE_WIDGETS)):
            core=(core,'pending_local_core',active_core(visible))
        return layer, core

    def validate_mesh_inputs(self, *args):
        if self._layer_inputs is None and self._mesh_inputs is None:
            return
        try:
            # Commit visible wall drafts before direct export/fill checks too.
            self.mesh_subpanel.save_current_ui_to_active_scope()
            layer, core = self.mesh_inputs()
        except ValueError:
            layer, core = None, None
        if self._layer_inputs is not None and layer != self._layer_inputs:
            self.current_layer_result = None
            self._layer_inputs = None
        if self._mesh_inputs is not None and (layer, core) != self._mesh_inputs:
            self.current_mesh_result = None
            self.clear_mesh_diagnostics()
            self.current_quality_report = None
            self._mesh_inputs = None
            panel = self.mesh_subpanel
            panel.btn_export.setEnabled(False)
            panel.btn_export_star.setEnabled(False)
            panel.btn_quality.setEnabled(False)
            panel.lbl_status.setText("Параметры изменены. Перестройте сетку или заполните актуальный слой.")
            self.append_mesh_message("Сетка устарела: параметры изменены. Предыдущие размеры в журнале относятся к прежнему построению; экспорт заблокирован.")
        self.mesh_subpanel.btn_fill_core.setEnabled(self.current_layer_result is not None)

    def accept_mesh_inputs(self, result, *, filled=False):
        layer, core = self.mesh_inputs()
        if not filled:
            self.current_layer_result = result if not result.complete else None
            self._layer_inputs = layer if not result.complete else None
        self._mesh_inputs = (layer, core)

    def can_export_mesh(self):
        self.validate_mesh_inputs()
        return (self._mesh_inputs is not None and self.current_mesh_result is not None
                and self.current_mesh_result.complete)

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

        # 5. Клик по пустому пространству -> снимает выбор со стержня
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
            msg.setText(
                f"Стержень перекрывает {len(clashes)} соседних ТВЭЛ(ов).\n"
                "Удалить пересекающиеся ТВЭЛы автоматически?"
            )
            btn_yes = msg.addButton("Да, удалить автоматически", QMessageBox.YesRole)
            msg.addButton("Нет, оставить (удалю вручную)", QMessageBox.NoRole)
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
            msg.setText(
                f"Заданный диаметр {new_val:.2f} мм перекрывает {len(clashes)} соседних ТВЭЛ(ов).\n"
                "Удалить пересекающиеся ТВЭЛы автоматически?"
            )
            btn_yes = msg.addButton("Да, удалить автоматически", QMessageBox.YesRole)
            msg.addButton("Нет, оставить (удалю вручную)", QMessageBox.NoRole)
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
                type_names = {
                    "fuel": "Обычный ТВЭЛ",
                    "guide": "Направляющий Канал (НК)",
                    "instrument": "Инструментальный Канал (ИК)",
                }
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

                has_deleted = (
                    len(self.model.user_deleted_coords) > 0
                    or len(self.model.auto_deleted_clash_coords) > 0
                )
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
                "corner": "Угловой (грань проходит в вершину угла)",
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
        self.validate_mesh_inputs()
        if self._custom_limits is None and hasattr(self, "ax"):
            r_base = (self.model.s_flat / 2.0) / math.cos(math.radians(30)) * 1.08
            self._custom_limits = (-r_base, r_base, -r_base, r_base)

        self.ax.clear()

        hex_poly = Polygon(
            self.model.hex_vertices,
            closed=True,
            fill=False,
            edgecolor="#2c3e50",
            linewidth=2.5,
            zorder=2,
        )
        self.ax.add_patch(hex_poly)

        for i in range(6):
            mid = (self.model.hex_vertices[i] + self.model.hex_vertices[(i + 1) % 6]) / 2.0
            self.ax.text(
                mid[0] * 1.07,
                mid[1] * 1.07,
                f"S{i + 1}",
                ha="center",
                va="center",
                color="#2c3e50",
                fontsize=9,
                fontweight="bold",
            )

        color_map = {
            "interior": "#2ecc71",
            "guide_sub": "#f39c12",
            "instrument_sub": "#1abc9c",
            "peripheral": "#3498db",
            "corner": "#9b59b6",
        }
        edge_map = {
            "interior": "#27ae60",
            "guide_sub": "#d35400",
            "instrument_sub": "#16a085",
            "peripheral": "#2980b9",
            "corner": "#8e44ad",
        }

        bbox_style = dict(boxstyle="round,pad=0.25", facecolor="#ffffff", alpha=0.88, edgecolor="none")

        for sub_id in self.model.selected_subchannels:
            sub = self.model.subchannels[sub_id]
            c = color_map.get(sub.sub_type, "#2ecc71")
            ec = edge_map.get(sub.sub_type, "#27ae60")

            poly = Polygon(
                sub.polygon_points,
                closed=True,
                facecolor=c,
                edgecolor=ec,
                alpha=0.45,
                linewidth=1.5,
                zorder=3,
            )
            self.ax.add_patch(poly)
            self.ax.text(
                sub.fluid_center[0],
                sub.fluid_center[1],
                "−",
                ha="center",
                va="center",
                color="#900C3F",
                fontsize=15,
                fontweight="bold",
                bbox=bbox_style,
                zorder=6,
            )

        candidates = self.model.get_candidate_neighbors()
        for sub_id in candidates:
            sub = self.model.subchannels[sub_id]
            poly = Polygon(
                sub.polygon_points,
                closed=True,
                facecolor="#f1c40f",
                edgecolor="#f39c12",
                alpha=0.25,
                linewidth=1.2,
                linestyle="--",
                zorder=3,
            )
            self.ax.add_patch(poly)
            self.ax.text(
                sub.fluid_center[0],
                sub.fluid_center[1],
                "+",
                ha="center",
                va="center",
                color="#d35400",
                fontsize=14,
                fontweight="bold",
                bbox=bbox_style,
                zorder=6,
            )

        if not self.model.selected_subchannels:
            for sub in self.model.subchannels.values():
                poly = Polygon(
                    sub.polygon_points,
                    closed=True,
                    facecolor="#f8f9fa",
                    edgecolor="#bdc3c7",
                    alpha=0.3,
                    linewidth=0.7,
                    linestyle="-.",
                    zorder=1,
                )
                self.ax.add_patch(poly)
                lbl = {
                    "interior": "Регул.",
                    "guide_sub": "НК",
                    "instrument_sub": "ИК",
                    "peripheral": "Периф",
                    "corner": "Углов.",
                }.get(sub.sub_type, "+")
                self.ax.text(
                    sub.fluid_center[0],
                    sub.fluid_center[1],
                    lbl,
                    ha="center",
                    va="center",
                    color="#5d6d7e",
                    fontsize=7.5,
                    fontweight="bold",
                    bbox=bbox_style,
                    zorder=6,
                )

        active_id = self.model.active_rod_id
        for r_id, rod in self.model.rods.items():
            is_active = r_id == active_id

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

            circle = Circle(
                (rod.x, rod.y),
                rod.diameter / 2.0,
                facecolor=facecolor,
                edgecolor=edgecolor,
                linewidth=2.4 if is_active else (2.0 if rod.is_clashing else 1.5),
                linestyle="--" if rod.is_clashing else "-",
                zorder=5,
            )
            self.ax.add_patch(circle)

            label = f"R{rod.rod_id}" + badge
            self.ax.text(
                rod.x,
                rod.y,
                label,
                ha="center",
                va="center",
                color="#1a252f",
                fontsize=7.5 if badge else 8,
                fontweight="bold",
                zorder=7,
            )

        all_summary = self.model.get_total_assembly_summary()
        all_text = ""
        if all_summary:
            all_text = (
                f"<br><b>Гидравлика ВСЕЙ сборки ТВС ({all_summary['total_subchannels']} подканалов):</b><br>"
                f"&bull; <b>Полная площадь A:</b> {all_summary['total_a_fluid_mm2']:.2f} мм²<br>"
                f"&bull; <b>Полный периметр P:</b> {all_summary['total_p_wet_mm']:.2f} мм<br>"
                f"&bull; <b>D_h всей ТВС:</b> <b>{all_summary['total_d_h_mm']:.2f} мм</b>"
            )

        num_selected = len(self.model.selected_subchannels)
        num_rods = len(
            {rid for sid in self.model.selected_subchannels for rid in self.model.subchannels[sid].rod_ids}
        )

        sel_summary = self.model.get_selection_summary()
        if sel_summary:
            tot_a = sel_summary["total_a_fluid_mm2"]
            tot_p = sel_summary["total_p_wet_mm"]
            tot_dh = sel_summary["total_d_h_mm"]
            sel_text = (
                f"<hr><b>Гидравлика ВЫБРАННОЙ области ({num_selected} подканалов, {num_rods} стержней):</b><br>"
                f"&bull; <b>Площадь A:</b> {tot_a:.2f} мм²<br>"
                f"&bull; <b>Периметр P:</b> {tot_p:.2f} мм<br>"
                f"&bull; <b>D_h эквив.:</b> <b>{tot_dh:.2f} мм</b>"
            )
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

    def on_export_cross_section_json(self):
        name, _ = QFileDialog.getSaveFileName(self, "Сохранить конфигурацию сечения", "bundle_selection.json", "JSON (*.json)")
        if name:
            data = self.model.export_dict()
            Path(name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            QMessageBox.information(self, "Успех", f"Конфигурация сечения сохранена в:\n{name}")

    def _project_busy(self):
        if getattr(self,'_mesh_thread',None) is not None or getattr(self,'_export_job',None) is not None:
            QMessageBox.warning(self,'Проект занят','Дождитесь завершения построения/экспорта или отмените операцию.')
            return True
        return False

    def on_save_json(self, save_as=False):
        if self._project_busy():return
        from bundle_project import capture_project,save_project
        try:project=capture_project(self)
        except Exception as exc:
            QMessageBox.warning(self,'Не удалось сохранить проект',str(exc));return
        path=getattr(self,'project_path',None)
        if save_as or path is None:
            path,_=QFileDialog.getSaveFileName(self,'Сохранить полный проект конструктора',str(path or 'bundle_project.json'),'Проект meshBuilder (*.json)')
        if not path:return
        try:
            save_project(project,path)
            self.project_path=Path(path)
            self.setWindowTitle(f'meshBuilder — {self.project_path.name}')
            self.append_mesh_message(f'Проект сохранён: {path}')
        except Exception as exc:
            QMessageBox.critical(self,'Не удалось сохранить проект',str(exc))

    def on_load_json(self):
        if self._project_busy():return
        path,_=QFileDialog.getOpenFileName(self,'Открыть проект или старый JSON сечения','','JSON (*.json)')
        if not path:return
        try:
            from bundle_project import load_project
            project=load_project(path)  # All schema/geometry checks precede GUI mutation.
            self.apply_bundle_project(project)
            self.project_path=None if project.legacy else Path(path)
            self.setWindowTitle(f'meshBuilder — {Path(path).name}')
            self.append_mesh_message(f'Открыт проект: {path}. Для экспорта перестройте сетку.')
            if project.legacy:self.append_mesh_message('Импортирован старый JSON сечения: параметры сетки и экспорта в нём отсутствуют; установлены значения по умолчанию.')
        except Exception as exc:
            QMessageBox.warning(self,'Не удалось открыть проект',str(exc))

    def apply_bundle_project(self, project):
        from bundle_project import validate_project,BundleProjectError
        from yplus_dialog import YPlusDialog
        if getattr(self,'_mesh_thread',None) is not None or getattr(self,'_export_job',None) is not None:
            raise BundleProjectError('Дождитесь завершения фоновой операции')
        # Validate again for programmatic callers; corrupt files cannot partially apply.
        project=validate_project(project.data)
        p=self.mesh_subpanel;core=project.data['mesh']['core'];view=project.data['view']
        widgets=[*self.geometry_controls(),*p.fields.values(),p.radio_all,p.radio_template,p.radio_block,p.combo_templates,p.combo_blocks,p.combo_core_mode,p.combo_mesh_lines,p.combo_core_lines,p.combo_center_method,p.cu,self.combo_detail]
        blockers=[QSignalBlocker(widget) for widget in widgets]
        p.updating=True
        try:
            self.model=project.model;self.base_params=project.base
            self.template_configs=project.templates;self.block_custom_configs=project.blocks
            self.current_mesh_result=None;self.current_layer_result=None;self.current_quality_report=None
            self.clear_mesh_diagnostics()
            self.clear_mesh_variant()
            self._layer_inputs=None;self._mesh_inputs=None;self._mesh_drawn=False
            self.highlighted_block_id=None;self.active_plot_block_idx=0
            for widget,value in zip(self.geometry_controls(),view['geometry_inputs']):widget.setValue(value)
            # Reset even inactive numeric drafts before changing display units.
            for key,value in dict(z_len=project.base.z_len,ni=project.base.ni,nz=project.base.nz,
                    layers=project.base.nj-1,h1=project.base.h1,hmax=project.base.hmax,
                    layer_cells=project.base.wall_layers,layer_thickness=project.base.layer_thickness,
                    layer_growth=project.base.layer_growth,growth_limit=project.base.shape if (project.base.law,project.base.mode)==('geometric','first_growth') else 1.02).items():p.fields[key].setValue(value)
            p.apply_params(project.base)
            p.updating=False;p.change_cell_unit(core['unit']);p.cu.setCurrentText(core['unit']);p.updating=True
            for key in ('core_transition','core_growth','core_max_size','core_max_cells','core_layers'):p.fields[key].setValue(core[key])
            p.combo_center_method.setCurrentIndex(p.combo_center_method.findData(core['center']))
            p.combo_mesh_lines.setCurrentIndex(p.combo_mesh_lines.findData(core['mesh_lines']))
            p.combo_core_mode.setCurrentIndex(p.combo_core_mode.findData(core['mode']))
            p._fixed_core_line_index=int(core['core_lines']);p._last_core_line_mode=None
            p.combo_core_lines.setCurrentIndex(p.combo_core_lines.findData(core['core_lines']))
            from bundle_block_editor import core_state
            p._global_core_state=core_state(p)
            templates,instances=classify_subchannel_blocks(self.model,selected_sub_ids=sorted(self.model.selected_subchannels))
            self.instances_lookup={i.global_block_id:i for i in instances}
            p.populate_scope_and_tree(templates,instances)
            p.combo_templates.setCurrentIndex(p.combo_templates.findData(view['template']))
            p.combo_blocks.setCurrentIndex(p.combo_blocks.findData(view['block']))
            p.scope_mode=view['scope'];getattr(p,'radio_'+p.scope_mode).setChecked(True)
            p.load_active_scope_to_ui()
            p.yplus_saved_state=deepcopy(project.data['calculator'])
            self.star_export_options=deepcopy(project.data['export'])
            self.combo_detail.setCurrentIndex(self.combo_detail.findData(view['detail']))
        finally:
            p.updating=False
            del blockers
        p.refresh_controls()
        for button in (p.btn_export,p.btn_export_star,p.btn_quality,p.btn_fill_core):button.setEnabled(False)
        self.clear_ruler();self.ax_mesh.clear();self.canvas_mesh.draw_idle()
        self.ax_layers.clear();self.canvas_layers.draw_idle();self.table_blocks.setRowCount(0)
        self._custom_limits=None;self.update_inspector();self.on_fit_view();self.rebuild_view()
        self.tabs.setCurrentIndex(view['tab'])
        self.left_stack.setCurrentIndex(1 if view['tab']>0 and self.model.selected_subchannels else 0)
        p.current_fluid_props={};p.last_yplus_result={}
        if p.yplus_saved_state:
            # Recompute reference quantities from inputs, never trust serialized results.
            summary=self.model.get_selection_summary() if self.model.selected_subchannels else self.model.get_total_assembly_summary()
            dialog=YPlusDialog(p,d_hyd_mm=summary.get('total_d_h_mm',summary.get('total_dh_mm',14.0)),a_fluid_mm2=summary.get('total_a_fluid_mm2',100.0),state_dict=deepcopy(p.yplus_saved_state))
            if getattr(dialog,'last_yplus_result',None):
                p.current_fluid_props=deepcopy(getattr(dialog,'current_fluid_props',{}) or {})
                p.last_yplus_result=deepcopy(dialog.last_yplus_result)
            dialog.close();dialog.deleteLater()
        if view['geometry_inputs']!=[self.model.s_flat,self.model.pitch,self.model.d_fuel,self.model.d_guide,self.model.d_instrument]:
            self.append_mesh_message('В проекте есть неприменённые параметры геометрии. Для их применения используйте кнопку перестроения пучка; она сбрасывает ручные правки стержней.')
        self.append_mesh_message('Параметры проекта восстановлены. Построенная сетка и результаты проверки не загружаются; требуется построение.')


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
        if not self.model.selected_subchannels:
            return
        try:
            self.mesh_subpanel.save_current_ui_to_active_scope()
        except ValueError as exc:
            self.validate_mesh_inputs()
            QMessageBox.warning(self, "Проверьте ввод", str(exc))
            return
        self.mesh_subpanel.update_tree_status()
        base_p = self.base_params

        try:
            cm_method = (
                self.mesh_subpanel.combo_center_method.currentData()
                if hasattr(self.mesh_subpanel, "combo_center_method")
                else "equi_clearance"
            )
            model_snapshot=deepcopy(self.model)
            template_snapshot=deepcopy(self.template_configs)
            block_snapshot=deepcopy(self.block_custom_configs)
            hermite_snapshot=bool(self.mesh_subpanel.combo_mesh_lines.currentData())
            def compute(progress):
                progress(5,"Расчёт геометрии и координат сетки")
                res = ms.build_mesh_from_bundle_model(
                    model_snapshot,
                    base_params=base_p,
                    template_overrides=template_snapshot,
                    block_custom_overrides=block_snapshot,
                    auto_fill_core=False,
                    center_method=cm_method,
                    hermite_tfi=hermite_snapshot,
                    progress_callback=lambda fraction,text:progress(5+int(48*fraction),text),
                    allow_nonconformal=True,
                )
                rep = analyse_subchannel_result(res,progress)
                progress(92,"Расчёт завершён")

                return res,rep
            def completed(payload):
                res,rep=payload
                if not self.confirm_interface_problems(res):return
                self.clear_mesh_diagnostics()
                self.current_mesh_result = res
                self.accept_mesh_inputs(res)
                self.current_quality_report = rep
                self.mesh_subpanel.btn_quality.setEnabled(True)
                self.mesh_subpanel.btn_export.setEnabled(False)
                self.mesh_subpanel.btn_export_star.setEnabled(False)
                self.mesh_subpanel.btn_fill_core.setEnabled(self.current_layer_result is not None)

                d = res.diagnostics
                skipped = d.get("skipped_peripheral", 0)
                skip_txt = f" (пропущено пристеночных: {skipped})" if skipped else ""
                txt = (
                    f"Построен пристеночный слой: {d['blocks']} блоков.\n"
                    f"Ядро не заполнено. Настройте блок «5. Заполнение ядра» и нажмите «Заполнить ядро сетки».{skip_txt}"
                )
                self.mesh_subpanel.lbl_status.setText(txt)
                self.append_mesh_message(txt)
                self.report_viscous_units()
                self.mesh_subpanel.update_core_preview()
                self.redraw_mesh_views()
                self.populate_blocks_table()
            self._run_mesh_task("Построение пристеночного слоя",compute,completed,"Ошибка построения слоя")
        except Exception as exc:
            user_msg = format_friendly_error(exc)
            self.append_mesh_message("Ошибка построения слоя: "+user_msg)
            QMessageBox.critical(self, "Ошибка построения слоя", user_msg)

    def on_build_multiblock_mesh(self):
        if not self.model.selected_subchannels:
            return
        try:
            from bundle_project import commit_active_inputs
            commit_active_inputs(self)
        except ValueError as exc:
            self.validate_mesh_inputs()
            QMessageBox.warning(self, "Проверьте ввод", str(exc))
            return
        self.mesh_subpanel.update_tree_status()
        base_p = self.base_params
        is_layer_mode = any(p.law == "wall_core" for p in [base_p,*self.template_configs.values(),*self.block_custom_configs.values()])

        try:
            cm_method = (
                self.mesh_subpanel.combo_center_method.currentData()
                if hasattr(self.mesh_subpanel, "combo_center_method")
                else "equi_clearance"
            )
            model_snapshot=deepcopy(self.model)
            template_snapshot=deepcopy(self.template_configs)
            block_snapshot=deepcopy(self.block_custom_configs)
            hermite_snapshot=bool(self.mesh_subpanel.combo_mesh_lines.currentData())
            from bundle_block_editor import core_build_options
            core_options=core_build_options(self.mesh_subpanel) if is_layer_mode else None
            def compute(progress):
                progress(5,"Расчёт геометрии и координат сетки")
                res = ms.build_mesh_from_bundle_model(
                    model_snapshot,
                    base_params=base_p,
                    template_overrides=template_snapshot,
                    block_custom_overrides=block_snapshot,
                    auto_fill_core=False if is_layer_mode else True,
                    center_method=cm_method,
                    hermite_tfi=hermite_snapshot,
                    progress_callback=lambda fraction,text:progress(5+int(25*fraction),text),
                    allow_nonconformal=True,
                )
                layer_res=res if not res.complete else None
                if layer_res is not None:
                    from bundle_core_groups import fill_with_overrides
                    progress(30,'Заполнение ядра полной сетки')
                    res=fill_with_overrides(layer_res,model_snapshot,base_p,template_snapshot,block_snapshot,
                        core_options,lambda fraction,text:progress(30+int(23*fraction),text))
                rep = analyse_subchannel_result(res,progress)
                progress(92,"Расчёт завершён")

                return res,rep,layer_res
            def completed(payload):
                res,rep,layer_res=payload
                if not self.confirm_interface_problems(res):return
                self.clear_mesh_diagnostics()
                self.current_mesh_result = res
                self.accept_mesh_inputs(res)
                if layer_res is not None:
                    self.current_layer_result=layer_res
                    self._layer_inputs=self.mesh_inputs()[0]
                self.current_quality_report = rep
                self.mesh_subpanel.btn_quality.setEnabled(True)
                self.mesh_subpanel.btn_export.setEnabled(res.complete and not any(i['kind']=='geometry_mismatch' for i in res.diagnostics.get('interface_problems',[])))
                self.mesh_subpanel.btn_export_star.setEnabled(res.complete and not res.diagnostics.get('interface_problems'))
                self.mesh_subpanel.btn_fill_core.setEnabled(self.current_layer_result is not None)

                d = res.diagnostics
                skipped = d.get("skipped_peripheral", 0)
                skip_txt = f" (пропущено пристеночных: {skipped})" if skipped else ""
                txt = (
                    f"Сетка построена: {d['blocks']} блоков, {d['cells_3d']:,} ячеек (3D).\n"
                    f"Интерфейсов: {d.get('matched_interfaces', 0)}, Min Jacobian: {rep['metrics']['scaled_jacobian']['min']:.3f}.{skip_txt}"
                )
                self.mesh_subpanel.lbl_status.setText(txt)
                self.append_mesh_message(txt)
                self.report_viscous_units()
                self.redraw_mesh_views()
                self.populate_blocks_table()
            self._run_mesh_task("Построение сетки",compute,completed,"Ошибка построения сетки")
        except Exception as exc:
            user_msg = format_friendly_error(exc)
            self.append_mesh_message("Ошибка построения сетки: "+user_msg)
            QMessageBox.critical(self, "Ошибка построения сетки", user_msg)

    def on_fill_core_clicked(self):
        self.validate_mesh_inputs()
        layer_src = self.current_layer_result
        if layer_src is None:
            return
        try:
            from bundle_project import commit_active_inputs
            commit_active_inputs(self)
            if self.current_layer_result is not layer_src:raise ValueError('Параметры слоя изменены; перестройте пристеночный слой перед заполнением ядра')
            model_snapshot=deepcopy(self.model)
            template_snapshot=deepcopy(self.template_configs)
            block_snapshot=deepcopy(self.block_custom_configs)
            base_snapshot=self.base_params
            from bundle_block_editor import core_build_options
            core_options=core_build_options(self.mesh_subpanel)
            def compute(progress):
                from bundle_core_groups import fill_with_overrides
                progress(5,"Расчёт геометрии и координат сетки")
                full_res=fill_with_overrides(layer_src,model_snapshot,base_snapshot,template_snapshot,
                    block_snapshot,core_options,lambda fraction,text:progress(15+int(35*fraction),text))
                rep = analyse_subchannel_result(full_res,progress)
                progress(92,"Расчёт завершён")

                return full_res,rep
            def completed(payload):
                full_res,rep=payload
                if not self.confirm_interface_problems(full_res):return
                self.clear_mesh_diagnostics()
                self.current_mesh_result = full_res
                self.accept_mesh_inputs(full_res, filled=True)
                self.mesh_subpanel.btn_quality.setEnabled(True)
                self.current_quality_report = rep
                self.mesh_subpanel.btn_fill_core.setEnabled(True)
                self.mesh_subpanel.btn_export.setEnabled(not any(i['kind']=='geometry_mismatch' for i in full_res.diagnostics.get('interface_problems',[])))
                self.mesh_subpanel.btn_export_star.setEnabled(not full_res.diagnostics.get('interface_problems'))

                d = full_res.diagnostics
                extra = ""
                if d.get("core_target_exceeded"):
                    extra = (
                        f"\n⚠ Узкий зазор ограничил число слоёв: в центре ячейки крупнее целевого "
                        f"({d.get('core_target_m', 0) * 1e6:.0f} мкм) — до {d.get('core_plateau_max_m', 0) * 1e6:.0f} мкм."
                    )
                self.mesh_subpanel.lbl_status.setText(
                    f"Ядро заполнено: {d['blocks']} блоков, {d['cells_3d']:,} ячеек (3D). "
                    f"Слоёв ядра: {d.get('core_layers_count', '?')}; ячейка на конце ядра: "
                    f"зазор ≈ {d.get('core_plateau_min_m', 0) * 1e6:.0f} … центр ≈ {d.get('core_plateau_max_m', 0) * 1e6:.0f} мкм.\n"
                    f"Min Jacobian: {rep['metrics']['scaled_jacobian']['min']:.3f}.{extra}\n"
                    f"Можно менять параметры Блока 5 и нажимать «Заполнить ядро сетки» повторно — призма не пересоздаётся."
                )
                if d.get('core_alignment'):
                    a=d['core_alignment']
                    self.mesh_subpanel.lbl_status.setText(self.mesh_subpanel.lbl_status.text()+f"\nВыравнивание ядра: отношение сторон ≥1, идеально 1; медиана {a['median']:.2f}, 95-й процентиль {a['p95']:.2f}, максимум {a['maximum']:.2f}. Доля ≤1.5: {a['fraction_under_1_5']:.0%} (внешняя половина ядра).")
                self.append_mesh_message(self.mesh_subpanel.lbl_status.text())
                self.report_viscous_units()
                self.mesh_subpanel.update_core_preview()
                self.redraw_mesh_views()
                self.populate_blocks_table()
                QMessageBox.information(
                    self,
                    "Ядро заполнено",
                    f"Сетка успешно заполнена до центра подканалов! Всего ячеек: {d['cells_3d']:,}",
                )
            self._run_mesh_task("Заполнение ядра",compute,completed,"Не удалось заполнить ядро")
        except Exception as exc:
            user_msg = format_friendly_error(exc)
            self.append_mesh_message("Не удалось заполнить ядро: "+user_msg)
            QMessageBox.critical(self, "Не удалось заполнить ядро", user_msg)

    def populate_blocks_table(self):
        if self.current_mesh_result is None:
            return
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
                if m.growth_q <= 1.20:
                    it_param.setBackground(QBrush(QColor("#e8f5e9")))
                elif m.growth_q <= 1.35:
                    it_param.setBackground(QBrush(QColor("#fffde7")))
                else:
                    it_param.setBackground(QBrush(QColor("#ffebee")))
            elif "tanh" in m.law or "sinh" in m.law:
                if m.growth_q <= 3.5:
                    it_param.setBackground(QBrush(QColor("#e8f5e9")))
                else:
                    it_param.setBackground(QBrush(QColor("#fffde7")))
            elif m.law == "power":
                if m.growth_q <= 2.2:
                    it_param.setBackground(QBrush(QColor("#e8f5e9")))
                else:
                    it_param.setBackground(QBrush(QColor("#fffde7")))

            self.table_blocks.setItem(row_idx, 7, it_param)
            self.table_blocks.setItem(row_idx, 8, QTableWidgetItem(f"{m.h_last_um:.1f}"))

            it_ar = QTableWidgetItem(f"{m.aspect_ratio_wall:.1f}")
            if m.aspect_ratio_wall > 200.0:
                it_ar.setBackground(QBrush(QColor("#fffde7")))
            self.table_blocks.setItem(row_idx, 9, it_ar)

    def on_table_block_selected(self):
        items = self.table_blocks.selectedItems()
        if not items:
            return
        row = self.table_blocks.currentRow()
        gid_item = self.table_blocks.item(row, 0)
        if gid_item:
            gid = gid_item.data(Qt.UserRole)
            if gid is not None:
                self.highlight_mesh_block(gid)
                self.active_plot_block_idx = max(0, gid - 1)
                self.redraw_layer_plot_for_block(self.active_plot_block_idx)

    def redraw_layer_plot_for_block(self, block_idx):
        if self.current_mesh_result is None:
            return
        res = self.current_mesh_result
        all_w = getattr(res, "all_block_widths", [])
        widths_m = all_w[block_idx] if (all_w and block_idx < len(all_w)) else res.layer_widths
        if widths_m is None:
            return

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
            self.ax_layers.plot(nodes_idx, widths_um[mid_idx], "g.-", label=f"Сечение {mid_idx + 1}")
            self.ax_layers.plot(nodes_idx, widths_um[-1], "r.-", label="Сечение N (к зазору M)")

        self.ax_layers.set_xlabel("Номер ячейки по нормали (j)")
        self.ax_layers.set_ylabel("Толщина ячейки (мкм)")
        self.ax_layers.set_title(f"Распределение толщин ячеек по нормали: {b_info}")
        self.ax_layers.grid(True, alpha=0.3)
        self.ax_layers.legend(fontsize=9)
        self.canvas_layers.draw_idle()

    def on_mesh_scroll(self, event):
        if event.inaxes != self.ax_mesh or event.xdata is None or event.ydata is None:
            return
        base_scale = 1.2
        scale = 1.0 / base_scale if event.button == "up" else base_scale
        cur_xlim = self.ax_mesh.get_xlim()
        cur_ylim = self.ax_mesh.get_ylim()
        xdata, ydata = event.xdata, event.ydata
        w_old = cur_xlim[1] - cur_xlim[0]
        h_old = cur_ylim[1] - cur_ylim[0]
        w_new = w_old * scale
        h_new = h_old * scale
        rel_x = (cur_xlim[1] - xdata) / w_old
        rel_y = (cur_ylim[1] - ydata) / h_old
        self.ax_mesh.set_xlim(xdata - w_new * (1.0 - rel_x), xdata + w_new * rel_x)
        self.ax_mesh.set_ylim(ydata - h_new * (1.0 - rel_y), ydata + h_new * rel_y)
        self.canvas_mesh.draw_idle()

    def on_toggle_ruler(self, checked):
        self.ruler_active = checked
        if not checked:
            self.clear_ruler()

    def clear_ruler(self):
        self.ruler_p1 = None
        if self.ruler_line is not None:
            try:
                self.ruler_line.remove()
            except Exception:
                pass
            self.ruler_line = None
        if self.ruler_text is not None:
            try:
                self.ruler_text.remove()
            except Exception:
                pass
            self.ruler_text = None
        self.canvas_mesh.draw_idle()

    def on_ruler_click(self, event):
        if (
            not self.ruler_active
            or event.inaxes != self.ax_mesh
            or event.button != 1
            or event.xdata is None
            or event.ydata is None
        ):
            return
        x, y = event.xdata, event.ydata
        if self.ruler_p1 is None:
            self.ruler_p1 = (x, y)
        else:
            p1, p2 = self.ruler_p1, (x, y)
            dist_mm = float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))
            badge = f"ΔL = {dist_mm * 1e3:.3f} мкм ({dist_mm:.4f} мм)"

            if self.ruler_line is not None:
                self.ruler_line.set_data([p1[0], p2[0]], [p1[1], p2[1]])
            else:
                (self.ruler_line,) = self.ax_mesh.plot(
                    [p1[0], p2[0]], [p1[1], p2[1]], "r-o", linewidth=1.5, markersize=4, zorder=10
                )

            mid_x, mid_y = (p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0
            if self.ruler_text is not None:
                self.ruler_text.set_position((mid_x, mid_y))
                self.ruler_text.set_text(badge)
            else:
                self.ruler_text = self.ax_mesh.text(
                    mid_x,
                    mid_y,
                    badge,
                    color="red",
                    fontsize=8.5,
                    fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.25", facecolor="#fff9c4", edgecolor="red", linewidth=1.0),
                    zorder=11,
                )
            self.canvas_mesh.draw_idle()
            self.ruler_p1 = None

    def on_ruler_motion(self, event):
        if (
            not self.ruler_active
            or self.ruler_p1 is None
            or event.inaxes != self.ax_mesh
            or event.xdata is None
            or event.ydata is None
        ):
            return
        p1, p2 = self.ruler_p1, (event.xdata, event.ydata)
        dist_mm = float(np.hypot(p2[0] - p1[0], p2[1] - p1[1]))
        badge = f"{dist_mm * 1e3:.1f} мкм"
        if self.ruler_line is not None:
            self.ruler_line.set_data([p1[0], p2[0]], [p1[1], p2[1]])
        else:
            (self.ruler_line,) = self.ax_mesh.plot([p1[0], p2[0]], [p1[1], p2[1]], "r--", linewidth=1.2, zorder=10)

        mid_x, mid_y = (p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0
        if self.ruler_text is not None:
            self.ruler_text.set_position((mid_x, mid_y))
            self.ruler_text.set_text(badge)
        else:
            self.ruler_text = self.ax_mesh.text(
                mid_x,
                mid_y,
                badge,
                color="red",
                fontsize=8,
                bbox=dict(boxstyle="round,pad=0.2", facecolor="#ffffff", edgecolor="red", alpha=0.8),
                zorder=11,
            )
        self.canvas_mesh.draw_idle()

    def redraw_mesh_views(self):
        self.btn_mesh_diagnostic.setEnabled(self.current_mesh_result is not None)
        if self.current_mesh_result is None:
            return
        res = self.current_mesh_result
        prev_xlim = self.ax_mesh.get_xlim() if self._mesh_drawn else None
        prev_ylim = self.ax_mesh.get_ylim() if self._mesh_drawn else None

        self.ax_mesh.clear()
        colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
        stride = (
            self.combo_detail.currentData()
            if hasattr(self, "combo_detail") and self.combo_detail.currentData()
            else 1
        )

        total_points=sum(x.size for x,y in res.blocks)+self.comparison_point_count()
        render_stride=max(int(stride),int(np.ceil(np.sqrt(total_points/250000))))
        self.draw_mesh_comparison(render_stride)
        self.combo_detail.setToolTip(f'Фактическое отображение 1:{render_stride}. Авторазрежение больших сеток влияет только на рисунок; экспорт полный.')
        for k, (bx, by) in enumerate(res.blocks):
            v = np.stack((bx * 1e3, by * 1e3), axis=-1)
            ii = np.unique(np.r_[np.arange(0, bx.shape[0], render_stride), bx.shape[0] - 1])
            jj = np.unique(np.r_[np.arange(0, bx.shape[1], render_stride), bx.shape[1] - 1])
            lines = [v[i,jj] for i in ii] + [v[ii,j] for j in jj]
            c = colors[k % len(colors)]
            self.ax_mesh.add_collection(LineCollection(lines, colors=c, linewidths=0.5, alpha=0.85))

            gid = k + 1
            is_active = gid in self.mesh_subpanel.selected_block_ids() if self.mesh_subpanel.scope_mode=="block" else self.highlighted_block_id == gid
            is_custom = gid in self.block_custom_configs
            tid = self.get_template_for_block(gid)
            has_tmpl = tid in self.template_configs

            # Ownership/selection belongs to the block badge, not its physical
            # boundary: otherwise rod walls look like faulty interfaces.
            border_col, border_lw = '#555555', .7
            border = [v[0], v[-1], v[:, 0], v[:, -1]]
            self.ax_mesh.add_collection(LineCollection(border, colors=border_col, linewidths=border_lw))

            cx, cy = float(np.mean(bx * 1e3)), float(np.mean(by * 1e3))
            badge_lbl = f"Б{gid} ★" if is_custom else (f"Б{gid} [T{tid}]" if has_tmpl else f"Б{gid}")
            badge_col = "#087ac1" if is_active else "#eeeeee" if is_custom else ("#d4e6f1" if has_tmpl else "#ffffff")

            self.ax_mesh.text(
                cx,
                cy,
                badge_lbl,
                fontsize=7.5,
                fontweight="bold",
                color="white" if is_active else "#111",
                ha="center",
                va="center",
                bbox=dict(boxstyle="round,pad=0.2", facecolor=badge_col, alpha=0.9, edgecolor=border_col, linewidth=0.8),
            )

        if prev_xlim is not None and prev_ylim is not None:
            self.ax_mesh.set_xlim(prev_xlim)
            self.ax_mesh.set_ylim(prev_ylim)
        else:
            self.ax_mesh.autoscale_view()
            self._mesh_drawn = True

        self.ax_mesh.set_aspect("equal", adjustable="box")
        self.ax_mesh.set_xlabel("X (мм)")
        self.ax_mesh.set_ylabel("Y (мм)")
        self.ax_mesh.set_title(f"Сетка выбранной области: {len(res.blocks)} блоков")
        from mesh_interface_overlay import draw_interface_overlay
        draw_interface_overlay(self.ax_mesh,res,
            selected=bool(self.mesh_subpanel.selected_block_ids()) if self.mesh_subpanel.scope_mode=='block' else self.highlighted_block_id is not None,
            custom=bool(self.block_custom_configs))
        self.draw_mesh_diagnostics()
        self.canvas_mesh.draw_idle()
        self.redraw_layer_plot_for_block(self.active_plot_block_idx)

    def confirm_interface_problems(self,result):
        issues=result.diagnostics.get('interface_problems',[])
        if not issues:return True
        nonconformal=sum(i['kind']=='nonconformal' for i in issues)
        text=f'Неконформных стыков: {nonconformal}; несовпадений геометрии: {len(issues)-nonconformal}.\n'
        for issue in issues[:12]:
            text+=f"Б{issue['block_a']+1} {issue['face_a']} ↔ Б{issue['block_b']+1} {issue['face_b']}: {'разное разбиение' if issue['kind']=='nonconformal' else 'разная геометрия'}, узлы {issue['nodes_a']}/{issue['nodes_b']}\n"
        if len(issues)>12:text+='Остальные стыки перечислены в отчёте качества.\n'
        text+='Продолжить для просмотра? Проблемные стыки будут подсвечены. Текущий экспорт STAR-CCM+ для такой сетки недоступен.'
        self.append_mesh_message(text)
        return QMessageBox.question(self,'Проблемы стыков',text,QMessageBox.Yes|QMessageBox.No,QMessageBox.No)==QMessageBox.Yes

    def on_select_mesh_block(self,event):
        if event.inaxes is not self.ax_mesh or event.button!=1 or self.current_mesh_result is None:return
        if self.btn_ruler.isChecked() or getattr(self.toolbar_mesh,'mode','') or getattr(self,'_mesh_diagnostic',None):return
        from matplotlib.path import Path
        from PySide6.QtCore import QSignalBlocker
        for i,(x,y) in enumerate(self.current_mesh_result.blocks):
            outline=np.column_stack((np.r_[x[0],x[1:,-1],x[-1,-2::-1],x[-2:0:-1,0]],np.r_[y[0],y[1:,-1],y[-1,-2::-1],y[-2:0:-1,0]]))*1e3
            if Path(outline).contains_point((event.xdata,event.ydata)):
                tree=self.mesh_subpanel.tree_blocks
                with QSignalBlocker(tree):
                    if 'control' not in str(event.key) and 'ctrl' not in str(event.key):tree.clearSelection()
                    for item in tree.findItems('',Qt.MatchContains|Qt.MatchRecursive,0):
                        if item.data(0,Qt.UserRole)==('block',i+1):item.setSelected(not item.isSelected())
                from bundle_block_editor import selected
                selected(self.mesh_subpanel)
                break

    def highlight_mesh_block(self, global_block_id):
        self.highlighted_block_id = global_block_id
        self.redraw_mesh_views()

    def save_quality_report(self, report):
        name, _ = QFileDialog.getSaveFileName(
            self, "Сохранить отчёт качества", "bundle_quality_report.json", "JSON (*.json)"
        )
        if not name:
            return None
        try:
            saved = mq.save_report(report, name)
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка сохранения отчёта", "Не удалось сохранить отчёт качества: " + str(exc))
            return None
        QMessageBox.information(self, "Отчёт сохранён", f"Отчёт качества сохранён в: {saved}")
        return saved

    def on_check_quality(self):
        if self.current_quality_report is None:
            return
        try:
            dlg = QualityDialog(
                self,
                report=self.current_quality_report,
                kind="3D сетка выбранных подканалов ТВС",
                profile=DEFAULT_PROFILE,
                result=self.current_mesh_result,
            )
            dlg.exec()
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка контроля качества", f"Не удалось открыть окно контроля качества:\n{exc}")

    def on_export_starccm_dialog(self):
        from mesh_interface_diagnostics import require_star_conformity
        if self.current_mesh_result is not None:
            try:require_star_conformity(self.current_mesh_result)
            except ValueError as exc:
                QMessageBox.warning(self,'Экспорт недоступен',str(exc));return
        if not self.can_export_mesh():
            QMessageBox.warning(self, "Предупреждение", "Нет актуальной полной сетки. Перестройте сетку или заполните актуальный слой.")
            return
        try:
            from starccm_export_dialog import StarCcmExportDialog

            f_props = getattr(self.mesh_subpanel, "current_fluid_props", {})
            yp_data = getattr(self.mesh_subpanel, "last_yplus_result", {})
            dlg = StarCcmExportDialog(
                self,
                mesh_result=self.current_mesh_result,
                bundle_model=self.model,
                fluid_props=f_props,
                yplus_data=yp_data,
            )
            if self.star_export_options is not None:
                try:dlg.apply_options(self.star_export_options)
                except ValueError as exc:self.append_mesh_message(f'Сохранённые настройки экспорта не подходят новой сетке: {exc}. Окно открыто со значениями по умолчанию.')
            dlg.exec()
        except Exception as exc:
            QMessageBox.critical(self, "Ошибка", f"Не удалось открыть окно экспорта STAR-CCM+:\n{exc}")

    def on_export_plot3d(self):
        if not self.can_export_mesh():
            QMessageBox.warning(self, "Предупреждение", "Нет актуальной полной сетки. Перестройте сетку или заполните актуальный слой.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Сохранить сетку Plot3D", "bundle_subchannels.xyz", "Plot3D (*.xyz)")
        if path:
            from mesh_export_jobs import run_export,ExportCancelled
            result=self.current_mesh_result
            def compute(progress):
                ms.export_subchannel_plot3d(result,path,progress_callback=progress)
                return path
            def success(saved):
                self.append_mesh_message(f'Экспорт Plot3D завершён: {saved}')
                QMessageBox.information(self,'Успешно',f'Сетка успешно сохранена в файл:\n{saved}')
            def failure(exc):
                self.append_mesh_message(f'Экспорт Plot3D: {exc or "отменён"}')
                if not isinstance(exc,ExportCancelled):
                    QMessageBox.critical(self,'Ошибка',f'Не удалось сохранить сетку:\n{exc}')
            self.append_mesh_message(f'Экспорт Plot3D: {path}')
            run_export(self,'Экспорт Plot3D',compute,success,failure)



def main():
    app = QApplication(sys.argv)
    window = BundleBuilderWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
