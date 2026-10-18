#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Steam Syncer GUI — Windows 11 Fluent Design Application (DeckBridge)
Modern desktop interface for synchronizing local non-Steam games to Steam
and downloading official artwork from Valve's CDN.
"""

import os
import sys
import json
import logging
import traceback
import subprocess
import math
import time
import tempfile
from typing import List, Optional, Dict, Any, Tuple

import requests
from PIL import Image

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer, QPropertyAnimation, QEasingCurve, QPointF, QEvent, QRectF, QUrl
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QPainterPath, QColor, QTransform, QRadialGradient, QPen, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QFileDialog, QListWidget, QListWidgetItem, QFrame,
    QGridLayout, QSpacerItem, QSizePolicy, QGraphicsOpacityEffect,
    QStackedWidget, QPushButton, QLabel
)
from qfluentwidgets import (
    FluentWindow, NavigationItemPosition,
    PrimaryPushButton, PushButton, ToolButton, TransparentToolButton,
    CardWidget, SimpleCardWidget, HeaderCardWidget,
    ProgressBar, InfoBar, InfoBarPosition,
    LineEdit, ComboBox, SwitchButton, TextEdit, CheckBox,
    TitleLabel, SubtitleLabel, BodyLabel, CaptionLabel, StrongBodyLabel,
    ScrollArea, FluentIcon as FIF, setTheme, Theme, isDarkTheme,
    setThemeColor, themeColor, IconWidget, SmoothMode, MessageBoxBase,
    FlowLayout
)

import steam_syncer
import i18n
from i18n import tr

APP_VERSION = "1.0.0"
logger = logging.getLogger("SteamSyncerGUI")


def configure_high_dpi():
    """
    Configures High DPI scale factor rounding policy and OpenGL hardware acceleration
    prior to QApplication initialization, enabling maximum display FPS (120Hz/144Hz/165Hz/240Hz)
    and tear-free Windows 11 DWM presentation.
    """
    try:
        if hasattr(Qt, 'HighDpiScaleFactorRoundingPolicy'):
            QApplication.setHighDpiScaleFactorRoundingPolicy(
                Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
            )
        if hasattr(Qt, 'ApplicationAttribute'):
            if hasattr(Qt.ApplicationAttribute, 'AA_UseDesktopOpenGL'):
                QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseDesktopOpenGL, True)
            if hasattr(Qt.ApplicationAttribute, 'AA_ShareOpenGLContexts'):
                QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    except Exception as e:
        logger.debug(f"High DPI / GPU configuration notice: {e}")


_GLOBAL_QT_APP = None

def get_or_create_qapp() -> QApplication:
    """
    Returns existing QApplication or creates a persistent process-wide instance.
    Prevents premature Python garbage collection of QApplication between tests.
    """
    global _GLOBAL_QT_APP
    app = QApplication.instance()
    if app is None:
        if _GLOBAL_QT_APP is not None:
            app = _GLOBAL_QT_APP
        else:
            argv = sys.argv if sys.argv else ['DeckBridge']
            _GLOBAL_QT_APP = QApplication(argv)
            app = _GLOBAL_QT_APP
    else:
        _GLOBAL_QT_APP = app

    try:
        if os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
            app.setQuitOnLastWindowClosed(False)
    except Exception:
        pass

    return app


def ensure_qfluentwidgets_alive(app=None):
    """
    Guarantees that QFluentWidgets global singletons (qconfig, qrouter) remain bound to
    the QApplication lifetime and are never deleted during child window teardown
    or multi-suite test execution.
    """
    try:
        app = app or QApplication.instance()

        # 1. Ensure qconfig is alive and parented
        import qfluentwidgets.common.config as qc
        is_config_alive = False
        if getattr(qc, 'qconfig', None) is not None:
            try:
                _ = qc.qconfig.themeChanged
                is_config_alive = True
            except RuntimeError:
                is_config_alive = False
        if not is_config_alive:
            new_cfg = qc.QConfig()
            qc.qconfig = new_cfg
            for mod_name in list(sys.modules.keys()):
                if mod_name and mod_name.startswith('qfluentwidgets'):
                    mod = sys.modules[mod_name]
                    if hasattr(mod, 'qconfig'):
                        setattr(mod, 'qconfig', new_cfg)
        if app and qc.qconfig:
            try:
                if not qc.qconfig.parent():
                    qc.qconfig.setParent(app)
            except Exception:
                pass

        # 2. Ensure qrouter is alive and parented
        import qfluentwidgets.common.router as qr
        is_router_alive = False
        if getattr(qr, 'qrouter', None) is not None:
            try:
                _ = qr.qrouter.emptyChanged
                is_router_alive = True
            except RuntimeError:
                is_router_alive = False
        if not is_router_alive:
            new_router = qr.Router()
            qr.qrouter = new_router
            for mod_name in list(sys.modules.keys()):
                if mod_name and mod_name.startswith('qfluentwidgets'):
                    mod = sys.modules[mod_name]
                    if hasattr(mod, 'qrouter'):
                        setattr(mod, 'qrouter', new_router)
        if app and qr.qrouter:
            try:
                if not qr.qrouter.parent():
                    qr.qrouter.setParent(app)
            except Exception:
                pass

        if app:
            try:
                if os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
                    app.setQuitOnLastWindowClosed(False)
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"ensure_qfluentwidgets_alive notice: {e}")

ensure_qconfig_alive = ensure_qfluentwidgets_alive


def get_base_dir() -> str:
    if getattr(sys, 'frozen', False):
        return getattr(sys, '_MEIPASS', os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))

BASE_DIR = get_base_dir()

def get_app_data_dir() -> str:
    local_app_data = os.environ.get('LOCALAPPDATA')
    if not local_app_data:
        if sys.platform == 'win32':
            local_app_data = os.path.join(os.path.expanduser('~'), 'AppData', 'Local')
        else:
            xdg_data = os.environ.get('XDG_DATA_HOME')
            local_app_data = xdg_data if xdg_data else os.path.join(os.path.expanduser('~'), '.local', 'share')
    deckbridge_dir = os.path.join(local_app_data, 'DeckBridge')
    return deckbridge_dir

DECKBRIDGE_DATA_DIR = get_app_data_dir()
try:
    os.makedirs(DECKBRIDGE_DATA_DIR, exist_ok=True)
except Exception as e:
    logger.debug(f"Could not create DeckBridge data directory: {e}")

COVERS_CACHE_DIR = os.path.join(DECKBRIDGE_DATA_DIR, "covers_cache")
try:
    os.makedirs(COVERS_CACHE_DIR, exist_ok=True)
except Exception as e:
    logger.debug(f"Could not create covers_cache directory: {e}")

def get_default_config_path() -> str:
    for candidate_dir in (
        os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else None,
        BASE_DIR
    ):
        if candidate_dir:
            portable_cfg = os.path.join(candidate_dir, "config.json")
            if os.path.isfile(portable_cfg):
                try:
                    if os.access(candidate_dir, os.W_OK):
                        return portable_cfg
                except Exception:
                    pass
    return os.path.join(DECKBRIDGE_DATA_DIR, "config.json")

CONFIG_PATH = get_default_config_path()


class CloseSteamButton(QPushButton):
    """
    Dedicated Close Steam button using an internal QHBoxLayout with IconWidget and QLabel.
    Guarantees mathematically that the 'X' icon and text NEVER overlap under any language or scaling.
    """
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setFixedSize(235, 40)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(14, 0, 14, 0)
        self._layout.setSpacing(8)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.icon_widget = IconWidget(FIF.CLOSE, self)
        self.icon_widget.setFixedSize(14, 14)
        self.icon_widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.lbl_text = QLabel(text, self)
        self.lbl_text.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.lbl_text.setStyleSheet("font-weight: 600; font-size: 13px; color: #ffffff; background: transparent;")

        self._layout.addWidget(self.icon_widget)
        self._layout.addWidget(self.lbl_text)

        self.setStyleSheet("""
            CloseSteamButton {
                border: 1px solid rgba(239, 83, 80, 0.75);
                border-radius: 6px;
                background-color: rgba(229, 57, 53, 0.24);
                color: #ffffff;
            }
            CloseSteamButton QLabel {
                color: #ffffff;
            }
            CloseSteamButton:hover {
                border: 1px solid rgba(239, 83, 80, 0.95);
                background-color: rgba(229, 57, 53, 0.40);
                color: #ffffff;
            }
            CloseSteamButton:pressed {
                background-color: rgba(229, 57, 53, 0.55);
                color: #ffffff;
            }
            CloseSteamButton:disabled {
                border-color: rgba(255, 255, 255, 0.1);
                color: rgba(255, 255, 255, 0.35);
                background-color: transparent;
            }
        """)

    def setText(self, text: str):
        self.lbl_text.setText(text)

    def text(self) -> str:
        return self.lbl_text.text()


class SteamStatusDot(QWidget):
    """
    TitleBar status indicator showing Steam status:
    - Green dot: Steam is closed / ready for safe write.
    - Amber/Red dot: Steam is active (blocker).
    - Pulsing glow: Actively scanning or synchronizing.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(32, 32)
        self._is_running = False
        self._is_pulsing = False
        self._pulse_phase = 0.0
        self._pulse_start_time = 0.0
        self._pending_stop = False
        self.clicked_callback = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr("steam_dot_ready"))

        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(25)
        self._pulse_timer.timeout.connect(self._on_pulse_tick)

    def _on_pulse_tick(self):
        self._pulse_phase += 0.08
        if self._pulse_phase > 2 * math.pi:
            self._pulse_phase -= 2 * math.pi
        self.update()

    def set_pulsing(self, pulsing: bool, delayed: bool = False):
        if pulsing:
            self._pulse_start_time = time.monotonic()
            self._pending_stop = False
            if not self._is_pulsing:
                self._is_pulsing = True
                self.setToolTip(tr("steam_dot_scanning"))
                if not self._pulse_timer.isActive():
                    self._pulse_timer.start()
                self.update()
        else:
            if delayed:
                elapsed = time.monotonic() - getattr(self, '_pulse_start_time', 0.0)
                if elapsed < 1.0:
                    self._pending_stop = True
                    remaining_ms = int(max(50, (1.0 - elapsed) * 1000))
                    QTimer.singleShot(remaining_ms, self._on_delayed_stop_pulse)
                    return
            self._stop_pulse()

    def _on_delayed_stop_pulse(self):
        if getattr(self, '_pending_stop', False):
            self._stop_pulse()

    def _stop_pulse(self):
        self._pending_stop = False
        if self._is_pulsing:
            self._is_pulsing = False
            if self._pulse_timer.isActive():
                self._pulse_timer.stop()
            self.setToolTip(tr("steam_dot_running") if self._is_running else tr("steam_dot_ready"))
            self.update()

    def set_running_state(self, is_running: bool):
        self._is_running = is_running
        if not self._is_pulsing:
            self.setToolTip(tr("steam_dot_running") if is_running else tr("steam_dot_ready"))
        self.update()

    def hideEvent(self, event):
        if hasattr(self, '_pulse_timer') and self._pulse_timer.isActive():
            self._pulse_timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        if getattr(self, '_is_pulsing', False) and hasattr(self, '_pulse_timer') and not self._pulse_timer.isActive():
            self._pulse_timer.start()
        super().showEvent(event)

    def mousePressEvent(self, event):
        if self.clicked_callback:
            self.clicked_callback()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx, cy = self.width() / 2.0, self.height() / 2.0
        painter.setPen(Qt.PenStyle.NoPen)

        if self._is_pulsing:
            pulse_val = (math.sin(self._pulse_phase) + 1.0) / 2.0
            glow_alpha = int(40 + 75 * pulse_val)
            glow_radius = 8.0 + 4.0 * pulse_val
            painter.setBrush(QColor(76, 175, 80, glow_alpha))
            painter.drawEllipse(QPointF(cx, cy), glow_radius, glow_radius)

            painter.setBrush(QColor("#81c784"))
            painter.drawEllipse(QPointF(cx, cy), 4.5, 4.5)
        else:
            if self._is_running:
                painter.setBrush(QColor(239, 83, 80, 45))
                painter.drawEllipse(QPointF(cx, cy), 8.0, 8.0)
                painter.setBrush(QColor("#ff5252"))
                painter.drawEllipse(QPointF(cx, cy), 4.0, 4.0)
            else:
                painter.setBrush(QColor(76, 175, 80, 45))
                painter.drawEllipse(QPointF(cx, cy), 8.0, 8.0)
                painter.setBrush(QColor("#81c784"))
                painter.drawEllipse(QPointF(cx, cy), 4.0, 4.0)


class DraggableSwitchButton(SwitchButton):
    """
    Windows 11 Fluent ToggleSwitch supporting interactive pointer dragging of the indicator thumb.
    Allows both native drag interaction (swiping the dot left/right) and standard click-to-toggle.
    """
    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._drag_start_x = 0.0
        self._initial_slider_x = 5.0
        self._is_dragging = False
        self.indicator.installEventFilter(self)

    def eventFilter(self, obj, e: QEvent):
        if not self.isEnabled():
            return super().eventFilter(obj, e)

        if obj in (self, self.indicator):
            if e.type() == QEvent.Type.MouseButtonPress and e.button() == Qt.MouseButton.LeftButton:
                self._drag_start_x = e.globalPosition().x()
                self._initial_slider_x = float(self.indicator.sliderX)
                self._is_dragging = False
                self.indicator.slideAni.stop()
                self.indicator.setDown(True)
                return True
            elif e.type() == QEvent.Type.MouseMove and (e.buttons() & Qt.MouseButton.LeftButton):
                dx = e.globalPosition().x() - self._drag_start_x
                if abs(dx) >= 3 or self._is_dragging:
                    self._is_dragging = True
                    new_x = max(5.0, min(25.0, self._initial_slider_x + dx))
                    self.indicator.setSliderX(new_x)
                    return True
            elif e.type() == QEvent.Type.MouseButtonRelease and e.button() == Qt.MouseButton.LeftButton:
                self.indicator.setDown(False)
                if self._is_dragging:
                    self._is_dragging = False
                    target = (self.indicator.sliderX >= 15.0)
                    if target != self.isChecked():
                        self.setChecked(target)
                    else:
                        self.indicator.slideAni.setEndValue(25 if target else 5)
                        self.indicator.slideAni.start()
                    return True
                else:
                    self.toggleChecked()
                    return True

        return super().eventFilter(obj, e)


class TiltPosterLabel(CaptionLabel):
    """
    Vertical game poster thumbnail with ultra-neat 3D tilt perspective,
    soft depth drop shadow, and dynamic specular sheen (Apple TV / Steam Deck style).
    Maintains exact 80x120 footprint with aspect-ratio preserving centered crop.
    """
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(80, 120)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pixmap = None
        self._text = ''

        # 3D Tilt angles and scale
        self._rot_x = 0.0
        self._rot_y = 0.0
        self._scale = 1.0

        # Targets for smooth physics lerp
        self._target_rot_x = 0.0
        self._target_rot_y = 0.0
        self._target_scale = 1.0

        # Cursor normalized coordinates for specular light reflection
        self._norm_x = 0.0
        self._norm_y = 0.0
        self._is_hovered = False

        # Physics interpolation timer synced to display refresh rate
        self._timer = QTimer(self)
        screen = QApplication.primaryScreen()
        hz = 60
        if screen:
            try:
                hz = int(round(screen.refreshRate()))
            except Exception:
                hz = 60
        hz = max(60, min(240, hz))
        self._timer.setInterval(max(5, int(1000.0 / hz)))
        self._timer.timeout.connect(self._on_tick)

    def setPixmap(self, pixmap: QPixmap):
        self._pixmap = pixmap
        super().setPixmap(pixmap)
        self.update()

    def setText(self, text: str):
        self._text = text
        super().setText(text)
        self.update()

    def enterEvent(self, event):
        self._is_hovered = True
        self._target_scale = 1.04
        if not self._timer.isActive():
            self._timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._is_hovered = False
        self._target_rot_x = 0.0
        self._target_rot_y = 0.0
        self._target_scale = 1.0
        self._norm_x = 0.0
        self._norm_y = 0.0
        if not self._timer.isActive():
            self._timer.start()
        super().leaveEvent(event)

    def mouseMoveEvent(self, event):
        if not self._is_hovered:
            self._is_hovered = True
            self._target_scale = 1.04

        pos = event.position()
        w, h = float(self.width()), float(self.height())
        nx = (pos.x() - w / 2.0) / (w / 2.0)
        ny = (pos.y() - h / 2.0) / (h / 2.0)
        self._norm_x = max(-1.0, min(1.0, nx))
        self._norm_y = max(-1.0, min(1.0, ny))

        max_tilt = 8.0  # Subtle, elegant 8-degree maximum tilt
        self._target_rot_y = self._norm_x * max_tilt
        self._target_rot_x = -self._norm_y * max_tilt

        if not self._timer.isActive():
            self._timer.start()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def hideEvent(self, event):
        if hasattr(self, '_timer') and self._timer.isActive():
            self._timer.stop()
        super().hideEvent(event)

    def _on_tick(self):
        easing = 0.22
        self._rot_x += (self._target_rot_x - self._rot_x) * easing
        self._rot_y += (self._target_rot_y - self._rot_y) * easing
        self._scale += (self._target_scale - self._scale) * easing

        # Settle to idle state and stop timer to preserve 0% idle CPU
        if not self._is_hovered and abs(self._rot_x) < 0.02 and abs(self._rot_y) < 0.02 and abs(self._scale - 1.0) < 0.002:
            self._rot_x = 0.0
            self._rot_y = 0.0
            self._scale = 1.0
            self._timer.stop()

        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(
            QPainter.RenderHint.Antialiasing |
            QPainter.RenderHint.SmoothPixmapTransform
        )

        w, h = float(self.width()), float(self.height())
        card_w, card_h = 76.0, 116.0
        card_rect = QRectF(-card_w / 2.0, -card_h / 2.0, card_w, card_h)

        # 3D perspective transformation
        t = QTransform()
        t.translate(w / 2.0, h / 2.0)
        t.scale(self._scale, self._scale)

        perspective = 0.0010
        t.setMatrix(
            t.m11(), t.m12(), t.m13(),
            t.m21(), t.m22(), t.m23(),
            t.m31() - (self._rot_y * perspective),
            t.m32() + (self._rot_x * perspective),
            t.m33()
        )
        t.rotate(self._rot_y, Qt.Axis.YAxis)
        t.rotate(self._rot_x, Qt.Axis.XAxis)

        painter.setTransform(t)

        # 1. Soft depth drop shadow
        if self._is_hovered or self._scale > 1.0 or abs(self._rot_x) > 0.5 or abs(self._rot_y) > 0.5:
            s_dx = self._rot_y * 0.20
            s_dy = 2.0 - self._rot_x * 0.20
            path_s1 = QPainterPath()
            path_s1.addRoundedRect(card_rect.translated(s_dx, s_dy + 1.0), 6.0, 6.0)
            painter.fillPath(path_s1, QColor(0, 0, 0, 45))
            path_s2 = QPainterPath()
            path_s2.addRoundedRect(card_rect.translated(s_dx * 0.5, s_dy), 6.0, 6.0)
            painter.fillPath(path_s2, QColor(0, 0, 0, 80))

        # 2. Base rounded card path & artwork
        base_path = QPainterPath()
        base_path.addRoundedRect(card_rect, 6.0, 6.0)

        painter.save()
        painter.setClipPath(base_path)

        if self._pixmap and not self._pixmap.isNull():
            pw, ph = float(self._pixmap.width()), float(self._pixmap.height())
            if pw > 0 and ph > 0:
                # Aspect-ratio preserving centered crop (guarantees square/wide covers like 007 never squash)
                target_ar = card_w / card_h
                src_ar = pw / ph
                if src_ar > target_ar:
                    crop_h = ph
                    crop_w = ph * target_ar
                    crop_x = (pw - crop_w) / 2.0
                    crop_y = 0.0
                else:
                    crop_w = pw
                    crop_h = pw / target_ar
                    crop_x = 0.0
                    crop_y = (ph - crop_h) / 2.0
                src_rect = QRectF(crop_x, crop_y, crop_w, crop_h)
                painter.drawPixmap(card_rect, self._pixmap, src_rect)
            else:
                painter.drawPixmap(card_rect, self._pixmap, QRectF(self._pixmap.rect()))
        else:
            painter.fillRect(card_rect, QColor(36, 36, 44))
            painter.setPen(QColor(255, 255, 255, 180))
            f = painter.font()
            f.setPointSize(22)
            painter.setFont(f)
            painter.drawText(card_rect, Qt.AlignmentFlag.AlignCenter, self._text or "🎮")

        # 3. Dynamic specular highlight on hover
        if self._is_hovered:
            gx = card_rect.left() + (self._norm_x + 1.0) * (card_w / 2.0)
            gy = card_rect.top() + (self._norm_y + 1.0) * (card_h / 2.0)
            radial = QRadialGradient(gx, gy, 70.0)
            radial.setColorAt(0.0, QColor(255, 255, 255, 65))
            radial.setColorAt(0.5, QColor(255, 255, 255, 20))
            radial.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(card_rect, radial)

        painter.restore()

        # 4. Subtle crisp border
        border_alpha = 70 if self._is_hovered else 30
        painter.setPen(QPen(QColor(255, 255, 255, border_alpha), 1.0))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(base_path)


