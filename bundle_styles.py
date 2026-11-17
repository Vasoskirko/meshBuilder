# -*- coding: utf-8 -*-
"""Стили Qt (QSS) для конструктора сечения ТВС."""

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
