# src/gui/settings_dialog.py
import logging
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QKeySequence
from PyQt6.QtWidgets import (QWidget, QDialog, QFormLayout, QComboBox,
                             QSpinBox, QCheckBox, QPushButton, QColorDialog, QVBoxLayout, QHBoxLayout,
                             QGroupBox, QDialogButtonBox, QLabel, QSlider, QLineEdit, QDoubleSpinBox, QTabWidget,
                             QKeySequenceEdit)

from src.config.config import config, APP_NAME, IS_WINDOWS, IS_WAYLAND
from src.gui.input import InputLoop
from src.gui.popup import Popup
from src.dictionary.anki_client import AnkiClient
from src.ocr.ocr import OcrProcessor

AVAILABLE_SOURCES = [
    "",
    "{audio}",
    "{cloze-body}",
    "{cloze-prefix}",
    "{cloze-suffix}",
    "{document-title}",
    "{expression}",
    "{frequencies}",
    "{frequency-average-rank}",
    "{frequency-harmonic-rank}",
    "{furigana-plain}",
    "{glossary}",
    "{glossary-brief}",
    "{glossary-first}",
    "{glossary-1st-dict}",
    "{picture}",
    "{pitch-accent-categories}",
    "{pitch-accent-graphs}",
    "{pitch-accent-positions}",
    "{reading}",
    "{sentence}",
    "{tags}"
]

THEMES = {
    "Nazeka": {
        "color_background": "#2E2E2E", "color_foreground": "#F0F0F0",
        "color_highlight_word": "#88D8FF", "color_highlight_reading": "#90EE90",
        "color_definitions": "#d4d4d4",
        "background_opacity": 245,
    },
    "Celestial Indigo": {
        "color_background": "#281E50", "color_foreground": "#EAEFF5",
        "color_highlight_word": "#D4C58A", "color_highlight_reading": "#c3afe5",
        "color_definitions": "#E0DDE8",
        "background_opacity": 245,
    },
    "Neutral Slate": {
        "color_background": "#5D5C5B", "color_foreground": "#EFEBE8",
        "color_highlight_word": "#b3d4b3", "color_highlight_reading": "#b3d4b3",
        "color_definitions": "#dedede",
        "background_opacity": 245,
    },
    "Academic": {
        "color_background": "#FDFBF7", "color_foreground": "#212121",
        "color_highlight_word": "#8C2121", "color_highlight_reading": "#005A9C",
        "color_definitions": "#585858",
        "background_opacity": 245,
    },
    "Custom": {}

}

logger = logging.getLogger(__name__)


class ShortcutEdit(QLineEdit):
    """Custom line edit that captures both keyboard shortcuts and mouse buttons."""
    
    def __init__(self, initial_value="", parent=None):
        super().__init__(initial_value, parent)
        self.setPlaceholderText("Click here, then press key or mouse button")
        self._capturing = False
        self._captured_non_modifier = False
    
    def focusInEvent(self, event):
        super().focusInEvent(event)
        self._capturing = True
        self._captured_non_modifier = False
        self.setStyleSheet("background-color: #ffffcc;")  # Highlight when capturing
    
    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self._capturing = False
        self.setStyleSheet("")
    
    def keyPressEvent(self, event):
        if not self._capturing:
            super().keyPressEvent(event)
            return
        
        # Build key sequence string
        modifiers = event.modifiers()
        key = event.key()
        
        # Ignore lone modifier keys
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
            return

        self._captured_non_modifier = True
        
        parts = []
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            parts.append("Ctrl")
        if modifiers & Qt.KeyboardModifier.AltModifier:
            parts.append("Alt")
        if modifiers & Qt.KeyboardModifier.ShiftModifier:
            parts.append("Shift")
        if modifiers & Qt.KeyboardModifier.MetaModifier:
            parts.append("Meta")
        
        # Get key name
        key_seq = QKeySequence(key)
        key_str = key_seq.toString()
        if key_str:
            parts.append(key_str)
        
        if parts:
            self.setText("+".join(parts))
            self.clearFocus()

    def keyReleaseEvent(self, event):
        if not self._capturing:
            super().keyReleaseEvent(event)
            return

        # Allow binding lone modifiers by pressing and releasing them.
        if not self._captured_non_modifier:
            key = event.key()
            if key == Qt.Key.Key_Control:
                self.setText("Ctrl")
                self.clearFocus()
                return
            if key == Qt.Key.Key_Shift:
                self.setText("Shift")
                self.clearFocus()
                return
            if key == Qt.Key.Key_Alt:
                self.setText("Alt")
                self.clearFocus()
                return
            if key == Qt.Key.Key_Meta:
                self.setText("Meta")
                self.clearFocus()
                return

        super().keyReleaseEvent(event)
    
    def mousePressEvent(self, event):
        if not self._capturing:
            super().mousePressEvent(event)
            return
        
        button = event.button()
        
        # Map Qt mouse buttons to our naming convention
        if button == Qt.MouseButton.MiddleButton:
            self.setText("Mouse3")
            self.clearFocus()
        elif button == Qt.MouseButton.BackButton:
            self.setText("Mouse4")
            self.clearFocus()
        elif button == Qt.MouseButton.ForwardButton:
            self.setText("Mouse5")
            self.clearFocus()
        else:
            # Left/right click should focus the field, not set it
            super().mousePressEvent(event)