def setup_high_hz_smooth_scroll(scroll_area: ScrollArea):
    """
    Configures smooth scrolling to match the user's native monitor refresh rate (e.g. 144-240 Hz).
    Enables hardware-accelerated QPropertyAnimation to eliminate frame caps, float-step
    reverse-bounce bugs, and deceleration drag.
    """
    screen = QApplication.primaryScreen()
    hz = 60
    if screen:
        try:
            hz = int(round(screen.refreshRate()))
        except Exception:
            hz = 60
    hz = max(60, min(360, hz))

    delegate = getattr(scroll_area, 'scrollDelagate', None) or getattr(scroll_area, 'delegate', None)
    if not delegate:
        return

    # Enable native QPropertyAnimation for silky smooth, bounce-free scrolling synchronized with display Hz
    delegate.useAni = True
    if hasattr(delegate, 'vScrollBar') and delegate.vScrollBar:
        delegate.vScrollBar.setScrollAnimation(duration=200, easing=QEasingCurve.Type.OutCubic)
        delegate.vScrollBar.setSingleStep(24)

    vs = getattr(delegate, 'verticalSmoothScroll', None)
    if not vs:
        return

    for engine in (getattr(vs, 'fixedStepScrollEngine', None), getattr(vs, 'adaptiveScrollEngine', None)):
        if engine:
            engine.fps = hz
            engine.duration = 140
            engine.stepRatio = 1.3
            engine.acceleration = 1
            if hasattr(engine, 'minDuration'):
                engine.minDuration = 80

    # Safety patch on fixedStepScrollEngine against QFluentWidgets float division bounce bug
    f_engine = getattr(vs, 'fixedStepScrollEngine', None)
    if f_engine:
        orig_wheel = f_engine.wheelEvent
        def _safe_wheel(e, delta, eng=f_engine):
            orig_wheel(e, delta)
            eng.stepsTotal = max(1, int(round(eng.stepsTotal)))
            if eng.stepsLeftQueue:
                eng.stepsLeftQueue[-1][1] = eng.stepsTotal
        f_engine.wheelEvent = _safe_wheel

        def _safe_getTotalDelta(eng=f_engine):
            totalDelta = 0
            for i in eng.stepsLeftQueue:
                totalDelta += eng._subDelta(i[0], max(0, i[1]))
                i[1] -= 1
            while eng.stepsLeftQueue and eng.stepsLeftQueue[0][1] <= 0:
                eng.stepsLeftQueue.popleft()
            return totalDelta
        f_engine._getTotalDelta = _safe_getTotalDelta

    scroll_area.verticalScrollBar().setSingleStep(24)



def format_file_size(bytes_size: int) -> str:
    """Formats file size into human-readable binary units."""
    if bytes_size >= 1024 * 1024 * 1024:
        return f"{bytes_size / (1024 ** 3):.1f} GB"
    elif bytes_size >= 1024 * 1024:
        return f"{bytes_size / (1024 ** 2):.1f} MB"
    elif bytes_size >= 1024:
        return f"{bytes_size / 1024:.0f} KB"
    return f"{bytes_size} B"


def get_windows_accent_color() -> Optional[QColor]:
    """
    Retrieves active Windows 11 system accent color from Windows Registry / DWM.
    Prioritizes dark/light calibrated AccentPalette shades for WCAG 2.1 AA readability.
    """
    if sys.platform != "win32":
        return None

    # Method 1: Query HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Accent\AccentPalette
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\Accent") as key:
            palette, _ = winreg.QueryValueEx(key, "AccentPalette")
            if len(palette) >= 16:
                pr, pg, pb = palette[12:15]
                if pr or pg or pb:
                    return QColor(pr, pg, pb)
    except Exception:
        pass

    # Method 2: Query HKCU\Software\Microsoft\Windows\DWM\AccentColor (DWORD in ABGR)
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\DWM") as key:
            val, _ = winreg.QueryValueEx(key, "AccentColor")
            r = val & 0xFF
            g = (val >> 8) & 0xFF
            b = (val >> 16) & 0xFF
            if r or g or b:
                return QColor(r, g, b)
    except Exception:
        pass

    # Method 3: Fallback via DwmGetColorizationColor
    try:
        from ctypes import windll, byref, c_ulong, c_bool
        dwm = windll.dwmapi.DwmGetColorizationColor
        color = c_ulong()
        opaque = c_bool()
        if dwm(byref(color), byref(opaque)) == 0:
            val = color.value
            r = (val >> 16) & 0xFF
            g = (val >> 8) & 0xFF
            b = val & 0xFF
            if r or g or b:
                return QColor(r, g, b)
    except Exception:
        pass

    return None


def detect_installed_game_folders() -> List[str]:
    """
    Auto-discovers common game folders across Windows system drives and launchers:
    Amazon Games, Epic Games, GOG, Itch, Origin/EA, Ubisoft Connect, Playnite, and Standalone.
    """
    try:
        return steam_syncer.get_default_game_folders(existing_only=True)
    except Exception:
        return [r"D:\Gamess", r"C:\Games"]


def load_app_config() -> Dict[str, Any]:
    """Loads saved settings from config.json or returns defaults with auto-discovered folders."""
    detected = detect_installed_game_folders()
    defaults = {
        'game_folders': detected if detected else [r"D:\Gamess", r"C:\Games"],
        'steam_path': "",
        'user_id': "",
        'download_artwork': True,
        'backup_shortcuts': True,
        'steamgriddb_key': "",
        'auto_steam_lifecycle': False,
        'theme': "Auto",
        'sync_accent_color': True,
        'language': "auto",
        'first_run': True
    }
    cfg_candidates = [
        CONFIG_PATH,
        os.path.join(DECKBRIDGE_DATA_DIR, "config.json"),
        os.path.join(BASE_DIR, "config.json"),
        os.path.join(os.path.dirname(sys.executable), "config.json"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
    ]
    seen_paths = set()
    unique_candidates = []
    for cp in cfg_candidates:
        if cp and cp not in seen_paths:
            seen_paths.add(cp)
            unique_candidates.append(cp)

    for cp in unique_candidates:
        if os.path.isfile(cp):
            try:
                with open(cp, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    defaults.update(data)
                    defaults['first_run'] = False
                break
            except Exception as e:
                logger.warning(f"Failed to load {cp}: {e}")
    return defaults


def save_app_config(config_data: Dict[str, Any]):
    """Persists settings to config.json atomically to prevent file corruption."""
    targets = [CONFIG_PATH]
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        if exe_dir and os.path.isdir(exe_dir):
            c_exe = os.path.join(exe_dir, "config.json")
            if os.path.isfile(c_exe) and c_exe not in targets:
                try:
                    if os.access(exe_dir, os.W_OK):
                        targets.append(c_exe)
                except Exception:
                    pass
    for target in targets:
        tmp_target = None
        try:
            target_dir = os.path.dirname(os.path.abspath(target))
            os.makedirs(target_dir, exist_ok=True)
            with tempfile.NamedTemporaryFile('w', dir=target_dir, delete=False, encoding='utf-8') as f:
                tmp_target = f.name
                json.dump(config_data, f, indent=2, ensure_ascii=False)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_target, target)
        except Exception as e:
            if tmp_target and os.path.exists(tmp_target):
                try:
                    os.remove(tmp_target)
                except OSError:
                    pass
            logger.warning(f"Failed to save {target}: {e}")


# ==============================================================================
# Worker Threads for Non-Blocking Operations
# ==============================================================================

class CloseSteamWorker(QThread):
    closed = pyqtSignal(bool)

    def __init__(self, steam_path: Optional[str] = None, timeout_sec: float = 8.0):
        super().__init__()
        self.steam_path = steam_path
        self.timeout_sec = timeout_sec

    def run(self):
        try:
            ok = steam_syncer.close_steam_client(steam_path=self.steam_path, timeout_sec=self.timeout_sec)
            self.closed.emit(ok)
        except Exception as e:
            logger.error(f"CloseSteamWorker error: {e}")
            self.closed.emit(False)


class ScanWorker(QThread):
    scan_finished = pyqtSignal(list, set, dict)

    def __init__(self, game_folders: List[str], steam_path: Optional[str], user_id: Optional[str]):
        super().__init__()
        self.game_folders = game_folders
        self.steam_path = steam_path
        self.user_id = user_id

    def run(self):
        try:
            if self.isInterruptionRequested():
                return
            games = steam_syncer.scan_games(self.game_folders, include_launchers=True)
            if self.isInterruptionRequested():
                return
            existing_exes = set()
            if self.steam_path and self.user_id:
                vdf_p = os.path.join(self.steam_path, "userdata", self.user_id, "config", "shortcuts.vdf")
                data = steam_syncer.load_shortcuts_vdf(vdf_p)
                for item in data.get('shortcuts', {}).values():
                    if isinstance(item, dict):
                        exe_val = item.get('Exe', '')
                        if isinstance(exe_val, str):
                            existing_exes.add(os.path.normpath(exe_val.strip().strip('"\'')).lower())

            if self.isInterruptionRequested():
                return

            covers_map = {}
            grid_dir = os.path.join(self.steam_path, "userdata", self.user_id, "config", "grid") if self.steam_path and self.user_id else None
            if grid_dir and os.path.isdir(grid_dir):
                for g in games:
                    if self.isInterruptionRequested():
                        return
                    grid_id, _, grid_id_64 = steam_syncer.calculate_steam_ids(g['exe_path'], g['clean_name'])
                    for candidate in [f"{grid_id}p.png", f"{grid_id_64}p.png", f"{grid_id}.png"]:
                        p = os.path.join(grid_dir, candidate)
                        if os.path.isfile(p) and os.path.getsize(p) > 0:
                            covers_map[g['exe_path']] = p
                            break

            if self.isInterruptionRequested():
                return

            self.scan_finished.emit(games, existing_exes, covers_map)
        except Exception as e:
            logger.error(f"ScanWorker error: {e}")
            self.scan_finished.emit([], set(), {})


class SyncWorker(QThread):
    progress_changed = pyqtSignal(int, int, str)
    log_message = pyqtSignal(str)
    game_discovered = pyqtSignal(dict)
    sync_finished = pyqtSignal(dict)

    def __init__(
        self,
        game_folders: List[str],
        steam_path: Optional[str],
        user_id: Optional[str],
        download_artwork: bool,
        backup_shortcuts: bool = True,
        steamgriddb_key: Optional[str] = None,
        auto_steam_lifecycle: bool = False,
        selected_games: Optional[List[Dict[str, Any]]] = None
    ):
        super().__init__()
        self.game_folders = game_folders
        self.steam_path = steam_path
        self.user_id = user_id
        self.download_artwork = download_artwork
        self.backup_shortcuts = backup_shortcuts
        self.steamgriddb_key = steamgriddb_key or steam_syncer.DEFAULT_STEAMGRIDDB_KEY
        self.auto_steam_lifecycle = auto_steam_lifecycle
        self.selected_games = selected_games

    def run(self):
        report = {
            'success': False,
            'message': '',
            'steam_running': False,
            'games_found': [],
            'games_added': 0,
            'art_downloaded': 0,
            'verification': ''
        }

        try:
            # 1. Process Guard & Smart Lifecycle
            self.progress_changed.emit(5, 100, "Checking running processes...")
            self.log_message.emit("[1/5] Checking Windows processes...")
            steam_was_running = steam_syncer.is_steam_running()
            if steam_was_running:
                if self.auto_steam_lifecycle:
                    self.log_message.emit(" [LIFECYCLE] Steam is running. Closing Steam safely before sync...")
                    self.progress_changed.emit(8, 100, "Closing Steam safely...")
                    import steam_lifecycle
                    closed = steam_lifecycle.safe_close_steam(steam_path=self.steam_path, timeout_sec=8.0)
                    if not closed or steam_syncer.is_steam_running():
                        report['steam_running'] = True
                        report['message'] = "Failed to close Steam automatically. Please close Steam manually."
                        self.log_message.emit(" [ERROR] Failed to close Steam automatically.")
                        self.sync_finished.emit(report)
                        return
                    self.log_message.emit(" [LIFECYCLE] Steam closed successfully.")
                else:
                    report['steam_running'] = True
                    report['message'] = "Steam is currently RUNNING! Please exit Steam completely before syncing."
                    self.log_message.emit(" [ERROR] Steam is running. Aborting operation to protect shortcuts.vdf.")
                    self.sync_finished.emit(report)
                    return

            # 2. Locate Steam & User
            self.progress_changed.emit(15, 100, "Locating Steam directory...")
            steam_dir = self.steam_path or steam_syncer.get_steam_path()
            if not steam_dir or not os.path.isdir(steam_dir):
                report['message'] = f"Steam directory not found: {steam_dir}"
                self.log_message.emit(f" [ERROR] {report['message']}")
                self.sync_finished.emit(report)
                return

            if self.isInterruptionRequested():
                return
            user = self.user_id or steam_syncer.get_active_steam_user(steam_dir)
            if not user:
                report['message'] = "No active Steam account found in userdata."
                self.log_message.emit(f" [ERROR] {report['message']}")
                self.sync_finished.emit(report)
                return

            shortcuts_path = os.path.join(steam_dir, "userdata", user, "config", "shortcuts.vdf")
            grid_dir = os.path.join(steam_dir, "userdata", user, "config", "grid")

            self.log_message.emit(f" [INFO] Steam: {steam_dir}")
            self.log_message.emit(f" [INFO] User ID: {user}")
            self.log_message.emit(f" [INFO] Shortcuts: {shortcuts_path}")

            # 3. Scanning Games
            if self.isInterruptionRequested():
                return
            self.progress_changed.emit(30, 100, "Scanning game folders...")
            self.log_message.emit("[2/5] Scanning game directories...")

            if self.selected_games:
                games = [g for g in self.selected_games if g.get('selected', True)]
            else:
                games = steam_syncer.scan_games(self.game_folders, include_launchers=True)
            report['games_found'] = games

            for g in games:
                if self.isInterruptionRequested():
                    return
                self.game_discovered.emit(g)
                self.log_message.emit(f"   + Discovered game: {g['clean_name']} -> {g['exe_name']} ({g['exe_size'] / (1024*1024):.1f} MB)")

            if not games:
                report['success'] = True
                report['message'] = "No games found in the specified directories."
                self.log_message.emit(" [WARN] No games discovered.")
                self.sync_finished.emit(report)
                return

            # 4. Backup shortcuts.vdf
            if self.isInterruptionRequested():
                return
            if self.backup_shortcuts and os.path.isfile(shortcuts_path):
                self.progress_changed.emit(45, 100, "Backing up shortcuts.vdf...")
                self.log_message.emit("[3/5] Backing up shortcuts.vdf...")
                bak_p = steam_syncer.backup_shortcuts_file(shortcuts_path)
                self.log_message.emit(f"   + Backup saved: {bak_p}")

            # 5. Add Games & Download Artwork
            if self.isInterruptionRequested():
                return
            self.progress_changed.emit(50, 100, "Processing games and artwork...")
            self.log_message.emit("[4/5] Adding shortcuts and downloading official artwork...")

            def on_progress(current, total, game_name):
                if self.isInterruptionRequested():
                    return
                pct = 50 + int((current / max(total, 1)) * 40)
                self.progress_changed.emit(pct, 100, f"Processing {game_name} ({current}/{total})...")
                self.log_message.emit(f"   • [{current}/{total}] {game_name}")

            added_count, art_count = steam_syncer.add_games_to_shortcuts(
                shortcuts_path=shortcuts_path,
                games=games,
                download_artwork=self.download_artwork,
                steam_path=steam_dir,
                steam_user_id=user,
                progress_callback=on_progress,
                steamgriddb_key=self.steamgriddb_key
            )
            report['games_added'] = added_count
            report['art_downloaded'] = art_count
            self.log_message.emit(f"   + Added shortcuts: {added_count}")
            self.log_message.emit(f"   + Downloaded artworks: {art_count}")

            # 6. Verify integrity
            self.progress_changed.emit(95, 100, "Verifying shortcuts.vdf integrity...")
            self.log_message.emit("[5/5] Verifying shortcuts.vdf integrity...")
            ok, v_msg = steam_syncer.verify_shortcuts_integrity(shortcuts_path, grid_dir)
            report['verification'] = v_msg
            self.log_message.emit(f"   + Integrity verified: {v_msg}")

            if not ok:
                report['success'] = False
                report['message'] = f"Integrity verification failed: {v_msg}"
                self.sync_finished.emit(report)
                return

            report['success'] = True
            report['message'] = f"Sync successful! Added {added_count} shortcuts, downloaded {art_count} artworks."
            self.log_message.emit(f" [SUCCESS] {report['message']}")

            # 7. Smart Lifecycle: Relaunch Steam if it was running
            if self.auto_steam_lifecycle and steam_was_running:
                self.log_message.emit(" [LIFECYCLE] Relaunching Steam client...")
                import steam_lifecycle
                steam_lifecycle.launch_steam(steam_path=steam_dir)
                self.log_message.emit(" [LIFECYCLE] Steam client relaunched successfully.")
            self.progress_changed.emit(100, 100, "Completed!")

        except Exception as e:
            report['success'] = False
            report['message'] = f"Error during sync: {str(e)}"
            self.log_message.emit(f" [CRITICAL ERROR] {traceback.format_exc()}")

        self.sync_finished.emit(report)


_ACCENT_COLOR_CACHE: Dict[str, Optional[Tuple[int, int, int]]] = {}


def get_cover_accent_color(image_path: str) -> Optional[Tuple[int, int, int]]:
    """
    Extracts a subtle accent RGB tint from a game cover using Pillow thumbnail.
    Filters out extreme dark (<35) and bright (>220) pixels. Fast (<1ms, cached in-memory).
    """
    if not image_path or not os.path.isfile(image_path):
        return None
    if image_path in _ACCENT_COLOR_CACHE:
        return _ACCENT_COLOR_CACHE[image_path]
    try:
        with Image.open(image_path) as im:
            thumb = im.convert("RGB").resize((24, 24), Image.Resampling.BOX)
            raw = thumb.tobytes()
            pixels = [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)]
            valid = [p for p in pixels if 35 < (p[0] + p[1] + p[2]) / 3 < 220]
            if not valid:
                valid = pixels
            if not valid:
                _ACCENT_COLOR_CACHE[image_path] = None
                return None
            r = int(sum(p[0] for p in valid) / len(valid))
            g = int(sum(p[1] for p in valid) / len(valid))
            b = int(sum(p[2] for p in valid) / len(valid))
            res = (r, g, b)
            _ACCENT_COLOR_CACHE[image_path] = res
            return res
    except Exception:
        _ACCENT_COLOR_CACHE[image_path] = None
        return None


