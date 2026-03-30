import sys
import os
import subprocess
import psutil
import markdown
from pygments import highlight
from pygments.lexers import get_lexer_by_name
from pygments.formatters import HtmlFormatter
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QTreeWidget, QTreeWidgetItem, QTabWidget,
                             QMessageBox, QComboBox, QHeaderView, QMenu, QProgressBar, QSpinBox, 
                             QGroupBox, QProgressDialog, QDialog, QLineEdit, QFormLayout, QTextBrowser, QSplitter)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from scanner import format_size
from worker import ScanWorker, CleanWorker, RestoreWorker, DirectoryAnalysisWorker
from registry import RegistryManager
from ai_engine import AIEngine
import uuid
import datetime

import json

CACHE_FILE = "analysis_cache.json"

class SettingsDialog(QDialog):
    def __init__(self, ai_engine, parent=None):
        super().__init__(parent)
        self.ai_engine = ai_engine
        self.setWindowTitle("软件设置")
        self.setMinimumWidth(400)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["DeepSeek", "OpenAI (Compatible)"])
        self.provider_combo.setCurrentText(self.ai_engine.settings.get("provider", "DeepSeek"))

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setText(self.ai_engine.settings.get("api_key", ""))

        self.base_url_edit = QLineEdit()
        self.base_url_edit.setText(self.ai_engine.settings.get("base_url", "https://api.deepseek.com"))

        self.model_edit = QLineEdit()
        self.model_edit.setText(self.ai_engine.settings.get("model", "deepseek-chat"))

        form.addRow("AI 提供商:", self.provider_combo)
        form.addRow("API Key:", self.api_key_edit)
        form.addRow("Base URL:", self.base_url_edit)
        form.addRow("模型名称:", self.model_edit)

        layout.addLayout(form)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self.save_settings)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def save_settings(self):
        new_settings = {
            "provider": self.provider_combo.currentText(),
            "api_key": self.api_key_edit.text(),
            "base_url": self.base_url_edit.text(),
            "model": self.model_edit.text()
        }
        self.ai_engine.save_settings(new_settings)
        self.accept()

class AIChatWorker(QThread):
    finished = pyqtSignal(str)

    def __init__(self, ai_engine, message, current_path=None):
        super().__init__()
        self.ai_engine = ai_engine
        self.message = message
        self.current_path = current_path

    def run(self):
        response = self.ai_engine.chat(self.message, current_path=self.current_path)
        self.finished.emit(response)

class AIAnalysisWorker(QThread):
    finished = pyqtSignal(str)

    def __init__(self, ai_engine, top_items):
        super().__init__()
        self.ai_engine = ai_engine
        self.top_items = top_items

    def run(self):
        response = self.ai_engine.analyze_folders(self.top_items)
        self.finished.emit(response)

class CleanerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("C盘空间清理与 AI 分析 Agent")
        self.resize(1200, 700)
        self.registry = RegistryManager()
        self.ai_engine = AIEngine()
        
        self.init_ui()

    def init_ui(self):
        # 主布局使用 QSplitter，左侧为功能 Tab，右侧为 AI 聊天
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QHBoxLayout(main_widget)
        
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # 左侧 Tab 区域
        self.tabs = QTabWidget()
        
        # Tab 1: 扫描与清理
        self.tab_scan = QWidget()
        self.init_scan_tab()
        self.tabs.addTab(self.tab_scan, "扫描与清理")
        
        # Tab 2: 恢复中心
        self.tab_restore = QWidget()
        self.init_restore_tab()
        self.tabs.addTab(self.tab_restore, "恢复中心 (D盘)")
        
        # Tab 3: 空间分析
        self.tab_analysis = QWidget()
        self.init_analysis_tab()
        self.tabs.addTab(self.tab_analysis, "空间分析")
        
        self.tabs.currentChanged.connect(self.on_tab_changed)
        
        self.splitter.addWidget(self.tabs)
        
        # 右侧 AI 聊天区域
        self.init_ai_chat_panel()
        self.splitter.addWidget(self.ai_chat_panel)
        self.splitter.setSizes([800, 400]) # 默认比例
        
        main_layout.addWidget(self.splitter)

        # 菜单栏增加设置
        menubar = self.menuBar()
        settings_menu = menubar.addMenu("选项")
        settings_action = settings_menu.addAction("软件设置")
        settings_action.triggered.connect(self.show_settings)

    def init_ai_chat_panel(self):
        self.ai_chat_panel = QGroupBox("AI 清理 Agent")
        layout = QVBoxLayout(self.ai_chat_panel)

        self.chat_display = QTextBrowser()
        self.chat_display.setOpenExternalLinks(True)
        # 设置 CSS 样式，使表格和代码块更美观
        self.chat_display.setHtml(self.get_initial_html())
        layout.addWidget(self.chat_display)

        input_layout = QHBoxLayout()
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("输入问题...")
        self.chat_input.returnPressed.connect(self.send_chat_message)
        self.btn_send = QPushButton("发送")
        self.btn_send.clicked.connect(self.send_chat_message)
        
        input_layout.addWidget(self.chat_input)
        input_layout.addWidget(self.btn_send)
        layout.addLayout(input_layout)

    def get_initial_html(self):
        style = """
            <style>
                body { 
                    font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif; 
                    font-size: 14px; 
                    line-height: 1.6; 
                    color: #333; 
                    background-color: #f4f5f7; 
                    padding: 10px; 
                    margin: 0;
                }
                .content-table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 13px; }
                .content-table th, .content-table td { border: 1px solid #ddd; padding: 8px; text-align: left; background-color: #fff; }
                .content-table th { background-color: #f2f2f2; font-weight: bold; }
                code { background-color: #f0f0f0; padding: 2px 4px; border-radius: 3px; font-family: Consolas, monospace; color: #c7254e; font-size: 13px; }
                pre { background-color: #f8f8f8; padding: 10px; border-radius: 5px; overflow-x: auto; border: 1px solid #ccc; font-size: 13px; }
                p { margin-top: 0; margin-bottom: 10px; }
                p:last-child { margin-bottom: 0; }
                ul, ol { margin-top: 0; margin-bottom: 10px; padding-left: 20px; }
                li { margin-bottom: 4px; }
            </style>
        """
        return f"<html><head>{style}</head><body><div id='content'></div></body></html>"

    def append_to_chat(self, role, text):
        # 转换为 Markdown
        md = markdown.Markdown(extensions=['tables', 'fenced_code', 'codehilite'])
        html_content = md.convert(text)
        # 将 markdown 生成的 table 替换为带样式的 class
        html_content = html_content.replace("<table>", "<table class='content-table'>")
        
        if role == "你":
            msg_html = f"""
            <table width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-bottom: 15px;">
                <tr>
                    <td width="15%"></td>
                    <td width="85%" align="right">
                        <div style="color: #1976D2; font-size: 12px; margin-bottom: 4px; margin-right: 5px;">{role}</div>
                        <div style="background-color: #DCF8C6; padding: 10px 15px; border-radius: 8px; text-align: left; display: inline-block; border: 1px solid #c5e1a5;">
                            {html_content}
                        </div>
                    </td>
                </tr>
            </table>
            """
        else:
            msg_html = f"""
            <table width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-bottom: 15px;">
                <tr>
                    <td width="85%" align="left">
                        <div style="color: #388E3C; font-size: 12px; margin-bottom: 4px; margin-left: 5px;">{role}</div>
                        <div style="background-color: #FFFFFF; padding: 10px 15px; border-radius: 8px; text-align: left; display: inline-block; border: 1px solid #e0e0e0;">
                            {html_content}
                        </div>
                    </td>
                    <td width="15%"></td>
                </tr>
            </table>
            """
        
        # 获取当前 HTML 并插入新消息
        current_html = self.chat_display.toHtml()
        if "</div></body>" in current_html:
            new_html = current_html.replace("</div></body>", f"{msg_html}</div></body>")
        else:
            # 兜底处理
            new_html = current_html.replace("</body>", f"{msg_html}</body>")
            
        self.chat_display.setHtml(new_html)
        # 滚动到底部
        self.chat_display.verticalScrollBar().setValue(self.chat_display.verticalScrollBar().maximum())

    def show_settings(self):
        dialog = SettingsDialog(self.ai_engine, self)
        dialog.exec()

    def send_chat_message(self):
        msg = self.chat_input.text().strip()
        if not msg:
            return
            
        self.append_to_chat("你", msg)
        self.chat_input.clear()
        
        # 禁用输入框和按钮，防止重复发送
        self.chat_input.setEnabled(False)
        self.btn_send.setEnabled(False)
        self.btn_send.setText("处理中...")
        
        # 获取用户当前所在的目录路径
        current_path = getattr(self, 'current_analysis_path', 'C:\\')
        
        # 使用线程调用 AI
        self.chat_worker = AIChatWorker(self.ai_engine, msg, current_path)
        self.chat_worker.finished.connect(self.on_chat_finished)
        self.chat_worker.start()

    def on_chat_finished(self, response):
        self.append_to_chat("AI", response)
        self.chat_input.setEnabled(True)
        self.btn_send.setEnabled(True)
        self.btn_send.setText("发送")
        self.chat_input.setFocus()

    def init_analysis_tab(self):
        layout = QVBoxLayout(self.tab_analysis)
        
        # 顶部控制区
        top_layout = QHBoxLayout()
        self.lbl_current_dir = QLabel("当前分析目录: C:\\")
        self.lbl_current_dir.setStyleSheet("font-weight: bold; font-size: 14px;")
        
        self.btn_ai_analyze = QPushButton("✨ AI 一键分析当前目录")
        self.btn_ai_analyze.setStyleSheet("background-color: #e1f5fe; font-weight: bold;")
        self.btn_ai_analyze.clicked.connect(self.run_ai_folder_analysis)

        self.btn_up_dir = QPushButton("返回上一级")
        self.btn_up_dir.clicked.connect(self.analysis_go_up)
        
        self.btn_refresh_analysis = QPushButton("重新扫描此目录")
        self.btn_refresh_analysis.clicked.connect(self.force_refresh_analysis)
        
        self.btn_clear_cache = QPushButton("清空全局缓存")
        self.btn_clear_cache.setStyleSheet("color: red;")
        self.btn_clear_cache.clicked.connect(self.clear_global_cache)
        
        top_layout.addWidget(self.lbl_current_dir)
        top_layout.addStretch()
        top_layout.addWidget(self.btn_ai_analyze)
        top_layout.addWidget(self.btn_up_dir)
        top_layout.addWidget(self.btn_refresh_analysis)
        top_layout.addWidget(self.btn_clear_cache)
        
        layout.addLayout(top_layout)
        
        # 分析结果列表
        self.tree_analysis = QTreeWidget()
        self.tree_analysis.setHeaderLabels(["名称", "大小", "类型", "路径", "最后修改时间"])
        self.tree_analysis.setColumnWidth(0, 200)
        self.tree_analysis.setColumnWidth(1, 100)
        self.tree_analysis.setColumnWidth(2, 80)
        self.tree_analysis.setColumnWidth(3, 300)
        self.tree_analysis.setColumnWidth(4, 150)
        self.tree_analysis.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree_analysis.customContextMenuRequested.connect(self.show_analysis_context_menu)
        
        layout.addWidget(self.tree_analysis)
        
        self.current_analysis_path = "C:\\"
        self.analysis_results_cache = {}
        self.global_dir_cache = self.load_global_cache()

    def run_ai_folder_analysis(self):
        # 获取当前目录下排名前 10 的大项
        root = self.tree_analysis.invisibleRootItem()
        items_info = []
        for i in range(root.childCount()):
            item = root.child(i)
            items_info.append({
                "name": item.text(0),
                "size": item.text(1),
                "path": item.text(3),
                "mtime": item.text(4),
                "size_val": item.data(1, Qt.ItemDataRole.UserRole) # 原始字节大小
            })
        
        if not items_info:
            QMessageBox.warning(self, "提示", "当前目录没有可分析的内容。")
            return

        # 按大小排序并取前 10
        items_info.sort(key=lambda x: x["size_val"] if x["size_val"] else 0, reverse=True)
        top_items = items_info[:10]

        self.append_to_chat("系统", f"正在分析当前目录: `{self.current_analysis_path}`，请稍候...")
        self.tabs.setCurrentIndex(2) # 切换到分析 Tab
        
        self.btn_ai_analyze.setEnabled(False)
        self.btn_ai_analyze.setText("✨ AI 分析中...")
        
        # 异步调用 AI 分析
        self.analysis_worker = AIAnalysisWorker(self.ai_engine, top_items)
        self.analysis_worker.finished.connect(self.on_ai_analysis_finished)
        self.analysis_worker.start()

    def on_ai_analysis_finished(self, analysis_result):
        self.append_to_chat("AI 目录分析结果", f"### 目录分析: {self.current_analysis_path}\n\n{analysis_result}")
        self.btn_ai_analyze.setEnabled(True)
        self.btn_ai_analyze.setText("✨ AI 一键分析当前目录")


    def load_global_cache(self):
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_global_cache(self):
        try:
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.global_dir_cache, f, ensure_ascii=False)
        except Exception as e:
            print(f"保存缓存失败: {e}")

    def clear_global_cache(self):
        reply = QMessageBox.question(self, "确认", "确定要清空所有空间的扫描缓存吗？\n清空后下次查看将重新进行完整的耗时计算。",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.global_dir_cache = {}
            self.analysis_results_cache = {}
            if os.path.exists(CACHE_FILE):
                try:
                    os.remove(CACHE_FILE)
                except Exception:
                    pass
            self.tree_analysis.clear()
            QMessageBox.information(self, "成功", "全局缓存已清空。")

    def analysis_go_up(self):
        parent_dir = os.path.dirname(self.current_analysis_path)
        if parent_dir and parent_dir != self.current_analysis_path:
            self.load_analysis(parent_dir)

    def show_analysis_context_menu(self, position):
        item = self.tree_analysis.itemAt(position)
        if not item:
            return
            
        path = item.text(3)
        item_type = item.text(2)
        
        menu = QMenu()
        
        action_open = menu.addAction("打开所在位置")
        
        action_analyze = None
        if item_type == "文件夹":
            action_analyze = menu.addAction("进一步分析此目录")
            
        action = menu.exec(self.tree_analysis.viewport().mapToGlobal(position))
        
        if action == action_open:
            self.open_file_location(path)
        elif action_analyze and action == action_analyze:
            self.load_analysis(path)

    def force_refresh_analysis(self):
        self.load_analysis(self.current_analysis_path, force=True)

    def load_analysis(self, path=None, force=False):
        if path is None:
            path = self.current_analysis_path
        
        # 规范化路径
        path = os.path.abspath(path)
        self.current_analysis_path = path
        self.lbl_current_dir.setText(f"当前分析目录: {self.current_analysis_path}")
        
        if not force and hasattr(self, 'analysis_results_cache') and path in self.analysis_results_cache:
            self.display_analysis_results(self.analysis_results_cache[path])
            return
            
        self.tree_analysis.clear()
        
        msg = f"正在分析 {self.current_analysis_path}..."
        if force:
            msg = f"正在强制刷新分析 {self.current_analysis_path}..."
            
        self.progress_dialog = QProgressDialog(msg, "取消", 0, 0, self)
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.show()
        
        if not hasattr(self, 'global_dir_cache'):
            self.global_dir_cache = {}
            
        self.analysis_worker = DirectoryAnalysisWorker(self.current_analysis_path, self.global_dir_cache, force_rescan=force)
        self.analysis_worker.finished.connect(self.on_analysis_finished)
        self.analysis_worker.start()

    def on_analysis_finished(self, results, new_cache):
        if hasattr(self, 'progress_dialog'):
            self.progress_dialog.close()
            
        self.btn_refresh_analysis.setEnabled(True)
        self.btn_up_dir.setEnabled(True)
            
        # 更新全局字典缓存
        if not hasattr(self, 'global_dir_cache'):
            self.global_dir_cache = {}
        self.global_dir_cache.update(new_cache)
        self.save_global_cache()  # 将新缓存保存到本地文件
        
        # 缓存当前目录的展示结果
        if not hasattr(self, 'analysis_results_cache'):
            self.analysis_results_cache = {}
        self.analysis_results_cache[self.current_analysis_path] = results
        
        self.display_analysis_results(results)
        self.lbl_status.setText(f"分析完成: {self.current_analysis_path}")

    def display_analysis_results(self, results):
        self.tree_analysis.clear()
        for name, path, size, is_dir, mtime in results:
            item = QTreeWidgetItem(self.tree_analysis)
            item.setText(0, name)
            item.setText(1, format_size(size))
            item.setText(2, "文件夹" if is_dir else "文件")
            item.setText(3, path)
            item.setText(4, mtime)
            
            # 存储原始数据以便 AI 分析
            item.setData(1, Qt.ItemDataRole.UserRole, size)
            
            # 为文件夹设置不同的图标或颜色以便区分
            if is_dir:
                item.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_DirIcon))
                font = item.font(0)
                font.setBold(True)
                item.setFont(0, font)
            else:
                item.setIcon(0, self.style().standardIcon(self.style().StandardPixmap.SP_FileIcon))

    def init_scan_tab(self):
        layout = QVBoxLayout()
        
        # 仪表盘区域
        dashboard_group = QGroupBox("C盘状态仪表盘")
        dashboard_layout = QVBoxLayout()
        
        # 容量进度条
        self.disk_progress = QProgressBar()
        self.disk_progress.setTextVisible(True)
        self.disk_progress.setMinimumHeight(25)
        self.lbl_disk_info = QLabel("读取磁盘信息中...")
        
        disk_info_layout = QHBoxLayout()
        disk_info_layout.addWidget(self.lbl_disk_info)
        
        dashboard_layout.addLayout(disk_info_layout)
        dashboard_layout.addWidget(self.disk_progress)
        
        # 扫描选项与按钮
        scan_options_layout = QHBoxLayout()
        
        lbl_threshold = QLabel("大文件自定义阈值 (MB):")
        self.spin_threshold = QSpinBox()
        self.spin_threshold.setRange(50, 5000)
        self.spin_threshold.setValue(500)
        self.spin_threshold.setSingleStep(50)
        
        self.btn_scan = QPushButton("一键扫描 C 盘")
        self.btn_scan.setMinimumHeight(45)
        self.btn_scan.setStyleSheet("font-size: 16px; font-weight: bold; background-color: #4CAF50; color: white;")
        self.btn_scan.clicked.connect(self.start_scan)
        
        self.lbl_status = QLabel("就绪")
        
        scan_options_layout.addWidget(lbl_threshold)
        scan_options_layout.addWidget(self.spin_threshold)
        scan_options_layout.addSpacing(20)
        scan_options_layout.addWidget(self.btn_scan, stretch=1)
        scan_options_layout.addSpacing(20)
        scan_options_layout.addWidget(self.lbl_status)
        
        dashboard_layout.addLayout(scan_options_layout)
        dashboard_group.setLayout(dashboard_layout)
        
        layout.addWidget(dashboard_group)
        
        self.update_dashboard()
        
        # 树状列表
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["项目名称", "大小", "路径", "操作 (勾选后生效)"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_scan_context_menu)
        layout.addWidget(self.tree)
        
        # 底部清理按钮
        bottom_layout = QHBoxLayout()
        self.btn_clean = QPushButton("执行选中项的操作")
        self.btn_clean.setMinimumHeight(40)
        self.btn_clean.clicked.connect(self.execute_clean)
        self.btn_clean.setEnabled(False)
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_clean)
        layout.addLayout(bottom_layout)
        
        self.tab_scan.setLayout(layout)

    def init_restore_tab(self):
        layout = QVBoxLayout()
        
        self.restore_tree = QTreeWidget()
        self.restore_tree.setHeaderLabels(["原路径", "D盘备份路径", "大小", "移动时间"])
        self.restore_tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.restore_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.restore_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.restore_tree.customContextMenuRequested.connect(self.show_restore_context_menu)
        layout.addWidget(self.restore_tree)
        
        btn_layout = QHBoxLayout()
        self.btn_refresh_restore = QPushButton("刷新列表")
        self.btn_refresh_restore.clicked.connect(self.load_registry_data)
        
        self.btn_do_restore = QPushButton("还原选中的项目至 C 盘")
        self.btn_do_restore.clicked.connect(self.execute_restore)
        
        btn_layout.addWidget(self.btn_refresh_restore)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_do_restore)
        layout.addLayout(btn_layout)
        
        self.tab_restore.setLayout(layout)

    def update_dashboard(self):
        try:
            usage = psutil.disk_usage('C:\\')
            total = format_size(usage.total)
            used = format_size(usage.used)
            free = format_size(usage.free)
            percent = usage.percent
            
            self.lbl_disk_info.setText(f"总容量: {total} | 已用: {used} | 可用: {free}")
            self.disk_progress.setValue(int(percent))
            
            if percent > 90:
                self.disk_progress.setStyleSheet("QProgressBar::chunk { background-color: #f44336; }")
            elif percent > 75:
                self.disk_progress.setStyleSheet("QProgressBar::chunk { background-color: #ff9800; }")
            else:
                self.disk_progress.setStyleSheet("QProgressBar::chunk { background-color: #2196F3; }")
        except Exception as e:
            self.lbl_disk_info.setText(f"获取磁盘信息失败: {e}")

    def on_tab_changed(self, index):
        if index == 0:
            self.update_dashboard()
        elif index == 1:
            self.load_registry_data()

    def open_file_location(self, path):
        if not os.path.exists(path):
            QMessageBox.warning(self, "错误", "该路径已不存在")
            return
            
        if os.path.isdir(path):
            os.startfile(path)
        else:
            # 选中文件
            subprocess.run(['explorer', '/select,', os.path.normpath(path)])

    def show_scan_context_menu(self, position):
        item = self.tree.itemAt(position)
        if item is None:
            return
            
        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        if not item_data:  # 可能是父节点
            return
            
        menu = QMenu()
        open_action = menu.addAction("打开所在位置")
        action = menu.exec(self.tree.viewport().mapToGlobal(position))
        
        if action == open_action:
            self.open_file_location(item_data["path"])

    def show_restore_context_menu(self, position):
        item = self.restore_tree.itemAt(position)
        if item is None:
            return
            
        item_data = item.data(0, Qt.ItemDataRole.UserRole)
        if not item_data:
            return
            
        menu = QMenu()
        open_d_action = menu.addAction("打开备份所在位置(D盘)")
        action = menu.exec(self.restore_tree.viewport().mapToGlobal(position))
        
        if action == open_d_action:
            self.open_file_location(item_data["d_drive_path"])

    # --- 扫描与清理逻辑 ---
    def start_scan(self):
        self.btn_scan.setEnabled(False)
        self.btn_clean.setEnabled(False)
        self.tree.clear()
        self.update_dashboard()
        
        threshold = self.spin_threshold.value()
        self.scan_worker = ScanWorker(threshold_mb=threshold)
        self.scan_worker.progress.connect(self.update_status)
        self.scan_worker.finished.connect(self.on_scan_finished)
        self.scan_worker.start()

    def update_status(self, msg):
        self.lbl_status.setText(msg)

    def on_scan_finished(self, results):
        self.update_status("扫描完成，请勾选需要处理的项目并选择操作方式。")
        self.btn_scan.setEnabled(True)
        self.btn_clean.setEnabled(True)
        
        for cat in results:
            cat_item = QTreeWidgetItem(self.tree)
            cat_item.setText(0, cat["category"])
            cat_item.setFlags(cat_item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate)
            cat_item.setCheckState(0, Qt.CheckState.Unchecked)
            cat_item.setExpanded(True)
            
            cat_size = 0
            for item in cat["items"]:
                child = QTreeWidgetItem(cat_item)
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                # 默认勾选状态
                check_state = Qt.CheckState.Checked if item.get("checked_by_default") else Qt.CheckState.Unchecked
                child.setCheckState(0, check_state)
                
                child.setText(0, item["name"])
                child.setText(1, format_size(item["size"]))
                child.setText(2, item["path"])
                
                # 保存原始数据
                child.setData(0, Qt.ItemDataRole.UserRole, item)
                
                # 添加操作下拉框
                combo = QComboBox()
                combo.addItems(["直接删除", "移至 D 盘 (可还原)"])
                self.tree.setItemWidget(child, 3, combo)
                
                cat_size += item["size"]
            
            cat_item.setText(1, format_size(cat_size))

    def execute_clean(self):
        # 检查相关进程是否运行
        running_apps = []
        for proc in psutil.process_iter(['name']):
            try:
                name = proc.info['name'].lower()
                if "wechat" in name or "qq.exe" in name or "tim.exe" in name:
                    app_name = "微信" if "wechat" in name else "QQ/TIM"
                    if app_name not in running_apps:
                        running_apps.append(app_name)
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass

        if running_apps:
            apps_str = "、".join(running_apps)
            reply = QMessageBox.warning(self, "进程占用提示", 
                                         f"检测到 {apps_str} 正在运行，这可能导致部分文件无法清理（拒绝访问）。\n\n建议关闭后再继续，是否仍要尝试清理？",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.No:
                return

        actions = []
        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            cat_item = root.child(i)
            for j in range(cat_item.childCount()):
                child = cat_item.child(j)
                if child.checkState(0) == Qt.CheckState.Checked:
                    item_data = child.data(0, Qt.ItemDataRole.UserRole)
                    if not item_data:
                        print(f"警告: 项目 {child.text(0)} 没有 UserRole 数据")
                        continue
                        
                    combo = self.tree.itemWidget(child, 3)
                    action_text = combo.currentText()
                    
                    action_type = "delete" if "删除" in action_text else "move"
                    
                    # 确保 size 是数值
                    size_val = item_data.get("size", 0)
                    if isinstance(size_val, str):
                        try:
                            size_val = int(size_val)
                        except:
                            size_val = 0
                            
                    actions.append({
                        "id": str(uuid.uuid4())[:8],
                        "path": item_data.get("path", ""),
                        "size": size_val,
                        "action": action_type,
                        "type": item_data.get("type", "file")
                    })
        
        print(f"已收集 {len(actions)} 个清理任务")
        if not actions:
            QMessageBox.information(self, "提示", "没有选中任何要处理的项目")
            return
            
        delete_count = sum(1 for a in actions if a["action"] == "delete")
        move_count = sum(1 for a in actions if a["action"] == "move")
        
        msg = f"即将处理 {len(actions)} 个项目:\n"
        if delete_count > 0:
            msg += f"- 直接删除: {delete_count} 个 (将永久删除，不进入回收站)\n"
        if move_count > 0:
            msg += f"- 移至 D 盘: {move_count} 个\n"
        msg += "\n是否继续？"
            
        reply = QMessageBox.question(self, "确认", msg,
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.btn_clean.setEnabled(False)
            self.btn_scan.setEnabled(False)
            
            self.clean_worker = CleanWorker(actions)
            self.clean_worker.progress.connect(self.update_status)
            self.clean_worker.finished.connect(self.on_clean_finished)
            self.clean_worker.start()

    def on_clean_finished(self, processed, freed):
        QMessageBox.information(self, "完成", f"处理完毕！\n共处理 {processed} 个项目\n释放 C 盘空间: {format_size(freed)}")
        self.btn_scan.setEnabled(True)
        self.start_scan() # 重新扫描刷新列表

    # --- 恢复中心逻辑 ---
    def load_registry_data(self):
        self.restore_tree.clear()
        entries = self.registry.load_registry()
        
        for entry in entries:
            item = QTreeWidgetItem(self.restore_tree)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Unchecked)
            
            item.setText(0, entry["original_path"])
            item.setText(1, entry["d_drive_path"])
            item.setText(2, format_size(entry["size_bytes"]))
            item.setText(3, entry.get("moved_at", ""))
            
            item.setData(0, Qt.ItemDataRole.UserRole, entry)

    def execute_restore(self):
        entries_to_restore = []
        root = self.restore_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            if item.checkState(0) == Qt.CheckState.Checked:
                entries_to_restore.append(item.data(0, Qt.ItemDataRole.UserRole))
                
        if not entries_to_restore:
            QMessageBox.information(self, "提示", "请先勾选需要还原的项目")
            return
            
        reply = QMessageBox.question(self, "确认", f"即将还原 {len(entries_to_restore)} 个项目到 C 盘，是否继续？",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.btn_do_restore.setEnabled(False)
            self.lbl_status.setText("正在还原...")
            
            self.restore_worker = RestoreWorker(entries_to_restore)
            self.restore_worker.progress.connect(self.update_status)
            self.restore_worker.finished.connect(self.on_restore_finished)
            self.restore_worker.start()

    def on_restore_finished(self, restored):
        QMessageBox.information(self, "完成", f"成功还原 {restored} 个项目！")
        self.btn_do_restore.setEnabled(True)
        self.lbl_status.setText("还原完成")
        self.load_registry_data()

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = CleanerApp()
    window.show()
    sys.exit(app.exec())
