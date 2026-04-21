"""
Local PyInstaller hook for scipy.special._ufuncs.

SciPy 1.17.x ships _special_ufuncs but not _cdflib in this environment, so
we keep the proven hidden import and skip the nonexistent one to avoid noisy
build-time warnings.
"""

from PyInstaller.utils.hooks import is_module_satisfies


hiddenimports = ["scipy.special._ufuncs_cxx"]

if is_module_satisfies("scipy >= 1.14.0"):
    hiddenimports += ["scipy.special._special_ufuncs"]
