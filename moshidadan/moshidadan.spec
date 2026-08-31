# -*- mode: python ; coding: utf-8 -*-

"""
PyInstaller 打包配置
用法: pyinstaller moshidadan.spec
输出: dist/产地快打_<version>.exe (单文件 GUI)
"""

import json
import os
import sys

_icon = 'icon.ico' if os.path.exists('icon.ico') else None

# 从通用配置读取应用名和版本号，产物名随版本号自动同步
_APP_CONFIG = {}
try:
    with open('app_config.json', encoding='utf-8') as _f:
        _APP_CONFIG = json.load(_f)
except Exception:
    pass

_EXE_NAME = "{}_{}".format(
    _APP_CONFIG.get('app_name', '产地快打'),
    _APP_CONFIG.get('version', 'v1.0.1'),
)


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('app_config.json', '.')],
    hiddenimports=[
        'tkinter',
        'tkinter.ttk',
        'tkinter.messagebox',
        'tkinter.filedialog',
        'threading',
        'ctypes',
        'ctypes.wintypes',
        'json',
        'hook_engine',
        'overlay',
        'parser',
        'address_parser',
        'clipboard_safe',
        'clipboard_monitor',
        'clipboard_worker',
        'single_instance',
        'excel_exporter',
        'config_manager',
        'logger',
        'crash_handler',
        'paths',
        'template_manager',
        'openpyxl',
        'xlrd',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'numpy', 'pandas', 'PIL', 'cv2', 'scipy',
        'IPython', 'jupyter',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=_EXE_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon,
)
