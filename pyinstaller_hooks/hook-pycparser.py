"""
Local PyInstaller hook for pycparser.

The stock hook asks for generated parser tables that are not present in the
wheel we ship. pycparser can regenerate them if ever needed, and this app
does not exercise that path at runtime.
"""

hiddenimports = []
