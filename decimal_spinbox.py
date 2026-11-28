"""Qt numeric input accepting either decimal mark without thousands grouping."""
from PySide6.QtWidgets import QDoubleSpinBox


class DecimalSpinBox(QDoubleSpinBox):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.setGroupSeparatorShown(False)
        self.setToolTip('Десятичный разделитель: точка или запятая (12.75 = 12,75).')

    def _decimal_text(self,text):
        mark=self.locale().decimalPoint()
        return text.replace('.',mark).replace(',',mark)

    def validate(self,text,pos):
        return super().validate(self._decimal_text(text),pos)

    def valueFromText(self,text):
        return super().valueFromText(self._decimal_text(text))
