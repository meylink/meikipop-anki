import sys
import logging

logger = logging.getLogger(__name__)


def _get_x11_active_window():
    try:
        from Xlib import display as xlib_display
        from Xlib import Xatom
    except Exception:
        return None

    try:
        display = xlib_display.Display()
        root = display.screen().root
        active_window_atom = display.intern_atom('_NET_ACTIVE_WINDOW')
        active_window_prop = root.get_full_property(active_window_atom, Xatom.WINDOW)
        if not active_window_prop or not active_window_prop.value:
            return None
        return display.create_resource_object('window', active_window_prop.value[0])
    except Exception as e:
        logger.debug(f'Failed to query active X11 window: {e}')
        return None

def get_active_window_title():
    """Returns the title of the active window. Windows only implementation for now."""
    if sys.platform == 'win32':
        try:
            import ctypes
            from ctypes import wintypes
            
            user32 = ctypes.windll.user32
            
            # Get handle to active window
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return ""
            
            # Get length of title
            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return ""
            
            # Create buffer and get title
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            
            title = buff.value
            
            # Clean up browser suffixes to return only the tab title
            browser_suffixes = [
                " - Google Chrome",
                " - Mozilla Firefox",
                " - Microsoft Edge",
                " - Brave",
                " - Vivaldi",
                " - Opera",
                " - Internet Explorer"
            ]
            
            for suffix in browser_suffixes:
                if title.endswith(suffix):
                    title = title[:-len(suffix)]
                    break
            
            return title
        except Exception as e:
            logger.error(f"Failed to get window title: {e}")
            return ""
    else:
        # TODO: Linux/macOS implementations
        return ""


def is_active_window_fullscreen():
    """Return True if the currently active X11/XWayland window is fullscreen."""
    if sys.platform.startswith('win'):
        return False

    try:
        window = _get_x11_active_window()
        if window is None:
            return False

        display = window.display
        net_wm_state = display.intern_atom('_NET_WM_STATE')
        net_wm_state_fullscreen = display.intern_atom('_NET_WM_STATE_FULLSCREEN')
        state_prop = window.get_full_property(net_wm_state, 0)
        if not state_prop or not state_prop.value:
            return False

        return net_wm_state_fullscreen in state_prop.value
    except Exception as e:
        logger.debug(f'Failed to query fullscreen state: {e}')
        return False
