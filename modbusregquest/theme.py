# SPDX-License-Identifier: Apache-2.0
from PySide6.QtCore import Qt, QByteArray
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor
from PySide6.QtSvg import QSvgRenderer


PATHS = {
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/>',
    "moon": '<path d="M20.9 13.2A9 9 0 0 1 10.8 3.1a9 9 0 1 0 10.1 10.1Z"/>',
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "devices": '<rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 6.5h.01M7 17.5h.01M12 6.5h5M12 17.5h5"/>',
    "activity": '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    "settings": '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="BG"/><circle cx="15" cy="17" r="3" fill="BG"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "play": '<path d="m8 5 11 7-11 7Z"/>',
    "pause": '<path d="M8 5v14M16 5v14"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4 4"/>',
    "arrow_down": '<path d="M12 3v12m-5-5 5 5 5-5M4 17v4h16v-4"/>',
    "arrow_up": '<path d="M12 15V3m-5 5 5-5 5 5M4 17v4h16v-4"/>',
    "more": '<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    "check": '<path d="m5 12 4 4L19 6"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "bolt": '<path d="m13 2-9 12h7l-1 8 10-13h-7Z"/>',
    "shield": '<path d="M12 3 4 6v6c0 5 8 9 8 9s8-4 8-9V6Z"/><path d="m8 12 3 3 5-6"/>',
    "database": '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><path d="M14 2v6h6M8 13h8M8 17h5"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><ellipse cx="12" cy="12" rx="4" ry="9"/><path d="M3 12h18"/>',
    "warning": '<path d="m12 3 10 18H2Z"/><path d="M12 9v5m0 3h.01"/>',
    "network": '<rect x="8" y="2" width="8" height="6" rx="1"/><rect x="2" y="16" width="7" height="6" rx="1"/><rect x="15" y="16" width="7" height="6" rx="1"/><path d="M12 8v4M5.5 16v-4h13v4"/>',
}


def icon(name, color="#738198", size=18, background="none"):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{PATHS.get(name, PATHS["grid"]).replace("BG", background)}</svg>'
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


