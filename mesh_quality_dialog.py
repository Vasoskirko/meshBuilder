# -*- coding: utf-8 -*-
"""Окно отчёта о метриках качества сетки."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from mesh_quality import (
    DEFAULT_PROFILE,
    METRIC_INFO,
    QualityError,
    analyse_result,
    format_report,
    interpret_report,
    validate_profile,
)


class QualityDialog(QDialog):
    """Отчёт о метриках качества; не меняет сетку и параметры.

    Три вкладки:
      Обзор   — понятные названия, статусы (ок/проверить/риск), доли превышений.
      Подробности — прежний сырой текстовый отчёт.
      Пояснения и пороги — смысл метрик, редактирование ориентиров профиля.
    Изменение порогов не влияет на сетку, проект и признак `*`.
    """

    STATUS_COLORS = {
        "ok": "#2e7d32",
        "caution": "#b8860b",
        "risk": "#c0392b",
        "error": "#c0392b",
        "info": "#555555",
    }
    STATUS_LABELS = {
        "ok": "Без замечаний",
        "caution": "Требует проверки",
        "risk": "Высокий риск",
        "error": "Ошибка",
        "info": "Требует контекста",
    }

    def __init__(self, parent, report, kind, profile=None, result=None):
        super().__init__(parent)
        self.report = report
        self.result_for_recount = result
        self.profile = {k: dict(v) for k, v in (profile or DEFAULT_PROFILE).items()}
        self.setWindowTitle("Метрики качества сетки")
        self.resize(1280, 760)
        self.setModal(False)

        outer = QVBoxLayout(self)
        head = QLabel(f"{kind}. Пороги — настраиваемые ориентиры этой программы, не нормы решателя.")
        head.setWordWrap(True)
        outer.addWidget(head)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)

        self.overview = self._build_overview()
        self.tabs.addTab(self.overview, "Обзор")
        self.details = self._build_details()
        self.tabs.addTab(self.details, "Подробности")
        self.explain = self._build_explain()
        self.tabs.addTab(self.explain, "Пояснения и пороги")

        row = QHBoxLayout()
        row.addStretch()
        self.save_button = QPushButton("Сохранить отчёт JSON…")
        self.save_button.clicked.connect(self.save)
        close = QPushButton("Закрыть")
        close.clicked.connect(self.close)
        row.addWidget(self.save_button)
        row.addWidget(close)
        outer.addLayout(row)

        self._refresh_overview()

    def _build_overview(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setSpacing(10)
        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("font-weight:bold;padding:4px;")
        v.addWidget(self.summary_label)

        self.metric_tree = QTreeWidget()
        self.metric_tree.setColumnCount(5)
        self.metric_tree.setHeaderLabels(["Показатель", "Худшее значение", "Статус", "Требуют внимания", "Пояснение"])
        self.metric_tree.setRootIsDecorated(False)
        self.metric_tree.setColumnWidth(0, 380)
        self.metric_tree.setColumnWidth(1, 120)
        self.metric_tree.setColumnWidth(2, 130)
        self.metric_tree.setColumnWidth(3, 220)
        self.metric_tree.header().setStretchLastSection(True)
        self.metric_tree.setWordWrap(True)
        self.metric_tree.setTextElideMode(Qt.TextElideMode.ElideNone)
        v.addWidget(self.metric_tree, 1)

        self.notes_label = QLabel()
        self.notes_label.setWordWrap(True)
        v.addWidget(self.notes_label)
        return w

    def _refresh_overview(self):
        interp = interpret_report(self.report, self.profile)
        st = interp["summary_status"]
        color = self.STATUS_COLORS.get(st, "#333")
        self.summary_label.setText(interp["summary"])
        self.summary_label.setStyleSheet(f"font-weight:bold;padding:4px;color:{color};")
        self.metric_tree.clear()
        for r in interp["rows"]:
            worst = r["worst_fmt"]
            status = r["status"]
            color = self.STATUS_COLORS.get(status, "#333")
            label = self.STATUS_LABELS.get(status, status)
            zone_text = "недоступно"
            if r.get("zone_caution_count") is not None or r.get("zone_risk_count") is not None:
                c = int(r.get("zone_caution_count") or 0)
                k = int(r.get("zone_risk_count") or 0)
                total = int(r.get("count") or 0)
                scope = "граней" if r["name"] in ("non_orthogonality_deg", "neighbor_volume_ratio") else "яч."
                if total > 0:
                    pct = 100.0 * (c + k) / total
                    zone_text = f"{pct:.3f}% ({c + k} из {total} {scope})"
            item = QTreeWidgetItem()
            item.setText(0, r["title"])
            item.setText(1, worst)
            item.setText(2, label)
            item.setText(3, zone_text)
            item.setText(4, r["status_text"])
            item.setForeground(2, QBrush(QColor(color)))
            if status == "risk":
                item.setForeground(1, QBrush(QColor(color)))
            self.metric_tree.addTopLevelItem(item)
        for i, r in enumerate(interp["rows"]):
            item = self.metric_tree.topLevelItem(i)
            item.setToolTip(0, r["location_fmt"])
            item.setToolTip(1, r["location_fmt"])
        self.notes_label.setText("\n".join("• " + n for n in interp["notes"]))

    def _refresh_details(self):
        self.text.setPlainText(format_report(self.report))

    def _build_details(self):
        w = QWidget()
        v = QVBoxLayout(w)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.text.setPlainText(format_report(self.report))
        v.addWidget(self.text, 1)
        return w

    def _build_explain(self):
        w = QWidget()
        outer = QVBoxLayout(w)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        inner = QWidget()
        v = QVBoxLayout(inner)
        sc.setWidget(inner)
        outer.addWidget(sc, 1)

        intro = QLabel(
            "Пороги — это ориентировочные границы программы, а не обязательные нормы решателя. "
            "Их можно изменить; результат пересчитывается без изменения сетки, проекта и признака `*`."
        )
        intro.setWordWrap(True)
        v.addWidget(intro)

        self.threshold_fields = {}
        for name in ("scaled_jacobian", "skewness", "non_orthogonality_deg", "neighbor_volume_ratio"):
            box = QGroupBox(METRIC_INFO[name]["title"])
            fl = QFormLayout(box)
            d = QLabel(METRIC_INFO[name]["direction"])
            d.setWordWrap(True)
            fl.addRow(d)
            caution = QLineEdit(str(self.profile.get(name, {}).get("caution") or ""))
            risk = QLineEdit(str(self.profile.get(name, {}).get("risk") or ""))
            fl.addRow("Жёлтая зона (проверить):", caution)
            fl.addRow("Красная зона (высокий риск):", risk)
            self.threshold_fields[name] = (caution, risk)
            v.addWidget(box)

        btn = QPushButton("Применить пороги и обновить отчёт")
        btn.clicked.connect(self._apply_profile)
        v.addWidget(btn)
        self.warn_label = QLabel("")
        self.warn_label.setWordWrap(True)
        self.warn_label.setStyleSheet("color:#c0392b;padding:4px;")
        v.addWidget(self.warn_label)
        v.addStretch()
        return w

    def _apply_profile(self):
        self.warn_label.setText("")
        candidate = {}
        for name, (caution, risk) in self.threshold_fields.items():
            candidate[name] = {
                "caution": caution.text().strip() or None,
                "risk": risk.text().strip() or None,
            }
        for name, p in candidate.items():
            for key in ("caution", "risk"):
                if p[key] is None:
                    continue
                try:
                    p[key] = float(p[key])
                except (TypeError, ValueError):
                    self.warn_label.setText(f"Порог {name}.{key} должен быть числом или пустым.")
                    return
        try:
            validated = validate_profile(candidate)
        except QualityError as exc:
            self.warn_label.setText(str(exc))
            return
        if self.result_for_recount is not None:
            try:
                new_report = analyse_result(self.result_for_recount, profile=validated)
            except Exception:
                self.warn_label.setText("Не удалось пересчитать зоны по новым порогам; прежние пороги сохранены.")
                return
            self.report = new_report
            self.profile = validated
            self._refresh_overview()
            self._refresh_details()
        else:
            self.profile = validated
            self._refresh_overview()
            self.warn_label.setText(
                "Доли превышений недоступны: нужен повторный анализ исходной сетки. "
                "Статусы обновлены по новому профилю."
            )

    def save(self):
        parent = self.parent()
        if parent is not None:
            parent.save_quality_report(self.report)
