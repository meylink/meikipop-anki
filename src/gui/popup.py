# src/gui/popup.py
import logging
import threading
import time
import datetime
import hashlib
import io
import base64
from PIL import Image
from typing import List, Optional

from PyQt6.QtCore import QTimer, QPoint, QPointF, QSize, Qt, pyqtSignal, QRect
from PyQt6.QtGui import QColor, QCursor, QFont, QFontMetrics, QFontInfo, QPainter, QRegion, QMouseEvent
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QFrame, QApplication, QScrollArea, QProgressBar

import re


from src.config.config import config, MAX_DICT_ENTRIES, IS_KDE, IS_MACOS, IS_WAYLAND
from src.dictionary.lookup import DictionaryEntry
from src.dictionary.yomitan_client import YomitanClient
from src.gui.magpie_manager import magpie_manager
from src.gui.region_selector import RegionSelector
from src.utils.pitch_renderer import render_pitch_html
from src.utils.window_info import get_active_window_title

# macOS-specific imports for focus management
if IS_MACOS:
    try:
        import Quartz
    except ImportError:
        Quartz = None

logger = logging.getLogger(__name__)


def _popup_window_flags() -> Qt.WindowType:
    flags = (
        Qt.WindowType.Tool |
        Qt.WindowType.FramelessWindowHint |
        Qt.WindowType.WindowStaysOnTopHint
    )

    if IS_WAYLAND and IS_KDE:
        x11_bypass = getattr(Qt.WindowType, "X11BypassWindowManagerHint", None)
        if x11_bypass is not None:
            flags |= x11_bypass

    return flags


def _guard_window_flags() -> Qt.WindowType:
    flags = (
        Qt.WindowType.Tool |
        Qt.WindowType.FramelessWindowHint |
        Qt.WindowType.WindowStaysOnTopHint
    )

    if IS_WAYLAND and IS_KDE:
        x11_bypass = getattr(Qt.WindowType, "X11BypassWindowManagerHint", None)
        if x11_bypass is not None:
            flags |= x11_bypass

    return flags


YOMITAN_RAW_FALLBACK_CSS = """
.yomitan-glossary span.tag,
.yomitan-glossary span[data-sc-class=\"tag\"] {
    border-radius: 0.3em;
    font-size: 0.8em;
    font-weight: bold;
    margin-right: 0.5em;
    padding: 0.2em 0.3em;
    vertical-align: text-bottom;
    word-break: keep-all;
    background-color: rgb(86, 86, 86);
    color: white;
}

.yomitan-glossary span.tag + span.tag,
.yomitan-glossary span[data-sc-class=\"tag\"] + span[data-sc-class=\"tag\"] {
    background-color: brown;
}

.yomitan-glossary span[data-sc-content=\"forms-label\"],
.yomitan-glossary span.tag[title*="spelling and reading variants"] {
    background-color: rgb(86, 86, 86);
    color: white;
}

.yomitan-glossary ul {
    list-style-type: disc;
}

.yomitan-glossary div.extra-box,
.yomitan-glossary div[data-sc-class=\"extra-box\"] {
    border-radius: 0.4rem;
    border-style: none none none solid;
    border-width: 0.22rem;
    margin-bottom: 0.5rem;
    margin-top: 0.5rem;
    padding: 0.5rem;
    width: fit-content;
    border-color: var(--text-color, var(--fg, #333));
    background-color: color-mix(in srgb, var(--text-color, var(--fg, #333)) 5%, transparent);
}

.yomitan-glossary div.extra-box:has(span[lang=\"en\"]),
.yomitan-glossary div[data-sc-content=\"xref\"] {
    border-color: rgb(26, 115, 232);
    background-color: color-mix(in srgb, rgb(26, 115, 232) 5%, transparent);
}

.yomitan-glossary div:has(> span[lang=\"ja\"]) {
    font-size: 1.15em;
}

.yomitan-glossary div:has(> span[lang=\"en\"]) {
    font-size: 0.88em;
}

.yomitan-glossary span[lang=\"en\"] {
    opacity: 0.95;
}

.yomitan-glossary span:has(> ruby) {
    ruby-position: over;
}

.yomitan-glossary div[data-sc-content=\"attribution\"],
.yomitan-glossary > ol > li > div:last-child {
    font-size: 0.7em;
    text-align: right;
}

.yomitan-glossary div[data-sc-content=\"forms\"],
.yomitan-glossary li[data-sc-content=\"forms\"],
.yomitan-glossary div:has(> span.tag[title*="spelling and reading variants"]) {
    margin-top: 0.5em;
}

.yomitan-glossary table {
    margin-top: 0.2em;
    table-layout: auto;
    border-collapse: collapse;
}

.yomitan-glossary tr {
    border-width: 1px;
}

.yomitan-glossary th,
.yomitan-glossary td {
    border-style: solid;
    border-width: 1px;
    border-color: currentColor;
    padding: 0.25em;
    vertical-align: top;
}

.yomitan-glossary th {
    font-weight: normal;
    text-align: center;
}

.yomitan-glossary td {
    text-align: center;
}

.yomitan-glossary td > span {
    clip-path: circle();
    display: block;
    font-weight: bold;
    padding: 0 0.5em;
}

.yomitan-glossary td.form-pri > span,
.yomitan-glossary td[data-sc-class=\"form-pri\"] > span {
    color: white;
    background: radial-gradient(green 50%, white 100%);
}

.yomitan-glossary td.form-pri > span::before,
.yomitan-glossary td[data-sc-class=\"form-pri\"] > span::before {
    content: "△";
}

.yomitan-glossary td.form-irr > span,
.yomitan-glossary td[data-sc-class=\"form-irr\"] > span {
    color: white;
    background: radial-gradient(crimson 50%, white 100%);
}

.yomitan-glossary td.form-irr > span::before,
.yomitan-glossary td[data-sc-class=\"form-irr\"] > span::before {
    content: "✕";
}

.yomitan-glossary td.form-out > span,
.yomitan-glossary td[data-sc-class=\"form-out\"] > span {
    color: white;
    background: radial-gradient(blue 50%, white 100%);
}

.yomitan-glossary td.form-out > span::before,
.yomitan-glossary td[data-sc-class=\"form-out\"] > span::before {
    content: "古";
}

.yomitan-glossary td.form-old > span,
.yomitan-glossary td[data-sc-class=\"form-old\"] > span {
    color: white;
    background: radial-gradient(blue 50%, white 100%);
}

.yomitan-glossary td.form-old > span::before,
.yomitan-glossary td[data-sc-class=\"form-old\"] > span::before {
    content: "旧";
}

.yomitan-glossary td.form-rare > span,
.yomitan-glossary td[data-sc-class=\"form-rare\"] > span {
    color: white;
    background: radial-gradient(purple 50%, white 100%);
}

.yomitan-glossary td.form-rare > span::before,
.yomitan-glossary td[data-sc-class=\"form-rare\"] > span::before {
    content: "▽";
}

.yomitan-glossary td.form-valid > span,
.yomitan-glossary td[data-sc-class=\"form-valid\"] > span {
    color: var(--background-color, var(--canvas, #f8f9fa));
    background: radial-gradient(var(--text-color, var(--fg, #333)) 50%, white 100%);
}

.yomitan-glossary td.form-valid > span::before,
.yomitan-glossary td[data-sc-class=\"form-valid\"] > span::before {
    content: "◇";
}
"""


def group_frequency_tags(frequency_tags):
    """Groups frequency tags by dictionary name for popup display.
    Input: {"JPDB: 123", "JPDB: 456", "VN: 789"}
    Output: "JPDB: 123, 456, VN: 789"
    Values are sorted in ascending order (lowest/most frequent first).
    """
    if not frequency_tags:
        return ""
    freq_map = {}
    for ft in frequency_tags:
        if ":" in ft:
            parts = ft.split(":", 1)
            d_name = parts[0].strip()
            val = parts[1].strip()
            if d_name not in freq_map:
                freq_map[d_name] = []
            freq_map[d_name].append(val)
        else:
            freq_map[ft] = []
    
    result_parts = []
    for d_name, vals in sorted(freq_map.items()):
        if vals:
            # Sort values numerically (ascending order - lowest first)
            import re
            def extract_num(v):
                nums = re.findall(r'\d+', v)
                return int(nums[0]) if nums else float('inf')
            sorted_vals = sorted(vals, key=extract_num)
            result_parts.append(f"{d_name}: {', '.join(sorted_vals)}")
        else:
            result_parts.append(d_name)
    return ", ".join(result_parts)


class ScrollGuard(QWidget):
    """
    Transparent full-screen widget that sits behind the popup to capture
    mouse events (scrolls and clicks) preventing them from reaching the
    background application.
    """
    def __init__(self, popup):
        # Explicitly no parent to ensure top-level window
        super().__init__(None)
        self.popup = popup
        self.setWindowFlags(_guard_window_flags())
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        # Use simple Window-level opacity. 1% is visible enough to OS to catch clicks
        # but invisible enough to user.
        self.setWindowOpacity(0.01)
        self.setStyleSheet("background: black;")
    
    def showEvent(self, event):
        super().showEvent(event)

    def wheelEvent(self, event):
        # Forward scroll to popup
        delta = event.angleDelta().y()
        self.popup.manual_scroll(delta)
        event.accept()

    def mousePressEvent(self, event):
        # Guard only covers area outside popup via mask, so any click here is outside.
        event.accept()
        self.popup.hide()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep loading bar at top, full width
        if hasattr(self.popup, 'loading_bar'):
             self.popup.loading_bar.setGeometry(0, 0, self.popup.width(), 2)



class SimpleLoadingBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(2)
        # Position is 0.0 to 1.0 (float)
        self.position = 0.0
        self.chunk_width = 0.2  # 20% of width
        self.max_loops = 1
        self.current_loop = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._animate)
        self.timer.setInterval(10) # 10ms for smooth/fast animation

    def set_loops(self, count):
        self.max_loops = count

    def _animate(self):
        # Move right
        self.position += 0.015 # Speed control
        if self.position > 1.0 + self.chunk_width:
             self.current_loop += 1
             if self.current_loop >= self.max_loops:
                 self.timer.stop()
                 return
             self.position = -self.chunk_width
        self.update()

    def show(self):
        super().show()
        self.position = 0.0
        self.current_loop = 0
        self.timer.start()
        
    def hide(self):
        super().hide()
        self.timer.stop()
        self.position = 0.0
        self.current_loop = 0

    def paintEvent(self, event):
        painter = QPainter(self)
        
        # Determine color from config (mimic scrollbar/theme)
        try:
             fg_col = QColor(config.color_foreground)
             # Use higher opacity (200/255) for visibility
             c = QColor(fg_col.red(), fg_col.green(), fg_col.blue(), 200)
        except:
             c = QColor("#f0c674") # Fallback
             
        painter.fillRect(self.rect(), Qt.BrushStyle.NoBrush) # Transparent BG
        
        w = self.width()
        h = self.height()
        
        chunk_w_px = w * self.chunk_width
        # Interpolate position
        x = (w + chunk_w_px) * self.position - chunk_w_px
        
        # Draw chunk
        # Use QRect instead of QRectF for crisp edges on 2px height
        painter.fillRect(int(x), 0, int(chunk_w_px), h, c)


