"""Windows desktop UI using the shared catalog conversion and installation core."""

from datetime import datetime
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QButtonGroup, QCheckBox, QComboBox, QDialog,
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMainWindow, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QPlainTextEdit,
    QToolButton, QMenu, QWidgetAction,
)

from glass_catalog import CatalogError, SUPPLY_STATUS_LABELS, export_catalog, load_catalog, select_glasses, transmission_at
import codev_catalog_bundle as codev
from glass_expert import installed_catalog_paths
from supplier_catalog import GRADES, enrich_glasses, load_supplier_table
import zemax_catalog_manager as zemax
from app_settings import EXPORT_ROOT, VERSION, default_settings, load_settings, save_settings


ICON_PATHS = {
    "library": '<path d="M4 4h4v16H4zM11 4h4v16h-4zM18 4l3 15-3 1-3-15z"/>',
    "settings": '<path d="M4 7h7m4 0h5M4 17h11m4 0h1"/><circle cx="13" cy="7" r="2"/><circle cx="17" cy="17" r="2"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
    "filter": '<path d="M4 6h16M7 12h10M10 18h4"/>',
    "reset": '<path d="M4 5v5h5M4.5 10a8 8 0 1 1 0 5"/>',
    "install": '<path d="M12 3v12m-4-4 4 4 4-4M4 16v4h16v-4"/>',
    "export": '<path d="M12 15V3m-4 4 4-4 4 4M4 15v6h16v-6"/>',
    "trash": '<path d="M4 6h16M9 6V3h6v3M6 6l1 15h10l1-15M10 10v7M14 10v7"/>',
    "folder": '<path d="M3 7V4h6l2 3h10v13H3z"/>',
    "shield": '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6zM8 12l3 3 5-6"/>',
    "glass": '<path d="m12 3 9 5-9 5-9-5zM3 12l9 5 9-5M3 16l9 5 9-5"/>',
}


def icon(name, color="#777983", size=18):
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           f'stroke="{color}" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">'
           + ICON_PATHS[name] + '</svg>')
    ratio = QApplication.primaryScreen().devicePixelRatio()
    pixmap = QPixmap(round(size * ratio), round(size * ratio))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(svg.encode()).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return QIcon(pixmap)


def label(text, role=""):
    widget = QLabel(text)
    widget.setProperty("role", role)
    return widget


def button(text, callback=None, role="", glyph=None):
    widget = QPushButton(text)
    widget.setProperty("role", role)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if glyph:
        widget.setIcon(icon(glyph, "#FFFFFF" if role == "primary" else "#777983"))
        widget.setIconSize(QSize(17, 17))
    if callback:
        widget.clicked.connect(callback)
    return widget


class MultiSelector(QToolButton):
    def __init__(self, title, choices):
        super().__init__()
        self.title = title
        self.available = set(choices)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self)
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        layout.addWidget(label(title + " · 可多选，不选则不限", "muted"))
        self.checks = {}
        for value, text in choices.items():
            choice = QCheckBox(text)
            choice.setToolTip(str(value))
            choice.toggled.connect(self.update_text)
            self.checks[value] = choice
            layout.addWidget(choice)
        layout.addWidget(button("不限" + title, self.clear_selection, "text"))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(panel)
        self.scroll.setFixedWidth(320)
        action = QWidgetAction(menu)
        action.setDefaultWidget(self.scroll)
        menu.addAction(action)
        self.setMenu(menu)
        self.set_available(set(choices))

    def values(self):
        return [value for value, choice in self.checks.items() if value in self.available and choice.isChecked()] or None

    def set_available(self, values):
        self.available = set(values)
        for value, choice in self.checks.items():
            choice.setVisible(value in self.available)
        self.scroll.setFixedHeight(min(360, 85 + 32 * len(self.available)))
        self.update_text()

    def update_text(self):
        selected = [choice.text() for value, choice in self.checks.items() if value in self.available and choice.isChecked()]
        self.setText(self.title + " · " + (selected[0] if len(selected) == 1 else f"已选 {len(selected)} 项") if selected else self.title + " · 不限")

    def clear_selection(self):
        for choice in self.checks.values():
            choice.setChecked(False)