STYLE = """
QWidget { color: #1B293C; font-family: 'Inter', 'SF Pro Text', 'DejaVu Sans'; font-size: 13px; }
QMainWindow, QDialog { background: #F5F7FA; }
QWidget#content { background: #F5F7FA; }
QWidget#editorBody { background: #F5F7FA; }
QFrame#sidebar { background: #111C2E; border: none; }
QLabel#brand { color: #F5F9FF; font-size: 21px; font-weight: 700; letter-spacing: -0.6px; }
QLabel#brandSub { color: #7F90A9; font-size: 10px; letter-spacing: 2px; }
QLabel#navTitle { color: #60728E; font-size: 10px; font-weight: 600; letter-spacing: 1.5px; }
QPushButton#nav { text-align: left; color: #91A1BA; border: none; background: transparent; border-radius: 8px; padding: 12px 14px; font-weight: 500; }
QPushButton#nav:hover { background: #1B2A40; color: #E2EDF9; }
QPushButton#nav:checked { background: #173A40; color: #6EE7CB; }
QFrame#sidebarBottom { background: #18263B; border-radius: 10px; }
QLabel#sidebarLabel { color: #B3C1D4; font-size: 11px; }
QLabel#sidebarMuted { color: #7385A0; font-size: 10px; }
QLabel#title { font-size: 28px; font-weight: 700; letter-spacing: -0.8px; color: #142235; }
QLabel#subtitle { color: #7C899C; font-size: 13px; }
QLabel#sectionTitle { font-size: 17px; font-weight: 650; }
QLabel#muted { color: #8490A2; font-size: 12px; }
QLabel#eyebrow { color: #8A97A9; font-size: 10px; font-weight: 600; letter-spacing: 1.2px; }
QLabel#metric { font-size: 30px; font-weight: 650; color: #17263B; letter-spacing: -1px; }
QLabel#metricHint { color: #8B97A8; font-size: 11px; }
QFrame#card { background: white; border: 1px solid #E6EAF0; border-radius: 12px; }
QFrame#tableCard { background: white; border: 1px solid #E6EAF0; border-radius: 12px; }
QFrame#separator { background: #E9EDF3; border: none; max-height: 1px; }
QPushButton { background: white; border: 1px solid #DFE5ED; border-radius: 7px; padding: 9px 14px; font-weight: 550; }
QPushButton:hover { background: #F0F4F8; border-color: #C7D1DF; }
QPushButton:pressed { background: #E5ECF3; }
QPushButton:disabled { color: #A8B1BF; background: #F3F5F8; border-color: #E7EBF1; }
QPushButton#primary { color: white; background: #0C9B80; border-color: #0C9B80; }
QPushButton#primary:hover { background: #08866E; border-color: #08866E; }
QPushButton#primary:disabled { background: #A4CFC5; border-color: #A4CFC5; }
QPushButton#stop { color: #BC4A48; background: #FFF3F1; border-color: #F3D8D5; }
QPushButton#ghost { border: none; background: transparent; color: #7A889C; padding: 6px; }
QPushButton#ghost:hover { background: #EEF3F7; color: #263B54; }
QPushButton#danger { color: #C34F50; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #FFFFFF; border: 1px solid #DFE5ED; border-radius: 7px; min-height: 20px; padding: 8px 10px; selection-background-color: #0C9B80; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: #0C9B80; }
QSpinBox QLineEdit, QDoubleSpinBox QLineEdit { border: none; padding: 0px; min-height: 0px; background: transparent; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0px; border: none; }
QSpinBox:disabled, QDoubleSpinBox:disabled { background: #F0F3F7; }
QSpinBox:disabled QLineEdit, QDoubleSpinBox:disabled QLineEdit { color: #A0ACBC; }
QLineEdit#search { background: #F8FAFC; border-color: #E7EBF1; padding-left: 10px; }
QComboBox { padding-right: 23px; }
QComboBox::drop-down { border: none; width: 21px; }
QComboBox QAbstractItemView { background: white; selection-background-color: #DFF3ED; selection-color: #146552; border: 1px solid #DFE5ED; padding: 4px; }
QTableWidget { background: white; border: none; gridline-color: #EDF0F5; selection-background-color: #F0F9F6; selection-color: #17263B; outline: none; }
QTableWidget::item { padding: 10px 8px; border-bottom: 1px solid #EDF0F5; }
QTableWidget::item:selected { background: #EEF8F5; }
QHeaderView::section { background: #FAFBFD; color: #8995A7; font-size: 11px; font-weight: 500; border: none; border-bottom: 1px solid #E8ECF2; padding: 12px 8px; text-align: left; }
QTableCornerButton::section { background: #FAFBFD; border: none; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 0; }
QScrollBar::handle:vertical { background: #D9E1EA; min-height: 30px; border-radius: 4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 8px; }
QScrollBar::handle:horizontal { background: #D9E1EA; min-width: 30px; border-radius: 4px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QCheckBox { spacing: 9px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #CDD6E2; border-radius: 5px; background: white; }
QCheckBox::indicator:checked { background: #0C9B80; border-color: #0C9B80; image: none; }
QToolTip { background: #18263B; color: #EDF5FF; border: none; padding: 6px 10px; border-radius: 4px; }
QMenu { background: white; border: 1px solid #DFE5ED; border-radius: 8px; padding: 5px; }
QMenu::item { padding: 8px 24px 8px 12px; border-radius: 4px; }
QMenu::item:selected { background: #EAF6F1; }
QMessageBox { background: #F5F7FA; }
QScrollArea { border: none; background: transparent; }
QLabel#pill { color: #13836B; background: #E9F7F1; border-radius: 5px; padding: 5px 9px; font-size: 11px; font-weight: 550; }
QLabel#demoPill { color: #9B7620; background: #FFF6DD; border-radius: 4px; padding: 4px 7px; font-size: 10px; font-weight: 600; }
QLabel#toast { color: #14735E; background: #E6F6EF; border: 1px solid #C6E9DC; padding: 10px 16px; border-radius: 7px; }
"""

