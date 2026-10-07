from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QLockFile, QThread, QTime, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox,
    QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
    QTimeEdit, QVBoxLayout, QWidget)

from .browser import BrowserAdapter, DemoAdapter
from .core import Monitor, Settings, Store, resolve_seller


def data_dir():
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
    path = root / "XianyuSellerMonitor"
    path.mkdir(parents=True, exist_ok=True)
    return path


class Worker(QThread):
    event = Signal(str, object)

    def __init__(self, settings, directory, mode):
        super().__init__()
        self.settings, self.directory, self.mode = settings, directory, mode
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    def run(self):
        adapter = store = None
        emit = self.event.emit
        try:
            if self.mode == "demo":
                settings = replace(self.settings, seller="2141274515", auto_order=True, scheduled=False)
                adapter = DemoAdapter()
                store = Store(":memory:")
                emit("log", "演示模式：全部商品和订单均为模拟数据，不连接闲鱼")
            else:
                settings = self.settings
                if self.mode != "login":
                    emit("state", "正在解析卖家")
                    settings = replace(settings, seller=resolve_seller(settings.seller))
                    settings.validate()
                    settings.save(self.directory / "settings.json")
                    emit("seller", settings.seller)
                adapter = BrowserAdapter(self.directory / "browser-profile", settings.browser, emit, self.stop_event.is_set)
                emit("state", "正在打开浏览器")
                adapter.open()
                if self.mode == "login":
                    emit("state", "等待扫码登录")
                    emit("log", "请在独立浏览器中登录闲鱼。完成后点击“完成登录”，再开始监控")
                    while not self.stop_event.is_set():
                        adapter.pump()
                    emit("state", "登录窗口已关闭")
                    return
                store = Store(self.directory / "monitor.sqlite3")
                emit("rows", store.rows())
            settings.validate()
            monitor = Monitor(settings, store, adapter, emit,
                              lambda: self.stop_event.is_set() or not settings.active_at(datetime.now()))
            was_active = False
            while not self.stop_event.is_set():
                active = settings.active_at(datetime.now())
                if not active:
                    if was_active or monitor.ready:
                        monitor.ready = False
                    was_active = False
                    emit("state", "等待监控时段")
                    self._wait(1, adapter)
                    continue
                if not was_active:
                    # Baseline again after schedule gaps; don't order old/offline listings.
                    monitor.ready = False
                was_active = True
                emit("state", "演示运行中" if self.mode == "demo" else "监控中")
                started = time.monotonic()
                monitor.tick()
                elapsed = time.monotonic() - started
                emit("elapsed", elapsed)
                self._wait(max(0, settings.interval - elapsed), adapter)
            emit("state", "已停止")
        except Exception as exc:
            emit("state", "已暂停 · 需要处理")
            emit("log", f"{type(exc).__name__}: {str(exc)[:650]}")
            emit("log", "请检查登录、网络、默认收货地址或页面变化，再重新开始；不会重试不确定的拍单")
        finally:
            if store:
                store.close()
            if isinstance(adapter, BrowserAdapter):
                try:
                    adapter.close()
                except Exception:
                    pass

    def _wait(self, seconds, adapter):
        deadline = time.monotonic() + seconds
        while not self.stop_event.is_set() and time.monotonic() < deadline:
            if isinstance(adapter, BrowserAdapter):
                adapter.pump(100)
            else:
                self.stop_event.wait(min(0.1, max(0, deadline - time.monotonic())))


