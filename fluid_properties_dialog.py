"""Read-only fluid-state properties; calculations remain in fluid_properties."""
try:
    from PySide6.QtWidgets import (QDialog, QVBoxLayout, QFormLayout, QGroupBox,
        QLineEdit, QLabel, QPushButton, QScrollArea, QWidget, QComboBox)
    HAS_QT = True
except ImportError:
    HAS_QT = False

from fluid_properties import WATER_CONDUCTIVITY_MODELS


class FluidPropertiesDialog(QDialog if HAS_QT else object):
    def __init__(self, parent=None, conductivity_model='background'):
        if not HAS_QT:
            return
        super().__init__(parent)
        self.setWindowTitle('Свойства теплоносителя и линия насыщения')
        self.resize(740, 780)
        outer = QVBoxLayout(self)
        self.state_label = QLabel(self); self.state_label.setWordWrap(True)
        outer.addWidget(self.state_label)
        scroll = QScrollArea(self); scroll.setWidgetResizable(True)
        content = QWidget(); layout = QVBoxLayout(content); scroll.setWidget(content)
        outer.addWidget(scroll)
        self.model_group = QGroupBox('Модель теплопроводности воды', self)
        model_layout = QVBoxLayout(self.model_group)
        self.combo_conductivity = QComboBox(self)
        for key, label in WATER_CONDUCTIVITY_MODELS.items():
            self.combo_conductivity.addItem(label, key)
        self.combo_conductivity.setCurrentIndex(max(0,self.combo_conductivity.findData(conductivity_model)))
        self.combo_conductivity.setToolTip('При 300 °C / 15 МПа: без усиления λ≈0.557437; с усилением λ≈0.563209 Вт/(м·К). Не влияет на ρ, μ и расчёт y+.')
        model_layout.addWidget(self.combo_conductivity); layout.addWidget(self.model_group)
        properties = QGroupBox('Свойства текущего состояния', self)
        form = QFormLayout(properties); self.property_fields = {}
        for key, label in (
            ('density','Плотность (ρ, кг/м³):'), ('dyn_vis','Динамическая вязкость (μ, Па·с):'),
            ('kin_vis','Кинематическая вязкость (ν, м²/с):'), ('cp','Теплоёмкость (Cp, Дж/(кг·К)):'),
            ('lambda','Теплопроводность (λ, Вт/(м·К)):'), ('prandtl','Число Прандтля (Pr):'),
            ('enthalpy','Удельная энтальпия (h, кДж/кг):'), ('gamma','Показатель адиабаты (γ, газ):')):
            field = self._field(); self.property_fields[key] = field; form.addRow(label,field)
        self.property_fields['enthalpy'].setToolTip('Отсчёт IF97. При сравнении со STAR проверьте точку отсчёта энтальпии.')
        self.source_label = QLabel(self); self.source_label.setWordWrap(True)
        form.addRow('Метод расчёта:',self.source_label); layout.addWidget(properties)
        self.saturation_group = QGroupBox('Линия насыщения воды (IF97)',self)
        saturation = QFormLayout(self.saturation_group); self.saturation_fields = {}
        for key,label in (
            ('saturation_pressure_mpa','Давление насыщения при T (Psat, МПа):'),
            ('saturation_temperature_c','Температура насыщения при P (Tsat, °C):'),
            ('subcooling_k','Недогрев до насыщения (Tsat − T, K):'),
            ('pressure_margin_mpa','Запас давления (P − Psat, МПа):'),
            ('saturated_liquid_density','Плотность жидкости при Tsat(P) (ρ′, кг/м³):'),
            ('saturated_vapor_density','Плотность пара при Tsat(P) (ρ″, кг/м³):'),
            ('saturated_liquid_enthalpy','Энтальпия жидкости при Tsat(P) (h′, кДж/кг):'),
            ('saturated_vapor_enthalpy','Энтальпия пара при Tsat(P) (h″, кДж/кг):'),
            ('latent_heat','Теплота парообразования при P (r, кДж/кг):')):
            field=self._field();self.saturation_fields[key]=field;saturation.addRow(label,field)
        self.saturation_note=QLabel(self);self.saturation_note.setWordWrap(True)
        saturation.addRow(self.saturation_note);layout.addWidget(self.saturation_group)
        self.note=QLabel('T и P изменяются в калькуляторе y+. Это окно обновляется автоматически. Закрытие окна не меняет h1.',self)
        self.note.setWordWrap(True);outer.addWidget(self.note)
        close=QPushButton('Закрыть',self);close.clicked.connect(self.close);outer.addWidget(close)

    def _field(self):
        field=QLineEdit(self);field.setReadOnly(True);field.setPlaceholderText('—');return field

    def set_properties(self, props, mode='', is_water=True):
        self.props=dict(props)
        self.model_group.setVisible(is_water);self.saturation_group.setVisible(is_water)
        temperature=props.get('t_ref_c');pressure=props.get('p_ref_mpa')
        state=f'{mode}; T = {temperature:g} °C; P = {pressure:g} МПа' if temperature is not None and pressure is not None else f'{mode}: свойства не рассчитаны'
        self.state_label.setText(state)
        self.source_label.setText(props.get('desc','Для отсутствующих данных показан прочерк'))
        for key,field in {**self.property_fields,**self.saturation_fields}.items():
            value=props.get(key)
            if value is not None and ('enthalpy' in key or key=='latent_heat'):value/=1000
            field.setText('' if value is None else (f'{value:.8e}' if key in ('dyn_vis','kin_vis') else f'{value:.8g}'))
        self.saturation_note.setText(props.get('saturation_status',''))
