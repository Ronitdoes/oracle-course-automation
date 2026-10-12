"""Minimal editorial logo: ink rounded square, paper serif 'B'.

Drawn in code (no binary assets) so it stays crisp at any size and works
for the window/taskbar icon plus the in-app wordmark. Matches assets/app.ico
(the exe/installer icon), which is rendered from the same design.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPainter, QPixmap

INK = QColor("#1A1A18")
PAPER = QColor("#FAFAF7")


def logo_pixmap(size: int) -> QPixmap:
    side = max(16, size)
    img = QImage(side, side, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
    radius = side * 0.24
    p.setPen(Qt.NoPen)
    p.setBrush(INK)
    p.drawRoundedRect(0, 0, side, side, radius, radius)
    # Period-free, oversized glyph: stays legible down to 16px taskbar size.
    font = QFont("Georgia", int(side * (0.60 if side <= 32 else 0.56)), QFont.Bold)
    font.setStyleHint(QFont.Serif)
    p.setFont(font)
    p.setPen(PAPER)
    # Slight upward nudge so the serif B sits optically centered.
    p.drawText(0, -int(side * 0.04), side, side, Qt.AlignCenter, "B")
    p.end()
    return QPixmap.fromImage(img)


def build_icon() -> QIcon:
    icon = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(logo_pixmap(s))
    return icon
