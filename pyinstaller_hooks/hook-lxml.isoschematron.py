"""
Local PyInstaller hook for lxml.isoschematron.

Jinja2 is an optional dependency for schema-generation paths that this app
does not use, so exclude it to keep packaging noise down while still
collecting the required lxml resource files.
"""

import os

from PyInstaller.utils.hooks import collect_data_files


datas = collect_data_files("lxml", subdir=os.path.join("isoschematron", "resources"))
excludedimports = ["jinja2"]
