# -*- coding: utf-8 -*-
"""Диалог инженерного CFD-калькулятора y+ (IAPWS-97 / Идеальный газ)."""
try:
    from PySide6.QtWidgets import (
        QVBoxLayout, QHBoxLayout, QFormLayout, QGroupBox, QLineEdit,
        QComboBox, QPushButton, QLabel, QRadioButton, QButtonGroup, QDialog, QWidget, QScrollArea
    )
    HAS_QT = True
except ImportError:
    HAS_QT = False

import math

from fluid_properties_dialog import FluidPropertiesDialog

from yplus_calculator import calculate_yplus_and_step, FLUID_MODES
from fluid_properties import water_iapws97, gas_properties, GAS_PRESETS, WATER_CONDUCTIVITY_MODELS


class YPlusDialog(QDialog if HAS_QT else object):
    def __init__(self, parent=None, d_hyd_mm=14.0, a_fluid_mm2=100.0, target_field=None, state_dict=None):
        if not HAS_QT:
            return
        super().__init__(parent)
        self.setWindowTitle("Инженерный CFD-калькулятор y⁺ (IAPWS-97 / Идеальный газ)")
        self.resize(640, 720)
        self.target_field = target_field
        self.d_hyd_mm = d_hyd_mm
        self.a_fluid_mm2 = a_fluid_mm2
        self.state_dict = state_dict if state_dict is not None else {}

        self.properties_dialog = FluidPropertiesDialog(self,self.state_dict.get('conductivity_model','background'))
        # One shared selector/state; it is shown only in the property window.
        self.combo_water_conductivity = self.properties_dialog.combo_conductivity
        outer_lay = QVBoxLayout(self)
        scroll = QScrollArea(self); scroll.setWidgetResizable(True)
        content = QWidget(); lay = QVBoxLayout(content)
        scroll.setWidget(content); outer_lay.addWidget(scroll)

        g_fluid = QGroupBox("1. Теплоноситель и теплофизические свойства", self)
        f_fluid = QFormLayout(g_fluid)
        self.fluid_form = f_fluid

        self.combo_fluid_mode = QComboBox(self)
        for m_name in FLUID_MODES:
            self.combo_fluid_mode.addItem(m_name)

        init_mode = self.state_dict.get("fluid_mode", "Вода IAPWS-97 (T, P)")
        idx = self.combo_fluid_mode.findText(init_mode)
        if idx >= 0:
            self.combo_fluid_mode.setCurrentIndex(idx)
        self.combo_fluid_mode.currentIndexChanged.connect(self.on_fluid_mode_changed)
        f_fluid.addRow("Модель среды:", self.combo_fluid_mode)

        r_tp = QHBoxLayout()
        r_tp.addWidget(QLabel("T (°C):"))
        self.edit_temp = QLineEdit(str(self.state_dict.get("temp_c", "300.0")), self)
        self.edit_temp.textEdited.connect(self.recalc)
        r_tp.addWidget(self.edit_temp)

        r_tp.addWidget(QLabel("P (МПа):"))
        self.edit_press = QLineEdit(str(self.state_dict.get("press_mpa", "15.0")), self)
        self.edit_press.textEdited.connect(self.recalc)
        r_tp.addWidget(self.edit_press)
        f_fluid.addRow("Состояние (T, P):", r_tp)

        self.combo_gas = QComboBox(self)
        for gname in GAS_PRESETS:
            self.combo_gas.addItem(gname)
        self.combo_gas.currentIndexChanged.connect(self.recalc)
        f_fluid.addRow("Выбор газа:", self.combo_gas)

        self.combo_water_conductivity.currentIndexChanged.connect(self.recalc)

        self.edit_density = QLineEdit(str(self.state_dict.get("density", "712.0")), self)
        self.edit_density.textEdited.connect(self.recalc)
        f_fluid.addRow("Плотность (ρ, кг/м³):", self.edit_density)

        self.edit_visc = QLineEdit(str(self.state_dict.get("dyn_vis", "8.6e-5")), self)
        self.edit_visc.textEdited.connect(self.recalc)
        f_fluid.addRow("Динамическая вязкость (μ, Па·с):", self.edit_visc)

        self.edit_kinematic = QLineEdit(self); self.edit_kinematic.setReadOnly(True)
        self.edit_kinematic.setPlaceholderText('—')
        f_fluid.addRow('Кинематическая вязкость (ν, м²/с):',self.edit_kinematic)
        self.lbl_extra_props = QLabel(self); self.lbl_extra_props.setWordWrap(True)
        f_fluid.addRow('Модель свойств:',self.lbl_extra_props)
        self.btn_properties = QPushButton('Все свойства теплоносителя и насыщение…',self)
        self.btn_properties.clicked.connect(self.open_properties)
        f_fluid.addRow(self.btn_properties)

        lay.addWidget(g_fluid)

        g_geom = QGroupBox("2. Гидравлический масштаб ВЫБРАННОЙ области ТВС", self)
        f_geom = QFormLayout(g_geom)
        self.lbl_dh = QLabel(f"D_h = {self.d_hyd_mm:.3f} мм | A_fluid = {self.a_fluid_mm2:.3f} мм²")
        self.lbl_dh.setStyleSheet("font-weight: bold; color: #1a237e;")
        f_geom.addRow("Сечение потока:", self.lbl_dh)
        lay.addWidget(g_geom)

        g_flow = QGroupBox("3. Режим течения теплоносителя (выберите один)", self)
        l_flow = QVBoxLayout(g_flow)

        self.btn_group = QButtonGroup(self)

        r_re = QHBoxLayout()
        self.rad_re = QRadioButton("По числу Рейнольдса (Re):", self)
        self.btn_group.addButton(self.rad_re)
        self.edit_re = QLineEdit(str(self.state_dict.get("re", "50000")), self)
        self.edit_re.textEdited.connect(self.recalc)
        r_re.addWidget(self.rad_re)
        r_re.addWidget(self.edit_re)
        l_flow.addLayout(r_re)

        r_vel = QHBoxLayout()
        self.rad_vel = QRadioButton("По скорости потока (U_bulk, м/с):", self)
        self.btn_group.addButton(self.rad_vel)
        self.edit_vel = QLineEdit(str(self.state_dict.get("vel", "2.0")), self)
        self.edit_vel.textEdited.connect(self.recalc)
        r_vel.addWidget(self.rad_vel)
        r_vel.addWidget(self.edit_vel)
        l_flow.addLayout(r_vel)

        r_flow = QHBoxLayout()
        self.rad_flow = QRadioButton("По массовому расходу (Q, кг/с):", self)
        self.btn_group.addButton(self.rad_flow)
        self.edit_flow = QLineEdit(str(self.state_dict.get("flow", "0.15")), self)
        self.edit_flow.textEdited.connect(self.recalc)
        r_flow.addWidget(self.rad_flow)
        r_flow.addWidget(self.edit_flow)
        l_flow.addLayout(r_flow)

        init_flow_mode = self.state_dict.get("flow_mode", "reynolds")
        if init_flow_mode == "velocity":
            self.rad_vel.setChecked(True)
        elif init_flow_mode == "flow_rate":
            self.rad_flow.setChecked(True)
        else:
            self.rad_re.setChecked(True)

        self.rad_re.toggled.connect(self.recalc)
        self.rad_vel.toggled.connect(self.recalc)
        self.rad_flow.toggled.connect(self.recalc)

        r_yp = QHBoxLayout()
        r_yp.addWidget(QLabel("Целевой y⁺ (для стенки):"))
        self.edit_yplus = QLineEdit(str(self.state_dict.get("yplus", "1.0")), self)
        self.edit_yplus.textEdited.connect(self.recalc)
        r_yp.addWidget(self.edit_yplus)
        l_flow.addLayout(r_yp)
        lay.addWidget(g_flow)

        g_res = QGroupBox("4. Результаты расчёта и размер первой ячейки", self)
        f_res = QFormLayout(g_res)

        self.lbl_flow_summary = QLabel(self)
        self.lbl_flow_summary.setStyleSheet("color: #37474f;")
        f_res.addRow("Параметры потока:", self.lbl_flow_summary)

        self.lbl_tau_summary = QLabel(self)
        self.lbl_tau_summary.setStyleSheet("color: #37474f;")
        f_res.addRow("Трение на стенке:", self.lbl_tau_summary)

        self.lbl_step_res = QLabel(self)
        self.lbl_step_res.setStyleSheet("font-size: 13px; font-weight: bold; color: #2e7d32; padding: 4px; background: #e8f5e9; border-radius: 4px;")
        f_res.addRow("Искомый размер ячейки:", self.lbl_step_res)
        lay.addWidget(g_res)

        b_box = QHBoxLayout()
        self.btn_apply = QPushButton("Применить Δy₁ как h1 в сетку", self)
        self.btn_apply.setStyleSheet("background: #2e7d32; color: white; font-weight: bold; padding: 7px;")
        self.btn_apply.clicked.connect(self.apply_result)
        b_box.addWidget(self.btn_apply)

        btn_close = QPushButton("Закрыть", self)
        btn_close.clicked.connect(self.reject)
        b_box.addWidget(btn_close)
        outer_lay.addLayout(b_box)

        self.calculated_delta_y1_um = 2.5
        self.on_fluid_mode_changed(0)

    def on_fluid_mode_changed(self, idx):
        m_name = self.combo_fluid_mode.currentText()
        is_iapws = ("IAPWS" in m_name)
        is_gas = ("газ" in m_name)

        self.edit_temp.setEnabled(is_iapws or is_gas)
        self.edit_press.setEnabled(is_iapws or is_gas)
        self.combo_gas.setVisible(is_gas)
        self.fluid_form.labelForField(self.combo_gas).setVisible(is_gas)
        self.combo_water_conductivity.setEnabled(is_iapws)

        self.edit_density.setReadOnly(is_iapws or is_gas)
        self.edit_visc.setReadOnly(is_iapws or is_gas)
        self.recalc()

    def save_state(self):
        self.state_dict["conductivity_model"] = self.combo_water_conductivity.currentData()
        self.state_dict["fluid_mode"] = self.combo_fluid_mode.currentText()
        self.state_dict["temp_c"] = self.edit_temp.text().strip()
        self.state_dict["press_mpa"] = self.edit_press.text().strip()
        self.state_dict["density"] = self.edit_density.text().strip()
        self.state_dict["dyn_vis"] = self.edit_visc.text().strip()
        self.state_dict["re"] = self.edit_re.text().strip()
        self.state_dict["vel"] = self.edit_vel.text().strip()
        self.state_dict["flow"] = self.edit_flow.text().strip()
        self.state_dict["yplus"] = self.edit_yplus.text().strip()
        if self.rad_vel.isChecked():
            self.state_dict["flow_mode"] = "velocity"
        elif self.rad_flow.isChecked():
            self.state_dict["flow_mode"] = "flow_rate"
        else:
            self.state_dict["flow_mode"] = "reynolds"

    def open_properties(self):
        self.show_property_values(getattr(self,'current_fluid_props',{}))
        self.properties_dialog.show()
        self.properties_dialog.raise_()
        self.properties_dialog.activateWindow()

    def show_property_values(self, props):
        value=props.get('kin_vis')
        self.edit_kinematic.setText('' if value is None else f'{value:.8e}')
        self.properties_dialog.set_properties(props,self.combo_fluid_mode.currentText(),
            'IAPWS' in self.combo_fluid_mode.currentText())
        self.btn_properties.setEnabled(bool(props))

    def done(self, result):
        self.properties_dialog.close()
        super().done(result)

    def recalc(self):
        properties_ready = False
        try:
            m_name = self.combo_fluid_mode.currentText()
            t_c = float(self.edit_temp.text().strip().replace(",", "."))
            p_mpa = float(self.edit_press.text().strip().replace(",", "."))

            if "IAPWS" in m_name:
                p_props = water_iapws97(t_c, p_mpa, conductivity_model=self.combo_water_conductivity.currentData())
                self.current_fluid_props = p_props
                self.lbl_extra_props.setToolTip(p_props["desc"])
                rho = p_props["density"]
                mu = p_props["dyn_vis"]
                self.edit_density.setText(f"{rho:.6f}")
                self.edit_visc.setText(f"{mu:.7e}")
                self.lbl_extra_props.setText('Плотность — IF97; вязкость — IAPWS 2008. Полные свойства доступны в отдельном окне.')
            elif "газ" in m_name:
                comp = ("сжимаемый" in m_name)
                g_props = gas_properties(self.combo_gas.currentText(), t_c, p_mpa, compressible=comp)
                self.current_fluid_props = g_props
                rho = g_props["density"]
                mu = g_props["dyn_vis"]
                self.edit_density.setText(str(rho))
                self.edit_visc.setText(f"{mu:.7e}")
                self.lbl_extra_props.setText(g_props['desc'])
            else:
                rho = float(self.edit_density.text().strip().replace(",", "."))
                mu = float(self.edit_visc.text().strip().replace(",", "."))
                self.current_fluid_props = {
                    "density": rho, "dyn_vis": mu,
                    "t_ref_c": t_c, "p_ref_mpa": p_mpa
                }
                self.lbl_extra_props.setText("Пользовательские свойства теплоносителя")

            # Derived viscosity is meaningful for water, gas and manual rho/mu.
            if not math.isfinite(rho) or not math.isfinite(mu) or rho<=0 or mu<=0:
                raise ValueError('Плотность и динамическая вязкость должны быть положительными и конечными')
            self.current_fluid_props.update(kin_vis=mu/rho,t_ref_c=t_c,p_ref_mpa=p_mpa)
            self.show_property_values(self.current_fluid_props)
            properties_ready = True
            y_target = float(self.edit_yplus.text().strip().replace(",", "."))

            if self.rad_re.isChecked():
                flow_m = "reynolds"
                inp = float(self.edit_re.text().strip().replace(",", "."))
            elif self.rad_vel.isChecked():
                flow_m = "velocity"
                inp = float(self.edit_vel.text().strip().replace(",", "."))
            else:
                flow_m = "flow_rate"
                inp = float(self.edit_flow.text().strip().replace(",", "."))

            res = calculate_yplus_and_step(
                mode=flow_m,
                value=inp,
                rho=rho,
                mu=mu,
                dh_mm=self.d_hyd_mm,
                area_mm2=self.a_fluid_mm2,
                y_plus=y_target
            )

            self.calculated_delta_y1_um = res["delta_y1_um"]
            self.last_yplus_result = res
            self.lbl_flow_summary.setText(
                f"Re = {res['re']:,.0f} | U_bulk = {res['u']:.3f} м/с | Q = {res['mass_flow']:.4f} кг/с"
            )
            self.lbl_tau_summary.setText(
                f"Cf = {res['cf']:.5f} | τ_w = {res['tau_w']:.2f} Па | u_τ = {res['u_tau']:.4f} м/с"
            )
            self.lbl_step_res.setText(res["step_display_str"])
            self.btn_apply.setEnabled(True)
            self.save_state()
        except Exception as exc:
            if not properties_ready:
                self.current_fluid_props = {}
                self.show_property_values({})
                self.lbl_extra_props.setText('Свойства не рассчитаны: проверьте T, P и модель среды')
                if self.edit_density.isReadOnly(): self.edit_density.clear()
                if self.edit_visc.isReadOnly(): self.edit_visc.clear()
            self.lbl_step_res.setText(f"Проверьте ввод: {exc}")
            self.btn_apply.setEnabled(False)

    def apply_result(self):
        if self.target_field is not None and self.calculated_delta_y1_um > 0:
            self.save_state()
            rounded_um = round(self.calculated_delta_y1_um, 3)
            self.target_field.setValue(rounded_um * 1e-6)
            self.accept()
