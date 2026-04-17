# src/gui/input.py
import logging
import sys
import threading
import time

from pynput import mouse

from src.config.config import config, IS_LINUX, IS_MACOS, IS_WAYLAND

if IS_LINUX:
    from Xlib import display as xlib_display
    from Xlib.error import XError
    from Xlib import XK
elif IS_MACOS:
    import Quartz
    from AppKit import NSEvent
else:
    import keyboard


logger = logging.getLogger(__name__)

class LinuxX11KeyboardController:
    def __init__(self, hotkey_str):
        self.hotkey_str = hotkey_str.lower()
        try:
            self.display = xlib_display.Display()
            self._combo_cache = {}
            self._setup_keycodes()
        except (XError, Exception) as e:
            logger.critical("Could not connect to X server. Is DISPLAY environment variable set? Error: %s", e)
            logger.critical("Meikipop cannot run without a graphical session.")
            sys.exit(1)

    def _setup_keycodes(self):
        self.keycodes_to_check = set()
        modifier_map = {
            'shift': ['Shift_L', 'Shift_R'],
            'ctrl': ['Control_L', 'Control_R'],
            'alt': ['Alt_L', 'Alt_R']
        }
        target_keysyms = modifier_map.get(self.hotkey_str)
        if not target_keysyms:
            logger.critical(f"Unsupported hotkey '{self.hotkey_str}' for Linux/X11. Use 'shift', 'ctrl', or 'alt'.")
            sys.exit(1)
        for keysym_str in target_keysyms:
            keysym = XK.string_to_keysym(keysym_str)
            if keysym:
                keycode = self.display.keysym_to_keycode(keysym)
                if keycode:
                    self.keycodes_to_check.add(keycode)
        if not self.keycodes_to_check:
            logger.critical(f"Could not find keycodes for hotkey '{self.hotkey_str}'.")
            sys.exit(1)
    def is_hotkey_pressed(self) -> bool:
        try:
            key_map = self.display.query_keymap()
            for keycode in self.keycodes_to_check:
                if (key_map[keycode // 8] >> (keycode % 8)) & 1:
                    return True
            return False
        except XError:
            return False

    def is_key_pressed(self, key_str: str) -> bool:
        try:
            combo_parts = self._combo_cache.get(key_str)
            if combo_parts is None:
                combo_parts = self._parse_shortcut_to_keycode_sets(key_str)
                self._combo_cache[key_str] = combo_parts

            if not combo_parts:
                return False

            key_map = self.display.query_keymap()

            # Every part of the shortcut must be down (e.g. Ctrl + A).
            for part_keycodes in combo_parts:
                if not part_keycodes:
                    return False
                if not any((key_map[keycode // 8] >> (keycode % 8)) & 1 for keycode in part_keycodes):
                    return False
            return True
        except XError:
            return False
        except Exception:
            return False

    def _parse_shortcut_to_keycode_sets(self, key_str: str):
        parts = [p.strip().lower() for p in key_str.split('+') if p.strip()]
        if not parts:
            return []

        return [self._resolve_part_keycodes(part) for part in parts]

    def _resolve_part_keycodes(self, part: str):
        modifier_aliases = {
            'ctrl': ['Control_L', 'Control_R'],
            'control': ['Control_L', 'Control_R'],
            'shift': ['Shift_L', 'Shift_R'],
            'alt': ['Alt_L', 'Alt_R'],
            'meta': ['Meta_L', 'Meta_R', 'Super_L', 'Super_R'],
            'win': ['Super_L', 'Super_R'],
            'cmd': ['Super_L', 'Super_R'],
        }

        special_aliases = {
            'esc': ['Escape'],
            'del': ['Delete'],
            'ins': ['Insert'],
            'enter': ['Return'],
            'return': ['Return'],
            'space': ['space'],
            'tab': ['Tab'],
            'backspace': ['BackSpace'],
            'pgup': ['Prior'],
            'pageup': ['Prior'],
            'pgdown': ['Next'],
            'pagedown': ['Next'],
            'left': ['Left'],
            'right': ['Right'],
            'up': ['Up'],
            'down': ['Down'],
            'home': ['Home'],
            'end': ['End'],
        }

        keysyms = []
        if part in modifier_aliases:
            keysyms.extend(modifier_aliases[part])
        elif part in special_aliases:
            keysyms.extend(special_aliases[part])
        else:
            # General key names: letters, digits, punctuation, function keys, etc.
            keysyms.extend([part, part.upper(), part.capitalize()])

        keycodes = set()
        for keysym_str in keysyms:
            keysym = XK.string_to_keysym(keysym_str)
            if keysym:
                keycode = self.display.keysym_to_keycode(keysym)
                if keycode:
                    keycodes.add(keycode)
        return keycodes

class WindowsKeyboardController:
    def __init__(self, hotkey_str):
        self.hotkey_str = hotkey_str.lower()

    def is_hotkey_pressed(self) -> bool:
        try:
            return keyboard.is_pressed(self.hotkey_str)
        except ImportError:
            logger.critical("FATAL: The 'keyboard' library failed to import a backend. This often means it needs to be run with administrator/sudo privileges.")
            sys.exit(1)
        except Exception:
            return False

    def is_key_pressed(self, key_str: str) -> bool:
        try:
            return keyboard.is_pressed(key_str)
        except:
            return False

class MacOSKeyboardController:
    def __init__(self, hotkey_str):
        self.hotkey_str = hotkey_str.lower()
        self._setup_keycodes()

    def _setup_keycodes(self):
        # Map common hotkey strings to macOS key codes
        key_mapping = {
            'shift': [56, 60],  # Left and Right Shift
            'ctrl': [59, 62],   # Left and Right Control
            'alt': [58, 61],    # Left and Right Option/Alt
            'cmd': [55, 54],    # Left and Right Command
        }
        self.keycodes_to_check = key_mapping.get(self.hotkey_str, [])
        if not self.keycodes_to_check:
            logger.critical(f"Unsupported hotkey '{self.hotkey_str}' for macOS. Use 'shift', 'ctrl', 'alt', or 'cmd'.")
            sys.exit(1)

    def is_hotkey_pressed(self) -> bool:
        try:
            # Get current modifier flags
            flags = NSEvent.modifierFlags()

            # Check if any of our target keys are pressed
            if self.hotkey_str == 'shift':
                return bool(flags & (1 << 17) or flags & (1 << 18))  # NSShiftKeyMask
            elif self.hotkey_str == 'ctrl':
                return bool(flags & (1 << 12))  # NSControlKeyMask
            elif self.hotkey_str == 'alt':
                return bool(flags & (1 << 19))  # NSAlternateKeyMask
            elif self.hotkey_str == 'cmd':
                return bool(flags & (1 << 20))  # NSCommandKeyMask
            return False
        except Exception as e:
            logger.warning(f"Error checking hotkey state: {e}")
            return False

    def is_key_pressed(self, key_str: str) -> bool:
        # Basic implementation for macOS
        return False

class InputLoop(threading.Thread):
    def __init__(self, shared_state):
        super().__init__(daemon=True, name="InputLoop")
        self.shared_state = shared_state
        self.mouse_controller = mouse.Controller()
        self._last_hit_scan_trigger_time = 0.0
        self._hit_scan_min_interval_seconds = 0.03

        self.hotkey_str = config.hotkey.lower()
        if IS_LINUX:
            self.keyboard_controller = LinuxX11KeyboardController(self.hotkey_str)
        elif IS_MACOS:
            self.keyboard_controller = MacOSKeyboardController(self.hotkey_str)
        else: # IS_WINDOWS
            self.keyboard_controller = WindowsKeyboardController(self.hotkey_str)

        self.started_auto_mode = False

        self.scroll_dy = 0
        self.scroll_lock = threading.Lock()
        
        # Track mouse button states
        self.mouse_buttons_pressed = set()
        self.mouse_button_lock = threading.Lock()
        
        # Start mouse listener for scroll and click events
        self.mouse_listener = mouse.Listener(
            on_scroll=self.on_scroll,
            on_click=self.on_click
        )
        self.mouse_listener.start()

    def on_click(self, x, y, button, pressed):
        with self.mouse_button_lock:
            if pressed:
                self.mouse_buttons_pressed.add(button)
            else:
                self.mouse_buttons_pressed.discard(button)

    def on_scroll(self, x, y, dx, dy):
        with self.scroll_lock:
            self.scroll_dy += dy

    def get_and_reset_scroll_delta(self):
        with self.scroll_lock:
            delta = self.scroll_dy
            self.scroll_dy = 0
        return delta


    def run(self):
        logger.debug("Input thread started.")
        last_mouse_pos = (0, 0)
        hotkey_was_pressed = False

        while self.shared_state.running:
            if not config.is_enabled:
                time.sleep(0.1)
                continue
            try:
                current_mouse_pos = self.mouse_controller.position
                current_mouse_pos = (int(current_mouse_pos[0]), int(current_mouse_pos[1]))
                try:
                    hotkey_is_pressed = self.keyboard_controller.is_hotkey_pressed()
                except Exception:
                    hotkey_is_pressed = False

                lookup_active = hotkey_is_pressed or (
                    config.auto_scan_mode and config.auto_scan_mode_lookups_without_hotkey
                )

                # trigger screenshots + ocr in manual mode
                if hotkey_is_pressed and not hotkey_was_pressed and not config.auto_scan_mode:
                    logger.info(f"Input: Hotkey '{config.hotkey}' pressed. Triggering screenshot.")
                    self.shared_state.screenshot_trigger_event.set()

                # trigger initial screenshots + ocr in auto mode
                if not self.started_auto_mode and config.auto_scan_mode:
                    self.shared_state.screenshot_trigger_event.set()
                self.started_auto_mode = config.auto_scan_mode

                # trigger hit_scans + lookups
                if current_mouse_pos != last_mouse_pos and lookup_active:
                    if config.auto_scan_mode and getattr(config, 'auto_scan_on_mouse_move', False):
                        self.shared_state.screenshot_trigger_event.set()
                    now = time.perf_counter()
                    if (now - self._last_hit_scan_trigger_time) >= self._hit_scan_min_interval_seconds:
                        # Skip hit scan if popup is locked (the Lookup thread will double-check anyway)
                        if not self.shared_state.popup_locked_on_result:
                            self.shared_state.hit_scan_queue.put((False, None))
                            self._last_hit_scan_trigger_time = now

                if hotkey_was_pressed and not hotkey_is_pressed:
                    logger.info(f"Input: Hotkey '{config.hotkey}' released.")

                last_mouse_pos = current_mouse_pos
                hotkey_was_pressed = hotkey_is_pressed
                self.hotkey_is_pressed = hotkey_is_pressed
            except:
                logger.exception("An unexpected error occurred in the input loop. Continuing...")
            finally:
                time.sleep(0.02)
        logger.debug("Input thread stopped.")

    def is_virtual_hotkey_down(self):
        return self.keyboard_controller.is_hotkey_pressed() or (
                config.auto_scan_mode and config.auto_scan_mode_lookups_without_hotkey)

    def is_key_pressed(self, key_str: str) -> bool:
        key_lower = key_str.lower()

        # Resolve optional side-button enums across pynput backends.
        x1_button = getattr(mouse.Button, 'x1', None) or getattr(mouse.Button, 'button8', None)
        x2_button = getattr(mouse.Button, 'x2', None) or getattr(mouse.Button, 'button9', None)
        if x1_button is None:
            try:
                x1_button = mouse.Button(8)
            except Exception:
                x1_button = None
        if x2_button is None:
            try:
                x2_button = mouse.Button(9)
            except Exception:
                x2_button = None
        
        # Check for mouse button shortcuts (e.g., "mouse4", "mouse5", "xbutton1", "xbutton2")
        mouse_button_map = {
            'rightmouse': mouse.Button.right,
            'mouse2': mouse.Button.right,
            'middlemouse': mouse.Button.middle,
            'mouse3': mouse.Button.middle,
        }
        if x1_button is not None:
            mouse_button_map['mouse4'] = x1_button
            mouse_button_map['xbutton1'] = x1_button
        if x2_button is not None:
            mouse_button_map['mouse5'] = x2_button
            mouse_button_map['xbutton2'] = x2_button
        
        if key_lower in mouse_button_map:
            with self.mouse_button_lock:
                return mouse_button_map[key_lower] in self.mouse_buttons_pressed

        if IS_LINUX and IS_WAYLAND and not self._is_wayland_keyboard_shortcut_supported(key_lower):
            return False

        # Otherwise, fall back to keyboard check
        keyboard_pressed = self.keyboard_controller.is_key_pressed(key_str)
        if keyboard_pressed:
            return True

        return False

    def is_mouse_button_pressed(self, button_name: str) -> bool:
        button_lower = button_name.lower()

        x1_button = getattr(mouse.Button, 'x1', None) or getattr(mouse.Button, 'button8', None)
        x2_button = getattr(mouse.Button, 'x2', None) or getattr(mouse.Button, 'button9', None)
        if x1_button is None:
            try:
                x1_button = mouse.Button(8)
            except Exception:
                x1_button = None
        if x2_button is None:
            try:
                x2_button = mouse.Button(9)
            except Exception:
                x2_button = None

        mouse_button_map = {
            'rightmouse': mouse.Button.right,
            'mouse2': mouse.Button.right,
            'middlemouse': mouse.Button.middle,
            'mouse3': mouse.Button.middle,
        }
        if x1_button is not None:
            mouse_button_map['mouse4'] = x1_button
            mouse_button_map['xbutton1'] = x1_button
        if x2_button is not None:
            mouse_button_map['mouse5'] = x2_button
            mouse_button_map['xbutton2'] = x2_button

        button = mouse_button_map.get(button_lower)
        if button is None:
            return False

        with self.mouse_button_lock:
            return button in self.mouse_buttons_pressed

    @staticmethod
    def _is_wayland_keyboard_shortcut_supported(key_lower: str) -> bool:
        return key_lower in {'shift', 'ctrl', 'control', 'alt'}

    def reapply_settings(self):
        logger.debug(f"InputLoop: Re-applying settings. New hotkey: '{config.hotkey}'.")
        self.hotkey_str = config.hotkey.lower()
        if IS_LINUX:
            self.keyboard_controller = LinuxX11KeyboardController(self.hotkey_str)
        elif IS_MACOS:
            self.keyboard_controller = MacOSKeyboardController(self.hotkey_str)
        else: # IS_WINDOWS
            self.keyboard_controller = WindowsKeyboardController(self.hotkey_str)

    @staticmethod
    def get_mouse_pos():
        with mouse.Controller() as mc:
            pos = mc.position
            # Convert floats to integers for QPoint compatibility
            return (int(pos[0]), int(pos[1]))
