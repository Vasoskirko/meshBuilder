# -*- coding: utf-8 -*-
"""Виджет числового поля ввода с поддержкой единиц измерения."""
import math

try:
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QLineEdit
    HAS_QT = True
except ImportError:
    HAS_QT = False

from mesh_ui import NumberValue


class NumberField(QLineEdit if HAS_QT else object):
    if HAS_QT:
        edited = Signal()

    def __init__(self, value, factor=1., minimum=0., maximum=1e12):
        self.model = NumberValue(value, factor, minimum, maximum)
        if not HAS_QT:
            self._mock_text = self.model.display()
            self.setText = lambda t: setattr(self, "_mock_text", t)
            self.text = lambda: getattr(self, "_mock_text", "")
            self.setStyleSheet = lambda s: None
            return
        super().__init__()
        self.setText(self.model.display())
        self.textEdited.connect(self._edited)
        self.editingFinished.connect(self._finish)
        self.setToolTip("Разделитель целой и дробной части — точка (например 1.2; 5.7e-6).")

    def _edited(self, *_):
        if HAS_QT:
            self.setStyleSheet("")
            self.edited.emit()

    def _finish(self):
        try:
            self.value()
            self.setText(self.model.display())
            self.setStyleSheet("")
        except ValueError:
            self.setStyleSheet("border:1px solid #c33;")

    def value(self):
        text = self.text().strip()
        clean_text = text.rstrip(",.").replace(",", ".")
        if not clean_text:
            return self.model.raw
        try:
            raw_val = float(clean_text) * self.model.factor
            if math.isfinite(raw_val):
                self.model.raw = raw_val
                return raw_val
        except ValueError:
            pass
        return self.model.raw

    def setValue(self, value):
        self.setText(self.model.set_value(value))
        self.setStyleSheet("")

    def setFactor(self, factor):
        self.value()
        self.setText(self.model.change_factor(factor))

    def setLimits(self, minimum, maximum):
        self.model.minimum, self.model.maximum = minimum, maximum
