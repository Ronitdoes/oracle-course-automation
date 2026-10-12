"""Editorial design tokens + Qt stylesheet.

Minimal, clean, modern-editorial: paper background, ink text, hairline
dividers, serif display type for headings only, sans for UI, one accent.
"""
from __future__ import annotations

PAPER = "#FAFAF7"
SURFACE = "#FFFFFF"
INK = "#1A1A18"
MUTED = "#6B6862"
FAINT = "#9A968E"
HAIRLINE = "#E8E6E1"
WASH = "#F1EFEA"
LOG_BG = "#141412"
LOG_FG = "#E8E6DF"
SUCCESS = "#3F5A3A"
WARN = "#8A6D3B"
DANGER = "#8C2F2F"

DISPLAY_FONT = "Georgia, 'Times New Roman', serif"
BODY_FONT = "'Segoe UI Variable', 'Segoe UI', Inter, system-ui, sans-serif"
MONO_FONT = "'Cascadia Code', Consolas, 'Courier New', monospace"


def stylesheet() -> str:
    return f"""
* {{ font-family: {BODY_FONT}; font-size: 13px; color: {INK}; }}
QMainWindow, QDialog {{ background: {PAPER}; }}
QWidget#NavRail {{ background: {PAPER}; border-right: 1px solid {HAIRLINE}; }}
QLabel#Masthead {{ font-family: {DISPLAY_FONT}; font-size: 26px; color: {INK}; }}
QLabel#PageTitle {{ font-family: {DISPLAY_FONT}; font-size: 21px; color: {INK}; }}
QLabel#Brand {{ font-size: 13px; font-weight: 600; color: {INK}; }}
QLabel#BrandSub {{ font-size: 10px; letter-spacing: 2px; color: {MUTED}; font-weight: 600; }}
QLabel#DisplayLg {{ font-family: {DISPLAY_FONT}; font-size: 34px; color: {INK}; }}
QLabel#Section {{ font-size: 11px; letter-spacing: 2px; color: {MUTED}; font-weight: 600; }}
QLabel#Muted {{ color: {MUTED}; }}
QLabel#Mono {{ font-family: {MONO_FONT}; font-size: 12px; }}
QPushButton#NavBtn {{ text-align: left; padding: 10px 14px; border: none;
  background: transparent; color: {MUTED}; font-size: 13px; border-radius: 6px; }}
QPushButton#NavBtn:hover {{ background: {WASH}; color: {INK}; }}
QPushButton#NavBtn[active="true"] {{ background: {INK}; color: {PAPER}; font-weight: 600; }}
QPushButton#Primary {{ background: {INK}; color: {PAPER}; border: none;
  padding: 9px 18px; border-radius: 6px; font-weight: 600; }}
QPushButton#Primary:hover {{ background: #2E2E2A; }}
QPushButton#Primary:disabled {{ background: {HAIRLINE}; color: {FAINT}; }}
QPushButton#Ghost {{ background: {SURFACE}; color: {INK}; border: 1px solid {HAIRLINE};
  padding: 8px 16px; border-radius: 6px; }}
QPushButton#Ghost:hover {{ border-color: {INK}; }}
QLineEdit, QSpinBox, QComboBox, QTextEdit {{
  background: {SURFACE}; border: 1px solid {HAIRLINE}; border-radius: 6px;
  padding: 8px 10px; selection-background-color: {INK}; selection-color: {PAPER}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {{ border-color: {INK}; }}
QTableWidget {{ background: {SURFACE}; border: 1px solid {HAIRLINE}; border-radius: 6px;
  gridline-color: {HAIRLINE}; alternate-background-color: {PAPER}; }}
QTableWidget::item {{ padding: 4px; }}
QTableWidget::item:selected, QListWidget::item:selected {{
  background: {INK}; color: {PAPER}; }}
QHeaderView::section {{ background: {PAPER}; color: {MUTED}; border: none;
  border-bottom: 1px solid {HAIRLINE}; padding: 8px; font-size: 11px;
  font-weight: 600; text-transform: uppercase; }}
QPlainTextEdit#LogView {{ background: {LOG_BG}; color: {LOG_FG};
  font-family: {MONO_FONT}; font-size: 12px; border: 1px solid {HAIRLINE}; border-radius: 6px; }}
QProgressBar#Rule {{ background: {WASH}; border: none; height: 3px; border-radius: 1px; text-align: center; }}
QProgressBar#Rule::chunk {{ background: {INK}; border-radius: 1px; }}
QLabel#Pill {{ padding: 4px 12px; border-radius: 10px; font-size: 11px; font-weight: 600;
  letter-spacing: 1px; }}
QCheckBox {{ spacing: 8px; }}
QGroupBox {{ border: 1px solid {HAIRLINE}; border-radius: 8px; margin-top: 16px;
  background: {SURFACE}; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 6px; color: {MUTED};
  font-size: 11px; letter-spacing: 2px; }}
"""


def apply_theme(app) -> None:
    app.setStyleSheet(stylesheet())


def pill_style(state: str) -> str:
    """Inline style for the status pill by run state."""
    s = (state or "").upper()
    if s in ("COMPLETED",):
        bg, fg = "#E4EADF", SUCCESS
    elif s in ("FAILED",):
        bg, fg = "#F2DEDE", DANGER
    elif s in ("STOPPED",):
        bg, fg = WASH, MUTED
    elif s in ("AWAIT_APPROVAL", "RECOVER"):
        bg, fg = "#F3EAD2", WARN
    else:
        bg, fg = WASH, INK
    return f"background: {bg}; color: {fg};"