class SettingsDialog(QDialog):
    def __init__(self, ocr_processor: OcrProcessor, popup_window: Popup, input_loop: InputLoop, tray_icon, parent=None):
        super().__init__(parent)
        self.ocr_processor = ocr_processor
        self.popup_window = popup_window
        self.input_loop = input_loop
        self.tray_icon = tray_icon


        # Backup original settings for revert on cancel
        self.original_settings = self._backup_settings()

        self.anki_client = AnkiClient(config.anki_url)
        self.field_map_widgets = {}

        self.setWindowTitle(f"{APP_NAME} Settings")
        self.setWindowIcon(QIcon("icon.ico"))
        self.resize(500, 600)

        main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # --- General Tab ---
        self.general_tab = QWidget()
        self.general_layout = QFormLayout(self.general_tab)
        
        self.hotkey_combo = QComboBox()
        self.hotkey_combo.addItems(['shift', 'ctrl', 'alt'])
        self.hotkey_combo.setCurrentText(config.hotkey)
        self.hotkey_combo.currentTextChanged.connect(self.preview_settings)
        self.general_layout.addRow("Hotkey:", self.hotkey_combo)
        
        self.ocr_provider_combo = QComboBox()
        self.ocr_provider_combo.addItems(self.ocr_processor.available_providers.keys())
        self.ocr_provider_combo.setCurrentText(config.ocr_provider)
        self.ocr_provider_combo.currentTextChanged.connect(self.preview_settings)
        self.general_layout.addRow("OCR Provider:", self.ocr_provider_combo)
        
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(['fast', 'balanced', 'quality'])
        self.quality_combo.setCurrentText(config.quality_mode)
        self.quality_combo.currentTextChanged.connect(self.preview_settings)
        self.general_layout.addRow("Quality Mode:", self.quality_combo)
        
        self.max_lookup_spin = QSpinBox()
        self.max_lookup_spin.setRange(5, 100)
        self.max_lookup_spin.setValue(config.max_lookup_length)
        self.max_lookup_spin.valueChanged.connect(self.preview_settings)
        self.general_layout.addRow("Max Lookup Length:", self.max_lookup_spin)
        
        self.auto_scan_check = QCheckBox()
        self.auto_scan_check.setChecked(config.auto_scan_mode)
        self.auto_scan_check.toggled.connect(self.preview_settings)
        self.general_layout.addRow("Auto Scan Mode:", self.auto_scan_check)
        
        self.auto_scan_interval_spin = QDoubleSpinBox()
        self.auto_scan_interval_spin.setRange(0.0, 60.0)
        self.auto_scan_interval_spin.setDecimals(1)
        self.auto_scan_interval_spin.setSingleStep(0.1)
        self.auto_scan_interval_spin.setValue(config.auto_scan_interval_seconds)
        self.auto_scan_interval_spin.setSuffix(" s")
        self.auto_scan_interval_spin.valueChanged.connect(self.preview_settings)
        self.general_layout.addRow("Auto Scan Interval:", self.auto_scan_interval_spin)

        self.auto_scan_mouse_move_check = QCheckBox()
        self.auto_scan_mouse_move_check.setChecked(getattr(config, 'auto_scan_on_mouse_move', False))
        self.auto_scan_mouse_move_check.setToolTip("Pause auto scanning while the mouse is stationary.")
        self.auto_scan_mouse_move_check.toggled.connect(self.preview_settings)
        self.general_layout.addRow("Only Scan on Mouse Move:", self.auto_scan_mouse_move_check)
        
        self.auto_scan_no_hotkey_check = QCheckBox()
        self.auto_scan_no_hotkey_check.setChecked(config.auto_scan_mode_lookups_without_hotkey)
        self.auto_scan_no_hotkey_check.toggled.connect(self.preview_settings)
        self.general_layout.addRow("Lookups without Hotkey (in Auto Scan):", self.auto_scan_no_hotkey_check)
        
        if IS_WINDOWS:
            self.magpie_check = QCheckBox()
            self.magpie_check.setChecked(config.magpie_compatibility)
            self.magpie_check.setToolTip("Enable transformations for compatibility with Magpie game scaler.")
            self.magpie_check.toggled.connect(self.preview_settings)
            self.general_layout.addRow("Magpie Compatibility:", self.magpie_check)
            
        self.tabs.addTab(self.general_tab, "General")


        # --- Shortcuts Tab ---
        self.shortcuts_tab = QWidget()
        self.shortcuts_layout = QFormLayout(self.shortcuts_tab)
        
        # Add help label for mouse buttons
        help_label = QLabel("Click a field, then press any key or mouse button to set it")
        help_label.setStyleSheet("color: gray; font-size: 11px;")
        self.shortcuts_layout.addRow(help_label)

        if IS_WAYLAND:
            wayland_hint = QLabel("Wayland: global keyboard shortcuts are limited to Shift/Ctrl/Alt. "
                                  "Press and release Shift/Ctrl/Alt to bind a single modifier.")
            wayland_hint.setWordWrap(True)
            wayland_hint.setStyleSheet("color: #b35a00; font-size: 11px;")
            self.shortcuts_layout.addRow(wayland_hint)
        
        self.shortcut_widgets = {}
        
        def add_shortcut_row(label, config_key, default_val):
            val = getattr(config, config_key, default_val)
            shortcut_edit = ShortcutEdit(val)
            shortcut_edit.textChanged.connect(self.preview_settings)
            self.shortcuts_layout.addRow(label, shortcut_edit)
            self.shortcut_widgets[config_key] = shortcut_edit

        add_shortcut_row("Add to Anki:", "shortcut_add_to_anki", "Alt+A")
        add_shortcut_row("Copy Sentence:", "shortcut_copy_text", "Alt+C")

        self.tabs.addTab(self.shortcuts_tab, "Shortcuts")


        # --- Popup Tab ---
        self.popup_tab = QWidget()
        self.popup_layout = QFormLayout(self.popup_tab)
        
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(THEMES.keys())
        self.theme_combo.setCurrentText(config.theme_name if config.theme_name in THEMES else "Custom")
        self.theme_combo.currentTextChanged.connect(self._apply_theme) 
        # _apply_theme calls reapply_settings internally, detailed below
        self.popup_layout.addRow("Theme:", self.theme_combo)
        
        self.opacity_slider_container = QWidget()
        opacity_layout = QHBoxLayout(self.opacity_slider_container)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(50, 255)
        self.opacity_slider.setValue(config.background_opacity)
        self.opacity_label = QLabel(f"{config.background_opacity}")
        self.opacity_label.setMinimumWidth(30)
        self.opacity_slider.valueChanged.connect(lambda val: self.opacity_label.setText(str(val)))
        self.opacity_slider.valueChanged.connect(self._mark_as_custom)
        self.opacity_slider.valueChanged.connect(self.preview_settings)
        opacity_layout.addWidget(self.opacity_slider)
        opacity_layout.addWidget(self.opacity_label)
        self.popup_layout.addRow("Background Opacity:", self.opacity_slider_container)
        
        self.popup_layout.addRow(QLabel("Customize Colors:"))
        self.color_widgets = {}
        color_settings_map = {"Background": "color_background", "Foreground": "color_foreground",
                              "Highlight Word": "color_highlight_word", "Highlight Reading": "color_highlight_reading",
                              "Definitions": "color_definitions"}
        for name, key in color_settings_map.items():
            btn = QPushButton(getattr(config, key))
            btn.clicked.connect(lambda _, k=key, b=btn: self.pick_color(k, b))
            self.color_widgets[key] = btn
            self.popup_layout.addRow(f"  {name}:", btn)
            
        self.popup_layout.addRow(QLabel("Customize Layout:"))
        self.popup_position_combo = QComboBox()
        self.popup_position_combo.addItems(["Flip Both", "Flip Vertically", "Flip Horizontally", "Visual Novel Mode"])
        self.popup_mode_map = {
            "Flip Both": "flip_both",
            "Flip Vertically": "flip_vertically",
            "Flip Horizontally": "flip_horizontally",
            "Visual Novel Mode": "visual_novel_mode"
        }
        # Find the friendly name for the current config value to set the combo box
        current_friendly_name = next(
            (k for k, v in self.popup_mode_map.items() if v == config.popup_position_mode), "Flip Vertically"
        )
        self.popup_position_combo.setCurrentText(current_friendly_name)
        self.popup_position_combo.currentTextChanged.connect(self.preview_settings)
        self.popup_layout.addRow("  Popup Position Mode:", self.popup_position_combo)
        
        self.font_family_edit = QLineEdit(config.font_family)
        self.font_family_edit.textChanged.connect(self.preview_settings)
        self.popup_layout.addRow("  Font Family:", self.font_family_edit)
        
        self.font_size_header_spin = QSpinBox()
        self.font_size_header_spin.setRange(8, 72)
        self.font_size_header_spin.setValue(config.font_size_header)
        self.font_size_header_spin.valueChanged.connect(self.preview_settings)
        self.popup_layout.addRow("  Font Size (Header):", self.font_size_header_spin)
        
        self.font_size_def_spin = QSpinBox()
        self.font_size_def_spin.setRange(8, 72)
        self.font_size_def_spin.setValue(config.font_size_definitions)
        self.font_size_def_spin.valueChanged.connect(self.preview_settings)
        self.popup_layout.addRow("  Font Size (Definitions):", self.font_size_def_spin)
        
        self.compact_check = QCheckBox()
        self.compact_check.setChecked(config.compact_mode)
        self.compact_check.setToolTip("Removes line breaks between definitions.")
        self.compact_check.toggled.connect(self.preview_settings)
        self.popup_layout.addRow("  Compact Mode:", self.compact_check)
        
        self.show_deconj_check = QCheckBox()
        self.show_deconj_check.setChecked(config.show_deconjugation)
        self.show_deconj_check.toggled.connect(self.preview_settings)
        self.popup_layout.addRow("  Show Deconjugation:", self.show_deconj_check)
        
        self.show_pos_check = QCheckBox()
        self.show_pos_check.setChecked(config.show_pos)
        self.show_pos_check.toggled.connect(self.preview_settings)
        self.popup_layout.addRow("  Show Part of Speech:", self.show_pos_check)
        
        self.show_tags_check = QCheckBox()
        self.show_tags_check.setChecked(config.show_tags)
        self.show_tags_check.toggled.connect(self.preview_settings)
        self.popup_layout.addRow("  Show Tags:", self.show_tags_check)
        
        self.show_frequency_check = QCheckBox()
        self.show_frequency_check.setChecked(config.show_frequency)
        self.show_frequency_check.toggled.connect(self.preview_settings)
        self.popup_layout.addRow("  Show Frequency:", self.show_frequency_check)
        
        self.show_pitch_accent_check = QCheckBox()
        self.show_pitch_accent_check.setChecked(config.show_pitch_accent)
        self.show_pitch_accent_check.toggled.connect(self.preview_settings)
        self.popup_layout.addRow("  Show Pitch Accent:", self.show_pitch_accent_check)

        
        self.prevent_bg_scroll_check = QCheckBox()
        self.prevent_bg_scroll_check.setChecked(config.prevent_background_scroll)
        self.prevent_bg_scroll_check.setToolTip("Prevent scrolling in the background window when the popup is open.")
        self.prevent_bg_scroll_check.toggled.connect(self.preview_settings)
        self.popup_layout.addRow("  Prevent Background Scroll:", self.prevent_bg_scroll_check)

        self.tabs.addTab(self.popup_tab, "Popup")


        # --- Anki Tab ---
        # --- Anki Tab ---
        self.anki_tab = QWidget()
        self.anki_layout = QFormLayout(self.anki_tab)
        
        # Connection Row
        url_layout = QHBoxLayout()
        self.anki_url_edit = QLineEdit(config.anki_url)
        self.anki_url_edit.textChanged.connect(self.preview_settings)
        url_layout.addWidget(self.anki_url_edit)
        
        self.connect_btn = QPushButton("Refresh")
        self.connect_btn.clicked.connect(self.refresh_anki_data)
        url_layout.addWidget(self.connect_btn)
        
        self.anki_layout.addRow("Anki Connect URL:", url_layout)
        
        # Deck & Model Selection
        self.deck_combo = QComboBox()
        self.deck_combo.setEditable(True) # Allow typing if not connected
        self.deck_combo.setCurrentText(config.anki_deck_name)
        self.deck_combo.currentTextChanged.connect(self.preview_settings)
        self.anki_layout.addRow("Deck Name:", self.deck_combo)
        
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setCurrentText(config.anki_model_name)
        self.model_combo.currentTextChanged.connect(self.on_model_changed)
        self.model_combo.currentTextChanged.connect(self.preview_settings)
        self.anki_layout.addRow("Note Type:", self.model_combo)
        
        self.anki_hover_status_check = QCheckBox()
        self.anki_hover_status_check.setChecked(config.anki_show_hover_status)
        self.anki_hover_status_check.setToolTip("Show a small indicator when hovering if the word is already in your Anki deck.")
        self.anki_hover_status_check.toggled.connect(self.preview_settings)
        self.anki_layout.addRow("Prevent Duplicates:", self.anki_hover_status_check)
        
        self.anki_screenshot_check = QCheckBox()
        self.anki_screenshot_check.setChecked(config.anki_enable_screenshot)
        self.anki_screenshot_check.setToolTip("Enable the screenshot snipping tool when adding cards.")
        self.anki_screenshot_check.toggled.connect(self.preview_settings)
        self.anki_layout.addRow("Enable Screenshot:", self.anki_screenshot_check)
        
        # Field Mapping Section
        self.mapping_group = QGroupBox("Field Mapping")
        self.mapping_layout = QFormLayout(self.mapping_group)
        self.anki_layout.addRow(self.mapping_group)
        
        # Initial Population if possible, otherwise rely on manual refresh
        # We don't auto-connect on init to prevent freezing if Anki is down.
        # But we do need to populate fields if we have a map? 
        # For now, user presses Connect.
        
        self.tabs.addTab(self.anki_tab, "Anki")
        
        # Connect tab change signal to handle auto-refresh of Anki data
        self.tabs.currentChanged.connect(self._handle_tab_change)
        self.anki_data_fetched = False


        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save_and_accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)
        self._update_color_buttons()

    def _handle_tab_change(self, index):
        """Called when the active tab changes."""
        if self.tabs.widget(index) == self.anki_tab:
            if not self.anki_data_fetched:
                # User switched to Anki tab for the first time this session: Auto-Connect
                self.refresh_anki_data()
                self.anki_data_fetched = True

    def showEvent(self, event):
        """Reset fetch state when dialog opens."""
        # We want to re-fetch if the user opens the dialog again, 
        # just in case they opened Anki in the meantime.
        self.anki_data_fetched = False
        
        # If the dialog opens directly to the Anki tab (e.g. remembered state?), fetch immediately.
        if self.tabs.currentWidget() == self.anki_tab:
             self.refresh_anki_data()
             self.anki_data_fetched = True
             
        super().showEvent(event)

    def _backup_settings(self):
        """Capture a snapshot of the current config state."""
        return {
            'hotkey': config.hotkey,
            'ocr_provider': config.ocr_provider,
            'quality_mode': config.quality_mode,
            'max_lookup_length': config.max_lookup_length,
            'auto_scan_mode': config.auto_scan_mode,
            'auto_scan_interval_seconds': config.auto_scan_interval_seconds,
            'auto_scan_mode_lookups_without_hotkey': config.auto_scan_mode_lookups_without_hotkey,
            'auto_scan_on_mouse_move': getattr(config, 'auto_scan_on_mouse_move', False),
            'magpie_compatibility': getattr(config, 'magpie_compatibility', False),
            'theme_name': config.theme_name,
            'background_opacity': config.background_opacity,
            'color_background': config.color_background,
            'color_foreground': config.color_foreground,
            'color_highlight_word': config.color_highlight_word,
            'color_highlight_reading': config.color_highlight_reading,
            'color_definitions': config.color_definitions,
            'popup_position_mode': config.popup_position_mode,
            'font_family': config.font_family,
            'font_size_header': config.font_size_header,
            'font_size_definitions': config.font_size_definitions,
            'compact_mode': config.compact_mode,
            'show_deconjugation': config.show_deconjugation,
            'show_pos': config.show_pos,
            'show_tags': config.show_tags,
            'show_frequency': config.show_frequency,
            'show_pitch_accent': config.show_pitch_accent,
            'show_keyboard_shortcuts': config.show_keyboard_shortcuts,
            'prevent_background_scroll': config.prevent_background_scroll,
            'anki_url': config.anki_url,
            'anki_deck_name': config.anki_deck_name,
            'anki_model_name': config.anki_model_name,
            'anki_show_hover_status': config.anki_show_hover_status,
            'anki_field_map': config.anki_field_map.copy(),
        }

    def _restore_settings(self):
        """Restore config state from backup."""
        for key, value in self.original_settings.items():
            setattr(config, key, value)
        
        # Tell live components to re-apply the restored settings
        self.input_loop.reapply_settings()
        self.popup_window.reapply_settings()
        self.tray_icon.reapply_settings()

    def reject(self):
        """On cancel, revert settings and close."""
        self._restore_settings()
        super().reject()

    def _mark_as_custom(self):
        if self.theme_combo.currentText() != "Custom":
            self.theme_combo.setCurrentText("Custom")

    def _apply_theme(self, theme_name):
        if theme_name in THEMES and theme_name != "Custom":
            # Block signals to prevent feedback loop from _mark_as_custom
            self.opacity_slider.blockSignals(True)
            self.theme_combo.blockSignals(True)
            try:
                theme_data = THEMES[theme_name]
                for key, value in theme_data.items():
                    setattr(config, key, value)
                self._update_color_buttons()
                self.opacity_slider.setValue(config.background_opacity)
                self.popup_window.reapply_settings()
                # We implicitly preview here because we set config and called reapply properties
            finally:
                self.opacity_slider.blockSignals(False)
                self.theme_combo.blockSignals(False)
        self.preview_settings()

    def _update_color_buttons(self):
        for key, btn in self.color_widgets.items():
            color_hex = getattr(config, key)
            btn.setText(color_hex)
            q_color = QColor(color_hex)
            text_color = "#000000" if q_color.lightness() > 127 else "#FFFFFF"
            btn.setStyleSheet(f"background-color: {color_hex}; color: {text_color};")

    def pick_color(self, key, btn):
        color = QColorDialog.getColor(QColor(getattr(config, key)), self)
        if color.isValid():
            setattr(config, key, color.name())
            self._update_color_buttons()
            self._mark_as_custom()
            self.preview_settings() # Trigger preview on color change

    def refresh_anki_data(self):
        """Fetch Decks and Models from Anki."""
        # Update client URL first
        self.anki_client.api_url = self.anki_url_edit.text()
        
        try:
            decks = self.anki_client.get_deck_names()
            models = self.anki_client.get_model_names()
            
            # Update Combos
            current_deck = self.deck_combo.currentText()
            self.deck_combo.clear()
            self.deck_combo.addItems(decks)
            self.deck_combo.setCurrentText(current_deck)
            
            current_model = self.model_combo.currentText()
            self.model_combo.clear()
            self.model_combo.addItems(models)
            self.model_combo.setCurrentText(current_model)
            
            # Since model might have changed/reset, trigger fields update
            self.on_model_changed(self.model_combo.currentText())
            
        except Exception as e:
            # Maybe show status label?
            logger.error(f"Failed to connect to Anki: {e}")

    def on_model_changed(self, model_name):
        """Fetch fields for the selected model and rebuild mapping UI."""
        # Clear existing
        while self.mapping_layout.rowCount() > 0:
            self.mapping_layout.removeRow(0)
        self.field_map_widgets.clear()
        
        if not model_name:
            return
            
        try:
            current_map = config.anki_field_map
            fields = self.anki_client.get_model_field_names(model_name)
            for field in fields:
                combo = QComboBox()
                combo.setEditable(True)
                combo.addItems(AVAILABLE_SOURCES)
                
                # Restore mapping if exists
                if field in current_map:
                    combo.setCurrentText(current_map[field])
                
                # State tracking for template building
                # We need to store the user's typed text because QComboBox selection
                # replaces it immediately.
                combo.last_valid_template = combo.currentText()
                
                def sync_template(text, c=combo):
                    c.last_valid_template = text
                    
                combo.lineEdit().textEdited.connect(sync_template)
                
                # Connection for append logic
                combo.activated.connect(lambda index, c=combo: self.on_combo_insert(c, index))
                
                combo.currentTextChanged.connect(self.update_field_map_config)
                combo.currentTextChanged.connect(self.preview_settings)
                
                self.mapping_layout.addRow(f"{field}:", combo)
                self.field_map_widgets[field] = combo
        except Exception as e:
            logger.error(f"Failed to fetch fields: {e}")

    def on_combo_insert(self, combo: QComboBox, index: int):
        """
        Appends the selected item to the existing text instead of replacing it.
        """
        # The item text that was just selected (e.g. "{cloze-prefix}")
        token = combo.itemText(index)
        
        # The text BEFORE the selection replaced it (tracked via textEdited)
        # Default to empty if not set
        prev_text = getattr(combo, 'last_valid_template', "")
        
        # Append the new token
        # If the box was empty or just contained the token (initial state), 
        # checking if prev_text == token might be useful but "append" is safer standard behavior
        # for a template builder.
        
        # Check if we are just setting it initially (prev_text is empty)
        if not prev_text:
            new_text = token
        else:
            new_text = prev_text + token
            
        # Update the combo text programmatically
        combo.setCurrentText(new_text)
        
        # Update valid template tracker so subsequent adds work
        combo.last_valid_template = new_text
        
        # Move cursor to end
        combo.lineEdit().setCursorPosition(len(new_text))

    def update_field_map_config(self, text):
        """Update the config dictionary based on UI state."""
        new_map = {}
        for field, combo in self.field_map_widgets.items():
            val = combo.currentText()
            if val: # Only save if not empty
                new_map[field] = val
        config.anki_field_map = new_map

    def preview_settings(self, *args):
        """Read UI state, update config object (in memory), and refresh live components."""
        # Update OCR Provider
        selected_provider = self.ocr_provider_combo.currentText()
        if selected_provider != config.ocr_provider:
            self.ocr_processor.switch_provider(selected_provider)
        config.ocr_provider = selected_provider

        # Update all other config values from widgets
        config.hotkey = self.hotkey_combo.currentText()
        config.quality_mode = self.quality_combo.currentText()
        config.max_lookup_length = self.max_lookup_spin.value()
        config.auto_scan_mode = self.auto_scan_check.isChecked()
        config.auto_scan_interval_seconds = self.auto_scan_interval_spin.value()
        config.auto_scan_mode_lookups_without_hotkey = self.auto_scan_no_hotkey_check.isChecked()
        config.auto_scan_on_mouse_move = self.auto_scan_mouse_move_check.isChecked()
        if IS_WINDOWS:
            config.magpie_compatibility = self.magpie_check.isChecked()
        config.compact_mode = self.compact_check.isChecked()
        config.show_deconjugation = self.show_deconj_check.isChecked()
        config.show_pos = self.show_pos_check.isChecked()
        config.show_tags = self.show_tags_check.isChecked()
        config.show_frequency = self.show_frequency_check.isChecked()
        config.show_pitch_accent = self.show_pitch_accent_check.isChecked()
        config.anki_show_hover_status = self.anki_hover_status_check.isChecked()

        config.prevent_background_scroll = self.prevent_bg_scroll_check.isChecked()
        selected_friendly_name = self.popup_position_combo.currentText()
        config.popup_position_mode = self.popup_mode_map.get(selected_friendly_name, "flip_vertically")
        
        config.theme_name = self.theme_combo.currentText()
        config.background_opacity = self.opacity_slider.value()
        config.font_family = self.font_family_edit.text()
        config.font_size_header = self.font_size_header_spin.value()
        config.font_size_definitions = self.font_size_def_spin.value()
        
        config.anki_url = self.anki_url_edit.text()
        config.anki_deck_name = self.deck_combo.currentText()
        config.anki_model_name = self.model_combo.currentText()
        config.anki_show_hover_status = self.anki_hover_status_check.isChecked()
        config.anki_enable_screenshot = self.anki_screenshot_check.isChecked()
        # field map is updated live via update_field_map_config
        
        # Update Shortcuts
        for key, widget in self.shortcut_widgets.items():
            val = widget.text().strip()
            if IS_WAYLAND:
                val = self._normalize_wayland_shortcut(val)
                if val != widget.text().strip():
                    widget.blockSignals(True)
                    try:
                        widget.setText(val)
                    finally:
                        widget.blockSignals(False)
            if val:
                setattr(config, key, val)

        # Tell the live components to re-apply settings (Visual Preview)
        self.input_loop.reapply_settings()
        self.popup_window.reapply_settings()
        self.tray_icon.reapply_settings()
        self.ocr_processor.shared_state.screenshot_trigger_event.set()

    @staticmethod
    def _normalize_wayland_shortcut(shortcut: str) -> str:
        lower = shortcut.lower()
        if not lower:
            return shortcut

        # Mouse button shortcuts are supported as entered.
        if lower in {'mouse3', 'middlemouse', 'mouse4', 'mouse5', 'xbutton1', 'xbutton2'}:
            return shortcut

        # Supported single-modifier shortcuts.
        single_map = {
            'shift': 'Shift',
            'ctrl': 'Ctrl',
            'control': 'Ctrl',
            'alt': 'Alt',
        }
        if lower in single_map:
            return single_map[lower]

        # Unsupported combos are normalized to first supported modifier.
        if '+' in lower:
            for part in [p.strip() for p in lower.split('+') if p.strip()]:
                if part in single_map:
                    return single_map[part]

        return shortcut

    def save_and_accept(self):
        """Save config to disk and close."""
        self.preview_settings() # Ensure memory is up to date
        config.save() # Write to file
        self.accept()