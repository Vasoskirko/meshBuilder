# -*- coding: utf-8 -*-
"""Окно встроенной справки."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSplitter,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from mesh_ui import GROUPS, TOPICS, topic_html


class HelpDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Справка — генератор сетки")
        self.resize(1040, 750)
        self.setModal(False)
        self.current_topic = None
        self.items = {}

        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Найти в текущем разделе…")
        self.search.returnPressed.connect(self.find_next)
        row.addWidget(self.search, 1)
        find = QPushButton("Найти далее")
        find.clicked.connect(self.find_next)
        row.addWidget(find)
        layout.addLayout(row)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        for title, keys in GROUPS:
            group = QTreeWidgetItem(self.tree, [title])
            group.setExpanded(True)
            for key in keys:
                item = QTreeWidgetItem(group, [TOPICS[key][0]])
                item.setData(0, Qt.ItemDataRole.UserRole, key)
                self.items[key] = item
        self.tree.currentItemChanged.connect(self.topic_changed)
        splitter.addWidget(self.tree)

        self.browser = QTextBrowser()
        self.browser.setOpenLinks(False)
        self.browser.setOpenExternalLinks(False)
        self.browser.anchorClicked.connect(self.open_link)
        splitter.addWidget(self.browser)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([310, 730])
        layout.addWidget(splitter, 1)

        self.status = QLabel("Справка не меняет параметры сетки.")
        layout.addWidget(self.status)

        close = QPushButton("Закрыть")
        close.clicked.connect(self.close)
        bottom = QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(close)
        layout.addLayout(bottom)
        self.show_topic("start")

    def topic_changed(self, item, previous):
        if item is None:
            return
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if key in TOPICS:
            self.render_topic(key)

    def render_topic(self, key):
        self.current_topic = key
        self.browser.setHtml(topic_html(key))
        self.status.setText("Раздел: " + TOPICS[key][0])

    def show_topic(self, key):
        if key not in self.items:
            key = "start"
        self.tree.setCurrentItem(self.items[key])
        self.render_topic(key)

    def open_link(self, url):
        if url.scheme() == "help":
            self.show_topic(url.toString().split(":", 1)[1])

    def find_next(self, *_):
        text = self.search.text().strip()
        if not text:
            self.status.setText("Введите текст для поиска в текущем разделе.")
            return
        if self.browser.find(text):
            self.status.setText("Найдено: " + text)
            return
        cursor = self.browser.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        self.browser.setTextCursor(cursor)
        self.status.setText(
            "Поиск продолжен с начала раздела."
            if self.browser.find(text)
            else "В текущем разделе текст не найден."
        )
