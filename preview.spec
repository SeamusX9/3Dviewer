# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the 3D preview tool."""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None
site = Path(sys.prefix) / "Lib" / "site-packages"

datas = [("icon.ico", ".")]
binaries = []
hiddenimports = [
    "loader",
    "assimp_py",
    "pyvistaqt",
    "vtkmodules",
    "vtkmodules.qt.QVTKRenderWindowInteractor",
    "vtkmodules.all",
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",
    "openskp",
    "openskp.export",
    "openskp.export.glb",
    "trimesh",
    "shapely",
    "PIL",
    "PIL.Image",
    "mapbox_earcut",
    "defusedxml",
]

for package in ("vtkmodules", "pyvista", "pyvistaqt", "openskp", "trimesh", "assimp_py", "shapely"):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hidden

hiddenimports += collect_submodules("vtkmodules")
hiddenimports += collect_submodules("openskp")
hiddenimports += collect_submodules("trimesh")

for libs_name in ("vtk.libs", "numpy.libs", "shapely.libs", "mapbox_earcut.libs"):
    libs_dir = site / libs_name
    if not libs_dir.is_dir():
        continue
    for dll in libs_dir.glob("*.dll"):
        binaries.append((str(dll), libs_name))

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "IPython", "notebook"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="3D模型预览",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="icon.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="3D模型预览",
)