STYLE = """
QWidget { background: #010102; color: #f7f8f8; font-family: 'Microsoft YaHei UI', 'PingFang SC', 'Segoe UI'; font-size: 13px; }
QFrame#card { background: #0f1011; border: 1px solid #23252a; border-radius: 12px; }
QFrame#card QLabel, QFrame#card QCheckBox { background: transparent; border: none; }
QLabel#title { font-size: 28px; font-weight: 600; }
QLabel#muted { color: #8a8f98; }
QLabel#section { font-size: 16px; font-weight: 600; }
QLabel#metric { font-size: 28px; font-weight: 600; }
QLabel#badge { background: #18191a; border: 1px solid #34343a; border-radius: 6px; padding: 8px 12px; color: #d0d6e0; }
QLineEdit, QDoubleSpinBox, QTimeEdit, QComboBox { background: #141516; border: 1px solid #34343a; border-radius: 8px; padding: 9px; min-height: 22px; selection-background-color: #5e6ad2; }
QLineEdit:focus, QDoubleSpinBox:focus, QComboBox:focus { border: 1px solid #5e6ad2; }
QPushButton { background: #18191a; border: 1px solid #34343a; border-radius: 8px; padding: 10px 14px; min-height: 20px; }
QPushButton:hover { background: #23252a; }
QPushButton#primary { background: #5e6ad2; color: white; border: none; }
QPushButton#primary:hover { background: #828fff; }
QPushButton:disabled, QLineEdit:disabled, QComboBox:disabled { color: #62666d; }
QCheckBox { spacing: 8px; padding: 4px 0; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #62666d; border-radius: 4px; }
QCheckBox::indicator:checked { background: #5e6ad2; border-color: #828fff; }
QTableWidget { background: #0f1011; alternate-background-color: #141516; border: none; gridline-color: #23252a; selection-background-color: #23252a; }
QHeaderView::section { background: #141516; color: #8a8f98; border: none; padding: 10px; }
QTableWidget::item { padding: 8px; }
QPlainTextEdit { background: #0f1011; color: #d0d6e0; border: none; font-size: 12px; }
QScrollBar:vertical { background: #0f1011; width: 9px; }
QScrollBar::handle:vertical { background: #34343a; border-radius: 4px; min-height: 24px; }
QToolTip { background: #191a1b; color: #f7f8f8; border: 1px solid #34343a; }
"""


def label(text, name="", wrap=False):
    widget = QLabel(text)
    widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def card():
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(20, 20, 20, 20)
    layout.setSpacing(14)
    return frame, layout