class Popup(QWidget):
    # Signal for cross-thread Anki presence updates
    anki_presence_updated = pyqtSignal(str, bool)  # (dedup_key, is_present)
    copy_requested = pyqtSignal(str)
    
    def __init__(self, shared_state, input_loop, screen_manager=None):
        super().__init__()
        
        # Connect the signal for thread-safe UI updates
        self.anki_presence_updated.connect(self._on_anki_presence_updated)
        self.copy_requested.connect(self._copy_text_to_clipboard)
        
        # Guard window for scroll isolation
        self.guard = ScrollGuard(self)

        
        self._latest_data = None
        self._latest_context = None
        self._last_latest_data = None
        self._last_latest_context = None
        self._data_lock = threading.Lock()
        self._previous_active_window_on_mac = None
        
        self.anki_shortcut_was_pressed = False
        self.copy_shortcut_was_pressed = False
        self._wayland_keepalive_until = 0.0
        self._wayland_keepalive_seconds = 1.2
        self._wayland_cached_data = None
        self._wayland_cached_context = None
        self._wayland_hovered_popup_once = False
        self._screen_lock_held = False
        self._selected_entry_index = 0
        self._entry_cycle_wheel_direction = 0
        self._entry_cycle_wheel_accumulator = 0
        self._entry_cycle_threshold = 3
        self._entry_cycle_cooldown_until = 0.0
        self._entry_cycle_cooldown_seconds = 0.18
        self._kde_expose_retry_pending = False
        self._kde_expose_retry_count = 0
        self._input_grab_active = False
        self._suppress_popup_for_anki_screenshot = False
        self._suppress_popup_until = 0.0
        self.last_manual_crop_rect = None  # remember last user crop so Alt+A can reuse it
        self._anki_presence_status = None  # None=unknown, True=in Anki, False=not in Anki

        self.shared_state = shared_state
        self.input_loop = input_loop
        self.screen_manager = screen_manager

        self.is_visible = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_latest_data_loop)
        self.timer.start(10)
        
        # Caching for Anki presence
        self._presence_cache = {}  # {word: bool}
        self._anki_client = None   # Lazy loaded

        self.probe_label = QLabel()
        self.probe_label.setWordWrap(True)
        self.probe_label.setTextFormat(Qt.TextFormat.RichText)
        self.probe_label.setStyleSheet(f"font-family: \"{config.font_family}\";")

        self.is_calibrated = False
        self.header_chars_per_line = 50
        self.def_chars_per_line = 50

        self.setWindowFlags(_popup_window_flags())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        if IS_WAYLAND and IS_KDE:
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet("background: transparent;")

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.frame = QFrame()
        self.frame.setObjectName("PopupFrame")
        self._apply_frame_stylesheet()
        main_layout.addWidget(self.frame)

        self.content_layout = QVBoxLayout(self.frame)
        self.content_layout.setContentsMargins(10, 6, 10, 10)

        # Loading Bar (Top of card - Overlay)
        # Parent to self (Popup) not frame, so it sits on top of everything
        # Do NOT add to layout.
        self.loading_bar = SimpleLoadingBar(self)
        self.loading_bar.hide()
        # Geometry is set in resizeEvent method (see below)
        self.loading_bar.hide()
        # Geometry is set in resizeEvent method (see below)



        # Scroll Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        # Only show scrollbar when needed, don't reserve space when hidden
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._apply_scrollbar_theme()
        
        # Scroll area contents
        self.scroll_content_widget = QWidget()
        self.scroll_content_layout = QVBoxLayout(self.scroll_content_widget)
        self.scroll_content_layout.setContentsMargins(0, 0, 0, 0) # Tight layout inside scroll
        self.scroll_area.setWidget(self.scroll_content_widget)

        self.display_label = QLabel()
        self.display_label.setWordWrap(True)
        self.display_label.setTextFormat(Qt.TextFormat.RichText)
        self.display_label.linkActivated.connect(self.handle_link_click)
        self.scroll_content_layout.addWidget(self.display_label)
        
        # Add scroll area to main content layout instead of label directly
        self.content_layout.addWidget(self.scroll_area)

        # Footer Label (Sticky Hotkeys)
        self.footer_label = QLabel()
        self.footer_label.setWordWrap(True)
        self.footer_label.setTextFormat(Qt.TextFormat.RichText)
        self.footer_label.linkActivated.connect(self.handle_link_click)
        self.footer_label.setStyleSheet(f"font-family: \"{config.font_family}\"; margin-top: 5px;")
        
        footer_parts = []
        if config.show_keyboard_shortcuts:
            footer_parts.append(
                f'<a href="anki" style="color: cyan; text-decoration: none;">[Add to Anki - {config.shortcut_add_to_anki}]</a>'
            )
            footer_parts.append(
                f'<a href="copy" style="color: cyan; text-decoration: none;">[Copy Text - {config.shortcut_copy_text}]</a>'
            )

        if IS_WAYLAND:
            if not config.show_keyboard_shortcuts:
                footer_parts.append(
                    '<a href="anki" style="color: cyan; text-decoration: none;">[Add to Anki]</a>'
                )
            footer_parts.append(
                '<a href="entry_prev" style="color: cyan; text-decoration: none;">[Prev Entry]</a>'
            )
            footer_parts.append(
                '<a href="entry_next" style="color: cyan; text-decoration: none;">[Next Entry]</a>'
            )
            footer_parts.append(
                '<span style="color: #8aa2b8;">[Keys: ←/→, A, C, Esc]</span>'
            )

        if footer_parts:
            self.footer_label.setText('<div style="text-align: center;">' + ' &nbsp; '.join(footer_parts) + '</div>')
            self.footer_label.show()
        else:
            self.footer_label.hide()
        self.content_layout.addWidget(self.footer_label)


        self.status_label = QLabel()
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setStyleSheet("color: #f0c674; font-size: 12px;")
        self.status_label.hide()
        self.content_layout.addWidget(self.status_label)

        self.presence_label = QLabel()
        self.presence_label.setWordWrap(True)
        self.presence_label.setTextFormat(Qt.TextFormat.PlainText)
        self.presence_label.setStyleSheet("color: #8aa2b8; font-size: 12px;")
        self.presence_label.hide()
        self.content_layout.addWidget(self.presence_label)
        
        # Anki status icon (circle with + in top-right corner)
        self.anki_status_icon = QLabel(self.frame)
        self.anki_status_icon.setTextFormat(Qt.TextFormat.RichText)
        self.anki_status_icon.setStyleSheet("background: transparent;")
        self.anki_status_icon.setFixedSize(20, 20)
        self._update_anki_status_icon(None)  # Initialize hidden
        self.anki_status_icon.hide()
        
    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Keep loading bar at top, full width
        if hasattr(self, 'loading_bar'):
             self.loading_bar.setGeometry(0, 0, self.width(), 2)
        self._sync_guard_mask()

    def moveEvent(self, event):
        super().moveEvent(event)
        self._sync_guard_mask()

    def _sync_guard_mask(self):
        if IS_WAYLAND and IS_KDE:
            return
        if not config.prevent_background_scroll or not self.guard.isVisible():
            return

        guard_geo = self.guard.geometry()
        popup_geo = self.geometry()
        hole = QRect(
            popup_geo.left() - guard_geo.left(),
            popup_geo.top() - guard_geo.top(),
            popup_geo.width(),
            popup_geo.height(),
        )

        region = QRegion(self.guard.rect())
        region = region.subtracted(QRegion(hole))
        self.guard.setMask(region)

    def _apply_scrollbar_theme(self):
        """Apply a scrollbar stylesheet based on the current foreground color."""
        # Calculate dynamic handle colors
        fg_col = QColor(config.color_foreground)
        
        # Normal state: 30% opacity
        rgba_normal = f"rgba({fg_col.red()}, {fg_col.green()}, {fg_col.blue()}, 0.3)"
        
        # Hover state: 50% opacity
        rgba_hover = f"rgba({fg_col.red()}, {fg_col.green()}, {fg_col.blue()}, 0.5)"
        
        self.scroll_area.setStyleSheet(f"""
            QScrollArea {{
                background: transparent;
            }}
            QScrollBar:vertical {{
                background: transparent;
                width: 8px;
                margin: 0px;
            }}
            QScrollBar::handle:vertical {{
                background: {rgba_normal};
                min-height: 20px;
                border-radius: 4px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {rgba_hover};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
                background: transparent;
            }}
        """)


        self._last_presence_key = None

        self.hide()

    def _update_anki_status_icon(self, is_present: bool = None, loading: bool = False):
        """Update the Anki status icon. Green = new word, Gray = in Anki, Semi-transparent gray = loading."""
        if is_present is None and not loading:
            self.anki_status_icon.hide()
            return
        
        # Determine color and opacity
        if loading:
            color = "#888888"
            opacity = "0.5"
        elif is_present:
            color = "#888888"  # Already in Anki
            opacity = "1"
        else:
            color = "#4CAF50"  # New word - green
            opacity = "1"
        
        html_icon = f'<span style="font-size: 18px; color: {color}; opacity: {opacity};">⊕</span>'
        self.anki_status_icon.setText(html_icon)
        
        # Position in top-right corner of the frame (aligned with header)
        frame_width = self.frame.width()
        icon_x = frame_width - 28  # 20px icon + 8px margin
        icon_y = 12
        self.anki_status_icon.move(icon_x, icon_y)
        self.anki_status_icon.show()
        self.anki_status_icon.raise_()

    def handle_link_click(self, url):
        if url == "anki":
            self._bump_wayland_keepalive()
            self.add_to_anki(manual_crop=True)
        elif url == "copy":
            self.copy_to_clipboard()
        elif url == "entry_prev":
            self._bump_wayland_keepalive()
            self._move_selected_entry(-1)
        elif url == "entry_next":
            self._bump_wayland_keepalive()
            self._move_selected_entry(1)
        elif url.startswith("select:"):
            try:
                idx = int(url.split(":", 1)[1])
                self._bump_wayland_keepalive()
                self._set_selected_entry(idx)
            except (ValueError, IndexError):
                logger.debug(f"Invalid select link: {url}")

    def _bump_wayland_keepalive(self):
        if not IS_WAYLAND:
            return

        keepalive_seconds = max(0.0, float(getattr(config, 'popup_hide_delay_seconds', 0.0)))
        self._wayland_keepalive_until = time.perf_counter() + keepalive_seconds
        self._wayland_hovered_popup_once = True

        if not self._wayland_cached_data:
            latest_data, latest_context = self.get_latest_data()
            if latest_data:
                self._wayland_cached_data = latest_data
                self._wayland_cached_context = latest_context or {}

    def _get_selected_entry(self, entries=None):
        entries = entries if entries is not None else self._latest_data
        if not entries:
            return None, 0

        clamped_idx = max(0, min(self._selected_entry_index, len(entries) - 1))
        if clamped_idx != self._selected_entry_index:
            self._selected_entry_index = clamped_idx
        return entries[clamped_idx], clamped_idx

    def _get_entries_for_interaction(self):
        latest_data, _ = self.get_latest_data()
        if latest_data:
            return latest_data

        # Wayland keepalive can render cached data while live source is empty.
        if IS_WAYLAND and self._wayland_cached_data:
            return self._wayland_cached_data

        return None

    def _set_selected_entry(self, index: int):
        latest_data = self._get_entries_for_interaction()
        if not latest_data:
            return

        new_idx = max(0, min(index, len(latest_data) - 1))
        if new_idx == self._selected_entry_index:
            return

        self._selected_entry_index = new_idx
        selected_entry = latest_data[new_idx]
        self._refresh_presence_for_entry(selected_entry)
        self._entry_cycle_wheel_direction = 0
        self._entry_cycle_wheel_accumulator = 0
        full_html, new_size = self._calculate_content_and_size_char_count(latest_data)
        if full_html:
            self.display_label.setText(full_html)
            self.setFixedSize(new_size)
            # Always start a newly selected entry from the top to avoid cut-off headers.
            self.scroll_area.verticalScrollBar().setValue(0)
            self._bump_wayland_keepalive()

    def _move_selected_entry(self, delta: int):
        latest_data = self._get_entries_for_interaction()
        if not latest_data:
            return
        self._set_selected_entry(self._selected_entry_index + delta)

    def _update_scrollbar_policy_for_entries(self, entries):
        if entries and len(entries) > 1:
            self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        else:
            self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

    def _refresh_presence_for_entry(self, entry):
        """Refresh icon status based on the currently selected entry only."""
        presence_key = (entry.written_form or entry.reading or "").strip() if entry else ""
        self._last_presence_key = presence_key

        if not presence_key:
            self._anki_presence_status = None
            return

        if presence_key in self._presence_cache:
            self._anki_presence_status = self._presence_cache[presence_key]
        else:
            self._anki_presence_status = None
            threading.Thread(target=self._check_anki_presence, args=(presence_key,), daemon=True).start()

    def wheelEvent(self, event):
        """
        Consume wheel events to prevent them from propagating to the window underneath
        (e.g., the browser). The internal QScrollArea will still handle its own events
        because it receives them before they bubble up to this parent widget.
        """
        event.accept()

    def showEvent(self, event):
        super().showEvent(event)
        virtual_geometry = QRect()
        for screen in QApplication.screens():
            virtual_geometry = virtual_geometry.united(screen.geometry())
        
        # On KDE Wayland we rely on popup-level mouse/keyboard grabs instead of guard.
        if config.prevent_background_scroll and not (IS_WAYLAND and IS_KDE):
            self.guard.setGeometry(virtual_geometry)
            self.guard.show()
            self._sync_guard_mask()
            # Ensure popup is above the guard
            self.raise_()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.guard.hide()

    def manual_scroll(self, dy):
        """
        Called by ScrollGuard when it catches a wheel event.
        dy is in degrees (usually +/- 120 per notch).
        """
        scroll_bar = self.scroll_area.verticalScrollBar()
        # In Qt wheel event, positive delta is usually "forward/away" (UP).
        # ScrollBar value: 0 is top. Increasing value moves down.
        # So UP event (positive delta) should DECREASE scroll bar value.
        scroll_bar.setValue(scroll_bar.value() - dy)

    def mousePressEvent(self, event):
        # Only use special handling while explicit fullscreen input grab is active.
        if self._input_grab_active and not self.rect().contains(event.position().toPoint()):
            self.hide_popup()
            event.accept()
            return

        if self._input_grab_active and self._forward_mouse_event_to_child(event):
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._input_grab_active and self._forward_mouse_event_to_child(event):
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        key = event.key()

        if key in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self._move_selected_entry(-1)
            event.accept()
            return

        if key in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self._move_selected_entry(1)
            event.accept()
            return

        if key == Qt.Key.Key_A:
            self.add_to_anki(manual_crop=True)
            event.accept()
            return

        if key == Qt.Key.Key_C:
            self.copy_to_clipboard()
            event.accept()
            return

        if key == Qt.Key.Key_Escape:
            self.hide_popup()
            event.accept()
            return

        super().keyPressEvent(event)

    def _forward_mouse_event_to_child(self, event) -> bool:
        if event.button() != Qt.MouseButton.LeftButton:
            return False

        local_point = event.position().toPoint()
        target = self.childAt(local_point)
        if target is None or target is self:
            return False

        child_pos = target.mapFrom(self, local_point)
        forwarded = QMouseEvent(
            event.type(),
            QPointF(child_pos),
            event.globalPosition(),
            event.button(),
            event.buttons(),
            event.modifiers(),
        )
        QApplication.postEvent(target, forwarded)
        return True
        
    def add_to_anki(self, manual_crop=True):
        logger.info(f"Add to Anki clicked (manual_crop={manual_crop})")

        latest_data, latest_context = self._get_interaction_data()
        if not latest_context:
            logger.warning("No context available for Anki")
            return
        if not latest_data:
            logger.warning("No entries available for Anki")
            return

        # Duplicate guard before any UI interaction (per-word, not per-sentence)
        entry, selected_idx = self._get_selected_entry(latest_data)
        if not entry:
            logger.warning("No selected entry available for Anki")
            return
        dedup_key = (entry.written_form or entry.reading or "").strip()
        
        # User Request: "Detect Duplicates" setting should control whether we BLOCK creation.
        # checking config.anki_show_hover_status currently controls the hover label, 
        # but user wants it to also control this blocking behavior.
        if config.anki_show_hover_status and dedup_key:
            from src.dictionary.anki_client import AnkiClient
            anki = AnkiClient(config.anki_url)
            existing_notes, _ = self._find_anki_notes_for_key(dedup_key, anki=anki)
            if existing_notes:
                self._show_status_message("Duplicate: Already in Anki")
                logger.info(f"Skipping add_to_anki for '{dedup_key}' - duplicate found")
                return

        if config.anki_enable_screenshot:
            # Avoid popup reappearing during crop/select/capture and leaking into the image.
            self._suppress_popup_for_anki_screenshot = True
            self._suppress_popup_until = time.perf_counter() + 8.0
        
        crop_rect = None
        if config.anki_enable_screenshot and manual_crop:
            self.hide_popup()
            QApplication.processEvents()
            time.sleep(0.2)
            logger.info("Launching region selector for manual crop")
            crop_rect = RegionSelector.get_region()
            logger.info(f"Region selector result: {crop_rect}")
            if not crop_rect:
                logger.info("Manual crop cancelled")
                self._suppress_popup_for_anki_screenshot = False
                self._suppress_popup_until = 0.0
                return
            self.last_manual_crop_rect = crop_rect
        elif config.anki_enable_screenshot:
            # Reuse last manual crop if user selects then presses Alt+A
            crop_rect = self.last_manual_crop_rect
        # else: screenshot disabled, crop_rect stays None
        
        # Show loading bar (indefinite)
        # If already in Anki, run once (quick). If processing (adding), run twice (longer feedback).
        loops = 1 if self._anki_presence_status else 2
        self.loading_bar.set_loops(loops)
        self.loading_bar.show()
        
        logger.info("Spawning Anki add thread")
        threading.Thread(target=self._add_to_anki_thread, args=(crop_rect, latest_context, latest_data, selected_idx)).start()

    def _show_status_message(self, message: str, duration_ms: int = 2000):
        self.status_label.setText(message)
        self.status_label.show()

        def clear_message():
            self.status_label.clear()
            self.status_label.hide()

        if duration_ms > 0:
            QTimer.singleShot(duration_ms, clear_message)

    def _set_presence_label(self, text: str = "", color: str = "#8aa2b8", visible: bool = True):
        if not visible:
            self.presence_label.clear()
            self.presence_label.hide()
            return
        self.presence_label.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.presence_label.setText(text)
        self.presence_label.show()

    def _build_anki_tags(self, document_title: str) -> str:
        """Build space-separated tag string for Anki cards."""
        import re
        tags = []
        if config.anki_add_meikipop_tag:
            tags.append("meikipop")
        if config.anki_add_document_title_tag and document_title:
            # Sanitize: Anki tags can't have spaces, replace with underscores
            sanitized = re.sub(r'\s+', '_', document_title.strip())
            # Remove other problematic characters
            sanitized = re.sub(r'[^\w\-_]', '', sanitized)
            if sanitized:
                tags.append(sanitized)
        return " ".join(tags)



    def _find_anki_notes_for_key(self, dedup_key: str, anki=None, model_fields: Optional[List[str]] = None):
        """Find notes matching this word/read with tag first, then front/reading fields (avoids sentence matches)."""
        if not dedup_key:
            return [], None

        if not anki:
            from src.dictionary.anki_client import AnkiClient
            anki = AnkiClient(config.anki_url)

        if not anki:
            from src.dictionary.anki_client import AnkiClient
            anki = AnkiClient(config.anki_url)

        queries = []

        try:
            if model_fields is None:
                model_fields = anki.get_model_field_names(config.anki_model_name) or []
        except Exception as e:
            logger.debug(f"Model field lookup failed: {e}")
            model_fields = []

        safe_term = dedup_key.replace('"', '\\"')
        
        # Use configurable field names from config.ini to find duplicates across all note types
        common_fields = config.anki_duplicate_check_fields
        
        # Also include fields from user's configured field map that map to Expression/Reading/Word
        configured_fields = []
        for field, source in config.anki_field_map.items():
            if source in ["Expression", "Reading", "Word"]:
                configured_fields.append(field)
        
        # Combine and deduplicate
        target_fields = list(set(common_fields + configured_fields))
            
        for field_name in target_fields:
            queries.append(f'"{field_name}:{safe_term}"')

        existing_notes = []
        for query in queries:
            try:
                found = anki.find_notes(query) or []
                for note_id in found:
                    if note_id not in existing_notes:
                        existing_notes.append(note_id)
            except Exception as e:
                logger.debug(f"Anki query failed for '{query}': {e}")

        return existing_notes, None

    def _check_anki_presence(self, dedup_key: str):
        """Background thread - check if word exists in Anki and emit signal."""
        try:
            # Check cache again just in case (race condition, though minor)
            if dedup_key in self._presence_cache:
                self.anki_presence_updated.emit(dedup_key, self._presence_cache[dedup_key])
                return

            if not self._anki_client:
                from src.dictionary.anki_client import AnkiClient
                self._anki_client = AnkiClient(config.anki_url)
            
            # Use the persistent client
            existing_notes, _ = self._find_anki_notes_for_key(dedup_key, anki=self._anki_client)
            is_present = bool(existing_notes)
            
            # Emit signal to update UI in main thread
            self.anki_presence_updated.emit(dedup_key, is_present)
        except Exception as e:
            logger.debug(f"Presence check failed: {e}")

    def _on_anki_presence_updated(self, dedup_key: str, is_present: bool):
        """Slot handler - runs in main thread to update UI."""
        # Always cache the result
        self._presence_cache[dedup_key] = is_present
        
        # Hide loading bar (e.g. if we were adding to Anki)
        self.loading_bar.hide()
        
        if dedup_key != self._last_presence_key:
            return  # stale, don't update UI for old word
        
        # Store the presence status and refresh content to update inline icon
        self._anki_presence_status = is_present
        
        # Force content refresh to show the updated icon
        latest_data, latest_context = self._get_interaction_data()
        if latest_data:
            full_html, new_size = self._calculate_content_and_size_char_count(latest_data)
            if full_html:
                self.display_label.setText(full_html)
                self.display_label.repaint()



    def _add_to_anki_thread(self, manual_crop_rect=None, context=None, entries=None, selected_index=0):
        from src.dictionary.anki_client import AnkiClient
        import base64
        from io import BytesIO
        
        anki = AnkiClient(config.anki_url)
        deck_name = config.anki_deck_name
        model_name = config.anki_model_name
        if not anki.ping():
            logger.error("Anki is not connected")
            QTimer.singleShot(0, lambda: self._show_status_message("Anki not connected", 3000))
            if config.anki_enable_screenshot:
                self._suppress_popup_for_anki_screenshot = False
                self._suppress_popup_until = 0.0
            QTimer.singleShot(0, self.loading_bar.hide)
            return
        logger.info("Anki add thread started")

        # Fallback to latest if not passed (should not happen)
        context = context or self._latest_context
        entries = entries or self._latest_data
        if not entries:
            logger.warning("Anki add thread: no entries")
            QTimer.singleShot(0, lambda: self._show_status_message("No entries available", 2000))
            if config.anki_enable_screenshot:
                self._suppress_popup_for_anki_screenshot = False
                self._suppress_popup_until = 0.0
            QTimer.singleShot(0, self.loading_bar.hide)
            return
        
        selected_index = max(0, min(selected_index, len(entries) - 1))
        entry = entries[selected_index]
        
        # Prepare data
        word = entry.written_form or ""
        reading = entry.reading or ""
        meanings = []
        import re
        filter_pattern = re.compile(r'^\s*(?:\d+|[①-⑳])')

        for sense in entry.senses:
            original_glosses = sense.get('glosses', [])
            filtered_glosses = [g for g in original_glosses if filter_pattern.match(g)]
            
            if filtered_glosses:
                final_glosses = filtered_glosses
                # Validated: Use <div> blocks to enforce line breaks in Anki fields
                glosses_str = ''.join(f'<div>{g.replace(chr(10), "<br>")}</div>' for g in final_glosses)
            else:
                final_glosses = original_glosses
                # Fallback: Join with <br> for non-numbered, but still respect newlines
                glosses_str = '<br>'.join(g.replace('\n', '<br>') for g in final_glosses)
            
            meanings.append(glosses_str)
        
        sentence = context.get("context_text", "") or ""
        safe_word = word or reading or sentence
        screenshot = context.get("screenshot")
        context_box = context.get("context_box")
        scan_geometry = context.get("scan_geometry") # (x, y, w, h)
        screenshot_geometry = scan_geometry
        
        logger.debug(f"Anki Context Box: {context_box}")
        logger.debug(f"Manual crop passed in: {manual_crop_rect}; last saved: {self.last_manual_crop_rect}")
        logger.debug(f"Context text: {sentence}")

        screenshot_filename = f"meikipop_{int(time.time())}.png"
        screenshot_field = ""

        effective_manual_crop_rect = manual_crop_rect or self.last_manual_crop_rect

        if config.anki_enable_screenshot and effective_manual_crop_rect and self.screen_manager is not None:
            try:
                with self.shared_state.screen_lock:
                    full_screenshot, full_monitor = self.screen_manager.take_full_screenshot()
                screenshot = full_screenshot
                screenshot_geometry = (
                    full_monitor.get("left", 0),
                    full_monitor.get("top", 0),
                    full_monitor.get("width", 0),
                    full_monitor.get("height", 0),
                )
                logger.debug(f"Using full desktop screenshot for Anki crop with geometry {screenshot_geometry}")
            except Exception as e:
                logger.warning(f"Failed to capture full desktop screenshot for Anki crop: {e}")
        
        if config.anki_enable_screenshot and screenshot:
            from PIL import Image
            # Convert mss screenshot to PIL Image
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
            
            # Crop logic
            crop_coords = None # (left, top, right, bottom) relative to image
            if manual_crop_rect is None and self.last_manual_crop_rect:
                manual_crop_rect = self.last_manual_crop_rect
            
            if manual_crop_rect and screenshot_geometry:
                # Manual crop
                # manual_crop_rect is QRect in absolute screen coords
                # screenshot_geometry is (off_x, off_y, w, h)
                
                off_x, off_y, _, _ = screenshot_geometry
                
                # Calculate relative coordinates
                rel_x = manual_crop_rect.x() - off_x
                rel_y = manual_crop_rect.y() - off_y
                rel_w = manual_crop_rect.width()
                rel_h = manual_crop_rect.height()
                
                # Ensure within bounds
                left = max(0, rel_x)
                top = max(0, rel_y)
                right = min(img.width, rel_x + rel_w)
                bottom = min(img.height, rel_y + rel_h)
                
                if right > left and bottom > top:
                    crop_coords = (left, top, right, bottom)
                    logger.debug(f"Manual Crop: {crop_coords}")
                else:
                    logger.warning("Manual crop outside of scan area")

            elif context_box:
                # Auto smart crop
                width, height = img.size
                logger.debug(f"Original Image Size: {width}x{height}")
                
                # Calculate coordinates from normalized box
                c_x = context_box.center_x * width
                c_y = context_box.center_y * height
                b_w = context_box.width * width
                b_h = context_box.height * height
                
                left = c_x - (b_w / 2)
                top = c_y - (b_h / 2)
                right = c_x + (b_w / 2)
                bottom = c_y + (b_h / 2)
                
                logger.debug(f"Calculated Crop: {left}, {top}, {right}, {bottom}")
                
                # Add padding (e.g., 50px or 10% of dimension)
                padding_x = 50
                padding_y = 50
                
                left = max(0, int(left - padding_x))
                top = max(0, int(top - padding_y))
                right = min(width, int(right + padding_x))
                bottom = min(height, int(bottom + padding_y))
                
                logger.debug(f"Padded Crop: {left}, {top}, {right}, {bottom}")
                
                if right > left and bottom > top:
                    crop_coords = (left, top, right, bottom)

            if crop_coords:
                img = img.crop(crop_coords)
                logger.debug("Image cropped successfully")
            else:
                logger.debug("No crop applied; using full screenshot")
            
            buffered = BytesIO()
            img.save(buffered, format="PNG")
            img_str = base64.b64encode(buffered.getvalue()).decode()
            try:
                anki.store_media_file(screenshot_filename, img_str)
                screenshot_field = f'<img src="{screenshot_filename}">'
            except Exception as e:
                logger.warning(f"Failed to store screenshot media '{screenshot_filename}': {e}")
                screenshot_field = ""

        # Prepare Data Sources
        # --------------------
        # Build furigana-plain format - only add furigana for kanji characters
        # Yomitan style: 姉[ねえ]さん (reading only for kanji portions)
        def build_furigana_plain(kanji_word, kana_reading):
            if not kanji_word or not kana_reading:
                return kanji_word or kana_reading or ""
            if kanji_word == kana_reading:
                return kanji_word
            
            import re
            # Pattern to match kanji characters
            kanji_pattern = re.compile(r'[\u4e00-\u9faf\u3400-\u4dbf]+')
            # Pattern to match hiragana/katakana
            kana_pattern = re.compile(r'[\u3040-\u309f\u30a0-\u30ff]+')
            
            if not kanji_pattern.search(kanji_word):
                return kanji_word  # No kanji, no furigana needed
            
            # Try to build proper furigana by matching shared kana
            # Start by finding trailing kana that match in both word and reading
            result = ""
            word_idx = 0
            reading_idx = 0
            
            while word_idx < len(kanji_word):
                char = kanji_word[word_idx]
                
                # Check if current char is kanji
                if kanji_pattern.match(char):
                    # Find the extent of consecutive kanji
                    kanji_start = word_idx
                    while word_idx < len(kanji_word) and kanji_pattern.match(kanji_word[word_idx]):
                        word_idx += 1
                    kanji_portion = kanji_word[kanji_start:word_idx]
                    
                    # Find the kana that matches this kanji section
                    # Look ahead in the word to see if there's trailing kana to match
                    if word_idx < len(kanji_word):
                        # There's more after the kanji - find where reading matches
                        remaining_word = kanji_word[word_idx:]
                        # Find the first kana char from remaining_word in reading
                        if remaining_word and remaining_word[0] in kana_reading[reading_idx:]:
                            match_pos = kana_reading.index(remaining_word[0], reading_idx)
                            kanji_reading = kana_reading[reading_idx:match_pos]
                            reading_idx = match_pos
                        else:
                            # Take remaining reading up to next match or end
                            kanji_reading = kana_reading[reading_idx:]
                            reading_idx = len(kana_reading)
                    else:
                        # Kanji at end - take remaining reading
                        kanji_reading = kana_reading[reading_idx:]
                        reading_idx = len(kana_reading)
                    
                    if kanji_reading:
                        result += f"{kanji_portion}[{kanji_reading}]"
                    else:
                        result += kanji_portion
                else:
                    # Kana character - add directly and advance reading
                    result += char
                    word_idx += 1
                    if reading_idx < len(kana_reading) and kana_reading[reading_idx] == char:
                        reading_idx += 1
            
            return result
        
        furigana_plain = build_furigana_plain(word, reading)
        
        # Clean sentence - strip non-grammatical punctuation only at START and END
        sentence_clean = sentence
        edge_punctuation = "「」『』【】〔〕《》〈〉"
        # Strip from start
        while sentence_clean and sentence_clean[0] in edge_punctuation:
            sentence_clean = sentence_clean[1:]
        # Strip from end
        while sentence_clean and sentence_clean[-1] in edge_punctuation:
            sentence_clean = sentence_clean[:-1]
        sentence_clean = sentence_clean.strip()
        
        # Heuristic: Google Lens forces half-width alphanumeric text (e.g. "SNS" instead of "ＳＮＳ").
        # Japanese text usually uses full-width for visual consistency.
        # We try to "restore" this by converting ASCII alphanumerics to Full-Width.
        def ascii_to_fullwidth(text):
            result = ""
            for char in text:
                code = ord(char)
                if 0x21 <= code <= 0x7E:
                     # ASCII -> Fullwidth (Offset 0xFEE0)
                     result += chr(code + 0xFEE0)
                elif code == 0x20:
                     # Space -> Ideographic Space
                     result += chr(0x3000)
                else:
                     result += char
            return result
            
        # Only apply if the text contains Japanese (safety check)
        # Scan for Japanese chars
        if any(ord(c) > 0x2E80 for c in sentence_clean):
             # Don't convert mostly-english sentences? 
             # For now, just convert, assuming user scans Japanese content.
             # We only convert [A-Za-z0-9] effectively.
             sentence_clean = ascii_to_fullwidth(sentence_clean)
             # Also update raw_lookup_term if it was purely from the sentence? 
             # No, keep raw_lookup_term as is for matching, OR convert it too?
             # If we convert sentence_clean to FullWidth, we MUST convert raw_lookup_term to FullWidth 
             # for .find() to work!
             
        # UPDATE: If we changed sentence_clean, we should try to match raw_lookup_term against it.
        # But raw_lookup_term comes from OCR (Half-Width).
        # We should NOT modify raw_lookup_term because it drives the dictionary lookup (which handles normalization).
        # But for Cloze Splitting, we need to find it.
        # So we will rely on our "Smart Restoration / Restoration" logic later which handles normalization.
        
        
        # Glossary: HTML-formatted definitions with data-dictionary attributes (like Yomitan)
        # Yomitan format: each sense is a <li data-dictionary="..."><i>(pos)</i> <ul><li>gloss1</li><li>gloss2</li></ul></li>
        glossary_html_parts = []
        glossary_brief = ""
        for sense in entry.senses:
            gs = sense.get('glosses', [])
            # Filter out pitch data from glossary
            clean_glosses = [g for g in gs if not g.startswith("PITCH:")]
            if not clean_glosses:
                continue
            pos_list = sense.get('pos', [])
            source = sense.get('source', '')
            
            # Build POS string - Yomitan shows (pos, source)
            pos_str = ""
            if pos_list or source:
                parts = [p for p in pos_list if p]
                
                # Sort parts: move 'hon' and other specific tags to the end
                end_tags = {'hon', 'uk', 'hum', 'pol'}
                parts.sort(key=lambda x: 1 if x in end_tags else 0)
                
                if source:
                    parts.append(source)
                pos_str = f"<i>({', '.join(parts)})</i> "
            
            # Build glosses - only use ul/li for multiple definitions
            # Build glosses - only use ul/li for multiple definitions
            if len(clean_glosses) > 1:
                # Replace newlines in each gloss item
                li_items = "".join(f"<li>{g.replace(chr(10), '<br>')}</li>" for g in clean_glosses)
                glossary_html_parts.append(f'<li data-dictionary="{source}">{pos_str}<ul>{li_items}</ul></li>')
            else:
                # Single gloss - no ul wrapper, but replace newlines
                single_gloss = clean_glosses[0].replace(chr(10), '<br>')
                glossary_html_parts.append(f'<li data-dictionary="{source}">{pos_str}{single_gloss}</li>')
            
            # First sense for brief
            if not glossary_brief:
                # Replace newlines in brief too
                glossary_brief = "; ".join(g.replace(chr(10), '<br>') for g in clean_glosses)
        
        glossary_full = ""
        glossary_first = ""
        glossary_1st_dict = ""
        glossary_raw = ""
        if glossary_html_parts:
            glossary_full = f'<div style="text-align: left;" class="yomitan-glossary"><ol>{"".join(glossary_html_parts)}</ol></div>'
            # Glossary First: Only the first sense
            glossary_first = f'<div style="text-align: left;" class="yomitan-glossary"><ol>{glossary_html_parts[0]}</ol></div>'
            
            # Glossary 1st Dict: All senses from the first dictionary
            # Find the first dictionary source from the senses
            first_dict_source = None
            for sense in entry.senses:
                gs = sense.get('glosses', [])
                clean_glosses = [g for g in gs if not g.startswith("PITCH:")]
                if clean_glosses:
                    first_dict_source = sense.get('source', '')
                    break
            
            if first_dict_source is not None:
                # Collect all senses from that dictionary
                first_dict_parts = []
                for sense in entry.senses:
                    gs = sense.get('glosses', [])
                    clean_glosses = [g for g in gs if not g.startswith("PITCH:")]
                    if not clean_glosses:
                        continue
                    source = sense.get('source', '')
                    if source != first_dict_source:
                        continue
                    
                    pos_list = sense.get('pos', [])
                    pos_str = ""
                    if pos_list or source:
                        parts = [p for p in pos_list if p]
                        end_tags = {'hon', 'uk', 'hum', 'pol'}
                        parts.sort(key=lambda x: 1 if x in end_tags else 0)
                        if source:
                            parts.append(source)
                        pos_str = f"<i>({', '.join(parts)})</i> "
                    
                    if len(clean_glosses) > 1:
                        li_items = "".join(f"<li>{g.replace(chr(10), '<br>')}</li>" for g in clean_glosses)
                        first_dict_parts.append(f'<li data-dictionary="{source}">{pos_str}<ul>{li_items}</ul></li>')
                    else:
                        single_gloss = clean_glosses[0].replace(chr(10), '<br>')
                        first_dict_parts.append(f'<li data-dictionary="{source}">{pos_str}{single_gloss}</li>')
                
                if first_dict_parts:
                    glossary_1st_dict = f'<div style="text-align: left;" class="yomitan-glossary"><ol>{"".join(first_dict_parts)}</ol></div>'

        # Raw glossary from Yomitan API structured content, without overlay reformatting.
        raw_li_items = []
        for sense in entry.senses:
            gs = sense.get('glosses', [])
            if any(g.startswith("PITCH:") for g in gs):
                continue

            raw_html = sense.get('raw_html', '')
            if raw_html:
                source = sense.get('source', '')
                source_attr = source.replace('"', '&quot;')
                pos_list = sense.get('pos', [])
                pos_parts = [p for p in pos_list if p]
                if source:
                    pos_parts.append(source)
                pos_str = f"<i>({', '.join(pos_parts)})</i> " if pos_parts else ""
                raw_li_items.append(f'<li data-dictionary="{source_attr}">{pos_str}{raw_html}</li>')

        if raw_li_items:
            glossary_raw = f'<div style="text-align: left;" class="yomitan-glossary"><ol>{"".join(raw_li_items)}</ol></div>'

            # Some Yomitan API payloads do not include per-entry style blocks.
            # Add a fallback stylesheet so cards render close to Brave/Yomitan.
            if "<style" not in glossary_raw.lower():
                glossary_raw += f"<style>{YOMITAN_RAW_FALLBACK_CSS}</style>"
        else:
            glossary_raw = glossary_full
        
        # Pitch Accent
        pitch_positions = []
        pitch_graphs_html = []
        for sense in entry.senses:
             for g in sense.get('glosses', []):
                 if g.startswith("PITCH:"):
                     try:
                         parts = g.split(":")
                         pos = parts[1].strip()
                         target_reading = parts[2] if len(parts) > 2 else reading
                         pitch_positions.append(pos)
                         # Generate graph HTML - need numeric value for renderer
                         from src.utils.pitch_renderer import render_pitch_html
                         pos_num = int(pos.replace("[", "").replace("]", ""))
                         graph_html = render_pitch_html(target_reading, pos_num, color_line=config.color_foreground)
                         pitch_graphs_html.append(graph_html)
                     except:
                         pass
        
        # Build Cloze fields
        # Find the word in the sentence to create cloze-style splits
        cloze_prefix = ""
        # Prefer the raw lookup string (what was actually on screen) over dictionary form
        raw_lookup_term = context.get("lookup_string", "")
        
        # If we have match_len from the entry, trust it to determine the "Word" length in the raw string.
        # This prevents including suffixes that HitScanner might have greedily grabbed.
        
        if getattr(entry, 'match_len', 0) and len(raw_lookup_term) >= entry.match_len:
             lookup_term = raw_lookup_term[:entry.match_len]
        else:
             lookup_term = raw_lookup_term if raw_lookup_term else (word or reading or "")
        
        # Smart Character Restoration:
        # If the OCR gave us "SNS" (half-width) but the dictionary has "ＳＮＳ" (full-width),
        # we want to use the dictionary form to closer match the "original look" of the image.
        # We use NFKC normalization to check if they are "textually equivalent" (ignoring width).
        # We do NOT want to replace "たべる" with "食べる" (Kana vs Kanji), which normalize differently.
        import unicodedata
        try:
            dict_word = entry.written_form or ""
            # Only attempt if lengths correspond roughly (prevent aggressive replacement on short substring matches?)
            # Actually normalization is robust.
            if dict_word and lookup_term:
                norm_lookup = unicodedata.normalize('NFKC', lookup_term)
                norm_dict = unicodedata.normalize('NFKC', dict_word)
                if norm_lookup == norm_dict:
                    # Smart Restoration: Swapping OCR '{lookup_term}' with Dict '{dict_word}'
                    lookup_term = dict_word
        except Exception as e:
            logger.error(f"Error in Smart Restoration: {e}")

             
        cloze_body = lookup_term
        cloze_suffix = ""

        if lookup_term and sentence_clean:
            # We need to find the "OCR" version in the sentence to split,
            # but we want to put the "Restored" version in the cloze body.
            # Relaod raw_lookup_term/sliced for finding index
            
            # Recalculate the OCR-based term for searching in 'sentence_clean' (which is from OCR)
            ocr_term = raw_lookup_term[:entry.match_len] if getattr(entry, 'match_len', 0) else raw_lookup_term
            
            # Since we converted sentence_clean to FullWidth, we must also convert ocr_term to FullWidth to find it!
            fullwidth_ocr_term = ascii_to_fullwidth(ocr_term) if ocr_term else ""
            
            idx = sentence_clean.find(ocr_term) if ocr_term else -1
            if idx == -1 and fullwidth_ocr_term:
                idx = sentence_clean.find(fullwidth_ocr_term)
                if idx != -1:
                    # We found usage of the fullwidth version, so we should consider that the "ocr_term" for length calcs
                    ocr_term = fullwidth_ocr_term

            
            if idx != -1:
                cloze_prefix = sentence_clean[:idx]
                # If we have a 'smart restored' lookup_term (from dict), use it.
                # Otherwise use the text we found in the sentence (which is now FullWidth)
                cloze_body = lookup_term 
                
                # Wait, if 'lookup_term' (Dictionary) is "SNS" (half) but 'sentence' is "ＳＮＳ" (full),
                # we technically prefer the Sentence version (Full) over the Dictionary version (Half)??
                # The user wants "original look".
                # My previous block: "Smart Restoration: Swapping OCR '{lookup_term}' with Dict '{dict_word}'"
                # If Dict is 'ＳＮＳ', lookup_term is 'ＳＮＳ'. Great.
                # If Dict is 'SNS' (e.g. Jisho sometimes?), lookup_term is 'SNS'.
                # But Sentence is 'ＳＮＳ' (forced fullwidth).
                # We should probably favor the Sentence's version if it's fullwidth?
                # Actually, forcing sentence to FullWidth is the strong heuristic we applied.
                # So we should trust the sentence's characters for the body too, UNLESS Dict has specific Kanji etc.
                
                # Let's keep using 'lookup_term' as the 'body' because it might have Kanji corrections (from Smart Restore).
                # The 'Smart Restore' logic is still valid: it swaps OCR -> Dict if NFKC matches.
                
                cloze_suffix = sentence_clean[idx + len(ocr_term):] # Resume after the OCR version in the sentence
                
                # Dynamic Truncation based on configurable delimiters
                delims_keep = config.anki_sentence_delimiters # e.g. ['。', '!', '?']
                delims_remove = config.anki_sentence_delimiters_remove # e.g. ['\n']
                
                # We combine both for prefix truncation (always remove precedent)
                # But separate for suffix truncation (keep vs remove)
                
                if delims_keep or delims_remove:
                    import re # Fix for NameError: free variable 're'
                    
                    # Construct regex pattern with named groups for Suffix logic
                    # Group KEEP: (?:...)+
                    # Group REMOVE: (?:...)+
                    
                    patterns = []
                    if delims_keep:
                         safe_keep = [re.escape(d) for d in delims_keep]
                         patterns.append(f"(?P<KEEP>(?:{'|'.join(safe_keep)})+)")
                    
                    if delims_remove:
                         # Handle typical escape sequences if they came from config plain text
                         # e.g. user typed "\n" in config -> it's literal backslash n.
                         # We should interpret standard escapes? 
                         # For safety, let's treat config strings as literal unless valid escape char?
                         # Usually configparser reads raw. '\n' might be read as literal backslash-n.
                         # Let's effectively regex escape them, users can paste literals.
                         safe_remove = [re.escape(d) for d in delims_remove]
                         patterns.append(f"(?P<REMOVE>(?:{'|'.join(safe_remove)})+)")
                    
                    full_pattern = "|".join(patterns)
                    
                    # PREFIX TRUNCATION
                    # -----------------
                    # Prefix should be cut AFTER the last delimiter of ANY type.
                    # We just need to find the last match in the prefix string.
                    
                    last_delim_end = -1
                    for match in re.finditer(full_pattern, cloze_prefix):
                         if match.end() > last_delim_end:
                             last_delim_end = match.end()
                             
                    if last_delim_end != -1:
                         cloze_prefix = cloze_prefix[last_delim_end:]

                    # SUFFIX TRUNCATION
                    # -----------------
                    # Suffix should be cut AT the first delimiter.
                    # If it's a KEEP delimiter, we include it (end index).
                    # If it's a REMOVE delimiter, we exclude it (start index).
                    
                    first_match = re.search(full_pattern, cloze_suffix)
                    if first_match:
                         if first_match.group("KEEP"):
                             # Include values
                             cloze_suffix = cloze_suffix[:first_match.end()]
                         elif first_match.group("REMOVE"):
                             # Exclude values
                             cloze_suffix = cloze_suffix[:first_match.start()]
                         else:
                             # Should not match if regex is correct, but fallback to exclude
                             cloze_suffix = cloze_suffix[:first_match.start()]

            else:
                # Fallback if find fails (shouldn't happen if logic holds)
                 pass
        
        # Calculate Frequency Ranks
        # Parse frequency_tags like "JPDBv2㋕: 8143" - extract ONLY the number AFTER the colon
        import re

        def extract_preferred_freq_number(tag_text: str):
            """Extract preferred frequency number from a display tag.

            For values with multiple numbers (e.g. "730,35990の"), use the
            lowest numeric value as the effective frequency rank.
            """
            # Ignore orphan/unlabeled fragments (e.g. "127327") when computing ranks.
            if ":" not in tag_text:
                return None

            value_part = tag_text.split(":", 1)[-1]
            numbers = [int(n) for n in re.findall(r"\d+", value_part)]
            if not numbers:
                return None
            return min(numbers)

        def parse_frequency_tag(tag_text: str):
            """Return (dictionary_name, preferred_number) for a frequency tag."""
            if ":" not in tag_text:
                return None, None

            dict_name, _ = tag_text.split(":", 1)
            dict_name = dict_name.strip()
            if not dict_name:
                return None, None

            return dict_name, extract_preferred_freq_number(tag_text)

        # Use one effective frequency per dictionary source (lowest value per source).
        # This prevents overcounting when a source emits multiple numbers.
        freq_by_dict = {}
        for ft in entry.frequency_tags:
            dict_name, freq_num = parse_frequency_tag(ft)
            if dict_name is None or freq_num is None:
                continue

            current = freq_by_dict.get(dict_name)
            if current is None or freq_num < current:
                freq_by_dict[dict_name] = freq_num

        freq_values = list(freq_by_dict.values())
        
        freq_harmonic_rank = ""
        freq_average_rank = ""
        if freq_values:
            # Harmonic mean rank, matching Yomitan-style behavior.
            positive_values = [v for v in freq_values if v > 0]
            if positive_values:
                harmonic_mean = len(positive_values) / sum(1.0 / v for v in positive_values)
                freq_harmonic_rank = str(int(round(harmonic_mean)))
            
            # Average
            freq_average_rank = str(int(sum(freq_values) / len(freq_values)))

        frequencies_html = ""
        if freq_by_dict:
            sorted_freq_pairs = sorted(freq_by_dict.items(), key=lambda x: (x[1], x[0].lower()))
            frequencies_html = (
                '<ul style="text-align: left;">'
                + "".join(f"<li>{name}: {value}</li>" for name, value in sorted_freq_pairs)
                + "</ul>"
            )

        yomi_client = None
        pitch_accent_categories = ""
        if (word or reading) and config.yomitan_enabled:
            try:
                yomi_client = YomitanClient(config.yomitan_api_url)
                pitch_accent_categories = yomi_client.get_term_marker_value(
                    word,
                    reading,
                    "pitch-accent-categories",
                )
            except Exception as e:
                logger.debug(f"Failed to fetch Yomitan pitch-accent-categories: {e}")
        
        data_sources = {
            "Expression": word,
            "Reading": reading,
            "Furigana Plain": furigana_plain,
            "Glossary": glossary_full,
            "Glossary Raw": glossary_raw,
            "Glossary First": glossary_first,
            "Glossary 1st Dict": glossary_1st_dict,
            "Glossary Brief": glossary_brief,
            "Sentence": (cloze_prefix + cloze_body + cloze_suffix) if (cloze_body and idx != -1) else sentence_clean,
            "Cloze Prefix": cloze_prefix,
            "Cloze Body": cloze_body,
            "Cloze Suffix": cloze_suffix,
            "Pitch Accent Categories": pitch_accent_categories,
            "Pitch Accent Positions": ", ".join(pitch_positions),
            "Pitch Accent Graphs": "".join(pitch_graphs_html),
            "Frequencies": frequencies_html,
            "Frequency Harmonic Rank": freq_harmonic_rank,
            "Frequency Average Rank": freq_average_rank,
            "Tags": self._build_anki_tags(context.get("document_title", "")),
            "Audio": "",
            "Picture": "",
            "Document Title": context.get("document_title", "")
        }


        # Build Fields
        # ------------
        # Audio/Picture Logic
        # -------------------
        # Pre-calculate these so they can be treated as standard fields in templates
        
        audio_filename = ""
        audio_media_base64 = ""
        
        if word or reading:
             # Prefer Yomitan-provided audio for the selected entry.
             try:
                 if config.yomitan_enabled:
                     if yomi_client is None:
                         yomi_client = YomitanClient(config.yomitan_api_url)
                     audio_info = yomi_client.get_audio_media(word, reading)
                     if audio_info:
                         audio_filename = audio_info.get("filename", "")
                         audio_media_base64 = audio_info.get("content", "")
             except Exception as e:
                 logger.debug(f"Failed to fetch Yomitan audio: {e}")

             if audio_filename:
                 data_sources["Audio"] = f"[sound:{audio_filename}]"
        
        # Screenshot Logic for Picture field
        if screenshot_field:
             data_sources["Picture"] = screenshot_field

        # Helper map for template substitution (handles slugs like {cloze-prefix})
        slug_map = {}
        for k, v in data_sources.items():
             # Original key: "Cloze Prefix"
             slug_map[k] = str(v)
             # Slug key: "cloze-prefix"
             slug_map[k.lower().replace(" ", "-")] = str(v)

        # Fields Population Loop
        fields = {}
        has_audio_field = False
        
        for field, source in config.anki_field_map.items():
            if not source: continue
            
            # Check for template pattern (contains { and })
            if "{" in source and "}" in source:
                  import re
                  def replace_match(m):
                       key = m.group(1)
                       # Try slug (cloze-prefix), then exact key
                       s = key.lower().replace(" ", "-")
                       return slug_map.get(s, slug_map.get(key, m.group(0)))
                  
                  try:
                      fields[field] = re.sub(r'\{([^}]+)\}', replace_match, str(source))
                  except Exception as e:
                      logger.error(f"Template error in field '{field}': {e}")
                      fields[field] = str(source)
                  
                  # Detect if audio was used in this field
                  if "{audio}" in source.lower() or "{Audio}" in source:
                       has_audio_field = True
                       
            elif source in data_sources:
                  fields[field] = data_sources[source]
                  if source == "Audio":
                       has_audio_field = True

        should_upload_audio = bool(has_audio_field and audio_filename and audio_media_base64)

        if has_audio_field and not should_upload_audio:
             logger.info("Audio field is mapped but Yomitan returned no audio for this entry.")

        if not fields:
             logger.warning("No fields mapped for Anki card creation. Aborting.")
             self._show_status_message("Error: No fields mapped in settings", 3000)
             if config.anki_enable_screenshot:
                 self._suppress_popup_for_anki_screenshot = False
                 self._suppress_popup_until = 0.0
             return

        # Create Note Object
        note = {
            "deckName": deck_name,
            "modelName": model_name,
            "fields": fields,
            "tags": data_sources["Tags"].split(" "),
        }
        
        # User Request: If "Detect Duplicates" is OFF, allow adding duplicates explicitly.
        # AnkiConnect allows this via the 'options' field.
        if not config.anki_show_hover_status: # Assuming this config option means "Detect Duplicates" is OFF
            note["options"] = {
                "allowDuplicate": True,
                "duplicateScope": "deck" # or "collection", usually default is deck? check docs. 
                # Actually default for duplicateScope is "collection" in newer versions, 
                # but "deck" is often assumed if deckName is provided.
                # Safest is just allowDuplicate: True.
            }
            logger.info("Adding note with allowDuplicate=True")
        else:
            note["options"] = {
                "allowDuplicate": False,
                "duplicateScope": "deck",
                "duplicateScopeOptions": {
                    "deckName": deck_name,
                    "checkChildren": False,
                    "checkAllModels": False
                }
            }

        
        if should_upload_audio:
            try:
                anki.store_media_file(audio_filename, audio_media_base64)
            except Exception as e:
                logger.warning(f"Failed to store Yomitan audio media '{audio_filename}': {e}")
                # Avoid leaving broken [sound:...] references if media upload fails.
                search_tag = f"[sound:{audio_filename}]"
                for f_name, f_val in fields.items():
                    if search_tag in f_val:
                        fields[f_name] = f_val.replace(search_tag, "")
            
        try:
            note_id = anki.add_note(note)
            if note_id:
                logger.info(f"Note created: {note_id}")
                # Must use QTimer.singleShot to call Qt methods from background thread
                QTimer.singleShot(0, lambda: self._show_status_message(f"Added: {word}", 3000))
                self.copy_requested.emit(sentence)
                # Update UI immediately since we know it's now present
                # Ensure we use the exact same key derivation logic as the presence check
                dedup_key = (entry.written_form or entry.reading or "").strip()
                logger.info(f"Emitting signal for key='{dedup_key}' from add_to_anki")
                self.anki_presence_updated.emit(dedup_key, True)
            else:
                 logger.error("Failed to create note (no ID returned)")
                 # We should technically use a signal for this too, but QTimer might be failing silently. 
                 # If user sees status messages, then QTimer works? 
                 # But signal emit is definitely safe directly.
                 QTimer.singleShot(0, lambda: self._show_status_message("Failed to add note", 3000))
        except Exception as e:
            logger.error(f"Failed to add note: {e}")
            err_msg = str(e)
            QTimer.singleShot(0, lambda: self._show_status_message(f"Error: {err_msg}", 3000))
        finally:
            if config.anki_enable_screenshot:
                self._suppress_popup_for_anki_screenshot = False
                self._suppress_popup_until = 0.0
            QTimer.singleShot(0, self.loading_bar.hide)

    def copy_to_clipboard(self, text: Optional[str] = None):
        logger.info("Copy to clipboard clicked")
        if text is None:
            _, latest_context = self._get_interaction_data()
            if not latest_context:
                return

            text = latest_context.get("context_text", "")

        QApplication.clipboard().setText(text)

    def _copy_text_to_clipboard(self, text: str):
        self.copy_to_clipboard(text)

    def _apply_frame_stylesheet(self):
        bg_color = QColor(config.color_background)
        r, g, b = bg_color.red(), bg_color.green(), bg_color.blue()
        a = config.background_opacity
        self.frame.setStyleSheet(f"""
            #PopupFrame {{
                background-color: rgba({r}, {g}, {b}, {a});
                color: {config.color_foreground};
                border-radius: 8px;
                border: 1px solid #555;
            }}
            QLabel {{
                background-color: transparent;
                border: none;
                font-family: "{config.font_family}";
            }}
            hr {{
                border: none;
                height: 1px;
            }}
        """)

    def _calibrate_empirically(self):
        logger.debug("--- Calibrating Font Metrics Empirically (One-Time) ---")

        # Log font info
        actual_font = self.display_label.font()
        font_info = QFontInfo(actual_font)


        margins = self.content_layout.contentsMargins()
        border_width = 1
        horizontal_padding = margins.left() + margins.right() + (border_width * 2)

        screen = QApplication.primaryScreen()
        self.max_content_width = (int(screen.geometry().width() * 0.4)) - horizontal_padding

        header_font = QFont(config.font_family)
        header_font.setPixelSize(config.font_size_header)
        header_metrics = QFontMetrics(header_font)
        self.header_chars_per_line = self._find_chars_for_width(header_metrics, "Header")

        def_font = QFont(config.font_family)
        def_font.setPixelSize(config.font_size_definitions)
        def_metrics = QFontMetrics(def_font)
        self.def_chars_per_line = self._find_chars_for_width(def_metrics, "Definition")


        self.is_calibrated = True

    def _find_chars_for_width(self, metrics: QFontMetrics, name: str) -> int:
        low = 1
        high = 500
        best_fit = 1

        while low <= high:
            mid = (low + high) // 2
            if mid == 0: break

            test_string = 'x' * mid
            current_width = metrics.horizontalAdvance(test_string)

            if current_width <= self.max_content_width:
                best_fit = mid
                low = mid + 1
            else:
                high = mid - 1

        return best_fit if best_fit > 0 else 50

    def set_latest_data(self, data, context=None):
        if context is None:
            context = {}
            
        # Capture title if needed, outside lock to prevent blocking/deadlocks
        if "document_title" not in context:
            try:
                context["document_title"] = get_active_window_title()
            except Exception as e:
                logger.error(f"Error getting window title: {e}")
                context["document_title"] = ""

        with self._data_lock:
            self._latest_data = data
            self._latest_context = context
            if IS_WAYLAND and data:
                cursor_over_popup = self.is_visible and self.geometry().contains(QCursor.pos())
                # While interacting with popup controls, keep current cached content stable.
                if not cursor_over_popup:
                    self._wayland_cached_data = data
                    self._wayland_cached_context = context
                keepalive_seconds = max(0.0, float(getattr(config, 'popup_hide_delay_seconds', 0.0)))
                self._wayland_keepalive_until = time.perf_counter() + keepalive_seconds

    def get_latest_data(self):
        with self._data_lock:
            return self._latest_data, self._latest_context

    def _get_interaction_data(self):
        latest_data, latest_context = self.get_latest_data()
        if latest_data:
            return latest_data, latest_context

        if IS_WAYLAND and self._wayland_cached_data:
            return self._wayland_cached_data, (self._wayland_cached_context or {})

        # Final fallback: if popup is currently showing data, use the last rendered snapshot.
        if self._last_latest_data:
            return self._last_latest_data, (self._last_latest_context or {})

        return None, None

    def process_latest_data_loop(self):
        try:
            if not self.is_calibrated:
                self._calibrate_empirically()

            hotkey_or_auto_active = self.input_loop.is_virtual_hotkey_down()
            hotkey_physically_held = bool(getattr(self.input_loop, 'hotkey_is_pressed', False))

            live_latest_data, live_latest_context = self.get_latest_data()
            live_data_available = bool(live_latest_data)
            latest_data, latest_context = live_latest_data, live_latest_context
            data_refreshed = False
            cursor_over_popup = self.is_visible and self.geometry().contains(QCursor.pos())

            # Keep showing the last resolved entry while the user keeps holding
            # the hotkey (e.g. Shift), even if momentary hit-scan misses occur.
            if not latest_data and hotkey_physically_held and self._last_latest_data:
                latest_data = self._last_latest_data
                latest_context = self._last_latest_context or {}
            
            # Manage locked state: once hotkey is held and we have data, lock to that word
            if hotkey_physically_held and latest_data:
                if not self.shared_state.popup_locked_on_result:
                    # Just locked - store the lookup string we're locked on (use current context)
                    self.shared_state.popup_locked_on_result = True
                    locked_lookup_string = latest_context.get('lookup_string') if latest_context else None
                    self.shared_state.popup_locked_lookup_string = locked_lookup_string
                    logger.debug(f"Popup locked on: {locked_lookup_string}")
                else:
                    # Already locked - check if new lookup is for a different word
                    new_lookup_string = latest_context.get('lookup_string') if latest_context else None
                    if new_lookup_string and new_lookup_string != self.shared_state.popup_locked_lookup_string:
                        # Different word - ignore it, keep showing locked data
                        logger.debug(f"Popup: rejecting lookup for '{new_lookup_string}' (locked on '{self.shared_state.popup_locked_lookup_string}')")
                        latest_data = self._last_latest_data
                        latest_context = self._last_latest_context or {}
            elif not hotkey_physically_held:
                # Release lock when hotkey released
                if self.shared_state.popup_locked_on_result:
                    logger.debug(f"Popup lock released")
                self.shared_state.popup_locked_on_result = False
                self.shared_state.popup_locked_lookup_string = None

            if IS_WAYLAND and cursor_over_popup and self._wayland_cached_data:
                # Freeze displayed entry/content while cursor is in popup so controls
                # are directly clickable and not moved by incoming OCR updates.
                latest_data = self._wayland_cached_data
                latest_context = self._wayland_cached_context or {}

            if IS_WAYLAND and not latest_data:
                now_keepalive = time.perf_counter()
                if now_keepalive < self._wayland_keepalive_until and self._wayland_cached_data:
                    latest_data = self._wayland_cached_data
                    latest_context = self._wayland_cached_context or {}

            if latest_data and (latest_data != self._last_latest_data or latest_context != self._last_latest_context):
                data_refreshed = True
                self._update_scrollbar_policy_for_entries(latest_data)

                # Check if we should reset scroll (only if word changed)
                reset_scroll = True
                if self._last_latest_data and latest_data:
                    new_entry = latest_data[0]
                    old_entry = self._last_latest_data[0]
                    if new_entry.written_form == old_entry.written_form and new_entry.reading == old_entry.reading:
                        reset_scroll = False
                    else:
                        self._selected_entry_index = 0
                elif latest_data:
                    self._selected_entry_index = 0

                # Keep index valid when result count changes.
                self._get_selected_entry(latest_data)

                # ---- EARLY: Set presence status from cache BEFORE rendering ----
                entry, _ = self._get_selected_entry(latest_data)
                self._refresh_presence_for_entry(entry)
                # ----------------------------------------------------------------

                # update popup content
                full_html, new_size = self._calculate_content_and_size_char_count(latest_data)
                
                # If size calc crash returned None
                if full_html:
                    self.display_label.setText(full_html)
                    # self.setFixedSize(new_size) # Should use geometry if we set fixed size on frame?
                    # new_size is QSize(target_width, final_height)
                    # We should probably set popup window size too?
                    self.setFixedSize(new_size)
                    
                    # Reposition the Anki status icon after resize
                    if self.anki_status_icon.isVisible():
                        frame_width = self.frame.width()
                        icon_x = frame_width - 28
                        self.anki_status_icon.move(icon_x, 8)
                    
                    if reset_scroll:
                        self.scroll_area.verticalScrollBar().setValue(0)
            
            self._last_latest_data = latest_data
            self._last_latest_context = latest_context

            show_for_wayland_keepalive = False
            wayland_keepalive_seconds = max(0.0, float(getattr(config, 'popup_hide_delay_seconds', 0.0)))
            if IS_WAYLAND and latest_data:
                now = time.perf_counter()
                if live_data_available:
                    self._wayland_keepalive_until = now + wayland_keepalive_seconds
                if now < self._wayland_keepalive_until:
                    show_for_wayland_keepalive = True

                # If cursor is already over popup, keep it alive while interacting.
                if cursor_over_popup:
                    self._wayland_keepalive_until = now + wayland_keepalive_seconds
                    show_for_wayland_keepalive = True

            if IS_WAYLAND:
                should_show_popup = bool(latest_data) and (hotkey_or_auto_active or show_for_wayland_keepalive or cursor_over_popup)
            else:
                should_show_popup = bool(latest_data) and (hotkey_or_auto_active or show_for_wayland_keepalive)

            if self._suppress_popup_for_anki_screenshot:
                if self._suppress_popup_until and time.perf_counter() >= self._suppress_popup_until:
                    logger.warning("Anki screenshot popup suppression timed out; restoring popup behavior")
                    self._suppress_popup_for_anki_screenshot = False
                    self._suppress_popup_until = 0.0
                if self._suppress_popup_for_anki_screenshot:
                    should_show_popup = False

            if should_show_popup:
                self.show_popup()

                if show_for_wayland_keepalive and not hotkey_or_auto_active:
                    self._release_lock_safely()
                else:
                    self._acquire_lock_safely()
                
                # Check for shortcuts
                allow_shortcuts = hotkey_or_auto_active and bool(latest_data) and (
                    not IS_WAYLAND or live_data_available or cursor_over_popup
                )
                if allow_shortcuts:
                    anki_pressed = self.input_loop.is_key_pressed(config.shortcut_add_to_anki)
                    if anki_pressed and not self.anki_shortcut_was_pressed:
                        self.add_to_anki(manual_crop=True)
                    self.anki_shortcut_was_pressed = anki_pressed

                    copy_pressed = self.input_loop.is_key_pressed(config.shortcut_copy_text)
                    if copy_pressed and not self.copy_shortcut_was_pressed:
                        self.copy_to_clipboard()
                    self.copy_shortcut_was_pressed = copy_pressed
                else:
                    self.anki_shortcut_was_pressed = False
                    self.copy_shortcut_was_pressed = False


                
                # Handle scrolling (manual input hook)
                scroll_delta = self.input_loop.get_and_reset_scroll_delta()
                if scroll_delta != 0:
                    if IS_WAYLAND:
                        # On Wayland, global wheel blocking is not reliable and can
                        # still advance VN text. Ignore wheel in popup to avoid skip.
                        scroll_delta = 0

                if scroll_delta != 0:
                    # High-resolution wheels can emit bursts; clamp to keep behavior predictable.
                    scroll_delta = max(-2, min(2, int(scroll_delta)))

                    now = time.perf_counter()
                    if now < self._entry_cycle_cooldown_until:
                        self._entry_cycle_wheel_direction = 0
                        self._entry_cycle_wheel_accumulator = 0
                    else:
                        scrollbar = self.scroll_area.verticalScrollBar()
                        # dy is usually 1 or -1 for one notch. In pixels, maybe 30 or 60?
                        # Negative dy (scroll down) should increase value.
                        step = 28
                        current_val = scrollbar.value()
                        min_val = scrollbar.minimum()
                        max_val = scrollbar.maximum()
                        requested_val = scrollbar.value() - int(scroll_delta * step)
                        clamped_val = max(min_val, min(requested_val, max_val))
                        at_top_before = current_val <= min_val
                        at_bottom_before = current_val >= max_val

                        if latest_data and len(latest_data) > 1:
                            # Prefer reading current entry first.
                            # Only cycle entries if we were already at the edge before this wheel event.
                            if requested_val > max_val and at_bottom_before:
                                direction = 1
                                if self._entry_cycle_wheel_direction != direction:
                                    self._entry_cycle_wheel_direction = direction
                                    self._entry_cycle_wheel_accumulator = 0
                                self._entry_cycle_wheel_accumulator += 1
                                if self._entry_cycle_wheel_accumulator >= self._entry_cycle_threshold:
                                    self._move_selected_entry(1)
                                    self._entry_cycle_wheel_direction = 0
                                    self._entry_cycle_wheel_accumulator = 0
                                    self._entry_cycle_cooldown_until = now + self._entry_cycle_cooldown_seconds
                                    # Drop wheel carry-over so next entry does not jump to mid-content.
                                    self.input_loop.get_and_reset_scroll_delta()
                            elif requested_val < min_val and at_top_before:
                                direction = -1
                                if self._entry_cycle_wheel_direction != direction:
                                    self._entry_cycle_wheel_direction = direction
                                    self._entry_cycle_wheel_accumulator = 0
                                self._entry_cycle_wheel_accumulator += 1
                                if self._entry_cycle_wheel_accumulator >= self._entry_cycle_threshold:
                                    self._move_selected_entry(-1)
                                    self._entry_cycle_wheel_direction = 0
                                    self._entry_cycle_wheel_accumulator = 0
                                    self._entry_cycle_cooldown_until = now + self._entry_cycle_cooldown_seconds
                                    # Drop wheel carry-over so next entry does not jump to mid-content.
                                    self.input_loop.get_and_reset_scroll_delta()
                            else:
                                self._entry_cycle_wheel_direction = 0
                                self._entry_cycle_wheel_accumulator = 0
                                scrollbar.setValue(clamped_val)
                        else:
                            self._entry_cycle_wheel_direction = 0
                            self._entry_cycle_wheel_accumulator = 0
                            scrollbar.setValue(clamped_val)
                    
            else:
                self.hide_popup()
                # Clear accumulated scroll when not active to prevent jump on next show
                self.input_loop.get_and_reset_scroll_delta()
        except Exception as e:
            logger.exception("Error in process_latest_data_loop")

        # Anki presence check now runs through _refresh_presence_for_entry on selection/data updates.
        if not latest_data:
            self._update_scrollbar_policy_for_entries(None)
            self._anki_presence_status = None

        mouse_pos = QCursor.pos()
        if IS_WAYLAND:
            # On Wayland, continuous follow makes overlay impossible to interact with.
            # Reposition only on fresh OCR/lookup updates.
            if data_refreshed:
                self.move_to(mouse_pos.x(), mouse_pos.y())
        else:
            self.move_to(mouse_pos.x(), mouse_pos.y())

    def _calculate_content_and_size_char_count(self, entries: Optional[List[DictionaryEntry]]) -> tuple[
        Optional[str], Optional[QSize]]:
        if not self.is_calibrated: return None, None

        if not entries:
            return None, None

        all_html_parts = []
        max_ratio = 0.0

        selected_entry, selected_idx = self._get_selected_entry(entries)
        if not selected_entry:
            return None, None

        # Always render only the selected entry; users cycle with mouse wheel.
        entries_to_render = [(selected_idx, selected_entry)]

        # Prepare color with 60% opacity for separator (Hex #RRGGBBAA)
        # Prepare solid blended color for separator (60% FG onto BG)
        fg_col = QColor(config.color_foreground)
        bg_col = QColor(config.color_background)
        
        # Calculate blended RGB: Result = FG * 0.6 + BG * 0.4
        def blend(c1, c2, ratio):
            return int(c1 * ratio + c2 * (1 - ratio))
            
        r = blend(fg_col.red(), bg_col.red(), 0.6)
        g = blend(fg_col.green(), bg_col.green(), 0.6)
        b = blend(fg_col.blue(), bg_col.blue(), 0.6)
        
        sep_color = f"#{r:02x}{g:02x}{b:02x}"

        def build_raw_overlay_html(entry_obj, senses):
            def add_inline_style_to_tag(opening_tag: str, extra_style: str) -> str:
                style_match = re.search(r'style="([^"]*)"', opening_tag)
                if style_match:
                    merged = style_match.group(1).strip()
                    if merged and not merged.endswith(';'):
                        merged += '; '
                    merged += extra_style
                    return re.sub(r'style="[^"]*"', f'style="{merged}"', opening_tag, count=1)
                return opening_tag[:-1] + f' style="{extra_style}">'

            def style_by_class(html_text: str, tag: str, class_name: str, style: str) -> str:
                pattern = re.compile(rf'<{tag}([^>]*\bclass="[^"]*\b{class_name}\b[^"]*"[^>]*)>', re.IGNORECASE)
                return pattern.sub(lambda m: add_inline_style_to_tag(f'<{tag}{m.group(1)}>', style), html_text)

            def style_by_data_sc_class(html_text: str, tag: str, class_name: str, style: str) -> str:
                pattern = re.compile(rf'<{tag}([^>]*\bdata-sc-class="{class_name}"[^>]*)>', re.IGNORECASE)
                return pattern.sub(lambda m: add_inline_style_to_tag(f'<{tag}{m.group(1)}>', style), html_text)

            def style_by_data_sc_content(html_text: str, tag: str, content_name: str, style: str) -> str:
                pattern = re.compile(rf'<{tag}([^>]*\bdata-sc-content="{content_name}"[^>]*)>', re.IGNORECASE)
                return pattern.sub(lambda m: add_inline_style_to_tag(f'<{tag}{m.group(1)}>', style), html_text)

            def style_by_attr_contains(html_text: str, tag: str, attr_name: str, needle: str, style: str) -> str:
                pattern = re.compile(rf'<{tag}([^>]*\b{attr_name}="[^"]*{re.escape(needle)}[^"]*"[^>]*)>', re.IGNORECASE)
                return pattern.sub(lambda m: add_inline_style_to_tag(f'<{tag}{m.group(1)}>', style), html_text)

            def qtify_raw_html(html_text: str) -> str:
                # Make forms tables readable in Qt even when advanced CSS selectors are unsupported.
                html_text = re.sub(
                    r'<table(?![^>]*\bstyle=)([^>]*)>',
                    lambda m: add_inline_style_to_tag(f'<table{m.group(1)}>',
                                                      'table-layout:auto; border-collapse:collapse; margin-top:0.2em;'),
                    html_text,
                    flags=re.IGNORECASE
                )

                html_text = re.sub(
                    r'<th(?![^>]*\bstyle=)([^>]*)>',
                    lambda m: add_inline_style_to_tag(
                        f'<th{m.group(1)}>',
                        'font-weight:normal; border-style:solid; border-width:1px; border-color:currentColor; '
                        'padding:0.25em; vertical-align:top; text-align:center;'
                    ),
                    html_text,
                    flags=re.IGNORECASE
                )
                html_text = re.sub(
                    r'<td(?![^>]*\bstyle=)([^>]*)>',
                    lambda m: add_inline_style_to_tag(
                        f'<td{m.group(1)}>',
                        'border-style:solid; border-width:1px; border-color:currentColor; '
                        'padding:0.25em; vertical-align:top; text-align:center;'
                    ),
                    html_text,
                    flags=re.IGNORECASE
                )

                tag_badge_style = (
                    'display:inline-block; border-radius:0.3em; font-size:0.8em; font-weight:bold; margin-right:0.5em; '
                    'padding:0.2em 0.3em; vertical-align:text-bottom; word-break:keep-all; '
                    'background-color:rgb(86,86,86); color:white;'
                )
                html_text = style_by_class(html_text, 'span', 'tag', tag_badge_style)
                html_text = style_by_data_sc_class(html_text, 'span', 'tag', tag_badge_style)

                # Differentiate misc-style tags (e.g. kana) from POS tag.
                html_text = style_by_data_sc_content(
                    html_text,
                    'span',
                    'misc-info',
                    'background-color:#b73239; color:white;'
                )
                html_text = style_by_attr_contains(
                    html_text,
                    'span',
                    'title',
                    'word usually written using kana',
                    'background-color:#b73239; color:white;'
                )

                # Ensure visual separation between adjacent tags in Qt rich text.
                html_text = re.sub(
                    r'(</span>)(?=<span[^>]*(?:\bclass="[^"]*\btag\b[^"]*"|\bdata-sc-class="tag"))',
                    r'\1&nbsp;',
                    html_text,
                    flags=re.IGNORECASE
                )

                # Fix xref label/link spacing like "See also参る".
                html_text = re.sub(r'(</span>)(?=<a)', r'\1&nbsp;', html_text, flags=re.IGNORECASE)
                html_text = re.sub(r'(See also)(?=<a)', r'\1&nbsp;', html_text, flags=re.IGNORECASE)
                html_text = re.sub(r'(See also)(?=[\u3040-\u30ff\u4e00-\u9fff])', r'\1&nbsp;', html_text)

                # Extra info boxes: default + specialized colors for example/xref.
                extra_box_style = (
                    'display:block; border-radius:0.45rem; border-left:3px solid #2f81f7; '
                    'margin:0.5rem 0; padding:0.5rem 0.6rem; '
                    'background-color:#132338;'
                )
                html_text = style_by_class(html_text, 'div', 'extra-box', extra_box_style)
                html_text = style_by_data_sc_class(html_text, 'div', 'extra-box', extra_box_style)

                html_text = style_by_data_sc_content(
                    html_text,
                    'div',
                    'example-sentence',
                    'border-left:3px solid #2f81f7; background-color:#132338; border-radius:0.45rem; '
                    'padding:0.5rem 0.6rem; margin:0.5rem 0;'
                )
                html_text = style_by_data_sc_content(
                    html_text,
                    'div',
                    'xref',
                    'border-left:3px solid #2f81f7; background-color:#132338; border-radius:0.45rem; '
                    'padding:0.5rem 0.6rem; margin:0.5rem 0;'
                )

                html_text = style_by_data_sc_content(html_text, 'div', 'example-sentence-a', 'font-size:1.2em; margin-bottom:0.2rem;')
                html_text = style_by_data_sc_content(html_text, 'div', 'example-sentence-b', 'font-size:0.92em; opacity:0.96;')
                html_text = style_by_data_sc_content(html_text, 'div', 'xref-content', 'font-size:1.15em; margin-bottom:0.2rem;')
                html_text = style_by_data_sc_content(html_text, 'div', 'xref-glossary', 'font-size:0.9em;')
                html_text = style_by_data_sc_content(html_text, 'span', 'reference-label', 'color:#4ea3ff; margin-right:0.45rem;')

                # Fallback when data-sc-content attrs are absent but structure exists.
                html_text = re.sub(
                    r'<span([^>]*)\blang="en"([^>]*)>See also</span>',
                    r'<span\1lang="en"\2 style="color:#4ea3ff; margin-right:0.45rem;">See also</span>',
                    html_text,
                    flags=re.IGNORECASE
                )

                # Form status cells with visible symbol + color badge.
                form_styles = {
                    'form-pri': ('△', '#198f2d', 'white'),
                    'form-irr': ('✕', '#b31d1d', 'white'),
                    'form-out': ('古', '#1d4fa3', 'white'),
                    'form-old': ('旧', '#1d4fa3', 'white'),
                    'form-rare': ('▽', '#7a23a8', 'white'),
                    'form-valid': ('◇', '#d9d9d9', '#222')
                }
                for cls, (symbol, bg_color, fg_color) in form_styles.items():
                    html_text = style_by_class(html_text, 'td', cls, 'text-align:center;')
                    html_text = style_by_data_sc_class(html_text, 'td', cls, 'text-align:center;')
                    html_text = re.sub(
                        rf'(<td[^>]*(?:\bclass="[^"]*\b{cls}\b[^"]*"|\bdata-sc-class="{cls}")[^>]*>\s*<span[^>]*>)\s*(</span>)',
                        rf'\1{symbol}\2',
                        html_text,
                        flags=re.IGNORECASE
                    )
                    html_text = re.sub(
                        rf'(<td[^>]*(?:\bclass="[^"]*\b{cls}\b[^"]*"|\bdata-sc-class="{cls}")[^>]*>\s*<span)([^>]*>)',
                        lambda m, bg=bg_color, fg=fg_color: (
                            f"{m.group(1)}{m.group(2)[:-1]} "
                            f"style=\"display:inline-block; min-width:1.35em; text-align:center; "
                            f"font-weight:bold; line-height:1.25em; padding:0.05em 0.2em; border-radius:999px; "
                            f"color:{fg}; background-color:{bg};\">"
                        ),
                        html_text,
                        flags=re.IGNORECASE
                    )

                return html_text

            raw_li_items = []
            for sense in senses:
                glosses = sense.get('glosses', [])
                if any(g.startswith("PITCH:") for g in glosses):
                    continue

                raw_html = qtify_raw_html(sense.get('raw_html', ''))
                if not raw_html:
                    continue

                source = sense.get('source', '')
                source_attr = source.replace('"', '&quot;')

                pos_parts = [p for p in sense.get('pos', []) if p]
                if source:
                    pos_parts.append(source)
                pos_str = f"<i>({', '.join(pos_parts)})</i> " if pos_parts else ""

                raw_li_items.append(f'<li data-dictionary="{source_attr}">{pos_str}{raw_html}</li>')

            if not raw_li_items:
                return ""

            raw_html_block = f'<div style="text-align: left;" class="yomitan-glossary"><ol>{"".join(raw_li_items)}</ol></div>'
            if "<style" not in raw_html_block.lower():
                raw_html_block += f"<style>{YOMITAN_RAW_FALLBACK_CSS}</style>"
            return raw_html_block
        
        
        for i, (global_idx, entry) in enumerate(entries_to_render):
            header_text_calc = entry.written_form
            if entry.reading: header_text_calc += f" [{entry.reading}]"
            if config.show_tags and entry.tags:
                header_text_calc += f' [{", ".join(sorted(list(entry.tags)))}]'
            if config.show_frequency and entry.frequency_tags:
                header_text_calc += f' [{group_frequency_tags(entry.frequency_tags)}]'
            header_ratio = len(header_text_calc) / self.header_chars_per_line
            max_ratio = max(max_ratio, header_ratio)

            # Separate senses into regular and pitch/accent-related
            regular_senses = []
            pitch_html_list = []
            seen_pitches = set()
            
            for sense in entry.senses:
                source = sense.get('source', 'General')
                # Check if this is a pitch dictionary (heuristic: contains "Pitch" or "Accent" or "Kanjium" or "Otogen")
                # You might need to adjust these keywords based on actual dictionary names used.
                # Made case-insensitive and added common ones like NHK and Japanese "アクセント"
                keywords = ["pitch", "accent", "kanjium", "otogen", "nhk", "shinmeikai", "アクセント", "大辞林"]
                is_pitch_source = any(k in source.lower() for k in keywords)
                
                if is_pitch_source:
                    # Extract pitch info to show in header
                    glosses = sense.get('glosses', [])
                    if glosses:
                        for g in glosses:
                            if g.startswith("PITCH:"):
                                try:
                                    # Parse "PITCH:{pos}:{reading}"
                                    parts = g.split(":")
                                    # Handle "PITCH:[0]:reading" (strip brackets) or "PITCH:0:reading"
                                    pos_str = parts[1].replace('[', '').replace(']', '')
                                    pos = int(pos_str)
                                    reading = parts[2]
                                    
                                    # Check for duplicates
                                    pitch_key = (pos, reading)
                                    if pitch_key in seen_pitches:
                                        continue
                                    seen_pitches.add(pitch_key)

                                    # Render visual graph
                                    # Use foreground color for line or specific color?
                                    # User requested "line over reading".
                                    # let's use config.color_highlight_reading or foreground
                                    graph_html = render_pitch_html(reading, pos, color_line=config.color_foreground)
                                    pitch_html_list.append(graph_html)
                                except Exception as e:
                                    logger.error(f"Failed to render pitch graph for '{g}': {e}")
                            else:
                                # Fallback for text glosses (e.g. from local dictionaries like Kanjium which provide text [LHH])
                                # Kanjium glosses usually look like "[LHH] ..."
                                # We can't easily convert [LHH] to graph without parsing logic.
                                # So just display as text.
                                pitch_html_list.append(f'<span style="color:#dca3a3; font-size:{config.font_size_definitions - 2}px; margin-left: 5px;">{g}</span>')
                else:
                    regular_senses.append(sense)

            # --- HTML construction ---
            separator_html = ""
            if i > 0:
                # Add separator as part of the entry, with negative bottom margin to pull header closer
                separator_html = (
                    f'<div style="font-size: 0; line-height: 0;">'
                    f'<table width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-top: 20px; margin-bottom: 0px;">'
                    f'<tr><td style="border-top: 1px solid {sep_color}; height: 0px; padding: 0;"></td></tr>'
                    f'</table>'
                    f'</div>'
                )

            nav_html = ""
            if i == 0 and len(entries) > 1:
                nav_html = (
                    f'<div style="font-size:{config.font_size_definitions - 2}px; opacity:0.85; margin-bottom: 4px;">'
                    f'<span style="color:{config.color_foreground};">Entry {selected_idx + 1}/{len(entries)} | Scroll wheel to cycle</span>'
                    f'</div>'
                )

            if global_idx == selected_idx:
                word_html = (
                    f'<span style="color:{config.color_highlight_word}; font-size:{config.font_size_header}px; font-weight:600;">'
                    f'{entry.written_form} <span style="font-size:{config.font_size_definitions - 1}px; opacity:0.8;">[selected]</span>'
                    f'</span>'
                )
            else:
                word_html = (
                    f'<a href="select:{global_idx}" style="color:{config.color_highlight_word}; text-decoration:none;">'
                    f'<span style="font-size:{config.font_size_header}px;">{entry.written_form}</span>'
                    f'</a>'
                )

            header_html = f'{separator_html}{nav_html}{word_html}'
            
            if entry.reading: header_html += f' <span style="color: {config.color_highlight_reading}; font-size:{config.font_size_header - 2}px;">[{entry.reading}]</span>'
            if config.show_tags and entry.tags:
                tags_str = ", ".join(sorted(list(entry.tags)))
                header_html += f' <span style="color:{config.color_foreground}; font-size:{config.font_size_definitions - 2}px; opacity:0.7;">[{tags_str}]</span>'
            if config.show_frequency and entry.frequency_tags:
                freq_str = group_frequency_tags(entry.frequency_tags)
                header_html += f'&nbsp;&nbsp;&nbsp;<span style="color:{config.color_highlight_word}; font-size:{config.font_size_definitions - 2}px; opacity:0.8;">[{freq_str}]</span>'
            
            # --- Add Pitch Info to Header ---
            if config.show_pitch_accent and pitch_html_list:
                separator = '&nbsp;'
                pitch_joined = separator.join(pitch_html_list)
                header_html += f'&nbsp;&nbsp;&nbsp;{pitch_joined}'

            if entry.deconjugation_process and config.show_deconjugation:
                deconj_str = " ← ".join(p for p in entry.deconjugation_process if p)
                if deconj_str:
                    if config.show_deconjugation_below:
                        # New line below the word
                         header_html += f'<div style="color:{config.color_foreground}; font-size:{config.font_size_definitions - 2}px; opacity:0.8; margin-top: 2px;">({deconj_str})</div>'
                    else:
                        # Inline
                        header_html += f' <span style="color:{config.color_foreground}; font-size:{config.font_size_definitions - 2}px; opacity:0.8;">({deconj_str})</span>'
            
            # Wrap header in table for right-aligned icon (only for first entry)
            if i == 0:
                # Determine icon HTML based on status and config
                # When show_hover_status is ON: gray=in Anki, green=new
                # When show_hover_status is OFF: purple=in Anki, green=new
                if self._anki_presence_status is None:
                    # Loading state - gray if show_hover_status ON, green if OFF
                    loading_color = "#888888" if config.anki_show_hover_status else "#4CAF50"
                    icon_html = f'<span style="font-size: 16px; color: {loading_color}; opacity: 0.5;">⊕</span>'
                elif self._anki_presence_status:
                    # Already in Anki - gray if show_hover_status ON, purple if OFF
                    in_anki_color = "#888888" if config.anki_show_hover_status else "#D999EC"
                    icon_html = f'<span style="font-size: 16px; color: {in_anki_color};">⊕</span>'
                else:
                    # New word - always green
                    icon_html = '<span style="font-size: 16px; color: #4CAF50;">⊕</span>'
                
                # Use table to push icon to right
                header_html = (
                    f'<table width="100%" border="0" cellspacing="0" cellpadding="0" style="margin: 0;">'
                    f'<tr>'
                    f'<td style="vertical-align: top;">{header_html}</td>'
                    f'<td style="vertical-align: top; text-align: right; width: 20px; padding-top: 4px;">{icon_html}</td>'
                    f'</tr>'
                    f'</table>'
                )
            if getattr(config, 'use_raw_yomitan_overlay', False):
                raw_overlay_html = build_raw_overlay_html(entry, regular_senses)
                if raw_overlay_html:
                    raw_calc_text = re.sub(r'<[^>]+>', ' ', raw_overlay_html)
                    raw_calc_text = re.sub(r'\s+', ' ', raw_calc_text).strip()
                    if raw_calc_text:
                        def_ratio = len(raw_calc_text) / self.def_chars_per_line
                        max_ratio = max(max_ratio, def_ratio)

                    definitions_html_final = (
                        f'<div style="font-size:{config.font_size_definitions}px; '
                        f'color:{config.color_definitions}; margin-top: -4px;">{raw_overlay_html}</div>'
                    )
                    all_html_parts.append(f"{header_html}{definitions_html_final}")
                    continue

            # Group senses by source (preserves order)
            from itertools import groupby
            
            def get_source(s):
                return s.get('source', 'General')
                
            def_text_parts_calc = []
            def_text_parts_html = []
            
            # Sort senses by source first to ensure groupby works correctly
            # (groupby only groups consecutive items, so we need them sorted)
            sorted_senses = sorted(regular_senses, key=get_source)
            
            # Now groupby will properly group all senses from the same source together
            for source, group in groupby(sorted_senses, key=get_source):
                group_list = list(group)
                if not group_list: continue
                
                # Add Source Header
                if len(regular_senses) > len(group_list): # Only show header if there are multiple sources or mixing occurred? 
                    # Actually, always useful to know source if we are supporting yomichan dicts.
                    # But for single dictionary setup, might be noisy. 
                    # Let's show it if source is not "General" or if we have multiple groups.
                    source_header_html = f"<div style='color: #888888; font-size: {config.font_size_definitions - 2}px; margin-top: 6px; margin-bottom: 2px; font-weight: bold;'>{source}</div>"
                    def_text_parts_html.append(source_header_html)
                
                for idx, sense in enumerate(group_list):
                    original_glosses = sense.get('glosses', [])
                    
                    # Request: only show definitions next to numbers (1, 2, 3...) or circled numbers (①...)
                    # Heuristic: if ANY gloss in this sense matches the pattern, we filter to show ONLY matching ones.
                    # If NO glosses match (e.g. unnumbered dictionary), we show all (fallback).
                    # Pattern matches start of string: optional whitespace, then (digits OR circled numbers)
                    filter_pattern = re.compile(r'^\s*(?:\d+|[①-⑳])')
                    
                    filtered_glosses = [g for g in original_glosses if filter_pattern.match(g)]
                    
                    if filtered_glosses:
                        final_glosses = filtered_glosses
                        # If we have numbered definitions, show them on separate lines
                        glosses_str = '<br>'.join(g.replace('\n', '<br>') for g in final_glosses)
                    else:
                        final_glosses = original_glosses
                        # Standard joining for synonyms, but respect explicit newlines in text
                        glosses_str = '; '.join(g.replace('\n', '<br>') for g in final_glosses)
                    pos_list = sense.get('pos', [])
                    sense_calc = f"({idx + 1})"
                    sense_html = f"<b>({idx + 1})</b> "
                    if config.show_pos and pos_list:
                        pos_str = f' ({", ".join(pos_list)})'
                        sense_calc += pos_str
                        sense_html += f'<span style="color:{config.color_foreground}; opacity:0.7;"><i>{pos_str}</i></span> '
                    sense_calc += glosses_str
                    sense_html += glosses_str
                    def_text_parts_calc.append(sense_calc)
                    def_text_parts_html.append(sense_html)
                
            if config.compact_mode:
                separator = "; "
                # If we have headers (divs) in the list, joining by "; " might look weird for the divs themselves.
                # But headers are divs. 
                # We should probably join senses, but inject headers as block elements.
                # Simplify for now: Just join everything. Browsers/Qt might handle div inside inline context weirdly or force break.
                # Div forces line break usually.
                full_def_text_html = "".join(def_text_parts_html) 
                def_ratio = len("".join(def_text_parts_calc)) / self.def_chars_per_line
                max_ratio = max(max_ratio, def_ratio)
            else:
                separator = "<br>"
                # logic to join senses with BR but keep headers as is
                # We already appended headers to list as strings. 
                # Ideally headers shouldn't have BR before them if they are first?
                # But we join ALL parts.
                # Senses need BR between them. Header needs no BR after it but BR before it?
                # My loop structure appended header then senses.
                # If I join with <br>, I get: Header<br>Sense<br>Sense.
                # That logic is fine.
                full_def_text_html = separator.join(def_text_parts_html)
                for def_text_calc in def_text_parts_calc:
                    def_ratio = len(def_text_calc) / self.def_chars_per_line
                    max_ratio = max(max_ratio, def_ratio)

            definitions_html_final = f'<div style="font-size:{config.font_size_definitions}px; color:{config.color_definitions}; margin-top: -4px;">{full_def_text_html}</div>'
            all_html_parts.append(f"{header_html}{definitions_html_final}")

        full_html = "".join(all_html_parts)
        
        # Add buttons (Removed, moved to sticky footer)
        # buttons_html = ...
        # full_html += buttons_html

        margins = self.content_layout.contentsMargins()
        border_width = 1
        scrollbar_width = 25
        base_horizontal_padding = margins.left() + margins.right() + (border_width * 2)
        horizontal_padding_with_scroll = base_horizontal_padding + scrollbar_width
        
        vertical_padding = margins.top() + margins.bottom() + (border_width * 2)

        # Target width from config
        target_width = config.max_width
        
        # Determine footer height first
        footer_height = self.footer_label.sizeHint().height() + 10 # + margin

        # First pass: Calculate height assuming NO scrollbar (wider content area)
        self.probe_label.setText(full_html)
        self.probe_label.setFixedWidth(target_width - base_horizontal_padding)
        content_height_no_scroll = self.probe_label.heightForWidth(target_width - base_horizontal_padding)
        
        total_height_no_scroll = content_height_no_scroll + vertical_padding + footer_height
        
        # Check if we need a scrollbar
        if total_height_no_scroll <= config.max_height:
            # No scrollbar needed! Use wider layout.
            final_horizontal_padding = base_horizontal_padding
            final_height = total_height_no_scroll
        else:
            # Scrollbar needed. Recalculate height with narrower content area.
            self.probe_label.setFixedWidth(target_width - horizontal_padding_with_scroll)
            content_height_with_scroll = self.probe_label.heightForWidth(target_width - horizontal_padding_with_scroll)
            total_height_with_scroll = content_height_with_scroll + vertical_padding + footer_height
            
            final_horizontal_padding = horizontal_padding_with_scroll
            final_height = min(total_height_with_scroll, config.max_height)

        # Apply final width to labels
        self.display_label.setFixedWidth(target_width - final_horizontal_padding)
        self.footer_label.setFixedWidth(target_width - final_horizontal_padding)

        return full_html, QSize(target_width, final_height)

    def move_to(self, x, y):
        cursor_point = QPoint(x, y)
        screen = QApplication.screenAt(cursor_point) or QApplication.primaryScreen()
        screen_geo = screen.geometry()
        popup_size = self.size()
        offset = 15

        ratio = screen.devicePixelRatio()
        x, y = magpie_manager.transform_raw_to_visual((int(x), int(y)), ratio)

        # --- Positioning logic based on mode ---
        mode = config.popup_position_mode

        if mode == 'visual_novel_mode':
            # --- Vertical Position (VN Mode) ---
            screen_height = screen_geo.height()
            cursor_y_in_screen = y - screen_geo.top()
            is_below = True
            if cursor_y_in_screen > (2 * screen_height / 3):  # Lower third
                is_below = False  # Place above
            elif cursor_y_in_screen < (screen_height / 3):  # Upper third
                is_below = True  # Place below
            else:  # Middle third
                is_below = cursor_y_in_screen < (screen_height / 2)
            final_y = (y + offset) if is_below else (y - popup_size.height() - offset)

            # Vertical Push
            if final_y < screen_geo.top(): final_y = screen_geo.top()
            if final_y + popup_size.height() > screen_geo.bottom():
                final_y = screen_geo.bottom() - popup_size.height()

            # --- Horizontal Position (VN Mode) ---
            screen_width = screen_geo.width()
            cursor_x_in_screen = x - screen_geo.left()
            # Define anchor points for interpolation
            pos_right = x + offset
            pos_center = x - popup_size.width() / 2.0
            pos_left = x - popup_size.width() - offset

            # Interpolate smoothly between right, center, and left alignment
            if cursor_x_in_screen < screen_width / 2.0:
                ratio = cursor_x_in_screen / (screen_width / 2.0)
                final_x = pos_right * (1 - ratio) + pos_center * ratio
            else:
                ratio = (cursor_x_in_screen - (screen_width / 2.0)) / (screen_width / 2.0)
                final_x = pos_center * (1 - ratio) + pos_left * ratio

        elif mode == 'flip_horizontally':
            # X: Flip, Y: Push
            preferred_x = x + offset
            final_x = preferred_x if preferred_x + popup_size.width() <= screen_geo.right() else x - popup_size.width() - offset

            final_y = y + offset
            if final_y + popup_size.height() > screen_geo.bottom(): final_y = screen_geo.bottom() - popup_size.height()
            if final_y < screen_geo.top(): final_y = screen_geo.top()

        elif mode == 'flip_vertically':
            # X: Push, Y: Flip
            final_x = x + offset
            if final_x + popup_size.width() > screen_geo.right(): final_x = screen_geo.right() - popup_size.width()
            if final_x < screen_geo.left(): final_x = screen_geo.left()

            preferred_y = y + offset
            final_y = preferred_y if preferred_y + popup_size.height() <= screen_geo.bottom() else y - popup_size.height() - offset

        else:  # 'flip_both'
            # X: Flip
            preferred_x = x + offset
            final_x = preferred_x if preferred_x + popup_size.width() <= screen_geo.right() else x - popup_size.width() - offset

            # Y: Flip
            preferred_y = y + offset
            final_y = preferred_y if preferred_y + popup_size.height() <= screen_geo.bottom() else y - popup_size.height() - offset

        # Final clamp to ensure the popup is always fully visible.
        # This acts as a safeguard against any edge cases.
        final_x = max(screen_geo.left(), min(final_x, screen_geo.right() - popup_size.width()))
        final_y = max(screen_geo.top(), min(final_y, screen_geo.bottom() - popup_size.height()))

        self.move(int(final_x), int(final_y))

    def hide_popup(self):
        # logger.debug(f"hide_popup triggered while visibility:{self.is_visible}")
        if not self.is_visible:
            return
        self.hide()
        if IS_WAYLAND and IS_KDE and self._input_grab_active:
            # Best-effort release of explicit grabs made in show_popup.
            try:
                self.releaseMouse()
            except Exception:
                pass
            try:
                self.releaseKeyboard()
            except Exception:
                pass
            self._input_grab_active = False
        self.is_visible = False
        if IS_WAYLAND:
            self._wayland_keepalive_until = 0.0
            self._wayland_hovered_popup_once = False
        QTimer.singleShot(50, lambda: self._release_lock_safely())  # prevent popup from being screenshotted
        self._restore_focus_on_mac()

    def _acquire_lock_safely(self):
        if self._screen_lock_held:
            return
        logger.debug("show_popup acquiring lock...")
        self.shared_state.screen_lock.acquire()
        self._screen_lock_held = True
        logger.debug("...successfully acquired lock by show_popup")

    def _release_lock_safely(self):
        if not self._screen_lock_held:
            return
        logger.debug("hide_popup releasing lock...")
        self.shared_state.screen_lock.release()
        self._screen_lock_held = False
        logger.debug("...successfully released lock by hide_popup")

    def show_popup(self):
        # logger.debug(f"show_popup triggered while visibility:{self.is_visible}")
        if self.is_visible:
            return
        self._acquire_lock_safely()

        self._store_active_window_on_mac()
        self.show()
        if IS_MACOS or IS_WAYLAND:
            self.raise_()
        if IS_WAYLAND:
            if IS_KDE:
                # On KDE Wayland: give focus for input without activating (which pops taskbar)
                self.setFocus(Qt.FocusReason.PopupFocusReason)
                # Fullscreen detection can be unreliable on Wayland/XWayland boundaries.
                # Always attempt grab while popup is visible on KDE Wayland.
                grabbed_mouse = False
                grabbed_keyboard = False
                try:
                    self.grabMouse()
                    grabbed_mouse = True
                except Exception:
                    pass
                try:
                    self.grabKeyboard()
                    grabbed_keyboard = True
                except Exception:
                    pass
                self._input_grab_active = grabbed_mouse or grabbed_keyboard
            else:
                # On non-KDE Wayland: activate for visibility
                self.activateWindow()
                self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

        self.is_visible = True

    def reapply_settings(self):
        logger.debug("Popup: Re-applying settings and triggering font recalibration.")
        self._apply_frame_stylesheet()
        self._apply_scrollbar_theme()
        
        # Update probe label font
        self.probe_label.setStyleSheet(f"font-family: \"{config.font_family}\";")

        # By setting is_calibrated to False, the main loop will automatically
        # run _calibrate_empirically() again with the new font settings.
        self.is_calibrated = False
        
        footer_parts = []
        if config.show_keyboard_shortcuts:
            footer_parts.append(
                f'<a href="anki" style="color: cyan; text-decoration: none;">[Add to Anki - {config.shortcut_add_to_anki}]</a>'
            )
            footer_parts.append(
                f'<a href="copy" style="color: cyan; text-decoration: none;">[Copy Text - {config.shortcut_copy_text}]</a>'
            )

        if IS_WAYLAND:
            if not config.show_keyboard_shortcuts:
                footer_parts.append(
                    '<a href="anki" style="color: cyan; text-decoration: none;">[Add to Anki]</a>'
                )
            footer_parts.append(
                '<a href="entry_prev" style="color: cyan; text-decoration: none;">[Prev Entry]</a>'
            )
            footer_parts.append(
                '<a href="entry_next" style="color: cyan; text-decoration: none;">[Next Entry]</a>'
            )
            footer_parts.append(
                '<span style="color: #8aa2b8;">[Keys: ←/→, A, C, Esc]</span>'
            )

        if footer_parts:
            self.footer_label.setText('<div style="text-align: center;">' + ' &nbsp; '.join(footer_parts) + '</div>')
            self.footer_label.show()
        else:
            self.footer_label.hide()


    def _store_active_window_on_mac(self):
        """Store the currently active window for focus restoration (macOS only)."""
        if not IS_MACOS or not Quartz:
            return

        try:
            # Get the currently active application
            active_app = Quartz.NSWorkspace.sharedWorkspace().frontmostApplication()
            if active_app:
                # Store the application reference instead of trying to get the window
                # We'll use the application to restore focus later
                self._previous_active_window_on_mac = active_app
        except Exception as e:
            logger.warning(f"Failed to store active window: {e}")
            self._previous_active_window_on_mac = None

    def _restore_focus_on_mac(self):
        """Restore focus to the previously active application (macOS only)."""
        if not IS_MACOS or not Quartz or not self._previous_active_window_on_mac:
            return

        try:
            # Activate the previously active application
            self._previous_active_window_on_mac.activateWithOptions_(Quartz.NSApplicationActivateAllWindows)
        except Exception as e:
            logger.warning(f"Failed to restore focus: {e}")
        finally:
            # Clear the stored application reference
            self._previous_active_window_on_mac = None