def make_cropped_thumb(pix: QPixmap, tw: int, th: int) -> QPixmap:
    """
    Creates an aspect-ratio-preserving centered crop of a QPixmap to fit target dimensions.
    Guarantees wide or square covers (e.g. 007) are never squashed or distorted.
    """
    if not pix or pix.isNull() or tw <= 0 or th <= 0:
        return pix
    scaled = pix.scaled(tw, th, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    x = max(0, (scaled.width() - tw) // 2)
    y = max(0, (scaled.height() - th) // 2)
    return scaled.copy(x, y, tw, th)


class CoverVariantsWorker(QThread):
    variants_ready = pyqtSignal(list)

    def __init__(self, clean_name: str, game_folder: str = "", sgdb_key: Optional[str] = None):
        super().__init__()
        self.clean_name = clean_name
        self.game_folder = game_folder
        self.sgdb_key = sgdb_key

    def run(self):
        variants = []
        seen_urls = set()

        # 1. Local artwork candidates in game folder
        if self.game_folder and os.path.isdir(self.game_folder):
            try:
                for root, _, files in os.walk(self.game_folder):
                    for f in files:
                        if self.isInterruptionRequested():
                            return
                        ext = os.path.splitext(f)[1].lower()
                        if ext in ('.png', '.jpg', '.jpeg', '.webp'):
                            f_low = f.lower()
                            if any(k in f_low for k in ('cover', 'poster', 'boxart', 'folder', 'grid', 'capsule', 'artwork')):
                                full_p = os.path.join(root, f)
                                if os.path.isfile(full_p) and os.path.getsize(full_p) > 1024:
                                    variants.append({
                                        'source': tr("cover_source_local"),
                                        'url': full_p,
                                        'is_local': True
                                    })
                                    if len(variants) >= 2:
                                        break
                    if len(variants) >= 2:
                        break
            except Exception as e:
                logger.debug(f"Local cover search notice: {e}")

        if self.isInterruptionRequested():
            return

        # 2. Steam Store Search candidates
        try:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            term = self.clean_name
            url = f"https://store.steampowered.com/api/storesearch/?term={requests.utils.quote(term)}&l=russian&cc=RU"
            resp = steam_syncer.safe_requests_get(url, headers=headers, timeout=(3.0, 5.0), max_retries=1)
            if resp and resp.status_code == 200:
                data = resp.json()
                items = data.get('items', []) if isinstance(data, dict) else []
                candidate_items = []
                for itm in items:
                    if not isinstance(itm, dict):
                        continue
                    name = str(itm.get('name', ''))
                    if not any(k in name.lower() for k in steam_syncer.DLC_SOUNDTRACK_KEYWORDS):
                        candidate_items.append(itm)
                if not candidate_items and items:
                    candidate_items = items[:3]

                for itm in candidate_items[:4]:
                    if self.isInterruptionRequested():
                        return
                    aid = itm.get('id')
                    gname = itm.get('name', term)
                    if aid:
                        p_url = f"https://shared.cloudflare.steamstatic.com/store_item_assets/steam/apps/{aid}/library_600x900.jpg"
                        if p_url not in seen_urls and steam_syncer.is_safe_artwork_url(p_url):
                            seen_urls.add(p_url)
                            try:
                                chk = steam_syncer.safe_requests_get(p_url, timeout=(2.5, 4.0), headers=headers)
                                if chk and chk.status_code == 200:
                                    variants.append({
                                        'source': f"Steam: {gname}",
                                        'url': p_url,
                                        'thumb_bytes': chk.content,
                                        'is_local': False,
                                        'appid': aid
                                    })
                            except Exception:
                                pass
        except Exception as e:
            logger.debug(f"Store cover candidates search notice: {e}")

        if self.isInterruptionRequested():
            return

        # 3. SteamGridDB candidates
        effective_key = (self.sgdb_key or steam_syncer.DEFAULT_STEAMGRIDDB_KEY or "").strip()
        if effective_key:
            try:
                sgdb = steam_syncer.SteamGridDBClient(effective_key)
                gid = sgdb.search_game(self.clean_name)
                if gid and not self.isInterruptionRequested():
                    sg_url = f"https://www.steamgriddb.com/api/v2/grids/game/{gid}?dimensions=600x900"
                    resp = steam_syncer.safe_requests_get(sg_url, headers=sgdb._headers(), timeout=(3.0, 5.0), max_retries=1)
                    if resp and resp.status_code == 200:
                        s_data = resp.json()
                        grids = s_data.get('data', []) if isinstance(s_data, dict) else []
                        for g_item in grids[:4]:
                            if self.isInterruptionRequested():
                                return
                            if isinstance(g_item, dict) and g_item.get('url'):
                                g_url = g_item['url']
                                if not steam_syncer.is_safe_artwork_url(g_url):
                                    continue
                                if g_url not in seen_urls:
                                    seen_urls.add(g_url)
                                    thumb_url = g_item.get('thumb') or g_url
                                    if not steam_syncer.is_safe_artwork_url(thumb_url):
                                        thumb_url = g_url
                                    thumb_resp = steam_syncer.safe_requests_get(thumb_url, headers=sgdb._headers(), timeout=(2.5, 4.0))
                                    t_bytes = thumb_resp.content if (thumb_resp and thumb_resp.status_code == 200) else None
                                    variants.append({
                                        'source': "SteamGridDB",
                                        'url': g_url,
                                        'thumb': thumb_url,
                                        'thumb_bytes': t_bytes,
                                        'is_local': False
                                    })
            except Exception as e:
                logger.debug(f"SGDB cover variants fetch notice: {e}")

        if not self.isInterruptionRequested():
            self.variants_ready.emit(variants)


class CoverSelectorDialog(MessageBoxBase):
    """
    Fluent dialog presenting matching poster artwork variants from
    Steam Storefront and SteamGridDB, with one-click selection and local file fallback.
    """
    def __init__(
        self,
        clean_name: str,
        game_folder: str = "",
        steam_path: Optional[str] = None,
        sgdb_key: Optional[str] = None,
        parent=None
    ):
        super().__init__(parent=parent)
        self.clean_name = clean_name
        self.game_folder = game_folder
        self.steam_path = steam_path
        self.sgdb_key = sgdb_key
        self.selected_cover_path: Optional[str] = None
        self._candidate_cards = []
        self._selected_item = None

        self.widget.setMinimumWidth(620)
        self.titleLabel = SubtitleLabel(tr("cover_picker_title", name=clean_name), self.widget)
        self.titleLabel.setWordWrap(True)
        self.viewLayout.addWidget(self.titleLabel)

        self.descLabel = CaptionLabel(tr("cover_picker_desc"), self.widget)
        self.descLabel.setWordWrap(True)
        self.viewLayout.addWidget(self.descLabel)

        # Progress indicator while variants load
        self.progress_bar = ProgressBar(self.widget)
        self.progress_bar.setRange(0, 0)
        self.viewLayout.addWidget(self.progress_bar)

        self.lbl_status = CaptionLabel(tr("cover_picker_loading"), self.widget)
        self.lbl_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(self.lbl_status)

        # Container for candidate artwork cards
        self.variants_container = QWidget(self.widget)
        self.variants_layout = QHBoxLayout(self.variants_container)
        self.variants_layout.setContentsMargins(0, 8, 0, 8)
        self.variants_layout.setSpacing(12)
        self.variants_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.viewLayout.addWidget(self.variants_container)

        # Action row with browse local file button
        btn_row = QHBoxLayout()
        self.btn_browse_local = PushButton(tr("cover_picker_browse_local"), self.widget, FIF.FOLDER)
        self.btn_browse_local.clicked.connect(self._on_browse_local)
        btn_row.addWidget(self.btn_browse_local)
        btn_row.addStretch(1)
        self.viewLayout.addLayout(btn_row)

        self.yesButton.setText(tr("cover_picker_apply"))
        self.yesButton.setEnabled(False)
        self.cancelButton.setText(tr("cover_picker_cancel"))

        # Launch background search
        self.worker = CoverVariantsWorker(
            clean_name=self.clean_name,
            game_folder=self.game_folder,
            sgdb_key=self.sgdb_key
        )
        self.worker.variants_ready.connect(self._on_variants_ready)
        self.worker.start()

    def done(self, r):
        if hasattr(self, 'worker') and self.worker:
            try:
                self.worker.variants_ready.disconnect()
            except Exception:
                pass
            if self.worker.isRunning():
                try:
                    self.worker.requestInterruption()
                    self.worker.wait(200)
                except Exception:
                    pass
                if self.worker.isRunning():
                    try:
                        self.worker.terminate()
                        self.worker.wait(300)
                    except Exception:
                        pass
        super().done(r)

    def __del__(self):
        if hasattr(self, 'worker') and self.worker and self.worker.isRunning():
            try:
                self.worker.terminate()
                self.worker.wait(300)
            except Exception:
                pass

    def _on_browse_local(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("title_pick_poster", name=self.clean_name),
            "",
            "Image Files (*.png *.jpg *.jpeg *.webp *.bmp *.ico);;All Files (*.*)"
        )
        if file_path and os.path.isfile(file_path):
            self.selected_cover_path = file_path
            self.accept()

    def _on_variants_ready(self, variants: list):
        self.progress_bar.setVisible(False)
        self.lbl_status.setVisible(False)

        if not variants:
            self.lbl_status.setText(tr("cover_picker_no_variants"))
            self.lbl_status.setVisible(True)
            return

        for idx, var in enumerate(variants[:4]):
            card = SimpleCardWidget(self.variants_container)
            card.setFixedSize(130, 195)
            card.setCursor(Qt.CursorShape.PointingHandCursor)
            c_layout = QVBoxLayout(card)
            c_layout.setContentsMargins(8, 8, 8, 8)
            c_layout.setSpacing(6)
            c_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            img_lbl = QLabel(card)
            img_lbl.setFixedSize(100, 140)
            img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            img_lbl.setStyleSheet("background: rgba(0, 0, 0, 0.30); border-radius: 4px;")

            pix = None
            if var.get('is_local'):
                pix = QPixmap(var['url'])
            elif var.get('thumb_bytes'):
                pix = QPixmap()
                pix.loadFromData(var['thumb_bytes'])

            if pix and not pix.isNull():
                cropped = make_cropped_thumb(pix, 100, 140)
                img_lbl.setPixmap(cropped)
            else:
                img_lbl.setText("🎮")

            src_lbl = CaptionLabel(var.get('source', 'Steam'), card)
            src_lbl.setWordWrap(True)
            src_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            src_lbl.setStyleSheet("font-size: 10px; color: rgba(255, 255, 255, 0.7);")

            c_layout.addWidget(img_lbl, 0, Qt.AlignmentFlag.AlignCenter)
            c_layout.addWidget(src_lbl, 0, Qt.AlignmentFlag.AlignCenter)

            def _make_handler(c=card, v=var):
                return lambda e: self._on_select_card(c, v)

            card.mousePressEvent = _make_handler(card, var)
            card.mouseDoubleClickEvent = lambda e: self.accept()

            self.variants_layout.addWidget(card)
            self._candidate_cards.append((card, var))

        if self._candidate_cards:
            self._on_select_card(self._candidate_cards[0][0], self._candidate_cards[0][1])

    def _on_select_card(self, card: SimpleCardWidget, var: dict):
        self._selected_item = var
        self.yesButton.setEnabled(True)
        for c, _ in self._candidate_cards:
            if c == card:
                c.setStyleSheet("""
                    SimpleCardWidget {
                        background-color: rgba(33, 150, 243, 0.18);
                        border: 2px solid #2196f3;
                        border-radius: 6px;
                    }
                """)
            else:
                c.setStyleSheet("""
                    SimpleCardWidget {
                        background-color: rgba(30, 30, 34, 0.72);
                        border: 1px solid rgba(255, 255, 255, 0.08);
                        border-radius: 6px;
                    }
                """)

    def accept(self):
        if not self.selected_cover_path and self._selected_item:
            var = self._selected_item
            if var.get('is_local'):
                self.selected_cover_path = var['url']
            else:
                try:
                    c_bytes = None
                    if var.get('thumb_bytes'):
                        c_bytes = var['thumb_bytes']
                    elif var.get('url') and steam_syncer.is_safe_artwork_url(var['url']):
                        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                        r = steam_syncer.safe_requests_get(var['url'], headers=headers, timeout=(4.0, 8.0))
                        if r and r.status_code == 200:
                            c_bytes = r.content
                    if c_bytes:
                        try:
                            os.makedirs(COVERS_CACHE_DIR, exist_ok=True)
                        except Exception:
                            pass
                        fname = f"cover_custom_{os.getpid()}_{time.time_ns()}p.png"
                        out_p = os.path.join(COVERS_CACHE_DIR, fname)
                        if steam_syncer.convert_and_save_image(c_bytes, out_p, is_logo=False, min_size_bytes=500):
                            self.selected_cover_path = out_p
                except Exception as e:
                    logger.warning(f"Failed to prepare chosen cover: {e}")
        if not self.selected_cover_path:
            self.lbl_status.setText(tr("cover_picker_download_failed"))
            self.lbl_status.setVisible(True)
            return
        super().accept()

    def get_selected_cover_path(self) -> Optional[str]:
        return self.selected_cover_path


CRYPTO_WALLETS = [
    {
        "id": "usdt_bep20",
        "name": "USDT (BNB Smart Chain / BEP20)",
        "network": "BNB Smart Chain (BSC / BEP20)",
        "symbol": "USDT",
        "address": "0xb9e67030ab0f38d1d88e4eaa605fb2acf0aa0ba3",
        "qr": "donate_usdt_bep20.png",
        "notice": "Сеть: BNB Smart Chain (BEP20). Отправляйте только USDT в сети BSC."
    },
    {
        "id": "usdt_trc20",
        "name": "USDT (TRON / TRC20)",
        "network": "TRON (TRC20)",
        "symbol": "USDT",
        "address": "TQ4RwzWxs4kD6WXFgJkejRMSeAPsGUTv44",
        "qr": "donate_usdt_trc20.png",
        "notice": "Сеть: TRON (TRC20). Отправляйте только USDT в сети TRC20."
    },
    {
        "id": "usdc_sol",
        "name": "USDC (Solana / SOL)",
        "network": "Solana (SOL)",
        "symbol": "USDC",
        "address": "7SjWhmXyAQ2xVxB3BNuxHk1mQW8P5dg3aXVtr1eyT6qF",
        "qr": "donate_usdc_sol.png",
        "notice": "Сеть: Solana (SOL). Отправляйте только USDC в сети Solana."
    },
    {
        "id": "ltc",
        "name": "Litecoin (LTC Native)",
        "network": "Litecoin (LTC)",
        "symbol": "LTC",
        "address": "LRBmSE6GuURdMJzTB971BAz4Z8Z9UXnPbF",
        "qr": "donate_ltc.png",
        "notice": "Сеть: Litecoin (LTC). Отправляйте только монеты Litecoin (LTC)."
    }
]


class CryptoDonationDialog(MessageBoxBase):
    """
    Fluent dialog displaying cryptocurrency donation details, QR code,
    and one-click clipboard copying for multiple coins.
    """
    def __init__(self, parent=None, default_coin_idx=0):
        super().__init__(parent=parent)
        self.widget.setMinimumWidth(460)
        self.widget.setMaximumWidth(500)

        self.titleLabel = SubtitleLabel(tr("dialog_crypto_title"), self.widget)
        self.viewLayout.addWidget(self.titleLabel)

        self.cmb_coin = ComboBox(self.widget)
        for coin in CRYPTO_WALLETS:
            self.cmb_coin.addItem(coin["name"])
        self.viewLayout.addWidget(self.cmb_coin)

        self.descLabel = CaptionLabel("", self.widget)
        self.descLabel.setWordWrap(True)
        self.viewLayout.addWidget(self.descLabel)

        # QR Code Display
        qr_container = QHBoxLayout()
        qr_container.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_qr = QLabel(self.widget)
        self.lbl_qr.setFixedSize(180, 180)
        self.lbl_qr.setStyleSheet("background: white; border-radius: 8px; padding: 4px;")
        self.lbl_qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_container.addWidget(self.lbl_qr)
        self.viewLayout.addLayout(qr_container)

        # Address box with copy button
        addr_row = QHBoxLayout()
        addr_row.setSpacing(8)
        self.txt_addr = LineEdit(self.widget)
        self.txt_addr.setReadOnly(True)
        self.btn_copy = PushButton(tr("btn_copy_address"), self.widget, FIF.COPY)

        def on_copy():
            cb = QApplication.clipboard()
            if cb:
                cb.setText(self.txt_addr.text())
            self.btn_copy.setText(tr("badge_copied"))
            QTimer.singleShot(2500, lambda: self.btn_copy.setText(tr("btn_copy_address")))

        self.btn_copy.clicked.connect(on_copy)
        addr_row.addWidget(self.txt_addr, 1)
        addr_row.addWidget(self.btn_copy)
        self.viewLayout.addLayout(addr_row)

        def update_coin(idx):
            coin = CRYPTO_WALLETS[idx]
            self.descLabel.setText(coin["notice"])
            self.txt_addr.setText(coin["address"])
            self.btn_copy.setText(tr("btn_copy_address"))
            base_dir = os.path.dirname(os.path.abspath(__file__))
            qr_path = os.path.join(base_dir, "Assets", coin["qr"])
            if not os.path.isfile(qr_path):
                qr_path = os.path.join(base_dir, "assets", coin["qr"])
            if os.path.isfile(qr_path):
                pix = QPixmap(qr_path).scaled(172, 172, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                self.lbl_qr.setPixmap(pix)
            else:
                self.lbl_qr.clear()

        self.cmb_coin.currentIndexChanged.connect(update_coin)
        if 0 <= default_coin_idx < len(CRYPTO_WALLETS):
            self.cmb_coin.setCurrentIndex(default_coin_idx)
        update_coin(self.cmb_coin.currentIndex())

        self.yesButton.setText("OK")
        self.cancelButton.hide()


# ==============================================================================
# Main Fluent Window
# ==============================================================================

class MainWindow(FluentWindow):
    def __init__(self):
        app = get_or_create_qapp()
        ensure_qfluentwidgets_alive(app)
        super().__init__()
        self.setWindowTitle("DeckBridge")
        
        # Load persisted settings
        self.config = load_app_config()
        self.game_folders = steam_syncer.parse_folder_list(self.config.get('game_folders', []))
        if not self.game_folders:
            self.game_folders = steam_syncer.get_default_game_folders(existing_only=True)

        # Initialize language manager
        i18n.I18NManager.instance().set_language(self.config.get('language', 'auto'))

        # Window icon: prefer deckbridge.png on Linux, DeckBridge.ico on Windows
        icon_names = ("DeckBridge.ico", "deckbridge.png", "app_icon.ico", "DeckBridge_logo.png") if sys.platform == 'win32' else ("deckbridge.png", "DeckBridge.ico", "app_icon.ico", "DeckBridge_logo.png")
        for ic in icon_names:
            found = False
            for b in (BASE_DIR, os.path.dirname(sys.executable), os.path.dirname(os.path.abspath(__file__))):
                ip = os.path.join(b, ic)
                if os.path.isfile(ip):
                    self.setWindowIcon(QIcon(ip))
                    found = True
                    break
            if found:
                break

        # Compact utility window sizing: 860x620, minimum 760x520
        self.resize(860, 620)
        self.setMinimumSize(760, 520)
        self.setMicaEffectEnabled(sys.platform == 'win32')
        self.updateFrameless()

        # Center window on primary display
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            x = (geo.width() - 860) // 2 + geo.x()
            y = (geo.height() - 620) // 2 + geo.y()
            self.move(max(0, x), max(0, y))

        # Eliminate left sidebar and hamburger completely
        self.navigationInterface.hide()
        self.navigationInterface.setFixedWidth(0)
        self.navigationInterface.setReturnButtonVisible(False)
        if hasattr(self.navigationInterface, 'panel') and hasattr(self.navigationInterface.panel, 'bottomLayout'):
            self.navigationInterface.panel.bottomLayout.setContentsMargins(0, 0, 0, 0)

        # Windows 11 Fluent / Acrylic blur styling vs Linux clean Fluent dark backdrop
        main_win_bg = "transparent" if sys.platform == 'win32' else "#202020"
        self.setStyleSheet(f"""
            MainWindow {{
                background-color: {main_win_bg};
            }}
            StackedWidget, QStackedWidget,
            #homeInterface, #settingsInterface,
            #homeScrollViewport, #settingsScrollViewport,
            #homeScrollWidget, #settingsScrollWidget,
            #gamesScrollViewport, #gamesContainer {{
                background-color: transparent;
                background: transparent;
                border: none;
            }}
            SimpleCardWidget {{
                background-color: rgba(30, 30, 35, 0.78);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 8px;
            }}
            SimpleCardWidget:hover {{
                background-color: rgba(38, 38, 45, 0.88);
                border: 1px solid rgba(255, 255, 255, 0.16);
            }}
        """)

        # Enable authentic Windows 11 Acrylic blur-behind backdrop
        self.setup_system_blur_backdrop()

        # Align window icon and title with 20px padding (matching cards below)
        if hasattr(self.titleBar, 'hBoxLayout'):
            self.titleBar.hBoxLayout.insertSpacing(0, 20)
            self.titleBar.hBoxLayout.insertSpacing(2, 6)

        # TitleBar controls (Steam status dot, settings button)
        btn_h = self.titleBar.minBtn.height() if hasattr(self.titleBar, 'minBtn') else 32
        self.steam_dot = SteamStatusDot(self.titleBar)
        self.steam_dot.setFixedSize(btn_h, btn_h)
        self.steam_dot.clicked_callback = self.refresh_steam_status

        # Language selection is exclusively located in Settings View per design requirement
        self.cmb_header_lang = None

        self.btn_header_settings = TransparentToolButton(FIF.SETTING, self.titleBar)
        self.btn_header_settings.setFixedSize(36, btn_h)
        self.btn_header_settings.setToolTip(tr("nav_settings"))
        self.btn_header_settings.clicked.connect(self.toggle_settings_view)

        if hasattr(self.titleBar, 'buttonLayout'):
            self.titleBar.buttonLayout.insertWidget(0, self.steam_dot, 0, Qt.AlignmentFlag.AlignVCenter)
            self.titleBar.buttonLayout.insertSpacing(1, 4)
            self.titleBar.buttonLayout.insertWidget(2, self.btn_header_settings, 0, Qt.AlignmentFlag.AlignVCenter)
            self.titleBar.buttonLayout.insertSpacing(3, 8)
        else:
            tb_layout = self.titleBar.hBoxLayout
            tb_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)
            tb_layout.insertWidget(3, self.steam_dot, 0, Qt.AlignmentFlag.AlignVCenter)
            tb_layout.insertSpacing(4, 6)
            tb_layout.insertWidget(5, self.btn_header_settings, 0, Qt.AlignmentFlag.AlignVCenter)
            tb_layout.insertSpacing(6, 8)

        # Always adapt to Windows 11 system theme (Dark/Light) automatically
        setTheme(Theme.AUTO)

        # Synchronize Windows 11 system accent color dynamically
        self.sync_windows_accent_color()

        self.worker = None
        self.scan_worker = None
        self.close_worker = None
        self._pixmap_cache: Dict[str, QPixmap] = {}
        self._last_steam_running = None
        self._last_notified_steam_state = None
        self._folder_mtimes = {}
        self._current_button_mode = "sync"
        self._scanned_games_count = 0
        self._last_report = None
        self._displayed_cards: set = set()

        # Build UI interfaces (Home and Settings with embedded Log)
        self.init_main_interface()
        self.init_settings_interface()

        # Update initial Steam status & preview games
        self.refresh_steam_status()
        self.preview_scanned_games()

        # Background auto-monitoring timer (checks Steam running state & folder changes every 2 sec)
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(2000)
        self.poll_timer.timeout.connect(self.poll_background_state)
        if self.config.get('auto_scan', True):
            self.poll_timer.start()

    def setup_system_blur_backdrop(self):
        """
        Enables authentic Windows 11 Acrylic blur-behind material.
        Blurs open windows and desktop wallpaper behind DeckBridge in real-time.
        """
        if sys.platform == 'win32':
            try:
                import ctypes
                hWnd = int(self.winId())
                if hasattr(self, 'windowEffect'):
                    self.windowEffect.enableBlurBehindWindow(hWnd)
                    self.windowEffect.addWindowAnimation(hWnd)
                    self.windowEffect.setAcrylicEffect(hWnd, gradientColor="161618A0")
                if sys.getwindowsversion().build >= 22621:
                    dwmapi = ctypes.windll.dwmapi
                    # DWMSBT_TRANSIENTWINDOW = 3 (Desktop Acrylic real-time Gaussian blur)
                    dwmapi.DwmSetWindowAttribute(hWnd, 38, ctypes.byref(ctypes.c_int(3)), 4)
                    # DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                    dwmapi.DwmSetWindowAttribute(hWnd, 20, ctypes.byref(ctypes.c_int(1)), 4)
                if sys.getwindowsversion().build >= 22000:
                    # Enforce Windows 11 rounded corners (DWMWCP_ROUND = 2)
                    dwmapi = ctypes.windll.dwmapi
                    dwmapi.DwmSetWindowAttribute(hWnd, 33, ctypes.byref(ctypes.c_int(2)), 4)
            except Exception as e:
                logger.debug(f"Could not apply DWM system blur: {e}")

        if hasattr(self, 'stackedWidget') and self.stackedWidget:
            self.stackedWidget.setStyleSheet("StackedWidget, QStackedWidget { background-color: transparent; border: none; }")
            self.stackedWidget.setProperty("isTransparent", True)
        if hasattr(self, 'home_interface') and self.home_interface:
            self.home_interface.setProperty("isStackedTransparent", True)
        if hasattr(self, 'settings_interface') and self.settings_interface:
            self.settings_interface.setProperty("isStackedTransparent", True)

    def showEvent(self, e):
        super().showEvent(e)
        self.setup_system_blur_backdrop()

    def updateFrameless(self):
        """
        Enforces FramelessWindowHint on PyQt6 6.11+ to prevent duplicate native caption buttons,
        while maintaining Windows 11 DWM rounded corners and window animation.
        """
        stayOnTop = Qt.WindowType.WindowStaysOnTopHint if self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint else 0
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.FramelessWindowHint | stayOnTop)
        if hasattr(self, 'windowEffect'):
            self.windowEffect.addWindowAnimation(self.winId())
        if sys.platform == 'win32' and sys.getwindowsversion().build >= 22000:
            try:
                import ctypes
                ctypes.windll.dwmapi.DwmSetWindowAttribute(int(self.winId()), 33, ctypes.byref(ctypes.c_int(2)), 4)
            except Exception:
                pass

    def paintEvent(self, e):
        """
        Clears the backing store cleanly with CompositionMode_Clear when Acrylic blur is active.
        Completely eliminates resize trails, smearing, and duplicate widget ghosting on Windows.
        On Linux, delegates to super().paintEvent(e) for clean native rendering.
        """
        if sys.platform == 'win32':
            painter = QPainter(self)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        else:
            super().paintEvent(e)

    def resizeEvent(self, e):
        """Reposition titleBar to full window width and repaint smoothly."""
        super().resizeEvent(e)
        self.titleBar.move(0, 0)
        self.titleBar.resize(self.width(), self.titleBar.height())
        self.update()

    def cleanup(self):
        """Cleanly terminates background timers and active workers."""
        if hasattr(self, 'poll_timer') and self.poll_timer.isActive():
            try:
                self.poll_timer.stop()
            except Exception:
                pass
        for worker_attr in ['worker', 'scan_worker', 'close_worker']:
            w = getattr(self, worker_attr, None)
            if w and w.isRunning():
                try:
                    w.disconnect()
                except Exception:
                    pass
                try:
                    w.requestInterruption()
                    w.wait(200)
                except Exception:
                    pass
                if w.isRunning():
                    try:
                        w.terminate()
                        w.wait(300)
                    except Exception:
                        pass

    def closeEvent(self, event):
        """Cleanly terminates background timers and active workers before closing window."""
        self.cleanup()
        super().closeEvent(event)
        if os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
            app = QApplication.instance()
            if app and not app.quitOnLastWindowClosed():
                app.quit()

    def __del__(self):
        try:
            self.cleanup()
        except Exception:
            pass

    def nativeEvent(self, eventType, message):
        """Listens for Windows 11 live personalization and accent color changes."""
        if sys.platform == "win32":
            try:
                from ctypes.wintypes import MSG
                msg = MSG.from_address(message.__int__())
                if msg.message in (0x001A, 0x0320):
                    if self.config.get('sync_accent_color', True):
                        self.sync_windows_accent_color()
            except Exception:
                pass

        return super().nativeEvent(eventType, message)

    def sync_windows_accent_color(self):
        """Applies Windows 11 system accent color dynamically to QFluentWidgets."""
        if not self.config.get('sync_accent_color', True):
            return

        accent_color = get_windows_accent_color()
        if accent_color and accent_color.isValid():
            setThemeColor(accent_color)
            logger.info(f"Synchronized with Windows 11 system accent color: {accent_color.name()}")

    def show_toast(self, kind: str, title: str, content: str, duration: int = 3500) -> InfoBar:
        """
        Displays a non-intrusive Windows 11 Fluent toast notification in the bottom-right corner.
        Ensures the header, hero card, buttons, and settings view remain completely unobstructed.
        """
        factories = {
            'info': InfoBar.info,
            'success': InfoBar.success,
            'warning': InfoBar.warning,
            'error': InfoBar.error
        }
        create_fn = factories.get(kind.lower(), InfoBar.info)
        return create_fn(
            title=title,
            content=content,
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.BOTTOM_RIGHT,
            duration=duration,
            parent=self
        )

    def notify_steam_state_change(self, is_running: bool):
        """Single-source-of-truth notification to prevent duplicate InfoBars."""
        if self._last_notified_steam_state == is_running:
            return
        self._last_notified_steam_state = is_running

        if is_running:
            self.show_toast(
                "warning",
                title=tr("info_steam_running_title"),
                content=tr("info_steam_running_msg"),
                duration=4000
            )
        else:
            self.show_toast(
                "success",
                title=tr("info_steam_closed_title"),
                content=tr("info_steam_closed_msg"),
                duration=4000
            )

    def poll_background_state(self):
        """Periodically monitors Steam process and game folders without UI stutter."""
        if not self.config.get('auto_scan', True):
            return
        if self.worker and self.worker.isRunning():
            return

        is_running = steam_syncer.is_steam_running()
        if self._last_steam_running is not None and is_running != self._last_steam_running:
            self.refresh_steam_status()
            self.notify_steam_state_change(is_running)
        self._last_steam_running = is_running

        # Folder change detection (silent background refresh)
        changed = False
        for folder in self.game_folders:
            if os.path.isdir(folder):
                try:
                    mtime = os.path.getmtime(folder)
                    if folder not in self._folder_mtimes:
                        self._folder_mtimes[folder] = mtime
                    elif self._folder_mtimes[folder] != mtime:
                        self._folder_mtimes[folder] = mtime
                        changed = True
                except Exception:
                    pass
        if changed and not (self.scan_worker and self.scan_worker.isRunning()):
            self.preview_scanned_games()

    def toggle_settings_view(self):
        """Switches between Home library view and Settings view."""
        cur = self.stackedWidget.currentWidget()
        if cur == self.settings_interface:
            self.switchTo(self.home_interface)
        else:
            self.switchTo(self.settings_interface)

    def on_header_language_changed(self, idx: int):
        if not getattr(self, 'cmb_header_lang', None):
            return
        code = self.cmb_header_lang.currentData() or "auto"
        if hasattr(self, 'cmb_language'):
            s_idx = self.cmb_language.findData(code)
            if s_idx >= 0 and self.cmb_language.currentIndex() != s_idx:
                self.cmb_language.blockSignals(True)
                self.cmb_language.setCurrentIndex(s_idx)
                self.cmb_language.blockSignals(False)
        self.config['language'] = code
        i18n.I18NManager.instance().set_language(code)
        save_app_config(self.config)
        self.retranslate_ui()

    # --------------------------------------------------------------------------
    # Main Sync Tab
    # --------------------------------------------------------------------------
    def init_main_interface(self):
        self.home_interface = QWidget(self)
        self.home_interface.setObjectName("homeInterface")
        root_layout = QVBoxLayout(self.home_interface)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Primary scroll area ensuring responsiveness on all resolutions
        self.home_scroll = ScrollArea(self.home_interface)
        self.home_scroll.setWidgetResizable(True)
        self.home_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.home_scroll.setSmoothMode(SmoothMode.QUADRATI, Qt.Orientation.Vertical)
        setup_high_hz_smooth_scroll(self.home_scroll)
        self.home_scroll.enableTransparentBackground()
        if self.home_scroll.viewport():
            self.home_scroll.viewport().setObjectName("homeScrollViewport")
            self.home_scroll.viewport().setAutoFillBackground(False)
        self.home_scroll.setStyleSheet("""
            QScrollArea, #homeScrollViewport, #homeScrollWidget {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 4px;
                margin: 0px 2px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.25);
                min-height: 24px;
                border-radius: 2px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.50);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)

        home_scroll_widget = QWidget()
        home_scroll_widget.setObjectName("homeScrollWidget")
        home_scroll_layout = QVBoxLayout(home_scroll_widget)
        home_scroll_layout.setContentsMargins(20, 16, 20, 16)
        home_scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        # Compact Inset Grouped MaxWidth container (Apple / Fluent: 860 px)
        home_container = QWidget(home_scroll_widget)
        home_container.setMaximumWidth(860)
        home_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(home_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # 1. Unified Hero Status & Action Card (Compact, cohesive, perfectly balanced)
        self.hero_card = SimpleCardWidget(home_container)
        self.status_card = self.hero_card  # Aliased for backward compatibility with tests
        self.hero_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.hero_card.setMinimumWidth(0)
        hero_main_layout = QVBoxLayout(self.hero_card)
        hero_main_layout.setContentsMargins(20, 16, 20, 16)
        hero_main_layout.setSpacing(10)

        hero_top_row = QHBoxLayout()
        hero_top_row.setSpacing(10)
        hero_top_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # Left status icon (non-clickable indicator)
        self.status_icon = ToolButton(FIF.ACCEPT, self.hero_card)
        self.status_icon.setEnabled(False)
        self.status_icon.setFixedSize(36, 36)
        self.status_icon.setIconSize(QSize(18, 18))
        hero_top_row.addWidget(self.status_icon)

        # Left text column
        status_info_col = QVBoxLayout()
        status_info_col.setSpacing(3)
        status_info_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        title_badge_row = QHBoxLayout()
        title_badge_row.setSpacing(0)
        title_badge_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self.steam_title = StrongBodyLabel(tr("steam_title_default"), self.hero_card)
        self.steam_title.hide()  # Hidden to eliminate dead space; .text() retained for tests
        self.status_badge = CaptionLabel(tr("badge_checking"), self.hero_card)
        title_badge_row.addWidget(self.status_badge)
        title_badge_row.addStretch(1)

        self.steam_desc = CaptionLabel(tr("desc_checking"), self.hero_card)
        self.steam_desc.setWordWrap(True)
        self.steam_desc.setStyleSheet("font-size: 12px;")

        status_info_col.addLayout(title_badge_row)
        status_info_col.addWidget(self.steam_desc)
        hero_top_row.addLayout(status_info_col, 1)

        # Right dynamic action button stack
        actions_row = QHBoxLayout()
        actions_row.setSpacing(10)
        actions_row.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.action_stack = QStackedWidget(self.hero_card)
        self.action_stack.setFixedSize(235, 40)
        self.action_stack_opacity = QGraphicsOpacityEffect(self.action_stack)
        self.action_stack.setGraphicsEffect(self.action_stack_opacity)

        # Mode 0: Sync Games
        self.btn_sync = PrimaryPushButton(tr("btn_sync"), self.action_stack, FIF.SYNC)
        self.btn_sync.setFixedSize(235, 40)
        self.btn_sync.setToolTip(tr("btn_sync_tip"))
        self.btn_sync.clicked.connect(self.start_sync)
        self.action_stack.addWidget(self.btn_sync)

        # Mode 1: Close Steam (No icon overlap bug; uses internal QHBoxLayout)
        self.btn_close_steam = CloseSteamButton(tr("btn_close_steam"), self.action_stack)
        self.btn_close_steam.setToolTip(tr("btn_close_steam_tip"))
        self.btn_close_steam.clicked.connect(self.close_steam)
        self.action_stack.addWidget(self.btn_close_steam)

        # Mode 2: Browse Steam Folder (When Steam is missing on PC)
        self.btn_browse_hero = PushButton(tr("btn_browse_steam"), self.action_stack, FIF.FOLDER)
        self.btn_browse_hero.setFixedSize(235, 40)
        self.btn_browse_hero.setToolTip(tr("desc_not_found"))
        self.btn_browse_hero.clicked.connect(self.browse_steam_dir)
        self.action_stack.addWidget(self.btn_browse_hero)

        # Mode 3: Launch Steam (Primary action when library is up-to-date and Steam is closed)
        self.btn_launch_steam = PrimaryPushButton(tr("btn_launch_steam"), self.action_stack, FIF.PLAY)
        self.btn_launch_steam.setFixedSize(235, 40)
        self.btn_launch_steam.setToolTip(tr("btn_launch_steam"))
        self.btn_launch_steam.clicked.connect(self.launch_steam)
        self.action_stack.addWidget(self.btn_launch_steam)

        actions_row.addWidget(self.action_stack)

        # Download Steam button (appears beside action_stack when Steam is not installed)
        self.btn_download_steam = PushButton(tr("btn_download_steam"), self.hero_card, FIF.GLOBE)
        self.btn_download_steam.setFixedSize(140, 40)
        self.btn_download_steam.setVisible(False)
        self.btn_download_steam.setToolTip(tr("btn_download_steam"))
        self.btn_download_steam.clicked.connect(self.open_steam_website)
        actions_row.addWidget(self.btn_download_steam)

        hero_top_row.addLayout(actions_row)
        hero_main_layout.addLayout(hero_top_row)

        # Slim progress bar integrated along the bottom edge of the hero card
        self.progress_bar = ProgressBar(self.hero_card)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(3)
        self.progress_bar.setVisible(False)
        hero_main_layout.addWidget(self.progress_bar)

        layout.addWidget(self.hero_card)

        # 2. Discovered Games Header
        games_header = QHBoxLayout()
        games_header.setContentsMargins(4, 8, 4, 0)
        self.lbl_games_title = SubtitleLabel(tr("games_title_scanning"), home_container)
        games_header.addWidget(self.lbl_games_title)
        games_header.addStretch(1)
        layout.addLayout(games_header)

        # Adaptive Grid for Games Cards (2 columns inside 1000px max-width container)
        self.games_container = QWidget(home_container)
        self.games_container.setObjectName("gamesContainer")
        self.games_layout = QGridLayout(self.games_container)
        self.games_layout.setContentsMargins(0, 0, 0, 0)
        self.games_layout.setSpacing(12)
        self._game_card_count = 0

        # Spacer maintaining count() == 1 when cards are cleared (1 column Inset Grouped layout)
        self._games_spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        self.games_layout.addItem(self._games_spacer, 999, 0, 1, 1)

        layout.addWidget(self.games_container)
        layout.addStretch(1)

        home_scroll_layout.addWidget(home_container)
        self.home_scroll.setWidget(home_scroll_widget)
        root_layout.addWidget(self.home_scroll)

        # Add to Navigation
        self.nav_home = self.addSubInterface(
            self.home_interface,
            FIF.HOME,
            tr("nav_home"),
            NavigationItemPosition.TOP
        )

    # --------------------------------------------------------------------------
    # Settings Tab (With Integrated Operation Log)
    # --------------------------------------------------------------------------
    def init_settings_interface(self):
        self.settings_interface = QWidget(self)
        self.settings_interface.setObjectName("settingsInterface")
        root_layout = QVBoxLayout(self.settings_interface)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.settings_scroll = ScrollArea(self.settings_interface)
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.settings_scroll.setSmoothMode(SmoothMode.QUADRATI, Qt.Orientation.Vertical)
        setup_high_hz_smooth_scroll(self.settings_scroll)
        self.settings_scroll.enableTransparentBackground()
        if self.settings_scroll.viewport():
            self.settings_scroll.viewport().setObjectName("settingsScrollViewport")
            self.settings_scroll.viewport().setAutoFillBackground(False)
        self.settings_scroll.setStyleSheet("""
            QScrollArea, #settingsScrollViewport, #settingsScrollWidget {
                background: transparent;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 4px;
                margin: 0px 2px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: rgba(255, 255, 255, 0.25);
                min-height: 24px;
                border-radius: 2px;
            }
            QScrollBar::handle:vertical:hover {
                background: rgba(255, 255, 255, 0.50);
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
                height: 0px;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)

        settings_scroll_widget = QWidget()
        settings_scroll_widget.setObjectName("settingsScrollWidget")
        settings_scroll_layout = QVBoxLayout(settings_scroll_widget)
        settings_scroll_layout.setContentsMargins(20, 16, 20, 16)
        settings_scroll_layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)

        # Compact Inset Grouped MaxWidth container (Apple / Fluent: 860 px)
        settings_container = QWidget(settings_scroll_widget)
        settings_container.setMaximumWidth(860)
        settings_container.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(settings_container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        header_row = QHBoxLayout()
        header_row.setSpacing(12)
        self.btn_back_home = PushButton(tr("btn_back_to_library"), settings_container, FIF.LEFT_ARROW)
        self.btn_back_home.setFixedWidth(180)
        self.btn_back_home.clicked.connect(lambda: self.switchTo(self.home_interface))
        self.lbl_settings_title = TitleLabel(tr("settings_title"), settings_container)
        header_row.addWidget(self.btn_back_home)
        header_row.addWidget(self.lbl_settings_title)
        header_row.addStretch(1)
        layout.addLayout(header_row)

        # Card 0: Interface Language Selection
        self.lang_card = SimpleCardWidget(settings_container)
        l_layout = QHBoxLayout(self.lang_card)
        l_layout.setContentsMargins(18, 14, 18, 14)
        l_layout.setSpacing(14)

        l_info = QVBoxLayout()
        l_info.setSpacing(2)
        self.lbl_lang_subtitle = SubtitleLabel(tr("sec_language"), self.lang_card)
        self.lbl_lang_desc = CaptionLabel(tr("sec_language_desc"), self.lang_card)
        self.lbl_lang_desc.setWordWrap(True)
        self.lbl_lang_desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        l_info.addWidget(self.lbl_lang_subtitle)
        l_info.addWidget(self.lbl_lang_desc)

        self.cmb_language = ComboBox(self.lang_card)
        self.cmb_language.setFixedWidth(200)
        for code, name in i18n.LANGUAGES.items():
            self.cmb_language.addItem(name, userData=code)

        current_cfg_lang = self.config.get('language', 'auto')
        idx = self.cmb_language.findData(current_cfg_lang)
        if idx >= 0:
            self.cmb_language.setCurrentIndex(idx)
        self.cmb_language.currentIndexChanged.connect(self.on_language_changed)

        l_layout.addLayout(l_info, 1)
        l_layout.addWidget(self.cmb_language)
        layout.addWidget(self.lang_card)

        # Card 1: Folders to scan
        folders_card = SimpleCardWidget(settings_container)
        f_layout = QVBoxLayout(folders_card)
        f_layout.setContentsMargins(18, 14, 18, 14)
        f_layout.setSpacing(12)

        self.lbl_folders_subtitle = SubtitleLabel(tr("sec_folders"), folders_card)
        self.lbl_folders_subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_folders_desc = CaptionLabel(tr("sec_folders_desc"), folders_card)
        self.lbl_folders_desc.setWordWrap(True)
        self.lbl_folders_desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        f_layout.addWidget(self.lbl_folders_subtitle)
        f_layout.addWidget(self.lbl_folders_desc)

        self.list_folders = QListWidget(folders_card)
        self.list_folders.setFixedHeight(120)
        for d in self.game_folders:
            self.list_folders.addItem(d)
        f_layout.addWidget(self.list_folders)

        f_btn_row = FlowLayout(needAni=True)
        f_btn_row.setContentsMargins(0, 0, 0, 0)
        f_btn_row.setHorizontalSpacing(8)
        f_btn_row.setVerticalSpacing(8)
        self.btn_add_folder = PushButton(tr("btn_add_folder"), folders_card, FIF.FOLDER)
        self.btn_add_folder.setToolTip(tr("btn_add_folder_tip"))
        self.btn_add_folder.clicked.connect(self.add_folder)
        self.btn_remove_folder = PushButton(tr("btn_remove_folder"), folders_card, FIF.DELETE)
        self.btn_remove_folder.setToolTip(tr("btn_remove_folder_tip"))
        self.btn_remove_folder.clicked.connect(self.remove_folder)
        self.btn_detect_launchers = PushButton(tr("btn_detect_launchers"), folders_card, FIF.SEARCH)
        self.btn_detect_launchers.setToolTip(tr("btn_detect_launchers_tip"))
        self.btn_detect_launchers.clicked.connect(self.detect_launchers)
        self.btn_reset_folders = PushButton(tr("btn_reset_folders"), folders_card, FIF.SYNC)
        self.btn_reset_folders.setToolTip(tr("btn_reset_folders_tip"))
        self.btn_reset_folders.clicked.connect(self.reset_folders)
        f_btn_row.addWidget(self.btn_add_folder)
        f_btn_row.addWidget(self.btn_remove_folder)
        f_btn_row.addWidget(self.btn_detect_launchers)
        f_btn_row.addWidget(self.btn_reset_folders)
        f_layout.addLayout(f_btn_row)

        layout.addWidget(folders_card)

        # Card 2: Steam Configuration (Compact & Aligned, zero wasted space)
        steam_card = SimpleCardWidget(settings_container)
        s_layout = QVBoxLayout(steam_card)
        s_layout.setContentsMargins(18, 14, 18, 14)
        s_layout.setSpacing(12)

        self.lbl_steam_subtitle = SubtitleLabel(tr("sec_steam"), steam_card)
        self.lbl_steam_subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        s_layout.addWidget(self.lbl_steam_subtitle)

        # Steam Path input row
        path_row = QHBoxLayout()
        path_row.setSpacing(16)
        path_info = QVBoxLayout()
        path_info.setSpacing(2)
        self.lbl_path_title = StrongBodyLabel(tr("lbl_steam_path"), steam_card)
        self.lbl_path_desc = CaptionLabel(tr("lbl_steam_path_desc"), steam_card)
        self.lbl_path_desc.setWordWrap(True)
        self.lbl_path_desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        path_info.addWidget(self.lbl_path_title)
        path_info.addWidget(self.lbl_path_desc)

        path_ctrl = QHBoxLayout()
        path_ctrl.setSpacing(8)
        self.txt_steam_path = LineEdit(steam_card)
        self.txt_steam_path.setMinimumWidth(200)
        self.txt_steam_path.setMaximumWidth(360)
        default_steam = self.config.get('steam_path') or steam_syncer.get_steam_path() or ""
        self.txt_steam_path.setText(default_steam)
        self.txt_steam_path.setPlaceholderText(tr("placeholder_steam_path"))
        self.txt_steam_path.textChanged.connect(self.on_steam_path_changed)
        self.btn_browse_steam = PushButton(tr("btn_browse"), steam_card, FIF.FOLDER)
        self.btn_browse_steam.setFixedWidth(110)
        self.btn_browse_steam.clicked.connect(self.browse_steam_dir)
        path_ctrl.addWidget(self.txt_steam_path)
        path_ctrl.addWidget(self.btn_browse_steam)

        path_row.addLayout(path_info, 1)
        path_row.addLayout(path_ctrl)
        s_layout.addLayout(path_row)

        # Steam User Account row
        user_row = QHBoxLayout()
        user_row.setSpacing(16)
        user_info = QVBoxLayout()
        user_info.setSpacing(2)
        self.lbl_account_title = StrongBodyLabel(tr("lbl_steam_account"), steam_card)
        self.lbl_account_desc = CaptionLabel(tr("lbl_steam_account_desc"), steam_card)
        self.lbl_account_desc.setWordWrap(True)
        self.lbl_account_desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        user_info.addWidget(self.lbl_account_title)
        user_info.addWidget(self.lbl_account_desc)

        self.cmb_steam_users = ComboBox(steam_card)
        self.cmb_steam_users.setFixedWidth(280)
        self.populate_steam_users(default_steam)
        self.cmb_steam_users.currentIndexChanged.connect(self.on_user_changed)

        user_row.addLayout(user_info, 1)
        user_row.addWidget(self.cmb_steam_users)
        s_layout.addLayout(user_row)

        layout.addWidget(steam_card)

        # Card 3: Download & Appearance Options
        options_card = SimpleCardWidget(settings_container)
        o_layout = QVBoxLayout(options_card)
        o_layout.setContentsMargins(18, 16, 18, 16)
        o_layout.setSpacing(14)

        self.lbl_options_subtitle = SubtitleLabel(tr("sec_options"), options_card)
        self.lbl_options_subtitle.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        o_layout.addWidget(self.lbl_options_subtitle)

        # Switch: Download artwork
        art_row = QHBoxLayout()
        art_info = QVBoxLayout()
        art_info.setSpacing(4)
        self.lbl_art_title = StrongBodyLabel(tr("lbl_art"), options_card)
        self.lbl_art_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_art_desc = CaptionLabel(tr("lbl_art_desc"), options_card)
        self.lbl_art_desc.setWordWrap(True)
        self.lbl_art_desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        art_info.addWidget(self.lbl_art_title)
        art_info.addWidget(self.lbl_art_desc)
        self.sw_download_art = DraggableSwitchButton(options_card)
        self.sw_download_art.setChecked(self.config.get('download_artwork', True))
        self.sw_download_art.checkedChanged.connect(self.persist_settings)
        art_row.addLayout(art_info, 1)
        art_row.addSpacing(16)
        art_row.addWidget(self.sw_download_art)
        o_layout.addLayout(art_row)

        # Switch: Auto backup
        bak_row = QHBoxLayout()
        bak_info = QVBoxLayout()
        bak_info.setSpacing(4)
        self.lbl_bak_title = StrongBodyLabel(tr("lbl_backup"), options_card)
        self.lbl_bak_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_bak_desc = CaptionLabel(tr("lbl_backup_desc"), options_card)
        self.lbl_bak_desc.setWordWrap(True)
        self.lbl_bak_desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        bak_info.addWidget(self.lbl_bak_title)
        bak_info.addWidget(self.lbl_bak_desc)
        self.sw_backup = DraggableSwitchButton(options_card)
        self.sw_backup.setChecked(self.config.get('backup_shortcuts', True))
        self.sw_backup.checkedChanged.connect(self.persist_settings)
        bak_row.addLayout(bak_info, 1)
        bak_row.addSpacing(16)
        bak_row.addWidget(self.sw_backup)
        o_layout.addLayout(bak_row)

        # Switch: Background Auto-Scan
        auto_scan_row = QHBoxLayout()
        auto_scan_info = QVBoxLayout()
        auto_scan_info.setSpacing(4)
        self.lbl_auto_scan_title = StrongBodyLabel(tr("lbl_auto_scan"), options_card)
        self.lbl_auto_scan_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_auto_scan_desc = CaptionLabel(tr("lbl_auto_scan_desc"), options_card)
        self.lbl_auto_scan_desc.setWordWrap(True)
        self.lbl_auto_scan_desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        auto_scan_info.addWidget(self.lbl_auto_scan_title)
        auto_scan_info.addWidget(self.lbl_auto_scan_desc)
        self.sw_auto_scan = DraggableSwitchButton(options_card)
        self.sw_auto_scan.setChecked(self.config.get('auto_scan', True))
        self.sw_auto_scan.checkedChanged.connect(self.on_auto_scan_toggled)
        auto_scan_row.addLayout(auto_scan_info, 1)
        auto_scan_row.addSpacing(16)
        auto_scan_row.addWidget(self.sw_auto_scan)
        o_layout.addLayout(auto_scan_row)

        # SteamGridDB API Key
        sgdb_row = QHBoxLayout()
        sgdb_info = QVBoxLayout()
        sgdb_info.setSpacing(4)
        self.lbl_sgdb_title = StrongBodyLabel(tr("lbl_steamgriddb_key"), options_card)
        self.lbl_sgdb_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_sgdb_desc = CaptionLabel(tr("lbl_steamgriddb_key_desc"), options_card)
        self.lbl_sgdb_desc.setWordWrap(True)
        self.lbl_sgdb_desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        sgdb_info.addWidget(self.lbl_sgdb_title)
        sgdb_info.addWidget(self.lbl_sgdb_desc)
        self.txt_steamgriddb_key = LineEdit(options_card)
        self.txt_steamgriddb_key.setPlaceholderText(tr("placeholder_steamgriddb_key"))
        self.txt_steamgriddb_key.setText(self.config.get('steamgriddb_key', ''))
        self.txt_steamgriddb_key.textChanged.connect(self.persist_settings)
        self.txt_steamgriddb_key.setFixedWidth(280)
        sgdb_row.addLayout(sgdb_info, 1)
        sgdb_row.addSpacing(16)
        sgdb_row.addWidget(self.txt_steamgriddb_key)
        o_layout.addLayout(sgdb_row)

        # Switch: Smart Steam Lifecycle
        life_row = QHBoxLayout()
        life_info = QVBoxLayout()
        life_info.setSpacing(4)
        self.lbl_life_title = StrongBodyLabel(tr("lbl_auto_steam_lifecycle"), options_card)
        self.lbl_life_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_life_desc = CaptionLabel(tr("lbl_auto_steam_lifecycle_desc"), options_card)
        self.lbl_life_desc.setWordWrap(True)
        self.lbl_life_desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        life_info.addWidget(self.lbl_life_title)
        life_info.addWidget(self.lbl_life_desc)
        self.sw_auto_steam_lifecycle = DraggableSwitchButton(options_card)
        self.sw_auto_steam_lifecycle.setChecked(self.config.get('auto_steam_lifecycle', False))
        self.sw_auto_steam_lifecycle.checkedChanged.connect(self.persist_settings)
        life_row.addLayout(life_info, 1)
        life_row.addSpacing(16)
        life_row.addWidget(self.sw_auto_steam_lifecycle)
        o_layout.addLayout(life_row)

        layout.addWidget(options_card)

        # Card 4: Operation Log Section (Integrated into Settings)
        self.log_card = SimpleCardWidget(settings_container)
        log_layout = QVBoxLayout(self.log_card)
        log_layout.setContentsMargins(18, 16, 18, 16)
        log_layout.setSpacing(12)

        log_header = QHBoxLayout()
        log_title_col = QVBoxLayout()
        log_title_col.setSpacing(2)
        self.lbl_log_title = SubtitleLabel(tr("sec_log"), self.log_card)
        self.lbl_log_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_log_desc = CaptionLabel(tr("sec_log_desc"), self.log_card)
        self.lbl_log_desc.setWordWrap(True)
        self.lbl_log_desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        log_title_col.addWidget(self.lbl_log_title)
        log_title_col.addWidget(self.lbl_log_desc)
        log_header.addLayout(log_title_col, 1)

        self.btn_copy_log = PushButton(tr("btn_copy_log"), self.log_card, FIF.COPY)
        self.btn_copy_log.clicked.connect(self.copy_log_to_clipboard)
        self.btn_clear_log = PushButton(tr("btn_clear_log"), self.log_card, FIF.DELETE)
        self.btn_clear_log.clicked.connect(lambda: self.log_text.clear())
        log_header.addWidget(self.btn_copy_log)
        log_header.addWidget(self.btn_clear_log)
        log_layout.addLayout(log_header)

        # Attributes preserved as None for clean defensive compatibility
        self.lbl_metric_status = None
        self.lbl_metric_games = None
        self.lbl_metric_art = None

        # Console Text Edit
        self.log_text = TextEdit(self.log_card)
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(240)
        self.log_text.setStyleSheet("""
            TextEdit {
                background: rgba(0, 0, 0, 0.35);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 6px;
                font-family: 'Cascadia Code', 'Consolas', 'Segoe UI Variable', monospace;
                font-size: 11px;
                padding: 10px;
                color: rgba(255, 255, 255, 0.9);
            }
        """)
        log_layout.addWidget(self.log_text)
        layout.addWidget(self.log_card)

        # Card 5: Support & Donations / Поддержать проект
        self.donate_card = SimpleCardWidget(settings_container)
        donate_layout = QVBoxLayout(self.donate_card)
        donate_layout.setContentsMargins(18, 16, 18, 16)
        donate_layout.setSpacing(12)

        donate_header = QHBoxLayout()
        donate_title_col = QVBoxLayout()
        donate_title_col.setSpacing(2)
        self.lbl_donate_title = SubtitleLabel(tr("sec_donate"), self.donate_card)
        self.lbl_donate_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_donate_desc = CaptionLabel(
            tr("sec_donate_desc"),
            self.donate_card
        )
        self.lbl_donate_desc.setWordWrap(True)
        self.lbl_donate_desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        donate_title_col.addWidget(self.lbl_donate_title)
        donate_title_col.addWidget(self.lbl_donate_desc)
        donate_header.addLayout(donate_title_col, 1)
        donate_layout.addLayout(donate_header)

        # Responsive FlowLayout for Support Buttons (zero horizontal overflow, wraps gracefully)
        buttons_flow = FlowLayout(needAni=False)
        buttons_flow.setSpacing(10)
        buttons_flow.setContentsMargins(0, 4, 0, 0)

        self.btn_tribute = PrimaryPushButton(tr("btn_donate_tribute"), self.donate_card, FIF.HEART)
        self.btn_tribute.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://web.tribute.tg/d/SsO")))

        self.btn_boosty = PushButton(tr("btn_donate_boosty"), self.donate_card, FIF.CAFE)
        self.btn_boosty.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://boosty.to/n300l/donate")))

        self.btn_show_crypto = PushButton(tr("btn_show_crypto_qr"), self.donate_card, FIF.QRCODE)
        def show_crypto_dialog():
            dlg = CryptoDonationDialog(self)
            dlg.exec()

        self.btn_show_crypto.clicked.connect(show_crypto_dialog)

        self.btn_copy_usdt = PushButton("USDT (BEP20)", self.donate_card, FIF.COPY)
        def copy_usdt_address():
            cb = QApplication.clipboard()
            if cb:
                cb.setText("0xb9e67030ab0f38d1d88e4eaa605fb2acf0aa0ba3")
            self.show_toast("success", title=tr("sec_donate"), content=tr("toast_address_copied", coin="USDT (BEP20)"), duration=3500)
            self.btn_copy_usdt.setText(tr("badge_copied"))
            QTimer.singleShot(2500, lambda: self.btn_copy_usdt.setText("USDT (BEP20)"))
        self.btn_copy_usdt.clicked.connect(copy_usdt_address)

        self.btn_copy_trc = PushButton("USDT (TRC20)", self.donate_card, FIF.COPY)
        def copy_trc_address():
            cb = QApplication.clipboard()
            if cb:
                cb.setText("TQ4RwzWxs4kD6WXFgJkejRMSeAPsGUTv44")
            self.show_toast("success", title=tr("sec_donate"), content=tr("toast_address_copied", coin="USDT (TRC20)"), duration=3500)
            self.btn_copy_trc.setText(tr("badge_copied"))
            QTimer.singleShot(2500, lambda: self.btn_copy_trc.setText("USDT (TRC20)"))
        self.btn_copy_trc.clicked.connect(copy_trc_address)

        buttons_flow.addWidget(self.btn_tribute)
        buttons_flow.addWidget(self.btn_boosty)
        buttons_flow.addWidget(self.btn_show_crypto)
        buttons_flow.addWidget(self.btn_copy_usdt)
        buttons_flow.addWidget(self.btn_copy_trc)

        donate_layout.addLayout(buttons_flow)

        layout.addWidget(self.donate_card)

        # Card 6: About DeckBridge
        self.about_card = SimpleCardWidget(settings_container)
        about_layout = QVBoxLayout(self.about_card)
        about_layout.setContentsMargins(18, 16, 18, 16)
        about_layout.setSpacing(12)

        about_header = QHBoxLayout()
        about_title_col = QVBoxLayout()
        about_title_col.setSpacing(2)
        self.lbl_about_title = SubtitleLabel(f"DeckBridge v{APP_VERSION}", self.about_card)
        self.lbl_about_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_about_desc = CaptionLabel(
            "Non-Steam Game & Official Artwork Bridge for Windows 11 & Steam Deck. Licensed under GNU GPLv3.",
            self.about_card
        )
        self.lbl_about_desc.setWordWrap(True)
        self.lbl_about_desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        about_title_col.addWidget(self.lbl_about_title)
        about_title_col.addWidget(self.lbl_about_desc)
        about_header.addLayout(about_title_col, 1)

        btn_github = PushButton("GitHub", self.about_card, FIF.GITHUB)
        btn_github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/msmr14/DeckBridge")))
        about_header.addWidget(btn_github)
        about_layout.addLayout(about_header)

        layout.addWidget(self.about_card)
        layout.addStretch(1)

        settings_scroll_layout.addWidget(settings_container)
        self.settings_scroll.setWidget(settings_scroll_widget)
        root_layout.addWidget(self.settings_scroll)

        self.nav_settings = self.addSubInterface(
            self.settings_interface,
            FIF.SETTING,
            tr("nav_settings"),
            NavigationItemPosition.BOTTOM
        )

    # --------------------------------------------------------------------------
    # UI Actions & Configuration Management
    # --------------------------------------------------------------------------
    def append_log(self, text: str):
        self.log_text.append(text)

    def copy_log_to_clipboard(self):
        text = self.log_text.toPlainText()
        if text:
            clipboard = QApplication.clipboard()
            if clipboard:
                clipboard.setText(text)
            self.show_toast(
                "info",
                title=tr("sec_log"),
                content=tr("log_copied_msg"),
                duration=2500
            )

    def on_language_changed(self, idx: int):
        code = self.cmb_language.currentData() or "auto"
        if getattr(self, 'cmb_header_lang', None):
            h_idx = self.cmb_header_lang.findData(code)
            if h_idx >= 0 and self.cmb_header_lang.currentIndex() != h_idx:
                self.cmb_header_lang.blockSignals(True)
                self.cmb_header_lang.setCurrentIndex(h_idx)
                self.cmb_header_lang.blockSignals(False)
        self.config['language'] = code
        i18n.I18NManager.instance().set_language(code)
        save_app_config(self.config)
        self.retranslate_ui()

    def retranslate_ui(self):
        """Refreshes all visible UI texts and controls dynamically upon language change."""
        if hasattr(self, 'nav_home') and self.nav_home:
            self.nav_home.setText(tr("nav_home"))
        if hasattr(self, 'nav_settings') and self.nav_settings:
            self.nav_settings.setText(tr("nav_settings"))
        if hasattr(self, 'btn_back_home') and self.btn_back_home:
            self.btn_back_home.setText(tr("btn_back_to_library"))
        if hasattr(self, 'steam_dot') and self.steam_dot:
            is_running = steam_syncer.is_steam_running()
            self.steam_dot.setToolTip(tr("steam_dot_running") if is_running else tr("steam_dot_ready"))

        self.update_sync_button_text()
        self.btn_close_steam.setText(tr("btn_close_steam"))
        self.btn_close_steam.setToolTip(tr("btn_close_steam_tip"))
        self.btn_browse_hero.setText(tr("btn_browse_steam"))
        self.btn_launch_steam.setText(tr("btn_launch_steam"))

        if hasattr(self, 'lbl_settings_title'):
            self.lbl_settings_title.setText(tr("settings_title"))
        if hasattr(self, 'lbl_lang_subtitle'):
            self.lbl_lang_subtitle.setText(tr("sec_language"))
        if hasattr(self, 'lbl_lang_desc'):
            self.lbl_lang_desc.setText(tr("sec_language_desc"))
        if hasattr(self, 'lbl_folders_subtitle'):
            self.lbl_folders_subtitle.setText(tr("sec_folders"))
        if hasattr(self, 'lbl_folders_desc'):
            self.lbl_folders_desc.setText(tr("sec_folders_desc"))
        if hasattr(self, 'btn_add_folder'):
            self.btn_add_folder.setText(tr("btn_add_folder"))
        if hasattr(self, 'btn_remove_folder'):
            self.btn_remove_folder.setText(tr("btn_remove_folder"))
        if hasattr(self, 'btn_detect_launchers'):
            self.btn_detect_launchers.setText(tr("btn_detect_launchers"))
            self.btn_detect_launchers.setToolTip(tr("btn_detect_launchers_tip"))
        if hasattr(self, 'btn_reset_folders'):
            self.btn_reset_folders.setText(tr("btn_reset_folders"))

        if hasattr(self, 'lbl_steam_subtitle'):
            self.lbl_steam_subtitle.setText(tr("sec_steam"))
        if hasattr(self, 'lbl_path_title'):
            self.lbl_path_title.setText(tr("lbl_steam_path"))
        if hasattr(self, 'lbl_path_desc'):
            self.lbl_path_desc.setText(tr("lbl_steam_path_desc"))
        if hasattr(self, 'btn_browse_steam'):
            self.btn_browse_steam.setText(tr("btn_browse"))
        if hasattr(self, 'txt_steam_path'):
            self.txt_steam_path.setPlaceholderText(tr("placeholder_steam_path"))
        if hasattr(self, 'lbl_account_title'):
            self.lbl_account_title.setText(tr("lbl_steam_account"))
        if hasattr(self, 'lbl_account_desc'):
            self.lbl_account_desc.setText(tr("lbl_steam_account_desc"))

        if hasattr(self, 'lbl_options_subtitle'):
            self.lbl_options_subtitle.setText(tr("sec_options"))
        if hasattr(self, 'lbl_art_title'):
            self.lbl_art_title.setText(tr("lbl_art"))
        if hasattr(self, 'lbl_art_desc'):
            self.lbl_art_desc.setText(tr("lbl_art_desc"))
        if hasattr(self, 'lbl_bak_title'):
            self.lbl_bak_title.setText(tr("lbl_backup"))
        if hasattr(self, 'lbl_bak_desc'):
            self.lbl_bak_desc.setText(tr("lbl_backup_desc"))
        if hasattr(self, 'lbl_auto_scan_title'):
            self.lbl_auto_scan_title.setText(tr("lbl_auto_scan"))
        if hasattr(self, 'lbl_auto_scan_desc'):
            self.lbl_auto_scan_desc.setText(tr("lbl_auto_scan_desc"))
        if hasattr(self, 'lbl_sgdb_title'):
            self.lbl_sgdb_title.setText(tr("lbl_steamgriddb_key"))
        if hasattr(self, 'lbl_sgdb_desc'):
            self.lbl_sgdb_desc.setText(tr("lbl_steamgriddb_key_desc"))
        if hasattr(self, 'txt_steamgriddb_key'):
            self.txt_steamgriddb_key.setPlaceholderText(tr("placeholder_steamgriddb_key"))
        if hasattr(self, 'lbl_life_title'):
            self.lbl_life_title.setText(tr("lbl_auto_steam_lifecycle"))
        if hasattr(self, 'lbl_life_desc'):
            self.lbl_life_desc.setText(tr("lbl_auto_steam_lifecycle_desc"))

        if hasattr(self, 'lbl_log_title'):
            self.lbl_log_title.setText(tr("sec_log"))
        if hasattr(self, 'lbl_log_desc'):
            self.lbl_log_desc.setText(tr("sec_log_desc"))
        if hasattr(self, 'btn_clear_log'):
            self.btn_clear_log.setText(tr("btn_clear_log"))
        if hasattr(self, 'btn_copy_log'):
            self.btn_copy_log.setText(tr("btn_copy_log"))

        if hasattr(self, 'btn_download_steam') and self.btn_download_steam:
            self.btn_download_steam.setText(tr("btn_download_steam"))
            self.btn_download_steam.setToolTip(tr("btn_download_steam"))

        if hasattr(self, 'lbl_donate_title'):
            self.lbl_donate_title.setText(tr("sec_donate"))
        if hasattr(self, 'lbl_donate_desc'):
            self.lbl_donate_desc.setText(tr("sec_donate_desc"))
        if hasattr(self, 'btn_tribute'):
            self.btn_tribute.setText(tr("btn_donate_tribute"))
        if hasattr(self, 'btn_boosty'):
            self.btn_boosty.setText(tr("btn_donate_boosty"))
        if hasattr(self, 'btn_show_crypto'):
            self.btn_show_crypto.setText(tr("btn_show_crypto_qr"))

        if getattr(self, 'lbl_metric_status', None):
            last_report = getattr(self, '_last_report', None)
            if last_report:
                if last_report.get('success'):
                    self.lbl_metric_status.setText(tr("metric_status_done"))
                else:
                    self.lbl_metric_status.setText(tr("metric_status_error"))
                if getattr(self, 'lbl_metric_games', None):
                    self.lbl_metric_games.setText(tr("metric_games", count=last_report.get('games_added', 0)))
                if getattr(self, 'lbl_metric_art', None):
                    self.lbl_metric_art.setText(tr("metric_art", count=last_report.get('art_downloaded', 0)))
            else:
                self.lbl_metric_status.setText(tr("metric_status_ready"))
                if getattr(self, 'lbl_metric_games', None):
                    self.lbl_metric_games.setText(tr("metric_games", count=0))
                if getattr(self, 'lbl_metric_art', None):
                    self.lbl_metric_art.setText(tr("metric_art", count=0))

        self.refresh_steam_status()
        self.update_sync_button_text()

    def update_sync_button_text(self):
        count = getattr(self, '_scanned_games_count', 0)
        new_count = getattr(self, '_new_games_count', -1)

        current_games = getattr(self, '_current_games', [])
        if current_games:
            new_unregistered = [g for g in current_games if not g.get('is_registered')]
            new_count = len(new_unregistered)
            selected_count = len([g for g in new_unregistered if g.get('selected', True)])
        else:
            selected_count = new_count

        if count > 0 and new_count == 0:
            self.btn_sync.setEnabled(False)
            self.btn_sync.setText(tr("btn_sync_all_up_to_date"))
            self.btn_sync.setToolTip(tr("btn_sync_all_up_to_date"))
            if not steam_syncer.is_steam_running():
                self.animate_set_button_mode("launch")
        elif count > 0 and new_count > 0:
            self.btn_sync.setEnabled(selected_count > 0)
            if selected_count > 0:
                self.btn_sync.setText(f"{tr('btn_sync')} ({selected_count})")
            else:
                self.btn_sync.setText(tr("btn_sync"))
            self.btn_sync.setToolTip(tr("btn_sync_tip"))
            if not steam_syncer.is_steam_running():
                self.animate_set_button_mode("sync")
        else:
            self.btn_sync.setEnabled(True)
            self.btn_sync.setText(tr("btn_sync"))
            self.btn_sync.setToolTip(tr("btn_sync_tip"))

        if count > 0:
            if hasattr(self, 'lbl_games_title'):
                self.lbl_games_title.setText(tr("games_title_count", count=count))
        else:
            if hasattr(self, 'lbl_games_title'):
                self.lbl_games_title.setText(tr("games_title_scanning"))

    def on_auto_scan_toggled(self, checked: bool):
        self.config['auto_scan'] = checked
        save_app_config(self.config)
        if checked:
            if not self.poll_timer.isActive():
                self.poll_timer.start(2000)
        else:
            if self.poll_timer.isActive():
                self.poll_timer.stop()

    def persist_settings(self):
        self.config['game_folders'] = self.game_folders
        self.config['steam_path'] = self.txt_steam_path.text().strip()
        if hasattr(self, 'cmb_steam_users') and self.cmb_steam_users.count() > 0:
            sel_user = self.cmb_steam_users.currentData()
            if sel_user:
                self.config['user_id'] = sel_user
        self.config['download_artwork'] = self.sw_download_art.isChecked()
        self.config['backup_shortcuts'] = self.sw_backup.isChecked()
        if hasattr(self, 'sw_auto_scan'):
            self.config['auto_scan'] = self.sw_auto_scan.isChecked()
        if hasattr(self, 'txt_steamgriddb_key'):
            self.config['steamgriddb_key'] = self.txt_steamgriddb_key.text().strip()
        if hasattr(self, 'sw_auto_steam_lifecycle'):
            self.config['auto_steam_lifecycle'] = self.sw_auto_steam_lifecycle.isChecked()
        self.config['language'] = self.cmb_language.currentData() or "auto"
        save_app_config(self.config)

    def on_steam_path_changed(self, text: str):
        self.populate_steam_users(text.strip())
        self.refresh_steam_status()
        self.persist_settings()

    def on_user_changed(self, idx: int):
        self.refresh_steam_status()
        self.persist_settings()
        self.preview_scanned_games()

    def refresh_steam_status(self):
        """
        Inspects Steam installation and status:
        - If Steam is not installed/found: states 'Steam: Not found', provides browse button.
        - If Steam is running: states 'Steam: Client is running', provides close button.
        - If Steam is ready: states 'Steam: Ready to sync', provides sync button.
        """
        steam_path = self.txt_steam_path.text().strip() if hasattr(self, 'txt_steam_path') else steam_syncer.get_steam_path()
        steam_installed = bool(steam_path and os.path.isdir(steam_path))

        if not steam_installed:
            if hasattr(self, 'steam_dot'):
                self.steam_dot.set_running_state(False)
            self.hero_card.setStyleSheet("""
                SimpleCardWidget {
                    background-color: rgba(255, 152, 0, 0.12);
                    border: 1px solid rgba(255, 152, 0, 0.40);
                    border-radius: 8px;
                }
            """)
            self.steam_title.setText(tr("steam_title_not_found"))
            self.steam_desc.setText(tr("desc_not_found"))
            self.steam_desc.setVisible(True)
            self.status_icon.setIcon(FIF.QUESTION)
            self.status_badge.setText(tr("badge_not_found"))
            self.status_badge.setStyleSheet(
                "color: #ffb74d; background: rgba(255, 152, 0, 0.20); "
                "border: 1px solid rgba(255, 152, 0, 0.35); "
                "padding: 3px 10px; border-radius: 4px; font-weight: 600; font-size: 11px;"
            )
            self.animate_set_button_mode("browse")
            if hasattr(self, 'btn_download_steam'):
                self.btn_download_steam.setVisible(True)
            if hasattr(self, 'btn_launch_steam'):
                self.btn_launch_steam.setVisible(False)
            return

        if hasattr(self, 'btn_download_steam'):
            self.btn_download_steam.setVisible(False)

        is_running = steam_syncer.is_steam_running()
        if hasattr(self, 'steam_dot'):
            self.steam_dot.set_running_state(is_running)

        user_id = self.cmb_steam_users.currentData() if hasattr(self, 'cmb_steam_users') else (steam_syncer.get_active_steam_user(steam_path) if steam_path else None)

        users_info = steam_syncer.get_steam_users_info(steam_path) if steam_path else []
        active_persona = user_id or tr("account_undefined")
        for u in users_info:
            if u['account_id'] == user_id:
                active_persona = f"{u['persona_name']} ({u['account_id']})"
                break

        if is_running:
            self.hero_card.setStyleSheet("""
                SimpleCardWidget {
                    background-color: rgba(239, 83, 80, 0.16);
                    border: 1px solid rgba(239, 83, 80, 0.50);
                    border-radius: 8px;
                }
            """)
            self.steam_title.setText(tr("steam_title_running"))
            self.steam_desc.setText(tr("desc_running"))
            self.steam_desc.setVisible(True)
            self.status_icon.setIcon(FIF.INFO)
            self.status_badge.setText(tr("badge_close_required"))
            self.status_badge.setStyleSheet(
                "color: #ef9a9a; background: rgba(198, 40, 40, 0.28); "
                "border: 1px solid rgba(239, 83, 80, 0.45); "
                "padding: 4px 12px; border-radius: 12px; font-weight: 600; font-size: 11px;"
            )
            self.animate_set_button_mode("close")
            if hasattr(self, 'btn_launch_steam'):
                self.btn_launch_steam.setVisible(False)
        else:
            self.hero_card.setStyleSheet("""
                SimpleCardWidget {
                    background-color: rgba(30, 30, 34, 0.72);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 8px;
                }
            """)
            self.steam_title.setText(tr("steam_title_ready"))
            self.status_icon.setIcon(FIF.ACCEPT)

            scanned = getattr(self, '_scanned_games_count', 0)
            new_cnt = getattr(self, '_new_games_count', -1)

            if scanned > 0 and new_cnt == 0:
                self.steam_desc.setText(tr("desc_up_to_date"))
                self.steam_desc.setVisible(True)
                self.status_badge.setText(tr("badge_up_to_date"))
                self.status_badge.setStyleSheet(
                    "color: #81c784; background: rgba(46, 125, 50, 0.25); "
                    "border: 1px solid rgba(76, 175, 80, 0.40); "
                    "padding: 4px 12px; border-radius: 12px; font-weight: 600; font-size: 11px;"
                )
                self.animate_set_button_mode("launch")
            elif scanned > 0 and new_cnt > 0:
                self.steam_desc.setText(tr("desc_ready_to_sync", count=new_cnt))
                self.steam_desc.setVisible(True)
                self.status_badge.setText(tr("badge_ready_to_sync"))
                self.status_badge.setStyleSheet(
                    "color: #81c784; background: rgba(46, 125, 50, 0.25); "
                    "border: 1px solid rgba(76, 175, 80, 0.40); "
                    "padding: 4px 12px; border-radius: 12px; font-weight: 600; font-size: 11px;"
                )
                self.animate_set_button_mode("sync")
            else:
                self.steam_desc.setText(tr("desc_ready_initial"))
                self.steam_desc.setVisible(True)
                self.status_badge.setText(tr("badge_ready"))
                self.status_badge.setStyleSheet(
                    "color: #81c784; background: rgba(46, 125, 50, 0.25); "
                    "border: 1px solid rgba(76, 175, 80, 0.40); "
                    "padding: 4px 12px; border-radius: 12px; font-weight: 600; font-size: 11px;"
                )
                self.animate_set_button_mode("sync")

    def close_steam(self):
        """Initiates graceful closing of the Steam client in background."""
        if self.close_worker and self.close_worker.isRunning():
            return
        self.btn_close_steam.setEnabled(False)
        self.btn_close_steam.setText(tr("btn_closing_steam"))
        steam_p = self.txt_steam_path.text().strip() or None
        self.close_worker = CloseSteamWorker(steam_path=steam_p)
        self.close_worker.closed.connect(self.on_steam_closed_result)
        self.close_worker.start()

    def on_steam_closed_result(self, ok: bool):
        self.btn_close_steam.setEnabled(True)
        self.btn_close_steam.setText(tr("btn_close_steam"))
        is_running = steam_syncer.is_steam_running()
        self._last_steam_running = is_running
        self.refresh_steam_status()
        if ok and not is_running:
            self.notify_steam_state_change(False)
        elif not ok and is_running:
            self.show_toast(
                "warning",
                title=tr("info_steam_close_fail_title"),
                content=tr("info_steam_close_fail_msg"),
                duration=4000
            )

    def animate_set_button_mode(self, mode: str):
        """
        Dynamically transitions the action stack between 'sync' (0), 'close' (1), 'browse' (2), and 'launch' (3).
        """
        if mode == "close":
            target_idx = 1
        elif mode == "browse":
            target_idx = 2
        elif mode == "launch":
            target_idx = 3
        else:
            target_idx = 0

        if getattr(self, '_current_button_mode', None) == mode and self.action_stack.currentIndex() == target_idx:
            return

        self._current_button_mode = mode

        if not self.isVisible():
            self._apply_button_mode_instant(mode)
            return

        for anim_attr in ('_btn_anim_out', '_btn_anim_in'):
            anim = getattr(self, anim_attr, None)
            if anim:
                try:
                    anim.finished.disconnect()
                except Exception:
                    pass
                anim.stop()

        self._btn_anim_out = QPropertyAnimation(self.action_stack_opacity, b"opacity")
        self._btn_anim_out.setDuration(140)
        self._btn_anim_out.setStartValue(self.action_stack_opacity.opacity())
        self._btn_anim_out.setEndValue(0.0)
        self._btn_anim_out.setEasingCurve(QEasingCurve.Type.OutQuad)

        def on_fade_out_done():
            self._apply_button_mode_instant(mode)
            self._btn_anim_in = QPropertyAnimation(self.action_stack_opacity, b"opacity")
            self._btn_anim_in.setDuration(180)
            self._btn_anim_in.setStartValue(0.0)
            self._btn_anim_in.setEndValue(1.0)
            self._btn_anim_in.setEasingCurve(QEasingCurve.Type.InQuad)
            self._btn_anim_in.start()

        self._btn_anim_out.finished.connect(on_fade_out_done)
        self._btn_anim_out.start()

    def _apply_button_mode_instant(self, mode: str):
        if mode == "close":
            target_idx = 1
        elif mode == "browse":
            target_idx = 2
        elif mode == "launch":
            target_idx = 3
        else:
            target_idx = 0
        self.action_stack.setCurrentIndex(target_idx)
        if hasattr(self, 'btn_launch_steam'):
            self.btn_launch_steam.setVisible(mode == "launch" or target_idx == 3)

    def populate_steam_users(self, steam_path: str):
        self.cmb_steam_users.blockSignals(True)
        try:
            self.cmb_steam_users.clear()
            if not steam_path or not os.path.isdir(steam_path):
                return

            users_info = steam_syncer.get_steam_users_info(steam_path)
            if not users_info:
                return

            active_user_id = None
            for u in users_info:
                acc_id = u['account_id']
                pname = u.get('persona_name') or f"User {acc_id}"
                aname = u.get('account_name') or acc_id
                is_active = u.get('is_active', False)
                if is_active:
                    active_user_id = acc_id
                    label = f"{pname} ({aname}) [ID: {acc_id}] {tr('account_active_suffix')}"
                else:
                    label = f"{pname} ({aname}) [ID: {acc_id}]"
                self.cmb_steam_users.addItem(label, userData=acc_id)

            saved_user = self.config.get('user_id')
            user_ids = [u['account_id'] for u in users_info]
            target_user = saved_user if saved_user in user_ids else active_user_id
            if target_user:
                idx = self.cmb_steam_users.findData(target_user)
                if idx >= 0:
                    self.cmb_steam_users.setCurrentIndex(idx)
        finally:
            self.cmb_steam_users.blockSignals(False)

    def browse_steam_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("dialog_select_steam"), self.txt_steam_path.text())
        if d:
            self.txt_steam_path.setText(os.path.normpath(d))
            self.populate_steam_users(d)
            self.refresh_steam_status()
            self.persist_settings()

    def add_folder(self):
        d = QFileDialog.getExistingDirectory(self, tr("dialog_select_game"))
        if d:
            norm = os.path.normpath(d)
            if norm not in self.game_folders:
                self.game_folders.append(norm)
                self.list_folders.addItem(norm)
                self.persist_settings()
                self.preview_scanned_games()

    def remove_folder(self):
        curr_row = self.list_folders.currentRow()
        if curr_row >= 0:
            removed = self.list_folders.takeItem(curr_row).text()
            if removed in self.game_folders:
                self.game_folders.remove(removed)
                self.persist_settings()
                self.preview_scanned_games()

    def detect_launchers(self):
        """Auto-discovers and merges game folders across Amazon, Epic, GOG, Itch, EA, Ubisoft, Playnite, and all drives."""
        discovered = steam_syncer.get_default_game_folders(existing_only=True)
        added_count = 0
        existing_lower = {f.lower() for f in self.game_folders}
        for d in discovered:
            if d.lower() not in existing_lower:
                self.game_folders.append(d)
                self.list_folders.addItem(d)
                existing_lower.add(d.lower())
                added_count += 1
        self.persist_settings()
        self.preview_scanned_games()
        msg = tr("msg_launchers_detected").format(count=len(self.game_folders))
        self.append_log(msg)
        self.show_toast(
            "success",
            title=tr("sec_folders"),
            content=msg,
            duration=3500
        )

    def reset_folders(self):
        """Resets the folder list to comprehensive defaults across all launchers and drives."""
        self.game_folders = steam_syncer.get_default_game_folders(existing_only=True)
        self.list_folders.clear()
        for d in self.game_folders:
            self.list_folders.addItem(d)
        self.persist_settings()
        self.preview_scanned_games()
        msg = tr("msg_reset_folders")
        self.append_log(msg)
        self.show_toast(
            "info",
            title=tr("sec_folders"),
            content=msg,
            duration=2500
        )

    def preview_scanned_games(self):
        """Asynchronously discovers games in background so GUI never stutters or lags."""
        if (self.scan_worker and self.scan_worker.isRunning()) or (self.worker and self.worker.isRunning()):
            return
        if len(self._pixmap_cache) > 200:
            self._pixmap_cache.clear()
        if hasattr(self, 'lbl_games_title'):
            self.lbl_games_title.setText(tr("games_title_scanning"))
        if hasattr(self, 'steam_dot') and self.steam_dot:
            self.steam_dot.set_pulsing(True)

        steam_path = self.txt_steam_path.text().strip() or steam_syncer.get_steam_path()
        user_id = self.cmb_steam_users.currentData() if hasattr(self, 'cmb_steam_users') else (steam_syncer.get_active_steam_user(steam_path) if steam_path else None)

        self.scan_worker = ScanWorker(
            game_folders=self.game_folders,
            steam_path=steam_path,
            user_id=user_id
        )
        self.scan_worker.scan_finished.connect(self.on_scan_finished)
        self.scan_worker.start()

    def on_scan_finished(self, games: list, existing_exes: set, covers_map: dict):
        if hasattr(self, 'steam_dot') and self.steam_dot:
            self.steam_dot.set_pulsing(False, delayed=True)
        self.clear_game_cards()
        count = len(games)
        self._scanned_games_count = count
        self._current_games = games

        if not games:
            self._new_games_count = 0
            self.update_sync_button_text()
            self.refresh_steam_status()
            empty_card = SimpleCardWidget(self.games_container)
            empty_card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            empty_card.setMinimumWidth(0)
            empty_layout = QVBoxLayout(empty_card)
            empty_layout.setContentsMargins(24, 32, 24, 32)
            empty_layout.setSpacing(12)
            empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

            empty_icon = TitleLabel("🎮", empty_card)
            empty_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_layout.addWidget(empty_icon)

            empty_title = StrongBodyLabel(tr("games_empty_title"), empty_card)
            empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_title.setWordWrap(True)
            empty_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            empty_layout.addWidget(empty_title)

            empty_desc = CaptionLabel(tr("games_empty_desc"), empty_card)
            empty_desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_desc.setWordWrap(True)
            empty_desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            empty_layout.addWidget(empty_desc)

            btn_pick_folder = PushButton(tr("btn_pick_folder"), empty_card, FIF.FOLDER)
            btn_pick_folder.setFixedSize(220, 36)
            btn_pick_folder.clicked.connect(self.add_folder)
            empty_layout.addWidget(btn_pick_folder, alignment=Qt.AlignmentFlag.AlignCenter)

            self.games_layout.addWidget(empty_card, 0, 0, 1, 1)
            return

        for g in games:
            norm_exe = os.path.normpath(g['exe_path']).lower()
            g['is_registered'] = norm_exe in existing_exes
            g['cover_path'] = covers_map.get(g['exe_path'])
            self.add_game_card(g)

        new_count = len([g for g in games if not g.get('is_registered')])
        self._new_games_count = new_count
        self.update_sync_button_text()
        self.refresh_steam_status()

    def _apply_card_ambient_tint(self, card: QWidget, image_path: Optional[str]):
        """
        Applies a perfectly uniform, banding-free ambient tint to the card surface and border,
        matching the dominant accent color of the game cover.
        Completely eliminates color banding ('лесенка в бок') by avoiding horizontal gradient ramps.
        """
        rgb = get_cover_accent_color(image_path) if image_path else None
        if rgb:
            r, g, b = rgb
            # Very subtle uniform blend into the dark Fluent background (3-4% tint)
            bg_r = min(255, int(28 + r * 0.035))
            bg_g = min(255, int(28 + g * 0.035))
            bg_b = min(255, int(32 + b * 0.035))
            border_r = min(255, int(r * 0.7 + 50))
            border_g = min(255, int(g * 0.7 + 50))
            border_b = min(255, int(b * 0.7 + 50))
            card.setStyleSheet(f"""
                SimpleCardWidget {{
                    background-color: rgba({bg_r}, {bg_g}, {bg_b}, 0.78);
                    border: 1px solid rgba({border_r}, {border_g}, {border_b}, 0.20);
                    border-radius: 8px;
                }}
                SimpleCardWidget:hover {{
                    background-color: rgba({min(255, bg_r + 8)}, {min(255, bg_g + 8)}, {min(255, bg_b + 10)}, 0.88);
                    border: 1px solid rgba({border_r}, {border_g}, {border_b}, 0.38);
                }}
            """)
        else:
            card.setStyleSheet("""
                SimpleCardWidget {
                    background-color: rgba(30, 30, 35, 0.78);
                    border: 1px solid rgba(255, 255, 255, 0.08);
                    border-radius: 8px;
                }
                SimpleCardWidget:hover {
                    background-color: rgba(38, 38, 45, 0.88);
                    border: 1px solid rgba(255, 255, 255, 0.16);
                }
            """)

    def _sync_cover_to_steam_grid(self, game_info: dict, cover_path: str, steam_path: str, user_id: Optional[str] = None):
        """Immediately writes selected poster to Steam's userdata grid directory for registered shortcuts."""
        try:
            if not user_id:
                user_id = steam_syncer.get_active_steam_user(steam_path)
            if not user_id or not steam_syncer.is_safe_steam_user_id(str(user_id)):
                return
            grid_dir = os.path.join(steam_path, "userdata", str(user_id), "config", "grid")
            os.makedirs(grid_dir, exist_ok=True)
            exe_p = game_info.get('exe_path', '')
            c_name = game_info.get('clean_name', '')
            grid_id, _, grid_id_64 = steam_syncer.calculate_steam_ids(exe_p, c_name)
            p_dest = os.path.join(grid_dir, f"{grid_id}p.png")
            if not steam_syncer.is_safe_grid_path(p_dest, grid_dir):
                return
            with open(cover_path, 'rb') as f:
                c_bytes = f.read()
            steam_syncer.convert_and_save_image(c_bytes, p_dest, is_logo=False)
            if grid_id_64:
                p_dest_64 = os.path.join(grid_dir, f"{grid_id_64}p.png")
                if steam_syncer.is_safe_grid_path(p_dest_64, grid_dir):
                    steam_syncer.copy_or_link_64bit(p_dest, p_dest_64)
            logger.info(f"Synchronized cover to Steam grid: {p_dest}")
        except Exception as e:
            logger.warning(f"Failed to sync cover to Steam grid: {e}")

    def add_game_card(self, game_info: dict):
        exe_p = game_info.get('exe_path', '')
        norm_exe = os.path.normcase(os.path.normpath(exe_p)) if exe_p else ''
        if norm_exe and norm_exe in self._displayed_cards:
            return
        if norm_exe:
            self._displayed_cards.add(norm_exe)

        card = SimpleCardWidget(self.games_container)
        c_layout = QHBoxLayout(card)
        c_layout.setContentsMargins(14, 10, 14, 10)
        c_layout.setSpacing(14)

        # 0. Smart Checkbox: visible only for new unregistered games
        chk_select = CheckBox(card)
        is_reg = game_info.get('is_registered', False)
        if is_reg:
            chk_select.setChecked(False)
            chk_select.hide()
            game_info['selected'] = False
        else:
            chk_select.show()
            chk_select.setChecked(game_info.get('selected', True))
            game_info['selected'] = chk_select.isChecked()

        def _on_chk_toggled(checked):
            game_info['selected'] = checked
            self.update_sync_button_text()
        chk_select.toggled.connect(_on_chk_toggled)

        # 1. Poster Thumbnail: Apple / Steam Vertical Poster (80x120 px, 2:3 ratio) with 3D Tilt
        icon_lbl = TiltPosterLabel(card)
        icon_lbl.setFixedSize(80, 120)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setToolTip(tr("tip_click_change_poster"))

        def _on_poster_clicked():
            game_title = game_info.get('clean_name', '')
            game_folder = game_info.get('folder_path', '')
            steam_p = self.txt_steam_path.text().strip() or steam_syncer.get_steam_path()
            sgdb_k = self.txt_steamgriddb_key.text().strip() if hasattr(self, 'txt_steamgriddb_key') else None

            dlg = CoverSelectorDialog(
                clean_name=game_title,
                game_folder=game_folder,
                steam_path=steam_p,
                sgdb_key=sgdb_k,
                parent=self
            )
            if dlg.exec():
                chosen_path = dlg.get_selected_cover_path()
                if chosen_path and os.path.isfile(chosen_path):
                    game_info['custom_cover_path'] = chosen_path
                    game_info['cover_path'] = chosen_path
                    pix = QPixmap(chosen_path)
                    if not pix.isNull():
                        scaled = make_cropped_thumb(pix, 160, 240)
                        icon_lbl.setPixmap(scaled)
                        self._pixmap_cache[chosen_path] = scaled

                    self._apply_card_ambient_tint(card, chosen_path)

                    if is_reg and steam_p:
                        user_id = self.cmb_steam_users.currentData() if hasattr(self, 'cmb_steam_users') else None
                        self._sync_cover_to_steam_grid(game_info, chosen_path, steam_p, user_id)

                    self.show_toast(
                        "success",
                        title=tr("toast_poster_updated", name=game_title),
                        content=os.path.basename(chosen_path),
                        duration=3000
                    )
                else:
                    self.show_toast(
                        "warning",
                        title=tr("toast_cover_error_title"),
                        content=tr("toast_cover_error_msg"),
                        duration=3500
                    )

        icon_lbl.clicked.connect(_on_poster_clicked)

        cover_path = game_info.get('custom_cover_path') or game_info.get('cover_path')
        if cover_path and os.path.isfile(cover_path):
            if cover_path in self._pixmap_cache:
                scaled = self._pixmap_cache[cover_path]
            else:
                pix = QPixmap(cover_path)
                if not pix.isNull():
                    scaled = make_cropped_thumb(pix, 160, 240)
                    if len(self._pixmap_cache) >= 100:
                        try:
                            oldest_key = next(iter(self._pixmap_cache))
                            del self._pixmap_cache[oldest_key]
                        except Exception:
                            self._pixmap_cache.clear()
                    self._pixmap_cache[cover_path] = scaled
                else:
                    scaled = None
            if scaled:
                icon_lbl.setPixmap(scaled)
            else:
                icon_lbl.setText("🎮")
        else:
            icon_lbl.setText("🎮")

        # Apply subtle ambient gradient based on cover artwork
        self._apply_card_ambient_tint(card, cover_path)

        # 2. Details Column (Center: Title on top, Path and size on bottom)
        info_col = QVBoxLayout()
        info_col.setSpacing(4)
        info_col.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        title = StrongBodyLabel(game_info['clean_name'], card)
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        info_col.addWidget(title)

        exe_p = game_info.get('exe_path', '')
        folder_p = game_info.get('folder_path', '') or os.path.dirname(exe_p)
        exe_file = game_info.get('exe_name') or os.path.basename(exe_p)
        size_bytes = game_info.get('exe_size', 0)
        size_str = format_file_size(size_bytes) if size_bytes else ""
        subtitle_text = f"{folder_p} • {exe_file}" + (f" • {size_str}" if size_str else "")
        path_label = CaptionLabel(subtitle_text, card)
        path_label.setWordWrap(True)
        path_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        path_label.setStyleSheet("font-size: 11px; color: rgba(255, 255, 255, 0.65);")
        path_label.setToolTip(tr("tip_game_details", exe=exe_p, folder=folder_p, size=format_file_size(size_bytes) if size_bytes else 'N/A'))
        info_col.addWidget(path_label)

        # 3. Actions & Status Column (Right: Badge + Folder ToolButton)
        meta_col = QHBoxLayout()
        meta_col.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        meta_col.setSpacing(10)

        status_tag = CaptionLabel(tr("badge_in_library") if is_reg else tr("badge_ready_to_sync"), card)
        status_tag.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        if is_reg:
            status_tag.setStyleSheet(
                "color: #81c784; background: rgba(46, 125, 50, 0.25); "
                "border: 1px solid rgba(76, 175, 80, 0.40); "
                "padding: 4px 12px; border-radius: 12px; font-weight: 600; font-size: 11px;"
            )
        else:
            status_tag.setStyleSheet(
                "color: #90caf9; background: rgba(21, 101, 192, 0.20); "
                "border: 1px solid rgba(33, 150, 243, 0.35); "
                "padding: 4px 12px; border-radius: 12px; font-weight: 600; font-size: 11px;"
            )
        meta_col.addWidget(status_tag)

        btn_open = TransparentToolButton(FIF.FOLDER, card)
        btn_open.setFixedSize(32, 32)
        btn_open.setToolTip(tr("tip_open_folder", folder=folder_p))
        btn_open.setStyleSheet("""
            TransparentToolButton {
                border-radius: 6px;
                background-color: transparent;
                border: 1px solid transparent;
            }
            TransparentToolButton:hover {
                background-color: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.12);
            }
        """)

        def _safe_open(p=folder_p):
            try:
                if p and os.path.isdir(p):
                    norm = os.path.normpath(os.path.abspath(p))
                    if sys.platform == "win32" and hasattr(os, "startfile"):
                        try:
                            os.startfile(norm)
                            return
                        except Exception:
                            pass
                    if sys.platform == "win32":
                        subprocess.Popen(['explorer.exe', norm], shell=False)
                    elif sys.platform == "darwin":
                        subprocess.Popen(['open', norm])
                    else:
                        subprocess.Popen(['xdg-open', norm])
            except Exception as e:
                logger.warning(f"Cannot open directory {p}: {e}")

        btn_open.clicked.connect(lambda: _safe_open())
        meta_col.addWidget(btn_open)

        c_layout.addWidget(chk_select)
        c_layout.addWidget(icon_lbl)
        c_layout.addLayout(info_col, 1)
        c_layout.addLayout(meta_col)

        # Inset Grouped 1-column layout
        self.games_layout.addWidget(card, self._game_card_count, 0)
        self._game_card_count += 1

    def clear_pixmap_cache(self):
        """Evicts cached thumbnail pixmaps to free GDI handles and heap memory."""
        self._pixmap_cache.clear()

    def clear_game_cards(self):
        self._game_card_count = 0
        self._scanned_games_count = 0
        self._new_games_count = -1
        self._current_games = []
        if hasattr(self, '_displayed_cards'):
            self._displayed_cards.clear()
        self.clear_pixmap_cache()
        self.update_sync_button_text()
        for i in reversed(range(self.games_layout.count())):
            item = self.games_layout.itemAt(i)
            if item and item.widget():
                w = self.games_layout.takeAt(i).widget()
                if w:
                    w.deleteLater()

    # --------------------------------------------------------------------------
    # Sync Execution
    # --------------------------------------------------------------------------
    def start_sync(self):
        if self.worker and self.worker.isRunning():
            return
        if self.scan_worker and self.scan_worker.isRunning():
            try:
                self.scan_worker.scan_finished.disconnect()
            except Exception:
                pass
            try:
                self.scan_worker.requestInterruption()
                self.scan_worker.wait(300)
            except Exception:
                pass
        self.refresh_steam_status()
        auto_lifecycle = False
        if hasattr(self, 'sw_auto_steam_lifecycle'):
            auto_lifecycle = self.sw_auto_steam_lifecycle.isChecked()
        else:
            auto_lifecycle = bool(self.config.get('auto_steam_lifecycle', False))

        if not auto_lifecycle and steam_syncer.is_steam_running():
            self.show_toast(
                "error",
                title=tr("info_steam_running_title"),
                content=tr("info_steam_running_msg"),
                duration=4000
            )
            return

        self.btn_sync.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.btn_launch_steam.setVisible(False)
        self.clear_game_cards()
        if hasattr(self, 'steam_dot') and self.steam_dot:
            self.steam_dot.set_pulsing(True)

        steam_path = self.txt_steam_path.text().strip() or None
        user_id = self.cmb_steam_users.currentData() or None
        download_art = self.sw_download_art.isChecked()
        backup_bak = self.sw_backup.isChecked()
        sgdb_key = self.txt_steamgriddb_key.text().strip() if hasattr(self, 'txt_steamgriddb_key') else self.config.get('steamgriddb_key', '')
        selected_games = getattr(self, '_current_games', None)

        self.worker = SyncWorker(
            game_folders=self.game_folders,
            steam_path=steam_path,
            user_id=user_id,
            download_artwork=download_art,
            backup_shortcuts=backup_bak,
            steamgriddb_key=sgdb_key,
            auto_steam_lifecycle=auto_lifecycle,
            selected_games=selected_games
        )
        self.worker.progress_changed.connect(self.on_progress)
        self.worker.log_message.connect(self.append_log)
        self.worker.game_discovered.connect(self.add_game_card)
        self.worker.sync_finished.connect(self.on_sync_finished)
        self.worker.start()

    def on_progress(self, current: int, total: int, status_text: str):
        pct = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.steam_desc.setText(f"[{pct}%] {status_text}")

    def on_sync_finished(self, report: dict):
        if hasattr(self, 'steam_dot') and self.steam_dot:
            self.steam_dot.set_pulsing(False)
        self.btn_sync.setEnabled(True)
        self.progress_bar.setVisible(False)

        count = len(report.get('games_found', []))
        self._scanned_games_count = count
        self.update_sync_button_text()

        if getattr(self, 'lbl_metric_status', None):
            if report['success']:
                self.lbl_metric_status.setText(tr("metric_status_done"))
            else:
                self.lbl_metric_status.setText(tr("metric_status_error"))
            if getattr(self, 'lbl_metric_games', None):
                self.lbl_metric_games.setText(tr("metric_games", count=report.get('games_added', 0)))
            if getattr(self, 'lbl_metric_art', None):
                self.lbl_metric_art.setText(tr("metric_art", count=report.get('art_downloaded', 0)))

        if report['success']:
            added = report.get('games_added', 0)
            downloaded = report.get('art_downloaded', 0)
            if added == 0 and downloaded == 0:
                self.show_toast(
                    "info",
                    title=tr("info_sync_up_to_date_title"),
                    content=tr("info_sync_up_to_date_msg"),
                    duration=5000
                )
            else:
                self.show_toast(
                    "success",
                    title=tr("info_sync_success_title"),
                    content=report['message'],
                    duration=5000
                )
            self.refresh_steam_status()
            if hasattr(self, 'btn_launch_steam') and not steam_syncer.is_steam_running():
                self.btn_launch_steam.setVisible(True)
            self.preview_scanned_games()
        else:
            self.show_toast(
                "error",
                title=tr("info_sync_error_title"),
                content=report['message'],
                duration=6000
            )
            self.refresh_steam_status()

    def launch_steam(self):
        self._last_report = None
        if hasattr(self, 'btn_launch_steam'):
            self.btn_launch_steam.setVisible(False)
        steam_path = self.txt_steam_path.text().strip() or steam_syncer.get_steam_path()
        if steam_path:
            exe = os.path.normpath(os.path.abspath(os.path.join(steam_path, "steam.exe")))
            if os.path.isfile(exe):
                try:
                    subprocess.Popen([exe], shell=False)
                    self.show_toast(
                        "info",
                        title=tr("info_launch_steam_title"),
                        content=tr("info_launch_steam_msg"),
                        duration=3000
                    )
                except Exception as e:
                    logger.error(f"Failed to launch steam: {e}")

    def open_steam_website(self):
        """Opens official Steam website download page in default browser."""
        from PyQt6.QtGui import QDesktopServices
        from PyQt6.QtCore import QUrl
        QDesktopServices.openUrl(QUrl("https://store.steampowered.com/about/"))


# ==============================================================================
# GUI Entry Point
# ==============================================================================

def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            pass
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"DeckBridgeSoftware.DeckBridge.{APP_VERSION}")
        except Exception:
            pass

    configure_high_dpi()
    app = get_or_create_qapp()
    app.setApplicationName("DeckBridge")
    app.setApplicationDisplayName("DeckBridge")
    app.setOrganizationName("DeckBridge")
    if sys.platform != "win32":
        try:
            app.setDesktopFileName("deckbridge.desktop")
        except Exception:
            pass
    base_dir = BASE_DIR
    icon_names = ("DeckBridge.ico", "deckbridge.png", "app_icon.ico", "DeckBridge_logo.png") if sys.platform == 'win32' else ("deckbridge.png", "DeckBridge.ico", "app_icon.ico", "DeckBridge_logo.png")
    for ic in icon_names:
        ip = os.path.join(base_dir, ic)
        if os.path.isfile(ip):
            app.setWindowIcon(QIcon(ip))
            break

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