class Window(QMainWindow):
    def __init__(self, directory=None):
        super().__init__()
        self.directory = directory or data_dir()
        self.worker = None
        self.rows = []
        self.setWindowTitle("闲鱼上新监控")
        self.resize(1220, 870)
        self.setMinimumSize(1040, 780)
        self.setStyleSheet(STYLE)
        self.logger = logging.getLogger(f"monitor.{self.directory}")
        self.logger.setLevel(logging.INFO)
        if not self.logger.handlers:
            handler = RotatingFileHandler(self.directory / "activity.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
            self.logger.addHandler(handler)
        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(28, 24, 28, 24)
        main.setSpacing(20)
        header = QHBoxLayout()
        names = QVBoxLayout()
        names.addWidget(label("闲鱼上新监控", "title"))
        names.addWidget(label("关注指定卖家 · 发现上新 · 拍下后不付款", "muted"))
        header.addLayout(names)
        header.addStretch()
        self.status = label("未启动", "badge")
        self.status.setFixedHeight(38)
        header.addWidget(self.status)
        main.addLayout(header)

        metrics = QHBoxLayout()
        self.metric_labels = []
        for heading, value in [("监控轮次", "0"), ("卖家商品数", "—"), ("本轮耗时", "—"), ("已拍下 / 当前列表", "0")]:
            panel, layout = card()
            layout.addWidget(label(heading, "muted"))
            number = label(value, "metric")
            layout.addWidget(number)
            self.metric_labels.append(number)
            metrics.addWidget(panel)
        main.addLayout(metrics)

        body = QHBoxLayout()
        body.setSpacing(20)
        settings_card, settings_layout = card()
        settings_card.setFixedWidth(326)
        settings_layout.addWidget(label("监控设置", "section"))
        settings_body = QWidget()
        settings_body.setStyleSheet("background: #0f1011;")
        form = QVBoxLayout(settings_body)
        form.setContentsMargins(0, 0, 6, 0)
        form.setSpacing(10)
        self.seller = QLineEdit("2141274515")
        self.seller.setPlaceholderText("粘贴卖家分享文字或主页链接")
        self.seller.setToolTip("支持闲鱼复制的整段卖家分享文字；当前预填来自云南小木郎的分享链接")
        form.addWidget(label("卖家主页 / ID", "muted"))
        form.addWidget(self.seller)
        self.interval = QDoubleSpinBox()
        self.interval.setRange(1, 86400)
        self.interval.setDecimals(1)
        self.interval.setSuffix(" 秒")
        self.interval.setValue(5)
        form.addWidget(label("检查间隔", "muted"))
        form.addWidget(self.interval)
        form.addWidget(label("最短 1 秒。单轮超时不会叠加请求。", "muted", True))
        self.mode = QComboBox()
        self.mode.addItems(["仅监控上新", "自动拍下，不付款"])
        form.addWidget(label("发现上新后", "muted"))
        form.addWidget(self.mode)
        self.scheduled = QCheckBox("只在指定时段监控")
        form.addWidget(self.scheduled)
        time_row = QHBoxLayout()
        self.start_time, self.end_time = QTimeEdit(QTime(9, 0)), QTimeEdit(QTime(23, 0))
        for field in (self.start_time, self.end_time):
            field.setDisplayFormat("HH:mm")
        time_row.addWidget(self.start_time)
        time_row.addWidget(label("至", "muted"))
        time_row.addWidget(self.end_time)
        form.addLayout(time_row)
        form.addWidget(label("使用电脑本地时间，支持跨午夜。", "muted"))
        self.browser = QComboBox()
        self.browser.addItems(["Microsoft Edge", "Google Chrome"])
        form.addWidget(self.browser)
        form.addStretch()
        scroll = QScrollArea()
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidgetResizable(True)
        scroll.setWidget(settings_body)
        settings_layout.addWidget(scroll, 1)
        form = settings_layout
        self.login = QPushButton("① 打开闲鱼，扫码登录")
        self.login.clicked.connect(self.login_clicked)
        form.addWidget(self.login)
        self.start_button = QPushButton("② 开始监控")
        self.start_button.setObjectName("primary")
        self.start_button.clicked.connect(lambda: self.begin("monitor"))
        self.stop_button = QPushButton("停止监控")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        controls = QHBoxLayout()
        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        form.addLayout(controls)
        self.demo = QPushButton("运行演示")
        self.demo.clicked.connect(lambda: self.begin("demo"))
        form.addWidget(self.demo)
        body.addWidget(settings_card)

        right = QVBoxLayout()
        records, layout = card()
        top = QHBoxLayout()
        top.addWidget(label("上新与拍单记录", "section"))
        top.addStretch()
        self.open_button = QPushButton("打开选中商品")
        self.open_button.clicked.connect(self.open_item)
        top.addWidget(self.open_button)
        layout.addLayout(top)
        self.empty = label("开始后先记录已有商品，之后发现的上新会显示在这里。", "muted", True)
        layout.addWidget(self.empty)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["商品", "状态", "订单号", "时间"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for index in range(1, 4):
            self.table.horizontalHeader().setSectionResizeMode(index, QHeaderView.ResizeToContents)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        layout.addWidget(self.table)
        right.addWidget(records, 3)
        logs, layout = card()
        log_header = QHBoxLayout()
        log_header.addWidget(label("运行日志", "section"))
        log_header.addStretch()
        folder = QPushButton("数据目录")
        folder.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.directory))))
        log_header.addWidget(folder)
        layout.addLayout(log_header)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1500)
        layout.addWidget(self.log)
        right.addWidget(logs, 2)
        body.addLayout(right, 1)
        main.addLayout(body, 1)
        main.addWidget(label("每次启动先建立基线；下单结果不明时暂停，避免重复拍单。真实交易流程需登录后验证。", "muted", True))
        self.fields = [self.seller, self.interval, self.mode, self.scheduled, self.start_time, self.end_time, self.browser]
        self.load_settings()
        store = Store(self.directory / "monitor.sqlite3")
        self.render_rows(store.rows())
        store.close()
        self.receive("log", "已就绪。先扫码登录并设置默认收货地址；可先用“仅监控上新”验证卖家列表。")

    def load_settings(self):
        path = self.directory / "settings.json"
        if not path.exists():
            return
        try:
            settings = Settings(**json.loads(path.read_text(encoding="utf-8")))
            self.seller.setText(settings.seller)
            self.interval.setValue(settings.interval)
            self.mode.setCurrentIndex(int(settings.auto_order))
            self.scheduled.setChecked(settings.scheduled)
            self.start_time.setTime(QTime.fromString(settings.start, "HH:mm"))
            self.end_time.setTime(QTime.fromString(settings.end, "HH:mm"))
            self.browser.setCurrentIndex(int(settings.browser == "chrome"))
        except (TypeError, ValueError):
            self.receive("log", "配置文件无法读取，使用默认设置；原文件保留")

    def settings(self):
        return Settings(self.seller.text().strip(), self.interval.value(), self.mode.currentIndex() == 1,
                        self.scheduled.isChecked(), self.start_time.time().toString("HH:mm"),
                        self.end_time.time().toString("HH:mm"), "msedge" if self.browser.currentIndex() == 0 else "chrome")

    def login_clicked(self):
        if self.worker and self.worker.isRunning():
            self.stop()
        else:
            self.begin("login")

    def begin(self, mode):
        if self.worker and self.worker.isRunning():
            return
        settings = self.settings()
        if mode == "monitor" and not settings.seller:
            QMessageBox.information(self, "填写卖家", "请先粘贴卖家主页、分享文字或数字 ID")
            return
        if mode == "demo":
            self.render_rows([])
        for field in self.fields:
            field.setEnabled(False)
        self.start_button.setEnabled(False)
        self.demo.setEnabled(False)
        self.login.setEnabled(mode == "login")
        self.login.setText("完成登录" if mode == "login" else "① 打开闲鱼，扫码登录")
        self.stop_button.setEnabled(True)
        self.metric_labels[0].setText("0")
        self.worker = Worker(settings, self.directory, mode)
        self.worker.event.connect(self.receive)
        self.worker.finished.connect(self.finished)
        self.worker.start()

    def stop(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.status.setText("正在停止")
            self.stop_button.setEnabled(False)
            self.login.setEnabled(False)

    def finished(self):
        for field in self.fields:
            field.setEnabled(True)
        self.start_button.setEnabled(True)
        self.demo.setEnabled(True)
        self.login.setEnabled(True)
        self.login.setText("① 打开闲鱼，扫码登录")
        self.stop_button.setEnabled(False)

    def receive(self, kind, value):
        if kind == "state":
            self.status.setText(value)
        elif kind == "seller":
            self.seller.setText(value)
        elif kind == "log":
            self.log.appendPlainText(f"{datetime.now():%H:%M:%S}  {value}")
            self.logger.info(value)
        elif kind == "rows":
            self.render_rows(value)
        elif kind == "cycle":
            self.metric_labels[0].setText(str(value["cycles"]))
            self.metric_labels[1].setText(str(value["items"]))
        elif kind == "elapsed":
            self.metric_labels[2].setText(f"{value:.1f} s")

    def render_rows(self, rows):
        self.rows = rows
        self.table.setRowCount(len(rows))
        self.empty.setVisible(not rows)
        statuses = {"detected": "发现上新", "attempting": "结果待核对", "attention": "需要核对", "ordered": "已拍下 · 未付款"}
        for index, row in enumerate(rows):
            status = statuses.get(row["status"], row["status"])
            if row["order_id"].startswith("DEMO-"):
                status = "演示 · 模拟拍下"
            for column, text in enumerate([row["title"], status, row["order_id"] or "—", row["updated"][11:]]):
                cell = QTableWidgetItem(text)
                cell.setToolTip(f"{row['updated']}\n卖家 {row['seller']} · 商品 {row['id']}\n{row['note']}")
                self.table.setItem(index, column, cell)
        self.metric_labels[3].setText(str(sum(row["status"] == "ordered" for row in rows)))

    def open_item(self):
        index = self.table.currentRow()
        if index >= 0 and not self.rows[index]["title"].startswith("演示 ·"):
            QDesktopServices.openUrl(QUrl(f"https://www.goofish.com/item?id={self.rows[index]['id']}"))

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            self.stop()
            self.receive("log", "正在停止任务；等待当前请求结束后即可关闭窗口")
            event.ignore()
        else:
            event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("闲鱼上新监控")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    directory = data_dir()
    lock = QLockFile(str(directory / "app.lock"))
    if not lock.tryLock(100):
        QMessageBox.information(None, "软件已运行", "请使用已打开的监控窗口，避免重复任务")
        return 1
    window = Window(directory)
    window.show()
    return app.exec()
