from __future__ import annotations


GENZ_THEME = {
    "pink": "#ff4fd8",
    "pink_hover": "#ff7ae3",
    "pink_pressed": "#ff2fc9",
    "green": "#39ff14",
    "green_hover": "#6bff4a",
    "green_pressed": "#1ed400",
    "bg": "#f9fff5",
    "panel": "#ffffff",
    "border": "#000000",
}


def gen_z_colors() -> dict[str, str]:
    return {
        "segment": GENZ_THEME["pink"],
        "segment_active": GENZ_THEME["green"],
        "chapter": GENZ_THEME["pink"],
        "comment": GENZ_THEME["green"],
    }


def gen_z_stylesheet() -> str:
    theme = GENZ_THEME
    return f"""
QMainWindow {{
    background: {theme["bg"]};
}}
QWidget {{
    background: {theme["bg"]};
    color: #000000;
}}
QToolBar, QStatusBar {{
    background: {theme["green"]};
    color: #000000;
    border-bottom: 2px solid {theme["border"]};
}}
QToolBar QToolButton {{
    background: {theme["pink"]};
    color: #000000;
    border: 2px solid {theme["border"]};
    border-radius: 6px;
    padding: 4px 8px;
}}
QToolBar QToolButton:hover {{
    background: {theme["pink_hover"]};
}}
QToolBar QToolButton:pressed,
QToolBar QToolButton:checked {{
    background: {theme["green"]};
}}
QPushButton {{
    background: {theme["pink"]};
    color: #000000;
    border: 2px solid {theme["border"]};
    border-radius: 6px;
    padding: 6px 10px;
}}
QPushButton:hover {{
    background: {theme["pink_hover"]};
}}
QPushButton:pressed,
QPushButton:checked {{
    background: {theme["green"]};
}}
QListWidget,
QLineEdit,
QSpinBox,
QDoubleSpinBox,
QComboBox,
QTextEdit {{
    background: {theme["panel"]};
    color: #000000;
    border: 2px solid {theme["border"]};
}}
QListWidget::item:selected {{
    background: {theme["green"]};
    color: #000000;
}}
QListWidget::item:hover {{
    background: {theme["pink_hover"]};
    color: #000000;
}}
QCheckBox {{
    color: #000000;
}}
QSlider::groove:horizontal {{
    height: 6px;
    background: {theme["pink"]};
    border: 2px solid {theme["border"]};
    border-radius: 4px;
}}
QSlider::handle:horizontal {{
    background: {theme["green"]};
    width: 12px;
    margin: -6px 0;
    border: 2px solid {theme["border"]};
    border-radius: 6px;
}}
""".strip()