# Semantic light → dark palette, shared by stylesheets and painted table cells.
DARK_COLORS = {
    "#F5F7FA": "#0E1726", "#FFFFFF": "#172438", "#FFFFFF00": "#FFFFFF00",
    "#1B293C": "#DDE7F4", "#142235": "#EDF4FE", "#17263B": "#EDF4FE",
    "#E6EAF0": "#2A3A51", "#DFE5ED": "#34475F", "#E7EBF1": "#2B3D55",
    "#E9EDF3": "#2A3A51", "#EDF0F5": "#26364C", "#E8ECF2": "#2A3A51",
    "#FAFBFD": "#142034", "#F8FAFC": "#122035", "#F0F4F8": "#24364F",
    "#C7D1DF": "#466078", "#E5ECF3": "#2A3D56", "#F3F5F8": "#172438",
    "#F0F3F7": "#142034", "#F0F9F6": "#173B3B", "#EEF8F5": "#173B3B",
    "#EEF3F7": "#24364F", "#EAF6F1": "#1D3D3E", "#DFF3ED": "#1D3D3E",
    "#E9F7F1": "#173B3B", "#14735E": "#71E5C5", "#13836B": "#71E5C5",
    "#E6F6EF": "#173B3B", "#C6E9DC": "#285D53", "#FFF3F1": "#3D282F",
    "#F3D8D5": "#6D3D47", "#BC4A48": "#F39492", "#FFF6DD": "#3D3422",
    "#9B7620": "#E5C47B", "#344C64": "#D9E6F5", "#52647C": "#B7CAE0",
    "#697D95": "#A8BCD4", "#0E9B7C": "#5ADDB9", "#0C9B80": "#11A88A",
    "#7B889C": "#A5B5CA", "#738198": "#A5B5CA", "#76869C": "#A5B5CA",
    "#8290A3": "#A5B5CA", "#8390A3": "#A5B5CA", "#8490A2": "#9AACBF",
    "#7C899C": "#9AACBF", "#8B97A8": "#9AACBF", "#8995A7": "#9AACBF",
}


def themed_color(color, theme):
    return DARK_COLORS.get(color.upper(), color) if theme == "dark" else color


def apply_theme(app, theme):
    from PySide6.QtGui import QPalette
    import re
    palette = QPalette()
    dark = theme == "dark"
    for role, value in ((QPalette.ColorRole.Window, "#0E1726" if dark else "#F5F7FA"),
        (QPalette.ColorRole.Base, "#172438" if dark else "#FFFFFF"),
        (QPalette.ColorRole.WindowText, "#DDE7F4" if dark else "#1B293C"),
        (QPalette.ColorRole.Text, "#DDE7F4" if dark else "#1B293C"),
        (QPalette.ColorRole.Button, "#172438" if dark else "#FFFFFF"),
        (QPalette.ColorRole.ButtonText, "#DDE7F4" if dark else "#1B293C"),
        (QPalette.ColorRole.Highlight, "#0C9B80"),
        (QPalette.ColorRole.HighlightedText, "#FFFFFF")):
        palette.setColor(role, QColor(value))
    app.setPalette(palette)
    if dark:
        style = re.sub(r"#[0-9A-Fa-f]{6}", lambda match: themed_color(match[0], theme), STYLE)
        # Explicit white text stays white on primary action buttons.
        style += "\nQPushButton#primary { color: #FFFFFF; }"
        style = style.replace("background: white", "background: #172438").replace("color: white", "color: #FFFFFF")
    else:
        style = STYLE
    app.setStyleSheet(style + "\nQPlainTextEdit { border: none; padding: 10px; background: transparent; } QTabWidget::pane { border: none; } QTabBar::tab { padding: 9px 14px; } QSplitter::handle { background: transparent; }")

STYLE += """
QFrame#byteGroup { border: 1px solid #DFE5ED; border-radius: 7px; background: #F8FAFC; }
QFrame#byteGroupData { border: 1px solid #C6E9DC; border-radius: 7px; background: #E9F7F1; }
"""
STYLE += """
QTabBar { qproperty-drawBase: 0; }
QTabBar::tab { border: none; border-bottom: 2px solid transparent; padding: 8px 12px; background: transparent; color: #8290A3; }
QTabBar::tab:selected { color: #0C9B80; border-bottom: 2px solid #0C9B80; background: #E9F7F1; }
QTabBar::tab:hover { background: #F0F4F8; }
"""
