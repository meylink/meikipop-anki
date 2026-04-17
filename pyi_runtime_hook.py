"""
PyInstaller runtime hook to disable gi.overrides for Wayland backend initialization.
This hook runs before any user code imports gi, preventing the broken override assertion.
"""
import os
import sys

# Disable gi.overrides to prevent unix_signal_add_full assertion error
os.environ['GI_OVERRIDES_PATH'] = '/nonexistent'
