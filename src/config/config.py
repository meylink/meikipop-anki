# src/config/config.py
import configparser
import logging
import os
import sys
import json

logger = logging.getLogger(__name__)

APP_NAME = "meikipop-anki"
APP_VERSION = "v.1.5.6"
MAX_DICT_ENTRIES = 10
IS_LINUX = sys.platform.startswith('linux')
IS_WINDOWS = sys.platform.startswith('win')
IS_MACOS = sys.platform.startswith('darwin')
IS_X11 = IS_LINUX and os.environ.get('XDG_SESSION_TYPE', '').lower() == 'x11'
IS_WAYLAND = IS_LINUX and os.environ.get('XDG_SESSION_TYPE', '').lower() == 'wayland'
_XDG_DESKTOP = os.environ.get('XDG_CURRENT_DESKTOP', '').upper()
IS_KDE = IS_LINUX and ('KDE' in _XDG_DESKTOP or os.environ.get('KDE_FULL_SESSION', '').lower() == 'true')

# Under Wayland we run Qt via xcb for more predictable window positioning.
if IS_WAYLAND:
    os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')

class Config:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            self._load()
            self._initialized = True


    def _load(self):
        config = configparser.ConfigParser()

        # Step 1: Set hardcoded defaults
        defaults = {
            'Settings': {
                'hotkey': 'shift',
                'scan_region': '0',
                'max_lookup_length': '25',
                'quality_mode': 'balanced',
                'ocr_provider': 'Google Lens',
                'auto_scan_mode': 'true',
                'auto_scan_mode_lookups_without_hotkey': 'true',
                'auto_scan_interval_seconds': '1.0',
                'auto_scan_on_mouse_move': 'false',
                'magpie_compatibility': 'false'
            },
            'Theme': {
                'theme_name': 'Nazeka',
                'font_family': 'Noto Sans JP',
                'font_size_definitions': '14',
                'font_size_header': '18',
                'compact_mode': 'false',
                'show_deconjugation': 'false',
                'show_pos': 'false',
                'show_tags': 'false',
                'show_frequency': 'true',
                'show_pitch_accent': 'true',
                'color_background': '#2E2E2E',
                'color_foreground': '#F0F0F0',
                'color_highlight_word': '#88D8FF',
                'color_highlight_reading': '#90EE90',
                'color_definitions': '#D0D0D0',
                'background_opacity': '245',
                'background_opacity': '245',
                'background_opacity': '245',
                'popup_position_mode': 'flip_vertically',
                'max_width': '500',
                'max_height': '400',
                'show_keyboard_shortcuts': 'false',
                'prevent_background_scroll': 'false'
            },
            'Anki': {
                'deck_name': 'Default',
                'model_name': 'Basic',
                'url': 'http://127.0.0.1:8765',
                'show_hover_status': 'true',
                'add_meikipop_tag': 'true',
                'add_document_title_tag': 'true',
                'enable_screenshot': 'false',
                'field_map': '{}',
                'duplicate_check_fields': 'Front,Word,Expression,Vocab,Kanji,Reading,Furigana,Writing,Term,Vocabulary',
                'sentence_truncation_delimiters': '。,！,？,（,）',
                'sentence_truncation_delimiters_remove': '「,」'
            },
            'Yomitan': {
                'enabled': 'true',
                'api_url': 'http://127.0.0.1:19633'
            },
            'Shortcuts': {
                'add_to_anki': 'Alt+A',
                'copy_text': 'Alt+C'
            }
        }
        config.read_dict(defaults)

        # Step 2: Load from config.ini, creating it if it doesn't exist
        try:
            if not config.read('config.ini', encoding='utf-8'):
                with open('config.ini', 'w', encoding='utf-8') as configfile:
                    config.write(configfile)
                logger.info("config.ini not found, created with default settings.")
            else:
                logger.info("Loaded settings from config.ini.")
        except configparser.Error as e:
            logger.warning(f"Warning: Could not parse config.ini. Using defaults. Error: {e}")

        # Apply settings from the config object first
        self.hotkey = config.get('Settings', 'hotkey')
        self.scan_region = config.get('Settings', 'scan_region')
        self.max_lookup_length = config.getint('Settings', 'max_lookup_length')
        self.quality_mode = config.get('Settings', 'quality_mode')
        self.ocr_provider = config.get('Settings', 'ocr_provider')
        self.auto_scan_mode = config.getboolean('Settings', 'auto_scan_mode')
        self.auto_scan_mode_lookups_without_hotkey = config.getboolean('Settings',
                                                                       'auto_scan_mode_lookups_without_hotkey')
        self.auto_scan_interval_seconds = config.getfloat('Settings', 'auto_scan_interval_seconds')
        self.auto_scan_on_mouse_move = config.getboolean('Settings', 'auto_scan_on_mouse_move', fallback=False)
        self.magpie_compatibility = config.getboolean('Settings', 'magpie_compatibility')

        self.theme_name = config.get('Theme', 'theme_name')
        self.font_family = config.get('Theme', 'font_family')
        self.font_size_definitions = config.getint('Theme', 'font_size_definitions')
        self.font_size_header = config.getint('Theme', 'font_size_header')
        self.compact_mode = config.getboolean('Theme', 'compact_mode')
        self.show_deconjugation = config.getboolean('Theme', 'show_deconjugation')
        self.show_deconjugation_below = config.getboolean('Theme', 'show_deconjugation_below', fallback=False)
        self.show_pos = config.getboolean('Theme', 'show_pos')
        self.show_tags = config.getboolean('Theme', 'show_tags')
        self.show_frequency = config.getboolean('Theme', 'show_frequency', fallback=False)
        self.show_pitch_accent = config.getboolean('Theme', 'show_pitch_accent', fallback=True)
        self.color_background = config.get('Theme', 'color_background')
        self.color_foreground = config.get('Theme', 'color_foreground')
        self.color_highlight_word = config.get('Theme', 'color_highlight_word')
        self.color_highlight_reading = config.get('Theme', 'color_highlight_reading')
        self.color_definitions = config.get('Theme', 'color_definitions', fallback='#D0D0D0')
        self.background_opacity = config.getint('Theme', 'background_opacity')
        self.background_opacity = config.getint('Theme', 'background_opacity')
        self.popup_position_mode = config.get('Theme', 'popup_position_mode')
        self.max_width = config.getint('Theme', 'max_width', fallback=500)
        self.max_height = config.getint('Theme', 'max_height', fallback=400)
        self.show_keyboard_shortcuts = config.getboolean('Theme', 'show_keyboard_shortcuts', fallback=True)
        self.prevent_background_scroll = config.getboolean('Theme', 'prevent_background_scroll', fallback=True)

        self.anki_deck_name = config.get('Anki', 'deck_name', fallback='Default')
        self.anki_model_name = config.get('Anki', 'model_name', fallback='Basic')
        self.anki_url = config.get('Anki', 'url', fallback='http://127.0.0.1:8765')
        self.anki_show_hover_status = config.getboolean('Anki', 'show_hover_status', fallback=False)
        self.anki_add_meikipop_tag = config.getboolean('Anki', 'add_meikipop_tag', fallback=True)
        self.anki_add_document_title_tag = config.getboolean('Anki', 'add_document_title_tag', fallback=True)
        self.anki_enable_screenshot = config.getboolean('Anki', 'enable_screenshot', fallback=True)
        
        try:
            self.anki_field_map = json.loads(config.get('Anki', 'field_map', fallback='{}'))
        except json.JSONDecodeError:
            self.anki_field_map = {}
        
        # Configurable field names to search for duplicates (comma-separated)
        dup_fields_str = config.get('Anki', 'duplicate_check_fields', fallback='Front,Word,Expression,Vocab,Kanji,Reading,Furigana,Writing,Term,Vocabulary')
        self.anki_duplicate_check_fields = [f.strip() for f in dup_fields_str.split(',') if f.strip()]

        # Configurable delimiters for sentence truncation
        # Stored as comma-separated string, parsed into list
        trunc_delims_str = config.get('Anki', 'sentence_truncation_delimiters', fallback='。')
        self.anki_sentence_delimiters = [d.strip() for d in trunc_delims_str.split(',') if d.strip()]

        # Delimiters that should be REMOVED from the result string when truncating
        trunc_delims_rem_str = config.get('Anki', 'sentence_truncation_delimiters_remove', fallback='')
        self.anki_sentence_delimiters_remove = [d.strip('\'"') for d in trunc_delims_rem_str.split(',') if d.strip()]

        self.yomitan_enabled = config.getboolean('Yomitan', 'enabled', fallback=False)
        self.yomitan_api_url = config.get('Yomitan', 'api_url', fallback='http://127.0.0.1:19633')
        
        self.shortcut_add_to_anki = config.get('Shortcuts', 'add_to_anki', fallback='Alt+A')
        self.shortcut_copy_text = config.get('Shortcuts', 'copy_text', fallback='Alt+C')

        self.is_enabled = True

        # todo command line args parsing

    def save(self):
        config = configparser.ConfigParser()
        config['Settings'] = {
            'hotkey': self.hotkey,
            'scan_region': self.scan_region,
            'max_lookup_length': str(self.max_lookup_length),
            'quality_mode': self.quality_mode,
            'ocr_provider': self.ocr_provider,
            'auto_scan_mode': str(self.auto_scan_mode).lower(),
            'auto_scan_mode_lookups_without_hotkey': str(self.auto_scan_mode_lookups_without_hotkey).lower(),
            'auto_scan_interval_seconds': str(self.auto_scan_interval_seconds),
            'auto_scan_on_mouse_move': str(self.auto_scan_on_mouse_move).lower(),
            'magpie_compatibility': str(self.magpie_compatibility).lower()
        }
        config['Theme'] = {
            'theme_name': self.theme_name,
            'font_family': self.font_family,
            'font_size_definitions': str(self.font_size_definitions),
            'font_size_header': str(self.font_size_header),
            'compact_mode': str(self.compact_mode).lower(),
            'show_deconjugation': str(self.show_deconjugation).lower(),
            'show_deconjugation_below': str(self.show_deconjugation_below).lower(),
            'show_pos': str(self.show_pos).lower(),
            'show_tags': str(self.show_tags).lower(),
            'show_frequency': str(self.show_frequency).lower(),
            'show_pitch_accent': str(self.show_pitch_accent).lower(),
            'color_background': self.color_background,
            'color_foreground': self.color_foreground,
            'color_highlight_word': self.color_highlight_word,
            'color_highlight_reading': self.color_highlight_reading,
            'color_definitions': self.color_definitions,
            'background_opacity': str(self.background_opacity),
            'popup_position_mode': self.popup_position_mode,
            'max_width': str(self.max_width),
            'max_height': str(self.max_height),
            'show_keyboard_shortcuts': str(self.show_keyboard_shortcuts).lower(),
            'prevent_background_scroll': str(self.prevent_background_scroll).lower()
        }
        config['Anki'] = {
            'deck_name': self.anki_deck_name,
            'model_name': self.anki_model_name,
            'url': self.anki_url,
            'show_hover_status': str(self.anki_show_hover_status).lower(),
            'add_meikipop_tag': str(self.anki_add_meikipop_tag).lower(),
            'add_document_title_tag': str(self.anki_add_document_title_tag).lower(),
            'enable_screenshot': str(self.anki_enable_screenshot).lower(),
            'field_map': json.dumps(self.anki_field_map),
            'duplicate_check_fields': ','.join(self.anki_duplicate_check_fields),
            'sentence_truncation_delimiters': ','.join(self.anki_sentence_delimiters),
            'sentence_truncation_delimiters_remove': ','.join(self.anki_sentence_delimiters_remove)
        }
        config['Yomitan'] = {
            'enabled': str(self.yomitan_enabled).lower(),
            'api_url': self.yomitan_api_url
        }
        config['Shortcuts'] = {
            'add_to_anki': self.shortcut_add_to_anki,
            'copy_text': self.shortcut_copy_text
        }
        with open('config.ini', 'w', encoding='utf-8') as configfile:
            config.write(configfile)
        logger.info("Settings saved to config.ini.")

# The singleton instance
config = Config()