class GlassCatalogWindow(QMainWindow):
    def __init__(self, *, settings=None, persist_settings=True):
        super().__init__()
        self.preferences = load_settings() if settings is None else {**default_settings(), **settings}
        self.persist_settings = persist_settings
        self.last_notice = None
        self.codev_catalogs = []
        self.zemax_catalogs = []
        self.catalogs = []
        self.expert_catalogs = []
        self.dat_mode = False
        self.supplier_reference = None
        self.filtered = []
        self.active_filters = {}
        self.last_bundle = None
        self.name_suggestion = ""
        self.output_names = {False: ("", ""), True: ("", "")}
        self.setWindowTitle(f"玻璃库管理 · Zemax / CODE V · {VERSION}")
        self.setWindowIcon(QIcon(str(Path(__file__).resolve().parent / "assets/app.ico")))
        self.resize(1180, 800)
        self.setMinimumSize(1000, 650)
        stylesheet = Path(__file__).with_suffix(".qss").read_text(encoding="utf-8")
        self.setStyleSheet(stylesheet.replace("@ASSETS@", (Path(__file__).resolve().parent / "assets").as_posix()))

        shell = QWidget()
        self.setCentralWidget(shell)
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        shell_layout.addWidget(sidebar)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(14, 26, 14, 20)
        side.setSpacing(6)
        brand = QHBoxLayout()
        brand.setContentsMargins(10, 0, 4, 0)
        brand.setSpacing(11)
        mark = QLabel()
        mark.setPixmap(self.windowIcon().pixmap(QSize(34, 34)))
        brand.addWidget(mark)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(3)
        brand_text.addWidget(label("玻璃库", "brand"))
        brand_text.addWidget(label("Zemax / CODE V", "caption"))
        brand.addLayout(brand_text)
        brand.addStretch()
        side.addLayout(brand)
        side.addSpacing(26)
        self.add_button = button("添加玻璃库", self.add_files, glyph="plus")
        side.addWidget(self.add_button)
        side.addSpacing(22)
        caption = label("工作区", "caption")
        caption.setContentsMargins(12, 0, 0, 5)
        side.addWidget(caption)
        self.nav_buttons = {}
        navigation = QButtonGroup(self)
        for key, text, glyph, hint in (
            ("browse", "玻璃库与筛选", "library", "查看材料、设置筛选条件"),
            ("settings", "导出设置", "settings", "选择输出格式、设置安装目录"),
            ("codev", "CODE V 库管理", "folder", "查看、载入、安装与卸载 CODE V XML 库"),
            ("zemax", "Zemax 库管理", "folder", "查看、安装、备份与卸载 Zemax AGF 库"),
        ):
            if key == "codev":
                side.addSpacing(18)
                caption = label("玻璃库管理", "caption")
                caption.setContentsMargins(12, 0, 0, 5)
                side.addWidget(caption)
            nav = button(text, lambda checked=False, page=key: self.show_page(page), "nav", glyph)
            nav.setCheckable(True)
            nav.setToolTip(hint)
            navigation.addButton(nav)
            side.addWidget(nav)
            self.nav_buttons[key] = nav
        self.library_summary = label("尚未导入玻璃库", "muted")
        self.library_summary.setContentsMargins(14, 14, 0, 0)
        side.addWidget(self.library_summary)
        side.addStretch()
        footer_note = label(f"AGF  /  XML  /  DAT   ·   {VERSION}", "caption")
        footer_note.setContentsMargins(12, 0, 0, 0)
        side.addWidget(footer_note)

        workspace = QWidget()
        workspace.setObjectName("workspace")
        shell_layout.addWidget(workspace, 1)
        main = QVBoxLayout(workspace)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 14)
        content_layout.setSpacing(12)
        main.addWidget(content, 1)
        header = QHBoxLayout()
        headings = QVBoxLayout()
        headings.setSpacing(7)
        self.page_title = label("", "title")
        self.page_description = label("", "description")
        headings.addWidget(self.page_title)
        headings.addWidget(self.page_description)
        header.addLayout(headings, 1)
        self.clear_button = button("清空", self.clear, "text")
        header.addWidget(self.clear_button)
        self.format_badge = format_badge = label("AGF  /  XML  /  DAT", "badge")
        format_badge.setFixedHeight(26)
        header.addWidget(format_badge, alignment=Qt.AlignmentFlag.AlignVCenter)
        content_layout.addLayout(header)
        self.notice = QFrame()
        self.notice.setObjectName("notice")
        notice_layout = QVBoxLayout(self.notice)
        notice_layout.setContentsMargins(12, 9, 12, 9)
        notice_layout.setSpacing(8)
        notice_row = QHBoxLayout()
        self.notice_title = label("")
        self.notice_title.setWordWrap(True)
        notice_row.addWidget(self.notice_title, 1)
        self.notice_more = button("查看详情", role="text")
        self.notice_more.setMaximumHeight(28)
        self.notice_more.setCheckable(True)
        notice_row.addWidget(self.notice_more)
        dismiss = button("×", self.notice.hide, "text")
        dismiss.setObjectName("noticeDismiss")
        dismiss.setMaximumSize(30, 28)
        notice_row.addWidget(dismiss)
        notice_layout.addLayout(notice_row)
        self.notice_details = QPlainTextEdit()
        self.notice_details.setReadOnly(True)
        self.notice_details.setMaximumHeight(130)
        self.notice_details.hide()
        self.notice_more.toggled.connect(self.notice_details.setVisible)
        notice_layout.addWidget(self.notice_details)
        content_layout.addWidget(self.notice)
        self.notice.hide()
        self.page_stack = QStackedWidget()
        content_layout.addWidget(self.page_stack, 1)
        self.pages = {}

        browse = QWidget()
        browse_layout = QVBoxLayout(browse)
        browse_layout.setContentsMargins(0, 0, 0, 0)
        browse_layout.setSpacing(10)
        self.pages["browse"] = browse
        self.page_stack.addWidget(browse)
        source_bar = QFrame()
        source_bar.setProperty("role", "card")
        source_layout = QHBoxLayout(source_bar)
        source_layout.setContentsMargins(12, 8, 12, 8)
        self.source_summary = label("", "muted")
        source_layout.addWidget(self.source_summary)
        self.source_catalog = QComboBox()
        self.source_catalog.setMinimumContentsLength(12)
        self.source_catalog.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.source_catalog.currentIndexChanged.connect(
            lambda: self.source_catalog.setToolTip(self.source_catalog.currentData() or ""))
        source_layout.addWidget(self.source_catalog, 1)
        self.remove_source_button = button("移除选中库", self.remove_source_catalog)
        self.remove_source_button.setToolTip("仅从当前工作区移除，保留原始文件和软件已安装的库。")
        source_layout.addWidget(self.remove_source_button)
        self.expert_location_button = button("库位置", lambda: self.show_page("codev"), "text")
        source_layout.addWidget(self.expert_location_button)
        browse_layout.addWidget(source_bar)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        self.values = {"name": QLineEdit()}
        search = self.values["name"]
        search.setObjectName("searchInput")
        search.setPlaceholderText("搜索材料名称，按 Enter 筛选")
        search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        search.setClearButtonEnabled(True)
        search.returnPressed.connect(self.apply_filters)
        toolbar.addWidget(search, 1)
        self.filter_button = button("筛选条件", glyph="filter")
        self.filter_button.setCheckable(True)
        toolbar.addWidget(self.filter_button)
        self.convertible_only = QCheckBox("仅可转换")
        self.convertible_only.setToolTip("仅显示可跨格式转换的材料")
        self.convertible_only.toggled.connect(self.apply_filters)
        toolbar.addWidget(self.convertible_only)
        toolbar.addWidget(button("重置", self.reset_filters, "text", "reset"))
        browse_layout.addLayout(toolbar)

        self.advanced_filters = QFrame()
        self.advanced_filters.setObjectName("advancedFilters")
        filter_grid = QGridLayout(self.advanced_filters)
        filter_grid.setContentsMargins(16, 13, 16, 13)
        filter_grid.setHorizontalSpacing(12)
        filter_grid.setVerticalSpacing(10)
        for col, (key, text) in enumerate((("nd_min", "nd 下限"), ("nd_max", "nd 上限"),
                                            ("vd_min", "Vd 下限"), ("vd_max", "Vd 上限"))):
            self.values[key] = QLineEdit()
            self.values[key].setPlaceholderText(text)
            self.values[key].setToolTip(text + "，留空为不限")
            self.values[key].returnPressed.connect(self.apply_filters)
            filter_grid.addWidget(self.values[key], 0, col)
            filter_grid.setColumnStretch(col, 1)
        for col, (key, text) in enumerate((("density_min", "密度下限 · g/cm³"), ("density_max", "密度上限 · g/cm³"))):
            self.values[key] = QLineEdit()
            self.values[key].setPlaceholderText(text)
            self.values[key].setToolTip(text + "，留空为不限")
            self.values[key].returnPressed.connect(self.apply_filters)
            filter_grid.addWidget(self.values[key], 1, col)
        self.status = MultiSelector("供应状态", SUPPLY_STATUS_LABELS)
        filter_grid.addWidget(self.status, 1, 2)
        filter_grid.addWidget(button("应用筛选", self.apply_filters), 1, 3)
        for col, (key, text) in enumerate((("transmission_wavelength_nm", "波长 nm"),
                                          ("transmission_thickness_mm", "厚度 mm"),
                                          ("transmission_min_percent", "内透过率下限 %"),
                                          ("transmission_max_percent", "内透过率上限 %"))):
            self.values[key] = QLineEdit()
            self.values[key].setPlaceholderText(text)
            self.values[key].setToolTip(text)
            self.values[key].returnPressed.connect(self.apply_filters)
            row = QHBoxLayout()
            row.setSpacing(6)
            row.addWidget(label(text if col < 2 else ("下限 %" if col == 2 else "上限 %"), "muted"))
            if col >= 2:
                self.values[key].setPlaceholderText("不限")
            row.addWidget(self.values[key], 1)
            filter_grid.addLayout(row, 2, col)
        self.values["transmission_wavelength_nm"].setText("550")
        self.values["transmission_thickness_mm"].setText("10")
        transmission_hint = label("内透过率不含表面反射；波长内插值、厚度指数换算。设定阈值时排除缺数据的材料。", "caption")
        transmission_hint.setWordWrap(True)
        self.melt_frequency_row = QWidget()
        frequency_layout = QHBoxLayout(self.melt_frequency_row)
        frequency_layout.setContentsMargins(0, 0, 0, 0)
        self.melt_frequency = MultiSelector("熔炼频率", {1: "1 · 很频繁", 2: "2", 3: "3", 4: "4", 5: "5 · 很少"})
        frequency_layout.addWidget(self.melt_frequency)
        frequency_note = label("Zemax 独立等级，1 高、5 低；厂家 MA/A/B 请以同版厂家表为准。", "caption")
        frequency_note.setWordWrap(True)
        frequency_layout.addWidget(frequency_note, 1)
        filter_grid.addWidget(self.melt_frequency_row, 3, 0, 1, 4)
        supplier_filter = QHBoxLayout()
        self.supplier_grade = MultiSelector("厂家分级", {value: value for value in GRADES})
        self.supplier_grade.setEnabled(False)
        supplier_filter.addWidget(self.supplier_grade)
        supplier_filter.addWidget(label("先在导出设置载入厂家表；选分级后排除未匹配材料。", "caption"), 1)
        filter_grid.addLayout(supplier_filter, 4, 0, 1, 4)
        filter_grid.addWidget(transmission_hint, 5, 0, 1, 4)
        self.filter_scroll = QScrollArea()
        self.filter_scroll.setWidgetResizable(True)
        self.filter_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.filter_scroll.setWidget(self.advanced_filters)
        self.filter_scroll.setMaximumHeight(240)
        browse_layout.addWidget(self.filter_scroll)
        self.filter_scroll.hide()
        self.filter_button.toggled.connect(self.filter_scroll.setVisible)

        table_card = QFrame()
        table_card.setProperty("role", "card")
        card_layout = QVBoxLayout(table_card)
        card_layout.setContentsMargins(1, 0, 1, 0)
        card_layout.setSpacing(0)
        table_heading = QHBoxLayout()
        table_heading.setSpacing(12)
        table_heading.setContentsMargins(18, 10, 18, 9)
        table_heading.addWidget(label("材料列表", "section"))
        self.selection_summary = label("当前未选中材料", "muted")
        table_heading.addWidget(self.selection_summary)
        table_heading.addStretch()
        self.count = label("尚未导入", "muted")
        table_heading.addWidget(self.count)
        card_layout.addLayout(table_heading)
        self.table_stack = QStackedWidget()
        self.table_stack.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        card_layout.addWidget(self.table_stack, 1)
        self.table = QTableWidget(0, 10)
        self.table.setHorizontalHeaderLabels(("材料名称", "来源库", "nd", "Vd", "密度", "色散公式", "供应状态", "内透过率", "熔炼频率", "厂家分级"))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.horizontalHeader().setMinimumSectionSize(65)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        for col, width in enumerate((140, 110, 102, 102, 75, 180, 165, 160, 120)):
            self.table.setColumnWidth(col, width)
            if col in (2, 3, 4):
                self.table.horizontalHeaderItem(col).setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.table.itemDoubleClicked.connect(self.show_details)
        self.table.itemSelectionChanged.connect(self.update_selection_summary)
        self.table_stack.addWidget(self.table)
        self.empty_state = QWidget()
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(13)
        empty_mark = QLabel()
        empty_mark.setPixmap(icon("glass", "#B2B5BF", 46).pixmap(QSize(46, 46)))
        empty_mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_mark)
        self.empty_title = label("从一份玻璃库开始", "emptyTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(self.empty_title)
        self.empty_description = label("添加 Zemax AGF 或 CODE V XML，筛选后组合成你的材料库。", "description")
        self.empty_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_description.setWordWrap(True)
        empty_layout.addWidget(self.empty_description)
        empty_layout.addSpacing(7)
        self.empty_add_button = button("添加玻璃库", self.add_files, "primary", "plus")
        empty_layout.addWidget(self.empty_add_button, alignment=Qt.AlignmentFlag.AlignCenter)
        self.table_stack.addWidget(self.empty_state)
        self.table_stack.setCurrentWidget(self.empty_state)
        table_note = label("Ctrl / Shift 多选    ·    双击查看材料详情", "caption")
        table_note.setContentsMargins(18, 6, 18, 7)
        card_layout.addWidget(table_note)
        browse_layout.addWidget(table_card, 1)

        settings = QScrollArea()
        settings.setWidgetResizable(True)
        settings.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        settings_content = QWidget()
        settings_content.setObjectName("settingsContent")
        settings.setWidget(settings_content)
        settings_layout = QVBoxLayout(settings_content)
        settings_layout.setContentsMargins(0, 0, 3, 0)
        settings_layout.setSpacing(16)
        self.pages["settings"] = settings
        self.page_stack.addWidget(settings)
        conversion = QFrame()
        conversion.setProperty("role", "card")
        conversion_layout = QVBoxLayout(conversion)
        conversion_layout.setContentsMargins(21, 18, 21, 18)
        conversion_layout.setSpacing(13)
        conversion_layout.addWidget(label("输出格式", "section"))
        self.format_description = label("", "muted")
        self.format_description.setWordWrap(True)
        conversion_layout.addWidget(self.format_description)
        formats = QHBoxLayout()
        formats.setSpacing(12)
        self.format_buttons = {}
        format_group = QButtonGroup(self)
        for value, text in (("xml", "CODE V\nXML 玻璃库"), ("agf", "Zemax\nAGF 玻璃库"),
                            ("dat", "Glass Expert\nDAT 候选清单")):
            choice = button(text, lambda checked=False, fmt=value: self.set_output_format(fmt), "format")
            choice.setCheckable(True)
            format_group.addButton(choice)
            self.format_buttons[value] = choice
            formats.addWidget(choice)
        conversion_layout.addLayout(formats)
        self.prefix_source = QCheckBox("材料名加来源前缀，区分多个库中的同名材料")
        conversion_layout.addWidget(self.prefix_source)
        self.thickness_row = QWidget()
        thickness = QHBoxLayout(self.thickness_row)
        thickness.setContentsMargins(0, 0, 0, 0)
        thickness.addWidget(label("透过率厚度", "description"))
        self.thickness = QLineEdit()
        self.thickness.setPlaceholderText("mm")
        self.thickness.setFixedWidth(85)
        thickness.addWidget(self.thickness)
        thickness.addWidget(label("XML → AGF 有多厚度曲线时填写", "muted"))
        thickness.addStretch()
        conversion_layout.addWidget(self.thickness_row)
        self.expert_options = QWidget()
        expert_layout = QVBoxLayout(self.expert_options)
        expert_layout.setContentsMargins(0, 0, 0, 0)
        expert_note = label("DAT 只从所选 CODE V 已安装的 XML 库选材，保留原库名与牌号。新材料请先转换为 XML 并安装。", "muted")
        expert_note.setWordWrap(True)
        expert_layout.addWidget(expert_note)
        expert_layout.addWidget(button("选择 CODE V 已安装库", self.choose_expert_catalogs, glyph="folder"))
        conversion_layout.addWidget(self.expert_options)
        settings_layout.addWidget(conversion)
        self.codev_installation = installation = QFrame()
        installation.setProperty("role", "card")
        installation_layout = QVBoxLayout(installation)
        installation_layout.setContentsMargins(21, 18, 21, 18)
        installation_layout.setSpacing(12)
        installation_layout.addWidget(label("CODE V 安装位置", "section"))
        self.codev_target_summary = label(self.preferences["codev_root"], "description")
        self.codev_target_summary.setWordWrap(True)
        installation_layout.addWidget(self.codev_target_summary)
        installation_layout.addWidget(button("打开 CODE V 库管理", lambda: self.show_page("codev"), glyph="folder"))
        self.include_codev_tables = QCheckBox("导出 CODE V 时同时生成材料目录和热光目录（含两张总表）")
        self.include_codev_tables.setChecked(True)
        installation_layout.addWidget(self.include_codev_tables)
        self.installation_backup_note = QWidget()
        backup = QHBoxLayout(self.installation_backup_note)
        backup.setContentsMargins(0, 0, 0, 0)
        backup_mark = QLabel()
        backup_mark.setPixmap(icon("shield", "#92959F", 16).pixmap(QSize(16, 16)))
        backup.addWidget(backup_mark)
        backup.addWidget(label("安装与卸载前自动备份，材料目录与热光目录同步更新。", "muted"))
        backup.addStretch()
        installation_layout.addWidget(self.installation_backup_note)
        settings_layout.addWidget(installation)
        self.zemax_installation = QFrame()
        self.zemax_installation.setProperty("role", "card")
        zemax_settings = QVBoxLayout(self.zemax_installation)
        zemax_settings.setContentsMargins(21, 18, 21, 18)
        zemax_settings.addWidget(label("Zemax 安装位置", "section"))
        zemax_settings.addWidget(label("选择 Zemax 实际使用的 Glasscat 文件夹，可在“Zemax 库管理”中修改。", "muted"))
        self.zemax_target_summary = label(self.preferences["zemax_glasscat"], "description")
        self.zemax_target_summary.setWordWrap(True)
        zemax_settings.addWidget(self.zemax_target_summary)
        zemax_settings.addWidget(button("打开 Zemax 库管理", lambda: self.show_page("zemax"), glyph="folder"))
        settings_layout.addWidget(self.zemax_installation)
        self.install_selected_only = QCheckBox("一键安装仅使用列表中选中的材料")
        settings_layout.addWidget(self.install_selected_only)
        supplier_card = QFrame()
        supplier_card.setProperty("role", "card")
        supplier_layout = QVBoxLayout(supplier_card)
        supplier_layout.setContentsMargins(21, 18, 21, 18)
        supplier_layout.addWidget(label("厂家生产频率表 · 可选", "section"))
        supplier_row = QHBoxLayout()
        self.supplier_path = QLineEdit(self.preferences.get("supplier_table", ""))
        self.supplier_path.setPlaceholderText("选择 CSV、TSV 或 XLSX 厂家表")
        self.supplier_path.setReadOnly(True)
        supplier_row.addWidget(self.supplier_path, 1)
        supplier_row.addWidget(button("选择表", self.choose_supplier_table, glyph="folder"))
        supplier_layout.addLayout(supplier_row)
        supplier_actions = QHBoxLayout()
        supplier_actions.addWidget(label("厂家", "muted"))
        self.supplier_name = QLineEdit(self.preferences.get("supplier", ""))
        self.supplier_name.setPlaceholderText("如 CDGM")
        self.supplier_name.setMaximumWidth(160)
        supplier_actions.addWidget(self.supplier_name)
        supplier_actions.addWidget(button("读取表", self.reload_supplier_table))
        supplier_actions.addWidget(button("清除", self.clear_supplier_table, "text"))
        supplier_actions.addStretch()
        supplier_layout.addLayout(supplier_actions)
        self.supplier_summary = label("按厂家与牌号匹配 MA/A/B/C/D，保留表的来源和版本；不从软件数字等级猜测。", "muted")
        self.supplier_summary.setWordWrap(True)
        supplier_layout.addWidget(self.supplier_summary)
        settings_layout.addWidget(supplier_card)
        settings_layout.addStretch()

        for software in ("codev", "zemax"):
            is_codev = software == "codev"
            manager = QWidget()
            manager_layout = QVBoxLayout(manager)
            manager_layout.setContentsMargins(0, 0, 0, 0)
            manager_layout.setSpacing(12)
            directory_card = QFrame()
            directory_card.setProperty("role", "card")
            directory_layout = QVBoxLayout(directory_card)
            directory_layout.setContentsMargins(16, 14, 16, 14)
            directory_layout.addWidget(label("CODE V 安装文件夹" if is_codev else "Zemax Glasscat 文件夹", "section"))
            directory = QHBoxLayout()
            root = QLineEdit(self.preferences["codev_root" if is_codev else "zemax_glasscat"])
            root.setCursorPosition(0)
            root.setPlaceholderText("选择包含 glass 和 macro 的 CODE V 目录" if is_codev else "选择实际使用的 Glasscat 目录")
            setattr(self, software + "_root", root)
            directory.addWidget(root, 1)
            directory.addWidget(button("选择目录", self.choose_codev_root if is_codev else self.choose_zemax_root, glyph="folder"))
            directory.addWidget(button("刷新", self.refresh_codev if is_codev else self.refresh_zemax, glyph="reset"))
            directory_layout.addLayout(directory)
            note = ("安装与卸载前自动备份，并同步材料与热光两张总表；文件同步后请在 CODE V 中查询确认识别。" if is_codev else
                    "安装、更新与卸载前自动备份；Zemax 会自行生成 BGF 缓存。安装后在镜头的 Material Catalogs 中加入库名。")
            manager_note = label(note, "muted")
            manager_note.setWordWrap(True)
            directory_layout.addWidget(manager_note)
            manager_layout.addWidget(directory_card)
            manager_actions = QHBoxLayout()
            manager_actions.addWidget(button("安装已有导出包" if is_codev else "安装已有 AGF",
                                             self.install_codev if is_codev else self.install_zemax_file, glyph="install"))
            if not is_codev:
                manager_actions.addWidget(button("从备份恢复", self.restore_zemax, glyph="reset"))
            manager_actions.addStretch()
            count = label("", "muted")
            setattr(self, software + "_count", count)
            manager_actions.addWidget(count)
            manager_layout.addLayout(manager_actions)
            columns = ["玻璃库", "材料数", "数据提示", *([] if is_codev else ["BGF 缓存"]), "文件位置"]
            table = QTableWidget(0, len(columns))
            setattr(self, software + "_table", table)
            table.setHorizontalHeaderLabels(columns)
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setShowGrid(False)
            table.setWordWrap(False)
            table.verticalHeader().hide()
            table.verticalHeader().setDefaultSectionSize(38)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            table.horizontalHeader().setSectionResizeMode(len(columns) - 1, QHeaderView.ResizeMode.Stretch)
            load_selection = self.load_codev_selection if is_codev else self.load_zemax_selection
            table.itemDoubleClicked.connect(load_selection)
            manager_layout.addWidget(table, 1)
            installed_actions = QHBoxLayout()
            load_button = button("载入到筛选工作区", load_selection, glyph="library")
            setattr(self, software + "_load_button", load_button)
            installed_actions.addWidget(load_button)
            if not is_codev:
                self.zemax_backup_button = button("备份选中的库", self.backup_zemax_selection, glyph="shield")
                installed_actions.addWidget(self.zemax_backup_button)
            installed_actions.addStretch()
            uninstall_button = button("卸载选中的库", self.uninstall_codev if is_codev else self.uninstall_zemax_selection, glyph="trash")
            setattr(self, software + "_uninstall_button", uninstall_button)
            installed_actions.addWidget(uninstall_button)
            manager_layout.addLayout(installed_actions)
            table.itemSelectionChanged.connect(self.update_codev_selection if is_codev else self.update_zemax_selection)
            self.pages[software] = manager
            self.page_stack.addWidget(manager)

        self.output_bar = output_bar = QFrame()
        output_bar.setObjectName("outputBar")
        output_layout = QVBoxLayout(output_bar)
        output_layout.setContentsMargins(24, 10, 24, 12)
        output_layout.setSpacing(8)
        output_row = QHBoxLayout()
        output_row.setSpacing(12)
        self.output_name_label = label("新库名称", "muted")
        output_row.addWidget(self.output_name_label)
        self.catalog_name = QLineEdit()
        self.catalog_name.setMinimumWidth(160)
        self.catalog_name.setToolTip("自动按来源库、筛选标记和日期命名，可手动修改。玻璃库名以英文字母开头，只用字母、数字、下划线；保存时与文件名同步。")
        output_row.addWidget(self.catalog_name, 1)
        output_row.addWidget(button("自动命名", lambda: self.update_catalog_name(force=True), "text"))
        output_row.addWidget(label("导出为", "muted"))
        self.output_format = QComboBox()
        self.output_format.addItem("CODE V XML", "xml")
        self.output_format.addItem("Zemax AGF", "agf")
        self.output_format.addItem("Glass Expert DAT", "dat")
        self.output_format.setFixedWidth(165)
        output_row.addWidget(self.output_format)
        output_layout.addLayout(output_row)
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self.export_button = button("导出筛选结果", lambda: self.export(False), glyph="export")
        actions.addWidget(self.export_button)
        self.export_selection_button = button("仅导出选中材料", lambda: self.export(True))
        actions.addWidget(self.export_selection_button)
        actions.addStretch()
        self.install_button = button("一键转换并安装到 CODE V", self.convert_and_install, "primary", "install")
        actions.addWidget(self.install_button)
        output_layout.addLayout(actions)
        main.addWidget(output_bar)
        self.output_format.currentIndexChanged.connect(self.update_output_format)
        self.codev_root.editingFinished.connect(self.update_codev_directory)
        self.zemax_root.editingFinished.connect(self.update_zemax_directory)
        self.update_output_format()
        self.apply_filters()
        self.update_codev_selection()
        self.update_zemax_selection()
        self.show_page("browse")
        if self.supplier_path.text():
            self.reload_supplier_table()

    def show_page(self, key):
        self.page_stack.setCurrentWidget(self.pages[key])
        self.nav_buttons[key].setChecked(True)
        self.current_page = key
        titles = {"browse": (("Glass Expert 候选材料", "选择 CODE V 已安装库，筛选后导出 DAT 清单。") if self.dat_mode else
                             ("玻璃库与筛选", "导入库文件，挑选材料，再导出为新库。")),
                  "settings": ("导出设置", "选择输出格式及对应的安装选项。"),
                  "codev": ("CODE V 库管理", "查看、载入、安装与卸载本机 CODE V 玻璃库。"),
                  "zemax": ("Zemax 库管理", "查看、安装、备份与卸载本机 Zemax 玻璃库。")}
        self.page_title.setText(titles[key][0])
        self.page_description.setText(titles[key][1])
        self.output_bar.setVisible(key in {"browse", "settings"})
        self.clear_button.setVisible(key in {"browse", "settings"})
        self.format_badge.setVisible(key in {"browse", "settings"})
        if key == "codev":
            self.refresh_codev()
        elif key == "zemax":
            self.refresh_zemax()

    def set_output_format(self, value):
        self.output_format.setCurrentIndex(self.output_format.findData(value))

    def update_output_format(self):
        fmt = self.output_format.currentData()
        source_changed = self.dat_mode != (fmt == "dat")
        if source_changed:
            self.output_names[self.dat_mode] = (self.catalog_name.text(), self.name_suggestion)
        self.dat_mode = fmt == "dat"
        if source_changed:
            value, self.name_suggestion = self.output_names[self.dat_mode]
            self.catalog_name.setText(value)
        self.filter_scroll.setMaximumHeight(80 if self.height() < 720 else 240)
        self.format_buttons[fmt].setChecked(True)
        self.codev_installation.setVisible(fmt in {"xml", "dat"})
        self.zemax_installation.setVisible(fmt == "agf")
        self.thickness_row.setVisible(fmt == "agf")
        self.expert_options.setVisible(fmt == "dat")
        self.include_codev_tables.setVisible(fmt == "xml")
        self.installation_backup_note.setVisible(fmt == "xml")
        self.install_selected_only.setVisible(fmt != "dat")
        self.prefix_source.setVisible(fmt != "dat")
        self.prefix_source.setEnabled(fmt != "dat")
        self.convertible_only.setVisible(fmt != "dat")
        self.expert_location_button.setVisible(fmt == "dat")
        self.output_name_label.setText("清单名称" if self.dat_mode else "新库名称")
        self.add_button.setText("选择已安装库" if self.dat_mode else "添加玻璃库")
        self.empty_add_button.setText(self.add_button.text())
        names = {"xml": "XML", "agf": "AGF", "dat": "DAT"}
        self.export_button.setText("导出 DAT 清单" if self.dat_mode else f"导出筛选结果 · {names[fmt]}")
        self.export_selection_button.setText(f"仅导出选中 · {names[fmt]}")
        self.install_button.setText({"xml": "转换并安装到 CODE V", "agf": "转换并安装到 Zemax",
                                     "dat": "导出 Glass Expert 清单"}[fmt])
        self.install_button.setIcon(icon("export" if fmt == "dat" else "install", "#FFFFFF"))
        self.install_button.setVisible(fmt != "dat")
        self.export_button.setProperty("role", "primary" if self.dat_mode else "")
        self.export_button.setIcon(icon("export", "#FFFFFF" if self.dat_mode else "#777983"))
        self.export_button.style().unpolish(self.export_button)
        self.export_button.style().polish(self.export_button)
        self.format_description.setText({
            "xml": "导出 XML，可同时生成材料与热光目录；一键安装会备份并写入 CODE V。",
            "agf": "导出 AGF；一键安装会备份并写入 Zemax 的 Glasscat 文件夹。",
            "dat": "从已安装的 CODE V 库选择候选材料，筛选后导出 Catalog / Glass 两列 DAT。"}[fmt])
        if source_changed:
            self.apply_filters()
        else:
            self.update_catalog_name()
        if hasattr(self, "current_page"):
            self.show_page(self.current_page)

    def notify(self, title, details="", level="success"):
        """Persistent inline feedback, without modal alerts or system sounds."""
        self.last_notice = {"title": title, "details": details, "level": level}
        self.notice.setProperty("level", level)
        self.notice.style().unpolish(self.notice)
        self.notice.style().polish(self.notice)
        self.notice_title.setText(title)
        self.notice_details.setPlainText(details)
        self.notice_more.setChecked(False)
        self.notice_more.setVisible(bool(details))
        self.notice.show()

    def save_preferences(self):
        codev_changed = self.preferences["codev_root"] != self.codev_root.text().strip()
        self.preferences.update(codev_root=self.codev_root.text().strip(),
                                zemax_glasscat=self.zemax_root.text().strip(),
                                supplier_table=self.supplier_path.text(), supplier=self.supplier_name.text().strip())
        self.codev_target_summary.setText(self.preferences["codev_root"] or "尚未选择 CODE V 安装目录")
        self.zemax_target_summary.setText(self.preferences["zemax_glasscat"] or "尚未选择 Zemax Glasscat 文件夹")
        if codev_changed:
            self.expert_catalogs = []
            if self.dat_mode:
                self.apply_filters()
        if self.persist_settings:
            try:
                save_settings(self.preferences)
            except OSError as exc:
                self.notify("设置尚未保存", str(exc), "error")

    def closeEvent(self, event):
        self.save_preferences()
        super().closeEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "filter_scroll"):
            self.filter_scroll.setMaximumHeight(80 if self.height() < 720 else 240)

    def selected_glasses(self):
        return [self.filtered[index.row()] for index in self.table.selectionModel().selectedRows()]

    def update_selection_summary(self):
        count = len(self.table.selectionModel().selectedRows())
        self.selection_summary.setText(f"已选中 {count} 种材料" if count else "当前未选中材料")

    def update_catalog_name(self, force=False):
        catalogs = self.expert_catalogs if self.dat_mode else self.catalogs
        base = catalogs[0].name if len(catalogs) == 1 else "MIXED" if catalogs else "CUSTOM"
        base = re.sub(r"[^A-Za-z0-9]+", "_", base).strip("_") or "CUSTOM"
        if not base[0].isalpha():
            base = "CATALOG_" + base
        parts = [base]
        if self.dat_mode:
            parts.append("EXPERT")
        parts.extend(self.active_filters.get("supplier_grade") or [])
        if any(value is not None and value is not False and value != "" and value != []
               for key, value in self.active_filters.items()
               if key not in {"supplier_grade", "transmission_wavelength_nm", "transmission_thickness_mm"}):
            parts.append("FILTERED")
        parts.append(datetime.now().strftime("%Y%m%d"))
        suggestion = "_".join(parts)
        if force or not self.catalog_name.text().strip() or self.catalog_name.text() == self.name_suggestion:
            self.catalog_name.setText(suggestion)
        self.name_suggestion = suggestion
        return self.catalog_name.text().strip()

    def choose_codev_root(self):
        path = QFileDialog.getExistingDirectory(self, "选择 CODE V 安装目录", self.codev_root.text())
        if path:
            self.codev_root.setText(path)
            self.update_codev_directory()

    def add_files(self):
        if self.dat_mode:
            return self.choose_expert_catalogs()
        paths, _ = QFileDialog.getOpenFileNames(self, "添加玻璃库", "", "玻璃库 (*.AGF *.agf *.xml *.XML);;所有文件 (*)")
        if not paths:
            return
        try:
            existing = {c.source.casefold() for c in self.catalogs}
            loaded = [load_catalog(p) for p in paths if str(Path(p).resolve()).casefold() not in existing]
            self.catalogs.extend(loaded)
            self.apply_filters()
        except (OSError, ValueError, ET.ParseError) as exc:
            self.notify("无法读取玻璃库", str(exc), "error")

    def choose_supplier_table(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择厂家生产频率表", self.supplier_path.text(), "厂家表 (*.xlsx *.csv *.tsv)")
        if path:
            self.supplier_path.setText(path)
            self.supplier_name.clear()
            self.reload_supplier_table()

    def reload_supplier_table(self):
        try:
            table = load_supplier_table(self.supplier_path.text(), self.supplier_name.text().strip() or None)
            self.supplier_reference = table
            self.supplier_name.setText(table.manufacturer)
            self.supplier_grade.clear_selection()
            self.supplier_grade.set_available(set(table.grades.values()))
            self.supplier_grade.setEnabled(True)
            self.apply_filters()
            self.save_preferences()
            self.notify("已载入厂家生产频率表", f"{table.source}\n厂家：{table.manufacturer}\n版本：{table.version or '文件名未标注'}\n"
                        "仅按该厂家库名及牌号匹配，原始光学库不改动。")
        except (OSError, ValueError) as exc:
            self.supplier_reference = None
            self.supplier_grade.clear_selection()
            self.supplier_grade.setEnabled(False)
            self.supplier_summary.setText("厂家表未载入；请核对文件和厂家名称后重新读取。")
            self.apply_filters()
            self.notify("厂家表未载入", str(exc), "error")

    def clear_supplier_table(self):
        self.supplier_reference = None
        self.supplier_path.clear()
        self.supplier_name.clear()
        self.supplier_grade.clear_selection()
        self.supplier_grade.setEnabled(False)
        self.supplier_summary.setText("未载入厂家表；供应状态与软件熔炼频率仍使用原始库数据。")
        self.apply_filters()
        self.save_preferences()

    def choose_expert_catalogs(self):
        try:
            paths = installed_catalog_paths(self.codev_root.text().strip())
        except (OSError, ValueError) as exc:
            self.notify("请选择有效的 CODE V 位置", str(exc), "info")
            self.show_page("codev")
            return
        if not paths:
            self.notify("没有找到已安装的 CODE V XML 库", "请核对 CODE V 安装位置，或先安装材料库。", "info")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("选择 CODE V 已安装库")
        dialog.resize(720, 510)
        body = QVBoxLayout(dialog)
        body.setContentsMargins(20, 18, 20, 18)
        body.setSpacing(12)
        body.addWidget(label("选择已安装库", "title"))
        location = label(str(paths[0].parent), "muted")
        location.setWordWrap(True)
        body.addWidget(location)
        search = QLineEdit()
        search.setPlaceholderText("搜索库文件名，可勾选多个库")
        body.addWidget(search)
        table = QTableWidget(len(paths), 1)
        table.setObjectName("expertCatalogChoices")
        table.setHorizontalHeaderLabels(["CODE V 已安装库 · 勾选后载入材料"])
        table.verticalHeader().hide()
        table.verticalHeader().setDefaultSectionSize(38)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        selected = {c.source.casefold() for c in self.expert_catalogs}
        for row, path in enumerate(paths):
            item = QTableWidgetItem(path.name)
            item.setToolTip(str(path))
            item.setCheckState(Qt.CheckState.Checked if str(path.resolve()).casefold() in selected else Qt.CheckState.Unchecked)
            table.setItem(row, 0, item)
        body.addWidget(table, 1)
        def filter_libraries(text):
            for row, path in enumerate(paths):
                table.setRowHidden(row, text.casefold() not in path.name.casefold())

        search.textChanged.connect(filter_libraries)
        error = label("", "description")
        error.setWordWrap(True)
        error.hide()
        body.addWidget(error)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(button("取消", dialog.reject))
        load = button("载入所选库", role="primary")
        load.setObjectName("loadExpertCatalogs")
        actions.addWidget(load)
        body.addLayout(actions)

        def load_selected():
            selected_paths = [path for row, path in enumerate(paths) if table.item(row, 0).checkState() == Qt.CheckState.Checked]
            if not selected_paths:
                error.setText("请至少勾选一个已安装库。")
                error.show()
                return
            try:
                catalogs = [load_catalog(path) for path in selected_paths]
            except (OSError, ValueError, ET.ParseError) as exc:
                error.setText(str(exc))
                error.show()
                return
            self.expert_catalogs = catalogs
            self.set_output_format("dat")
            self.apply_filters()
            self.show_page("browse")
            self.notify(f"已载入 {len(catalogs)} 个 CODE V 已安装库", "可继续筛选，或按 Ctrl / Shift 选择材料后导出 DAT。")
            dialog.accept()

        load.clicked.connect(load_selected)
        dialog.open()
        return dialog

    def clear(self):
        if self.dat_mode:
            self.expert_catalogs = []
        else:
            self.catalogs = []
        self.reset_filters()

    def reset_filters(self):
        for entry in self.values.values():
            entry.clear()
        self.values["transmission_wavelength_nm"].setText("550")
        self.values["transmission_thickness_mm"].setText("10")
        self.status.clear_selection()
        self.melt_frequency.clear_selection()
        self.supplier_grade.clear_selection()
        self.convertible_only.setChecked(False)
        self.apply_filters()

    def refresh_source_catalogs(self):
        catalogs = self.expert_catalogs if self.dat_mode else self.catalogs
        selected = self.source_catalog.currentData()
        self.source_catalog.clear()
        self.source_summary.setText(f"{'DAT 来源库' if self.dat_mode else '已导入库'} · {len(catalogs)}")
        self.source_catalog.setPlaceholderText("尚未选择已安装库" if self.dat_mode else "尚未导入玻璃库")
        for catalog in catalogs:
            self.source_catalog.addItem(f"{catalog.name} · {catalog.format.upper()} · {len(catalog.glasses)} 种", catalog.source)
            self.source_catalog.setItemData(self.source_catalog.count() - 1, catalog.source, Qt.ItemDataRole.ToolTipRole)
        index = self.source_catalog.findData(selected)
        if catalogs:
            self.source_catalog.setCurrentIndex(index if index >= 0 else 0)
        self.source_catalog.setEnabled(bool(catalogs))
        self.remove_source_button.setEnabled(bool(catalogs))

    def remove_source_catalog(self):
        index = self.source_catalog.currentIndex()
        if index < 0:
            return
        catalogs = self.expert_catalogs if self.dat_mode else self.catalogs
        removed = catalogs.pop(index)
        # Keep the applied conditions even when a filter edit is still unfinished.
        self.apply_filters(options=dict(self.active_filters))
        self.notify(f"已从工作区移除 {removed.name}", f"原始文件保留，可重新添加：\n{removed.source}")

    def apply_filters(self, *, options=None):
        self.refresh_source_catalogs()
        try:
            catalogs = self.expert_catalogs if self.dat_mode else self.catalogs
            formats = {c.format for c in catalogs} or ({"xml"} if self.dat_mode else {"agf", "xml"})
            self.status.set_available({key for key in SUPPLY_STATUS_LABELS if
                                       (key.startswith("codev:") and "xml" in formats) or (key.startswith("agf:") and "agf" in formats)})
            self.melt_frequency_row.setVisible("agf" in formats)
            if options is None:
                options = {key: (entry.text().strip() if key == "name" else float(entry.text()) if entry.text().strip() else None)
                           for key, entry in self.values.items()}
                options["supply_status"] = self.status.values()
                options["melt_frequency"] = self.melt_frequency.values() if "agf" in formats else None
                options["supplier_grade"] = self.supplier_grade.values() if self.supplier_reference else None
                options["convertible_only"] = self.convertible_only.isChecked() and not self.dat_mode
            glasses = [g for c in catalogs for g in c.glasses]
            if self.supplier_reference:
                glasses = enrich_glasses(glasses, self.supplier_reference)
                matched = sum(g.supplier_grade is not None for g in glasses)
                self.supplier_summary.setText(f"{self.supplier_reference.manufacturer} · {self.supplier_reference.version or '未标注版本'} · "
                                              f"已匹配 {matched}/{len(glasses)} 种材料。未匹配材料不会猜测分级。")
            self.filtered = select_glasses(glasses, **options)
            self.active_filters = options
            self.table.setUpdatesEnabled(False)
            self.table.clearContents()
            self.table.setRowCount(len(self.filtered))
            for row, glass in enumerate(self.filtered):
                number = lambda value: "—" if value is None else f"{value:.7g}"
                transmission = (transmission_at(glass, options["transmission_wavelength_nm"], options["transmission_thickness_mm"])
                                if options["transmission_wavelength_nm"] is not None else None)
                for col, value in enumerate((glass.name, glass.catalog, number(glass.nd), number(glass.vd),
                                             number(glass.density), glass.equation, glass.supply_label,
                                             "—" if transmission is None else f"{transmission * 100:.3f}%", glass.melt_frequency_label,
                                             glass.supplier_grade or "—")):
                    item = QTableWidgetItem(str(value))
                    item.setToolTip(str(value))
                    if col == 6:
                        item.setToolTip(f"{value}\n原始状态：{glass.supply_status or '未提供'}")
                    elif col == 8:
                        item.setToolTip(f"{value}\n" + ("来自 CODE V Availability，仅显示明确的熔炼频率分类。" if glass.format == "xml" else
                                                        "来自 Zemax NM 的独立 melt freq 字段；不将数字等级直接还原为厂家 MA/A/B/C/D。"))
                    elif col == 9 and glass.supplier_reference:
                        item.setToolTip(f"{glass.supplier_grade}\n{glass.supplier_reference['source']}\n版本：{glass.supplier_reference['version'] or '未标注'}")
                    if col in (2, 3, 4):
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    if col == 0:
                        font = item.font()
                        font.setWeight(QFont.Weight.DemiBold)
                        item.setFont(font)
                    elif col == 1:
                        item.setForeground(QColor("#85868F"))
                    self.table.setItem(row, col, item)
            self.table.setUpdatesEnabled(True)
            issues = sum(bool(g.issues) for g in glasses)
            self.count.setText(f"{len(self.filtered)} / {len(glasses)} 种材料" + (f"  ·  {issues} 种有提示" if issues else ""))
            self.library_summary.setText((f"已选 {len(catalogs)} 个已安装库" if catalogs else "尚未选择已安装库") if self.dat_mode else
                                         (f"已导入 {len(catalogs)} 个玻璃库" if catalogs else "尚未导入玻璃库"))
            self.table_stack.setCurrentWidget(self.table if self.filtered else self.empty_state)
            self.empty_title.setText("没有符合条件的材料" if catalogs else "选择 CODE V 已安装库" if self.dat_mode else "从一份玻璃库开始")
            self.empty_description.setText("试试调整或重置筛选条件。" if catalogs else
                                          "DAT 仅从已安装的 XML 库选材；新材料请先转换并安装。" if self.dat_mode else
                                          "添加 Zemax AGF 或 CODE V XML，筛选后组合成你的材料库。")
            self.empty_add_button.setVisible(not catalogs)
            self.update_selection_summary()
            self.update_catalog_name()
            wave = options["transmission_wavelength_nm"]
            thickness = options["transmission_thickness_mm"]
            self.table.horizontalHeaderItem(7).setText(f"内透过率 · {wave:g}nm/{thickness:g}mm" if wave is not None else "内透过率")
            if self.last_notice and self.last_notice["title"] == "筛选条件有误":
                self.notice.hide()
            return True
        except ValueError as exc:
            self.notify("筛选条件有误", str(exc), "error")
            return False

    def show_details(self, item=None):
        selected = self.selected_glasses()
        if not selected:
            return
        glass = selected[0]
        details = (f"来源：{glass.source}\n材料：{glass.name}\n色散公式：{glass.equation}\n"
                   f"原生供应状态：{glass.supply_label}（{glass.supply_status or '未提供'}）\n熔炼频率：{glass.melt_frequency_label}\n"
                   f"厂家分级：{glass.supplier_grade or '未匹配'}\n"
                   f"nd：{glass.nd}\nVd：{glass.vd}\n密度：{glass.density} g/cm³\n"
                   f"有效波段：{glass.wavelength_range} μm\n色散系数：{glass.coefficients}\n"
                   f"热光常数 TD：{glass.td}\n透过率点数：{len(glass.transmission) + len(glass.transmission_above_one)}\n\n"
                   + ("\n".join(glass.issues) if glass.issues else "未发现数据提示；跨格式支持范围见使用说明。"))
        dialog = QDialog(self)
        dialog.setWindowTitle(glass.name + " · 材料详情")
        dialog.resize(650, 460)
        body = QVBoxLayout(dialog)
        body.addWidget(label(glass.name, "title"))
        view = QPlainTextEdit(details)
        view.setReadOnly(True)
        body.addWidget(view)
        body.addWidget(button("关闭", dialog.accept))
        dialog.open()
        return dialog

    def export(self, selected_only):
        glasses = self.selected_glasses() if selected_only else self.filtered
        if not glasses:
            self.notify("没有可导出的材料", "请先选择 CODE V 已安装库，再筛选或选中材料。" if self.dat_mode else
                        "请先导入、筛选或选中材料。", "info")
            return
        extension = "." + self.output_format.currentData()
        name = self.update_catalog_name()
        directory = Path(self.preferences.get("export_directory", str(EXPORT_ROOT)))
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path, _ = QFileDialog.getSaveFileName(self, "保存 Glass Expert DAT 清单" if self.dat_mode else "另存为新玻璃库", str(directory / (name + extension)),
                                                 "玻璃库 (*" + extension + ")")
            if not path:
                return
            output = Path(path)
            if not output.suffix:
                output = output.with_suffix(extension)
            if output.suffix.lower() != extension:
                raise CatalogError(f"当前选择 {extension} 格式，请保存为 {extension} 文件")
            report = export_catalog(glasses, output, catalog_name=output.stem,
                                    prefix_source=self.prefix_source.isChecked() and self.prefix_source.isEnabled(),
                                    transmission_thickness=float(self.thickness.text())
                                    if self.output_format.currentData() == "agf" and self.thickness.text().strip() else None,
                                    codev_root=self.codev_root.text().strip()
                                    if self.dat_mode or (self.output_format.currentData() == "xml" and self.include_codev_tables.isChecked()) else None,
                                    selection_info={"input_count": sum(len(c.glasses) for c in (self.expert_catalogs if self.dat_mode else self.catalogs)),
                                                    "filters": self.active_filters, "selected_rows_only": selected_only})
            self.catalog_name.setText(output.stem)
            self.preferences["export_directory"] = str(output.parent)
            self.save_preferences()
            details = f"已导出 {report['count']} 种材料\n{report['output']}\n\n报告：{report['report']}"
            if "codev_bundle" in report:
                self.last_bundle = report["codev_bundle"]
                details += (f"\n\nCODE V 完整导出包：{self.last_bundle}\n"
                            "已包含：XML、单库材料目录、CatalogFull.dat、dndt_constants.dat。\n"
                            "尚未安装；可在“CODE V 库管理”中选择“安装已有导出包”。")
            if report["warnings"]:
                details += "\n\n" + "\n".join(report["warnings"])
            if self.dat_mode:
                details += "\n\n已核对所选 CODE V 中的库名和牌号。在 Glass Expert 中选择 USER，将此 DAT 指定为 User Catalog。"
            self.notify(f"已导出 {report['count']} 种材料 · {output.name}", details)
        except (OSError, ValueError, ET.ParseError) as exc:
            self.notify("未完成导出", str(exc), "error")

    def install_codev(self):
        path = QFileDialog.getExistingDirectory(self, "选择 CODE V 导出包目录（内含 manifest.json）",
                                                self.last_bundle or str(Path.cwd()))
        if not path:
            return
        try:
            result = codev.apply(path, self.codev_root.text().strip())
            self.refresh_codev()
            details = (f"已安装 {result['catalog']}，共 {result['count']} 种材料。\n"
                       f"XML、单库材料目录及两张总表均已同步。\n\n备份：{result['backup']}\n\n"
                       "请在 CODE V 中查询新库，确认软件识别。")
            self.notify("CODE V 库文件已安装" if result["ok"] else "文件核对未通过",
                        details if result["ok"] else str(result), "success" if result["ok"] else "error")
        except (OSError, ValueError, KeyError, ET.ParseError) as exc:
            self.notify("未完成安装", str(exc), "error")

    def convert_and_install(self):
        fmt = self.output_format.currentData()
        if fmt == "dat":
            return self.export(False)
        if self.install_selected_only.isChecked():
            glasses = self.selected_glasses()
        else:
            if not self.apply_filters():
                return
            glasses = self.filtered
        if not glasses:
            self.notify("没有可安装的材料", "请先导入、筛选或选中材料。", "info")
            return
        name = self.update_catalog_name()
        target = "CODEV" if fmt == "xml" else "ZEMAX"
        output = EXPORT_ROOT / (name + "_安装到" + target + "_" + datetime.now().strftime("%H%M%S_%f")) / (name + "." + fmt)
        try:
            report = export_catalog(glasses, output, catalog_name=name, prefix_source=self.prefix_source.isChecked(),
                                    transmission_thickness=float(self.thickness.text()) if fmt == "agf" and self.thickness.text().strip() else None,
                                    codev_root=self.codev_root.text().strip() if fmt == "xml" else None,
                                    bundle_dir=output.parent / "CODEV安装包" if fmt == "xml" else None,
                                    install_codev=fmt == "xml",
                                    selection_info={"input_count": sum(len(c.glasses) for c in self.catalogs),
                                                    "filters": self.active_filters,
                                                    "selected_rows_only": self.install_selected_only.isChecked()})
            if fmt == "agf":
                root = self.zemax_root.text().strip()
                if not root:
                    raise CatalogError("请在 Zemax 库管理中选择实际使用的 Glasscat 目录")
                result = zemax.install(output, root, name)
                if not result["ok"]:
                    raise CatalogError("Zemax AGF 安装后的文件核对未通过")
                self.notify(f"已安装到 Zemax · {name} · {report['count']} 种材料",
                            f"位置：{result['path']}\n备份：{result['backup']}\n导出与报告：{output.parent}\n\n" + result["note"])
                self.refresh_zemax()
                return
            self.last_bundle = report["codev_bundle"]
            self.refresh_codev()
            details = (f"已将 {report['catalog']} 库的 {report['count']} 种材料安装到：\n{self.codev_root.text()}\n\n"
                       "玻璃库、材料目录和热光目录已同步，文件核对通过。\n"
                       f"备份：{report['codev_installation']['backup']}\n导出与报告：{output.parent}\n\n"
                       f"轻微透过率超限自动处理：{len(report['transmission_corrections'])} 个点，原值已记录。\n"
                       "请在 CODE V 中查询新库，确认软件识别。")
            self.notify(f"已安装到 CODE V · {report['catalog']} · {report['count']} 种材料", details)
        except (OSError, ValueError, KeyError, ET.ParseError) as exc:
            self.notify("未完成安装", str(exc), "error")

    def uninstall_codev(self):
        catalog = self.selected_codev_catalog()
        if catalog is None:
            return
        try:
            result = codev.uninstall(catalog["catalog"], self.codev_root.text().strip())
            self.refresh_codev()
            self.notify(f"已卸载 CODE V 库 · {result['catalog']}" if result["ok"] else "卸载核对未通过",
                        (f"已移除 {result['count']} 种材料及两张总表中的对应记录。\n备份：{result['backup']}\n"
                         "请在 CODE V 中确认该库已移除。") if result["ok"] else str(result),
                        "success" if result["ok"] else "error")
        except (OSError, ValueError, ET.ParseError) as exc:
            self.notify("未完成卸载", str(exc), "error")

    def update_codev_directory(self):
        self.save_preferences()
        self.refresh_codev()

    def refresh_codev(self):
        root = self.codev_root.text().strip()
        if not root:
            self.codev_catalogs = []
            self.codev_table.setRowCount(0)
            self.codev_count.setText("请先选择 CODE V 安装文件夹")
            self.update_codev_selection()
            return False
        try:
            result = codev.list_catalogs(root)
            self.codev_catalogs = result["catalogs"]
            self.codev_table.setRowCount(len(self.codev_catalogs))
            for row, catalog in enumerate(self.codev_catalogs):
                values = (catalog["catalog"], "—" if catalog["count"] is None else str(catalog["count"]),
                          catalog.get("error") or str(catalog["issues"]), catalog["path"])
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setToolTip(value)
                    self.codev_table.setItem(row, column, item)
            self.codev_count.setText(f"{result['count']} 个玻璃库" if result["exists"] else "未找到 glass 文件夹，请核对安装位置")
            self.update_codev_selection()
            return True
        except OSError as exc:
            self.notify("无法读取 CODE V 目录", str(exc), "error")
            return False

    def update_codev_selection(self):
        catalog = self.selected_codev_catalog()
        self.codev_load_button.setEnabled(catalog is not None and catalog["count"] is not None)
        self.codev_uninstall_button.setEnabled(catalog is not None)

    def selected_codev_catalog(self):
        rows = self.codev_table.selectionModel().selectedRows()
        return self.codev_catalogs[rows[0].row()] if rows else None

    def load_codev_selection(self):
        catalog = self.selected_codev_catalog()
        if catalog is None:
            return
        try:
            source = load_catalog(catalog["path"])
            catalogs = self.expert_catalogs if self.dat_mode else self.catalogs
            if not any(item.source.casefold() == source.source.casefold() for item in catalogs):
                catalogs.append(source)
            self.reset_filters()
            self.show_page("browse")
            self.notify(f"已载入 CODE V 库 · {source.name}", f"{len(source.glasses)} 种材料；可继续筛选和导出。")
        except (OSError, ValueError, ET.ParseError) as exc:
            self.notify("无法载入 CODE V 库", str(exc), "error")

    def choose_zemax_root(self):
        path = QFileDialog.getExistingDirectory(self, "选择 Zemax 实际使用的 Glasscat 文件夹", self.zemax_root.text())
        if path:
            self.zemax_root.setText(path)
            self.update_zemax_directory()

    def update_zemax_directory(self):
        self.zemax_target_summary.setText(self.zemax_root.text().strip())
        self.save_preferences()
        self.refresh_zemax()

    def refresh_zemax(self):
        root = self.zemax_root.text().strip()
        if not root:
            self.notify("请先选择 Zemax Glasscat 文件夹", level="info")
            return False
        try:
            result = zemax.list_catalogs(root)
            self.zemax_catalogs = result["catalogs"]
            self.zemax_table.setRowCount(len(self.zemax_catalogs))
            for row, catalog in enumerate(self.zemax_catalogs):
                values = (catalog["catalog"], "—" if catalog.get("count") is None else str(catalog["count"]),
                          catalog.get("error") or str(catalog["issues"]),
                          "有" if catalog["bgf_cache"] else "待软件生成", catalog["path"])
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    item.setToolTip(value)
                    self.zemax_table.setItem(row, column, item)
            self.zemax_count.setText(f"{result['count']} 个玻璃库" if result["exists"] else "目录尚不存在，安装时创建")
            self.update_zemax_selection()
            return True
        except OSError as exc:
            self.notify("无法读取 Zemax 目录", str(exc), "error")
            return False

    def update_zemax_selection(self):
        enabled = bool(self.zemax_table.selectionModel().selectedRows())
        for widget in (self.zemax_load_button, self.zemax_backup_button, self.zemax_uninstall_button):
            widget.setEnabled(enabled)

    def selected_zemax_catalog(self):
        rows = self.zemax_table.selectionModel().selectedRows()
        return self.zemax_catalogs[rows[0].row()] if rows else None

    def load_zemax_selection(self):
        catalog = self.selected_zemax_catalog()
        if catalog is None:
            return
        try:
            source = load_catalog(catalog["path"])
            if self.dat_mode:
                self.set_output_format("agf")
            if not any(item.source.casefold() == source.source.casefold() for item in self.catalogs):
                self.catalogs.append(source)
            self.reset_filters()
            self.show_page("browse")
            self.notify(f"已载入 Zemax 库 · {source.name}", f"{len(source.glasses)} 种材料；可筛选、组合或转换导出。")
        except (OSError, ValueError) as exc:
            self.notify("无法载入 Zemax 库", str(exc), "error")

    def install_zemax_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "安装已有 Zemax AGF", "", "Zemax 玻璃库 (*.AGF *.agf)")
        if not path:
            return
        try:
            root = self.zemax_root.text().strip()
            if not root:
                raise CatalogError("请选择 Zemax 实际使用的 Glasscat 文件夹")
            result = zemax.install(path, root)
            self.refresh_zemax()
            self.notify(f"已安装 Zemax 库 · {result['catalog']}" if result["ok"] else "文件核对未通过",
                        f"{result['path']}\n备份：{result['backup']}\n\n{result['note']}",
                        "success" if result["ok"] else "error")
        except (OSError, ValueError) as exc:
            self.notify("未完成 Zemax 库安装", str(exc), "error")

    def backup_zemax_selection(self):
        catalog = self.selected_zemax_catalog()
        if catalog is None:
            return
        try:
            result = zemax.backup_catalog(catalog["catalog"], self.zemax_root.text().strip())
            self.notify(f"已备份 Zemax 库 · {result['catalog']}", result["backup"])
        except (OSError, ValueError) as exc:
            self.notify("未完成备份", str(exc), "error")

    def uninstall_zemax_selection(self):
        catalog = self.selected_zemax_catalog()
        if catalog is None:
            return
        try:
            result = zemax.uninstall(catalog["catalog"], self.zemax_root.text().strip())
            self.refresh_zemax()
            self.notify(f"已卸载 Zemax 库 · {result['catalog']}", f"AGF 和 BGF 缓存已移除，备份：{result['backup']}")
        except (OSError, ValueError) as exc:
            self.notify("未完成 Zemax 库卸载", str(exc), "error")

    def restore_zemax(self):
        directory = QFileDialog.getExistingDirectory(self, "选择 Zemax 库备份目录（包含 backup.json）",
                                                      str(Path(self.zemax_root.text()) / "catalog_backups"))
        if not directory:
            return
        try:
            result = zemax.restore(directory, self.zemax_root.text().strip())
            self.refresh_zemax()
            self.notify(f"已恢复 Zemax 库 · {result['catalog']}", f"{result['path']}\n恢复前备份：{result['backup']}")
        except (OSError, ValueError, KeyError) as exc:
            self.notify("未完成 Zemax 库恢复", str(exc), "error")


def create_application():
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Xuplusstar.GlassCatalogManager")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("GlassCatalog")
    app.setApplicationDisplayName("玻璃库管理")
    app.setStyle("windows11")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    return app


def main():
    app = create_application()
    window = GlassCatalogWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
