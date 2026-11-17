# -*- coding: utf-8 -*-
"""Диалоговое окно таблицы гидравлических характеристик подканалов ТВС."""
import csv

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


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
            "ID подканала",
            "Тип",
            "Стержни",
            "Площадь A (мм²)",
            "Периметр P (мм)",
            "D_h (мм)",
            "Входит в расчёт",
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
            "corner": "Угловые",
        }

        all_summary = self.model.get_total_assembly_summary()
        lines = [
            "<table border='0' cellpadding='4'><tr><th>Категория подканалов</th>"
            "<th>Число</th><th>Ср. площадь A (мм²)</th><th>Ср. периметр P (мм)</th><th>Ср. D_h (мм)</th></tr>"
        ]

        if all_summary:
            for st, data in all_summary["by_type"].items():
                cnt = data["count"]
                mean_a = data["a_fluid"] / cnt
                mean_p = data["p_wet"] / cnt
                dh = (4.0 * mean_a / mean_p) if mean_p > 0 else 0.0
                name = types_ru.get(st, st)
                lines.append(
                    f"<tr><td><b>{name}</b></td><td>{cnt}</td><td>{mean_a:.2f}</td>"
                    f"<td>{mean_p:.2f}</td><td><b>{dh:.2f}</b></td></tr>"
                )

            lines.append(
                f"<tr style='background-color:#eaf2f8;'><td><b>ВСЯ СБОРКА ТВС (суммарно)</b></td>"
                f"<td><b>{all_summary['total_subchannels']}</b></td>"
                f"<td><b>{all_summary['total_a_fluid_mm2']:.2f}</b></td>"
                f"<td><b>{all_summary['total_p_wet_mm']:.2f}</b></td>"
                f"<td><b>{all_summary['total_d_h_mm']:.2f}</b></td></tr>"
            )

        sel_summary = self.model.get_selection_summary()
        if sel_summary and sel_summary["total_subchannels"] != len(self.model.subchannels):
            lines.append(
                f"<tr style='background-color:#e8f8f5;'><td><b>ВЫБРАННАЯ ОБЛАСТЬ (суммарно)</b></td>"
                f"<td><b>{sel_summary['total_subchannels']}</b></td>"
                f"<td><b>{sel_summary['total_a_fluid_mm2']:.2f}</b></td>"
                f"<td><b>{sel_summary['total_p_wet_mm']:.2f}</b></td>"
                f"<td><b>{sel_summary['total_d_h_mm']:.2f}</b></td></tr>"
            )

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
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт характеристик подканалов", "subchannels_hydraulics.csv", "CSV (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "ID подканала",
                    "Тип",
                    "Стержни",
                    "Площадь A (мм2)",
                    "Смоченный периметр P (мм)",
                    "Гидравлический диаметр Dh (мм)",
                    "Выбран в расчет",
                ])
                for row in range(self.table.rowCount()):
                    writer.writerow([self.table.item(row, col).text() for col in range(self.table.columnCount())])
            QMessageBox.information(self, "Экспорт завершён", f"Таблица успешно сохранена в:\n{path}")
        except Exception as exc:
            QMessageBox.warning(self, "Ошибка записи", f"Не удалось записать CSV: {exc}")
